from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from app.api.auth import SessionResponse, _session_response
from app.api.dependencies import (
    CurrentUser,
    DbSession,
    require_household_admin,
    require_household_member,
)
from app.db.base import utc_now
from app.db.models import (
    Household,
    HouseholdInvitation,
    Membership,
    MembershipRole,
    MembershipStatus,
    User,
)


router = APIRouter(prefix="/v1", tags=["households"])
INVITATION_ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"


class HouseholdSwitchRequest(BaseModel):
    household_id: str = Field(min_length=1, max_length=36)


class InvitationResponse(BaseModel):
    code: str
    expires_at: datetime


class JoinHouseholdRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    invitation_code: str = Field(min_length=6, max_length=32)


class MemberResponse(BaseModel):
    user_id: str
    nickname: str | None
    avatar_url: str | None
    role: MembershipRole
    joined_at: datetime


def _normalize_code(code: str) -> str:
    return "".join(character for character in code.upper() if character.isalnum())


def _code_hash(code: str) -> str:
    return hashlib.sha256(_normalize_code(code).encode("utf-8")).hexdigest()


def _generate_code() -> str:
    raw = "".join(secrets.choice(INVITATION_ALPHABET) for _ in range(8))
    return f"{raw[:4]}-{raw[4:]}"


@router.get(
    "/households/{household_id}/members",
    response_model=list[MemberResponse],
)
async def list_household_members(
    household_id: str,
    user: CurrentUser,
    session: DbSession,
) -> list[MemberResponse]:
    await require_household_member(
        session,
        household_id=household_id,
        user_id=user.id,
    )
    rows = (
        await session.execute(
            select(Membership, User)
            .join(User, User.id == Membership.user_id)
            .where(
                Membership.household_id == household_id,
                Membership.status == MembershipStatus.ACTIVE,
            )
            .order_by(Membership.joined_at, Membership.user_id)
        )
    ).all()
    return [
        MemberResponse(
            user_id=member.id,
            nickname=member.nickname,
            avatar_url=member.avatar_url,
            role=membership.role,
            joined_at=membership.joined_at,
        )
        for membership, member in rows
    ]


@router.post(
    "/households/{household_id}/invitations",
    response_model=InvitationResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_household_invitation(
    household_id: str,
    user: CurrentUser,
    session: DbSession,
) -> InvitationResponse:
    await require_household_admin(
        session,
        household_id=household_id,
        user_id=user.id,
    )
    household = await session.get(Household, household_id)
    if household is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

    expires_at = utc_now() + timedelta(hours=24)
    for _ in range(5):
        code = _generate_code()
        existing = await session.scalar(
            select(HouseholdInvitation.id).where(
                HouseholdInvitation.code_hash == _code_hash(code)
            )
        )
        if existing is None:
            break
    else:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="could not generate invitation code",
        )

    session.add(
        HouseholdInvitation(
            household_id=household_id,
            created_by_user_id=user.id,
            code_hash=_code_hash(code),
            expires_at=expires_at,
        )
    )
    await session.commit()
    return InvitationResponse(code=code, expires_at=expires_at)


@router.post("/households/join", response_model=SessionResponse)
async def join_household(
    payload: JoinHouseholdRequest,
    user: CurrentUser,
    session: DbSession,
) -> SessionResponse:
    now = datetime.now(timezone.utc)
    invitation = await session.scalar(
        select(HouseholdInvitation)
        .where(HouseholdInvitation.code_hash == _code_hash(payload.invitation_code))
        .with_for_update()
    )
    if invitation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="invitation code is invalid",
        )
    expires_at = invitation.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if invitation.used_at is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="invitation code has already been used",
        )
    if expires_at <= now:
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="invitation code has expired",
        )

    membership = await session.get(
        Membership,
        (invitation.household_id, user.id),
    )
    if membership is not None and membership.status == MembershipStatus.ACTIVE:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="already a member of this household",
        )
    if membership is None:
        membership = Membership(
            household_id=invitation.household_id,
            user_id=user.id,
            role=MembershipRole.MEMBER,
            status=MembershipStatus.ACTIVE,
            joined_at=now,
        )
        session.add(membership)
    else:
        membership.role = MembershipRole.MEMBER
        membership.status = MembershipStatus.ACTIVE
        membership.joined_at = now

    invitation.used_at = now
    invitation.used_by_user_id = user.id
    user.recent_household_id = invitation.household_id
    await session.commit()
    return await _session_response(session, user)


@router.post("/me/current-household", response_model=SessionResponse)
async def switch_current_household(
    payload: HouseholdSwitchRequest,
    user: CurrentUser,
    session: DbSession,
) -> SessionResponse:
    await require_household_member(
        session,
        household_id=payload.household_id,
        user_id=user.id,
    )
    user.recent_household_id = payload.household_id
    await session.commit()
    return await _session_response(session, user)


@router.delete(
    "/households/{household_id}/members/{member_user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def remove_household_member(
    household_id: str,
    member_user_id: str,
    user: CurrentUser,
    session: DbSession,
) -> None:
    await require_household_admin(
        session,
        household_id=household_id,
        user_id=user.id,
    )
    if member_user_id == user.id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="household admin cannot remove self",
        )
    membership = await session.get(
        Membership,
        (household_id, member_user_id),
    )
    if membership is None or membership.status != MembershipStatus.ACTIVE:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="member not found",
        )
    if membership.role == MembershipRole.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="household admin cannot be removed",
        )

    membership.status = MembershipStatus.REMOVED
    removed_user = await session.get(User, member_user_id)
    if (
        removed_user is not None
        and removed_user.recent_household_id == household_id
    ):
        replacement = await session.scalar(
            select(Membership.household_id)
            .where(
                Membership.user_id == member_user_id,
                Membership.status == MembershipStatus.ACTIVE,
                Membership.household_id != household_id,
            )
            .order_by(Membership.joined_at)
        )
        removed_user.recent_household_id = replacement
    await session.commit()
