from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ShelfLifePreference
from app.domain.inventory import StorageLocation


DEFAULT_SHELF_LIFE_DAYS = {
    StorageLocation.REFRIGERATED: 3,
    StorageLocation.FROZEN: 30,
    StorageLocation.ROOM_TEMPERATURE: 7,
}


def normalize_food_name(name: str) -> str:
    return " ".join(name.strip().split()).casefold()


async def suggested_shelf_life_days(
    session: AsyncSession,
    *,
    household_id: str,
    food_name: str,
    location: StorageLocation,
) -> tuple[int, str]:
    rule = await session.scalar(
        select(ShelfLifePreference).where(
            ShelfLifePreference.household_id == household_id,
            ShelfLifePreference.user_id.is_(None),
            ShelfLifePreference.category == normalize_food_name(food_name),
            ShelfLifePreference.location == location,
        )
    )
    if rule is not None:
        return rule.suggested_days, "household_rule"
    return DEFAULT_SHELF_LIFE_DAYS[location], "system_default"


async def suggested_use_by_date(
    session: AsyncSession,
    *,
    household_id: str,
    food_name: str,
    location: StorageLocation,
    stocked_on: date,
) -> tuple[date, int, str]:
    days, source = await suggested_shelf_life_days(
        session,
        household_id=household_id,
        food_name=food_name,
        location=location,
    )
    return stocked_on + timedelta(days=days), days, source
