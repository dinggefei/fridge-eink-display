from __future__ import annotations

from datetime import date

from fastapi import APIRouter, HTTPException, Query, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from app.api.dependencies import (
    CurrentUser,
    DbSession,
    require_household_admin,
    require_household_member,
)
from app.db.models import ShelfLifePreference
from app.domain.inventory import StorageLocation
from app.services.shelf_life import (
    normalize_food_name,
    suggested_use_by_date,
)


router = APIRouter(
    prefix="/v1/households/{household_id}/shelf-life-rules",
    tags=["shelf-life"],
)


class ShelfLifeRuleWrite(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    food_name: str = Field(min_length=1, max_length=100)
    location: StorageLocation
    suggested_days: int = Field(ge=0, le=3650)


class ShelfLifeRuleResponse(BaseModel):
    id: str
    food_name: str
    location: StorageLocation
    suggested_days: int


class ShelfLifeSuggestionResponse(BaseModel):
    food_name: str
    location: StorageLocation
    stocked_on: date
    suggested_days: int
    suggested_use_by: date
    source: str


@router.get("", response_model=list[ShelfLifeRuleResponse])
async def list_shelf_life_rules(
    household_id: str,
    user: CurrentUser,
    session: DbSession,
) -> list[ShelfLifeRuleResponse]:
    await require_household_member(
        session,
        household_id=household_id,
        user_id=user.id,
    )
    rules = (
        await session.scalars(
            select(ShelfLifePreference)
            .where(
                ShelfLifePreference.household_id == household_id,
                ShelfLifePreference.user_id.is_(None),
            )
            .order_by(
                ShelfLifePreference.category,
                ShelfLifePreference.location,
            )
        )
    ).all()
    return [
        ShelfLifeRuleResponse(
            id=rule.id,
            food_name=rule.category,
            location=rule.location,
            suggested_days=rule.suggested_days,
        )
        for rule in rules
    ]


@router.post(
    "",
    response_model=ShelfLifeRuleResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_or_update_shelf_life_rule(
    household_id: str,
    payload: ShelfLifeRuleWrite,
    user: CurrentUser,
    session: DbSession,
) -> ShelfLifeRuleResponse:
    await require_household_admin(
        session,
        household_id=household_id,
        user_id=user.id,
    )
    food_name = normalize_food_name(payload.food_name)
    rule = await session.scalar(
        select(ShelfLifePreference).where(
            ShelfLifePreference.household_id == household_id,
            ShelfLifePreference.user_id.is_(None),
            ShelfLifePreference.category == food_name,
            ShelfLifePreference.location == payload.location,
        )
    )
    if rule is None:
        rule = ShelfLifePreference(
            household_id=household_id,
            user_id=None,
            category=food_name,
            location=payload.location,
            suggested_days=payload.suggested_days,
        )
        session.add(rule)
        await session.flush()
    else:
        rule.suggested_days = payload.suggested_days
    await session.commit()
    return ShelfLifeRuleResponse(
        id=rule.id,
        food_name=rule.category,
        location=rule.location,
        suggested_days=rule.suggested_days,
    )


@router.delete("/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_shelf_life_rule(
    household_id: str,
    rule_id: str,
    user: CurrentUser,
    session: DbSession,
) -> Response:
    await require_household_admin(
        session,
        household_id=household_id,
        user_id=user.id,
    )
    rule = await session.scalar(
        select(ShelfLifePreference).where(
            ShelfLifePreference.id == rule_id,
            ShelfLifePreference.household_id == household_id,
            ShelfLifePreference.user_id.is_(None),
        )
    )
    if rule is None:
        raise HTTPException(status_code=404, detail="shelf-life rule not found")
    await session.delete(rule)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/suggestion", response_model=ShelfLifeSuggestionResponse)
async def suggest_shelf_life(
    household_id: str,
    user: CurrentUser,
    session: DbSession,
    food_name: str = Query(min_length=1, max_length=100),
    location: StorageLocation = Query(),
    stocked_on: date = Query(),
) -> ShelfLifeSuggestionResponse:
    await require_household_member(
        session,
        household_id=household_id,
        user_id=user.id,
    )
    use_by, days, source = await suggested_use_by_date(
        session,
        household_id=household_id,
        food_name=food_name,
        location=location,
        stocked_on=stocked_on,
    )
    return ShelfLifeSuggestionResponse(
        food_name=food_name,
        location=location,
        stocked_on=stocked_on,
        suggested_days=days,
        suggested_use_by=use_by,
        source=source,
    )
