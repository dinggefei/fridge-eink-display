from __future__ import annotations

import hashlib
import hmac
import time
from datetime import date, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.device_frame import FRAME_SIZE, load_inventory_frame
from app.services.inventory_store import InventoryStore, get_inventory_store
from app.settings import get_settings


client = TestClient(app)


@pytest.fixture(autouse=True)
def isolated_inventory(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    data_path = tmp_path / "inventory.json"
    monkeypatch.setenv("INVENTORY_DATA_PATH", str(data_path))
    get_settings.cache_clear()
    get_inventory_store.cache_clear()
    yield data_path
    get_inventory_store.cache_clear()
    get_settings.cache_clear()


def item_payload(name: str = "联调苹果") -> dict[str, str]:
    today = date.today()
    return {
        "name": name,
        "quantity": "2",
        "unit": "个",
        "location": "refrigerated",
        "stocked_on": today.isoformat(),
        "suggested_use_by": (today + timedelta(days=5)).isoformat(),
    }


def signed_headers(
    *,
    device_code: str,
    device_secret: str,
    nonce: str,
    etag: str = "",
) -> dict[str, str]:
    timestamp = str(int(time.time()))
    path = f"/v1/devices/{device_code}/frame"
    signing_text = "\n".join(("GET", path, timestamp, nonce, etag))
    signature = hmac.new(
        device_secret.encode(),
        signing_text.encode(),
        hashlib.sha256,
    ).hexdigest()
    headers = {
        "X-Device-Timestamp": timestamp,
        "X-Device-Nonce": nonce,
        "X-Device-Signature": signature,
    }
    if etag:
        headers["If-None-Match"] = etag
    return headers


def test_inventory_is_seeded_and_sorted() -> None:
    response = client.get("/v1/inventory")

    assert response.status_code == 200
    payload = response.json()
    assert payload["revision"] == 1
    assert payload["summary"]["total"] == 8
    assert payload["items"][0]["status"] == "eat_today"
    assert payload["items"][1]["status"] == "overdue"


def test_create_item_persists_and_changes_device_frame(
    isolated_inventory: Path,
) -> None:
    initial_snapshot = get_inventory_store().snapshot()
    initial_frame = load_inventory_frame(initial_snapshot, date.today())

    create_response = client.post("/v1/inventory", json=item_payload())

    assert create_response.status_code == 201
    created_id = create_response.json()["id"]
    current_snapshot = get_inventory_store().snapshot()
    current_frame = load_inventory_frame(current_snapshot, date.today())
    assert current_snapshot.revision == 2
    assert len(current_frame.data) == FRAME_SIZE
    assert current_frame.etag != initial_frame.etag

    reloaded = InventoryStore(isolated_inventory).snapshot()
    assert any(item.id == created_id for item in reloaded.items)


def test_replace_delete_and_filter_item() -> None:
    created = client.post("/v1/inventory", json=item_payload()).json()
    replacement = item_payload("冷冻蓝莓")
    replacement["location"] = "frozen"

    replace_response = client.put(
        f"/v1/inventory/{created['id']}",
        json=replacement,
    )
    filtered_response = client.get(
        "/v1/inventory",
        params={"location": "frozen"},
    )
    delete_response = client.delete(f"/v1/inventory/{created['id']}")

    assert replace_response.status_code == 200
    assert replace_response.json()["name"] == "冷冻蓝莓"
    assert any(
        item["id"] == created["id"]
        for item in filtered_response.json()["items"]
    )
    assert delete_response.status_code == 204
    assert client.delete(f"/v1/inventory/{created['id']}").status_code == 404


def test_rename_household_changes_revision() -> None:
    response = client.put(
        "/v1/inventory/settings/household",
        json={"name": "图拉的冰箱"},
    )

    assert response.status_code == 200
    assert response.json()["household_name"] == "图拉的冰箱"
    assert response.json()["revision"] == 2


def test_rejects_use_by_before_stocked_on() -> None:
    payload = item_payload()
    payload["suggested_use_by"] = (
        date.fromisoformat(payload["stocked_on"]) - timedelta(days=1)
    ).isoformat()

    response = client.post("/v1/inventory", json=payload)

    assert response.status_code == 422


def test_inventory_change_publishes_new_authenticated_device_frame() -> None:
    settings = get_settings()
    path = f"/v1/devices/{settings.device_code}/frame"
    first_response = client.get(
        path,
        headers=signed_headers(
            device_code=settings.device_code,
            device_secret=settings.device_secret,
            nonce="inventory-frame-before-0001",
        ),
    )
    first_etag = first_response.headers["etag"]

    create_response = client.post(
        "/v1/inventory",
        json=item_payload("屏幕联调苹果"),
    )
    second_response = client.get(
        path,
        headers=signed_headers(
            device_code=settings.device_code,
            device_secret=settings.device_secret,
            nonce="inventory-frame-after-00001",
            etag=first_etag,
        ),
    )

    assert first_response.status_code == 200
    assert create_response.status_code == 201
    assert second_response.status_code == 200
    assert len(second_response.content) == FRAME_SIZE
    assert second_response.headers["etag"] != first_etag
