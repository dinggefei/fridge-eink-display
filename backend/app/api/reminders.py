from __future__ import annotations

from datetime import time

from fastapi import APIRouter
from pydantic import BaseModel, Field, field_serializer
from sqlalchemy import select

from app.api.dependencies import (
    CurrentUser,
    DbSession,
    require_household_member,
)
from app.db.models import ReminderPreference
from app.services.reminders import reminder_delivery_counts
from app.settings import get_settings


router = APIRouter(
    prefix="/v1/households/{household_id}/reminders",
    tags=["reminders"],
)


class ReminderPreferenceUpdate(BaseModel):
    enabled: bool
    reminder_time: time
    threshold_days: int = Field(ge=1, le=7)


class ReminderPreferenceResponse(BaseModel):
    enabled: bool
    reminder_time: time
    threshold_days: int
    subscription_grants: int
    delivery_mode: str
    template_id: str
    delivery_counts: dict[str, int]

    @field_serializer("reminder_time")
    def serialize_time(self, value: time) -> str:
        return value.strftime("%H:%M")


class SubscriptionGrantResponse(BaseModel):
    subscription_grants: int


async def _get_or_create_preference(
    session: DbSession,
    *,
    user_id: str,
    household_id: str,
) -> ReminderPreference:
    preference = await session.scalar(
        select(ReminderPreference).where(
            ReminderPreference.user_id == user_id,
            ReminderPreference.household_id == household_id,
        )
    )
    if preference is None:
        preference = ReminderPreference(
            user_id=user_id,
            household_id=household_id,
        )
        session.add(preference)
        await session.flush()
    return preference


async def _response(
    session: DbSession,
    *,
    preference: ReminderPreference,
) -> ReminderPreferenceResponse:
    settings = get_settings()
    counts = await reminder_delivery_counts(
        session,
        user_id=preference.user_id,
        household_id=preference.household_id,
    )
    return ReminderPreferenceResponse(
        enabled=preference.enabled,
        reminder_time=preference.reminder_time,
        threshold_days=preference.threshold_days,
        subscription_grants=preference.subscription_grants,
        delivery_mode=settings.reminder_delivery_mode,
        template_id=settings.wechat_reminder_template_id,
        delivery_counts=counts,
    )


@router.get("", response_model=ReminderPreferenceResponse)
async def read_reminder_preference(
    household_id: str,
    user: CurrentUser,
    session: DbSession,
) -> ReminderPreferenceResponse:
    await require_household_member(
        session,
        household_id=household_id,
        user_id=user.id,
    )
    preference = await _get_or_create_preference(
        session,
        user_id=user.id,
        household_id=household_id,
    )
    await session.commit()
    return await _response(session, preference=preference)


@router.put("", response_model=ReminderPreferenceResponse)
async def update_reminder_preference(
    household_id: str,
    payload: ReminderPreferenceUpdate,
    user: CurrentUser,
    session: DbSession,
) -> ReminderPreferenceResponse:
    await require_household_member(
        session,
        household_id=household_id,
        user_id=user.id,
    )
    preference = await _get_or_create_preference(
        session,
        user_id=user.id,
        household_id=household_id,
    )
    preference.enabled = payload.enabled
    preference.reminder_time = payload.reminder_time
    preference.threshold_days = payload.threshold_days
    await session.commit()
    return await _response(session, preference=preference)


@router.post(
    "/subscription-grants",
    response_model=SubscriptionGrantResponse,
)
async def record_subscription_grant(
    household_id: str,
    user: CurrentUser,
    session: DbSession,
) -> SubscriptionGrantResponse:
    await require_household_member(
        session,
        household_id=household_id,
        user_id=user.id,
    )
    preference = await _get_or_create_preference(
        session,
        user_id=user.id,
        household_id=household_id,
    )
    preference.subscription_grants += 1
    await session.commit()
    return SubscriptionGrantResponse(
        subscription_grants=preference.subscription_grants
    )
