from __future__ import annotations

from hashlib import sha256
from io import BytesIO
import time

from fastapi.testclient import TestClient
from PIL import Image
import pytest

from app.main import app
from app.services.device_frame import load_demo_frame
from app.services.kindle_frame import (
    KINDLE_HEIGHT,
    KINDLE_MODEL,
    KINDLE_WIDTH,
    decode_native_frame,
    render_kindle_frame,
)
from app.settings import get_settings
from tests.test_device_auth import (
    TEST_DEVICE_CODE,
    TEST_DEVICE_SECRET,
    signed_headers,
)


client = TestClient(app)


@pytest.fixture(autouse=True)
def kindle_device_settings(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("DEVICE_CODE", TEST_DEVICE_CODE)
    monkeypatch.setenv("DEVICE_SECRET", TEST_DEVICE_SECRET)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_native_frame_decodes_to_grayscale_image() -> None:
    image = decode_native_frame(load_demo_frame().data)

    assert image.mode == "L"
    assert image.size == (800, 480)
    assert set(image.get_flattened_data()) <= {17, 80, 184, 255}


def test_device_time_supports_clients_with_an_unreliable_clock() -> None:
    response = client.get("/v1/device-time")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert abs(int(response.text.strip()) - int(time.time())) <= 2


def test_kindle_frame_is_pw3_png() -> None:
    frame = render_kindle_frame(load_demo_frame())

    with Image.open(BytesIO(frame.data)) as image:
        assert image.format == "PNG"
        assert image.mode == "L"
        assert image.size == (KINDLE_WIDTH, KINDLE_HEIGHT)
    assert frame.sha256 == sha256(frame.data).hexdigest()
    assert frame.version.startswith("kindle-pw3-v1-")


def test_authenticated_kindle_frame_endpoint_and_etag() -> None:
    path = f"/v1/devices/{TEST_DEVICE_CODE}/frame"
    first = client.get(
        f"{path}?format=kindle-pw3",
        headers=signed_headers(nonce="kindle-frame-000001"),
    )

    assert first.status_code == 200
    assert first.headers["content-type"] == "image/png"
    assert first.headers["x-panel-model"] == KINDLE_MODEL
    assert first.headers["x-image-width"] == str(KINDLE_WIDTH)
    assert first.headers["x-image-height"] == str(KINDLE_HEIGHT)
    assert first.headers["x-frame-sha256"] == sha256(first.content).hexdigest()

    etag = first.headers["etag"]
    second = client.get(
        f"{path}?format=kindle-pw3",
        headers=signed_headers(nonce="kindle-frame-000002", etag=etag),
    )
    assert second.status_code == 304
    assert second.content == b""
