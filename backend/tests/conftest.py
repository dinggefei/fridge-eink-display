from __future__ import annotations

import os

# The public test suite must run without a developer's private .env file.
os.environ.setdefault("DEVICE_CODE", "rfm-test-001")
os.environ.setdefault("DEVICE_SECRET", "0" * 64)

import pytest

from app.settings import get_settings
from app.services.display_photo_storage import get_display_photo_storage
from app.services.market_data import get_market_data_provider
from app.services.weather import get_weather_data_provider


@pytest.fixture(autouse=True)
def isolate_tests_from_live_database(
    monkeypatch: pytest.MonkeyPatch,
):
    """Unit tests must never depend on the developer's live PostgreSQL state."""
    monkeypatch.setenv("DATABASE_INVENTORY_ENABLED", "false")
    get_settings.cache_clear()
    get_display_photo_storage.cache_clear()
    get_market_data_provider.cache_clear()
    get_weather_data_provider.cache_clear()
    yield
    get_weather_data_provider.cache_clear()
    get_market_data_provider.cache_clear()
    get_display_photo_storage.cache_clear()
    get_settings.cache_clear()
