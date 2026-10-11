"""Seven-day forecasts shared by city; independent of the almanac toggle."""
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import utc_now
from app.db.models import Household, WeatherForecastCache
from app.services.weather import (
    WeatherForecast, _aware_utc, get_weather_data_provider, weather_provider_ready,
)
from app.settings import get_settings

LOCAL_ZONE = ZoneInfo("Asia/Shanghai")


@dataclass(frozen=True)
class WeatherWeek:
    city: str
    displayed_on: date
    days: tuple[WeatherForecast, ...]
    fetched_at: datetime | None
    delayed: bool = False


def cached_week(row: WeatherForecastCache | None, *, city: str,
                displayed_on: date, now: datetime) -> WeatherWeek:
    success = _aware_utc(row.last_success_at) if row else None
    attempt = _aware_utc(row.last_attempted_at) if row else None
    settings = get_settings()
    values = []
    if success and now - success <= timedelta(hours=settings.weather_stale_hours):
        for item in row.days or []:
            try:
                day = date.fromisoformat(item['displayed_on'])
                if displayed_on <= day < displayed_on + timedelta(days=7):
                    values.append(WeatherForecast(**{**item, 'displayed_on': day}))
            except (TypeError, KeyError, ValueError):
                continue
    delayed = (len(values) < 7 or not success or
               bool(attempt and attempt > success) or
               now - success >= timedelta(hours=settings.weather_refresh_hours))
    return WeatherWeek(city, displayed_on, tuple(sorted(values, key=lambda v: v.displayed_on)),
                       success, delayed)


async def load_weather_week(session: AsyncSession, household: Household, *,
                            displayed_on: date, now: datetime | None = None,
                            refresh: bool = True) -> WeatherWeek:
    now = _aware_utc(now or utc_now())
    city = household.weather_location_name or "未选择城市"
    if household.weather_latitude is None or household.weather_longitude is None:
        return WeatherWeek(city, displayed_on, (), None, True)
    settings = get_settings()
    key = f"{settings.weather_data_provider}:{household.weather_latitude:.2f}:{household.weather_longitude:.2f}"
    statement = select(WeatherForecastCache).where(WeatherForecastCache.cache_key == key)
    if refresh and weather_provider_ready():
        # A database row lock deduplicates simultaneous device/preview requests,
        # including requests served by different backend workers.
        insert = pg_insert if session.get_bind().dialect.name == 'postgresql' else sqlite_insert
        await session.execute(insert(WeatherForecastCache).values(cache_key=key, days=[])
                              .on_conflict_do_nothing(index_elements=['cache_key']))
        row = await session.scalar(statement.with_for_update().execution_options(populate_existing=True))
        attempt = _aware_utc(row.last_attempted_at)
        success = _aware_utc(row.last_success_at)
        failed = bool(attempt and (not success or attempt > success))
        retry_due = not attempt or now - attempt >= timedelta(minutes=settings.weather_failure_retry_minutes)
        normal_due = (not success or now - success >= timedelta(hours=settings.weather_refresh_hours)
                      or success.astimezone(LOCAL_ZONE).date() != displayed_on)
        if (retry_due if failed else normal_due):
            row.last_attempted_at = now
            try:
                days = await get_weather_data_provider().fetch_days(
                    latitude=household.weather_latitude, longitude=household.weather_longitude,
                    displayed_on=displayed_on, days=7)
                if not days:
                    raise ValueError('empty forecast')
                row.days = [{**asdict(v), 'displayed_on': v.displayed_on.isoformat()} for v in days]
                row.last_success_at = now
            except (httpx.HTTPError, ValueError, TypeError, KeyError, RuntimeError, OverflowError):
                # Do not overwrite valid cached data or expose credentials in logs.
                pass
            await session.flush()
    else:
        row = await session.scalar(statement)
    return cached_week(row, city=city, displayed_on=displayed_on, now=now)
