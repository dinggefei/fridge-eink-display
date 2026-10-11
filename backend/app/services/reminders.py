from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import utc_now
from app.db.models import (
    FoodBatch,
    Membership,
    MembershipStatus,
    ReminderPreference,
    SubscriptionDelivery,
    User,
)
from app.services.mini_program_code import (
    MiniProgramCodeError,
    get_wechat_access_token,
)
from app.settings import get_settings


SHANGHAI = ZoneInfo("Asia/Shanghai")


class ReminderDeliveryError(RuntimeError):
    pass


def _local_now(now: datetime | None = None) -> datetime:
    value = now or utc_now()
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(SHANGHAI)


async def _send_wechat_subscription(
    *,
    openid: str,
    item_names: list[str],
    item_count: int,
    due_date: date,
) -> None:
    settings = get_settings()
    try:
        access_token = await get_wechat_access_token()
    except MiniProgramCodeError as error:
        raise ReminderDeliveryError(str(error)) from error
    summary = "、".join(item_names[:2])
    if len(summary) > 20:
        summary = summary[:20]
    data = {
        settings.wechat_reminder_items_key: {"value": summary or "临期食材"},
        settings.wechat_reminder_count_key: {"value": str(item_count)},
        settings.wechat_reminder_date_key: {"value": due_date.isoformat()},
    }
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            response = await client.post(
                (
                    f"{settings.wechat_api_base_url.rstrip('/')}"
                    "/cgi-bin/message/subscribe/send"
                ),
                params={"access_token": access_token},
                json={
                    "touser": openid,
                    "template_id": settings.wechat_reminder_template_id,
                    "page": settings.wechat_reminder_page,
                    "miniprogram_state": (
                        "formal"
                        if settings.app_env.lower() == "production"
                        else "developer"
                    ),
                    "lang": "zh_CN",
                    "data": data,
                },
            )
            response.raise_for_status()
        except httpx.HTTPError as error:
            raise ReminderDeliveryError(
                "WeChat subscription service is unavailable"
            ) from error
    payload = response.json()
    if payload.get("errcode") != 0:
        raise ReminderDeliveryError(
            f"WeChat subscription send failed ({payload.get('errcode')})"
        )


async def dispatch_due_reminders(
    session: AsyncSession,
    *,
    now: datetime | None = None,
) -> int:
    settings = get_settings()
    if settings.reminder_delivery_mode == "disabled":
        return 0

    local_now = _local_now(now)
    today = local_now.date()
    rows = (
        await session.execute(
            select(ReminderPreference, User)
            .join(User, User.id == ReminderPreference.user_id)
            .join(
                Membership,
                (Membership.user_id == ReminderPreference.user_id)
                & (
                    Membership.household_id
                    == ReminderPreference.household_id
                ),
            )
            .where(
                ReminderPreference.enabled.is_(True),
                ReminderPreference.subscription_grants > 0,
                Membership.status == MembershipStatus.ACTIVE,
                User.deleted_at.is_(None),
            )
        )
    ).all()
    sent_count = 0
    for preference, user in rows:
        if preference.reminder_time > local_now.time().replace(tzinfo=None):
            continue
        if preference.last_reminded_on == today:
            continue
        limit_date = today + timedelta(days=preference.threshold_days)
        foods = (
            await session.scalars(
                select(FoodBatch)
                .where(
                    FoodBatch.household_id == preference.household_id,
                    FoodBatch.deleted_at.is_(None),
                    FoodBatch.quantity > 0,
                    FoodBatch.suggested_use_by.is_not(None),
                    FoodBatch.suggested_use_by <= limit_date,
                )
                .order_by(FoodBatch.suggested_use_by, FoodBatch.standard_name)
            )
        ).all()
        if not foods:
            preference.last_reminded_on = today
            continue

        delivery = SubscriptionDelivery(
            user_id=user.id,
            household_id=preference.household_id,
            template_id=settings.wechat_reminder_template_id or None,
            scheduled_for=local_now.astimezone(timezone.utc),
            status="pending",
            item_count=len(foods),
        )
        session.add(delivery)
        try:
            if settings.reminder_delivery_mode == "wechat":
                await _send_wechat_subscription(
                    openid=user.openid,
                    item_names=[food.standard_name for food in foods],
                    item_count=len(foods),
                    due_date=foods[0].suggested_use_by or today,
                )
            delivery.status = "sent"
            delivery.sent_at = utc_now()
            preference.subscription_grants -= 1
            preference.last_reminded_on = today
            sent_count += 1
        except ReminderDeliveryError as error:
            delivery.status = "failed"
            delivery.error_message = str(error)
            preference.last_reminded_on = today
    await session.commit()
    return sent_count


async def reminder_delivery_counts(
    session: AsyncSession,
    *,
    user_id: str,
    household_id: str,
) -> dict[str, int]:
    rows = (
        await session.execute(
            select(
                SubscriptionDelivery.status,
                func.count(SubscriptionDelivery.id),
            )
            .where(
                SubscriptionDelivery.user_id == user_id,
                SubscriptionDelivery.household_id == household_id,
            )
            .group_by(SubscriptionDelivery.status)
        )
    ).all()
    return {status: count for status, count in rows}
