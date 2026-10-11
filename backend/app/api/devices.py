from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, HTTPException, Response, status
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    field_validator,
)
from sqlalchemy import select, update

from app.api.dependencies import (
    CurrentUser,
    DbSession,
    require_household_admin,
    require_household_member,
)
from app.db.base import utc_now
from app.db.models import (
    Device,
    DisplayMode,
    DeviceProvisioningSession,
    DeviceProvisioningStatus,
    DeviceStatus,
    Membership,
    MembershipStatus,
)
from app.services.device_provisioning import (
    ProvisioningPayload,
    encrypt_provisioning_payload,
    unix_timestamp,
)
from app.services.device_secrets import (
    DeviceSecretError,
    encrypt_device_secret,
    resolve_device_secret,
)
from app.services.mini_program_code import (
    MiniProgramCodeError,
    generate_mini_program_code,
)
from app.settings import get_settings


BLE_SERVICE_UUID = "7b9e0001-5f34-4f6f-9f46-7d4c8a1e0001"
BLE_DEVICE_CODE_UUID = "7b9e0002-5f34-4f6f-9f46-7d4c8a1e0001"
BLE_CHALLENGE_UUID = "7b9e0003-5f34-4f6f-9f46-7d4c8a1e0001"
BLE_COMMAND_UUID = "7b9e0004-5f34-4f6f-9f46-7d4c8a1e0001"
BLE_STATUS_UUID = "7b9e0005-5f34-4f6f-9f46-7d4c8a1e0001"
BLE_CHUNK_SIZE = 12

household_router = APIRouter(
    prefix="/v1/households/{household_id}/devices",
    tags=["devices"],
)
device_router = APIRouter(prefix="/v1/devices", tags=["devices"])


class DeviceResponse(BaseModel):
    device_code: str
    status: DeviceStatus
    household_id: str | None
    panel_model: str
    display_mode_override: DisplayMode | None
    poll_interval_seconds: int
    last_seen_at: datetime | None
    mini_program_code_ready: bool


class DeviceEntryResponse(BaseModel):
    state: Literal["accessible", "unbound", "unavailable"]
    household_id: str | None = None


class CreateProvisioningSessionRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    device_code: str = Field(
        min_length=3,
        max_length=32,
        pattern=r"^[\x21-\x7e]+$",
    )
    challenge: str = Field(pattern=r"^[0-9A-Fa-f]{32}$")
    wifi_ssid: str = Field(min_length=1, max_length=64)
    wifi_password: SecretStr = SecretStr("")

    @field_validator("wifi_ssid")
    @classmethod
    def validate_ssid_bytes(cls, value: str) -> str:
        if len(value.encode("utf-8")) > 32:
            raise ValueError("Wi-Fi SSID exceeds 32 bytes")
        return value

    @field_validator("wifi_password")
    @classmethod
    def validate_password_bytes(cls, value: SecretStr) -> SecretStr:
        if len(value.get_secret_value().encode("utf-8")) > 63:
            raise ValueError("Wi-Fi password exceeds 63 bytes")
        return value


class ProvisioningSessionResponse(BaseModel):
    id: str
    device_code: str
    status: DeviceProvisioningStatus
    expires_at: datetime
    encrypted_payload: str | None = None
    payload_sha256: str | None = None
    ble_service_uuid: str = BLE_SERVICE_UUID
    ble_device_code_uuid: str = BLE_DEVICE_CODE_UUID
    ble_challenge_uuid: str = BLE_CHALLENGE_UUID
    ble_command_uuid: str = BLE_COMMAND_UUID
    ble_status_uuid: str = BLE_STATUS_UUID
    ble_chunk_size: int = BLE_CHUNK_SIZE


class CompleteProvisioningRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    session_id: str = Field(min_length=36, max_length=36)
    binding_token: str = Field(min_length=32, max_length=128)


class CompleteProvisioningResponse(BaseModel):
    device_code: str
    status: DeviceStatus
    household_id: str
    poll_interval_seconds: int
    frame_path: str


def _device_response(device: Device) -> DeviceResponse:
    return DeviceResponse(
        device_code=device.device_code,
        status=device.status,
        household_id=device.household_id,
        panel_model=device.panel_model,
        display_mode_override=device.display_mode_override,
        poll_interval_seconds=device.poll_interval_seconds,
        last_seen_at=device.last_seen_at,
        mini_program_code_ready=device.mini_program_code_png is not None,
    )


def _session_response(
    row: DeviceProvisioningSession,
    device_code: str,
) -> ProvisioningSessionResponse:
    return ProvisioningSessionResponse(
        id=row.id,
        device_code=device_code,
        status=row.status,
        expires_at=row.expires_at,
    )


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


@device_router.get(
    "/{device_code}/entry",
    response_model=DeviceEntryResponse,
)
async def resolve_device_entry(
    device_code: str,
    session: DbSession,
    user: CurrentUser,
) -> DeviceEntryResponse:
    """Resolve a scanned device without exposing another household's data."""
    device = await session.scalar(
        select(Device).where(Device.device_code == device_code)
    )
    if device is None:
        raise HTTPException(status_code=404, detail="device not found")
    if device.household_id is None:
        return DeviceEntryResponse(state="unbound")

    membership = await session.get(
        Membership,
        (device.household_id, user.id),
    )
    if membership is None or membership.status != MembershipStatus.ACTIVE:
        return DeviceEntryResponse(state="unavailable")
    return DeviceEntryResponse(
        state="accessible",
        household_id=device.household_id,
    )


@household_router.get("", response_model=list[DeviceResponse])
async def list_household_devices(
    household_id: str,
    session: DbSession,
    user: CurrentUser,
) -> list[DeviceResponse]:
    await require_household_member(
        session,
        household_id=household_id,
        user_id=user.id,
    )
    rows = (
        await session.scalars(
            select(Device)
            .where(Device.household_id == household_id)
            .order_by(Device.created_at, Device.device_code)
        )
    ).all()
    return [_device_response(row) for row in rows]


@household_router.post(
    "/provisioning-sessions",
    response_model=ProvisioningSessionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_provisioning_session(
    household_id: str,
    payload: CreateProvisioningSessionRequest,
    session: DbSession,
    user: CurrentUser,
) -> ProvisioningSessionResponse:
    await require_household_admin(
        session,
        household_id=household_id,
        user_id=user.id,
    )
    device = await session.scalar(
        select(Device)
        .where(Device.device_code == payload.device_code)
        .with_for_update()
    )
    if device is None:
        raise HTTPException(status_code=404, detail="device is not registered")
    if device.household_id not in {None, household_id}:
        raise HTTPException(
            status_code=409,
            detail="device is already bound to another household",
        )
    try:
        device_secret, needs_encryption = resolve_device_secret(device)
    except DeviceSecretError as error:
        raise HTTPException(
            status_code=409,
            detail="device secret is not ready for provisioning",
        ) from error
    if needs_encryption:
        device.device_secret_ciphertext = encrypt_device_secret(
            device_secret,
            device.device_code,
        )

    await session.execute(
        update(DeviceProvisioningSession)
        .where(
            DeviceProvisioningSession.device_id == device.id,
            DeviceProvisioningSession.status
            == DeviceProvisioningStatus.PENDING,
        )
        .values(status=DeviceProvisioningStatus.CANCELLED)
    )
    now = utc_now()
    expires_at = now + timedelta(
        seconds=get_settings().device_provisioning_ttl_seconds
    )
    binding_token = secrets.token_urlsafe(32)
    row = DeviceProvisioningSession(
        device_id=device.id,
        household_id=household_id,
        created_by_user_id=user.id,
        challenge_hash=hashlib.sha256(
            payload.challenge.lower().encode("ascii")
        ).hexdigest(),
        binding_token_hash=hashlib.sha256(
            binding_token.encode("ascii")
        ).hexdigest(),
        status=DeviceProvisioningStatus.PENDING,
        expires_at=expires_at,
    )
    session.add(row)
    await session.flush()
    encrypted_payload, payload_sha256 = encrypt_provisioning_payload(
        device_code=device.device_code,
        device_secret=device_secret,
        challenge_hex=payload.challenge,
        payload=ProvisioningPayload(
            session_id=row.id,
            binding_token=binding_token,
            api_base_url=get_settings().device_api_base_url.rstrip("/"),
            wifi_ssid=payload.wifi_ssid,
            wifi_password=payload.wifi_password.get_secret_value(),
            expires_at=unix_timestamp(expires_at),
        ),
    )
    await session.commit()
    return ProvisioningSessionResponse(
        id=row.id,
        device_code=device.device_code,
        status=row.status,
        expires_at=row.expires_at,
        encrypted_payload=encrypted_payload,
        payload_sha256=payload_sha256,
    )


@household_router.get(
    "/provisioning-sessions/{provisioning_session_id}",
    response_model=ProvisioningSessionResponse,
)
async def read_provisioning_session(
    household_id: str,
    provisioning_session_id: str,
    session: DbSession,
    user: CurrentUser,
) -> ProvisioningSessionResponse:
    await require_household_admin(
        session,
        household_id=household_id,
        user_id=user.id,
    )
    result = await session.execute(
        select(DeviceProvisioningSession, Device.device_code)
        .join(Device, Device.id == DeviceProvisioningSession.device_id)
        .where(
            DeviceProvisioningSession.id == provisioning_session_id,
            DeviceProvisioningSession.household_id == household_id,
        )
    )
    pair = result.one_or_none()
    if pair is None:
        raise HTTPException(
            status_code=404,
            detail="provisioning session not found",
        )
    row, device_code = pair
    if (
        row.status == DeviceProvisioningStatus.PENDING
        and _aware(row.expires_at) <= utc_now()
    ):
        row.status = DeviceProvisioningStatus.EXPIRED
        await session.commit()
    return _session_response(row, device_code)


@household_router.post(
    "/{device_code}/unbind",
    response_model=DeviceResponse,
)
async def unbind_device(
    household_id: str,
    device_code: str,
    session: DbSession,
    user: CurrentUser,
) -> DeviceResponse:
    await require_household_admin(
        session,
        household_id=household_id,
        user_id=user.id,
    )
    device = await session.scalar(
        select(Device)
        .where(
            Device.device_code == device_code,
            Device.household_id == household_id,
        )
        .with_for_update()
    )
    if device is None:
        raise HTTPException(status_code=404, detail="device not found")
    device.household_id = None
    device.status = DeviceStatus.UNBOUND
    device.frame_version = None
    device.frame_etag = None
    await session.execute(
        update(DeviceProvisioningSession)
        .where(
            DeviceProvisioningSession.device_id == device.id,
            DeviceProvisioningSession.status
            == DeviceProvisioningStatus.PENDING,
        )
        .values(status=DeviceProvisioningStatus.CANCELLED)
    )
    await session.commit()
    return _device_response(device)


@household_router.post(
    "/{device_code}/mini-program-code",
    response_model=DeviceResponse,
)
async def refresh_mini_program_code(
    household_id: str,
    device_code: str,
    session: DbSession,
    user: CurrentUser,
) -> DeviceResponse:
    await require_household_admin(
        session,
        household_id=household_id,
        user_id=user.id,
    )
    device = await session.scalar(
        select(Device).where(
            Device.device_code == device_code,
            Device.household_id == household_id,
        )
    )
    if device is None:
        raise HTTPException(status_code=404, detail="device not found")
    try:
        device.mini_program_code_png = await generate_mini_program_code(
            device.device_code
        )
    except MiniProgramCodeError as error:
        raise HTTPException(
            status_code=502,
            detail=str(error),
        ) from error
    device.mini_program_code_updated_at = utc_now()
    device.frame_etag = None
    device.frame_version = None
    await session.commit()
    return _device_response(device)


@household_router.get(
    "/{device_code}/mini-program-code",
    response_class=Response,
)
async def read_mini_program_code(
    household_id: str,
    device_code: str,
    session: DbSession,
    user: CurrentUser,
) -> Response:
    await require_household_member(
        session,
        household_id=household_id,
        user_id=user.id,
    )
    device = await session.scalar(
        select(Device).where(
            Device.device_code == device_code,
            Device.household_id == household_id,
        )
    )
    if device is None or device.mini_program_code_png is None:
        raise HTTPException(
            status_code=404,
            detail="mini program code is not ready",
        )
    return Response(
        content=device.mini_program_code_png,
        media_type="image/png",
        headers={"Cache-Control": "private, max-age=86400"},
    )


@device_router.post(
    "/{device_code}/provisioning/complete",
    response_model=CompleteProvisioningResponse,
)
async def complete_device_provisioning(
    device_code: str,
    payload: CompleteProvisioningRequest,
    session: DbSession,
) -> CompleteProvisioningResponse:
    result = await session.execute(
        select(DeviceProvisioningSession, Device)
        .join(Device, Device.id == DeviceProvisioningSession.device_id)
        .where(
            DeviceProvisioningSession.id == payload.session_id,
            Device.device_code == device_code,
        )
        .with_for_update()
    )
    pair = result.one_or_none()
    if pair is None:
        raise HTTPException(
            status_code=404,
            detail="provisioning session not found",
        )
    row, device = pair
    if row.status != DeviceProvisioningStatus.PENDING:
        raise HTTPException(
            status_code=409,
            detail="provisioning session is no longer pending",
        )
    if _aware(row.expires_at) <= utc_now():
        row.status = DeviceProvisioningStatus.EXPIRED
        await session.commit()
        raise HTTPException(
            status_code=410,
            detail="provisioning session has expired",
        )
    provided_hash = hashlib.sha256(
        payload.binding_token.encode("ascii")
    ).hexdigest()
    if not hmac.compare_digest(row.binding_token_hash, provided_hash):
        raise HTTPException(
            status_code=401,
            detail="invalid binding token",
        )
    if device.household_id not in {None, row.household_id}:
        raise HTTPException(
            status_code=409,
            detail="device is already bound to another household",
        )
    now = utc_now()
    row.status = DeviceProvisioningStatus.COMPLETED
    row.completed_at = now
    device.household_id = row.household_id
    device.status = DeviceStatus.ONLINE
    device.last_seen_at = now
    await session.commit()
    return CompleteProvisioningResponse(
        device_code=device.device_code,
        status=device.status,
        household_id=row.household_id,
        poll_interval_seconds=device.poll_interval_seconds,
        frame_path=f"/v1/devices/{device.device_code}/frame",
    )
