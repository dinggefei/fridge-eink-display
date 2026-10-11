from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from functools import lru_cache
from hashlib import sha256
from pathlib import Path

from PIL import Image

from app.domain.inventory import (
    FoodBatch,
    calculate_food_status,
    describe_food_status,
    sort_batches_for_display,
)
from app.services.almanac import ALMANAC_CALCULATION_VERSION, calculate_almanac
from app.services.display_renderer import (
    DisplayFoodItem,
    render_almanac_image,
    render_display_image,
    render_market_image,
)
from app.services.market_data import MarketSnapshot
from app.services.weather import WeatherSummary
from app.services.timetable_renderer import TIMETABLE_RENDER_VERSION, render_timetable_image
from app.services.display_photos import photo_png_to_native_image
from app.services.inventory_store import InventorySnapshot


PANEL_MODEL = "GDEM075F53"
DISPLAY_ORIENTATION = "portrait"
FRAME_WIDTH = 800
FRAME_HEIGHT = 480
FRAME_SIZE = FRAME_WIDTH * FRAME_HEIGHT // 4
ALMANAC_RENDER_VERSION = "v2"
MARKET_RENDER_VERSION = "v1"

# Two-bit values confirmed by the physical GDEM075F53 bring-up test.
WIRE_CODES = {
    (17, 17, 17): 0b00,       # black
    (255, 255, 255): 0b01,    # white
    (224, 160, 0): 0b10,      # yellow
    (196, 43, 37): 0b11,      # red
}

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEMO_IMAGE_PATH = PROJECT_ROOT / "docs/assets/screen_preview_f53.png"


@dataclass(frozen=True, slots=True)
class DeviceFrame:
    data: bytes
    sha256: str
    version: str
    etag: str
    orientation: str = DISPLAY_ORIENTATION


def encode_f53(image: Image.Image) -> bytes:
    rgb = image.convert("RGB")
    if rgb.size != (FRAME_WIDTH, FRAME_HEIGHT):
        raise ValueError(
            f"expected {FRAME_WIDTH}x{FRAME_HEIGHT}, "
            f"got {rgb.size[0]}x{rgb.size[1]}"
        )

    color_counts = rgb.getcolors(maxcolors=FRAME_WIDTH * FRAME_HEIGHT)
    if color_counts is None:
        raise ValueError("image contains too many colors")
    unknown = {color for _, color in color_counts} - set(WIRE_CODES)
    if unknown:
        raise ValueError(
            f"image contains unsupported colors: {sorted(unknown)[:5]}"
        )

    frame = bytearray(FRAME_SIZE)
    pixels = rgb.load()
    frame_index = 0
    for y in range(FRAME_HEIGHT):
        for x in range(0, FRAME_WIDTH, 4):
            frame[frame_index] = (
                (WIRE_CODES[pixels[x, y]] << 6)
                | (WIRE_CODES[pixels[x + 1, y]] << 4)
                | (WIRE_CODES[pixels[x + 2, y]] << 2)
                | WIRE_CODES[pixels[x + 3, y]]
            )
            frame_index += 1

    return bytes(frame)


@lru_cache(maxsize=1)
def load_demo_frame() -> DeviceFrame:
    with Image.open(DEMO_IMAGE_PATH) as image:
        data = encode_f53(image)

    digest = sha256(data).hexdigest()
    version = f"demo-{digest[:16]}"
    return DeviceFrame(
        data=data,
        sha256=digest,
        version=version,
        etag=f'"{version}"',
    )


@lru_cache(maxsize=32)
def load_inventory_frame(
    snapshot: InventorySnapshot,
    displayed_on: date,
    mini_program_code_png: bytes | None = None,
) -> DeviceFrame:
    item_by_id = {item.id: item for item in snapshot.items}
    batches = [
        FoodBatch(
            batch_id=item.id,
            name=item.name,
            quantity=item.quantity,
            unit=item.unit,
            location=item.location,
            stocked_on=item.stocked_on,
            suggested_use_by=item.suggested_use_by,
        )
        for item in snapshot.items
    ]
    ordered = sort_batches_for_display(batches, today=displayed_on)
    display_items = []
    for batch in ordered:
        item = item_by_id[batch.batch_id]
        display_items.append(
            DisplayFoodItem(
                name=item.name,
                quantity_text=(
                    f"{format(item.quantity.normalize(), 'f')} {item.unit}"
                ),
                status=calculate_food_status(
                    item.suggested_use_by,
                    today=displayed_on,
                ),
                status_text=describe_food_status(
                    item.suggested_use_by,
                    today=displayed_on,
                ),
            )
        )

    image = render_display_image(
        household_name=snapshot.household_name,
        items=display_items,
        rendered_at=snapshot.updated_at,
        displayed_on=displayed_on,
        mini_program_code_png=mini_program_code_png,
        display_todos=snapshot.display_todos,
    )
    data = encode_f53(image)
    digest = sha256(data).hexdigest()
    version = f"inventory-{digest[:16]}"
    return DeviceFrame(
        data=data,
        sha256=digest,
        version=version,
        etag=f'"{version}"',
    )


@lru_cache(maxsize=64)
def load_almanac_frame(
    displayed_on: date,
    weather: WeatherSummary | None = None,
) -> DeviceFrame:
    image = render_almanac_image(calculate_almanac(displayed_on), weather)
    data = encode_f53(image)
    digest = sha256(data).hexdigest()
    algorithm = ALMANAC_CALCULATION_VERSION.replace("lunar-python-", "lp")
    version = (
        f"almanac-{ALMANAC_RENDER_VERSION}-"
        f"{displayed_on.strftime('%Y%m%d')}-"
        f"{algorithm}-{digest[:12]}"
    )
    return DeviceFrame(
        data=data,
        sha256=digest,
        version=version,
        etag=f'"{version}"',
    )


def load_weather_frame(week) -> DeviceFrame:
    from app.services.weather_renderer import render_weather_image
    data = encode_f53(render_weather_image(week))
    digest = sha256(data).hexdigest()
    version = f"weather-v1-{digest[:16]}"
    return DeviceFrame(data=data, sha256=digest, version=version, etag=f'"{version}"')


def load_timetable_frame(periods, entries, *, orientation="portrait", now=None) -> DeviceFrame:
    data = encode_f53(
        render_timetable_image(periods, entries, orientation=orientation, now=now)
    )
    digest = sha256(data).hexdigest()
    version = f"timetable-{TIMETABLE_RENDER_VERSION}-{digest[:16]}"
    return DeviceFrame(
        data=data,
        sha256=digest,
        version=version,
        etag=f'"{version}"',
        orientation=orientation,
    )


@lru_cache(maxsize=8)
def load_album_frame(photo_png: bytes) -> DeviceFrame:
    image = photo_png_to_native_image(photo_png)
    data = encode_f53(image)
    digest = sha256(data).hexdigest()
    version = f"photo-{digest[:16]}"
    return DeviceFrame(
        data=data,
        sha256=digest,
        version=version,
        etag=f'"{version}"',
    )


@lru_cache(maxsize=32)
def load_market_frame(snapshot: MarketSnapshot) -> DeviceFrame:
    image = render_market_image(snapshot)
    data = encode_f53(image)
    digest = sha256(data).hexdigest()
    version = f"market-{MARKET_RENDER_VERSION}-{digest[:16]}"
    return DeviceFrame(
        data=data,
        sha256=digest,
        version=version,
        etag=f'"{version}"',
    )
