from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from io import BytesIO

import pytest
from PIL import Image

from app.services.device_provisioning import (
    ProvisioningPayload,
    ProvisioningPayloadError,
    decrypt_provisioning_payload,
    encrypt_provisioning_payload,
)
from app.services.device_secrets import (
    DeviceSecretError,
    decrypt_device_secret,
    device_secret_hash,
    encrypt_device_secret,
)
from app.services.mini_program_code import _normalize_code_png
from app.services.device_frame import FRAME_SIZE, encode_f53
from app.services.display_renderer import render_display_image


TEST_SECRET = "factory-secret-with-at-least-thirty-two-characters"
TEST_CODE = "RFM-S3-TEST-001"
TEST_CHALLENGE = "00112233445566778899aabbccddeeff"


def test_device_secret_is_encrypted_and_bound_to_device_code() -> None:
    encrypted = encrypt_device_secret(TEST_SECRET, TEST_CODE)

    assert TEST_SECRET not in encrypted
    assert decrypt_device_secret(encrypted, TEST_CODE) == TEST_SECRET
    assert device_secret_hash(TEST_SECRET) == hashlib.sha256(
        TEST_SECRET.encode()
    ).hexdigest()
    with pytest.raises(DeviceSecretError):
        decrypt_device_secret(encrypted, "another-device")


def test_provisioning_payload_round_trip_hides_wifi_credentials() -> None:
    payload = ProvisioningPayload(
        session_id="00000000-0000-0000-0000-000000000001",
        binding_token="binding-token-with-sufficient-entropy-001",
        api_base_url="https://api.example.test",
        wifi_ssid="Kitchen-2.4G",
        wifi_password="private-wifi-password",
        expires_at=int(datetime.now(timezone.utc).timestamp()) + 600,
    )

    encrypted, digest = encrypt_provisioning_payload(
        device_code=TEST_CODE,
        device_secret=TEST_SECRET,
        challenge_hex=TEST_CHALLENGE,
        payload=payload,
    )

    assert "Kitchen-2.4G" not in encrypted
    assert "private-wifi-password" not in encrypted
    assert digest == hashlib.sha256(encrypted.encode("ascii")).hexdigest()
    assert (
        decrypt_provisioning_payload(
            device_code=TEST_CODE,
            device_secret=TEST_SECRET,
            challenge_hex=TEST_CHALLENGE,
            encrypted_payload=encrypted,
        )
        == payload
    )
    with pytest.raises(ProvisioningPayloadError):
        decrypt_provisioning_payload(
            device_code=TEST_CODE,
            device_secret=TEST_SECRET,
            challenge_hex="ffeeddccbbaa99887766554433221100",
            encrypted_payload=encrypted,
        )


def test_wechat_code_image_is_normalized_to_png() -> None:
    source = BytesIO()
    Image.new("RGB", (280, 280), "white").save(source, format="JPEG")

    normalized = _normalize_code_png(source.getvalue())

    assert normalized.startswith(b"\x89PNG\r\n\x1a\n")
    with Image.open(BytesIO(normalized)) as image:
        assert image.size == (280, 280)


def test_real_black_code_can_be_encoded_for_four_color_panel() -> None:
    source = BytesIO()
    Image.new("RGB", (280, 280), "black").save(source, format="PNG")

    rendered = render_display_image(
        household_name="我的冰箱",
        items=[],
        rendered_at=datetime.now(timezone.utc),
        mini_program_code_png=source.getvalue(),
    )

    assert len(encode_f53(rendered)) == FRAME_SIZE
