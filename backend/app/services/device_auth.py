from __future__ import annotations

import hashlib
import hmac
import logging
import re
import threading
import time

from fastapi import HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import utc_now
from app.db.models import Device, DeviceStatus
from app.services.device_secrets import (
    DeviceSecretError,
    encrypt_device_secret,
    resolve_device_secret,
)
from app.settings import get_settings


MAX_CLOCK_SKEW_SECONDS = 300
NONCE_RETENTION_SECONDS = 600
NONCE_PATTERN = re.compile(r"^[A-Za-z0-9_-]{16,64}$")
SIGNATURE_PATTERN = re.compile(r"^[0-9a-f]{64}$")
FIRMWARE_VERSION_PATTERN = re.compile(r"^[0-9A-Za-z][0-9A-Za-z._+-]{0,31}$")
HARDWARE_PATTERN = re.compile(r"^[0-9A-Za-z][0-9A-Za-z._-]{0,63}$")

logger = logging.getLogger(__name__)


class NonceStore:
    """In-memory replay protection for the single-process development server."""

    def __init__(self) -> None:
        self._expires_at: dict[tuple[str, str], int] = {}
        self._lock = threading.Lock()

    def consume(self, device_code: str, nonce: str, now: int) -> bool:
        key = (device_code, nonce)
        with self._lock:
            expired = [
                stored_key
                for stored_key, expires_at in self._expires_at.items()
                if expires_at <= now
            ]
            for stored_key in expired:
                del self._expires_at[stored_key]

            if key in self._expires_at:
                return False

            self._expires_at[key] = now + NONCE_RETENTION_SECONDS
            return True


nonce_store = NonceStore()


async def verify_device_request(
    request: Request,
    device_code: str,
    session: AsyncSession,
) -> Device | None:
    settings = get_settings()
    timestamp_text = request.headers.get("x-device-timestamp", "")
    nonce = request.headers.get("x-device-nonce", "")
    signature = request.headers.get("x-device-signature", "")
    if_none_match = request.headers.get("if-none-match", "")
    auth_version = request.headers.get("x-device-auth-version", "1")
    firmware_version = request.headers.get("x-device-firmware-version", "")
    firmware_build_text = request.headers.get("x-device-firmware-build", "")
    firmware_hardware = request.headers.get("x-device-hardware", "")
    content_sha256 = request.headers.get("x-content-sha256", "")

    device: Device | None = None
    device_secret = settings.device_secret
    if settings.database_inventory_enabled:
        device = await session.scalar(
            select(Device).where(Device.device_code == device_code)
        )
        if device is None:
            _reject("unknown_device", device_code)
        try:
            device_secret, needs_encryption = resolve_device_secret(device)
        except DeviceSecretError:
            _reject("unusable_device_secret", device_code)
        if needs_encryption:
            device.device_secret_ciphertext = encrypt_device_secret(
                device_secret,
                device.device_code,
            )
    elif device_code != settings.device_code:
        _reject("unexpected_device_code", device_code)

    try:
        request_timestamp = int(timestamp_text)
    except ValueError:
        _reject("invalid_timestamp", device_code)

    now = int(time.time())
    if abs(now - request_timestamp) > MAX_CLOCK_SKEW_SECONDS:
        _reject(
            f"clock_skew_seconds={now - request_timestamp}",
            device_code,
        )
    if NONCE_PATTERN.fullmatch(nonce) is None:
        _reject(f"invalid_nonce_length={len(nonce)}", device_code)
    if SIGNATURE_PATTERN.fullmatch(signature) is None:
        _reject(f"invalid_signature_length={len(signature)}", device_code)

    firmware_build: int | None = None
    if auth_version == "1":
        signing_fields = (
            request.method,
            request.url.path,
            timestamp_text,
            nonce,
            if_none_match,
        )
    elif auth_version == "2":
        try:
            firmware_build = int(firmware_build_text)
        except ValueError:
            _reject()
        if (
            firmware_build is None
            or firmware_build < 0
            or FIRMWARE_VERSION_PATTERN.fullmatch(firmware_version) is None
            or HARDWARE_PATTERN.fullmatch(firmware_hardware) is None
            or SIGNATURE_PATTERN.fullmatch(content_sha256) is None
        ):
            _reject()
        request_body = await request.body()
        actual_content_sha256 = hashlib.sha256(request_body).hexdigest()
        if not hmac.compare_digest(content_sha256, actual_content_sha256):
            _reject()
        signing_fields = (
            request.method,
            request.url.path,
            timestamp_text,
            nonce,
            if_none_match,
            firmware_version,
            firmware_build_text,
            firmware_hardware,
            content_sha256,
        )
    else:
        _reject("unsupported_auth_version", device_code)

    signing_text = "\n".join(signing_fields)
    expected_signature = hmac.new(
        device_secret.encode("utf-8"),
        signing_text.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(signature, expected_signature):
        _reject("signature_mismatch", device_code)

    if not nonce_store.consume(device_code, nonce, now):
        _reject("replayed_nonce", device_code)
    if device is not None:
        device.last_seen_at = utc_now()
        # An authenticated poll proves the hardware is reachable, but it must
        # not turn a deliberately unbound device back into the ONLINE state.
        device.status = (
            DeviceStatus.ONLINE
            if device.household_id is not None
            else DeviceStatus.UNBOUND
        )
        if auth_version == "2":
            device.firmware_version = firmware_version
            device.firmware_build_number = firmware_build
            device.firmware_hardware = firmware_hardware
    return device


def _reject(reason: str = "invalid_v2_request", device_code: str = "-") -> None:
    logger.warning(
        "device authentication rejected: device=%s reason=%s",
        device_code,
        reason,
    )
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="invalid device authentication",
    )
