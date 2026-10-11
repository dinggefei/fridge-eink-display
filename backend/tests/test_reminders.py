from __future__ import annotations

import asyncio
from datetime import date, datetime, time, timezone
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.base import Base
from app.db.models import (
    FoodBatch,
    Household,
    Membership,
    MembershipRole,
    MembershipStatus,
    ReminderPreference,
    SubscriptionDelivery,
    User,
)
from app.domain.inventory import FoodStatus, StorageLocation
from app.services.reminders import dispatch_due_reminders
from app.settings import get_settings


def test_mock_reminder_delivery_consumes_one_subscription_grant(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    monkeypatch.setenv("REMINDER_DELIVERY_MODE", "mock")
    get_settings.cache_clear()

    async def scenario() -> None:
        engine = create_async_engine(
            f"sqlite+aiosqlite:///{tmp_path / 'reminders.db'}"
        )
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        async with sessions() as session:
            user = User(openid="reminder-openid", nickname="提醒用户")
            session.add(user)
            await session.flush()
            household = Household(name="提醒家庭", admin_user_id=user.id)
            session.add(household)
            await session.flush()
            session.add(
                Membership(
                    household_id=household.id,
                    user_id=user.id,
                    role=MembershipRole.ADMIN,
                    status=MembershipStatus.ACTIVE,
                )
            )
            session.add(
                ReminderPreference(
                    user_id=user.id,
                    household_id=household.id,
                    enabled=True,
                    reminder_time=time(20, 0),
                    threshold_days=3,
                    subscription_grants=1,
                )
            )
            session.add(
                FoodBatch(
                    household_id=household.id,
                    standard_name="临期牛奶",
                    original_name="临期牛奶",
                    quantity=Decimal("1"),
                    unit="盒",
                    location=StorageLocation.REFRIGERATED,
                    stocked_on=date(2026, 7, 30),
                    suggested_use_by=date(2026, 7, 31),
                    status=FoodStatus.EAT_TODAY,
                )
            )
            await session.commit()

            delivered = await dispatch_due_reminders(
                session,
                now=datetime(2026, 7, 31, 13, 0, tzinfo=timezone.utc),
            )
            assert delivered == 1
            preference = await session.scalar(select(ReminderPreference))
            delivery = await session.scalar(select(SubscriptionDelivery))
            assert preference is not None
            assert preference.subscription_grants == 0
            assert preference.last_reminded_on == date(2026, 7, 31)
            assert delivery is not None
            assert delivery.status == "sent"
            assert delivery.item_count == 1
        await engine.dispose()

    asyncio.run(scenario())
    get_settings.cache_clear()
