from __future__ import annotations

from datetime import date
from decimal import Decimal
from io import BytesIO
from typing import Literal

import httpx
from fastapi import APIRouter, HTTPException, Query, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.api.dependencies import CurrentUser, DbSession, require_household_member
from app.db.models import (
    Device,
    DisplayMode,
    DisplayPhoto,
    DisplayPhotoStatus,
    Household,
    MarketAsset,
)
from app.services.almanac import AlmanacDay, calculate_almanac
from app.services.display_renderer import current_display_date
from app.services.market_data import live_market_data_ready, load_market_snapshot
from app.services.weather import (
    QWEATHER_SOURCE_NAME,
    QWEATHER_SOURCE_URL,
    WeatherLocation,
    WeatherSummary,
    load_weather_summary,
    search_weather_locations,
    weather_provider_ready,
)
from app.settings import get_settings
from app.services.weather_forecast import load_weather_week
from app.services.weather_renderer import render_weather_image
from app.services.display_renderer import native_image_to_portrait

router = APIRouter(
    prefix="/v1/households/{household_id}/display-settings",
    tags=["display-settings"],
)


class AlmanacDayResponse(BaseModel):
    displayed_on: date
    date_text: str
    day_number: int
    weekday: str
    lunar_date: str
    ganzhi: str
    zodiac: str
    seasonal_note: str
    yi: list[str]
    ji: list[str]
    chong_sha: str
    disclaimer: str


class WeatherLocationResponse(BaseModel):
    location_id: str = Field(min_length=1, max_length=32)
    name: str = Field(min_length=1, max_length=80)
    adm1: str = Field(max_length=80)
    display_name: str = Field(min_length=1, max_length=180)
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)


class WeatherSummaryResponse(BaseModel):
    location_name: str
    condition_text: str
    temp_min: int
    temp_max: int
    precip_probability: int | None


class DisplaySettingsResponse(BaseModel):
    weather_mode_available: bool = True
    timetable_mode_available: bool = True
    display_mode: DisplayMode
    scope: Literal["household", "device"] = "household"
    device_code: str | None = None
    inherits_household: bool = True
    household_display_mode: DisplayMode
    album_ready: bool
    market_ready: bool
    timetable_ready: bool
    timetable_orientation: Literal["portrait", "landscape"]
    almanac: AlmanacDayResponse
    weather_enabled: bool
    weather_provider_ready: bool
    weather_location: WeatherLocationResponse | None
    weather: WeatherSummaryResponse | None
    weather_source_name: str
    weather_source_url: str


class DisplaySettingsWrite(BaseModel):
    display_mode: DisplayMode | None = None


class WeatherSettingsWrite(BaseModel):
    # Omitted for weather-mode city selection; do not change the almanac switch.
    enabled: bool | None = None
    location: WeatherLocationResponse | None = None


def _almanac_response(value: AlmanacDay) -> AlmanacDayResponse:
    return AlmanacDayResponse(
        displayed_on=value.displayed_on,
        date_text=value.displayed_on.strftime("%Y年%m月%d日"),
        day_number=value.displayed_on.day,
        weekday=value.weekday,
        lunar_date=value.lunar_date,
        ganzhi=value.ganzhi,
        zodiac=value.zodiac,
        seasonal_note=value.seasonal_note,
        yi=list(value.yi),
        ji=list(value.ji),
        chong_sha=value.chong_sha,
        disclaimer=value.disclaimer,
    )


def _location_response(value: WeatherLocation) -> WeatherLocationResponse:
    return WeatherLocationResponse(
        location_id=value.location_id,
        name=value.name,
        adm1=value.adm1,
        display_name=value.display_name,
        latitude=float(value.latitude),
        longitude=float(value.longitude),
    )


def _household_location(household: Household) -> WeatherLocationResponse | None:
    if (
        not household.weather_location_id
        or not household.weather_location_name
        or household.weather_latitude is None
        or household.weather_longitude is None
    ):
        return None
    parts = [
        value
        for value in (household.weather_adm1, household.weather_location_name)
        if value
    ]
    display_name = " · ".join(dict.fromkeys(parts))
    return WeatherLocationResponse(
        location_id=household.weather_location_id,
        name=household.weather_location_name,
        adm1=household.weather_adm1 or "",
        display_name=display_name,
        latitude=float(household.weather_latitude),
        longitude=float(household.weather_longitude),
    )


def _weather_response(value: WeatherSummary | None) -> WeatherSummaryResponse | None:
    if value is None:
        return None
    return WeatherSummaryResponse(
        location_name=value.location_name,
        condition_text=value.condition_text,
        temp_min=value.temp_min,
        temp_max=value.temp_max,
        precip_probability=value.precip_probability,
    )


async def _load_response(
    session: DbSession,
    household: Household,
    device: Device | None = None,
) -> DisplaySettingsResponse:
    confirmed_count = await session.scalar(
        select(func.count(DisplayPhoto.id)).where(
            DisplayPhoto.household_id == household.id,
            DisplayPhoto.status == DisplayPhotoStatus.CONFIRMED,
        )
    )
    market_count = await session.scalar(
        select(func.count(MarketAsset.id)).where(
            MarketAsset.household_id == household.id,
        )
    )
    displayed_on = current_display_date()
    weather = await load_weather_summary(
        session,
        household,
        displayed_on=displayed_on,
        refresh=False,
    )
    return DisplaySettingsResponse(
        display_mode=(
            device.display_mode_override
            if device is not None and device.display_mode_override is not None
            else household.display_mode
        ),
        scope="device" if device is not None else "household",
        device_code=device.device_code if device is not None else None,
        inherits_household=(
            device is None or device.display_mode_override is None
        ),
        household_display_mode=household.display_mode,
        album_ready=(confirmed_count or 0) > 0,
        market_ready=(market_count or 0) > 0,
        timetable_ready=any(
            str(item.get("course_name", "")).strip()
            for item in (household.timetable_entries or [])
        ),
        timetable_orientation=household.timetable_orientation,
        almanac=_almanac_response(calculate_almanac(displayed_on)),
        weather_enabled=household.almanac_weather_enabled,
        weather_provider_ready=weather_provider_ready(),
        weather_location=_household_location(household),
        weather=_weather_response(weather),
        weather_source_name=QWEATHER_SOURCE_NAME,
        weather_source_url=QWEATHER_SOURCE_URL,
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


async def _display_device(
    session: DbSession,
    household_id: str,
    device_code: str | None,
    *,
    lock: bool = False,
) -> Device | None:
    if not device_code:
        return None
    statement = select(Device).where(
        Device.device_code == device_code,
        Device.household_id == household_id,
    )
    if lock:
        statement = statement.with_for_update()
    device = await session.scalar(statement)
    if device is None:
        raise HTTPException(status_code=404, detail="device not found")
    return device


@router.get("", response_model=DisplaySettingsResponse)
async def read_display_settings(
    household_id: str,
    session: DbSession,
    user: CurrentUser,
    device_code: str | None = Query(default=None, min_length=3, max_length=64),
) -> DisplaySettingsResponse:
    household = await _household(session, user, household_id)
    device = await _display_device(session, household_id, device_code)
    return await _load_response(session, household, device)


@router.put("", response_model=DisplaySettingsResponse)
async def replace_display_settings(
    household_id: str,
    payload: DisplaySettingsWrite,
    session: DbSession,
    user: CurrentUser,
    device_code: str | None = Query(default=None, min_length=3, max_length=64),
) -> DisplaySettingsResponse:
    household = await _household(session, user, household_id, lock=True)
    device = await _display_device(
        session,
        household_id,
        device_code,
        lock=True,
    )
    if device is None and payload.display_mode is None:
        raise HTTPException(
            status_code=422,
            detail="household display mode cannot inherit",
        )
    response = await _load_response(session, household, device)
    previous_mode = response.display_mode
    target_mode = payload.display_mode or household.display_mode
    if target_mode == DisplayMode.WEATHER:
        if not weather_provider_ready():
            raise HTTPException(status_code=503, detail="weather service is not configured")
        if not response.weather_location:
            raise HTTPException(status_code=409, detail="select a weather city before enabling weather mode")
    if target_mode == DisplayMode.ALBUM and not response.album_ready:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="confirm at least one photo before enabling album mode",
        )
    if target_mode == DisplayMode.MARKET and not response.market_ready:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="add at least one market asset before enabling market mode",
        )
    if target_mode == DisplayMode.TIMETABLE and not response.timetable_ready:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="add at least one course before enabling timetable mode",
        )
    if (
        target_mode == DisplayMode.MARKET
        and get_settings().app_env.lower() == "production"
        and not live_market_data_ready()
    ):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="live market data provider is not configured",
        )
    if device is None:
        household.display_mode = target_mode
    else:
        device.display_mode_override = payload.display_mode
    if target_mode == DisplayMode.MARKET and previous_mode != DisplayMode.MARKET:
        # Switching modes is an explicit request for a current screen. Perform
        # one quote fetch even during the configured night-pause window; later
        # device polls still follow the normal interval and night-pause rules.
        await load_market_snapshot(session, household, force_refresh=True)
    await session.commit()
    await session.refresh(household)
    if device is not None:
        await session.refresh(device)
    return await _load_response(session, household, device)


@router.get("/weather-preview", response_class=Response)
async def weather_preview(household_id: str, session: DbSession, user: CurrentUser) -> Response:
    household = await _household(session, user, household_id, lock=True)
    week = await load_weather_week(session, household, displayed_on=current_display_date())
    output = BytesIO()
    native_image_to_portrait(render_weather_image(week)).save(output, format="PNG")
    await session.commit()
    return Response(content=output.getvalue(), media_type="image/png",
                    headers={"Cache-Control": "private, no-store"})


@router.get(
    "/weather-locations",
    response_model=list[WeatherLocationResponse],
)
async def find_weather_locations(
    household_id: str,
    session: DbSession,
    user: CurrentUser,
    query: str = Query(min_length=2, max_length=40),
) -> list[WeatherLocationResponse]:
    await _household(session, user, household_id)
    if not weather_provider_ready():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="weather service is not configured",
        )
    try:
        locations = await search_weather_locations(query)
    except (httpx.HTTPError, ValueError, TypeError, RuntimeError) as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="weather location search is temporarily unavailable",
        ) from error
    return [_location_response(location) for location in locations]


@router.put("/weather", response_model=DisplaySettingsResponse)
async def replace_weather_settings(
    household_id: str,
    payload: WeatherSettingsWrite,
    session: DbSession,
    user: CurrentUser,
) -> DisplaySettingsResponse:
    household = await _household(session, user, household_id, lock=True)
    if payload.enabled and not weather_provider_ready():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="weather service is not configured",
        )
    if (
        payload.enabled
        and payload.location is None
        and not household.weather_location_id
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="select a weather city before enabling weather",
        )
    if payload.location is not None:
        location_changed = (
            payload.location.location_id != household.weather_location_id
            or Decimal(str(payload.location.latitude)) != household.weather_latitude
            or Decimal(str(payload.location.longitude)) != household.weather_longitude
        )
        household.weather_location_id = payload.location.location_id
        household.weather_location_name = payload.location.name.strip()
        household.weather_adm1 = payload.location.adm1.strip()
        household.weather_latitude = Decimal(str(payload.location.latitude))
        household.weather_longitude = Decimal(str(payload.location.longitude))
        if location_changed:
            household.weather_condition_text = None
            household.weather_temp_min = None
            household.weather_temp_max = None
            household.weather_precip_probability = None
            household.weather_forecast_date = None
            household.weather_last_attempted_at = None
            household.weather_last_success_at = None
    if payload.enabled is not None:
        household.almanac_weather_enabled = payload.enabled
    await session.flush()
    if payload.enabled:
        await load_weather_summary(
            session,
            household,
            displayed_on=current_display_date(),
            refresh=True,
        )
    await session.commit()
    await session.refresh(household)
    return await _load_response(session, household)
