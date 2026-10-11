from __future__ import annotations

import asyncio
from datetime import date, timedelta
from decimal import Decimal
from io import BytesIO
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.base import Base
from app.db.session import get_db_session
from app.main import app
from app.services.inventory_store import get_inventory_store
from app.services.recognition import (
    HunyuanRecognitionProvider,
    RecognitionAction,
    RecognitionResult,
    merge_order_results,
)
from app.settings import get_settings
from app.services.wechat_login import WechatIdentity


@pytest.fixture
def recognition_client(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    monkeypatch.setenv(
        "AUTH_TOKEN_SECRET",
        "test-secret-with-at-least-thirty-two-characters",
    )
    monkeypatch.setenv("ALLOW_DEV_LOGIN", "true")
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("RECOGNITION_PROVIDER", "mock")
    monkeypatch.setenv("RECOGNITION_EXECUTION_MODE", "inline")
    monkeypatch.setenv(
        "RECOGNITION_UPLOAD_DIR",
        str(tmp_path / "recognition"),
    )
    monkeypatch.setenv(
        "INVENTORY_DATA_PATH",
        str(tmp_path / "inventory.json"),
    )
    get_settings.cache_clear()
    get_inventory_store.cache_clear()

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'api.db'}")
    sessions = async_sessionmaker(engine, expire_on_commit=False)

    async def prepare_database() -> None:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

    async def override_session():
        async with sessions() as session:
            yield session

    asyncio.run(prepare_database())
    app.dependency_overrides[get_db_session] = override_session
    with TestClient(app) as client:
        yield client

    app.dependency_overrides.clear()
    asyncio.run(engine.dispose())
    get_inventory_store.cache_clear()
    get_settings.cache_clear()


def _login(client: TestClient) -> tuple[str, dict[str, str]]:
    session = client.post(
        "/v1/auth/dev-login",
        json={"nickname": "识别测试用户"},
    ).json()
    return (
        session["current_household_id"],
        {"Authorization": f"Bearer {session['access_token']}"},
    )


def _inventory_item(name: str) -> dict[str, str]:
    today = date.today()
    return {
        "name": name,
        "quantity": "2",
        "unit": "盒",
        "location": "refrigerated",
        "stocked_on": today.isoformat(),
        "suggested_use_by": (today + timedelta(days=3)).isoformat(),
    }


def test_quick_entry_requires_confirmation_before_writing(
    recognition_client: TestClient,
) -> None:
    household_id, headers = _login(recognition_client)
    before = recognition_client.get(
        f"/v1/households/{household_id}/inventory",
        headers=headers,
    ).json()

    parsed = recognition_client.post(
        f"/v1/households/{household_id}/quick-entry/parse",
        json={"text": "今天买了两盒牛奶和一斤西红柿"},
        headers=headers,
    )

    assert parsed.status_code == 201
    task = parsed.json()
    assert task["status"] == "needs_confirmation"
    assert len(task["result"]["actions"]) == 2
    unchanged = recognition_client.get(
        f"/v1/households/{household_id}/inventory",
        headers=headers,
    ).json()
    assert unchanged["summary"]["total"] == before["summary"]["total"]

    confirmed = recognition_client.post(
        f"/v1/households/{household_id}/quick-entry/{task['id']}/confirm",
        json={"actions": task["result"]["actions"]},
        headers={**headers, "X-Idempotency-Key": "quick-add-confirm"},
    )

    assert confirmed.status_code == 200
    after = recognition_client.get(
        f"/v1/households/{household_id}/inventory",
        headers=headers,
    ).json()
    assert after["summary"]["total"] == before["summary"]["total"] + 2


def test_quick_entry_consumes_existing_inventory(
    recognition_client: TestClient,
) -> None:
    household_id, headers = _login(recognition_client)
    created = recognition_client.post(
        f"/v1/households/{household_id}/inventory",
        json=_inventory_item("酸奶"),
        headers={**headers, "X-Idempotency-Key": "seed-yogurt"},
    )
    assert created.status_code == 201

    parsed = recognition_client.post(
        f"/v1/households/{household_id}/quick-entry/parse",
        json={"text": "喝了一盒酸奶"},
        headers=headers,
    ).json()
    action = parsed["result"]["actions"][0]
    assert action["type"] == "consume"
    assert action["target_batch_id"] == created.json()["id"]

    confirmed = recognition_client.post(
        f"/v1/households/{household_id}/quick-entry/{parsed['id']}/confirm",
        json={"actions": [action]},
        headers={**headers, "X-Idempotency-Key": "consume-yogurt"},
    )
    assert confirmed.status_code == 200

    inventory = recognition_client.get(
        f"/v1/households/{household_id}/inventory",
        headers=headers,
    ).json()
    yogurt = next(item for item in inventory["items"] if item["name"] == "酸奶")
    assert yogurt["quantity"] == "1"


def test_quick_entry_consumes_all_when_food_is_finished(
    recognition_client: TestClient,
) -> None:
    household_id, headers = _login(recognition_client)
    created = recognition_client.post(
        f"/v1/households/{household_id}/inventory",
        json=_inventory_item("牛奶"),
        headers=headers,
    )
    assert created.status_code == 201

    parsed = recognition_client.post(
        f"/v1/households/{household_id}/quick-entry/parse",
        json={"text": "牛奶喝完了"},
        headers=headers,
    ).json()
    action = parsed["result"]["actions"][0]
    assert action["type"] == "consume"
    assert Decimal(action["quantity"]) == Decimal("2")
    assert action["note"] == "按当前库存全部消耗"

    confirmed = recognition_client.post(
        f"/v1/households/{household_id}/quick-entry/{parsed['id']}/confirm",
        json={"actions": [action]},
        headers={**headers, "X-Idempotency-Key": "finish-milk"},
    )
    assert confirmed.status_code == 200
    inventory = recognition_client.get(
        f"/v1/households/{household_id}/inventory",
        headers=headers,
    ).json()
    assert all(item["name"] != "牛奶" for item in inventory["items"])

    history = recognition_client.get(
        f"/v1/households/{household_id}/inventory/history",
        headers=headers,
    ).json()
    event = next(item for item in history["items"] if item["action"] == "consume")
    assert event["reversible"] is True


def test_quick_entry_discards_existing_inventory(
    recognition_client: TestClient,
) -> None:
    household_id, headers = _login(recognition_client)
    created = recognition_client.post(
        f"/v1/households/{household_id}/inventory",
        json=_inventory_item("酸奶"),
        headers={**headers, "X-Idempotency-Key": "seed-discard-yogurt"},
    )
    assert created.status_code == 201

    parsed = recognition_client.post(
        f"/v1/households/{household_id}/quick-entry/parse",
        json={"text": "丢了一盒酸奶"},
        headers=headers,
    ).json()
    action = parsed["result"]["actions"][0]
    assert action["type"] == "discard"

    confirmed = recognition_client.post(
        f"/v1/households/{household_id}/quick-entry/{parsed['id']}/confirm",
        json={"actions": [action]},
        headers={**headers, "X-Idempotency-Key": "discard-yogurt"},
    )
    assert confirmed.status_code == 200

    inventory = recognition_client.get(
        f"/v1/households/{household_id}/inventory",
        headers=headers,
    ).json()
    yogurt = next(item for item in inventory["items"] if item["name"] == "酸奶")
    assert yogurt["quantity"] == "1"


def test_quick_entry_query_does_not_mutate_inventory(
    recognition_client: TestClient,
) -> None:
    household_id, headers = _login(recognition_client)
    recognition_client.post(
        f"/v1/households/{household_id}/inventory",
        json=_inventory_item("查询酸奶"),
        headers=headers,
    )
    before = recognition_client.get(
        f"/v1/households/{household_id}/inventory",
        headers=headers,
    ).json()

    parsed = recognition_client.post(
        f"/v1/households/{household_id}/quick-entry/parse",
        json={"text": "查询酸奶还有多少"},
        headers=headers,
    )

    assert parsed.status_code == 201
    body = parsed.json()
    assert body["status"] == "confirmed"
    assert body["result"]["actions"] == []
    assert body["result"]["query_results"][0]["items"][0]["name"] == "查询酸奶"
    after = recognition_client.get(
        f"/v1/households/{household_id}/inventory",
        headers=headers,
    ).json()
    assert after["revision"] == before["revision"]


def test_quick_entry_edit_requires_confirmation_and_updates_item(
    recognition_client: TestClient,
) -> None:
    household_id, headers = _login(recognition_client)
    created = recognition_client.post(
        f"/v1/households/{household_id}/inventory",
        json=_inventory_item("修改酸奶"),
        headers=headers,
    ).json()
    parsed = recognition_client.post(
        f"/v1/households/{household_id}/quick-entry/parse",
        json={"text": "把修改酸奶数量改为1盒"},
        headers=headers,
    ).json()
    action = parsed["result"]["actions"][0]
    assert action["type"] == "edit"
    assert action["target_batch_id"] == created["id"]

    confirmed = recognition_client.post(
        f"/v1/households/{household_id}/quick-entry/{parsed['id']}/confirm",
        json={"actions": [action]},
        headers={**headers, "X-Idempotency-Key": "edit-yogurt"},
    )
    assert confirmed.status_code == 200
    inventory = recognition_client.get(
        f"/v1/households/{household_id}/inventory",
        headers=headers,
    ).json()
    item = next(
        candidate
        for candidate in inventory["items"]
        if candidate["name"] == "修改酸奶"
    )
    assert item["quantity"] == "1"


def test_quick_entry_merges_all_supported_edit_fields(
    recognition_client: TestClient,
) -> None:
    household_id, headers = _login(recognition_client)
    recognition_client.post(
        f"/v1/households/{household_id}/inventory",
        json=_inventory_item("全字段酸奶"),
        headers=headers,
    )
    stocked_on = date.today().isoformat()
    use_by = (date.today() + timedelta(days=10)).isoformat()
    parsed = recognition_client.post(
        f"/v1/households/{household_id}/quick-entry/parse",
        json={
            "text": (
                "把全字段酸奶数量改为1瓶，"
                "把全字段酸奶单位改为瓶，"
                "把全字段酸奶储存位置改为冷冻，"
                f"把全字段酸奶入库日期改为{stocked_on}，"
                f"把全字段酸奶建议食用日期改为{use_by}"
            )
        },
        headers=headers,
    ).json()
    assert len(parsed["result"]["actions"]) == 1
    action = parsed["result"]["actions"][0]
    assert action["quantity"] == "1"
    assert action["unit"] == "瓶"
    assert action["location"] == "frozen"
    assert action["stocked_on"] == stocked_on
    assert action["suggested_use_by"] == use_by


def test_household_shelf_life_rule_applies_to_quick_add(
    recognition_client: TestClient,
) -> None:
    household_id, headers = _login(recognition_client)
    rule = recognition_client.post(
        f"/v1/households/{household_id}/shelf-life-rules",
        json={
            "food_name": "规则牛奶",
            "location": "refrigerated",
            "suggested_days": 5,
        },
        headers=headers,
    )
    assert rule.status_code == 201

    parsed = recognition_client.post(
        f"/v1/households/{household_id}/quick-entry/parse",
        json={"text": "买了一盒规则牛奶"},
        headers=headers,
    ).json()
    action = parsed["result"]["actions"][0]
    assert action["suggested_use_by"] == (
        date.today() + timedelta(days=5)
    ).isoformat()


def test_recognition_history_and_metrics_do_not_return_images(
    recognition_client: TestClient,
) -> None:
    household_id, headers = _login(recognition_client)
    recognition_client.post(
        f"/v1/households/{household_id}/quick-entry/parse",
        json={"text": "今天到期的有哪些"},
        headers=headers,
    )
    history = recognition_client.get(
        f"/v1/households/{household_id}/recognition/history",
        headers=headers,
    )
    metrics = recognition_client.get(
        f"/v1/households/{household_id}/recognition/metrics",
        headers=headers,
    )
    assert history.status_code == 200
    assert history.json()["total"] == 1
    assert "images" not in history.json()["items"][0]
    assert metrics.status_code == 200
    assert metrics.json()["scope"] == "household"
    assert metrics.json()["task_count"] == 1


def test_member_metrics_and_history_do_not_expose_other_users_input(
    recognition_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    household_id, admin_headers = _login(recognition_client)
    recognition_client.post(
        f"/v1/households/{household_id}/quick-entry/parse",
        json={"text": "管理员的私有原始输入"},
        headers=admin_headers,
    )
    invitation = recognition_client.post(
        f"/v1/households/{household_id}/invitations",
        headers=admin_headers,
    ).json()

    async def fake_exchange_login_code(_code: str) -> WechatIdentity:
        return WechatIdentity(openid="recognition-privacy-member")

    monkeypatch.setattr(
        "app.api.auth.exchange_login_code",
        fake_exchange_login_code,
    )
    member_session = recognition_client.post(
        "/v1/auth/wechat",
        json={"code": "privacy-member"},
    ).json()
    member_headers = {
        "Authorization": f"Bearer {member_session['access_token']}"
    }
    joined = recognition_client.post(
        "/v1/households/join",
        json={"invitation_code": invitation["code"]},
        headers=member_headers,
    )
    assert joined.status_code == 200

    history = recognition_client.get(
        f"/v1/households/{household_id}/recognition/history",
        headers=member_headers,
    ).json()
    metrics = recognition_client.get(
        f"/v1/households/{household_id}/recognition/metrics",
        headers=member_headers,
    ).json()
    assert history["items"] == []
    assert metrics["scope"] == "personal"
    assert metrics["task_count"] == 0


def test_adjacent_order_screenshot_overlap_is_deduplicated() -> None:
    first = RecognitionAction(
        type="add",
        name="鲜牛奶",
        specification="950ml",
        quantity="1",
        unit="瓶",
        location="refrigerated",
        source_image_index=0,
    )
    repeated = first.model_copy(
        update={"action_id": "next-page", "source_image_index": 1}
    )

    merged = merge_order_results(
        [
            RecognitionResult(actions=[first]),
            RecognitionResult(actions=[repeated]),
        ]
    )

    assert len(merged.actions) == 1


def test_order_image_is_deleted_after_recognition_and_confirmed_once(
    recognition_client: TestClient,
) -> None:
    household_id, headers = _login(recognition_client)
    created = recognition_client.post(
        f"/v1/households/{household_id}/imports",
        headers=headers,
    )
    assert created.status_code == 201
    task_id = created.json()["id"]

    buffer = BytesIO()
    Image.new("RGB", (640, 960), "white").save(buffer, format="PNG")
    uploaded = recognition_client.post(
        f"/v1/households/{household_id}/imports/{task_id}/images",
        headers=headers,
        files={"image": ("order.png", buffer.getvalue(), "image/png")},
    )
    assert uploaded.status_code == 201

    started = recognition_client.post(
        f"/v1/households/{household_id}/imports/{task_id}/start",
        headers=headers,
    )
    assert started.status_code == 200
    task = started.json()
    assert task["status"] == "needs_confirmation"
    assert task["image_count"] == 0
    assert len(task["result"]["actions"]) == 1

    confirm_url = (
        f"/v1/households/{household_id}/imports/{task_id}/confirm"
    )
    first = recognition_client.post(
        confirm_url,
        json={"actions": task["result"]["actions"]},
        headers={**headers, "X-Idempotency-Key": "order-confirm"},
    )
    second = recognition_client.post(
        confirm_url,
        json={"actions": task["result"]["actions"]},
        headers={**headers, "X-Idempotency-Key": "order-confirm"},
    )
    assert first.status_code == 200
    assert second.status_code == 200

    inventory = recognition_client.get(
        f"/v1/households/{household_id}/inventory",
        headers=headers,
    ).json()
    recognized = [
        item
        for item in inventory["items"]
        if item["name"] == "识别测试牛奶1"
    ]
    assert len(recognized) == 1


def test_hunyuan_order_result_fills_server_owned_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HUNYUAN_API_KEY", "test-key")
    get_settings.cache_clear()
    provider = HunyuanRecognitionProvider()

    async def compact_response(**_kwargs) -> str:
        return """
        {
          "actions": [{
            "type": "add",
            "name": "鲜牛奶",
            "specification": "950ml",
            "quantity": "1",
            "unit": "瓶",
            "location": "refrigerated",
            "confidence": 0.95,
            "needs_confirmation": false
          }],
          "warnings": []
        }
        """

    monkeypatch.setattr(provider, "_complete", compact_response)
    result = asyncio.run(
        provider.recognize_order_image(
            image_bytes=b"image",
            content_type="image/jpeg",
            image_index=2,
        )
    )

    action = result.actions[0]
    assert action.type == "add"
    assert action.source_image_index == 2
    assert action.stocked_on == date.today()
    assert action.suggested_use_by == date.today() + timedelta(days=3)
    assert action.target_batch_id is None
    get_settings.cache_clear()


def test_order_images_are_recognized_with_concurrency_two(
    recognition_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class TrackingProvider:
        def __init__(self) -> None:
            self.active = 0
            self.max_active = 0

        async def recognize_order_image(
            self,
            *,
            image_bytes: bytes,
            content_type: str,
            image_index: int,
        ) -> RecognitionResult:
            del image_bytes, content_type
            self.active += 1
            self.max_active = max(self.max_active, self.active)
            await asyncio.sleep(0.03)
            self.active -= 1
            return RecognitionResult(
                actions=[
                    RecognitionAction(
                        type="add",
                        name=f"并发测试食材{image_index}",
                        quantity="1",
                        unit="份",
                        location="refrigerated",
                        source_image_index=image_index,
                    )
                ]
            )

    provider = TrackingProvider()
    monkeypatch.setattr(
        "app.services.recognition_tasks.get_recognition_provider",
        lambda: provider,
    )
    household_id, headers = _login(recognition_client)
    created = recognition_client.post(
        f"/v1/households/{household_id}/imports",
        headers=headers,
    )
    task_id = created.json()["id"]
    buffer = BytesIO()
    Image.new("RGB", (320, 480), "white").save(buffer, format="PNG")

    for index in range(2):
        uploaded = recognition_client.post(
            f"/v1/households/{household_id}/imports/{task_id}/images",
            headers=headers,
            files={
                "image": (
                    f"order-{index}.png",
                    buffer.getvalue(),
                    "image/png",
                )
            },
        )
        assert uploaded.status_code == 201

    started = recognition_client.post(
        f"/v1/households/{household_id}/imports/{task_id}/start",
        headers=headers,
    )

    assert started.status_code == 200
    assert started.json()["status"] == "needs_confirmation"
    assert provider.max_active == 2
