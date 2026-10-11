from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from enum import StrEnum
from typing import Iterable


class StorageLocation(StrEnum):
    REFRIGERATED = "refrigerated"
    FROZEN = "frozen"
    ROOM_TEMPERATURE = "room_temperature"


class FoodStatus(StrEnum):
    NORMAL = "normal"
    EAT_SOON = "eat_soon"
    EAT_TODAY = "eat_today"
    OVERDUE = "overdue"
    NO_DATE = "no_date"


@dataclass(frozen=True, slots=True)
class FoodBatch:
    batch_id: str
    name: str
    quantity: Decimal
    unit: str
    location: StorageLocation
    stocked_on: date
    suggested_use_by: date | None

    def __post_init__(self) -> None:
        if not self.batch_id.strip():
            raise ValueError("batch_id must not be empty")
        if not self.name.strip():
            raise ValueError("name must not be empty")
        if self.quantity <= 0:
            raise ValueError("quantity must be greater than zero")


@dataclass(frozen=True, slots=True)
class Deduction:
    batch_id: str
    quantity: Decimal


_STATUS_PRIORITY = {
    FoodStatus.EAT_TODAY: 0,
    FoodStatus.OVERDUE: 1,
    FoodStatus.EAT_SOON: 2,
    FoodStatus.NORMAL: 3,
    FoodStatus.NO_DATE: 4,
}


def calculate_suggested_use_by(stocked_on: date, suggested_days: int) -> date:
    if suggested_days < 0:
        raise ValueError("suggested_days must not be negative")
    return stocked_on + timedelta(days=suggested_days)


def calculate_food_status(
    suggested_use_by: date | None,
    *,
    today: date,
    reminder_days: int = 3,
) -> FoodStatus:
    if not 1 <= reminder_days <= 7:
        raise ValueError("reminder_days must be between 1 and 7")
    if suggested_use_by is None:
        return FoodStatus.NO_DATE

    remaining_days = (suggested_use_by - today).days
    if remaining_days < 0:
        return FoodStatus.OVERDUE
    if remaining_days == 0:
        return FoodStatus.EAT_TODAY
    if remaining_days <= reminder_days:
        return FoodStatus.EAT_SOON
    return FoodStatus.NORMAL


def describe_food_status(
    suggested_use_by: date | None,
    *,
    today: date,
    reminder_days: int = 3,
) -> str:
    status = calculate_food_status(
        suggested_use_by,
        today=today,
        reminder_days=reminder_days,
    )
    if status == FoodStatus.NO_DATE:
        return "待补日期"

    remaining_days = (suggested_use_by - today).days
    if status == FoodStatus.OVERDUE:
        return f"超期 {abs(remaining_days)} 天"
    if status == FoodStatus.EAT_TODAY:
        return "今天吃"
    return f"剩 {remaining_days} 天"


def sort_batches_for_display(
    batches: Iterable[FoodBatch],
    *,
    today: date,
    reminder_days: int = 3,
) -> list[FoodBatch]:
    def sort_key(batch: FoodBatch) -> tuple[int, date, date, str, str]:
        status = calculate_food_status(
            batch.suggested_use_by,
            today=today,
            reminder_days=reminder_days,
        )
        return (
            _STATUS_PRIORITY[status],
            batch.suggested_use_by or date.max,
            batch.stocked_on,
            batch.name,
            batch.batch_id,
        )

    return sorted(batches, key=sort_key)


def allocate_fefo(
    batches: Iterable[FoodBatch],
    requested_quantity: Decimal,
) -> list[Deduction]:
    """Allocate a deduction using first-expire, first-out (FEFO)."""
    if requested_quantity <= 0:
        raise ValueError("requested_quantity must be greater than zero")

    ordered = sorted(
        batches,
        key=lambda batch: (
            batch.suggested_use_by or date.max,
            batch.stocked_on,
            batch.batch_id,
        ),
    )
    available = sum((batch.quantity for batch in ordered), start=Decimal("0"))
    if available < requested_quantity:
        raise ValueError("requested quantity exceeds available inventory")

    remaining = requested_quantity
    deductions: list[Deduction] = []
    for batch in ordered:
        if remaining == 0:
            break
        quantity = min(batch.quantity, remaining)
        deductions.append(Deduction(batch_id=batch.batch_id, quantity=quantity))
        remaining -= quantity

    return deductions
