from __future__ import annotations

import secrets

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import delete, func, or_, select, update

from app.api.auth import SessionResponse, _session_response
from app.api.dependencies import CurrentUser, DbSession, require_household_member
from app.db.base import utc_now
from app.db.models import (
    Device,
    DeviceProvisioningSession,
    DeviceStatus,
    DisplayPhoto,
    FoodBatch,
    Household,
    HouseholdInvitation,
    ImportTask,
    InventoryEvent,
    MarketAsset,
    Membership,
    MembershipRole,
    MembershipStatus,
    ReminderPreference,
    ShelfLifePreference,
    SubscriptionDelivery,
)
from app.services.recognition_tasks import delete_task_images
from app.services.display_photo_storage import get_display_photo_storage


router = APIRouter(prefix="/v1", tags=["privacy"])


@router.post(
    "/households/{household_id}/leave",
    response_model=SessionResponse,
)
async def leave_household(
    household_id: str,
    user: CurrentUser,
    session: DbSession,
) -> SessionResponse:
    membership = await require_household_member(
        session,
        household_id=household_id,
        user_id=user.id,
    )
    if membership.role == MembershipRole.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "家庭管理员不能直接退出，"
                "请使用删除个人账号或先处理家庭成员"
            ),
        )

    replacement = await session.scalar(
        select(Membership.household_id)
        .where(
            Membership.user_id == user.id,
            Membership.status == MembershipStatus.ACTIVE,
            Membership.household_id != household_id,
        )
        .order_by(Membership.joined_at, Membership.household_id)
    )
    if replacement is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "至少需要保留一个家庭；"
                "如需清除全部数据，请删除个人账号"
            ),
        )

    await session.execute(
        delete(ReminderPreference).where(
            ReminderPreference.user_id == user.id,
            ReminderPreference.household_id == household_id,
        )
    )
    await session.execute(
        delete(ShelfLifePreference).where(
            ShelfLifePreference.user_id == user.id,
            ShelfLifePreference.household_id == household_id,
        )
    )
    await session.execute(
        delete(SubscriptionDelivery).where(
            SubscriptionDelivery.user_id == user.id,
            SubscriptionDelivery.household_id == household_id,
        )
    )
    await session.delete(membership)
    user.recent_household_id = replacement
    await session.commit()
    return await _session_response(session, user)


@router.delete("/me", status_code=status.HTTP_204_NO_CONTENT)
async def delete_personal_account(
    user: CurrentUser,
    session: DbSession,
) -> None:
    owned_households = (
        await session.scalars(
            select(Household)
            .where(Household.admin_user_id == user.id)
            .with_for_update()
        )
    ).all()
    owned_household_ids = [household.id for household in owned_households]

    for household in owned_households:
        other_member_count = await session.scalar(
            select(func.count(Membership.user_id)).where(
                Membership.household_id == household.id,
                Membership.status == MembershipStatus.ACTIVE,
                Membership.user_id != user.id,
            )
        )
        if other_member_count:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"家庭“{household.name}”仍有其他成员，"
                    "请先在家庭管理中移除其他成员"
                ),
            )

    task_filter = ImportTask.created_by_user_id == user.id
    if owned_household_ids:
        task_filter = or_(
            task_filter,
            ImportTask.household_id.in_(owned_household_ids),
        )
    task_ids = list(
        await session.scalars(select(ImportTask.id).where(task_filter))
    )
    for task_id in task_ids:
        await delete_task_images(session, task_id)
    if task_ids:
        await session.execute(
            delete(ImportTask).where(ImportTask.id.in_(task_ids))
        )

    personal_or_owned_filters = {
        DeviceProvisioningSession: (
            DeviceProvisioningSession.created_by_user_id == user.id
        ),
        ReminderPreference: ReminderPreference.user_id == user.id,
        ShelfLifePreference: ShelfLifePreference.user_id == user.id,
        SubscriptionDelivery: SubscriptionDelivery.user_id == user.id,
    }
    for model, row_filter in personal_or_owned_filters.items():
        if owned_household_ids:
            row_filter = or_(
                row_filter,
                model.household_id.in_(owned_household_ids),
            )
        await session.execute(delete(model).where(row_filter))

    invitation_filter = or_(
        HouseholdInvitation.created_by_user_id == user.id,
        HouseholdInvitation.used_by_user_id == user.id,
    )
    if owned_household_ids:
        invitation_filter = or_(
            invitation_filter,
            HouseholdInvitation.household_id.in_(owned_household_ids),
        )
    await session.execute(
        delete(HouseholdInvitation).where(invitation_filter)
    )

    if owned_household_ids:
        display_photos = list(
            await session.scalars(
                select(DisplayPhoto).where(
                    DisplayPhoto.household_id.in_(owned_household_ids)
                )
            )
        )
        try:
            for photo in display_photos:
                await get_display_photo_storage().delete(photo.object_key)
        except Exception as error:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="display photo storage is temporarily unavailable",
            ) from error
        await session.execute(
            delete(DisplayPhoto).where(
                DisplayPhoto.household_id.in_(owned_household_ids)
            )
        )
        await session.execute(
            update(Device)
            .where(Device.household_id.in_(owned_household_ids))
            .values(
                household_id=None,
                status=DeviceStatus.UNBOUND,
                frame_version=None,
                frame_etag=None,
                last_seen_at=None,
            )
        )
        await session.execute(
            delete(InventoryEvent).where(
                InventoryEvent.household_id.in_(owned_household_ids)
            )
        )
        await session.execute(
            delete(FoodBatch).where(
                FoodBatch.household_id.in_(owned_household_ids)
            )
        )
        await session.execute(
            delete(Membership).where(
                Membership.household_id.in_(owned_household_ids)
            )
        )
        await session.execute(
            delete(Household).where(Household.id.in_(owned_household_ids))
        )

    await session.execute(
        update(DisplayPhoto)
        .where(DisplayPhoto.created_by_user_id == user.id)
        .values(created_by_user_id=None)
    )
    await session.execute(
        update(MarketAsset)
        .where(MarketAsset.created_by_user_id == user.id)
        .values(created_by_user_id=None)
    )

    await session.execute(
        delete(Membership).where(Membership.user_id == user.id)
    )
    user.openid = f"deleted:{user.id}:{secrets.token_hex(8)}"
    user.nickname = None
    user.avatar_url = None
    user.recent_household_id = None
    user.deleted_at = utc_now()
    await session.commit()
