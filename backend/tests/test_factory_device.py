from __future__ import annotations

import asyncio
import re
from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.base import Base
from app.db.models import Device, DeviceStatus
from app.settings import get_settings
from tools.factory_device import (
    create_factory_batch,
    generate_device_code,
    inspect_release_readiness,
    validate_device_code,
)


def _code_png() -> bytes:
    output = BytesIO()
    Image.new("RGB", (280, 280), "white").save(output, format="PNG")
    return output.getvalue()


def test_device_code_validation_and_generation() -> None:
    assert validate_device_code("rfm-26-a7k3p9") == "rfm-26-a7k3p9"
    generated = generate_device_code("rfm-26")

    assert generated.startswith("rfm-26-")
    assert len(generated.rsplit("-", maxsplit=1)[1]) == 6
    assert not set(generated.rsplit("-", maxsplit=1)[1]) & set("01ilo")
    with pytest.raises(ValueError):
        validate_device_code("RFM DEVICE 001")


def test_factory_batch_creates_private_artifacts_and_unbound_device(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "DEVICE_SECRET_ENCRYPTION_KEY",
        "factory-test-encryption-key-with-32-characters",
    )
    get_settings.cache_clear()
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'factory.db'}"
    )
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    output_dir = tmp_path / "batch"
    expected_png = _code_png()

    async def fake_code_generator(device_code: str) -> bytes:
        assert device_code == "rfm-26-a7k3p9"
        return expected_png

    async def scenario() -> None:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

        artifacts = await create_factory_batch(
            output_dir=output_dir,
            prefix="rfm-26",
            explicit_codes=["rfm-26-a7k3p9"],
            session_factory=sessions,
            code_generator=fake_code_generator,
        )

        assert [item.device_code for item in artifacts] == [
            "rfm-26-a7k3p9"
        ]
        async with sessions() as session:
            device = await session.scalar(
                select(Device).where(
                    Device.device_code == "rfm-26-a7k3p9"
                )
            )
        assert device is not None
        assert device.status == DeviceStatus.UNBOUND
        assert device.household_id is None
        assert device.mini_program_code_png == expected_png
        assert device.device_secret_ciphertext

        device_dir = output_dir / "rfm-26-a7k3p9"
        header = device_dir / "device_secrets.h"
        header_content = header.read_text(encoding="utf-8")
        secret_match = re.search(
            r'kDeviceSecret\[\] = "([^"]+)"',
            header_content,
        )
        assert secret_match is not None
        assert len(secret_match.group(1)) == 64
        assert (header.stat().st_mode & 0o077) == 0
        assert (output_dir.stat().st_mode & 0o077) == 0
        assert (device_dir / "mini-program-code.png").is_file()
        pairing_header = device_dir / "factory_pairing_frame.h"
        pairing_preview = device_dir / "factory-pairing-frame.png"
        assert pairing_header.is_file()
        assert (pairing_header.stat().st_mode & 0o077) == 0
        pairing_header_content = pairing_header.read_text(encoding="utf-8")
        assert (
            'kFactoryPairingDeviceCode[] = "rfm-26-a7k3p9"'
            in pairing_header_content
        )
        assert "kFactoryPairingFrameSize = 96000" in pairing_header_content
        assert pairing_preview.is_file()
        with Image.open(pairing_preview) as preview:
            assert preview.size == (800, 480)
            assert set(preview.convert("RGB").get_flattened_data()) <= {
                (17, 17, 17),
                (255, 255, 255),
                (224, 160, 0),
                (196, 43, 37),
            }
        assert (device_dir / "device-label.png").is_file()
        assert (output_dir / "labels-a4-page-01.png").is_file()
        assert (output_dir / "labels-a4.pdf").is_file()

        manifest = (output_dir / "manifest.json").read_text(
            encoding="utf-8"
        )
        assert secret_match.group(1) not in manifest
        assert '"manifest_contains_device_secrets": false' in manifest
        assert '"schema_version": 2' in manifest
        assert '"pairing_frame_header"' in manifest

        incomplete = await inspect_release_readiness(
            device_code="rfm-26-a7k3p9",
            artifact_dir=device_dir,
            hardware_passed=False,
            nvs_cleared=False,
            session_factory=sessions,
        )
        assert not all(check.passed for check in incomplete)

        ready = await inspect_release_readiness(
            device_code="rfm-26-a7k3p9",
            artifact_dir=device_dir,
            hardware_passed=True,
            nvs_cleared=True,
            session_factory=sessions,
        )
        assert all(check.passed for check in ready)

    try:
        asyncio.run(scenario())
    finally:
        asyncio.run(engine.dispose())
        get_settings.cache_clear()


def test_factory_batch_rolls_back_files_and_database_on_code_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "DEVICE_SECRET_ENCRYPTION_KEY",
        "factory-test-encryption-key-with-32-characters",
    )
    get_settings.cache_clear()
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'rollback.db'}"
    )
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    output_dir = tmp_path / "failed-batch"

    async def failing_code_generator(device_code: str) -> bytes:
        del device_code
        raise RuntimeError("simulated WeChat failure")

    async def scenario() -> None:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

        with pytest.raises(RuntimeError, match="simulated WeChat failure"):
            await create_factory_batch(
                output_dir=output_dir,
                prefix="rfm-26",
                explicit_codes=["rfm-26-failure"],
                session_factory=sessions,
                code_generator=failing_code_generator,
            )

        assert not output_dir.exists()
        async with sessions() as session:
            device_count = await session.scalar(
                select(func.count()).select_from(Device)
            )
        assert device_count == 0

    try:
        asyncio.run(scenario())
    finally:
        asyncio.run(engine.dispose())
        get_settings.cache_clear()
