from __future__ import annotations

import asyncio
import re
import time
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from functools import lru_cache
from typing import Any, ClassVar, Protocol
from zoneinfo import ZoneInfo

import httpx
from longbridge.openapi import (
    AsyncQuoteContext,
    Config,
    Market,
    OpenApiException,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import utc_now
from app.db.models import Household, MarketAsset, MarketAssetType
from app.settings import get_settings

MAX_MARKET_ASSETS = 6
MARKET_REFRESH_MINUTES = (15, 30, 60)
MARKET_TIMEZONE = ZoneInfo("Asia/Shanghai")
MARKET_SEARCH_LIMIT = 20
LONG_BRIDGE_SECURITY_CACHE_SECONDS = 6 * 60 * 60
SEARCHABLE_MARKET_ASSET_TYPES = frozenset(
    {
        MarketAssetType.CRYPTO,
        MarketAssetType.US_STOCK,
        MarketAssetType.CN_STOCK,
        MarketAssetType.HK_STOCK,
    }
)


@dataclass(frozen=True, slots=True)
class MarketCatalogItem:
    asset_type: MarketAssetType
    symbol: str
    name: str
    currency: str
    provider_symbol: str
    provider_mic_code: str | None = None
    longbridge_symbol: str | None = None


@dataclass(frozen=True, slots=True)
class MarketSearchResult:
    asset_type: MarketAssetType
    symbol: str
    name: str
    currency: str
    provider_symbol: str


class MarketSearchUnavailable(RuntimeError):
    """Raised when a configured upstream cannot serve asset search."""


MARKET_CATALOG = (
    MarketCatalogItem(MarketAssetType.CRYPTO, "BTC", "比特币", "USD", "bitcoin"),
    MarketCatalogItem(MarketAssetType.CRYPTO, "ETH", "以太坊", "USD", "ethereum"),
    MarketCatalogItem(
        MarketAssetType.US_STOCK,
        "AAPL",
        "苹果",
        "USD",
        "AAPL",
        longbridge_symbol="AAPL.US",
    ),
    MarketCatalogItem(
        MarketAssetType.US_STOCK,
        "MSFT",
        "微软",
        "USD",
        "MSFT",
        longbridge_symbol="MSFT.US",
    ),
    MarketCatalogItem(
        MarketAssetType.US_STOCK,
        "NVDA",
        "英伟达",
        "USD",
        "NVDA",
        longbridge_symbol="NVDA.US",
    ),
    MarketCatalogItem(
        MarketAssetType.US_STOCK,
        "TSLA",
        "特斯拉",
        "USD",
        "TSLA",
        longbridge_symbol="TSLA.US",
    ),
    MarketCatalogItem(
        MarketAssetType.CN_STOCK,
        "600519.SH",
        "贵州茅台",
        "CNY",
        "600519",
        "XSHG",
        "600519.SH",
    ),
    MarketCatalogItem(
        MarketAssetType.CN_STOCK,
        "300750.SZ",
        "宁德时代",
        "CNY",
        "300750",
        "XSHE",
        "300750.SZ",
    ),
    MarketCatalogItem(
        MarketAssetType.CN_STOCK,
        "601318.SH",
        "中国平安",
        "CNY",
        "601318",
        "XSHG",
        "601318.SH",
    ),
    MarketCatalogItem(
        MarketAssetType.HK_STOCK,
        "00700.HK",
        "腾讯控股",
        "HKD",
        "0700",
        "XHKG",
        "700.HK",
    ),
    MarketCatalogItem(
        MarketAssetType.HK_STOCK,
        "01810.HK",
        "小米集团-W",
        "HKD",
        "1810",
        "XHKG",
        "1810.HK",
    ),
    MarketCatalogItem(
        MarketAssetType.HK_STOCK,
        "00005.HK",
        "汇丰控股",
        "HKD",
        "0005",
        "XHKG",
        "5.HK",
    ),
    MarketCatalogItem(
        MarketAssetType.HK_STOCK,
        "09988.HK",
        "阿里巴巴-W",
        "HKD",
        "9988",
        "XHKG",
        "9988.HK",
    ),
    MarketCatalogItem(
        MarketAssetType.INDEX,
        "HSI",
        "恒生指数",
        "HKD",
        "HSI",
        longbridge_symbol="HSI.HK",
    ),
    MarketCatalogItem(
        MarketAssetType.INDEX,
        "IXIC",
        "纳斯达克指数",
        "USD",
        ".IXIC",
        longbridge_symbol=".IXIC.US",
    ),
)
MARKET_CATALOG_BY_KEY = {
    (item.asset_type, item.symbol): item for item in MARKET_CATALOG
}


@dataclass(frozen=True, slots=True)
class MarketQuote:
    price: Decimal
    change_percent: Decimal | None
    status: str
    quoted_at: datetime


@dataclass(frozen=True, slots=True)
class MarketSnapshotItem:
    asset_id: str
    asset_type: MarketAssetType
    symbol: str
    name: str
    currency: str
    price: Decimal | None
    change_percent: Decimal | None
    status: str
    quoted_at: datetime | None
    stale: bool


@dataclass(frozen=True, slots=True)
class MarketSnapshot:
    items: tuple[MarketSnapshotItem, ...]
    updated_at: datetime
    refresh_minutes: int
    night_pause: bool


class MarketDataProvider(Protocol):
    async def fetch_quotes(
        self,
        assets: Sequence[MarketAsset],
        *,
        now: datetime,
    ) -> dict[str, MarketQuote]: ...


def catalog_item(
    asset_type: MarketAssetType,
    symbol: str,
) -> MarketCatalogItem | None:
    return MARKET_CATALOG_BY_KEY.get((asset_type, symbol.strip().upper()))


def _aware_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _decimal(value: object) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


def _quoted_at(value: object, fallback: datetime) -> datetime:
    if isinstance(value, datetime):
        return _aware_utc(value) or fallback
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, timezone.utc)
    if isinstance(value, str) and value:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return _aware_utc(parsed) or fallback
        except ValueError:
            pass
    return fallback


def _longbridge_symbol(asset: MarketAsset) -> str | None:
    item = catalog_item(asset.asset_type, asset.symbol)
    if item is not None and item.longbridge_symbol:
        return item.longbridge_symbol
    if asset.asset_type in {
        MarketAssetType.US_STOCK,
        MarketAssetType.CN_STOCK,
        MarketAssetType.HK_STOCK,
    } and re.fullmatch(r"[A-Z0-9.-]{2,32}", asset.provider_symbol.upper()):
        return asset.provider_symbol.upper()
    if asset.asset_type == MarketAssetType.US_STOCK:
        return f"{asset.symbol}.US"
    return None


def _longbridge_class_name(value: object) -> str:
    explicit_name = getattr(value, "name", None)
    if explicit_name:
        return str(explicit_name)
    text = str(value)
    if "." in text and not text.startswith("<"):
        return text.rsplit(".", 1)[-1]
    return getattr(value, "__name__", "") or value.__class__.__name__


def _longbridge_market(asset_type: MarketAssetType) -> type[Market]:
    return {
        MarketAssetType.US_STOCK: Market.US,
        MarketAssetType.CN_STOCK: Market.CN,
        MarketAssetType.HK_STOCK: Market.HK,
    }[asset_type]


def _longbridge_board_allowed(
    asset_type: MarketAssetType,
    board: object,
) -> bool:
    allowed = {
        MarketAssetType.US_STOCK: {"USMain"},
        MarketAssetType.CN_STOCK: {
            "SHMainConnect",
            "SHMainNonConnect",
            "SHSTAR",
            "SZMainConnect",
            "SZMainNonConnect",
            "SZGEMConnect",
            "SZGEMNonConnect",
        },
        MarketAssetType.HK_STOCK: {"HKEquity", "HKPreIPO"},
    }
    return _longbridge_class_name(board) in allowed.get(asset_type, set())


def _display_symbol(asset_type: MarketAssetType, provider_symbol: str) -> str:
    code, _, market = provider_symbol.upper().rpartition(".")
    if asset_type == MarketAssetType.US_STOCK and market == "US":
        return code
    if asset_type == MarketAssetType.HK_STOCK and market == "HK":
        return f"{code.zfill(5) if code.isdigit() else code}.HK"
    return provider_symbol.upper()


def _preferred_security_name(value: object) -> str:
    for attribute in ("name_cn", "name_hk", "name_en"):
        name = str(getattr(value, attribute, "") or "").strip()
        if name:
            return name
    return str(getattr(value, "symbol", "")).strip()


def _normalized_search_text(value: str) -> str:
    return "".join(value.casefold().split())


def _security_search_rank(
    query: str,
    symbol: str,
    names: Sequence[str],
) -> tuple[int, int, str] | None:
    normalized_query = _normalized_search_text(query)
    fields = [
        _normalized_search_text(symbol),
        *(_normalized_search_text(name) for name in names if name),
    ]
    if not any(normalized_query in field for field in fields):
        return None
    if normalized_query in fields:
        priority = 0
    elif any(field.startswith(normalized_query) for field in fields):
        priority = 1
    elif any(normalized_query in field for field in fields):
        priority = 2
    else:
        return None
    shortest_name = min((len(value) for value in fields[1:]), default=99)
    return priority, shortest_name, symbol


def _longbridge_status(value: object) -> str:
    name = _longbridge_class_name(value)
    return {
        "Halted": "停牌",
        "Suspend": "停牌",
        "Delisted": "退市",
        "Fuse": "熔断",
        "PrepareList": "待上市",
        "ToBeOpened": "待开盘",
        "Expired": "已到期",
    }.get(name, "实时")


def _longbridge_quote(value: Any, now: datetime) -> MarketQuote | None:
    price = _decimal(getattr(value, "last_done", None))
    if price is None:
        return None
    quoted_at = _quoted_at(getattr(value, "timestamp", None), now)
    status = _longbridge_status(getattr(value, "trade_status", None))

    # Longbridge exposes US extended-session values separately. Prefer the
    # newest timestamp so a later pre/post/overnight quote is not hidden by
    # the regular-session close.
    for attribute, label in (
        ("pre_market_quote", "盘前"),
        ("post_market_quote", "盘后"),
        ("overnight_quote", "夜盘"),
    ):
        extended = getattr(value, attribute, None)
        if extended is None:
            continue
        extended_price = _decimal(getattr(extended, "last_done", None))
        if extended_price is None:
            continue
        extended_at = _quoted_at(getattr(extended, "timestamp", None), now)
        if extended_at > quoted_at:
            price = extended_price
            quoted_at = extended_at
            status = label

    previous_close = _decimal(getattr(value, "prev_close", None))
    change_percent = None
    if previous_close not in (None, Decimal("0")):
        change_percent = (price - previous_close) / previous_close * Decimal("100")
    return MarketQuote(
        price=price,
        change_percent=change_percent,
        status=status,
        quoted_at=quoted_at,
    )


def live_market_data_ready() -> bool:
    settings = get_settings()
    if settings.market_data_provider != "live":
        return False
    crypto_ready = bool(
        settings.coingecko_api_key.get_secret_value()
        or settings.twelve_data_api_key.get_secret_value()
    )
    if settings.market_security_provider == "longbridge":
        securities_ready = all(
            (
                settings.longbridge_app_key.get_secret_value(),
                settings.longbridge_app_secret.get_secret_value(),
                settings.longbridge_access_token.get_secret_value(),
            )
        )
    else:
        securities_ready = bool(settings.twelve_data_api_key.get_secret_value())
    return crypto_ready and securities_ready


def market_data_source_label() -> str:
    settings = get_settings()
    if settings.market_data_provider == "mock":
        return "演示行情"
    security_source = (
        "Longbridge"
        if settings.market_security_provider == "longbridge"
        else "Twelve Data"
    )
    return f"CoinGecko / {security_source}"


class MockMarketDataProvider:
    _quotes: ClassVar[dict[str, tuple[str, str]]] = {
        "BTC": ("112480.50", "1.82"),
        "ETH": ("4398.20", "-0.64"),
        "AAPL": ("234.16", "0.92"),
        "MSFT": ("512.44", "0.31"),
        "NVDA": ("182.76", "-0.25"),
        "TSLA": ("346.82", "1.08"),
        "600519.SH": ("1475.20", "-0.38"),
        "300750.SZ": ("318.66", "0.52"),
        "601318.SH": ("61.08", "-0.19"),
        "00700.HK": ("612.00", "1.15"),
        "01810.HK": ("58.40", "-0.51"),
        "00005.HK": ("107.30", "0.28"),
        "09988.HK": ("152.70", "0.73"),
        "HSI": ("25180.32", "-0.47"),
        "SPX": ("6588.14", "0.41"),
        "IXIC": ("22136.02", "0.56"),
    }

    async def fetch_quotes(
        self,
        assets: Sequence[MarketAsset],
        *,
        now: datetime,
    ) -> dict[str, MarketQuote]:
        result: dict[str, MarketQuote] = {}
        for asset in assets:
            price, change = self._quotes.get(asset.symbol, ("100.00", "0.00"))
            status = "24H" if asset.asset_type == MarketAssetType.CRYPTO else "快照"
            result[asset.id] = MarketQuote(
                price=Decimal(price),
                change_percent=Decimal(change),
                status=status,
                quoted_at=now,
            )
        return result


class LiveMarketDataProvider:
    def __init__(self) -> None:
        settings = get_settings()
        self.twelve_data_api_key = settings.twelve_data_api_key.get_secret_value()
        self.twelve_data_api_base_url = settings.twelve_data_api_base_url.rstrip("/")
        self.coingecko_api_key = settings.coingecko_api_key.get_secret_value()
        self.coingecko_api_key_type = settings.coingecko_api_key_type
        self.coingecko_api_base_url = settings.coingecko_api_base_url.rstrip("/")
        self.security_provider = settings.market_security_provider
        self.longbridge_app_key = settings.longbridge_app_key.get_secret_value()
        self.longbridge_app_secret = settings.longbridge_app_secret.get_secret_value()
        self.longbridge_access_token = (
            settings.longbridge_access_token.get_secret_value()
        )
        self.longbridge_http_url = settings.longbridge_http_url.rstrip("/")
        self.longbridge_quote_ws_url = settings.longbridge_quote_ws_url
        self.longbridge_enable_overnight = settings.longbridge_enable_overnight
        self.longbridge_paper_trading = settings.longbridge_paper_trading
        self.timeout = settings.market_data_timeout_seconds
        self._longbridge_security_cache: dict[
            MarketAssetType,
            tuple[float, tuple[tuple[str, str, str, str], ...]],
        ] = {}
        self._twelve_crypto_cache: tuple[
            float,
            tuple[tuple[str, str], ...],
        ] | None = None

    def _coingecko_headers(self) -> dict[str, str]:
        headers = {"accept": "application/json"}
        if self.coingecko_api_key:
            key_header = (
                "x-cg-pro-api-key"
                if self.coingecko_api_key_type == "pro"
                else "x-cg-demo-api-key"
            )
            headers[key_header] = self.coingecko_api_key
        return headers

    async def fetch_quotes(
        self,
        assets: Sequence[MarketAsset],
        *,
        now: datetime,
    ) -> dict[str, MarketQuote]:
        crypto = [
            asset for asset in assets if asset.asset_type == MarketAssetType.CRYPTO
        ]
        securities = [
            asset for asset in assets if asset.asset_type != MarketAssetType.CRYPTO
        ]
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            security_request = (
                self._fetch_longbridge_securities(securities, now)
                if self.security_provider == "longbridge"
                else self._fetch_securities(client, securities, now)
            )
            crypto_result, security_results = await asyncio.gather(
                self._fetch_crypto(client, crypto, now),
                security_request,
                return_exceptions=True,
            )
            resolved_crypto = (
                crypto_result if isinstance(crypto_result, dict) else {}
            )
            unresolved_crypto = [
                asset for asset in crypto if asset.id not in resolved_crypto
            ]
            if unresolved_crypto:
                fallback = await self._fetch_twelve_crypto(
                    client,
                    unresolved_crypto,
                    now,
                )
                resolved_crypto.update(fallback)
            resolved_securities = (
                security_results if isinstance(security_results, dict) else {}
            )
        return {**resolved_crypto, **resolved_securities}

    def _create_longbridge_context(self) -> AsyncQuoteContext:
        config = Config.from_apikey(
            self.longbridge_app_key,
            self.longbridge_app_secret,
            self.longbridge_access_token,
            http_url=self.longbridge_http_url or None,
            quote_ws_url=self.longbridge_quote_ws_url or None,
            enable_overnight=self.longbridge_enable_overnight,
            enable_print_quote_packages=False,
            enable_papertrading=self.longbridge_paper_trading,
        )
        return AsyncQuoteContext.create(config)

    async def _fetch_longbridge_securities(
        self,
        assets: Sequence[MarketAsset],
        now: datetime,
    ) -> dict[str, MarketQuote]:
        if not assets or not all(
            (
                self.longbridge_app_key,
                self.longbridge_app_secret,
                self.longbridge_access_token,
            )
        ):
            return {}
        context = self._create_longbridge_context()
        assets_by_symbol = {
            symbol: asset
            for asset in assets
            if (symbol := _longbridge_symbol(asset)) is not None
        }
        if not assets_by_symbol:
            return {}

        quotes: list[Any] = []
        try:
            quotes = await asyncio.wait_for(
                context.quote(list(assets_by_symbol)),
                timeout=self.timeout,
            )
        except (TimeoutError, OpenApiException, RuntimeError):
            # If a mixed-market batch fails, retry each symbol so one missing
            # permission or malformed symbol does not blank every quote.
            for symbol in assets_by_symbol:
                try:
                    response = await asyncio.wait_for(
                        context.quote([symbol]),
                        timeout=self.timeout,
                    )
                except (TimeoutError, OpenApiException, RuntimeError):
                    continue
                quotes.extend(response)

        result: dict[str, MarketQuote] = {}
        for value in quotes:
            asset = assets_by_symbol.get(str(getattr(value, "symbol", "")))
            if asset is None:
                continue
            quote = _longbridge_quote(value, now)
            if quote is not None:
                result[asset.id] = quote
        return result

    async def search_assets(
        self,
        asset_type: MarketAssetType,
        query: str,
        *,
        limit: int = MARKET_SEARCH_LIMIT,
    ) -> list[MarketSearchResult]:
        if asset_type not in SEARCHABLE_MARKET_ASSET_TYPES:
            raise ValueError("asset type is not searchable")
        if asset_type == MarketAssetType.CRYPTO:
            return await self._search_crypto_assets(query, limit=limit)
        if self.security_provider != "longbridge":
            raise MarketSearchUnavailable(
                "security search requires the Longbridge provider"
            )
        return await self._search_longbridge_assets(
            asset_type,
            query,
            limit=limit,
        )

    async def resolve_asset(
        self,
        asset_type: MarketAssetType,
        provider_symbol: str,
    ) -> MarketCatalogItem:
        if asset_type not in SEARCHABLE_MARKET_ASSET_TYPES:
            raise ValueError("asset type is not searchable")
        if asset_type == MarketAssetType.CRYPTO:
            return await self._resolve_crypto_asset(provider_symbol)
        if self.security_provider != "longbridge":
            raise MarketSearchUnavailable(
                "security search requires the Longbridge provider"
            )
        return await self._resolve_longbridge_asset(asset_type, provider_symbol)

    async def _search_crypto_assets(
        self,
        query: str,
        *,
        limit: int,
    ) -> list[MarketSearchResult]:
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(
                    f"{self.coingecko_api_base_url}/search",
                    params={"query": query},
                    headers=self._coingecko_headers(),
                )
                response.raise_for_status()
            payload = response.json()
            results: list[MarketSearchResult] = []
            seen_symbols: set[str] = set()
            for value in payload.get("coins", []):
                provider_symbol = str(value.get("id", "")).strip()
                symbol = str(value.get("symbol", "")).strip().upper()
                name = str(value.get("name", "")).strip()
                if (
                    not provider_symbol
                    or not symbol
                    or not name
                    or symbol in seen_symbols
                ):
                    continue
                seen_symbols.add(symbol)
                results.append(
                    MarketSearchResult(
                        asset_type=MarketAssetType.CRYPTO,
                        symbol=symbol[:32],
                        name=name[:80],
                        currency="USD",
                        provider_symbol=provider_symbol[:64],
                    )
                )
                if len(results) >= limit:
                    break
            if results:
                return results
        except (httpx.HTTPError, ValueError, TypeError):
            pass
        return await self._search_twelve_crypto_assets(query, limit=limit)

    async def _twelve_crypto_catalog(self) -> tuple[tuple[str, str], ...]:
        cached = self._twelve_crypto_cache
        current = time.monotonic()
        if cached is not None and current - cached[0] < LONG_BRIDGE_SECURITY_CACHE_SECONDS:
            return cached[1]
        if not self.twelve_data_api_key:
            raise MarketSearchUnavailable(
                "Twelve Data is not configured for cryptocurrency search"
            )
        async with httpx.AsyncClient(timeout=max(self.timeout, 20)) as client:
            response = await client.get(
                f"{self.twelve_data_api_base_url}/cryptocurrencies",
                params={
                    "apikey": self.twelve_data_api_key,
                    "currency_quote": "USD",
                    "outputsize": 5000,
                    "page": 1,
                },
            )
            response.raise_for_status()
        payload = response.json()
        if payload.get("status") != "ok":
            raise MarketSearchUnavailable(
                str(payload.get("message") or "Twelve Data crypto catalog failed")
            )
        catalog: list[tuple[str, str]] = []
        seen_pairs: set[str] = set()
        for value in payload.get("data", []):
            pair = str(value.get("symbol", "")).strip()
            name = str(value.get("currency_base", "")).strip()
            if (
                not pair.upper().endswith("/USD")
                or not name
                or pair.casefold() in seen_pairs
            ):
                continue
            seen_pairs.add(pair.casefold())
            catalog.append((pair, name))
        result = tuple(catalog)
        self._twelve_crypto_cache = (current, result)
        return result

    async def _search_twelve_crypto_assets(
        self,
        query: str,
        *,
        limit: int,
    ) -> list[MarketSearchResult]:
        catalog = await self._twelve_crypto_catalog()
        ranked: list[tuple[tuple[int, int, str], str, str]] = []
        for pair, name in catalog:
            symbol = pair.rsplit("/", 1)[0].upper()
            rank = _security_search_rank(query, symbol, (name, pair))
            if rank is not None:
                ranked.append((rank, pair, name))
        ranked.sort(key=lambda value: value[0])
        return [
            MarketSearchResult(
                asset_type=MarketAssetType.CRYPTO,
                symbol=pair.rsplit("/", 1)[0].upper()[:32],
                name=name[:80],
                currency="USD",
                provider_symbol=pair[:64],
            )
            for _, pair, name in ranked[:limit]
        ]

    async def _longbridge_security_list(
        self,
        asset_type: MarketAssetType,
    ) -> tuple[tuple[str, str, str, str], ...]:
        cached = self._longbridge_security_cache.get(asset_type)
        current = time.monotonic()
        if cached is not None and current - cached[0] < LONG_BRIDGE_SECURITY_CACHE_SECONDS:
            return cached[1]
        context = self._create_longbridge_context()
        values = await asyncio.wait_for(
            context.security_list(_longbridge_market(asset_type)),
            timeout=max(self.timeout, 30),
        )
        securities = tuple(
            (
                str(value.symbol),
                str(value.name_cn or ""),
                str(value.name_hk or ""),
                str(value.name_en or ""),
            )
            for value in values
        )
        self._longbridge_security_cache[asset_type] = (current, securities)
        return securities

    async def _search_longbridge_assets(
        self,
        asset_type: MarketAssetType,
        query: str,
        *,
        limit: int,
    ) -> list[MarketSearchResult]:
        securities = await self._longbridge_security_list(asset_type)
        ranked: list[tuple[tuple[int, int, str], str]] = []
        for symbol, name_cn, name_hk, name_en in securities:
            rank = _security_search_rank(
                query,
                symbol,
                (name_cn, name_hk, name_en),
            )
            if rank is not None:
                ranked.append((rank, symbol))
        ranked.sort(key=lambda value: value[0])
        candidate_symbols = [symbol for _, symbol in ranked[: max(limit * 5, 50)]]
        if not candidate_symbols:
            return []
        context = self._create_longbridge_context()
        static_values = await asyncio.wait_for(
            context.static_info(candidate_symbols),
            timeout=self.timeout,
        )
        info_by_symbol = {str(value.symbol): value for value in static_values}
        results: list[MarketSearchResult] = []
        for symbol in candidate_symbols:
            value = info_by_symbol.get(symbol)
            if value is None or not _longbridge_board_allowed(asset_type, value.board):
                continue
            results.append(
                MarketSearchResult(
                    asset_type=asset_type,
                    symbol=_display_symbol(asset_type, symbol),
                    name=_preferred_security_name(value)[:80],
                    currency=str(value.currency)[:8],
                    provider_symbol=symbol,
                )
            )
            if len(results) >= limit:
                break
        return results

    async def _resolve_crypto_asset(
        self,
        provider_symbol: str,
    ) -> MarketCatalogItem:
        if "/" in provider_symbol:
            return await self._resolve_twelve_crypto_asset(provider_symbol)
        if not re.fullmatch(r"[A-Za-z0-9._-]{1,64}", provider_symbol):
            raise ValueError("invalid cryptocurrency identifier")
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.get(
                f"{self.coingecko_api_base_url}/coins/{provider_symbol}",
                params={
                    "localization": "false",
                    "tickers": "false",
                    "market_data": "false",
                    "community_data": "false",
                    "developer_data": "false",
                    "sparkline": "false",
                },
                headers=self._coingecko_headers(),
            )
            if response.status_code == 404:
                raise ValueError("cryptocurrency was not found")
            response.raise_for_status()
        value = response.json()
        symbol = str(value.get("symbol", "")).strip().upper()
        name = str(value.get("name", "")).strip()
        if not symbol or not name:
            raise ValueError("cryptocurrency metadata is incomplete")
        return MarketCatalogItem(
            asset_type=MarketAssetType.CRYPTO,
            symbol=symbol[:32],
            name=name[:80],
            currency="USD",
            provider_symbol=provider_symbol,
        )

    async def _resolve_twelve_crypto_asset(
        self,
        provider_symbol: str,
    ) -> MarketCatalogItem:
        normalized_pair = provider_symbol.strip().upper()
        if not re.fullmatch(r"[A-Z0-9._-]{1,32}/USD", normalized_pair):
            raise ValueError("invalid Twelve Data cryptocurrency pair")
        catalog = await self._twelve_crypto_catalog()
        for pair, name in catalog:
            if pair.upper() != normalized_pair:
                continue
            return MarketCatalogItem(
                asset_type=MarketAssetType.CRYPTO,
                symbol=normalized_pair.rsplit("/", 1)[0],
                name=name[:80],
                currency="USD",
                provider_symbol=pair[:64],
            )
        raise ValueError("cryptocurrency was not found")

    async def _resolve_longbridge_asset(
        self,
        asset_type: MarketAssetType,
        provider_symbol: str,
    ) -> MarketCatalogItem:
        normalized_symbol = provider_symbol.strip().upper()
        expected = {
            MarketAssetType.US_STOCK: r"[A-Z0-9.-]+\.US",
            MarketAssetType.CN_STOCK: r"[0-9]{6}\.(SH|SZ)",
            MarketAssetType.HK_STOCK: r"[A-Z0-9.-]+\.HK",
        }[asset_type]
        if not re.fullmatch(expected, normalized_symbol):
            raise ValueError("security symbol does not match the selected market")
        context = self._create_longbridge_context()
        values = await asyncio.wait_for(
            context.static_info([normalized_symbol]),
            timeout=self.timeout,
        )
        if not values:
            raise ValueError("security was not found")
        value = values[0]
        if not _longbridge_board_allowed(asset_type, value.board):
            raise ValueError("the selected security is not a supported stock")
        return MarketCatalogItem(
            asset_type=asset_type,
            symbol=_display_symbol(asset_type, normalized_symbol),
            name=_preferred_security_name(value)[:80],
            currency=str(value.currency)[:8],
            provider_symbol=normalized_symbol,
            provider_mic_code=str(value.exchange)[:16] or None,
            longbridge_symbol=normalized_symbol,
        )

    async def _fetch_crypto(
        self,
        client: httpx.AsyncClient,
        assets: Sequence[MarketAsset],
        now: datetime,
    ) -> dict[str, MarketQuote]:
        if not assets:
            return {}
        headers = {"accept": "application/json"}
        if self.coingecko_api_key:
            key_header = (
                "x-cg-pro-api-key"
                if self.coingecko_api_key_type == "pro"
                else "x-cg-demo-api-key"
            )
            headers[key_header] = self.coingecko_api_key
        response = await client.get(
            f"{self.coingecko_api_base_url}/simple/price",
            params={
                "ids": ",".join(asset.provider_symbol for asset in assets),
                "vs_currencies": "usd",
                "include_24hr_change": "true",
                "include_last_updated_at": "true",
            },
            headers=headers,
        )
        response.raise_for_status()
        payload = response.json()
        result: dict[str, MarketQuote] = {}
        for asset in assets:
            value = payload.get(asset.provider_symbol, {})
            price = _decimal(value.get("usd"))
            if price is None:
                continue
            result[asset.id] = MarketQuote(
                price=price,
                change_percent=_decimal(value.get("usd_24h_change")),
                status="24H",
                quoted_at=_quoted_at(value.get("last_updated_at"), now),
            )
        return result

    async def _fetch_securities(
        self,
        client: httpx.AsyncClient,
        assets: Sequence[MarketAsset],
        now: datetime,
    ) -> dict[str, MarketQuote]:
        if not assets or not self.twelve_data_api_key:
            return {}

        async def fetch_one(asset: MarketAsset) -> tuple[str, MarketQuote | None]:
            params = {
                "symbol": asset.provider_symbol,
                "apikey": self.twelve_data_api_key,
            }
            if asset.provider_mic_code:
                params["mic_code"] = asset.provider_mic_code
            response = await client.get(
                f"{self.twelve_data_api_base_url}/quote",
                params=params,
            )
            response.raise_for_status()
            value = response.json()
            if value.get("status") == "error":
                return asset.id, None
            price = _decimal(value.get("close") or value.get("price"))
            if price is None:
                return asset.id, None
            is_open = value.get("is_market_open")
            status = "盘中" if is_open is True else "收盘" if is_open is False else "快照"
            return asset.id, MarketQuote(
                price=price,
                change_percent=_decimal(value.get("percent_change")),
                status=status,
                quoted_at=_quoted_at(
                    value.get("last_quote_at")
                    or value.get("timestamp")
                    or value.get("datetime"),
                    now,
                ),
            )

        responses = await asyncio.gather(
            *(fetch_one(asset) for asset in assets),
            return_exceptions=True,
        )
        result: dict[str, MarketQuote] = {}
        for response in responses:
            if isinstance(response, BaseException):
                continue
            asset_id, quote = response
            if quote is not None:
                result[asset_id] = quote
        return result

    async def _fetch_twelve_crypto(
        self,
        client: httpx.AsyncClient,
        assets: Sequence[MarketAsset],
        now: datetime,
    ) -> dict[str, MarketQuote]:
        if not assets or not self.twelve_data_api_key:
            return {}

        async def fetch_one(asset: MarketAsset) -> tuple[str, MarketQuote | None]:
            response = await client.get(
                f"{self.twelve_data_api_base_url}/quote",
                params={
                    "symbol": f"{asset.symbol}/USD",
                    "apikey": self.twelve_data_api_key,
                },
            )
            response.raise_for_status()
            value = response.json()
            if value.get("status") == "error":
                return asset.id, None
            price = _decimal(value.get("close") or value.get("price"))
            if price is None:
                return asset.id, None
            return asset.id, MarketQuote(
                price=price,
                change_percent=_decimal(
                    value.get("rolling_1d_change")
                    or value.get("percent_change")
                ),
                status="24H",
                quoted_at=_quoted_at(
                    value.get("last_quote_at")
                    or value.get("timestamp")
                    or value.get("datetime"),
                    now,
                ),
            )

        responses = await asyncio.gather(
            *(fetch_one(asset) for asset in assets),
            return_exceptions=True,
        )
        result: dict[str, MarketQuote] = {}
        for response in responses:
            if isinstance(response, Exception):
                continue
            asset_id, quote = response
            if quote is not None:
                result[asset_id] = quote
        return result


@lru_cache
def get_market_data_provider() -> MarketDataProvider:
    if get_settings().market_data_provider == "live":
        return LiveMarketDataProvider()
    return MockMarketDataProvider()


async def search_market_assets(
    asset_type: MarketAssetType,
    query: str,
    *,
    limit: int = MARKET_SEARCH_LIMIT,
) -> list[MarketSearchResult]:
    normalized_query = query.strip()
    if not normalized_query:
        return []
    if asset_type not in SEARCHABLE_MARKET_ASSET_TYPES:
        raise ValueError("asset type is not searchable")
    provider = get_market_data_provider()
    if isinstance(provider, LiveMarketDataProvider):
        try:
            return await provider.search_assets(
                asset_type,
                normalized_query,
                limit=limit,
            )
        except (httpx.HTTPError, OpenApiException, TimeoutError) as exc:
            raise MarketSearchUnavailable("market search is temporarily unavailable") from exc

    matches: list[MarketSearchResult] = []
    for item in MARKET_CATALOG:
        if item.asset_type != asset_type:
            continue
        if _security_search_rank(
            normalized_query,
            item.symbol,
            (item.name,),
        ) is None:
            continue
        matches.append(
            MarketSearchResult(
                asset_type=item.asset_type,
                symbol=item.symbol,
                name=item.name,
                currency=item.currency,
                provider_symbol=item.longbridge_symbol or item.provider_symbol,
            )
        )
    return matches[:limit]


async def resolve_market_asset(
    asset_type: MarketAssetType,
    provider_symbol: str,
) -> MarketCatalogItem:
    normalized_provider_symbol = provider_symbol.strip()
    if not normalized_provider_symbol:
        raise ValueError("provider symbol is required")
    for item in MARKET_CATALOG:
        if item.asset_type != asset_type:
            continue
        candidates = {
            item.provider_symbol.casefold(),
            (item.longbridge_symbol or "").casefold(),
        }
        if normalized_provider_symbol.casefold() in candidates:
            return item

    provider = get_market_data_provider()
    if not isinstance(provider, LiveMarketDataProvider):
        raise ValueError("asset is not available in the local catalog")
    try:
        return await provider.resolve_asset(asset_type, normalized_provider_symbol)
    except (httpx.HTTPError, OpenApiException, TimeoutError) as exc:
        raise MarketSearchUnavailable("asset validation is temporarily unavailable") from exc


def market_refresh_due(
    household: Household,
    assets: Sequence[MarketAsset],
    *,
    now: datetime,
) -> bool:
    if not assets:
        return False
    last_attempts = [_aware_utc(asset.last_fetched_at) for asset in assets]
    # A newly selected asset needs one initial quote even during the night pause;
    # otherwise its first rendered frame would remain "暂无" until 07:00.
    if any(value is None for value in last_attempts):
        return True
    local_now = now.astimezone(MARKET_TIMEZONE)
    if household.market_night_pause and (local_now.hour >= 23 or local_now.hour < 7):
        return False
    oldest = min(value for value in last_attempts if value is not None)
    return now - oldest >= timedelta(minutes=household.market_refresh_minutes)


async def load_market_assets(
    session: AsyncSession,
    household_id: str,
) -> list[MarketAsset]:
    return list(
        await session.scalars(
            select(MarketAsset)
            .where(MarketAsset.household_id == household_id)
            .order_by(MarketAsset.sequence, MarketAsset.created_at, MarketAsset.id)
        )
    )


async def load_market_snapshot(
    session: AsyncSession,
    household: Household,
    *,
    now: datetime | None = None,
    refresh: bool = True,
    force_refresh: bool = False,
) -> MarketSnapshot:
    fetched_at = _aware_utc(now or utc_now()) or utc_now()
    assets = await load_market_assets(session, household.id)
    refresh_due = force_refresh or market_refresh_due(
        household,
        assets,
        now=fetched_at,
    )
    if refresh and refresh_due:
        try:
            quotes = await get_market_data_provider().fetch_quotes(
                assets,
                now=fetched_at,
            )
        except (httpx.HTTPError, ValueError, TypeError, KeyError, AttributeError):
            quotes = {}
        for asset in assets:
            quote = quotes.get(asset.id)
            asset.last_fetched_at = fetched_at
            if quote is None:
                asset.quote_stale = asset.last_price is not None
                continue
            asset.last_price = quote.price
            asset.last_change_percent = quote.change_percent
            asset.last_status = quote.status
            asset.last_quoted_at = quote.quoted_at
            asset.quote_stale = False
        await session.flush()

    snapshot_items = tuple(
        MarketSnapshotItem(
            asset_id=asset.id,
            asset_type=asset.asset_type,
            symbol=asset.symbol,
            name=asset.name,
            currency=asset.currency,
            price=asset.last_price,
            change_percent=asset.last_change_percent,
            status="延迟" if asset.quote_stale else (asset.last_status or "暂无"),
            quoted_at=_aware_utc(asset.last_quoted_at),
            stale=asset.quote_stale,
        )
        for asset in assets
    )
    update_candidates = [
        value
        for value in (_aware_utc(asset.last_fetched_at) for asset in assets)
        if value is not None
    ]
    updated_at = max(update_candidates, default=_aware_utc(household.updated_at) or fetched_at)
    return MarketSnapshot(
        items=snapshot_items,
        updated_at=updated_at,
        refresh_minutes=household.market_refresh_minutes,
        night_pause=household.market_night_pause,
    )
