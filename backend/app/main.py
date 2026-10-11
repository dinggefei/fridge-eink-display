from fastapi import FastAPI, Request, Response
from sqlalchemy import select
import time

from app.api.auth import router as auth_router
from app.api.dependencies import DbSession
from app.api.devices import (
    device_router,
    household_router as household_device_router,
)
from app.api.display_album import router as display_album_router
from app.api.display_market import router as display_market_router
from app.api.display_settings import router as display_settings_router
from app.api.display_timetable import router as display_timetable_router
from app.api.device_ota import router as device_ota_router
from app.api.household_inventory import router as household_inventory_router
from app.api.households import router as households_router
from app.api.inventory import router as inventory_router
from app.api.privacy import router as privacy_router
from app.api.recognition import router as recognition_router
from app.api.reminders import router as reminders_router
from app.api.shelf_life import router as shelf_life_router
from app.db.models import (
    Device,
    DisplayMode,
    DisplayPhoto,
    DisplayPhotoStatus,
    Household,
)
from app.services.database_inventory import load_household_inventory_snapshot
from app.services.device_auth import verify_device_request
from app.services.device_ota import (
    OTA_CAPABILITY_HEADER,
    OTA_CAPABILITY_VERSION,
    firmware_offer_headers,
    select_firmware_release,
)
from app.services.device_frame import (
    DISPLAY_ORIENTATION,
    PANEL_MODEL,
    DeviceFrame,
    load_demo_frame,
    load_album_frame,
    load_almanac_frame,
    load_inventory_frame,
    load_market_frame,
    load_timetable_frame,
    load_weather_frame,
)
from app.services.display_photo_storage import get_display_photo_storage
from app.services.display_photos import active_display_photo
from app.services.display_renderer import current_display_date
from app.services.inventory_store import get_inventory_store
from app.services.kindle_frame import KINDLE_MODEL, KindleFrame, render_kindle_frame
from app.services.market_data import load_market_snapshot
from app.services.weather import load_weather_summary
from app.services.weather_forecast import load_weather_week
from app.settings import get_settings


app = FastAPI(
    title="FridgeEInkDisplay API",
    version="0.1.0",
)
app.include_router(auth_router)
app.include_router(household_device_router)
app.include_router(device_router)
app.include_router(device_ota_router)
app.include_router(display_album_router)
app.include_router(display_market_router)
app.include_router(display_settings_router)
app.include_router(display_timetable_router)
app.include_router(household_inventory_router)
app.include_router(households_router)
app.include_router(inventory_router)
app.include_router(privacy_router)
app.include_router(recognition_router)
app.include_router(reminders_router)
app.include_router(shelf_life_router)


@app.get("/health", tags=["system"])
def health() -> dict[str, str]:
    return {
        "service": "fridge-eink-display",
        "status": "ok",
    }


@app.get("/v1/device-time", tags=["system"], response_class=Response)
def device_time() -> Response:
    """Return a fresh Unix timestamp for devices with an unreliable RTC."""
    return Response(
        content=f"{int(time.time())}\n",
        media_type="text/plain",
        headers={"Cache-Control": "no-store"},
    )


@app.get(
    "/v1/bringup/frame",
    tags=["bringup"],
    response_class=Response,
    responses={
        200: {
            "content": {"application/octet-stream": {}},
            "description": "GDEM075F53 native four-color frame",
        },
        304: {"description": "Frame has not changed"},
    },
)
def get_bringup_frame(request: Request) -> Response:
    """Serve a known-good frame during local hardware integration.

    This intentionally unauthenticated endpoint is for a trusted development
    LAN only. The production device endpoint will require an HMAC signature.
    """
    frame = load_demo_frame()
    return _frame_response(request, frame)


@app.get(
    "/v1/devices/{device_code}/frame",
    tags=["device"],
    response_class=Response,
    responses={
        200: {
            "content": {"application/octet-stream": {}},
            "description": "Authenticated GDEM075F53 native frame",
        },
        304: {"description": "Frame has not changed"},
        401: {"description": "Device authentication failed"},
    },
)
async def get_device_frame(
    device_code: str,
    request: Request,
    session: DbSession,
) -> Response:
    device = await verify_device_request(request, device_code, session)
    snapshot = get_inventory_store().snapshot()
    frame: DeviceFrame | None = None
    displayed_on = current_display_date()
    ota_headers: dict[str, str] = {}
    if get_settings().database_inventory_enabled:
        if device is None or device.household_id is None:
            return Response(
                status_code=409,
                content="device is not bound to a household",
                headers={"X-Device-State": "unbound"},
            )
        household = await session.get(Household, device.household_id)
        if household is None:
            return Response(
                status_code=409,
                content="device household no longer exists",
            )
        display_mode = device.display_mode_override or household.display_mode
        if display_mode == DisplayMode.ALMANAC:
            weather = await load_weather_summary(
                session,
                household,
                displayed_on=displayed_on,
            )
            frame = load_almanac_frame(displayed_on, weather)
        elif display_mode == DisplayMode.WEATHER:
            frame = load_weather_frame(await load_weather_week(
                session, household, displayed_on=displayed_on))
        elif display_mode == DisplayMode.MARKET:
            frame = load_market_frame(
                await load_market_snapshot(session, household)
            )
        elif display_mode == DisplayMode.TIMETABLE:
            frame = load_timetable_frame(
                household.timetable_periods,
                household.timetable_entries,
                orientation=household.timetable_orientation,
            )
        elif display_mode == DisplayMode.ALBUM:
            photos = list(
                await session.scalars(
                    select(DisplayPhoto)
                    .where(
                        DisplayPhoto.household_id == household.id,
                        DisplayPhoto.status == DisplayPhotoStatus.CONFIRMED,
                    )
                    .order_by(DisplayPhoto.sequence, DisplayPhoto.created_at)
                )
            )
            active_photo = active_display_photo(household, photos)
            if active_photo is not None:
                try:
                    photo_png = await get_display_photo_storage().get(
                        active_photo.object_key
                    )
                    frame = load_album_frame(photo_png)
                except Exception:
                    return Response(
                        status_code=503,
                        content="display photo storage is temporarily unavailable",
                )
        if (
            request.headers.get(OTA_CAPABILITY_HEADER)
            == OTA_CAPABILITY_VERSION
        ):
            ota_headers = firmware_offer_headers(
                await select_firmware_release(session, device),
                device.device_code,
            )
        if frame is None:
            snapshot = await load_household_inventory_snapshot(session, household)
        await session.commit()
    if frame is None:
        frame = load_inventory_frame(
            snapshot,
            displayed_on,
            device.mini_program_code_png if device is not None else None,
        )
    if request.query_params.get("format") == "kindle-pw3":
        return _kindle_frame_response(request, render_kindle_frame(frame))
    return _frame_response(request, frame, ota_headers)


def _kindle_frame_response(request: Request, frame: KindleFrame) -> Response:
    headers = {
        "ETag": frame.etag,
        "X-Frame-Version": frame.version,
        "X-Frame-SHA256": frame.sha256,
        "X-Panel-Model": KINDLE_MODEL,
        "X-Display-Orientation": "portrait",
        "X-Image-Width": str(frame.width),
        "X-Image-Height": str(frame.height),
    }
    if request.headers.get("if-none-match") == frame.etag:
        return Response(status_code=304, headers=headers)
    return Response(content=frame.data, media_type="image/png", headers=headers)


def _frame_response(
    request: Request,
    frame: DeviceFrame,
    extra_headers: dict[str, str] | None = None,
) -> Response:
    common_headers = {
        "ETag": frame.etag,
        "X-Frame-Version": frame.version,
        "X-Frame-SHA256": frame.sha256,
        "X-Panel-Model": PANEL_MODEL,
        "X-Display-Orientation": frame.orientation,
    }
    common_headers.update(extra_headers or {})
    if request.headers.get("if-none-match") == frame.etag:
        return Response(status_code=304, headers=common_headers)

    return Response(
        content=frame.data,
        media_type="application/octet-stream",
        headers=common_headers,
    )
