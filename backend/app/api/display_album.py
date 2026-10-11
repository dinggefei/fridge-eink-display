from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, Response, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.api.dependencies import (
    CurrentUser,
    DbSession,
    require_household_member,
)
from app.db.base import new_id, utc_now
from app.db.models import (
    DisplayMode,
    DisplayPhoto,
    DisplayPhotoStatus,
    Household,
)
from app.services.display_photo_storage import get_display_photo_storage
from app.services.display_photos import (
    DisplayPhotoProcessingError,
    active_display_photo,
    process_display_photo,
)
from app.settings import get_settings


router = APIRouter(
    prefix="/v1/households/{household_id}/display-album",
    tags=["display-album"],
)


class DisplayPhotoResponse(BaseModel):
    id: str
    status: DisplayPhotoStatus
    sequence: int
    original_filename: str
    byte_size: int
    width: int
    height: int
    confirmed_at: datetime | None
    created_at: datetime
    is_active: bool
    image_path: str


class DisplayAlbumResponse(BaseModel):
    display_mode: DisplayMode
    rotation_hours: int
    active_photo_id: str | None
    max_photos: int
    photos: list[DisplayPhotoResponse]


class DisplayAlbumSettingsWrite(BaseModel):
    display_mode: DisplayMode | None = None
    rotation_hours: int | None = Field(default=None)
    active_photo_id: str | None = None


class DisplayPhotoOrderWrite(BaseModel):
    photo_ids: list[str] = Field(min_length=1, max_length=6)


async def _household(
    session: DbSession,
    user: CurrentUser,
    household_id: str,
    *,
    lock: bool = False,
) -> Household:
    await require_household_member(
        session,
        household_id=household_id,
        user_id=user.id,
    )
    statement = select(Household).where(Household.id == household_id)
    if lock:
        statement = statement.with_for_update()
    household = await session.scalar(statement)
    if household is None:
        raise HTTPException(status_code=404, detail="household not found")
    return household


async def _list_photos(
    session: DbSession,
    household_id: str,
) -> list[DisplayPhoto]:
    return list(
        await session.scalars(
            select(DisplayPhoto)
            .where(DisplayPhoto.household_id == household_id)
            .order_by(
                DisplayPhoto.sequence,
                DisplayPhoto.created_at,
                DisplayPhoto.id,
            )
        )
    )


def _photo_response(
    household_id: str,
    photo: DisplayPhoto,
    *,
    active_photo_id: str | None,
) -> DisplayPhotoResponse:
    return DisplayPhotoResponse(
        id=photo.id,
        status=photo.status,
        sequence=photo.sequence,
        original_filename=photo.original_filename,
        byte_size=photo.byte_size,
        width=photo.width,
        height=photo.height,
        confirmed_at=photo.confirmed_at,
        created_at=photo.created_at,
        is_active=photo.id == active_photo_id,
        image_path=(
            f"/v1/households/{household_id}/display-album/"
            f"photos/{photo.id}/image"
        ),
    )


async def _album_response(
    session: DbSession,
    household: Household,
) -> DisplayAlbumResponse:
    photos = await _list_photos(session, household.id)
    active = active_display_photo(household, photos)
    active_id = active.id if active is not None else None
    return DisplayAlbumResponse(
        display_mode=household.display_mode,
        rotation_hours=household.photo_rotation_hours,
        active_photo_id=active_id,
        max_photos=get_settings().display_photo_max_photos,
        photos=[
            _photo_response(
                household.id,
                photo,
                active_photo_id=active_id,
            )
            for photo in photos
        ],
    )


@router.get("", response_model=DisplayAlbumResponse)
async def read_display_album(
    household_id: str,
    session: DbSession,
    user: CurrentUser,
) -> DisplayAlbumResponse:
    household = await _household(session, user, household_id)
    return await _album_response(session, household)


@router.post(
    "/photos",
    response_model=DisplayPhotoResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_display_photo(
    household_id: str,
    session: DbSession,
    user: CurrentUser,
    image: UploadFile = File(...),
) -> DisplayPhotoResponse:
    household = await _household(session, user, household_id, lock=True)
    settings = get_settings()
    existing_count = await session.scalar(
        select(func.count(DisplayPhoto.id)).where(
            DisplayPhoto.household_id == household_id
        )
    )
    if (existing_count or 0) >= settings.display_photo_max_photos:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"a household can store at most {settings.display_photo_max_photos} photos",
        )

    source_type = (image.content_type or "").lower()
    if source_type not in {
        "application/octet-stream",
        "image/jpeg",
        "image/jpg",
        "image/pjpeg",
        "image/png",
        "image/x-png",
    }:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="only JPG and PNG images are supported",
        )
    try:
        raw = await image.read(settings.display_photo_max_image_bytes + 1)
    finally:
        await image.close()
    if len(raw) > settings.display_photo_max_image_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="image exceeds the 5 MB limit",
        )
    try:
        processed = await asyncio.to_thread(
            process_display_photo,
            raw,
            max_bytes=settings.display_photo_max_image_bytes,
        )
    except DisplayPhotoProcessingError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error

    sequence = await session.scalar(
        select(func.max(DisplayPhoto.sequence)).where(
            DisplayPhoto.household_id == household_id
        )
    )
    photo_id = new_id()
    object_key = f"display-photos/{household_id}/{photo_id}.png"
    filename = Path(image.filename or "photo").name[:255] or "photo"
    storage = get_display_photo_storage()
    try:
        await storage.put(
            object_key,
            processed.png_bytes,
            content_type="image/png",
        )
    except Exception as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="display photo storage is temporarily unavailable",
        ) from error

    photo = DisplayPhoto(
        id=photo_id,
        household_id=household_id,
        created_by_user_id=user.id,
        status=DisplayPhotoStatus.PENDING,
        sequence=(sequence if sequence is not None else -1) + 1,
        object_key=object_key,
        original_filename=filename,
        content_type="image/png",
        sha256=processed.sha256,
        byte_size=len(processed.png_bytes),
        width=processed.width,
        height=processed.height,
    )
    session.add(photo)
    try:
        await session.commit()
    except Exception:
        await storage.delete(object_key)
        raise
    await session.refresh(photo)
    return _photo_response(
        household_id,
        photo,
        active_photo_id=None,
    )


@router.get("/photos/{photo_id}/image", response_class=Response)
async def read_display_photo_image(
    household_id: str,
    photo_id: str,
    session: DbSession,
    user: CurrentUser,
) -> Response:
    await _household(session, user, household_id)
    photo = await session.scalar(
        select(DisplayPhoto).where(
            DisplayPhoto.id == photo_id,
            DisplayPhoto.household_id == household_id,
        )
    )
    if photo is None:
        raise HTTPException(status_code=404, detail="display photo not found")
    try:
        data = await get_display_photo_storage().get(photo.object_key)
    except Exception as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="display photo storage is temporarily unavailable",
        ) from error
    return Response(
        data,
        media_type=photo.content_type,
        headers={
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.post(
    "/photos/{photo_id}/confirm",
    response_model=DisplayAlbumResponse,
)
async def confirm_display_photo(
    household_id: str,
    photo_id: str,
    session: DbSession,
    user: CurrentUser,
) -> DisplayAlbumResponse:
    household = await _household(session, user, household_id, lock=True)
    photo = await session.scalar(
        select(DisplayPhoto)
        .where(
            DisplayPhoto.id == photo_id,
            DisplayPhoto.household_id == household_id,
        )
        .with_for_update()
    )
    if photo is None:
        raise HTTPException(status_code=404, detail="display photo not found")
    if photo.status == DisplayPhotoStatus.PENDING:
        photo.status = DisplayPhotoStatus.CONFIRMED
        photo.confirmed_at = utc_now()
        if household.active_display_photo_id is None:
            household.active_display_photo_id = photo.id
            household.photo_rotation_started_at = utc_now()
        await session.commit()
        await session.refresh(household)
    return await _album_response(session, household)


@router.delete(
    "/photos/{photo_id}",
    response_model=DisplayAlbumResponse,
)
async def delete_display_photo(
    household_id: str,
    photo_id: str,
    session: DbSession,
    user: CurrentUser,
) -> DisplayAlbumResponse:
    household = await _household(session, user, household_id, lock=True)
    photo = await session.scalar(
        select(DisplayPhoto)
        .where(
            DisplayPhoto.id == photo_id,
            DisplayPhoto.household_id == household_id,
        )
        .with_for_update()
    )
    if photo is None:
        raise HTTPException(status_code=404, detail="display photo not found")
    try:
        await get_display_photo_storage().delete(photo.object_key)
    except Exception as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="display photo storage is temporarily unavailable",
        ) from error
    await session.delete(photo)
    await session.flush()

    remaining = list(
        await session.scalars(
            select(DisplayPhoto)
            .where(
                DisplayPhoto.household_id == household_id,
                DisplayPhoto.status == DisplayPhotoStatus.CONFIRMED,
            )
            .order_by(DisplayPhoto.sequence, DisplayPhoto.created_at)
        )
    )
    if household.active_display_photo_id == photo_id:
        household.active_display_photo_id = remaining[0].id if remaining else None
        household.photo_rotation_started_at = utc_now() if remaining else None
    if not remaining and household.display_mode == DisplayMode.ALBUM:
        household.display_mode = DisplayMode.INVENTORY
    await session.commit()
    await session.refresh(household)
    return await _album_response(session, household)


@router.put("/order", response_model=DisplayAlbumResponse)
async def replace_display_photo_order(
    household_id: str,
    payload: DisplayPhotoOrderWrite,
    session: DbSession,
    user: CurrentUser,
) -> DisplayAlbumResponse:
    household = await _household(session, user, household_id, lock=True)
    photos = list(
        await session.scalars(
            select(DisplayPhoto)
            .where(
                DisplayPhoto.household_id == household_id,
                DisplayPhoto.status == DisplayPhotoStatus.CONFIRMED,
            )
            .with_for_update()
        )
    )
    if len(payload.photo_ids) != len(set(payload.photo_ids)):
        raise HTTPException(status_code=422, detail="photo order contains duplicates")
    if set(payload.photo_ids) != {photo.id for photo in photos}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="photo order must contain every confirmed photo exactly once",
        )
    by_id = {photo.id: photo for photo in photos}
    for sequence, photo_id in enumerate(payload.photo_ids):
        by_id[photo_id].sequence = sequence
    household.photo_rotation_started_at = utc_now()
    await session.commit()
    await session.refresh(household)
    return await _album_response(session, household)


@router.put("/settings", response_model=DisplayAlbumResponse)
async def replace_display_album_settings(
    household_id: str,
    payload: DisplayAlbumSettingsWrite,
    session: DbSession,
    user: CurrentUser,
) -> DisplayAlbumResponse:
    household = await _household(session, user, household_id, lock=True)
    confirmed = list(
        await session.scalars(
            select(DisplayPhoto)
            .where(
                DisplayPhoto.household_id == household_id,
                DisplayPhoto.status == DisplayPhotoStatus.CONFIRMED,
            )
            .order_by(DisplayPhoto.sequence, DisplayPhoto.created_at)
        )
    )
    if payload.rotation_hours is not None and payload.rotation_hours not in {
        1,
        3,
        6,
        12,
        24,
    }:
        raise HTTPException(
            status_code=422,
            detail="rotation_hours must be 1, 3, 6, 12 or 24",
        )
    if payload.display_mode == DisplayMode.ALBUM and not confirmed:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="confirm at least one photo before enabling album mode",
        )
    if payload.active_photo_id is not None:
        selected = next(
            (photo for photo in confirmed if photo.id == payload.active_photo_id),
            None,
        )
        if selected is None:
            raise HTTPException(
                status_code=404,
                detail="confirmed display photo not found",
            )
        household.active_display_photo_id = selected.id
        household.display_mode = DisplayMode.ALBUM
    if payload.display_mode is not None:
        household.display_mode = payload.display_mode
    if payload.rotation_hours is not None:
        household.photo_rotation_hours = payload.rotation_hours
    household.photo_rotation_started_at = utc_now()
    await session.commit()
    await session.refresh(household)
    return await _album_response(session, household)
