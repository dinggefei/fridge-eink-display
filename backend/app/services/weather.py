from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from functools import lru_cache
from typing import Protocol
from zoneinfo import ZoneInfo

import httpx
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import utc_now
from app.db.models import Household
from app.settings import get_settings


QWEATHER_SOURCE_NAME = "和风天气"
QWEATHER_SOURCE_URL = "https://www.qweather.com"


@dataclass(frozen=True, slots=True)
class WeatherLocation:
    location_id: str
    name: str
    adm1: str
    adm2: str
    country: str
    latitude: Decimal
    longitude: Decimal

    @property
    def display_name(self) -> str:
        parts: list[str] = []
        for value in (self.adm1, self.adm2, self.name):
            if value and value not in parts:
                parts.append(value)
        return " · ".join(parts)


@dataclass(frozen=True, slots=True)
class WeatherSummary:
    location_name: str
    condition_text: str
    temp_min: int
    temp_max: int
    precip_probability: int | None


@dataclass(frozen=True, slots=True)
class WeatherForecast:
    displayed_on: date
    condition_text: str
    temp_min: int
    temp_max: int
    precip_probability: int | None


class WeatherDataProvider(Protocol):
    async def fetch_days(self, *, latitude: Decimal, longitude: Decimal,
                         displayed_on: date, days: int = 7) -> list[WeatherForecast]: ...
    async def search_locations(self, query: str) -> list[WeatherLocation]: ...

    async def fetch_daily(
        self,
        *,
        latitude: Decimal,
        longitude: Decimal,
        displayed_on: date,
    ) -> WeatherForecast: ...


def _aware_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _base64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _bounded_probability(value: object) -> int | None:
    if value is None:
        return None
    number = float(value)
    if number <= 1:
        number *= 100
    return max(0, min(100, round(number)))


def _weather_text(daytime: str, nighttime: str) -> str:
    first = daytime.strip()
    second = nighttime.strip()
    if not second or first == second:
        return first or second or "天气待更新"
    return f"{first}转{second}"


class DisabledWeatherDataProvider:
    async def fetch_days(self, **kwargs) -> list[WeatherForecast]:
        raise RuntimeError("weather data provider is disabled")

    async def search_locations(self, query: str) -> list[WeatherLocation]:
        return []

    async def fetch_daily(
        self,
        *,
        latitude: Decimal,
        longitude: Decimal,
        displayed_on: date,
    ) -> WeatherForecast:
        raise RuntimeError("weather data provider is disabled")


class MockWeatherDataProvider:
    async def fetch_days(self, *, latitude: Decimal, longitude: Decimal,
                         displayed_on: date, days: int = 7) -> list[WeatherForecast]:
        return [WeatherForecast(displayed_on + timedelta(days=i),
                    "午后阵雨" if i in (3, 4) else "晴间多云", 21 + i % 3, 30,
                    65 if i in (3, 4) else 10) for i in range(days)]

    _locations = (
        WeatherLocation(
            "101020100",
            "上海",
            "上海市",
            "上海",
            "中国",
            Decimal("31.23171"),
            Decimal("121.47264"),
        ),
        WeatherLocation(
            "101010100",
            "北京",
            "北京市",
            "北京",
            "中国",
            Decimal("39.90499"),
            Decimal("116.40529"),
        ),
        WeatherLocation(
            "101280601",
            "深圳",
            "广东省",
            "深圳",
            "中国",
            Decimal("22.54700"),
            Decimal("114.08595"),
        ),
        WeatherLocation(
            "101210101",
            "杭州",
            "浙江省",
            "杭州",
            "中国",
            Decimal("30.27415"),
            Decimal("120.15515"),
        ),
    )

    async def search_locations(self, query: str) -> list[WeatherLocation]:
        normalized = query.strip().lower()
        return [
            location
            for location in self._locations
            if normalized in location.display_name.lower()
            or normalized in location.location_id.lower()
        ][:10]

    async def fetch_daily(
        self,
        *,
        latitude: Decimal,
        longitude: Decimal,
        displayed_on: date,
    ) -> WeatherForecast:
        return WeatherForecast(
            displayed_on=displayed_on,
            condition_text="多云",
            temp_min=18,
            temp_max=27,
            precip_probability=20,
        )


class QWeatherDataProvider:
    def __init__(self) -> None:
        settings = get_settings()
        self.api_host = settings.qweather_api_host.strip().rstrip("/")
        if self.api_host and not self.api_host.startswith(("http://", "https://")):
            self.api_host = f"https://{self.api_host}"
        self.credential_id = settings.qweather_credential_id
        self.developer_id = settings.qweather_developer_id
        self.project_id = settings.qweather_project_id
        encoded_key = settings.qweather_private_key_base64.get_secret_value()
        try:
            key_bytes = base64.b64decode(encoded_key, validate=True)
            private_key = serialization.load_pem_private_key(key_bytes, password=None)
        except (ValueError, TypeError) as error:
            raise ValueError("invalid QWeather Ed25519 private key") from error
        if not isinstance(private_key, Ed25519PrivateKey):
            raise ValueError("QWeather private key must use Ed25519")
        self.private_key = private_key
        self.timeout = settings.weather_data_timeout_seconds

    def _jwt(self, *, now: datetime | None = None) -> str:
        issued_at = int((now or utc_now()).timestamp()) - 30
        header = {"alg": "EdDSA", "kid": self.credential_id}
        payload = {
            "iss": self.developer_id,
            "sub": self.project_id,
            "iat": issued_at,
            "exp": issued_at + 900,
        }
        encoded_header = _base64url(
            json.dumps(header, separators=(",", ":")).encode("utf-8")
        )
        encoded_payload = _base64url(
            json.dumps(payload, separators=(",", ":")).encode("utf-8")
        )
        message = f"{encoded_header}.{encoded_payload}".encode("ascii")
        signature = _base64url(self.private_key.sign(message))
        return f"{message.decode('ascii')}.{signature}"

    def _headers(self) -> dict[str, str]:
        return {
            "Accept": "application/json",
            "Authorization": f"Bearer {self._jwt()}",
        }

    async def search_locations(self, query: str) -> list[WeatherLocation]:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.get(
                f"{self.api_host}/geo/v2/city/lookup",
                params={
                    "location": query,
                    "range": "cn",
                    "number": 10,
                    "lang": "zh",
                },
                headers=self._headers(),
            )
            response.raise_for_status()
            payload = response.json()
        if payload.get("code") != "200":
            raise ValueError("QWeather city lookup failed")
        result: list[WeatherLocation] = []
        for item in payload.get("location") or []:
            try:
                result.append(
                    WeatherLocation(
                        location_id=str(item["id"]),
                        name=str(item["name"]),
                        adm1=str(item.get("adm1") or ""),
                        adm2=str(item.get("adm2") or ""),
                        country=str(item.get("country") or ""),
                        latitude=Decimal(str(item["lat"])),
                        longitude=Decimal(str(item["lon"])),
                    )
                )
            except (KeyError, ValueError, TypeError):
                continue
        return result

    async def fetch_daily(
        self,
        *,
        latitude: Decimal,
        longitude: Decimal,
        displayed_on: date,
    ) -> WeatherForecast:
        forecasts = await self.fetch_days(latitude=latitude, longitude=longitude,
                                         displayed_on=displayed_on, days=1)
        return forecasts[0]

    async def fetch_days(self, *, latitude: Decimal, longitude: Decimal,
                         displayed_on: date, days: int = 7) -> list[WeatherForecast]:
        lat = f"{latitude:.2f}"
        lon = f"{longitude:.2f}"
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.get(
                f"{self.api_host}/weather/v1/daily/{lat}/{lon}",
                params={"days": days, "localTime": "true", "lang": "zh"},
                headers=self._headers(),
            )
            response.raise_for_status()
            payload = response.json()
        values = payload.get("days") or []
        forecasts = [self._parse_day(value) for value in values]
        forecasts = sorted((v for v in forecasts if
            displayed_on <= v.displayed_on < displayed_on + timedelta(days=days)),
            key=lambda v: v.displayed_on)
        if not forecasts or len({v.displayed_on for v in forecasts}) != len(forecasts):
            raise ValueError("QWeather daily forecast is empty")
        return forecasts

    @staticmethod
    def _parse_day(value: dict) -> WeatherForecast:
        # The forecast period may begin on the previous UTC date; use its local date.
        start = datetime.fromisoformat(value["forecastStartTime"].replace("Z", "+00:00"))
        if start.tzinfo is not None:
            start = start.astimezone(ZoneInfo("Asia/Shanghai"))
        daytime = value.get("daytime") or {}
        nighttime = value.get("nighttime") or {}
        day_condition = (daytime.get("condition") or {}).get("text") or ""
        night_condition = (nighttime.get("condition") or {}).get("text") or ""
        probabilities = [
            _bounded_probability(
                (period.get("precipitation") or {}).get("probability")
            )
            for period in (daytime, nighttime)
        ]
        known_probabilities = [item for item in probabilities if item is not None]
        return WeatherForecast(
            displayed_on=start.date(),
            condition_text=_weather_text(day_condition, night_condition),
            temp_min=round(float(value["temperatureMin"]["value"])),
            temp_max=round(float(value["temperatureMax"]["value"])),
            precip_probability=max(known_probabilities, default=None),
        )


def weather_provider_ready() -> bool:
    settings = get_settings()
    if settings.weather_data_provider == "mock":
        return True
    if settings.weather_data_provider != "qweather":
        return False
    return all(
        (
            settings.qweather_api_host,
            settings.qweather_credential_id,
            settings.qweather_developer_id,
            settings.qweather_project_id,
            settings.qweather_private_key_base64.get_secret_value(),
        )
    )


@lru_cache
def get_weather_data_provider() -> WeatherDataProvider:
    provider = get_settings().weather_data_provider
    if provider == "qweather":
        return QWeatherDataProvider()
    if provider == "mock":
        return MockWeatherDataProvider()
    return DisabledWeatherDataProvider()


async def search_weather_locations(query: str) -> list[WeatherLocation]:
    normalized = query.strip()
    if len(normalized) < 2:
        return []
    return await get_weather_data_provider().search_locations(normalized)


def _cached_summary(
    household: Household,
    *,
    displayed_on: date,
    now: datetime,
) -> WeatherSummary | None:
    settings = get_settings()
    last_success = _aware_utc(household.weather_last_success_at)
    if (
        household.weather_forecast_date != displayed_on
        or not household.weather_location_name
        or not household.weather_condition_text
        or household.weather_temp_min is None
        or household.weather_temp_max is None
        or last_success is None
        or now - last_success > timedelta(hours=settings.weather_stale_hours)
    ):
        return None
    return WeatherSummary(
        location_name=household.weather_location_name,
        condition_text=household.weather_condition_text,
        temp_min=household.weather_temp_min,
        temp_max=household.weather_temp_max,
        precip_probability=household.weather_precip_probability,
    )


def weather_refresh_due(
    household: Household,
    *,
    displayed_on: date,
    now: datetime,
) -> bool:
    settings = get_settings()
    if household.weather_forecast_date != displayed_on:
        return True
    last_attempt = _aware_utc(household.weather_last_attempted_at)
    if last_attempt is None:
        return True
    has_cached_value = household.weather_last_success_at is not None
    interval = (
        timedelta(hours=settings.weather_refresh_hours)
        if has_cached_value
        else timedelta(minutes=settings.weather_failure_retry_minutes)
    )
    return now - last_attempt >= interval


async def load_weather_summary(
    session: AsyncSession,
    household: Household,
    *,
    displayed_on: date,
    now: datetime | None = None,
    refresh: bool = True,
) -> WeatherSummary | None:
    if (
        not household.almanac_weather_enabled
        or not household.weather_location_name
        or household.weather_latitude is None
        or household.weather_longitude is None
    ):
        return None
    fetched_at = _aware_utc(now or utc_now()) or utc_now()
    if refresh and weather_provider_ready() and weather_refresh_due(
        household,
        displayed_on=displayed_on,
        now=fetched_at,
    ):
        household.weather_last_attempted_at = fetched_at
        try:
            forecast = await get_weather_data_provider().fetch_daily(
                latitude=household.weather_latitude,
                longitude=household.weather_longitude,
                displayed_on=displayed_on,
            )
        except (httpx.HTTPError, ValueError, TypeError, KeyError, RuntimeError):
            pass
        else:
            household.weather_condition_text = forecast.condition_text
            household.weather_temp_min = forecast.temp_min
            household.weather_temp_max = forecast.temp_max
            household.weather_precip_probability = forecast.precip_probability
            household.weather_forecast_date = forecast.displayed_on
            household.weather_last_success_at = fetched_at
        await session.flush()
    return _cached_summary(household, displayed_on=displayed_on, now=fetched_at)
