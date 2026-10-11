from __future__ import annotations

import asyncio
import base64
import json
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import httpx
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from app.db.models import Household
from app.services.weather import QWeatherDataProvider, load_weather_summary
from app.settings import get_settings


DISPLAYED_ON = date(2026, 9, 11)
NOW = datetime(2026, 9, 11, 6, 0, tzinfo=timezone.utc)


class FlushOnlySession:
    def __init__(self) -> None:
        self.flush_count = 0

    async def flush(self) -> None:
        self.flush_count += 1


class FailingWeatherProvider:
    async def fetch_daily(self, **kwargs):
        raise httpx.ConnectError("weather provider unavailable")


def _decode_base64url(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _cached_household(*, last_success_at: datetime) -> Household:
    household = Household(name="天气缓存测试", admin_user_id="user-1")
    household.almanac_weather_enabled = True
    household.weather_location_id = "101020100"
    household.weather_location_name = "上海"
    household.weather_latitude = Decimal("31.23171")
    household.weather_longitude = Decimal("121.47264")
    household.weather_condition_text = "多云"
    household.weather_temp_min = 18
    household.weather_temp_max = 27
    household.weather_precip_probability = 20
    household.weather_forecast_date = DISPLAYED_ON
    household.weather_last_attempted_at = NOW - timedelta(hours=4)
    household.weather_last_success_at = last_success_at
    return household


def test_weather_failure_keeps_fresh_same_day_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("WEATHER_DATA_PROVIDER", "mock")
    get_settings.cache_clear()
    monkeypatch.setattr(
        "app.services.weather.get_weather_data_provider",
        lambda: FailingWeatherProvider(),
    )
    household = _cached_household(last_success_at=NOW - timedelta(hours=2))
    session = FlushOnlySession()

    result = asyncio.run(
        load_weather_summary(
            session,  # type: ignore[arg-type]
            household,
            displayed_on=DISPLAYED_ON,
            now=NOW,
        )
    )

    assert result is not None
    assert result.location_name == "上海"
    assert result.condition_text == "多云"
    assert session.flush_count == 1


def test_weather_cache_is_hidden_after_stale_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("WEATHER_DATA_PROVIDER", "disabled")
    monkeypatch.setenv("WEATHER_STALE_HOURS", "12")
    get_settings.cache_clear()
    household = _cached_household(last_success_at=NOW - timedelta(hours=13))

    result = asyncio.run(
        load_weather_summary(
            FlushOnlySession(),  # type: ignore[arg-type]
            household,
            displayed_on=DISPLAYED_ON,
            now=NOW,
        )
    )

    assert result is None


def test_qweather_jwt_uses_configured_ed25519_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    private_key = Ed25519PrivateKey.generate()
    pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    monkeypatch.setenv("WEATHER_DATA_PROVIDER", "qweather")
    monkeypatch.setenv("QWEATHER_API_HOST", "weather.example.test")
    monkeypatch.setenv("QWEATHER_CREDENTIAL_ID", "credential-1")
    monkeypatch.setenv("QWEATHER_DEVELOPER_ID", "developer-1")
    monkeypatch.setenv("QWEATHER_PROJECT_ID", "project-1")
    monkeypatch.setenv(
        "QWEATHER_PRIVATE_KEY_BASE64",
        base64.b64encode(pem).decode("ascii"),
    )
    get_settings.cache_clear()

    provider = QWeatherDataProvider()
    token = provider._jwt(now=NOW)
    encoded_header, encoded_payload, encoded_signature = token.split(".")
    header = json.loads(_decode_base64url(encoded_header))
    payload = json.loads(_decode_base64url(encoded_payload))

    assert provider.api_host == "https://weather.example.test"
    assert header == {"alg": "EdDSA", "kid": "credential-1"}
    assert payload["iss"] == "developer-1"
    assert payload["sub"] == "project-1"
    assert payload["exp"] - payload["iat"] == 900
    private_key.public_key().verify(
        _decode_base64url(encoded_signature),
        f"{encoded_header}.{encoded_payload}".encode("ascii"),
    )
