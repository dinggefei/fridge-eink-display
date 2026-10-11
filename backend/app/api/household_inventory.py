from __future__ import annotations

from collections import Counter
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

from fastapi import APIRouter, Header, HTTPException, Query, Response, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import func, select

from app.api.dependencies import (
    CurrentUser,
    DbSession,
    require_household_admin,
    require_household_member,
)
from app.api.inventory import (
    HouseholdNameWrite,
    InventoryItemResponse,
    InventoryItemWrite,
    InventoryListResponse,
    InventorySummary,
    _item_response,
)
from app.db.base import utc_now
from app.db.models import (
    FoodBatch as FoodBatchModel,
    Household,
    InventoryAction,
    InventoryEvent,
    User,
)
from app.domain.inventory import (
    FoodBatch,
    FoodStatus,
    StorageLocation,
    calculate_food_status,
    sort_batches_for_display,
)
from app.services.inventory_store import InventoryItem
from app.services.shelf_life import suggested_use_by_date


router = APIRouter(
    prefix="/v1/households/{household_id}/inventory",
    tags=["household-inventory"],
)


def _as_item(row: FoodBatchModel) -> InventoryItem:
    return InventoryItem(
        id=row.id,
        name=row.standard_name,
        quantity=row.quantity,
        unit=row.unit,
        location=row.location,
        stocked_on=row.stocked_on,
        suggested_use_by=row.suggested_use_by,
    )


async def _household(
    session: DbSession,
    user: CurrentUser,
    household_id: str,
) -> Household:
    await require_household_member(
        session,
        household_id=household_id,
        user_id=user.id,
    )
    household = await session.get(Household, household_id)
    if household is None:
        raise HTTPException(status_code=404, detail="household not found")
    return household


async def _list_response(
    session: DbSession,
    household: Household,
    location: StorageLocation | None,
) -> InventoryListResponse:
    statement = select(FoodBatchModel).where(
        FoodBatchModel.household_id == household.id,
        FoodBatchModel.deleted_at.is_(None),
        FoodBatchModel.quantity > 0,
    )
    if location is not None:
        statement = statement.where(FoodBatchModel.location == location)
    rows = (await session.scalars(statement)).all()
    today = date.today()
    ordered = sort_batches_for_display(
        (
            FoodBatch(
                batch_id=row.id,
                name=row.standard_name,
                quantity=row.quantity,
                unit=row.unit,
                location=row.location,
                stocked_on=row.stocked_on,
                suggested_use_by=row.suggested_use_by,
            )
            for row in rows
        ),
        today=today,
    )
    rows_by_id = {row.id: row for row in rows}
    responses = [
        _item_response(_as_item(rows_by_id[item.batch_id]), today)
        for item in ordered
    ]
    counts = Counter(item.status for item in responses)
    return InventoryListResponse(
        household_name=household.name,
        revision=household.inventory_revision,
        updated_at=household.updated_at,
        summary=InventorySummary(
            total=len(responses),
            eat_today=counts[FoodStatus.EAT_TODAY],
            eat_soon=counts[FoodStatus.EAT_SOON],
            overdue=counts[FoodStatus.OVERDUE],
            normal=counts[FoodStatus.NORMAL],
            no_date=counts[FoodStatus.NO_DATE],
        ),
        items=responses,
    )


def _record_event(
    *,
    household_id: str,
    batch: FoodBatchModel,
    user_id: str,
    action: InventoryAction,
    idempotency_key: str,
    quantity: Decimal | None = None,
    event_data: dict | None = None,
) -> InventoryEvent:
    return InventoryEvent(
        household_id=household_id,
        batch_id=batch.id,
        actor_user_id=user_id,
        action=action,
        quantity=quantity or batch.quantity,
        idempotency_key=idempotency_key,
        event_data=event_data,
    )


def _batch_snapshot(batch: FoodBatchModel) -> dict[str, str | None]:
    return {
        "standard_name": batch.standard_name,
        "original_name": batch.original_name,
        "quantity": str(batch.quantity),
        "unit": batch.unit,
        "location": batch.location.value,
        "stocked_on": batch.stocked_on.isoformat(),
        "suggested_use_by": (
            batch.suggested_use_by.isoformat()
            if batch.suggested_use_by
            else None
        ),
        "status": batch.status.value,
        "deleted_at": (
            batch.deleted_at.isoformat() if batch.deleted_at else None
        ),
    }


def _apply_snapshot(batch: FoodBatchModel, snapshot: dict) -> None:
    batch.standard_name = snapshot["standard_name"]
    batch.original_name = snapshot.get("original_name")
    batch.quantity = Decimal(snapshot["quantity"])
    batch.unit = snapshot["unit"]
    batch.location = StorageLocation(snapshot["location"])
    batch.stocked_on = date.fromisoformat(snapshot["stocked_on"])
    batch.suggested_use_by = (
        date.fromisoformat(snapshot["suggested_use_by"])
        if snapshot.get("suggested_use_by")
        else None
    )
    batch.status = FoodStatus(snapshot["status"])
    batch.deleted_at = (
        datetime.fromisoformat(snapshot["deleted_at"])
        if snapshot.get("deleted_at")
        else None
    )


class InventoryOperationWrite(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    action: InventoryAction
    quantity: Decimal = Field(gt=0, max_digits=12, decimal_places=3)


class InventoryOperationResponse(BaseModel):
    item: InventoryItemResponse
    revision: int


class InventoryHistoryItem(BaseModel):
    id: str
    batch_id: str
    food_name: str
    actor_user_id: str
    actor_name: str | None
    action: InventoryAction
    quantity: Decimal
    unit: str
    created_at: datetime
    reversible: bool
    reverse_reason: str | None = None


class InventoryHistoryResponse(BaseModel):
    items: list[InventoryHistoryItem]
    total: int
    page: int
    page_size: int


class RestoreResponse(BaseModel):
    item: InventoryItemResponse
    revision: int


class DisplayTodosWrite(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    items: list[str] = Field(default_factory=list, max_length=10)

    @field_validator("items")
    @classmethod
    def validate_items(cls, items: list[str]) -> list[str]:
        normalized: list[str] = []
        for item in items:
            text = item.strip()
            if not text:
                raise ValueError("todo text cannot be empty")
            if len(text) > 40:
                raise ValueError("todo text cannot exceed 40 characters")
            normalized.append(text)
        return normalized


class DisplayTodosResponse(BaseModel):
    items: list[str]
    revision: int
    updated_at: datetime


@router.get("", response_model=InventoryListResponse)
async def list_household_inventory(
    household_id: str,
    session: DbSession,
    user: CurrentUser,
    location: StorageLocation | None = Query(default=None),
) -> InventoryListResponse:
    household = await _household(session, user, household_id)
    return await _list_response(session, household, location)


@router.post(
    "",
    response_model=InventoryItemResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_household_inventory_item(
    household_id: str,
    payload: InventoryItemWrite,
    session: DbSession,
    user: CurrentUser,
    idempotency_key: str | None = Header(
        default=None,
        alias="X-Idempotency-Key",
    ),
) -> InventoryItemResponse:
    household = await _household(session, user, household_id)
    suggested_use_by = payload.suggested_use_by
    if suggested_use_by is None:
        suggested_use_by, _, _ = await suggested_use_by_date(
            session,
            household_id=household_id,
            food_name=payload.name,
            location=payload.location,
            stocked_on=payload.stocked_on,
        )
    item_status = calculate_food_status(
        suggested_use_by,
        today=date.today(),
    )
    batch = FoodBatchModel(
        household_id=household_id,
        standard_name=payload.name,
        original_name=payload.name,
        quantity=payload.quantity,
        unit=payload.unit,
        location=payload.location,
        stocked_on=payload.stocked_on,
        suggested_use_by=suggested_use_by,
        status=item_status,
    )
    session.add(batch)
    await session.flush()
    session.add(
        _record_event(
            household_id=household_id,
            batch=batch,
            user_id=user.id,
            action=InventoryAction.ADD,
            idempotency_key=idempotency_key or str(uuid4()),
            event_data={"before": None, "after": _batch_snapshot(batch)},
        )
    )
    household.inventory_revision += 1
    await session.commit()
    return _item_response(_as_item(batch), date.today())


@router.put("/{item_id}", response_model=InventoryItemResponse)
async def replace_household_inventory_item(
    household_id: str,
    item_id: str,
    payload: InventoryItemWrite,
    session: DbSession,
    user: CurrentUser,
    idempotency_key: str | None = Header(
        default=None,
        alias="X-Idempotency-Key",
    ),
) -> InventoryItemResponse:
    household = await _household(session, user, household_id)
    batch = await session.scalar(
        select(FoodBatchModel).where(
            FoodBatchModel.id == item_id,
            FoodBatchModel.household_id == household_id,
            FoodBatchModel.deleted_at.is_(None),
        )
    )
    if batch is None:
        raise HTTPException(status_code=404, detail="inventory item not found")
    before = _batch_snapshot(batch)
    batch.standard_name = payload.name
    batch.original_name = payload.name
    batch.quantity = payload.quantity
    batch.unit = payload.unit
    batch.location = payload.location
    batch.stocked_on = payload.stocked_on
    batch.suggested_use_by = payload.suggested_use_by
    batch.status = calculate_food_status(
        payload.suggested_use_by,
        today=date.today(),
    )
    session.add(
        _record_event(
            household_id=household_id,
            batch=batch,
            user_id=user.id,
            action=InventoryAction.EDIT,
            idempotency_key=idempotency_key or str(uuid4()),
            event_data={
                "before": before,
                "after": _batch_snapshot(batch),
            },
        )
    )
    household.inventory_revision += 1
    await session.commit()
    return _item_response(_as_item(batch), date.today())


@router.delete("/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_household_inventory_item(
    household_id: str,
    item_id: str,
    session: DbSession,
    user: CurrentUser,
    idempotency_key: str | None = Header(
        default=None,
        alias="X-Idempotency-Key",
    ),
) -> Response:
    household = await _household(session, user, household_id)
    batch = await session.scalar(
        select(FoodBatchModel).where(
            FoodBatchModel.id == item_id,
            FoodBatchModel.household_id == household_id,
            FoodBatchModel.deleted_at.is_(None),
        )
    )
    if batch is None:
        raise HTTPException(status_code=404, detail="inventory item not found")
    before = _batch_snapshot(batch)
    batch.deleted_at = utc_now()
    session.add(
        _record_event(
            household_id=household_id,
            batch=batch,
            user_id=user.id,
            action=InventoryAction.DELETE,
            idempotency_key=idempotency_key or str(uuid4()),
            event_data={
                "before": before,
                "after": _batch_snapshot(batch),
            },
        )
    )
    household.inventory_revision += 1
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/{item_id}/actions",
    response_model=InventoryOperationResponse,
)
async def apply_inventory_operation(
    household_id: str,
    item_id: str,
    payload: InventoryOperationWrite,
    session: DbSession,
    user: CurrentUser,
    idempotency_key: str | None = Header(
        default=None,
        alias="X-Idempotency-Key",
    ),
) -> InventoryOperationResponse:
    if payload.action not in {
        InventoryAction.CONSUME,
        InventoryAction.DISCARD,
    }:
        raise HTTPException(
            status_code=422,
            detail="action must be consume or discard",
        )
    household = await _household(session, user, household_id)
    batch = await session.scalar(
        select(FoodBatchModel)
        .where(
            FoodBatchModel.id == item_id,
            FoodBatchModel.household_id == household_id,
            FoodBatchModel.deleted_at.is_(None),
            FoodBatchModel.quantity > 0,
        )
        .with_for_update()
    )
    if batch is None:
        raise HTTPException(status_code=404, detail="inventory item not found")
    if payload.quantity > batch.quantity:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="operation quantity exceeds current inventory",
        )
    before = _batch_snapshot(batch)
    batch.quantity -= payload.quantity
    session.add(
        _record_event(
            household_id=household_id,
            batch=batch,
            user_id=user.id,
            action=payload.action,
            quantity=payload.quantity,
            idempotency_key=idempotency_key or str(uuid4()),
            event_data={
                "before": before,
                "after": _batch_snapshot(batch),
            },
        )
    )
    household.inventory_revision += 1
    await session.commit()
    return InventoryOperationResponse(
        item=_item_response(_as_item(batch), date.today()),
        revision=household.inventory_revision,
    )


@router.get("/history", response_model=InventoryHistoryResponse)
async def list_inventory_history(
    household_id: str,
    session: DbSession,
    user: CurrentUser,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=30, ge=1, le=100),
) -> InventoryHistoryResponse:
    await _household(session, user, household_id)
    total = await session.scalar(
        select(func.count(InventoryEvent.id)).where(
            InventoryEvent.household_id == household_id
        )
    )
    rows = (
        await session.execute(
            select(InventoryEvent, FoodBatchModel, User)
            .join(FoodBatchModel, FoodBatchModel.id == InventoryEvent.batch_id)
            .join(User, User.id == InventoryEvent.actor_user_id)
            .where(InventoryEvent.household_id == household_id)
            .order_by(InventoryEvent.created_at.desc(), InventoryEvent.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()
    now = datetime.now(timezone.utc)
    items: list[InventoryHistoryItem] = []
    for event, batch, actor in rows:
        latest_id = await session.scalar(
            select(InventoryEvent.id)
            .where(InventoryEvent.batch_id == event.batch_id)
            .order_by(
                InventoryEvent.created_at.desc(),
                InventoryEvent.id.desc(),
            )
            .limit(1)
        )
        created_at = event.created_at
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        reversible_action = event.action in {
            InventoryAction.EDIT,
            InventoryAction.CONSUME,
            InventoryAction.DISCARD,
            InventoryAction.DELETE,
        }
        reason = None
        if not reversible_action:
            reason = "该操作不支持撤销"
        elif event.reversed_at is not None:
            reason = "该操作已撤销"
        elif latest_id != event.id:
            reason = "只能撤销该食材的最近一次操作"
        elif now - created_at > timedelta(hours=24):
            reason = "已超过 24 小时撤销期限"
        elif not event.event_data or not event.event_data.get("before"):
            reason = "历史数据缺少恢复快照"
        items.append(
            InventoryHistoryItem(
                id=event.id,
                batch_id=event.batch_id,
                food_name=batch.standard_name,
                actor_user_id=actor.id,
                actor_name=actor.nickname,
                action=event.action,
                quantity=event.quantity,
                unit=batch.unit,
                created_at=event.created_at,
                reversible=reason is None,
                reverse_reason=reason,
            )
        )
    return InventoryHistoryResponse(
        items=items,
        total=total or 0,
        page=page,
        page_size=page_size,
    )


@router.post(
    "/history/{event_id}/restore",
    response_model=RestoreResponse,
)
async def restore_inventory_event(
    household_id: str,
    event_id: str,
    session: DbSession,
    user: CurrentUser,
    idempotency_key: str | None = Header(
        default=None,
        alias="X-Idempotency-Key",
    ),
) -> RestoreResponse:
    household = await _household(session, user, household_id)
    event = await session.scalar(
        select(InventoryEvent)
        .where(
            InventoryEvent.id == event_id,
            InventoryEvent.household_id == household_id,
        )
        .with_for_update()
    )
    if event is None:
        raise HTTPException(status_code=404, detail="history event not found")
    if event.action not in {
        InventoryAction.EDIT,
        InventoryAction.CONSUME,
        InventoryAction.DISCARD,
        InventoryAction.DELETE,
    }:
        raise HTTPException(status_code=409, detail="operation cannot be restored")
    if event.reversed_at is not None:
        raise HTTPException(status_code=409, detail="operation already restored")
    latest_id = await session.scalar(
        select(InventoryEvent.id)
        .where(InventoryEvent.batch_id == event.batch_id)
        .order_by(InventoryEvent.created_at.desc(), InventoryEvent.id.desc())
        .limit(1)
    )
    if latest_id != event.id:
        raise HTTPException(
            status_code=409,
            detail="only the latest operation for this food can be restored",
        )
    created_at = event.created_at
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    if datetime.now(timezone.utc) - created_at > timedelta(hours=24):
        raise HTTPException(
            status_code=409,
            detail="operation is outside the 24-hour restore window",
        )
    before = (event.event_data or {}).get("before")
    if not before:
        raise HTTPException(
            status_code=409,
            detail="operation does not contain a restore snapshot",
        )
    batch = await session.scalar(
        select(FoodBatchModel)
        .where(
            FoodBatchModel.id == event.batch_id,
            FoodBatchModel.household_id == household_id,
        )
        .with_for_update()
    )
    if batch is None:
        raise HTTPException(status_code=404, detail="inventory item not found")
    current = _batch_snapshot(batch)
    _apply_snapshot(batch, before)
    event.reversed_at = utc_now()
    event.reversed_by_user_id = user.id
    session.add(
        _record_event(
            household_id=household_id,
            batch=batch,
            user_id=user.id,
            action=InventoryAction.RESTORE,
            quantity=event.quantity,
            idempotency_key=idempotency_key or str(uuid4()),
            event_data={
                "restored_event_id": event.id,
                "before": current,
                "after": _batch_snapshot(batch),
            },
        )
    )
    household.inventory_revision += 1
    await session.commit()
    return RestoreResponse(
        item=_item_response(_as_item(batch), date.today()),
        revision=household.inventory_revision,
    )


@router.put("/settings/household", response_model=InventoryListResponse)
async def rename_household(
    household_id: str,
    payload: HouseholdNameWrite,
    session: DbSession,
    user: CurrentUser,
) -> InventoryListResponse:
    await require_household_admin(
        session,
        household_id=household_id,
        user_id=user.id,
    )
    household = await session.get(Household, household_id)
    if household is None:
        raise HTTPException(status_code=404, detail="household not found")
    household.name = payload.name
    household.inventory_revision += 1
    await session.commit()
    return await _list_response(session, household, None)


@router.get("/settings/display-todos", response_model=DisplayTodosResponse)
async def read_display_todos(
    household_id: str,
    session: DbSession,
    user: CurrentUser,
) -> DisplayTodosResponse:
    household = await _household(session, user, household_id)
    return DisplayTodosResponse(
        items=list(household.display_todos or ()),
        revision=household.inventory_revision,
        updated_at=household.updated_at,
    )


@router.put("/settings/display-todos", response_model=DisplayTodosResponse)
async def replace_display_todos(
    household_id: str,
    payload: DisplayTodosWrite,
    session: DbSession,
    user: CurrentUser,
) -> DisplayTodosResponse:
    household = await _household(session, user, household_id)
    if list(household.display_todos or ()) != payload.items:
        household.display_todos = list(payload.items)
        household.inventory_revision += 1
        await session.commit()
        await session.refresh(household)
    return DisplayTodosResponse(
        items=list(household.display_todos or ()),
        revision=household.inventory_revision,
        updated_at=household.updated_at,
    )
