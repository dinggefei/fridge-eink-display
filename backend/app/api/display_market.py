from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import delete, select

from app.api.dependencies import CurrentUser, DbSession, require_household_member
from app.db.models import DisplayMode, Household, MarketAsset, MarketAssetType
from app.services.market_data import (
    MARKET_CATALOG,
    MARKET_REFRESH_MINUTES,
    MARKET_SEARCH_LIMIT,
    MAX_MARKET_ASSETS,
    MarketCatalogItem,
    MarketSearchResult,
    MarketSearchUnavailable,
    MarketSnapshot,
    catalog_item,
    load_market_assets,
    load_market_snapshot,
    market_data_source_label,
    resolve_market_asset,
    search_market_assets,
)

router = APIRouter(
    prefix="/v1/households/{household_id}/display-market",
    tags=["display-market"],
)


class MarketCatalogItemResponse(BaseModel):
    asset_type: MarketAssetType
    symbol: str
    name: str
    currency: str


class MarketAssetSelection(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    asset_type: MarketAssetType
    symbol: str = Field(min_length=1, max_length=32)


class MarketAssetCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    asset_type: MarketAssetType
    provider_symbol: str = Field(min_length=1, max_length=64)


class MarketSearchResultResponse(BaseModel):
    asset_type: MarketAssetType
    symbol: str
    name: str
    currency: str
    provider_symbol: str


class MarketDashboardWrite(BaseModel):
    refresh_minutes: int | None = None
    night_pause: bool | None = None
    assets: list[MarketAssetSelection] | None = Field(
        default=None,
        max_length=MAX_MARKET_ASSETS,
    )

    @model_validator(mode="after")
    def validate_request(self) -> "MarketDashboardWrite":
        if (
            self.refresh_minutes is not None
            and self.refresh_minutes not in MARKET_REFRESH_MINUTES
        ):
            raise ValueError("refresh_minutes must be 15, 30 or 60")
        if self.assets is not None:
            keys = [
                (item.asset_type, item.symbol.upper()) for item in self.assets
            ]
            if len(keys) != len(set(keys)):
                raise ValueError("market assets must not contain duplicates")
        return self


class MarketAssetResponse(BaseModel):
    id: str
    asset_type: MarketAssetType
    symbol: str
    name: str
    currency: str
    sequence: int
    price: Decimal | None
    change_percent: Decimal | None
    status: str
    quoted_at: datetime | None
    stale: bool


class MarketDashboardResponse(BaseModel):
    display_mode: DisplayMode
    refresh_minutes: int
    night_pause: bool
    max_assets: int
    assets: list[MarketAssetResponse]
    catalog: list[MarketCatalogItemResponse]
    source_label: str
    disclaimer: str = "行情仅供参考"


def _catalog_response(item: MarketCatalogItem) -> MarketCatalogItemResponse:
    return MarketCatalogItemResponse(
        asset_type=item.asset_type,
        symbol=item.symbol,
        name=item.name,
        currency=item.currency,
    )


def _search_response(item: MarketSearchResult) -> MarketSearchResultResponse:
    return MarketSearchResultResponse(
        asset_type=item.asset_type,
        symbol=item.symbol,
        name=item.name,
        currency=item.currency,
        provider_symbol=item.provider_symbol,
    )


def _stored_catalog_item(asset: MarketAsset) -> MarketCatalogItem:
    return MarketCatalogItem(
        asset_type=asset.asset_type,
        symbol=asset.symbol,
        name=asset.name,
        currency=asset.currency,
        provider_symbol=asset.provider_symbol,
        provider_mic_code=asset.provider_mic_code,
        longbridge_symbol=(
            asset.provider_symbol
            if asset.asset_type
            in {
                MarketAssetType.US_STOCK,
                MarketAssetType.CN_STOCK,
                MarketAssetType.HK_STOCK,
            }
            else None
        ),
    )


def _dashboard_response(
    household: Household,
    assets: list[MarketAsset],
    snapshot: MarketSnapshot,
) -> MarketDashboardResponse:
    snapshot_by_id = {item.asset_id: item for item in snapshot.items}
    response_assets: list[MarketAssetResponse] = []
    for asset in assets:
        quote = snapshot_by_id[asset.id]
        response_assets.append(
            MarketAssetResponse(
                id=asset.id,
                asset_type=asset.asset_type,
                symbol=asset.symbol,
                name=asset.name,
                currency=asset.currency,
                sequence=asset.sequence,
                price=quote.price,
                change_percent=quote.change_percent,
                status=quote.status,
                quoted_at=quote.quoted_at,
                stale=quote.stale,
            )
        )
    return MarketDashboardResponse(
        display_mode=household.display_mode,
        refresh_minutes=household.market_refresh_minutes,
        night_pause=household.market_night_pause,
        max_assets=MAX_MARKET_ASSETS,
        assets=response_assets,
        catalog=[_catalog_response(item) for item in MARKET_CATALOG],
        source_label=market_data_source_label(),
    )


async def _household(
    session: DbSession,
    user: CurrentUser,
    household_id: str,
    *,
    lock: bool = False,
) -> Household:
    await require_household_member(
        session,
        household_id=household_id,
        user_id=user.id,
    )
    statement = select(Household).where(Household.id == household_id)
    if lock:
        statement = statement.with_for_update()
    household = await session.scalar(statement)
    if household is None:
        raise HTTPException(status_code=404, detail="household not found")
    return household


@router.get("", response_model=MarketDashboardResponse)
async def read_market_dashboard(
    household_id: str,
    session: DbSession,
    user: CurrentUser,
) -> MarketDashboardResponse:
    household = await _household(session, user, household_id)
    snapshot = await load_market_snapshot(session, household)
    assets = await load_market_assets(session, household.id)
    await session.commit()
    return _dashboard_response(household, assets, snapshot)


@router.get(
    "/search",
    response_model=list[MarketSearchResultResponse],
)
async def search_market_catalog(
    household_id: str,
    session: DbSession,
    user: CurrentUser,
    asset_type: MarketAssetType,
    query: str = Query(min_length=1, max_length=40),
) -> list[MarketSearchResultResponse]:
    await _household(session, user, household_id)
    try:
        results = await search_market_assets(
            asset_type,
            query,
            limit=MARKET_SEARCH_LIMIT,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc
    except MarketSearchUnavailable as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="行情搜索服务暂时不可用，请稍后重试",
        ) from exc
    return [_search_response(item) for item in results]


@router.post(
    "/assets",
    response_model=MarketDashboardResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_market_asset(
    household_id: str,
    payload: MarketAssetCreate,
    session: DbSession,
    user: CurrentUser,
) -> MarketDashboardResponse:
    await _household(session, user, household_id)
    try:
        item = await resolve_market_asset(
            payload.asset_type,
            payload.provider_symbol,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc
    except MarketSearchUnavailable as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="行情标的校验暂时不可用，请稍后重试",
        ) from exc

    household = await _household(session, user, household_id, lock=True)
    existing = await load_market_assets(session, household.id)
    if any(
        asset.asset_type == item.asset_type
        and (
            asset.symbol.casefold() == item.symbol.casefold()
            or asset.provider_symbol.casefold() == item.provider_symbol.casefold()
        )
        for asset in existing
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="该资产已经在当前展示列表中",
        )
    if len(existing) >= MAX_MARKET_ASSETS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"最多展示 {MAX_MARKET_ASSETS} 项资产",
        )
    session.add(
        MarketAsset(
            household_id=household.id,
            created_by_user_id=user.id,
            asset_type=item.asset_type,
            symbol=item.symbol,
            name=item.name,
            currency=item.currency,
            provider_symbol=item.provider_symbol,
            provider_mic_code=item.provider_mic_code,
            sequence=len(existing),
        )
    )
    await session.flush()
    snapshot = await load_market_snapshot(session, household)
    assets = await load_market_assets(session, household.id)
    await session.commit()
    return _dashboard_response(household, assets, snapshot)


@router.delete(
    "/assets/{asset_id}",
    response_model=MarketDashboardResponse,
)
async def delete_market_asset(
    household_id: str,
    asset_id: str,
    session: DbSession,
    user: CurrentUser,
) -> MarketDashboardResponse:
    household = await _household(session, user, household_id, lock=True)
    asset = await session.scalar(
        select(MarketAsset).where(
            MarketAsset.id == asset_id,
            MarketAsset.household_id == household.id,
        )
    )
    if asset is None:
        raise HTTPException(status_code=404, detail="market asset not found")
    await session.delete(asset)
    await session.flush()
    assets = await load_market_assets(session, household.id)
    for sequence, retained in enumerate(assets):
        retained.sequence = sequence
    if not assets and household.display_mode == DisplayMode.MARKET:
        household.display_mode = DisplayMode.INVENTORY
    await session.flush()
    snapshot = await load_market_snapshot(session, household)
    await session.commit()
    return _dashboard_response(household, assets, snapshot)


@router.put("", response_model=MarketDashboardResponse)
async def replace_market_dashboard(
    household_id: str,
    payload: MarketDashboardWrite,
    session: DbSession,
    user: CurrentUser,
) -> MarketDashboardResponse:
    household = await _household(session, user, household_id, lock=True)
    if payload.refresh_minutes is not None:
        household.market_refresh_minutes = payload.refresh_minutes
    if payload.night_pause is not None:
        household.market_night_pause = payload.night_pause

    if payload.assets is not None:
        existing = await load_market_assets(session, household.id)
        existing_by_key = {
            (asset.asset_type, asset.symbol): asset for asset in existing
        }
        resolved: list[MarketCatalogItem] = []
        for selection in payload.assets:
            item = catalog_item(selection.asset_type, selection.symbol)
            if item is None:
                stored = existing_by_key.get(
                    (selection.asset_type, selection.symbol.upper())
                )
                if stored is None:
                    raise HTTPException(
                        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                        detail=(
                            f"unsupported market asset: "
                            f"{selection.asset_type.value}/{selection.symbol}"
                        ),
                    )
                item = _stored_catalog_item(stored)
            resolved.append(item)

        retained_ids: set[str] = set()
        for sequence, item in enumerate(resolved):
            key = (item.asset_type, item.symbol)
            asset = existing_by_key.get(key)
            if asset is None:
                asset = MarketAsset(
                    household_id=household.id,
                    created_by_user_id=user.id,
                    asset_type=item.asset_type,
                    symbol=item.symbol,
                    name=item.name,
                    currency=item.currency,
                    provider_symbol=item.provider_symbol,
                    provider_mic_code=item.provider_mic_code,
                    sequence=sequence,
                )
                session.add(asset)
                await session.flush()
            else:
                asset.sequence = sequence
                asset.name = item.name
                asset.currency = item.currency
                asset.provider_symbol = item.provider_symbol
                asset.provider_mic_code = item.provider_mic_code
            retained_ids.add(asset.id)

        remove_ids = [asset.id for asset in existing if asset.id not in retained_ids]
        if remove_ids:
            await session.execute(
                delete(MarketAsset).where(MarketAsset.id.in_(remove_ids))
            )
        if not resolved and household.display_mode == DisplayMode.MARKET:
            household.display_mode = DisplayMode.INVENTORY

    await session.flush()
    snapshot = await load_market_snapshot(session, household)
    assets = await load_market_assets(session, household.id)
    await session.commit()
    return _dashboard_response(household, assets, snapshot)
