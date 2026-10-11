from __future__ import annotations

from collections import Counter
from datetime import date, datetime
from decimal import Decimal

from fastapi import APIRouter, HTTPException, Query, Response, status
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domain.inventory import (
    FoodBatch,
    FoodStatus,
    StorageLocation,
    calculate_food_status,
    describe_food_status,
    sort_batches_for_display,
)
from app.services.inventory_store import (
    InventoryItem,
    InventoryItemValues,
    InventorySnapshot,
    get_inventory_store,
)


router = APIRouter(prefix="/v1/inventory", tags=["inventory"])


class InventoryItemWrite(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=60)
    quantity: Decimal = Field(gt=0, max_digits=12, decimal_places=3)
    unit: str = Field(min_length=1, max_length=20)
    location: StorageLocation
    stocked_on: date
    suggested_use_by: date | None = None

    @model_validator(mode="after")
    def validate_dates(self) -> "InventoryItemWrite":
        if (
            self.suggested_use_by is not None
            and self.suggested_use_by < self.stocked_on
        ):
            raise ValueError("suggested_use_by must not be before stocked_on")
        return self

    def to_values(self) -> InventoryItemValues:
        return InventoryItemValues(
            name=self.name,
            quantity=self.quantity,
            unit=self.unit,
            location=self.location,
            stocked_on=self.stocked_on,
            suggested_use_by=self.suggested_use_by,
        )


class InventoryItemResponse(BaseModel):
    id: str
    name: str
    quantity: str
    unit: str
    quantity_text: str
    location: StorageLocation
    stocked_on: date
    suggested_use_by: date | None
    status: FoodStatus
    status_text: str
    days_remaining: int | None


class InventorySummary(BaseModel):
    total: int
    eat_today: int
    eat_soon: int
    overdue: int
    normal: int
    no_date: int


class InventoryListResponse(BaseModel):
    household_name: str
    revision: int
    updated_at: datetime
    summary: InventorySummary
    items: list[InventoryItemResponse]


class HouseholdNameWrite(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=40)


def _quantity_text(quantity: Decimal, unit: str) -> str:
    text = format(quantity.normalize(), "f")
    return f"{text} {unit}"


def _to_domain(item: InventoryItem) -> FoodBatch:
    return FoodBatch(
        batch_id=item.id,
        name=item.name,
        quantity=item.quantity,
        unit=item.unit,
        location=item.location,
        stocked_on=item.stocked_on,
        suggested_use_by=item.suggested_use_by,
    )


def _item_response(item: InventoryItem, today: date) -> InventoryItemResponse:
    item_status = calculate_food_status(item.suggested_use_by, today=today)
    return InventoryItemResponse(
        id=item.id,
        name=item.name,
        quantity=format(item.quantity.normalize(), "f"),
        unit=item.unit,
        quantity_text=_quantity_text(item.quantity, item.unit),
        location=item.location,
        stocked_on=item.stocked_on,
        suggested_use_by=item.suggested_use_by,
        status=item_status,
        status_text=describe_food_status(item.suggested_use_by, today=today),
        days_remaining=(
            (item.suggested_use_by - today).days
            if item.suggested_use_by
            else None
        ),
    )


def _list_response(
    snapshot: InventorySnapshot,
    location: StorageLocation | None = None,
) -> InventoryListResponse:
    today = date.today()
    ordered_batches = sort_batches_for_display(
        (_to_domain(item) for item in snapshot.items),
        today=today,
    )
    item_by_id = {item.id: item for item in snapshot.items}
    ordered_items = [item_by_id[batch.batch_id] for batch in ordered_batches]
    if location is not None:
        ordered_items = [
            item for item in ordered_items if item.location == location
        ]

    responses = [_item_response(item, today) for item in ordered_items]
    status_counts = Counter(item.status for item in responses)
    return InventoryListResponse(
        household_name=snapshot.household_name,
        revision=snapshot.revision,
        updated_at=snapshot.updated_at,
        summary=InventorySummary(
            total=len(responses),
            eat_today=status_counts[FoodStatus.EAT_TODAY],
            eat_soon=status_counts[FoodStatus.EAT_SOON],
            overdue=status_counts[FoodStatus.OVERDUE],
            normal=status_counts[FoodStatus.NORMAL],
            no_date=status_counts[FoodStatus.NO_DATE],
        ),
        items=responses,
    )


@router.get("", response_model=InventoryListResponse)
def list_inventory(
    location: StorageLocation | None = Query(default=None),
) -> InventoryListResponse:
    return _list_response(get_inventory_store().snapshot(), location)


@router.post(
    "",
    response_model=InventoryItemResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_inventory_item(payload: InventoryItemWrite) -> InventoryItemResponse:
    item = get_inventory_store().add(payload.to_values())
    return _item_response(item, date.today())


@router.put("/{item_id}", response_model=InventoryItemResponse)
def replace_inventory_item(
    item_id: str,
    payload: InventoryItemWrite,
) -> InventoryItemResponse:
    try:
        item = get_inventory_store().replace(item_id, payload.to_values())
    except KeyError:
        raise HTTPException(status_code=404, detail="inventory item not found")
    return _item_response(item, date.today())


@router.delete("/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_inventory_item(item_id: str) -> Response:
    try:
        get_inventory_store().delete(item_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="inventory item not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.put("/settings/household", response_model=InventoryListResponse)
def rename_household(payload: HouseholdNameWrite) -> InventoryListResponse:
    snapshot = get_inventory_store().rename_household(payload.name)
    return _list_response(snapshot)
