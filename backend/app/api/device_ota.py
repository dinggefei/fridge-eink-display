from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Body, HTTPException, Request, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app.api.dependencies import DbSession
from app.db.base import utc_now
from app.db.models import (
    FirmwareRelease,
    FirmwareUpdateEvent,
    FirmwareUpdateEventType,
)
from app.services.device_auth import verify_device_request
from app.services.device_ota import release_binary_path, release_targets_device


router = APIRouter(prefix="/v1/devices/{device_code}/firmware", tags=["device"])


class FirmwareReportRequest(BaseModel):
    release_id: str = Field(min_length=36, max_length=36)
    event: FirmwareUpdateEventType
    detail: str | None = Field(default=None, max_length=255)


@router.get("/{release_id}", response_class=FileResponse)
async def download_firmware(
    device_code: str,
    release_id: str,
    request: Request,
    session: DbSession,
) -> FileResponse:
    device = await verify_device_request(request, device_code, session)
    if device is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="database-backed device identity is required for OTA",
        )
    release = await session.get(FirmwareRelease, release_id)
    if release is None or not release_targets_device(release, device):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="firmware release not found",
        )
    path = release_binary_path(release)
    device.last_ota_result = "downloading"
    device.last_ota_error = None
    await session.commit()
    return FileResponse(
        path,
        media_type="application/octet-stream",
        filename=f"rfm-{release.version}-{release.build_number}-signed.bin",
        headers={
            "Cache-Control": "no-store",
            "X-Firmware-SHA256": release.sha256,
            "X-Firmware-Size": str(release.binary_size),
        },
    )


@router.post("/report", status_code=status.HTTP_204_NO_CONTENT)
async def report_firmware_result(
    device_code: str,
    request: Request,
    session: DbSession,
    payload: Annotated[FirmwareReportRequest, Body()],
) -> None:
    device = await verify_device_request(request, device_code, session)
    if device is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="database-backed device identity is required for OTA",
        )
    release = await session.get(FirmwareRelease, payload.release_id)
    if release is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="firmware release not found",
        )
    session.add(
        FirmwareUpdateEvent(
            device_id=device.id,
            release_id=release.id,
            event=payload.event,
            detail=payload.detail,
        )
    )
    device.last_ota_release_id = release.id
    device.last_ota_result = payload.event.value
    device.last_ota_error = (
        payload.detail
        if payload.event
        in (FirmwareUpdateEventType.FAILED, FirmwareUpdateEventType.ROLLED_BACK)
        else None
    )
    if payload.event == FirmwareUpdateEventType.INSTALLED:
        device.firmware_version = release.version
        device.firmware_build_number = release.build_number
        device.firmware_hardware = release.hardware_model
    await session.commit()
