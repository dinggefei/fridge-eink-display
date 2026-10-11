from hashlib import sha256

from fastapi.testclient import TestClient

from app.main import app
from app.services.device_frame import (
    DISPLAY_ORIENTATION,
    FRAME_SIZE,
    PANEL_MODEL,
    load_demo_frame,
)


client = TestClient(app)


def test_bringup_frame_has_valid_transport_metadata() -> None:
    response = client.get("/v1/bringup/frame")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/octet-stream"
    assert response.headers["content-length"] == str(FRAME_SIZE)
    assert response.headers["x-panel-model"] == PANEL_MODEL
    assert response.headers["x-display-orientation"] == DISPLAY_ORIENTATION
    assert len(response.content) == FRAME_SIZE
    assert response.headers["x-frame-sha256"] == sha256(response.content).hexdigest()


def test_bringup_frame_honors_etag() -> None:
    frame = load_demo_frame()

    response = client.get(
        "/v1/bringup/frame",
        headers={"If-None-Match": frame.etag},
    )

    assert response.status_code == 304
    assert response.content == b""
    assert response.headers["etag"] == frame.etag
