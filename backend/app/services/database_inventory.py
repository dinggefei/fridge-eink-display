from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import FoodBatch, Household
from app.services.inventory_store import (
    InventoryItem,
    InventorySnapshot,
)


async def load_household_inventory_snapshot(
    session: AsyncSession,
    household: Household,
) -> InventorySnapshot:
    rows = (
        await session.scalars(
            select(FoodBatch).where(
                FoodBatch.household_id == household.id,
                FoodBatch.deleted_at.is_(None),
                FoodBatch.quantity > 0,
            )
        )
    ).all()
    return InventorySnapshot(
        household_name=household.name,
        revision=household.inventory_revision,
        updated_at=household.updated_at,
        display_todos=tuple(household.display_todos or ()),
        items=tuple(
            InventoryItem(
                id=row.id,
                name=row.standard_name,
                quantity=row.quantity,
                unit=row.unit,
                location=row.location,
                stocked_on=row.stocked_on,
                suggested_use_by=row.suggested_use_by,
            )
            for row in rows
        ),
    )
