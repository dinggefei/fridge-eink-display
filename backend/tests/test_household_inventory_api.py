from __future__ import annotations

import asyncio
import hashlib
import hmac
import time
from datetime import date, timedelta
from decimal import Decimal
from io import BytesIO
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy.ext.asyncio import (
    async_sessionmaker,
    create_async_engine,
)

from app.db.base import Base
from app.db.session import get_db_session
from app.main import app
from app.services.device_provisioning import decrypt_provisioning_payload
from app.services.display_photo_storage import get_display_photo_storage
from app.services.inventory_store import get_inventory_store
from app.services.market_data import MarketCatalogItem, MarketSearchResult
from app.services.weather import get_weather_data_provider
from app.services.wechat_login import WechatIdentity
from app.settings import get_settings


@pytest.fixture
def database_client(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    monkeypatch.setenv(
        "AUTH_TOKEN_SECRET",
        "test-secret-with-at-least-thirty-two-characters",
    )
    monkeypatch.setenv("ALLOW_DEV_LOGIN", "true")
    monkeypatch.setenv(
        "INVENTORY_DATA_PATH",
        str(tmp_path / "inventory.json"),
    )
    monkeypatch.setenv(
        "DISPLAY_PHOTO_LOCAL_DIR",
        str(tmp_path / "display-photos"),
    )
    get_settings.cache_clear()
    get_display_photo_storage.cache_clear()
    get_inventory_store.cache_clear()

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'api.db'}")
    sessions = async_sessionmaker(engine, expire_on_commit=False)

    async def prepare_database() -> None:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

    async def override_session():
        async with sessions() as session:
            yield session

    asyncio.run(prepare_database())
    app.dependency_overrides[get_db_session] = override_session
    with TestClient(app) as client:
        yield client

    app.dependency_overrides.clear()
    asyncio.run(engine.dispose())
    get_inventory_store.cache_clear()
    get_display_photo_storage.cache_clear()
    get_settings.cache_clear()


def _item_payload(name: str) -> dict[str, str]:
    today = date.today()
    return {
        "name": name,
        "quantity": "2",
        "unit": "个",
        "location": "refrigerated",
        "stocked_on": today.isoformat(),
        "suggested_use_by": (today + timedelta(days=5)).isoformat(),
    }


def _photo_payload(color: tuple[int, int, int]) -> bytes:
    output = BytesIO()
    Image.new("RGB", (1200, 800), color).save(output, format="JPEG", quality=92)
    return output.getvalue()


def _signed_frame_headers(
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


def test_dev_login_imports_legacy_inventory_and_returns_household(
    database_client: TestClient,
) -> None:
    login = database_client.post(
        "/v1/auth/dev-login",
        json={"nickname": "数据库联调用户"},
    )

    assert login.status_code == 200
    session = login.json()
    assert session["user"]["nickname"] == "数据库联调用户"
    assert len(session["households"]) == 1

    household_id = session["current_household_id"]
    inventory = database_client.get(
        f"/v1/households/{household_id}/inventory",
        headers={"Authorization": f"Bearer {session['access_token']}"},
    )

    assert inventory.status_code == 200
    assert inventory.json()["summary"]["total"] == 8
    assert inventory.json()["household_name"] == "我的冰箱"


def test_authenticated_household_inventory_crud(
    database_client: TestClient,
) -> None:
    session = database_client.post(
        "/v1/auth/dev-login",
        json={"nickname": "数据库联调用户"},
    ).json()
    household_id = session["current_household_id"]
    headers = {
        "Authorization": f"Bearer {session['access_token']}",
        "X-Idempotency-Key": "create-integration-apple",
    }

    created = database_client.post(
        f"/v1/households/{household_id}/inventory",
        json=_item_payload("数据库苹果"),
        headers=headers,
    )
    assert created.status_code == 201

    item_id = created.json()["id"]
    replacement = _item_payload("数据库青苹果")
    updated = database_client.put(
        f"/v1/households/{household_id}/inventory/{item_id}",
        json=replacement,
        headers={
            **headers,
            "X-Idempotency-Key": "update-integration-apple",
        },
    )
    assert updated.status_code == 200
    assert updated.json()["name"] == "数据库青苹果"

    deleted = database_client.delete(
        f"/v1/households/{household_id}/inventory/{item_id}",
        headers={
            **headers,
            "X-Idempotency-Key": "delete-integration-apple",
        },
    )
    assert deleted.status_code == 204

    inventory = database_client.get(
        f"/v1/households/{household_id}/inventory",
        headers=headers,
    ).json()
    assert all(item["id"] != item_id for item in inventory["items"])
    assert inventory["revision"] == 4


def test_inventory_consume_discard_history_and_restore(
    database_client: TestClient,
) -> None:
    login = database_client.post(
        "/v1/auth/dev-login",
        json={"nickname": "库存操作用户"},
    ).json()
    household_id = login["current_household_id"]
    headers = {"Authorization": f"Bearer {login['access_token']}"}
    created = database_client.post(
        f"/v1/households/{household_id}/inventory",
        json=_item_payload("可撤销牛奶"),
        headers=headers,
    ).json()

    consumed = database_client.post(
        (
            f"/v1/households/{household_id}/inventory/"
            f"{created['id']}/actions"
        ),
        json={"action": "consume", "quantity": "0.5"},
        headers=headers,
    )
    assert consumed.status_code == 200
    assert Decimal(consumed.json()["item"]["quantity"]) == Decimal("1.5")

    history = database_client.get(
        f"/v1/households/{household_id}/inventory/history",
        headers=headers,
    )
    assert history.status_code == 200
    consume_event = next(
        item for item in history.json()["items"]
        if item["action"] == "consume"
    )
    assert consume_event["reversible"] is True

    restored = database_client.post(
        (
            f"/v1/households/{household_id}/inventory/history/"
            f"{consume_event['id']}/restore"
        ),
        headers=headers,
    )
    assert restored.status_code == 200
    assert Decimal(restored.json()["item"]["quantity"]) == Decimal("2")

    restored_twice = database_client.post(
        (
            f"/v1/households/{household_id}/inventory/history/"
            f"{consume_event['id']}/restore"
        ),
        headers=headers,
    )
    assert restored_twice.status_code == 409


def test_household_inventory_requires_authentication(
    database_client: TestClient,
) -> None:
    response = database_client.get(
        "/v1/households/not-accessible/inventory"
    )

    assert response.status_code == 401


def test_admin_rename_changes_session_and_portrait_device_frame(
    database_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    login = database_client.post(
        "/v1/auth/dev-login",
        json={"nickname": "冰箱名称管理员"},
    ).json()
    household_id = login["current_household_id"]
    auth_headers = {
        "Authorization": f"Bearer {login['access_token']}"
    }
    settings = get_settings()
    monkeypatch.setenv("DATABASE_INVENTORY_ENABLED", "true")
    get_settings.cache_clear()
    path = f"/v1/devices/{settings.device_code}/frame"

    first_frame = database_client.get(
        path,
        headers=_signed_frame_headers(
            device_code=settings.device_code,
            device_secret=settings.device_secret,
            nonce="rename-frame-before-001",
        ),
    )
    renamed = database_client.put(
        f"/v1/households/{household_id}/inventory/settings/household",
        headers=auth_headers,
        json={"name": "小明的冰箱"},
    )
    second_frame = database_client.get(
        path,
        headers=_signed_frame_headers(
            device_code=settings.device_code,
            device_secret=settings.device_secret,
            nonce="rename-frame-after-0001",
            etag=first_frame.headers["etag"],
        ),
    )
    current_session = database_client.get("/v1/me", headers=auth_headers)

    assert first_frame.status_code == 200
    assert renamed.status_code == 200
    assert renamed.json()["household_name"] == "小明的冰箱"
    assert renamed.json()["revision"] == 2
    assert second_frame.status_code == 200
    assert second_frame.headers["x-display-orientation"] == "portrait"
    assert second_frame.headers["etag"] != first_frame.headers["etag"]
    assert current_session.json()["households"][0]["name"] == "小明的冰箱"


def test_admin_display_todos_change_portrait_device_frame(
    database_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    login = database_client.post(
        "/v1/auth/dev-login",
        json={"nickname": "待办管理员"},
    ).json()
    household_id = login["current_household_id"]
    auth_headers = {"Authorization": f"Bearer {login['access_token']}"}
    settings = get_settings()
    monkeypatch.setenv("DATABASE_INVENTORY_ENABLED", "true")
    get_settings.cache_clear()
    frame_path = f"/v1/devices/{settings.device_code}/frame"

    first_frame = database_client.get(
        frame_path,
        headers=_signed_frame_headers(
            device_code=settings.device_code,
            device_secret=settings.device_secret,
            nonce="todos-frame-before-0001",
        ),
    )
    saved = database_client.put(
        f"/v1/households/{household_id}/inventory/settings/display-todos",
        headers=auth_headers,
        json={"items": ["买牛奶", "清理冷藏室", "补充鸡蛋", "倒垃圾"]},
    )
    read_back = database_client.get(
        f"/v1/households/{household_id}/inventory/settings/display-todos",
        headers=auth_headers,
    )
    second_frame = database_client.get(
        frame_path,
        headers=_signed_frame_headers(
            device_code=settings.device_code,
            device_secret=settings.device_secret,
            nonce="todos-frame-after-00001",
            etag=first_frame.headers["etag"],
        ),
    )

    assert first_frame.status_code == 200
    assert saved.status_code == 200
    assert saved.json()["items"] == [
        "买牛奶",
        "清理冷藏室",
        "补充鸡蛋",
        "倒垃圾",
    ]
    assert read_back.json()["items"] == saved.json()["items"]
    assert second_frame.status_code == 200
    assert second_frame.headers["etag"] != first_frame.headers["etag"]


def test_display_todos_validate_limits(
    database_client: TestClient,
) -> None:
    login = database_client.post(
        "/v1/auth/dev-login",
        json={"nickname": "待办限制测试"},
    ).json()
    household_id = login["current_household_id"]
    headers = {"Authorization": f"Bearer {login['access_token']}"}
    path = (
        f"/v1/households/{household_id}/inventory/settings/display-todos"
    )

    too_many = database_client.put(
        path,
        headers=headers,
        json={"items": [f"待办{index}" for index in range(11)]},
    )
    too_long = database_client.put(
        path,
        headers=headers,
        json={"items": ["长" * 41]},
    )

    assert too_many.status_code == 422
    assert too_long.status_code == 422


def test_household_album_preview_confirm_and_device_frame(
    database_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    login = database_client.post(
        "/v1/auth/dev-login",
        json={"nickname": "相册测试成员"},
    ).json()
    household_id = login["current_household_id"]
    auth_headers = {"Authorization": f"Bearer {login['access_token']}"}
    settings = get_settings()

    uploaded = database_client.post(
        f"/v1/households/{household_id}/display-album/photos",
        headers=auth_headers,
        files={
            "image": (
                "家庭照片.jpg",
                _photo_payload((196, 43, 37)),
                "image/jpeg",
            )
        },
    )
    assert uploaded.status_code == 201
    photo = uploaded.json()
    assert photo["status"] == "pending"
    assert photo["width"] == 480
    assert photo["height"] == 800

    preview = database_client.get(photo["image_path"], headers=auth_headers)
    assert preview.status_code == 200
    assert preview.headers["cache-control"] == "private, no-store"
    with Image.open(BytesIO(preview.content)) as image:
        assert image.size == (480, 800)
        assert set(image.convert("RGB").get_flattened_data()) <= {
            (17, 17, 17),
            (255, 255, 255),
            (224, 160, 0),
            (196, 43, 37),
        }

    confirmed = database_client.post(
        (
            f"/v1/households/{household_id}/display-album/"
            f"photos/{photo['id']}/confirm"
        ),
        headers=auth_headers,
    )
    assert confirmed.status_code == 200
    assert confirmed.json()["display_mode"] == "inventory"
    assert confirmed.json()["photos"][0]["status"] == "confirmed"

    enabled = database_client.put(
        f"/v1/households/{household_id}/display-album/settings",
        headers=auth_headers,
        json={
            "display_mode": "album",
            "rotation_hours": 24,
            "active_photo_id": photo["id"],
        },
    )
    assert enabled.status_code == 200
    assert enabled.json()["display_mode"] == "album"
    assert enabled.json()["rotation_hours"] == 24
    assert enabled.json()["active_photo_id"] == photo["id"]

    monkeypatch.setenv("DATABASE_INVENTORY_ENABLED", "true")
    get_settings.cache_clear()
    frame_path = f"/v1/devices/{settings.device_code}/frame"
    frame = database_client.get(
        frame_path,
        headers=_signed_frame_headers(
            device_code=settings.device_code,
            device_secret=settings.device_secret,
            nonce="album-frame-confirmed-0001",
        ),
    )
    assert frame.status_code == 200
    assert frame.headers["x-frame-version"].startswith("photo-")
    assert len(frame.content) == 96000

    deleted = database_client.delete(
        (
            f"/v1/households/{household_id}/display-album/"
            f"photos/{photo['id']}"
        ),
        headers=auth_headers,
    )
    assert deleted.status_code == 200
    assert deleted.json()["display_mode"] == "inventory"
    assert deleted.json()["photos"] == []


def test_album_mode_requires_a_confirmed_photo(
    database_client: TestClient,
) -> None:
    login = database_client.post(
        "/v1/auth/dev-login",
        json={"nickname": "空相册测试"},
    ).json()
    household_id = login["current_household_id"]
    headers = {"Authorization": f"Bearer {login['access_token']}"}

    response = database_client.put(
        f"/v1/households/{household_id}/display-album/settings",
        headers=headers,
        json={"display_mode": "album"},
    )

    assert response.status_code == 409


def test_album_rotation_accepts_short_intervals(
    database_client: TestClient,
) -> None:
    login = database_client.post(
        "/v1/auth/dev-login",
        json={"nickname": "短周期轮播测试"},
    ).json()
    household_id = login["current_household_id"]
    headers = {"Authorization": f"Bearer {login['access_token']}"}
    path = f"/v1/households/{household_id}/display-album/settings"

    one_hour = database_client.put(
        path,
        headers=headers,
        json={"rotation_hours": 1},
    )
    assert one_hour.status_code == 200
    assert one_hour.json()["rotation_hours"] == 1

    three_hours = database_client.put(
        path,
        headers=headers,
        json={"rotation_hours": 3},
    )
    assert three_hours.status_code == 200
    assert three_hours.json()["rotation_hours"] == 3

    unsupported = database_client.put(
        path,
        headers=headers,
        json={"rotation_hours": 2},
    )
    assert unsupported.status_code == 422
    assert unsupported.json()["detail"] == (
        "rotation_hours must be 1, 3, 6, 12 or 24"
    )


def test_market_dashboard_settings_and_device_frame(
    database_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    login = database_client.post(
        "/v1/auth/dev-login",
        json={"nickname": "行情看板测试"},
    ).json()
    household_id = login["current_household_id"]
    auth_headers = {"Authorization": f"Bearer {login['access_token']}"}
    dashboard_path = f"/v1/households/{household_id}/display-market"
    selections = [
        {"asset_type": "crypto", "symbol": "BTC"},
        {"asset_type": "crypto", "symbol": "ETH"},
        {"asset_type": "us_stock", "symbol": "AAPL"},
        {"asset_type": "us_stock", "symbol": "MSFT"},
        {"asset_type": "us_stock", "symbol": "NVDA"},
        {"asset_type": "us_stock", "symbol": "TSLA"},
    ]

    initial_settings = database_client.get(
        f"/v1/households/{household_id}/display-settings",
        headers=auth_headers,
    )
    assert initial_settings.json()["market_ready"] is False

    saved = database_client.put(
        dashboard_path,
        headers=auth_headers,
        json={
            "refresh_minutes": 15,
            "night_pause": False,
            "assets": selections,
        },
    )
    assert saved.status_code == 200
    assert saved.json()["refresh_minutes"] == 15
    assert saved.json()["night_pause"] is False
    assert len(saved.json()["assets"]) == 6
    assert saved.json()["assets"][4]["symbol"] == "NVDA"
    assert saved.json()["assets"][4]["currency"] == "USD"
    assert Decimal(saved.json()["assets"][4]["price"]) == Decimal("182.76")
    assert {item["symbol"] for item in saved.json()["catalog"]} == {
        "BTC",
        "ETH",
        "AAPL",
        "MSFT",
        "NVDA",
        "TSLA",
        "600519.SH",
        "300750.SZ",
        "601318.SH",
        "00700.HK",
        "01810.HK",
        "00005.HK",
        "09988.HK",
        "HSI",
        "IXIC",
    }

    forced_refresh = AsyncMock()
    monkeypatch.setattr(
        "app.api.display_settings.load_market_snapshot",
        forced_refresh,
    )
    enabled = database_client.put(
        f"/v1/households/{household_id}/display-settings",
        headers=auth_headers,
        json={"display_mode": "market"},
    )
    assert enabled.status_code == 200
    assert enabled.json()["display_mode"] == "market"
    assert enabled.json()["market_ready"] is True
    forced_refresh.assert_awaited_once()
    assert forced_refresh.await_args.kwargs == {"force_refresh": True}

    unchanged_mode = database_client.put(
        f"/v1/households/{household_id}/display-settings",
        headers=auth_headers,
        json={"display_mode": "market"},
    )
    assert unchanged_mode.status_code == 200
    forced_refresh.assert_awaited_once()

    settings = get_settings()
    monkeypatch.setenv("DATABASE_INVENTORY_ENABLED", "true")
    get_settings.cache_clear()
    frame_path = f"/v1/devices/{settings.device_code}/frame"
    first = database_client.get(
        frame_path,
        headers=_signed_frame_headers(
            device_code=settings.device_code,
            device_secret=settings.device_secret,
            nonce="market-frame-20260909-0001",
        ),
    )
    assert first.status_code == 200
    assert first.headers["x-frame-version"].startswith("market-v1-")
    assert len(first.content) == 96000

    unchanged = database_client.get(
        frame_path,
        headers=_signed_frame_headers(
            device_code=settings.device_code,
            device_secret=settings.device_secret,
            nonce="market-frame-20260909-0002",
            etag=first.headers["etag"],
        ),
    )
    assert unchanged.status_code == 304

    cleared = database_client.put(
        dashboard_path,
        headers=auth_headers,
        json={"assets": []},
    )
    assert cleared.status_code == 200
    assert cleared.json()["display_mode"] == "inventory"
    assert cleared.json()["assets"] == []


def test_market_dashboard_validates_catalog_and_capacity(
    database_client: TestClient,
) -> None:
    login = database_client.post(
        "/v1/auth/dev-login",
        json={"nickname": "行情限制测试"},
    ).json()
    household_id = login["current_household_id"]
    headers = {"Authorization": f"Bearer {login['access_token']}"}
    path = f"/v1/households/{household_id}/display-market"

    for asset_type, symbol in (
        ("cn_stock", "600519.SH"),
        ("hk_stock", "00700.HK"),
        ("index", "HSI"),
    ):
        supported = database_client.put(
            path,
            headers=headers,
            json={"assets": [{"asset_type": asset_type, "symbol": symbol}]},
        )
        assert supported.status_code == 200
        assert supported.json()["assets"][0]["symbol"] == symbol

    unsupported = database_client.put(
        path,
        headers=headers,
        json={"assets": [{"asset_type": "hk_stock", "symbol": "INVALID.HK"}]},
    )
    assert unsupported.status_code == 422

    too_many = database_client.put(
        path,
        headers=headers,
        json={
            "assets": [
                {"asset_type": "crypto", "symbol": "BTC"},
                {"asset_type": "crypto", "symbol": "ETH"},
                {"asset_type": "us_stock", "symbol": "AAPL"},
                {"asset_type": "us_stock", "symbol": "MSFT"},
                {"asset_type": "us_stock", "symbol": "NVDA"},
                {"asset_type": "hk_stock", "symbol": "00700.HK"},
                {"asset_type": "index", "symbol": "HSI"},
            ]
        },
    )
    assert too_many.status_code == 422


def test_market_search_add_and_delete_dynamic_asset(
    database_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    login = database_client.post(
        "/v1/auth/dev-login",
        json={"nickname": "动态行情搜索测试"},
    ).json()
    household_id = login["current_household_id"]
    headers = {"Authorization": f"Bearer {login['access_token']}"}
    path = f"/v1/households/{household_id}/display-market"

    async def fake_search(asset_type, query, *, limit):
        assert asset_type.value == "crypto"
        assert query == "solana"
        assert limit == 20
        return [
            MarketSearchResult(
                asset_type=asset_type,
                symbol="SOL",
                name="Solana",
                currency="USD",
                provider_symbol="solana",
            )
        ]

    async def fake_resolve(asset_type, provider_symbol):
        assert asset_type.value == "crypto"
        assert provider_symbol == "solana"
        return MarketCatalogItem(
            asset_type=asset_type,
            symbol="SOL",
            name="Solana",
            currency="USD",
            provider_symbol="solana",
        )

    monkeypatch.setattr(
        "app.api.display_market.search_market_assets",
        fake_search,
    )
    monkeypatch.setattr(
        "app.api.display_market.resolve_market_asset",
        fake_resolve,
    )

    searched = database_client.get(
        f"{path}/search",
        headers=headers,
        params={"asset_type": "crypto", "query": "solana"},
    )
    assert searched.status_code == 200
    assert searched.json() == [
        {
            "asset_type": "crypto",
            "symbol": "SOL",
            "name": "Solana",
            "currency": "USD",
            "provider_symbol": "solana",
        }
    ]

    added = database_client.post(
        f"{path}/assets",
        headers=headers,
        json={"asset_type": "crypto", "provider_symbol": "solana"},
    )
    assert added.status_code == 201
    assert added.json()["assets"][0]["symbol"] == "SOL"
    assert added.json()["assets"][0]["name"] == "Solana"
    asset_id = added.json()["assets"][0]["id"]

    duplicate = database_client.post(
        f"{path}/assets",
        headers=headers,
        json={"asset_type": "crypto", "provider_symbol": "solana"},
    )
    assert duplicate.status_code == 409

    reordered = database_client.put(
        path,
        headers=headers,
        json={
            "assets": [
                {"asset_type": "crypto", "symbol": "BTC"},
                {"asset_type": "crypto", "symbol": "SOL"},
            ]
        },
    )
    assert reordered.status_code == 200
    assert [item["symbol"] for item in reordered.json()["assets"]] == [
        "BTC",
        "SOL",
    ]

    deleted = database_client.delete(
        f"{path}/assets/{asset_id}",
        headers=headers,
    )
    assert deleted.status_code == 200
    assert [item["symbol"] for item in deleted.json()["assets"]] == ["BTC"]


def test_market_mode_rejects_mock_provider_in_production(
    database_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    login = database_client.post(
        "/v1/auth/dev-login",
        json={"nickname": "生产行情保护测试"},
    ).json()
    household_id = login["current_household_id"]
    headers = {"Authorization": f"Bearer {login['access_token']}"}
    saved = database_client.put(
        f"/v1/households/{household_id}/display-market",
        headers=headers,
        json={"assets": [{"asset_type": "crypto", "symbol": "BTC"}]},
    )
    assert saved.status_code == 200

    class EmptySecret:
        @staticmethod
        def get_secret_value() -> str:
            return ""

    class ProductionSettings:
        app_env = "production"
        market_data_provider = "mock"
        twelve_data_api_key = EmptySecret()
        coingecko_api_key = EmptySecret()

    monkeypatch.setattr(
        "app.api.display_settings.get_settings",
        lambda: ProductionSettings(),
    )
    enabled = database_client.put(
        f"/v1/households/{household_id}/display-settings",
        headers=headers,
        json={"display_mode": "market"},
    )
    assert enabled.status_code == 503
    assert enabled.json()["detail"] == (
        "live market data provider is not configured"
    )


def test_admin_can_invite_join_switch_and_remove_household_member(
    database_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    admin_session = database_client.post(
        "/v1/auth/dev-login",
        json={"nickname": "家庭管理员"},
    ).json()
    household_id = admin_session["current_household_id"]
    admin_headers = {
        "Authorization": f"Bearer {admin_session['access_token']}"
    }

    invitation = database_client.post(
        f"/v1/households/{household_id}/invitations",
        headers=admin_headers,
    )
    assert invitation.status_code == 201
    invitation_code = invitation.json()["code"]

    async def fake_exchange_login_code(code: str) -> WechatIdentity:
        assert code == "member-login-code"
        return WechatIdentity(openid="household-member-openid")

    monkeypatch.setattr(
        "app.api.auth.exchange_login_code",
        fake_exchange_login_code,
    )
    member_session = database_client.post(
        "/v1/auth/wechat",
        json={"code": "member-login-code"},
    ).json()
    member_headers = {
        "Authorization": f"Bearer {member_session['access_token']}"
    }
    original_household_id = member_session["current_household_id"]

    joined = database_client.post(
        "/v1/households/join",
        headers=member_headers,
        json={"invitation_code": invitation_code.lower()},
    )
    assert joined.status_code == 200
    assert joined.json()["current_household_id"] == household_id
    assert len(joined.json()["households"]) == 2

    reused = database_client.post(
        "/v1/households/join",
        headers=member_headers,
        json={"invitation_code": invitation_code},
    )
    assert reused.status_code == 409

    member_rename = database_client.put(
        f"/v1/households/{household_id}/inventory/settings/household",
        headers=member_headers,
        json={"name": "成员不能修改"},
    )
    assert member_rename.status_code == 403

    member_todo_update = database_client.put(
        f"/v1/households/{household_id}/inventory/settings/display-todos",
        headers=member_headers,
        json={"items": ["成员可以修改"]},
    )
    assert member_todo_update.status_code == 200
    assert member_todo_update.json()["items"] == ["成员可以修改"]

    admin_reads_member_todo = database_client.get(
        f"/v1/households/{household_id}/inventory/settings/display-todos",
        headers=admin_headers,
    )
    assert admin_reads_member_todo.status_code == 200
    assert admin_reads_member_todo.json()["items"] == ["成员可以修改"]

    member_display_settings = database_client.put(
        f"/v1/households/{household_id}/display-settings",
        headers=member_headers,
        json={"display_mode": "almanac"},
    )
    assert member_display_settings.status_code == 200
    assert member_display_settings.json()["display_mode"] == "almanac"
    admin_reads_display_settings = database_client.get(
        f"/v1/households/{household_id}/display-settings",
        headers=admin_headers,
    )
    assert admin_reads_display_settings.status_code == 200
    assert admin_reads_display_settings.json()["display_mode"] == "almanac"

    member_market_update = database_client.put(
        f"/v1/households/{household_id}/display-market",
        headers=member_headers,
        json={
            "refresh_minutes": 60,
            "night_pause": True,
            "assets": [{"asset_type": "us_stock", "symbol": "AAPL"}],
        },
    )
    assert member_market_update.status_code == 200
    assert member_market_update.json()["assets"][0]["symbol"] == "AAPL"

    member_photo = database_client.post(
        f"/v1/households/{household_id}/display-album/photos",
        headers=member_headers,
        files={
            "image": (
                "成员照片.png",
                _photo_payload((224, 160, 0)),
                "application/octet-stream",
            )
        },
    )
    assert member_photo.status_code == 201
    photo_id = member_photo.json()["id"]
    member_confirm = database_client.post(
        (
            f"/v1/households/{household_id}/display-album/"
            f"photos/{photo_id}/confirm"
        ),
        headers=member_headers,
    )
    assert member_confirm.status_code == 200
    admin_preview = database_client.get(
        member_photo.json()["image_path"],
        headers=admin_headers,
    )
    assert admin_preview.status_code == 200
    member_delete = database_client.delete(
        (
            f"/v1/households/{household_id}/display-album/"
            f"photos/{photo_id}"
        ),
        headers=member_headers,
    )
    assert member_delete.status_code == 200

    switched = database_client.post(
        "/v1/me/current-household",
        headers=member_headers,
        json={"household_id": original_household_id},
    )
    assert switched.status_code == 200
    assert switched.json()["current_household_id"] == original_household_id

    members = database_client.get(
        f"/v1/households/{household_id}/members",
        headers=admin_headers,
    )
    assert members.status_code == 200
    member = next(
        item for item in members.json() if item["role"] == "member"
    )

    removed = database_client.delete(
        f"/v1/households/{household_id}/members/{member['user_id']}",
        headers=admin_headers,
    )
    assert removed.status_code == 204

    inaccessible = database_client.get(
        f"/v1/households/{household_id}/members",
        headers=member_headers,
    )
    assert inaccessible.status_code == 404
    inaccessible_album = database_client.get(
        f"/v1/households/{household_id}/display-album",
        headers=member_headers,
    )
    assert inaccessible_album.status_code == 404
    inaccessible_display_settings = database_client.get(
        f"/v1/households/{household_id}/display-settings",
        headers=member_headers,
    )
    assert inaccessible_display_settings.status_code == 404


def test_almanac_mode_serves_daily_frame_and_honors_etag(
    database_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    displayed_on = date(2026, 9, 7)
    monkeypatch.setattr(
        "app.api.display_settings.current_display_date",
        lambda: displayed_on,
    )
    monkeypatch.setattr("app.main.current_display_date", lambda: displayed_on)
    login = database_client.post(
        "/v1/auth/dev-login",
        json={"nickname": "黄历显示测试"},
    ).json()
    household_id = login["current_household_id"]
    auth_headers = {"Authorization": f"Bearer {login['access_token']}"}

    settings_response = database_client.get(
        f"/v1/households/{household_id}/display-settings",
        headers=auth_headers,
    )
    assert settings_response.status_code == 200
    assert settings_response.json()["almanac"]["lunar_date"] == (
        "二〇二六年七月廿六"
    )

    selected = database_client.put(
        f"/v1/households/{household_id}/display-settings",
        headers=auth_headers,
        json={"display_mode": "almanac"},
    )
    assert selected.status_code == 200
    assert selected.json()["display_mode"] == "almanac"

    settings = get_settings()
    monkeypatch.setenv("DATABASE_INVENTORY_ENABLED", "true")
    get_settings.cache_clear()
    frame_path = f"/v1/devices/{settings.device_code}/frame"
    first = database_client.get(
        frame_path,
        headers=_signed_frame_headers(
            device_code=settings.device_code,
            device_secret=settings.device_secret,
            nonce="almanac-frame-20260907-0001",
        ),
    )
    assert first.status_code == 200
    assert first.headers["x-frame-version"].startswith(
        "almanac-v2-20260907-lp1.4.8-sect1-"
    )
    assert len(first.content) == 96000

    unchanged = database_client.get(
        frame_path,
        headers=_signed_frame_headers(
            device_code=settings.device_code,
            device_secret=settings.device_secret,
            nonce="almanac-frame-20260907-0002",
            etag=first.headers["etag"],
        ),
    )
    assert unchanged.status_code == 304
    assert unchanged.content == b""


def test_timetable_settings_preview_and_device_frame(
    database_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    login = database_client.post(
        "/v1/auth/dev-login",
        json={"nickname": "课程表显示测试"},
    ).json()
    household_id = login["current_household_id"]
    auth_headers = {"Authorization": f"Bearer {login['access_token']}"}
    timetable_path = f"/v1/households/{household_id}/display-timetable"

    initial = database_client.get(timetable_path, headers=auth_headers)
    assert initial.status_code == 200
    assert len(initial.json()["periods"]) == 7
    assert initial.json()["orientation"] == "portrait"
    assert initial.json()["ready"] is False

    periods = initial.json()["periods"]
    saved = database_client.put(
        timetable_path,
        headers=auth_headers,
        json={
            "orientation": "portrait",
            "periods": periods,
            "entries": [
                {
                    "weekday": 1,
                    "period_id": "morning-1",
                    "course_name": "语文",
                    "note": "预习课文",
                },
                {
                    "weekday": 3,
                    "period_id": "morning-3",
                    "course_name": "科学",
                    "note": "实验课",
                },
            ],
        },
    )
    assert saved.status_code == 200
    assert saved.json()["ready"] is True

    preview = database_client.get(f"{timetable_path}/preview", headers=auth_headers)
    assert preview.status_code == 200
    assert preview.headers["content-type"] == "image/png"
    preview_image = Image.open(BytesIO(preview.content))
    assert preview_image.size == (480, 800)

    landscape_saved = database_client.put(
        timetable_path,
        headers=auth_headers,
        json={
            "orientation": "landscape",
            "periods": periods,
            "entries": saved.json()["entries"],
        },
    )
    assert landscape_saved.status_code == 200
    assert landscape_saved.json()["orientation"] == "landscape"
    landscape_preview = database_client.get(
        f"{timetable_path}/preview", headers=auth_headers
    )
    assert landscape_preview.status_code == 200
    assert Image.open(BytesIO(landscape_preview.content)).size == (800, 480)

    selected = database_client.put(
        f"/v1/households/{household_id}/display-settings",
        headers=auth_headers,
        json={"display_mode": "timetable"},
    )
    assert selected.status_code == 200
    assert selected.json()["display_mode"] == "timetable"
    assert selected.json()["timetable_ready"] is True

    settings = get_settings()
    monkeypatch.setenv("DATABASE_INVENTORY_ENABLED", "true")
    get_settings.cache_clear()
    first = database_client.get(
        f"/v1/devices/{settings.device_code}/frame",
        headers=_signed_frame_headers(
            device_code=settings.device_code,
            device_secret=settings.device_secret,
            nonce="timetable-frame-20260916-0001",
        ),
    )
    assert first.status_code == 200
    assert first.headers["x-frame-version"].startswith("timetable-v6-")
    assert first.headers["x-display-orientation"] == "landscape"
    assert len(first.content) == 96_000


def test_timetable_rejects_invalid_period_reference(
    database_client: TestClient,
) -> None:
    login = database_client.post(
        "/v1/auth/dev-login",
        json={"nickname": "课程表校验测试"},
    ).json()
    household_id = login["current_household_id"]
    response = database_client.put(
        f"/v1/households/{household_id}/display-timetable",
        headers={"Authorization": f"Bearer {login['access_token']}"},
        json={
            "periods": [
                {
                    "id": "morning-1",
                    "section": "morning",
                    "start_time": "08:00",
                    "end_time": "08:45",
                }
            ],
            "entries": [
                {
                    "weekday": 1,
                    "period_id": "missing",
                    "course_name": "语文",
                    "note": "",
                }
            ],
        },
    )
    assert response.status_code == 422


def test_almanac_weather_city_setting_and_device_frame(
    database_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    displayed_on = date(2026, 9, 7)
    monkeypatch.setenv("WEATHER_DATA_PROVIDER", "mock")
    get_settings.cache_clear()
    get_weather_data_provider.cache_clear()
    monkeypatch.setattr(
        "app.api.display_settings.current_display_date",
        lambda: displayed_on,
    )
    monkeypatch.setattr("app.main.current_display_date", lambda: displayed_on)
    login = database_client.post(
        "/v1/auth/dev-login",
        json={"nickname": "黄历天气测试"},
    ).json()
    household_id = login["current_household_id"]
    auth_headers = {"Authorization": f"Bearer {login['access_token']}"}
    settings_path = f"/v1/households/{household_id}/display-settings"

    initial = database_client.get(settings_path, headers=auth_headers)
    assert initial.status_code == 200
    assert initial.json()["weather_enabled"] is False
    assert initial.json()["weather_provider_ready"] is True

    locations = database_client.get(
        f"{settings_path}/weather-locations",
        headers=auth_headers,
        params={"query": "上海"},
    )
    assert locations.status_code == 200
    location = locations.json()[0]
    assert location["name"] == "上海"

    saved = database_client.put(
        f"{settings_path}/weather",
        headers=auth_headers,
        json={"enabled": True, "location": location},
    )
    assert saved.status_code == 200
    assert saved.json()["weather_enabled"] is True
    assert saved.json()["weather_location"]["name"] == "上海"
    assert saved.json()["weather"] == {
        "location_name": "上海",
        "condition_text": "多云",
        "temp_min": 18,
        "temp_max": 27,
        "precip_probability": 20,
    }
    assert saved.json()["weather_source_name"] == "和风天气"

    selected = database_client.put(
        settings_path,
        headers=auth_headers,
        json={"display_mode": "almanac"},
    )
    assert selected.status_code == 200

    settings = get_settings()
    monkeypatch.setenv("DATABASE_INVENTORY_ENABLED", "true")
    get_settings.cache_clear()
    get_weather_data_provider.cache_clear()
    first = database_client.get(
        f"/v1/devices/{settings.device_code}/frame",
        headers=_signed_frame_headers(
            device_code=settings.device_code,
            device_secret=settings.device_secret,
            nonce="almanac-weather-frame-20260907-0001",
        ),
    )
    assert first.status_code == 200
    assert first.headers["x-frame-version"].startswith(
        "almanac-v2-20260907-lp1.4.8-sect1-"
    )
    assert len(first.content) == 96000


def test_member_can_leave_household_and_switch_to_personal_household(
    database_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    admin_session = database_client.post(
        "/v1/auth/dev-login",
        json={"nickname": "退出测试管理员"},
    ).json()
    household_id = admin_session["current_household_id"]
    admin_headers = {
        "Authorization": f"Bearer {admin_session['access_token']}"
    }
    invitation_code = database_client.post(
        f"/v1/households/{household_id}/invitations",
        headers=admin_headers,
    ).json()["code"]

    async def fake_exchange_login_code(code: str) -> WechatIdentity:
        assert code == "leave-member-code"
        return WechatIdentity(openid="leave-member-openid")

    monkeypatch.setattr(
        "app.api.auth.exchange_login_code",
        fake_exchange_login_code,
    )
    member_session = database_client.post(
        "/v1/auth/wechat",
        json={"code": "leave-member-code"},
    ).json()
    original_household_id = member_session["current_household_id"]
    member_headers = {
        "Authorization": f"Bearer {member_session['access_token']}"
    }
    joined = database_client.post(
        "/v1/households/join",
        headers=member_headers,
        json={"invitation_code": invitation_code},
    )
    assert joined.status_code == 200
    assert joined.json()["current_household_id"] == household_id

    left = database_client.post(
        f"/v1/households/{household_id}/leave",
        headers=member_headers,
    )
    assert left.status_code == 200
    assert left.json()["current_household_id"] == original_household_id
    assert [item["id"] for item in left.json()["households"]] == [
        original_household_id
    ]
    assert database_client.get(
        f"/v1/households/{household_id}/members",
        headers=member_headers,
    ).status_code == 404

    members = database_client.get(
        f"/v1/households/{household_id}/members",
        headers=admin_headers,
    ).json()
    assert all(item["role"] == "admin" for item in members)
    assert database_client.post(
        f"/v1/households/{household_id}/leave",
        headers=admin_headers,
    ).status_code == 409


def test_user_can_delete_account_and_recreate_empty_identity(
    database_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_exchange_login_code(code: str) -> WechatIdentity:
        assert code == "delete-account-code"
        return WechatIdentity(openid="delete-account-openid")

    monkeypatch.setattr(
        "app.api.auth.exchange_login_code",
        fake_exchange_login_code,
    )
    original = database_client.post(
        "/v1/auth/wechat",
        json={"code": "delete-account-code"},
    ).json()
    original_headers = {
        "Authorization": f"Bearer {original['access_token']}"
    }

    deleted = database_client.delete("/v1/me", headers=original_headers)
    assert deleted.status_code == 204
    assert database_client.get(
        "/v1/me",
        headers=original_headers,
    ).status_code == 401

    recreated = database_client.post(
        "/v1/auth/wechat",
        json={"code": "delete-account-code"},
    )
    assert recreated.status_code == 200
    assert recreated.json()["user"]["id"] != original["user"]["id"]
    assert (
        recreated.json()["current_household_id"]
        != original["current_household_id"]
    )


def test_admin_must_remove_other_members_before_account_deletion(
    database_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    admin_session = database_client.post(
        "/v1/auth/dev-login",
        json={"nickname": "删除保护管理员"},
    ).json()
    household_id = admin_session["current_household_id"]
    admin_headers = {
        "Authorization": f"Bearer {admin_session['access_token']}"
    }
    invitation_code = database_client.post(
        f"/v1/households/{household_id}/invitations",
        headers=admin_headers,
    ).json()["code"]

    async def fake_exchange_login_code(code: str) -> WechatIdentity:
        assert code == "delete-protected-member-code"
        return WechatIdentity(openid="delete-protected-member-openid")

    monkeypatch.setattr(
        "app.api.auth.exchange_login_code",
        fake_exchange_login_code,
    )
    member_session = database_client.post(
        "/v1/auth/wechat",
        json={"code": "delete-protected-member-code"},
    ).json()
    member_headers = {
        "Authorization": f"Bearer {member_session['access_token']}"
    }
    assert database_client.post(
        "/v1/households/join",
        headers=member_headers,
        json={"invitation_code": invitation_code},
    ).status_code == 200

    blocked = database_client.delete("/v1/me", headers=admin_headers)
    assert blocked.status_code == 409
    assert "仍有其他成员" in blocked.json()["detail"]
    assert database_client.get(
        "/v1/me",
        headers=admin_headers,
    ).status_code == 200


def test_member_can_configure_reminders_and_record_subscription_grant(
    database_client: TestClient,
) -> None:
    login = database_client.post(
        "/v1/auth/dev-login",
        json={"nickname": "提醒测试用户"},
    ).json()
    household_id = login["current_household_id"]
    headers = {"Authorization": f"Bearer {login['access_token']}"}

    initial = database_client.get(
        f"/v1/households/{household_id}/reminders",
        headers=headers,
    )
    assert initial.status_code == 200
    assert initial.json()["subscription_grants"] == 0

    updated = database_client.put(
        f"/v1/households/{household_id}/reminders",
        headers=headers,
        json={
            "enabled": True,
            "reminder_time": "18:30",
            "threshold_days": 2,
        },
    )
    assert updated.status_code == 200
    assert updated.json()["reminder_time"] == "18:30"
    assert updated.json()["threshold_days"] == 2

    granted = database_client.post(
        (
            f"/v1/households/{household_id}/reminders/"
            "subscription-grants"
        ),
        headers=headers,
    )
    assert granted.status_code == 200
    assert granted.json()["subscription_grants"] == 1


def test_admin_can_provision_and_unbind_registered_device(
    database_client: TestClient,
) -> None:
    login = database_client.post(
        "/v1/auth/dev-login",
        json={"nickname": "设备管理员"},
    ).json()
    household_id = login["current_household_id"]
    headers = {"Authorization": f"Bearer {login['access_token']}"}
    settings = get_settings()
    challenge = "00112233445566778899aabbccddeeff"

    created = database_client.post(
        f"/v1/households/{household_id}/devices/provisioning-sessions",
        headers=headers,
        json={
            "device_code": settings.device_code,
            "challenge": challenge,
            "wifi_ssid": "Kitchen-2.4G",
            "wifi_password": "local-test-password",
        },
    )

    assert created.status_code == 201
    body = created.json()
    assert "Kitchen-2.4G" not in body["encrypted_payload"]
    decoded = decrypt_provisioning_payload(
        device_code=settings.device_code,
        device_secret=settings.device_secret,
        challenge_hex=challenge,
        encrypted_payload=body["encrypted_payload"],
    )
    assert decoded.wifi_ssid == "Kitchen-2.4G"
    assert decoded.wifi_password == "local-test-password"

    completed = database_client.post(
        f"/v1/devices/{settings.device_code}/provisioning/complete",
        json={
            "session_id": body["id"],
            "binding_token": decoded.binding_token,
        },
    )
    assert completed.status_code == 200
    assert completed.json()["status"] == "online"

    unbound = database_client.post(
        f"/v1/households/{household_id}/devices/"
        f"{settings.device_code}/unbind",
        headers=headers,
    )
    assert unbound.status_code == 200
    assert unbound.json()["status"] == "unbound"
    assert unbound.json()["household_id"] is None


def test_device_display_mode_override_does_not_change_household_default(
    database_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    login = database_client.post(
        "/v1/auth/dev-login",
        json={"nickname": "多屏独立显示测试"},
    ).json()
    household_id = login["current_household_id"]
    auth_headers = {"Authorization": f"Bearer {login['access_token']}"}
    settings = get_settings()
    challenge = "102132435465768798a9bacbdcedfe0f"

    created = database_client.post(
        f"/v1/households/{household_id}/devices/provisioning-sessions",
        headers=auth_headers,
        json={
            "device_code": settings.device_code,
            "challenge": challenge,
            "wifi_ssid": "Kitchen-2.4G",
            "wifi_password": "local-test-password",
        },
    )
    assert created.status_code == 201
    decoded = decrypt_provisioning_payload(
        device_code=settings.device_code,
        device_secret=settings.device_secret,
        challenge_hex=challenge,
        encrypted_payload=created.json()["encrypted_payload"],
    )
    completed = database_client.post(
        f"/v1/devices/{settings.device_code}/provisioning/complete",
        json={
            "session_id": created.json()["id"],
            "binding_token": decoded.binding_token,
        },
    )
    assert completed.status_code == 200

    settings_path = f"/v1/households/{household_id}/display-settings"
    household = database_client.put(
        settings_path,
        headers=auth_headers,
        json={"display_mode": "almanac"},
    )
    assert household.status_code == 200
    assert household.json()["scope"] == "household"
    assert household.json()["display_mode"] == "almanac"

    inherited = database_client.get(
        settings_path,
        headers=auth_headers,
        params={"device_code": settings.device_code},
    )
    assert inherited.status_code == 200
    assert inherited.json()["scope"] == "device"
    assert inherited.json()["inherits_household"] is True
    assert inherited.json()["display_mode"] == "almanac"

    overridden = database_client.put(
        settings_path,
        headers=auth_headers,
        params={"device_code": settings.device_code},
        json={"display_mode": "inventory"},
    )
    assert overridden.status_code == 200
    assert overridden.json()["inherits_household"] is False
    assert overridden.json()["display_mode"] == "inventory"
    assert overridden.json()["household_display_mode"] == "almanac"

    unchanged_household = database_client.get(
        settings_path,
        headers=auth_headers,
    )
    assert unchanged_household.json()["display_mode"] == "almanac"

    monkeypatch.setenv("DATABASE_INVENTORY_ENABLED", "true")
    get_settings.cache_clear()
    frame = database_client.get(
        f"/v1/devices/{settings.device_code}/frame",
        headers=_signed_frame_headers(
            device_code=settings.device_code,
            device_secret=settings.device_secret,
            nonce="device-mode-override-20260920-0001",
        ),
    )
    assert frame.status_code == 200
    assert frame.headers["x-frame-version"].startswith("inventory-")

    restored = database_client.put(
        settings_path,
        headers=auth_headers,
        params={"device_code": settings.device_code},
        json={"display_mode": None},
    )
    assert restored.status_code == 200
    assert restored.json()["inherits_household"] is True
    assert restored.json()["display_mode"] == "almanac"


def test_scanned_device_entry_routes_members_without_leaking_household(
    database_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    admin_session = database_client.post(
        "/v1/auth/dev-login",
        json={"nickname": "扫码设备管理员"},
    ).json()
    household_id = admin_session["current_household_id"]
    admin_headers = {
        "Authorization": f"Bearer {admin_session['access_token']}"
    }
    device_code = get_settings().device_code

    accessible = database_client.get(
        f"/v1/devices/{device_code}/entry",
        headers=admin_headers,
    )
    assert accessible.status_code == 200
    assert accessible.json() == {
        "state": "accessible",
        "household_id": household_id,
    }

    async def fake_exchange_login_code(code: str) -> WechatIdentity:
        assert code == "device-entry-outsider-code"
        return WechatIdentity(openid="device-entry-outsider-openid")

    monkeypatch.setattr(
        "app.api.auth.exchange_login_code",
        fake_exchange_login_code,
    )
    outsider_session = database_client.post(
        "/v1/auth/wechat",
        json={"code": "device-entry-outsider-code"},
    ).json()
    outsider_headers = {
        "Authorization": f"Bearer {outsider_session['access_token']}"
    }
    unavailable = database_client.get(
        f"/v1/devices/{device_code}/entry",
        headers=outsider_headers,
    )
    assert unavailable.status_code == 200
    assert unavailable.json() == {
        "state": "unavailable",
        "household_id": None,
    }

    invitation_code = database_client.post(
        f"/v1/households/{household_id}/invitations",
        headers=admin_headers,
    ).json()["code"]
    joined = database_client.post(
        "/v1/households/join",
        headers=outsider_headers,
        json={"invitation_code": invitation_code},
    )
    assert joined.status_code == 200
    assert joined.json()["current_household_id"] == household_id

    switched_back = database_client.post(
        "/v1/me/current-household",
        headers=outsider_headers,
        json={"household_id": outsider_session["current_household_id"]},
    )
    assert switched_back.status_code == 200
    member_entry = database_client.get(
        f"/v1/devices/{device_code}/entry",
        headers=outsider_headers,
    )
    assert member_entry.status_code == 200
    assert member_entry.json() == {
        "state": "accessible",
        "household_id": household_id,
    }

    unbound = database_client.post(
        f"/v1/households/{household_id}/devices/{device_code}/unbind",
        headers=admin_headers,
    )
    assert unbound.status_code == 200
    unbound_entry = database_client.get(
        f"/v1/devices/{device_code}/entry",
        headers=outsider_headers,
    )
    assert unbound_entry.status_code == 200
    assert unbound_entry.json() == {
        "state": "unbound",
        "household_id": None,
    }

    assert database_client.get(
        "/v1/devices/unknown-device/entry",
        headers=outsider_headers,
    ).status_code == 404
    assert database_client.get(
        f"/v1/devices/{device_code}/entry"
    ).status_code == 401


def test_admin_can_generate_and_read_cached_mini_program_code(
    database_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    login = database_client.post(
        "/v1/auth/dev-login",
        json={"nickname": "设备管理员"},
    ).json()
    household_id = login["current_household_id"]
    headers = {"Authorization": f"Bearer {login['access_token']}"}
    settings = get_settings()
    output = BytesIO()
    Image.new("RGB", (280, 280), "white").save(output, format="PNG")
    expected_png = output.getvalue()

    async def fake_generate(device_code: str) -> bytes:
        assert device_code == settings.device_code
        return expected_png

    monkeypatch.setattr(
        "app.api.devices.generate_mini_program_code",
        fake_generate,
    )
    refreshed = database_client.post(
        f"/v1/households/{household_id}/devices/"
        f"{settings.device_code}/mini-program-code",
        headers=headers,
    )
    assert refreshed.status_code == 200
    assert refreshed.json()["mini_program_code_ready"] is True

    image = database_client.get(
        f"/v1/households/{household_id}/devices/"
        f"{settings.device_code}/mini-program-code",
        headers=headers,
    )
    assert image.status_code == 200
    assert image.headers["content-type"] == "image/png"
    assert image.content == expected_png


def test_database_device_secret_authenticates_frame_request(
    database_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_client.post(
        "/v1/auth/dev-login",
        json={"nickname": "设备管理员"},
    )
    settings = get_settings()
    monkeypatch.setenv("DATABASE_INVENTORY_ENABLED", "true")
    get_settings.cache_clear()
    path = f"/v1/devices/{settings.device_code}/frame"
    timestamp = str(int(time.time()))
    nonce = "database-device-nonce-001"
    signing_text = "\n".join(("GET", path, timestamp, nonce, ""))
    signature = hmac.new(
        settings.device_secret.encode(),
        signing_text.encode(),
        hashlib.sha256,
    ).hexdigest()

    response = database_client.get(
        path,
        headers={
            "X-Device-Timestamp": timestamp,
            "X-Device-Nonce": nonce,
            "X-Device-Signature": signature,
        },
    )

    assert response.status_code == 200
    assert len(response.content) == 96000


def test_unbound_device_frame_response_has_explicit_state(
    database_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    login = database_client.post(
        "/v1/auth/dev-login",
        json={"nickname": "解绑状态测试管理员"},
    ).json()
    settings = get_settings()
    monkeypatch.setenv("DATABASE_INVENTORY_ENABLED", "true")
    get_settings.cache_clear()
    household_id = login["current_household_id"]
    auth_headers = {
        "Authorization": f"Bearer {login['access_token']}",
    }

    unbound = database_client.post(
        f"/v1/households/{household_id}/devices/"
        f"{settings.device_code}/unbind",
        headers=auth_headers,
    )
    response = database_client.get(
        f"/v1/devices/{settings.device_code}/frame",
        headers=_signed_frame_headers(
            device_code=settings.device_code,
            device_secret=settings.device_secret,
            nonce="unbound-device-state-0001",
        ),
    )

    assert unbound.status_code == 200
    assert response.status_code == 409
    assert response.headers["x-device-state"] == "unbound"
    assert response.text == "device is not bound to a household"
