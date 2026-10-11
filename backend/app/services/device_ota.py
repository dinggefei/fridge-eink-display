from __future__ import annotations

import hashlib
import hmac
from pathlib import Path

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import utc_now
from app.db.models import (
    Device,
    FirmwareRelease,
    FirmwareReleaseStatus,
)
from app.settings import get_settings


OTA_CAPABILITY_HEADER = "x-device-ota-capability"
OTA_CAPABILITY_VERSION = "1"


def _rollout_bucket(device_code: str, release_id: str) -> int:
    digest = hashlib.sha256(f"{device_code}:{release_id}".encode()).digest()
    return int.from_bytes(digest[:4], "big") % 100


def release_targets_device(
    release: FirmwareRelease,
    device: Device,
) -> bool:
    current_build = device.firmware_build_number
    hardware = device.firmware_hardware
    if current_build is None or hardware is None:
        return False
    if release.hardware_model != hardware:
        return False
    if release.build_number <= current_build:
        return False
    if current_build < release.min_build_number:
        return False

    explicit_targets = set(release.target_device_codes or [])
    if release.status == FirmwareReleaseStatus.CANARY:
        return device.device_code in explicit_targets
    if release.status != FirmwareReleaseStatus.PUBLISHED:
        return False
    if device.device_code in explicit_targets:
        return True
    return _rollout_bucket(device.device_code, release.id) < release.rollout_percent


async def select_firmware_release(
    session: AsyncSession,
    device: Device,
) -> FirmwareRelease | None:
    candidates = list(
        await session.scalars(
            select(FirmwareRelease)
            .where(
                FirmwareRelease.status.in_(
                    (
                        FirmwareReleaseStatus.CANARY,
                        FirmwareReleaseStatus.PUBLISHED,
                    )
                )
            )
            .order_by(FirmwareRelease.build_number.desc())
        )
    )
    device.last_ota_check_at = utc_now()
    for release in candidates:
        if release_targets_device(release, device):
            device.last_ota_release_id = release.id
            device.last_ota_result = "offered"
            device.last_ota_error = None
            return release
    return None


def firmware_offer_headers(
    release: FirmwareRelease | None,
    device_code: str,
) -> dict[str, str]:
    if release is None:
        return {"X-Firmware-Update": "none"}
    return {
        "X-Firmware-Update": "available",
        "X-Firmware-Release-Id": release.id,
        "X-Firmware-Version": release.version,
        "X-Firmware-Build": str(release.build_number),
        "X-Firmware-Hardware": release.hardware_model,
        "X-Firmware-Size": str(release.binary_size),
        "X-Firmware-SHA256": release.sha256,
        "X-Firmware-Path": (
            f"/v1/devices/{device_code}/firmware/{release.id}"
        ),
    }


def release_binary_path(release: FirmwareRelease) -> Path:
    storage_dir = get_settings().ota_firmware_storage_dir.resolve()
    candidate = (storage_dir / release.binary_path).resolve()
    if storage_dir not in candidate.parents:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="invalid firmware release path",
        )
    if not candidate.is_file():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="firmware binary is unavailable",
        )
    if candidate.stat().st_size != release.binary_size:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="firmware binary size does not match release metadata",
        )
    actual_sha256 = hashlib.sha256(candidate.read_bytes()).hexdigest()
    if not hmac.compare_digest(actual_sha256, release.sha256):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="firmware binary checksum does not match release metadata",
        )
    return candidate
