from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
from pathlib import Path
import time

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.base import Base
from app.db.models import (
    Device,
    FirmwareRelease,
    FirmwareReleaseStatus,
    Household,
    User,
)
from app.db.session import get_db_session
from app.main import app
from app.services.device_secrets import device_secret_hash, encrypt_device_secret
from app.services.device_ota import release_targets_device
from app.settings import get_settings
from tools.firmware_release import verify_signed_firmware


TEST_DEVICE_SECRET = "ota-test-device-secret-with-more-than-32-characters"


def _signed_v2_headers(
    *,
    method: str,
    path: str,
    nonce: str,
    body: bytes = b"",
) -> dict[str, str]:
    timestamp_text = str(int(time.time()))
    content_sha256 = hashlib.sha256(body).hexdigest()
    signing_text = "\n".join(
        (
            method,
            path,
            timestamp_text,
            nonce,
            "",
            "1.0.0-ota-base",
            "10000",
            "esp32-s3-dev-kit-n16r8",
            content_sha256,
        )
    )
    signature = hmac.new(
        TEST_DEVICE_SECRET.encode(),
        signing_text.encode(),
        hashlib.sha256,
    ).hexdigest()
    return {
        "X-Device-Auth-Version": "2",
        "X-Device-Timestamp": timestamp_text,
        "X-Device-Nonce": nonce,
        "X-Device-Signature": signature,
        "X-Device-Firmware-Version": "1.0.0-ota-base",
        "X-Device-Firmware-Build": "10000",
        "X-Device-Hardware": "esp32-s3-dev-kit-n16r8",
        "X-Device-OTA-Capability": "1",
        "X-Content-SHA256": content_sha256,
    }


@pytest.fixture
def ota_database_client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    device_code = "rfm-ota-api-test"
    storage = tmp_path / "firmware-releases"
    binary = b"signed-test-package" * 40
    binary_path = Path("esp32-s3-dev-kit-n16r8/test-signed.bin")
    (storage / binary_path).parent.mkdir(parents=True)
    (storage / binary_path).write_bytes(binary)
    monkeypatch.setenv("DATABASE_INVENTORY_ENABLED", "true")
    monkeypatch.setenv("DEVICE_CODE", device_code)
    monkeypatch.setenv("DEVICE_SECRET", TEST_DEVICE_SECRET)
    monkeypatch.setenv(
        "DEVICE_SECRET_ENCRYPTION_KEY",
        "ota-test-encryption-key-with-more-than-32-characters",
    )
    monkeypatch.setenv("OTA_FIRMWARE_STORAGE_DIR", str(storage))
    get_settings.cache_clear()

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'ota.db'}")
    sessions = async_sessionmaker(engine, expire_on_commit=False)

    async def prepare() -> None:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        async with sessions() as session:
            user = User(openid="ota-test-user")
            session.add(user)
            await session.flush()
            household = Household(name="OTA test", admin_user_id=user.id)
            session.add(household)
            await session.flush()
            device = Device(
                device_code=device_code,
                device_secret_hash=device_secret_hash(TEST_DEVICE_SECRET),
                device_secret_ciphertext=encrypt_device_secret(
                    TEST_DEVICE_SECRET,
                    device_code,
                ),
                household_id=household.id,
            )
            release = FirmwareRelease(
                version="1.0.1",
                build_number=10001,
                hardware_model="esp32-s3-dev-kit-n16r8",
                min_build_number=10000,
                binary_path=str(binary_path),
                binary_size=len(binary),
                sha256=hashlib.sha256(binary).hexdigest(),
                status=FirmwareReleaseStatus.CANARY,
                rollout_percent=0,
                target_device_codes=[device_code],
            )
            session.add_all((device, release))
            await session.commit()

    async def override_session():
        async with sessions() as session:
            yield session

    asyncio.run(prepare())
    app.dependency_overrides[get_db_session] = override_session
    with TestClient(app) as client:
        yield client, device_code, binary
    app.dependency_overrides.clear()
    asyncio.run(engine.dispose())
    get_settings.cache_clear()


def _device(*, code: str = "rfm-ota-test", build: int = 100) -> Device:
    return Device(
        id="device-test-id",
        device_code=code,
        device_secret_hash="unused",
        firmware_version="1.0.0",
        firmware_build_number=build,
        firmware_hardware="esp32-s3-dev-kit-n16r8",
    )


def _release(
    *,
    status: FirmwareReleaseStatus,
    build: int = 101,
    rollout: int = 0,
    targets: list[str] | None = None,
) -> FirmwareRelease:
    return FirmwareRelease(
        id="release-test-id",
        version="1.0.1",
        build_number=build,
        hardware_model="esp32-s3-dev-kit-n16r8",
        min_build_number=0,
        binary_path="test.bin",
        binary_size=1024,
        sha256=hashlib.sha256(b"test").hexdigest(),
        status=status,
        rollout_percent=rollout,
        target_device_codes=targets or [],
    )


def test_canary_targets_only_explicit_device() -> None:
    release = _release(
        status=FirmwareReleaseStatus.CANARY,
        targets=["rfm-ota-test"],
    )

    assert release_targets_device(release, _device()) is True
    assert release_targets_device(release, _device(code="rfm-other")) is False


def test_published_rollout_is_deterministic_and_explicit_target_wins() -> None:
    release = _release(
        status=FirmwareReleaseStatus.PUBLISHED,
        rollout=0,
        targets=["rfm-ota-test"],
    )

    assert release_targets_device(release, _device()) is True
    assert release_targets_device(release, _device(code="rfm-other")) is False


def test_downgrade_and_wrong_hardware_are_rejected() -> None:
    device = _device(build=101)
    release = _release(
        status=FirmwareReleaseStatus.PUBLISHED,
        build=101,
        rollout=100,
    )

    assert release_targets_device(release, device) is False
    release.build_number = 102
    release.hardware_model = "different-board"
    assert release_targets_device(release, device) is False


def test_paused_release_is_never_offered() -> None:
    release = _release(
        status=FirmwareReleaseStatus.PAUSED,
        rollout=100,
        targets=["rfm-ota-test"],
    )

    assert release_targets_device(release, _device()) is False


def test_release_import_verifies_p256_signature(
    tmp_path: Path,
) -> None:
    private_key = ec.generate_private_key(ec.SECP256R1())
    public_key_path = tmp_path / "public.pem"
    public_key_path.write_bytes(
        private_key.public_key().public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    )
    image = b"firmware-image" * 100
    signature = private_key.sign(image, ec.ECDSA(hashes.SHA256()))
    signed_path = tmp_path / "firmware-signed.bin"
    signed_path.write_bytes(
        image + signature + b"\x00" * (512 - len(signature))
    )

    assert verify_signed_firmware(signed_path, public_key_path) == (
        signed_path.read_bytes()
    )

    corrupted = bytearray(signed_path.read_bytes())
    corrupted[5] ^= 0x01
    signed_path.write_bytes(corrupted)
    with pytest.raises(ValueError, match="signature is invalid"):
        verify_signed_firmware(signed_path, public_key_path)


def test_device_receives_private_canary_and_reports_install(
    ota_database_client,
) -> None:
    client, device_code, expected_binary = ota_database_client
    frame_path = f"/v1/devices/{device_code}/frame"
    frame_response = client.get(
        frame_path,
        headers=_signed_v2_headers(
            method="GET",
            path=frame_path,
            nonce="ota-frame-offer-0001",
        ),
    )

    assert frame_response.status_code == 200
    assert frame_response.headers["x-firmware-update"] == "available"
    release_id = frame_response.headers["x-firmware-release-id"]
    download_path = frame_response.headers["x-firmware-path"]
    download_response = client.get(
        download_path,
        headers=_signed_v2_headers(
            method="GET",
            path=download_path,
            nonce="ota-download-bin-0001",
        ),
    )
    assert download_response.status_code == 200
    assert download_response.content == expected_binary

    report_path = f"/v1/devices/{device_code}/firmware/report"
    body = json.dumps(
        {"release_id": release_id, "event": "installed"},
        separators=(",", ":"),
    ).encode()
    report_response = client.post(
        report_path,
        content=body,
        headers={
            **_signed_v2_headers(
                method="POST",
                path=report_path,
                nonce="ota-install-report-01",
                body=body,
            ),
            "Content-Type": "application/json",
        },
    )
    assert report_response.status_code == 204
