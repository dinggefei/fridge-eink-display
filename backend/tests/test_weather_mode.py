from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from io import BytesIO
import asyncio

import httpx
import pytest
from PIL import Image
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from app.db.models import Household, WeatherForecastCache
from app.services.weather import QWeatherDataProvider, MockWeatherDataProvider, WeatherForecast
from app.services.weather_forecast import WeatherWeek, cached_week, load_weather_week
from app.services.weather_renderer import render_weather_image
from app.services.device_frame import load_weather_frame
from app.settings import get_settings
from app.services.wechat_login import WechatIdentity
from tests.test_household_inventory_api import database_client, _signed_frame_headers

DAY = date(2026, 9, 15)
NOW = datetime(2026, 9, 15, 0, tzinfo=timezone.utc)


def sample_week():
    return WeatherWeek('上海', DAY, tuple(WeatherForecast(DAY+timedelta(days=i),
        '午后阵雨' if i in (3,4) else '晴间多云',21+i%3,30,None) for i in range(7)), NOW)


def test_week_frame_palette_size_and_etag():
    week=sample_week()
    image=render_weather_image(week)
    assert image.size == (800,480)
    assert len(image.getcolors(384001)) <= 4
    frame=load_weather_frame(week)
    assert len(frame.data) == 96000
    assert frame.version.startswith('weather-v1-')
    assert frame.etag == load_weather_frame(week).etag
    assert frame.etag != load_weather_frame(replace(week,delayed=True)).etag
    assert frame.etag != load_weather_frame(replace(week,displayed_on=DAY+timedelta(days=1))).etag
    assert frame.etag != load_weather_frame(replace(week,city='北京')).etag
    assert len(load_weather_frame(replace(week,days=(),fetched_at=None,delayed=True)).data) == 96000


def test_cache_staleness_and_calendar_dates():
    row=WeatherForecastCache(cache_key='test', days=[dict(displayed_on=v.displayed_on.isoformat(),
        condition_text=v.condition_text,temp_min=v.temp_min,temp_max=v.temp_max,precip_probability=None)
        for v in sample_week().days],last_success_at=NOW,last_attempted_at=NOW)
    assert len(cached_week(row,city='上海',displayed_on=DAY,now=NOW).days) == 7
    next_day=cached_week(row,city='上海',displayed_on=DAY+timedelta(days=1),now=NOW+timedelta(hours=2))
    assert len(next_day.days) == 6
    assert next_day.days[0].displayed_on == DAY+timedelta(days=1)
    assert next_day.delayed
    expired=cached_week(row,city='上海',displayed_on=DAY,now=NOW+timedelta(hours=13))
    assert expired.days == () and expired.delayed


def test_shared_cache_failures_retry_and_city_change(tmp_path,monkeypatch):
    monkeypatch.setenv('WEATHER_DATA_PROVIDER','mock')
    get_settings.cache_clear()
    class Provider(MockWeatherDataProvider):
        calls=0
        failing=False
        async def fetch_days(self,**kwargs):
            self.calls+=1
            if self.failing: raise httpx.ConnectError('unavailable')
            return await super().fetch_days(**kwargs)
    provider=Provider()
    monkeypatch.setattr('app.services.weather_forecast.get_weather_data_provider',lambda:provider)
    async def run():
        engine=create_async_engine(f'sqlite+aiosqlite:///{tmp_path / "cache.db"}')
        async with engine.begin() as c:
            await c.run_sync(WeatherForecastCache.__table__.create)
        sessions=async_sessionmaker(engine,expire_on_commit=False)
        h=Household(name='test',admin_user_id='test',weather_location_name='上海',
                    weather_latitude=Decimal('31.23'),weather_longitude=Decimal('121.47'),
                    almanac_weather_enabled=False)
        async with sessions() as s:
            first=await load_weather_week(s,h,displayed_on=DAY,now=NOW)
            await s.commit()
            assert len(first.days)==7 and not first.delayed
        async with sessions() as s:
            await load_weather_week(s,h,displayed_on=DAY,now=NOW+timedelta(minutes=5))
            assert provider.calls==1
            provider.failing=True
            later=NOW+timedelta(hours=3)
            failed=await load_weather_week(s,h,displayed_on=DAY,now=later)
            assert len(failed.days)==7 and failed.delayed
            assert provider.calls==2
            await load_weather_week(s,h,displayed_on=DAY,now=later+timedelta(minutes=5))
            assert provider.calls==2
            await load_weather_week(s,h,displayed_on=DAY,now=later+timedelta(minutes=15))
            assert provider.calls==3
            h.weather_latitude=Decimal('39.90')
            h.weather_longitude=Decimal('116.40')
            h.weather_location_name='北京'
            changed=await load_weather_week(s,h,displayed_on=DAY,now=later)
            assert changed.days==() and changed.city=='北京'
            await s.commit()
        await engine.dispose()
    asyncio.run(run())


def test_qweather_parse_date_and_missing_probability():
    row={'forecastStartTime':'2026-09-14T22:00Z',
         'temperatureMin':{'value':21.2},'temperatureMax':{'value':30.1},
         'daytime':{'condition':{'text':'晴'}},'nighttime':{'condition':{'text':'多云'}}}
    parsed=QWeatherDataProvider._parse_day(row)
    assert parsed.displayed_on==DAY
    assert parsed.temp_min==21 and parsed.temp_max==30
    assert parsed.precip_probability is None
    assert parsed.condition_text=='晴转多云'


def test_qweather_fetch_seven_days_contract(monkeypatch):
    seen=[]
    def handle(request):
        seen.append(request)
        return httpx.Response(200,json={'days':[
            {'forecastStartTime':(DAY+timedelta(days=i)).isoformat()+'T06:00:00+08:00',
             'temperatureMin':{'value':20},'temperatureMax':{'value':30},
             'daytime':{'condition':{'text':'晴'}},'nighttime':{}} for i in range(7)]})
    real_client=httpx.AsyncClient
    monkeypatch.setattr('app.services.weather.httpx.AsyncClient',
        lambda **kw:real_client(transport=httpx.MockTransport(handle),**kw))
    provider=object.__new__(QWeatherDataProvider)
    provider.api_host='https://test.example'
    provider.timeout=2
    provider._headers=lambda: {'Authorization':'Bearer test-only'}
    days=asyncio.run(provider.fetch_days(latitude=Decimal('31.23'),longitude=Decimal('121.47'),displayed_on=DAY))
    assert len(days)==7 and days[0].displayed_on==DAY
    assert seen[0].url.params['days']=='7'
    assert seen[0].url.params['localTime']=='true'


def test_weather_mode_api_png_and_device_frame(database_client,monkeypatch):
    monkeypatch.setenv('WEATHER_DATA_PROVIDER','mock')
    get_settings.cache_clear()
    monkeypatch.setattr('app.api.display_settings.current_display_date',lambda:DAY)
    monkeypatch.setattr('app.main.current_display_date',lambda:DAY)
    monkeypatch.setattr('app.services.weather_forecast.utc_now',lambda:NOW)
    login=database_client.post('/v1/auth/dev-login',json={'nickname':'七日天气测试'}).json()
    auth={'Authorization':f"Bearer {login['access_token']}"}
    path=f"/v1/households/{login['current_household_id']}/display-settings"
    assert database_client.put(path,headers=auth,json={'display_mode':'weather'}).status_code==409
    location=database_client.get(path+'/weather-locations',headers=auth,params={'query':'上海'}).json()[0]
    saved=database_client.put(path+'/weather',headers=auth,json={'location':location})
    assert saved.status_code==200
    assert saved.json()['weather_enabled'] is False
    assert database_client.put(path,headers=auth,json={'display_mode':'weather'}).status_code==200
    assert database_client.get(path+'/weather-preview').status_code==401
    preview=database_client.get(path+'/weather-preview',headers=auth)
    assert preview.status_code==200
    assert Image.open(BytesIO(preview.content)).size==(480,800)
    assert preview.headers['cache-control']=='private, no-store'
    assert database_client.get('/v1/households/not-my-family/display-settings/weather-preview',headers=auth).status_code==404
    settings=get_settings()
    monkeypatch.setenv('DATABASE_INVENTORY_ENABLED','true')
    get_settings.cache_clear()
    frame_path=f'/v1/devices/{settings.device_code}/frame'
    def signed(nonce,etag=''):
        return _signed_frame_headers(device_code=settings.device_code,device_secret=settings.device_secret,nonce=nonce,etag=etag)
    frame=database_client.get(frame_path,headers=signed('weather-preview-frame-0001'))
    assert frame.status_code==200 and len(frame.content)==96000
    assert frame.headers['x-frame-version'].startswith('weather-v1-')
    unchanged=database_client.get(frame_path,headers=signed('weather-preview-frame-0002',frame.headers['etag']))
    assert unchanged.status_code==304
    assert database_client.put(path,headers=auth,json={'display_mode':'almanac'}).status_code==200
    assert database_client.get(path,headers=auth).json()['weather_enabled'] is False


def test_ordinary_member_can_set_weather_city_and_mode(database_client, monkeypatch):
    monkeypatch.setenv('WEATHER_DATA_PROVIDER', 'mock')
    get_settings.cache_clear()
    admin = database_client.post('/v1/auth/dev-login', json={'nickname': '管理员'}).json()
    auth = {'Authorization': f"Bearer {admin['access_token']}"}
    family = admin['current_household_id']
    invite = database_client.post(f'/v1/households/{family}/invitations', headers=auth).json()['code']
    async def exchange(code):
        return WechatIdentity(openid='weather-mode-member')
    monkeypatch.setattr('app.api.auth.exchange_login_code', exchange)
    member = database_client.post('/v1/auth/wechat', json={'code': 'weather-member'}).json()
    member_auth = {'Authorization': f"Bearer {member['access_token']}"}
    path = f'/v1/households/{family}/display-settings'
    assert database_client.get(path+'/weather-preview', headers=member_auth).status_code == 404
    assert database_client.post('/v1/households/join', headers=member_auth,
                                json={'invitation_code': invite}).status_code == 200
    city = database_client.get(path+'/weather-locations', headers=member_auth, params={'query':'上海'}).json()[0]
    assert database_client.put(path+'/weather', headers=member_auth, json={'location':city}).status_code == 200
    assert database_client.put(path, headers=member_auth, json={'display_mode':'weather'}).status_code == 200
    assert database_client.get(path, headers=auth).json()['display_mode'] == 'weather'
