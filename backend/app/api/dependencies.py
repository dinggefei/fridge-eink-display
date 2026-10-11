from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    Membership,
    MembershipRole,
    MembershipStatus,
    User,
)
from app.db.session import get_db_session
from app.services.access_tokens import InvalidAccessToken, decode_access_token


bearer_scheme = HTTPBearer(auto_error=False)
DbSession = Annotated[AsyncSession, Depends(get_db_session)]


async def get_current_user(
    session: DbSession,
    credentials: Annotated[
        HTTPAuthorizationCredentials | None,
        Depends(bearer_scheme),
    ],
) -> User:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="authentication required",
        )
    try:
        claims = decode_access_token(credentials.credentials)
    except InvalidAccessToken as error:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(error),
        ) from error

    user = await session.get(User, claims.user_id)
    if user is None or user.deleted_at is not None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="user no longer exists",
        )
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


async def require_household_member(
    session: AsyncSession,
    *,
    household_id: str,
    user_id: str,
) -> Membership:
    membership = await session.scalar(
        select(Membership).where(
            Membership.household_id == household_id,
            Membership.user_id == user_id,
            Membership.status == MembershipStatus.ACTIVE,
        )
    )
    if membership is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="household not found",
        )
    return membership


async def require_household_admin(
    session: AsyncSession,
    *,
    household_id: str,
    user_id: str,
) -> Membership:
    membership = await require_household_member(
        session,
        household_id=household_id,
        user_id=user_id,
    )
    if membership.role != MembershipRole.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="household admin permission required",
        )
    return membership
