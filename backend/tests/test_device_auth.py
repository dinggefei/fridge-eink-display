from __future__ import annotations

import hashlib
import hmac
import time

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.device_frame import FRAME_SIZE
from app.settings import get_settings


TEST_DEVICE_CODE = "rfm-test-001"
TEST_DEVICE_SECRET = "test-secret-that-is-long-enough-for-hmac-validation"
client = TestClient(app)


@pytest.fixture(autouse=True)
def device_settings(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("DEVICE_CODE", TEST_DEVICE_CODE)
    monkeypatch.setenv("DEVICE_SECRET", TEST_DEVICE_SECRET)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def signed_headers(
    *,
    nonce: str,
    timestamp: int | None = None,
    etag: str = "",
    secret: str = TEST_DEVICE_SECRET,
) -> dict[str, str]:
    timestamp_text = str(timestamp if timestamp is not None else int(time.time()))
    path = f"/v1/devices/{TEST_DEVICE_CODE}/frame"
    signing_text = "\n".join(("GET", path, timestamp_text, nonce, etag))
    signature = hmac.new(
        secret.encode(),
        signing_text.encode(),
        hashlib.sha256,
    ).hexdigest()
    headers = {
        "X-Device-Timestamp": timestamp_text,
        "X-Device-Nonce": nonce,
        "X-Device-Signature": signature,
    }
    if etag:
        headers["If-None-Match"] = etag
    return headers


def signed_v2_headers(
    *,
    nonce: str,
    content: bytes = b"",
) -> dict[str, str]:
    timestamp_text = str(int(time.time()))
    path = f"/v1/devices/{TEST_DEVICE_CODE}/frame"
    content_sha256 = hashlib.sha256(content).hexdigest()
    signing_text = "\n".join(
        (
            "GET",
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


def test_signed_frame_request_succeeds() -> None:
    headers = signed_headers(nonce="nonce-valid-000001")

    response = client.get(
        f"/v1/devices/{TEST_DEVICE_CODE}/frame",
        headers=headers,
    )

    assert response.status_code == 200
    assert len(response.content) == FRAME_SIZE


def test_signed_v2_frame_request_succeeds() -> None:
    response = client.get(
        f"/v1/devices/{TEST_DEVICE_CODE}/frame",
        headers=signed_v2_headers(nonce="nonce-v2-valid-0001"),
    )

    assert response.status_code == 200
    assert len(response.content) == FRAME_SIZE


def test_signed_v2_request_rejects_wrong_content_hash() -> None:
    headers = signed_v2_headers(
        nonce="nonce-v2-content-bad",
        content=b"not-the-request-body",
    )

    response = client.get(
        f"/v1/devices/{TEST_DEVICE_CODE}/frame",
        headers=headers,
    )

    assert response.status_code == 401


def test_signed_request_honors_etag() -> None:
    first_response = client.get(
        f"/v1/devices/{TEST_DEVICE_CODE}/frame",
        headers=signed_headers(nonce="nonce-valid-000002"),
    )
    etag = first_response.headers["etag"]
    headers = signed_headers(nonce="nonce-valid-000003", etag=etag)

    response = client.get(
        f"/v1/devices/{TEST_DEVICE_CODE}/frame",
        headers=headers,
    )

    assert response.status_code == 304
    assert response.content == b""


def test_invalid_signature_is_rejected() -> None:
    headers = signed_headers(
        nonce="nonce-invalid-0001",
        secret="incorrect-device-secret",
    )

    response = client.get(
        f"/v1/devices/{TEST_DEVICE_CODE}/frame",
        headers=headers,
    )

    assert response.status_code == 401


def test_stale_timestamp_is_rejected() -> None:
    headers = signed_headers(
        nonce="nonce-stale-000001",
        timestamp=int(time.time()) - 301,
    )

    response = client.get(
        f"/v1/devices/{TEST_DEVICE_CODE}/frame",
        headers=headers,
    )

    assert response.status_code == 401


def test_replayed_nonce_is_rejected() -> None:
    headers = signed_headers(nonce="nonce-replay-00001")
    path = f"/v1/devices/{TEST_DEVICE_CODE}/frame"

    first_response = client.get(path, headers=headers)
    replay_response = client.get(path, headers=headers)

    assert first_response.status_code == 200
    assert replay_response.status_code == 401
