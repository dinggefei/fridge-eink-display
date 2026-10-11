from __future__ import annotations

from datetime import date, datetime

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select

from app.api.dependencies import CurrentUser, DbSession
from app.db.models import (
    Device,
    DeviceStatus,
    FoodBatch,
    Household,
    InventoryAction,
    InventoryEvent,
    Membership,
    MembershipRole,
    MembershipStatus,
    User,
)
from app.domain.inventory import calculate_food_status
from app.services.access_tokens import create_access_token
from app.services.device_secrets import (
    device_secret_hash,
    encrypt_device_secret,
)
from app.services.inventory_store import get_inventory_store
from app.services.wechat_login import WechatLoginError, exchange_login_code
from app.settings import get_settings


router = APIRouter(prefix="/v1", tags=["auth"])


class WechatLoginRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    code: str = Field(min_length=1, max_length=256)


class DevLoginRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    nickname: str = Field(default="本地开发用户", min_length=1, max_length=100)


class UserResponse(BaseModel):
    id: str
    nickname: str | None
    avatar_url: str | None


class HouseholdResponse(BaseModel):
    id: str
    name: str
    role: MembershipRole
    member_count: int = 1
    inventory_revision: int
    updated_at: datetime


class SessionResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserResponse
    households: list[HouseholdResponse]
    current_household_id: str


async def _get_or_create_user(
    session: DbSession,
    *,
    openid: str,
    nickname: str | None,
) -> User:
    user = await session.scalar(select(User).where(User.openid == openid))
    if user is not None:
        if nickname and not user.nickname:
            user.nickname = nickname
        return user

    user = User(openid=openid, nickname=nickname)
    session.add(user)
    await session.flush()

    household = Household(
        name="我的冰箱",
        admin_user_id=user.id,
    )
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
    user.recent_household_id = household.id
    return user


async def _session_response(
    session: DbSession,
    user: User,
) -> SessionResponse:
    rows = (
        await session.execute(
            select(Household, Membership.role)
            .join(
                Membership,
                Membership.household_id == Household.id,
            )
            .where(
                Membership.user_id == user.id,
                Membership.status == MembershipStatus.ACTIVE,
            )
            .order_by(Membership.joined_at, Household.id)
        )
    ).all()
    if not rows:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="user has no active household",
        )
    valid_household_ids = {household.id for household, _ in rows}
    member_counts = dict(
        (
            await session.execute(
                select(Membership.household_id, func.count(Membership.user_id))
                .where(Membership.status == MembershipStatus.ACTIVE)
                .group_by(Membership.household_id)
            )
        ).all()
    )
    current_household_id = (
        user.recent_household_id
        if user.recent_household_id in valid_household_ids
        else rows[0][0].id
    )
    return SessionResponse(
        access_token=create_access_token(user.id),
        user=UserResponse(
            id=user.id,
            nickname=user.nickname,
            avatar_url=user.avatar_url,
        ),
        households=[
            HouseholdResponse(
                id=household.id,
                name=household.name,
                role=role,
                member_count=member_counts.get(household.id, 1),
                inventory_revision=household.inventory_revision,
                updated_at=household.updated_at,
            )
            for household, role in rows
        ],
        current_household_id=current_household_id,
    )


async def _prepare_local_development_household(
    session: DbSession,
    user: User,
) -> None:
    settings = get_settings()
    household_id = user.recent_household_id
    if not household_id:
        return

    item_count = await session.scalar(
        select(func.count(FoodBatch.id)).where(
            FoodBatch.household_id == household_id,
            FoodBatch.deleted_at.is_(None),
        )
    )
    if item_count == 0:
        snapshot = get_inventory_store().snapshot()
        household = await session.get(Household, household_id)
        if household is not None:
            household.name = snapshot.household_name
        for item in snapshot.items:
            batch = FoodBatch(
                household_id=household_id,
                standard_name=item.name,
                original_name=item.name,
                quantity=item.quantity,
                unit=item.unit,
                location=item.location,
                stocked_on=item.stocked_on,
                suggested_use_by=item.suggested_use_by,
                status=calculate_food_status(
                    item.suggested_use_by,
                    today=date.today(),
                ),
            )
            session.add(batch)
            await session.flush()
            session.add(
                InventoryEvent(
                    household_id=household_id,
                    batch_id=batch.id,
                    actor_user_id=user.id,
                    action=InventoryAction.ADD,
                    quantity=batch.quantity,
                    idempotency_key=f"development-import-{item.id}",
                    event_data={"source": "legacy-json"},
                )
            )

    device = await session.scalar(
        select(Device).where(Device.device_code == settings.device_code)
    )
    secret_hash = device_secret_hash(settings.device_secret)
    if device is None:
        session.add(
            Device(
                device_code=settings.device_code,
                device_secret_hash=secret_hash,
                device_secret_ciphertext=encrypt_device_secret(
                    settings.device_secret,
                    settings.device_code,
                ),
                household_id=household_id,
                status=DeviceStatus.ONLINE,
            )
        )
    elif device.household_id is None:
        device.household_id = household_id
        device.status = DeviceStatus.ONLINE
    if device is not None and device.device_secret_ciphertext is None:
        device.device_secret_ciphertext = encrypt_device_secret(
            settings.device_secret,
            settings.device_code,
        )


@router.post("/auth/wechat", response_model=SessionResponse)
async def login_with_wechat(
    payload: WechatLoginRequest,
    session: DbSession,
) -> SessionResponse:
    try:
        identity = await exchange_login_code(payload.code)
    except WechatLoginError as error:
        status_code = (
            status.HTTP_503_SERVICE_UNAVAILABLE
            if "not configured" in str(error)
            else status.HTTP_401_UNAUTHORIZED
        )
        raise HTTPException(status_code=status_code, detail=str(error)) from error

    async with session.begin():
        user = await _get_or_create_user(
            session,
            openid=identity.openid,
            nickname=None,
        )
    return await _session_response(session, user)


@router.post("/auth/dev-login", response_model=SessionResponse)
async def login_for_local_development(
    payload: DevLoginRequest,
    session: DbSession,
) -> SessionResponse:
    settings = get_settings()
    if settings.app_env.lower() == "production" or not settings.allow_dev_login:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

    async with session.begin():
        user = await _get_or_create_user(
            session,
            openid="development-local-user",
            nickname=payload.nickname,
        )
        await _prepare_local_development_household(session, user)
    return await _session_response(session, user)


@router.get("/me", response_model=SessionResponse)
async def read_current_session(
    user: CurrentUser,
    session: DbSession,
) -> SessionResponse:
    return await _session_response(session, user)
