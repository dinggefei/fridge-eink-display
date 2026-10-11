from __future__ import annotations

import base64
import json
import logging
import re
from time import perf_counter
from abc import ABC, abstractmethod
from datetime import date, timedelta
from decimal import Decimal
from typing import Any, Literal
from uuid import uuid4

import httpx
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

from app.domain.inventory import StorageLocation
from app.settings import get_settings


logger = logging.getLogger("uvicorn.error.recognition")


ActionType = Literal["add", "consume", "discard", "edit"]
QueryType = Literal[
    "named_quantity",
    "location_items",
    "expiring_soon",
    "due_today",
    "overdue",
]


class InventoryCandidate(BaseModel):
    id: str
    name: str
    quantity: Decimal
    unit: str
    location: StorageLocation
    stocked_on: date
    suggested_use_by: date | None = None


class RecognitionAction(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    action_id: str = Field(default_factory=lambda: str(uuid4()))
    type: ActionType
    name: str = Field(min_length=1, max_length=200)
    quantity: Decimal | None = Field(
        default=None,
        gt=0,
        max_digits=12,
        decimal_places=3,
    )
    unit: str | None = Field(default=None, min_length=1, max_length=20)
    location: StorageLocation | None = None
    stocked_on: date | None = None
    suggested_use_by: date | None = None
    target_batch_id: str | None = None
    confidence: float = Field(default=0.8, ge=0, le=1)
    needs_confirmation: bool = False
    note: str | None = Field(default=None, max_length=300)
    source_image_index: int | None = Field(default=None, ge=0, le=8)
    specification: str | None = Field(default=None, max_length=100)

    @field_validator("location", mode="before")
    @classmethod
    def normalize_location(cls, value: Any) -> Any:
        aliases = {
            "冷藏": StorageLocation.REFRIGERATED,
            "冷冻": StorageLocation.FROZEN,
            "常温": StorageLocation.ROOM_TEMPERATURE,
        }
        return aliases.get(value, value)

    @model_validator(mode="after")
    def validate_fields_for_action(self) -> "RecognitionAction":
        if self.type in {"add", "consume", "discard"}:
            if self.quantity is None or self.unit is None:
                raise ValueError(f"{self.type} requires quantity and unit")
        elif not any(
            value is not None
            for value in (
                self.quantity,
                self.unit,
                self.location,
                self.stocked_on,
                self.suggested_use_by,
            )
        ):
            raise ValueError("edit requires at least one changed field")
        return self


class RecognitionQuery(BaseModel):
    query_id: str = Field(default_factory=lambda: str(uuid4()))
    type: QueryType
    name: str | None = Field(default=None, max_length=200)
    location: StorageLocation | None = None
    days: int = Field(default=3, ge=1, le=30)


class RecognitionQueryItem(BaseModel):
    id: str
    name: str
    quantity: Decimal
    unit: str
    location: StorageLocation
    suggested_use_by: date | None
    days_remaining: int | None


class RecognitionQueryResult(BaseModel):
    query_id: str
    type: QueryType
    title: str
    items: list[RecognitionQueryItem] = Field(default_factory=list)


class RecognitionResult(BaseModel):
    actions: list[RecognitionAction] = Field(default_factory=list, max_length=100)
    queries: list[RecognitionQuery] = Field(default_factory=list, max_length=20)
    query_results: list[RecognitionQueryResult] = Field(
        default_factory=list,
        max_length=20,
    )
    warnings: list[str] = Field(default_factory=list, max_length=30)


class RecognitionProviderError(RuntimeError):
    pass


class RecognitionProvider(ABC):
    @abstractmethod
    async def parse_quick_entry(
        self,
        text: str,
        inventory: list[InventoryCandidate],
    ) -> RecognitionResult:
        raise NotImplementedError

    @abstractmethod
    async def recognize_order_image(
        self,
        *,
        image_bytes: bytes,
        content_type: str,
        image_index: int,
    ) -> RecognitionResult:
        raise NotImplementedError


_NUMBER_WORDS = {
    "半": Decimal("0.5"),
    "一": Decimal("1"),
    "两": Decimal("2"),
    "二": Decimal("2"),
    "三": Decimal("3"),
    "四": Decimal("4"),
    "五": Decimal("5"),
    "六": Decimal("6"),
    "七": Decimal("7"),
    "八": Decimal("8"),
    "九": Decimal("9"),
    "十": Decimal("10"),
}
_ITEM_PATTERN = re.compile(
    r"(?P<number>\d+(?:\.\d+)?|半|一|两|二|三|四|五|六|七|八|九|十)"
    r"\s*(?P<unit>盒|袋|瓶|份|斤|克|公斤|千克|个|包|根|颗)"
    r"\s*(?P<name>.+?)(?=(?:和|、)?(?:\d+(?:\.\d+)?|半|一|两|二|三|四|五|六|七|八|九|十)"
    r"\s*(?:盒|袋|瓶|份|斤|克|公斤|千克|个|包|根|颗)|$)"
)
_FULL_OPERATION_PATTERN = re.compile(
    r"^(?:我)?(?:把)?(?P<name>.+?)"
    r"(?P<verb>喝完了|吃完了|用完了|消耗完了|喝光了|吃光了|用光了|"
    r"坏了|坏掉了|扔掉了|丢掉了|不要了)$"
)


def _decimal_number(raw: str) -> Decimal:
    if raw in _NUMBER_WORDS:
        return _NUMBER_WORDS[raw]
    return Decimal(raw)


def _suggest_location(name: str) -> StorageLocation:
    frozen_words = ("冻", "冰淇淋", "雪糕", "水饺", "丸")
    room_words = ("纸巾", "洗衣", "牙膏", "米", "面粉", "盐")
    if any(word in name for word in frozen_words):
        return StorageLocation.FROZEN
    if any(word in name for word in room_words):
        return StorageLocation.ROOM_TEMPERATURE
    return StorageLocation.REFRIGERATED


def _suggest_use_by(
    stocked_on: date,
    location: StorageLocation,
) -> date:
    days = {
        StorageLocation.REFRIGERATED: 3,
        StorageLocation.FROZEN: 30,
        StorageLocation.ROOM_TEMPERATURE: 7,
    }[location]
    return stocked_on + timedelta(days=days)


def parse_full_inventory_entry(
    text: str,
    inventory: list[InventoryCandidate],
) -> RecognitionResult | None:
    """Resolve explicit consume-all/discard-all phrases without model guessing."""
    clauses = [
        clause.strip()
        for clause in re.split(r"[,，。；;]", text)
        if clause.strip()
    ]
    if not clauses:
        return None
    matches = [_FULL_OPERATION_PATTERN.fullmatch(clause) for clause in clauses]
    if any(match is None for match in matches):
        return None

    actions: list[RecognitionAction] = []
    warnings: list[str] = []
    discard_verbs = {"坏了", "坏掉了", "扔掉了", "丢掉了", "不要了"}
    for match in matches:
        assert match is not None
        name = match.group("name").strip(" 的")
        candidates = [item for item in inventory if item.name == name]
        if not candidates:
            warnings.append(f"库存中没有找到“{name}”。")
            continue
        units = {item.unit for item in candidates}
        if len(units) != 1:
            warnings.append(
                f"“{name}”存在多个计量单位，请明确要处理的数量。"
            )
            continue
        action_type: ActionType = (
            "discard" if match.group("verb") in discard_verbs else "consume"
        )
        actions.append(
            RecognitionAction(
                type=action_type,
                name=name,
                quantity=sum(
                    (item.quantity for item in candidates),
                    Decimal("0"),
                ),
                unit=next(iter(units)),
                target_batch_id=candidates[0].id,
                confidence=0.99,
                needs_confirmation=False,
                note=(
                    "按当前库存全部丢弃"
                    if action_type == "discard"
                    else "按当前库存全部消耗"
                ),
            )
        )
    return RecognitionResult(actions=actions, warnings=warnings)


class MockRecognitionProvider(RecognitionProvider):
    """Deterministic development provider; never calls an external service."""

    async def parse_quick_entry(
        self,
        text: str,
        inventory: list[InventoryCandidate],
    ) -> RecognitionResult:
        full_result = parse_full_inventory_entry(text, inventory)
        if full_result is not None:
            return full_result
        actions: list[RecognitionAction] = []
        queries: list[RecognitionQuery] = []
        clauses = re.split(r"[,，。；;]", text)
        inherited_type: ActionType = "add"
        for clause in clauses:
            clause = clause.strip()
            if not clause:
                continue
            if "今天到期" in clause or "今天要到期" in clause:
                queries.append(RecognitionQuery(type="due_today"))
                continue
            if "过期" in clause and not any(
                word in clause for word in ("快过期", "临期")
            ):
                queries.append(RecognitionQuery(type="overdue"))
                continue
            if any(word in clause for word in ("快过期", "临期", "快到期")):
                queries.append(RecognitionQuery(type="expiring_soon"))
                continue
            location_query = next(
                (
                    (word, location)
                    for word, location in (
                        ("冷藏", StorageLocation.REFRIGERATED),
                        ("冷冻", StorageLocation.FROZEN),
                        ("常温", StorageLocation.ROOM_TEMPERATURE),
                    )
                    if word in clause
                    and any(
                        query_word in clause
                        for query_word in ("有什么", "有哪些", "都有什么")
                    )
                ),
                None,
            )
            if location_query:
                queries.append(
                    RecognitionQuery(
                        type="location_items",
                        location=location_query[1],
                    )
                )
                continue
            quantity_query = re.search(
                r"(?:还有|有)?(?P<name>.+?)(?:还有)?(?:多少|几)(?:个|盒|袋|瓶|份)?",
                clause,
            )
            if quantity_query and any(
                word in clause for word in ("多少", "几个", "几盒", "几袋", "几瓶")
            ):
                name = quantity_query.group("name").strip("冰箱里中的 ")
                queries.append(
                    RecognitionQuery(type="named_quantity", name=name)
                )
                continue

            edit_match = re.search(
                r"(?:把)?(?P<name>.+?)(?:的)?数量改(?:成|为)"
                r"(?P<number>\d+(?:\.\d+)?)\s*"
                r"(?P<unit>盒|袋|瓶|份|斤|克|公斤|千克|个|包|根|颗)?$",
                clause,
            )
            if edit_match:
                name = edit_match.group("name").strip()
                target_matches = [item for item in inventory if item.name == name]
                target = target_matches[0] if len(target_matches) == 1 else None
                actions.append(
                    RecognitionAction(
                        type="edit",
                        name=name,
                        quantity=Decimal(edit_match.group("number")),
                        unit=(
                            edit_match.group("unit")
                            or (target.unit if target else None)
                        ),
                        target_batch_id=target.id if target else None,
                        needs_confirmation=target is None,
                        confidence=0.9,
                    )
                )
                continue
            unit_edit = re.search(
                r"(?:把)?(?P<name>.+?)(?:的)?单位改(?:成|为)"
                r"(?P<unit>盒|袋|瓶|份|斤|克|公斤|千克|个|包|根|颗)$",
                clause,
            )
            if unit_edit:
                name = unit_edit.group("name").strip()
                target_matches = [item for item in inventory if item.name == name]
                target = target_matches[0] if len(target_matches) == 1 else None
                actions.append(
                    RecognitionAction(
                        type="edit",
                        name=name,
                        unit=unit_edit.group("unit"),
                        target_batch_id=target.id if target else None,
                        needs_confirmation=target is None,
                        confidence=0.9,
                    )
                )
                continue
            date_edit = re.search(
                r"(?:把)?(?P<name>.+?)(?:的)?"
                r"(?P<field>入库日期|建议食用日期)"
                r"改(?:成|为)(?P<date>\d{4}-\d{2}-\d{2})$",
                clause,
            )
            if date_edit:
                name = date_edit.group("name").strip()
                target_matches = [item for item in inventory if item.name == name]
                target = target_matches[0] if len(target_matches) == 1 else None
                changed_date = date.fromisoformat(date_edit.group("date"))
                actions.append(
                    RecognitionAction(
                        type="edit",
                        name=name,
                        stocked_on=(
                            changed_date
                            if date_edit.group("field") == "入库日期"
                            else None
                        ),
                        suggested_use_by=(
                            changed_date
                            if date_edit.group("field") == "建议食用日期"
                            else None
                        ),
                        target_batch_id=target.id if target else None,
                        needs_confirmation=target is None,
                        confidence=0.9,
                    )
                )
                continue
            location_edit = re.search(
                r"(?:把)?(?P<name>.+?)(?:的)?(?:储存位置|位置)?"
                r"(?:放到|移到|改为)"
                r"(?P<location>冷藏|冷冻|常温)$",
                clause,
            )
            if location_edit:
                name = location_edit.group("name").strip()
                target_matches = [item for item in inventory if item.name == name]
                target = target_matches[0] if len(target_matches) == 1 else None
                actions.append(
                    RecognitionAction(
                        type="edit",
                        name=name,
                        location=location_edit.group("location"),
                        target_batch_id=target.id if target else None,
                        needs_confirmation=target is None,
                        confidence=0.9,
                    )
                )
                continue

            action_type: ActionType = inherited_type
            if any(word in clause for word in ("扔", "丢", "坏了", "坏掉")):
                action_type = "discard"
            elif any(word in clause for word in ("吃", "喝", "用掉", "消耗")):
                action_type = "consume"
            elif any(word in clause for word in ("买", "新增", "放入", "加")):
                action_type = "add"
            inherited_type = action_type

            cleaned = re.sub(
                r"^(今天|刚刚|刚才)?(买了|新增了?|放入了?|加了?|"
                r"吃了|喝了|用掉了?|消耗了?|扔了|丢了)",
                "",
                clause,
            )
            matches = list(_ITEM_PATTERN.finditer(cleaned))
            if not matches:
                continue
            for match in matches:
                name = match.group("name").strip(" 和、的")
                quantity = _decimal_number(match.group("number"))
                unit = match.group("unit")
                location = _suggest_location(name)
                target = None
                if action_type != "add":
                    matches_inventory = [
                        item for item in inventory if item.name == name
                    ]
                    if len(matches_inventory) == 1:
                        target = matches_inventory[0].id
                actions.append(
                    RecognitionAction(
                        type=action_type,
                        name=name,
                        quantity=quantity,
                        unit=unit,
                        location=location if action_type == "add" else None,
                        stocked_on=date.today() if action_type == "add" else None,
                        suggested_use_by=(
                            _suggest_use_by(date.today(), location)
                            if action_type == "add"
                            else None
                        ),
                        target_batch_id=target,
                        needs_confirmation=(
                            action_type != "add" and target is None
                        ),
                        confidence=0.85,
                    )
                )
        warnings = []
        if not actions and not queries:
            warnings.append("没有识别到明确的食材和数量，请换一种说法。")
        return RecognitionResult(
            actions=actions,
            queries=queries,
            warnings=warnings,
        )

    async def recognize_order_image(
        self,
        *,
        image_bytes: bytes,
        content_type: str,
        image_index: int,
    ) -> RecognitionResult:
        del image_bytes, content_type
        stocked_on = date.today()
        return RecognitionResult(
            actions=[
                RecognitionAction(
                    type="add",
                    name=f"识别测试牛奶{image_index + 1}",
                    quantity=Decimal("1"),
                    unit="盒",
                    location=StorageLocation.REFRIGERATED,
                    stocked_on=stocked_on,
                    suggested_use_by=stocked_on + timedelta(days=3),
                    confidence=0.99,
                    source_image_index=image_index,
                )
            ]
        )


class HunyuanRecognitionProvider(RecognitionProvider):
    def __init__(self) -> None:
        settings = get_settings()
        self.api_key = settings.hunyuan_api_key.get_secret_value()
        self.endpoint = (
            f"{settings.hunyuan_base_url.rstrip('/')}/chat/completions"
        )
        self.text_model = settings.hunyuan_text_model
        self.vision_model = settings.hunyuan_vision_model
        self.timeout = settings.hunyuan_timeout_seconds

    async def _complete(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
    ) -> str:
        started_at = perf_counter()
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    self.endpoint,
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": model,
                        "messages": messages,
                        "temperature": 0,
                        "stream": False,
                    },
                )
                response.raise_for_status()
        except httpx.HTTPError as error:
            logger.warning(
                "recognition_provider_failed model=%s duration_ms=%.1f",
                model,
                (perf_counter() - started_at) * 1000,
            )
            raise RecognitionProviderError(
                f"recognition provider request failed: {error}"
            ) from error
        logger.info(
            "recognition_provider_completed model=%s duration_ms=%.1f",
            model,
            (perf_counter() - started_at) * 1000,
        )
        payload = response.json()
        try:
            return payload["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as error:
            raise RecognitionProviderError(
                "recognition provider returned an unexpected response"
            ) from error

    @staticmethod
    def _parse_json(content: str) -> RecognitionResult:
        started_at = perf_counter()
        cleaned = content.strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
            cleaned = re.sub(r"\s*```$", "", cleaned)
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start < 0 or end < start:
            raise RecognitionProviderError(
                "recognition provider did not return JSON"
            )
        try:
            result = RecognitionResult.model_validate_json(
                cleaned[start : end + 1]
            )
        except ValidationError as error:
            raise RecognitionProviderError(
                "recognition provider returned invalid structured data"
            ) from error
        logger.info(
            "recognition_json_parsed duration_ms=%.1f actions=%d",
            (perf_counter() - started_at) * 1000,
            len(result.actions),
        )
        return result

    async def parse_quick_entry(
        self,
        text: str,
        inventory: list[InventoryCandidate],
    ) -> RecognitionResult:
        inventory_json = json.dumps(
            [
                {
                    **item.model_dump(mode="json"),
                    "quantity": str(item.quantity),
                }
                for item in inventory
            ],
            ensure_ascii=False,
        )
        prompt = f"""
你是冰箱库存操作解析器。只输出 JSON，不要输出 Markdown。
写操作 type 支持 add、consume、discard、edit。查询 type 支持
named_quantity、location_items、expiring_soon、due_today、overdue。
严禁直接执行写操作。
输出结构：
{{"actions":[{{"type":"add","name":"牛奶","quantity":"2","unit":"盒",
"location":"refrigerated","stocked_on":"{date.today().isoformat()}",
"suggested_use_by":"{(date.today() + timedelta(days=3)).isoformat()}",
"target_batch_id":null,"confidence":0.9,"needs_confirmation":false,
"note":null}}],
"queries":[{{"type":"named_quantity","name":"牛奶","location":null,"days":3}}],
"query_results":[],"warnings":[]}}
location 只能是 refrigerated、frozen、room_temperature。
新增操作填写位置、入库日期和建议食用日期。
消耗或丢弃操作只能从下方库存选择真实 target_batch_id；不能唯一匹配时
target_batch_id 为 null 且 needs_confirmation 为 true。
用户说“喝完了、吃完了、用完了、喝光了”等且没有给数量时，表示 consume
当前同名同单位库存的全部数量；“坏了、扔掉了、丢掉了、不要了”表示 discard
当前同名同单位库存的全部数量。仍然必须返回确认卡片，不能直接执行。
修改操作必须选择真实 target_batch_id，只输出用户明确要求修改的字段；
可修改 quantity、unit、location、stocked_on、suggested_use_by。
查询只填写 queries，不能伪造成写操作。查询不修改库存。
用户输入：{text}
当前库存：{inventory_json}
""".strip()
        content = await self._complete(
            model=self.text_model,
            messages=[{"role": "user", "content": prompt}],
        )
        return self._parse_json(content)

    async def recognize_order_image(
        self,
        *,
        image_bytes: bytes,
        content_type: str,
        image_index: int,
    ) -> RecognitionResult:
        data_url = (
            f"data:{content_type};base64,"
            f"{base64.b64encode(image_bytes).decode('ascii')}"
        )
        prompt = f"""
识别这张生鲜或商超订单截图中的商品。只输出 JSON，不要输出 Markdown。
过滤订单号、地址、姓名、电话、配送费、包装费、优惠、支付信息和营销文案。
每个实际商品输出一个 add 操作，不要把规格数字误认为购买数量。
无法确定时保留商品并设置 needs_confirmation=true。
日期、图片序号、目标库存和备注由后端补齐，不要输出这些字段。
输出结构：
{{"actions":[{{"type":"add","name":"商品通用名称",
"specification":"原图规格","quantity":"1","unit":"份",
"location":"refrigerated","confidence":0.8,
"needs_confirmation":false}}],"warnings":[]}}
location 只能是 refrigerated、frozen、room_temperature。
非食品不要输出。常温食品可以输出，但 location 使用 room_temperature。
""".strip()
        content = await self._complete(
            model=self.vision_model,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {"url": data_url},
                        },
                    ],
                }
            ],
        )
        result = self._parse_json(content)
        stocked_on = date.today()
        for action in result.actions:
            action.source_image_index = image_index
            action.type = "add"
            action.location = (
                action.location or StorageLocation.REFRIGERATED
            )
            action.stocked_on = stocked_on
            action.suggested_use_by = _suggest_use_by(
                stocked_on,
                action.location,
            )
            action.target_batch_id = None
        return result


def get_recognition_provider() -> RecognitionProvider:
    if get_settings().recognition_provider == "hunyuan":
        return HunyuanRecognitionProvider()
    return MockRecognitionProvider()


def merge_order_results(
    results: list[RecognitionResult],
) -> RecognitionResult:
    """Drop exact adjacent-image duplicates while preserving real repeat buys."""
    actions: list[RecognitionAction] = []
    warnings: list[str] = []
    seen_previous_page: dict[str, int] = {}
    for result in results:
        warnings.extend(result.warnings)
        current_page: dict[str, int] = {}
        for action in result.actions:
            fingerprint = "|".join(
                [
                    re.sub(r"\s+", "", action.name).lower(),
                    re.sub(r"\s+", "", action.specification or "").lower(),
                    str(action.quantity.normalize()),
                    action.unit,
                ]
            )
            image_index = action.source_image_index or 0
            if (
                fingerprint in seen_previous_page
                and seen_previous_page[fingerprint] == image_index - 1
            ):
                continue
            actions.append(action)
            current_page[fingerprint] = image_index
        seen_previous_page = current_page
    return RecognitionResult(actions=actions, warnings=warnings)
