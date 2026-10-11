import asyncio
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

import httpx
import pytest

from app.db.models import Household, MarketAsset, MarketAssetType
from app.services.device_frame import FRAME_SIZE, encode_f53, load_market_frame
from app.services.display_renderer import (
    native_image_to_portrait,
    render_market_image,
)
from app.services.market_data import (
    MARKET_CATALOG,
    LiveMarketDataProvider,
    MarketQuote,
    MarketSearchResult,
    MarketSnapshot,
    MarketSnapshotItem,
    _longbridge_class_name,
    _longbridge_symbol,
    load_market_snapshot,
    market_refresh_due,
)

DISPLAYED_AT = datetime(2026, 9, 9, 15, 30, tzinfo=timezone.utc)


def _snapshot() -> MarketSnapshot:
    return MarketSnapshot(
        items=(
            MarketSnapshotItem(
                asset_id="btc",
                asset_type=MarketAssetType.CRYPTO,
                symbol="BTC",
                name="比特币",
                currency="USD",
                price=Decimal("112480.50"),
                change_percent=Decimal("1.82"),
                status="24H",
                quoted_at=DISPLAYED_AT,
                stale=False,
            ),
            MarketSnapshotItem(
                asset_id="tencent",
                asset_type=MarketAssetType.HK_STOCK,
                symbol="00700.HK",
                name="腾讯控股",
                currency="HKD",
                price=Decimal("612.00"),
                change_percent=Decimal("-0.47"),
                status="收盘",
                quoted_at=DISPLAYED_AT,
                stale=False,
            ),
        ),
        updated_at=DISPLAYED_AT,
        refresh_minutes=30,
        night_pause=True,
    )


def test_market_catalog_only_exposes_supported_first_release_assets() -> None:
    assert {item.symbol for item in MARKET_CATALOG} == {
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
    assert {item.asset_type for item in MARKET_CATALOG} == {
        MarketAssetType.CRYPTO,
        MarketAssetType.US_STOCK,
        MarketAssetType.CN_STOCK,
        MarketAssetType.HK_STOCK,
        MarketAssetType.INDEX,
    }


def test_market_render_is_native_four_color_frame() -> None:
    image = render_market_image(_snapshot())
    assert image.size == (800, 480)
    assert native_image_to_portrait(image).size == (480, 800)
    assert set(image.get_flattened_data()) <= {
        (17, 17, 17),
        (255, 255, 255),
        (224, 160, 0),
        (196, 43, 37),
    }
    assert len(encode_f53(image)) == FRAME_SIZE
    frame = load_market_frame(_snapshot())
    assert frame.version.startswith("market-v1-")
    assert len(frame.data) == FRAME_SIZE


def test_market_refresh_interval_and_night_pause() -> None:
    daytime = datetime(2026, 9, 9, 2, 0, tzinfo=timezone.utc)
    household = Household(
        id="household-market",
        name="行情家庭",
        admin_user_id="user-market",
        market_refresh_minutes=30,
        market_night_pause=True,
    )
    asset = MarketAsset(
        id="asset-market",
        household_id=household.id,
        asset_type=MarketAssetType.CRYPTO,
        symbol="BTC",
        name="比特币",
        currency="USD",
        provider_symbol="bitcoin",
        sequence=0,
        last_fetched_at=daytime,
    )
    assert market_refresh_due(
        household,
        [asset],
        now=daytime + timedelta(minutes=29),
    ) is False
    assert market_refresh_due(
        household,
        [asset],
        now=daytime + timedelta(minutes=30),
    ) is True

    # 16:30 UTC is 00:30 in Shanghai, inside the configured night pause.
    assert market_refresh_due(
        household,
        [asset],
        now=datetime(2026, 9, 9, 16, 30, tzinfo=timezone.utc),
    ) is False

    asset.last_fetched_at = None
    assert market_refresh_due(
        household,
        [asset],
        now=datetime(2026, 9, 9, 16, 30, tzinfo=timezone.utc),
    ) is True


def test_forced_market_refresh_bypasses_night_pause(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    night = datetime(2026, 9, 9, 16, 30, tzinfo=timezone.utc)
    household = Household(
        id="household-market-force",
        name="行情家庭",
        admin_user_id="user-market",
        market_refresh_minutes=30,
        market_night_pause=True,
    )
    asset = MarketAsset(
        id="asset-market-force",
        household_id=household.id,
        asset_type=MarketAssetType.CRYPTO,
        symbol="BTC",
        name="比特币",
        currency="USD",
        provider_symbol="bitcoin",
        sequence=0,
        last_fetched_at=night - timedelta(days=3),
    )

    class Provider:
        calls = 0

        async def fetch_quotes(self, assets, *, now):
            self.calls += 1
            return {}

    class Session:
        flushed = False

        async def flush(self):
            self.flushed = True

    provider = Provider()
    session = Session()
    monkeypatch.setattr(
        "app.services.market_data.load_market_assets",
        lambda *_args, **_kwargs: asyncio.sleep(0, result=[asset]),
    )
    monkeypatch.setattr(
        "app.services.market_data.get_market_data_provider",
        lambda: provider,
    )

    snapshot = asyncio.run(
        load_market_snapshot(
            session,
            household,
            now=night,
            force_refresh=True,
        )
    )

    assert provider.calls == 1
    assert session.flushed is True
    assert asset.last_fetched_at == night
    assert snapshot.updated_at == night


def test_live_provider_parses_coingecko_and_twelve_data_contracts() -> None:
    provider = LiveMarketDataProvider.__new__(LiveMarketDataProvider)
    provider.coingecko_api_key = "demo-key"
    provider.coingecko_api_key_type = "demo"
    provider.coingecko_api_base_url = "https://api.coingecko.test/api/v3"
    provider.twelve_data_api_key = "stock-key"
    provider.twelve_data_api_base_url = "https://api.twelvedata.test"
    provider.security_provider = "twelve_data"
    provider.timeout = 1.0
    bitcoin = MarketAsset(
        id="asset-btc",
        household_id="household-market",
        asset_type=MarketAssetType.CRYPTO,
        symbol="BTC",
        name="比特币",
        currency="USD",
        provider_symbol="bitcoin",
        sequence=0,
    )
    tencent = MarketAsset(
        id="asset-tencent",
        household_id="household-market",
        asset_type=MarketAssetType.HK_STOCK,
        symbol="00700.HK",
        name="腾讯控股",
        currency="HKD",
        provider_symbol="0700",
        provider_mic_code="XHKG",
        sequence=1,
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "api.coingecko.test":
            assert request.headers["x-cg-demo-api-key"] == "demo-key"
            return httpx.Response(
                200,
                json={
                    "bitcoin": {
                        "usd": 112480.5,
                        "usd_24h_change": 1.82,
                        "last_updated_at": 1788940800,
                    }
                },
            )
        assert request.url.params["symbol"] == "0700"
        assert request.url.params["mic_code"] == "XHKG"
        assert request.url.params["apikey"] == "stock-key"
        return httpx.Response(
            200,
            json={
                "close": "612.00",
                "percent_change": "1.15",
                "currency": "HKD",
                "datetime": "2026-09-09 16:00:00",
                "timestamp": 1788940800,
                "is_market_open": False,
            },
        )

    async def exercise() -> None:
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler)
        ) as client:
            crypto = await provider._fetch_crypto(client, [bitcoin], DISPLAYED_AT)
            stocks = await provider._fetch_securities(client, [tencent], DISPLAYED_AT)
        assert crypto[bitcoin.id].price == Decimal("112480.5")
        assert crypto[bitcoin.id].change_percent == Decimal("1.82")
        assert crypto[bitcoin.id].status == "24H"
        assert stocks[tencent.id].price == Decimal("612.00")
        assert stocks[tencent.id].change_percent == Decimal("1.15")
        assert stocks[tencent.id].status == "收盘"

    asyncio.run(exercise())


def test_live_provider_falls_back_to_twelve_data_for_crypto(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = LiveMarketDataProvider.__new__(LiveMarketDataProvider)
    provider.coingecko_api_key = "demo-key"
    provider.coingecko_api_key_type = "demo"
    provider.coingecko_api_base_url = "https://blocked.coingecko.test/api/v3"
    provider.twelve_data_api_key = "stock-key"
    provider.twelve_data_api_base_url = "https://api.twelvedata.test"
    provider.security_provider = "twelve_data"
    provider.timeout = 1.0
    bitcoin = MarketAsset(
        id="asset-btc-fallback",
        household_id="household-market",
        asset_type=MarketAssetType.CRYPTO,
        symbol="BTC",
        name="比特币",
        currency="USD",
        provider_symbol="bitcoin",
        sequence=0,
    )

    expected = MarketQuote(
        price=Decimal("112480.50"),
        change_percent=Decimal("1.82"),
        status="24H",
        quoted_at=DISPLAYED_AT,
    )

    async def blocked_crypto(client, assets, now):
        del client, assets, now
        raise httpx.ConnectError("blocked")

    async def empty_securities(client, assets, now):
        del client, assets, now
        return {}

    async def twelve_fallback(client, assets, now):
        del client, now
        assert assets == [bitcoin]
        return {bitcoin.id: expected}

    monkeypatch.setattr(provider, "_fetch_crypto", blocked_crypto)
    monkeypatch.setattr(provider, "_fetch_securities", empty_securities)
    monkeypatch.setattr(provider, "_fetch_twelve_crypto", twelve_fallback)

    quotes = asyncio.run(
        provider.fetch_quotes(
            [bitcoin],
            now=DISPLAYED_AT,
        )
    )
    assert quotes == {bitcoin.id: expected}


def test_longbridge_provider_parses_multiple_markets_and_extended_session() -> None:
    provider = LiveMarketDataProvider.__new__(LiveMarketDataProvider)
    provider.longbridge_app_key = "app-key"
    provider.longbridge_app_secret = "app-secret"
    provider.longbridge_access_token = "paper-token"
    provider.timeout = 1.0
    aapl = MarketAsset(
        id="asset-aapl",
        household_id="household-market",
        asset_type=MarketAssetType.US_STOCK,
        symbol="AAPL",
        name="苹果",
        currency="USD",
        provider_symbol="AAPL",
        sequence=0,
    )
    tencent = MarketAsset(
        id="asset-tencent-longbridge",
        household_id="household-market",
        asset_type=MarketAssetType.HK_STOCK,
        symbol="00700.HK",
        name="腾讯控股",
        currency="HKD",
        provider_symbol="0700",
        provider_mic_code="XHKG",
        sequence=1,
    )

    class Normal:
        pass

    class FakeQuoteContext:
        async def quote(self, symbols):
            assert symbols == ["AAPL.US", "700.HK"]
            return [
                SimpleNamespace(
                    symbol="AAPL.US",
                    last_done=Decimal("232.00"),
                    prev_close=Decimal("230.00"),
                    timestamp=DISPLAYED_AT,
                    trade_status=Normal,
                    pre_market_quote=None,
                    post_market_quote=SimpleNamespace(
                        last_done=Decimal("233.00"),
                        timestamp=DISPLAYED_AT + timedelta(minutes=30),
                    ),
                    overnight_quote=None,
                ),
                SimpleNamespace(
                    symbol="700.HK",
                    last_done=Decimal("612.00"),
                    prev_close=Decimal("610.00"),
                    timestamp=DISPLAYED_AT,
                    trade_status=Normal,
                    pre_market_quote=None,
                    post_market_quote=None,
                    overnight_quote=None,
                ),
            ]

    provider._create_longbridge_context = FakeQuoteContext
    quotes = asyncio.run(
        provider._fetch_longbridge_securities([aapl, tencent], DISPLAYED_AT)
    )
    assert quotes[aapl.id].price == Decimal("233.00")
    assert quotes[aapl.id].status == "盘后"
    assert quotes[aapl.id].change_percent == pytest.approx(
        Decimal("1.304347826086956521739130435")
    )
    assert quotes[tencent.id].price == Decimal("612.00")
    assert quotes[tencent.id].status == "实时"


def test_longbridge_provider_isolates_a_failed_symbol() -> None:
    provider = LiveMarketDataProvider.__new__(LiveMarketDataProvider)
    provider.longbridge_app_key = "app-key"
    provider.longbridge_app_secret = "app-secret"
    provider.longbridge_access_token = "paper-token"
    provider.timeout = 1.0
    aapl = MarketAsset(
        id="asset-aapl-failed",
        household_id="household-market",
        asset_type=MarketAssetType.US_STOCK,
        symbol="AAPL",
        name="苹果",
        currency="USD",
        provider_symbol="AAPL",
        sequence=0,
    )
    tencent = MarketAsset(
        id="asset-tencent-ok",
        household_id="household-market",
        asset_type=MarketAssetType.HK_STOCK,
        symbol="00700.HK",
        name="腾讯控股",
        currency="HKD",
        provider_symbol="0700",
        provider_mic_code="XHKG",
        sequence=1,
    )

    class Normal:
        pass

    class FakeQuoteContext:
        async def quote(self, symbols):
            if len(symbols) > 1 or symbols == ["AAPL.US"]:
                raise RuntimeError("permission denied for one symbol")
            return [
                SimpleNamespace(
                    symbol="700.HK",
                    last_done=Decimal("612.00"),
                    prev_close=Decimal("610.00"),
                    timestamp=DISPLAYED_AT,
                    trade_status=Normal,
                    pre_market_quote=None,
                    post_market_quote=None,
                    overnight_quote=None,
                )
            ]

    provider._create_longbridge_context = FakeQuoteContext
    quotes = asyncio.run(
        provider._fetch_longbridge_securities([aapl, tencent], DISPLAYED_AT)
    )
    assert aapl.id not in quotes
    assert quotes[tencent.id].price == Decimal("612.00")


def test_longbridge_search_filters_non_equity_results() -> None:
    provider = LiveMarketDataProvider.__new__(LiveMarketDataProvider)
    provider.timeout = 1.0
    provider.security_provider = "longbridge"
    provider._longbridge_security_cache = {}

    class HKEquity:
        pass

    class HKWarrant:
        pass

    class FakeQuoteContext:
        async def security_list(self, market):
            return [
                SimpleNamespace(
                    symbol="700.HK",
                    name_cn="腾讯控股",
                    name_hk="騰訊控股",
                    name_en="Tencent Holdings",
                ),
                SimpleNamespace(
                    symbol="27423.HK",
                    name_cn="腾讯华泰认购证",
                    name_hk="騰訊華泰認購證",
                    name_en="Tencent warrant",
                ),
            ]

        async def static_info(self, symbols):
            values = {
                "700.HK": SimpleNamespace(
                    symbol="700.HK",
                    name_cn="腾讯控股",
                    name_hk="騰訊控股",
                    name_en="Tencent Holdings",
                    currency="HKD",
                    exchange="SEHK",
                    board=HKEquity,
                ),
                "27423.HK": SimpleNamespace(
                    symbol="27423.HK",
                    name_cn="腾讯华泰认购证",
                    name_hk="騰訊華泰認購證",
                    name_en="Tencent warrant",
                    currency="HKD",
                    exchange="SEHK",
                    board=HKWarrant,
                ),
            }
            return [values[symbol] for symbol in symbols]

    provider._create_longbridge_context = FakeQuoteContext
    results = asyncio.run(
        provider.search_assets(
            MarketAssetType.HK_STOCK,
            "腾讯",
        )
    )
    assert results == [
        MarketSearchResult(
            asset_type=MarketAssetType.HK_STOCK,
            symbol="00700.HK",
            name="腾讯控股",
            currency="HKD",
            provider_symbol="700.HK",
        )
    ]

    dynamic = MarketAsset(
        id="dynamic-tencent",
        household_id="household-market",
        asset_type=MarketAssetType.HK_STOCK,
        symbol="03690.HK",
        name="美团-W",
        currency="HKD",
        provider_symbol="3690.HK",
        sequence=0,
    )
    assert _longbridge_symbol(dynamic) == "3690.HK"


def test_longbridge_enum_name_supports_sdk_string_representation() -> None:
    class FakeSecurityBoard:
        def __str__(self) -> str:
            return "SecurityBoard.HKEquity"

    assert _longbridge_class_name(FakeSecurityBoard()) == "HKEquity"


def test_twelve_data_crypto_catalog_search_and_resolve() -> None:
    provider = LiveMarketDataProvider.__new__(LiveMarketDataProvider)

    async def crypto_catalog() -> tuple[tuple[str, str], ...]:
        return (
            ("BTC/USD", "Bitcoin"),
            ("SOL/USD", "Solana"),
            ("SOLA/USD", "Solana Ecosystem Token"),
        )

    provider._twelve_crypto_catalog = crypto_catalog
    results = asyncio.run(
        provider._search_twelve_crypto_assets("Solana", limit=2)
    )
    assert results == [
        MarketSearchResult(
            asset_type=MarketAssetType.CRYPTO,
            symbol="SOL",
            name="Solana",
            currency="USD",
            provider_symbol="SOL/USD",
        ),
        MarketSearchResult(
            asset_type=MarketAssetType.CRYPTO,
            symbol="SOLA",
            name="Solana Ecosystem Token",
            currency="USD",
            provider_symbol="SOLA/USD",
        ),
    ]
    resolved = asyncio.run(provider._resolve_twelve_crypto_asset("sol/usd"))
    assert resolved.symbol == "SOL"
    assert resolved.name == "Solana"
    assert resolved.provider_symbol == "SOL/USD"


def test_live_provider_uses_pro_coingecko_header() -> None:
    provider = LiveMarketDataProvider.__new__(LiveMarketDataProvider)
    provider.coingecko_api_key = "pro-key"
    provider.coingecko_api_key_type = "pro"
    provider.coingecko_api_base_url = "https://pro-api.coingecko.test/api/v3"
    bitcoin = MarketAsset(
        id="asset-btc-pro",
        household_id="household-market",
        asset_type=MarketAssetType.CRYPTO,
        symbol="BTC",
        name="比特币",
        currency="USD",
        provider_symbol="bitcoin",
        sequence=0,
    )

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["x-cg-pro-api-key"] == "pro-key"
        assert "x-cg-demo-api-key" not in request.headers
        return httpx.Response(200, json={"bitcoin": {"usd": 112480.5}})

    async def exercise() -> None:
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler)
        ) as client:
            quotes = await provider._fetch_crypto(client, [bitcoin], DISPLAYED_AT)
        assert quotes[bitcoin.id].price == Decimal("112480.5")

    asyncio.run(exercise())
