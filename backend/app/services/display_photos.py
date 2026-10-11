from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from io import BytesIO

from PIL import Image, ImageOps, UnidentifiedImageError

from app.db.models import DisplayPhoto, DisplayPhotoStatus, Household
from app.services.display_renderer import (
    BLACK_RGB,
    PORTRAIT_HEIGHT,
    PORTRAIT_WIDTH,
    RED_RGB,
    WHITE_RGB,
    YELLOW_RGB,
)


ALLOWED_SOURCE_FORMATS = {"JPEG", "PNG"}
DISPLAY_PALETTE = (BLACK_RGB, WHITE_RGB, YELLOW_RGB, RED_RGB)


class DisplayPhotoProcessingError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ProcessedDisplayPhoto:
    png_bytes: bytes
    sha256: str
    width: int = PORTRAIT_WIDTH
    height: int = PORTRAIT_HEIGHT


def _open_source(data: bytes) -> Image.Image:
    try:
        source = Image.open(BytesIO(data))
        source.load()
    except (UnidentifiedImageError, OSError, ValueError) as error:
        raise DisplayPhotoProcessingError("invalid image file") from error
    if source.format not in ALLOWED_SOURCE_FORMATS:
        raise DisplayPhotoProcessingError("only JPG and PNG images are supported")
    return source


def _flatten_transparency(source: Image.Image) -> Image.Image:
    rgba = ImageOps.exif_transpose(source).convert("RGBA")
    background = Image.new("RGBA", rgba.size, (*WHITE_RGB, 255))
    background.alpha_composite(rgba)
    return background.convert("RGB")


def _center_crop_portrait(source: Image.Image) -> Image.Image:
    target_ratio = PORTRAIT_WIDTH / PORTRAIT_HEIGHT
    source_ratio = source.width / source.height
    if source_ratio > target_ratio:
        crop_width = max(1, round(source.height * target_ratio))
        left = (source.width - crop_width) // 2
        box = (left, 0, left + crop_width, source.height)
    else:
        crop_height = max(1, round(source.width / target_ratio))
        top = (source.height - crop_height) // 2
        box = (0, top, source.width, top + crop_height)
    return source.crop(box)


def _four_color_dither(source: Image.Image) -> Image.Image:
    palette_values: list[int] = []
    for color in DISPLAY_PALETTE:
        palette_values.extend(color)
    while len(palette_values) < 768:
        palette_values.extend(WHITE_RGB)
    palette = Image.new("P", (1, 1))
    palette.putpalette(palette_values[:768])
    return source.quantize(
        palette=palette,
        dither=Image.Dither.FLOYDSTEINBERG,
    ).convert("RGB")


def process_display_photo(data: bytes, *, max_bytes: int) -> ProcessedDisplayPhoto:
    if not data:
        raise DisplayPhotoProcessingError("image file is empty")
    if len(data) > max_bytes:
        raise DisplayPhotoProcessingError("image exceeds the 5 MB limit")

    source = _open_source(data)
    try:
        flattened = _flatten_transparency(source)
    finally:
        source.close()
    cropped = _center_crop_portrait(flattened)
    resized = cropped.resize(
        (PORTRAIT_WIDTH, PORTRAIT_HEIGHT),
        Image.Resampling.LANCZOS,
    )
    processed = _four_color_dither(resized)
    output = BytesIO()
    processed.save(output, format="PNG", optimize=True)
    png_bytes = output.getvalue()
    return ProcessedDisplayPhoto(
        png_bytes=png_bytes,
        sha256=sha256(png_bytes).hexdigest(),
    )


def photo_png_to_native_image(data: bytes) -> Image.Image:
    try:
        source = Image.open(BytesIO(data))
        source.load()
    except (UnidentifiedImageError, OSError, ValueError) as error:
        raise DisplayPhotoProcessingError("stored display photo is invalid") from error
    try:
        rgb = source.convert("RGB")
    finally:
        source.close()
    if rgb.size != (PORTRAIT_WIDTH, PORTRAIT_HEIGHT):
        raise DisplayPhotoProcessingError(
            f"stored display photo must be {PORTRAIT_WIDTH}x{PORTRAIT_HEIGHT}"
        )
    colors = rgb.getcolors(maxcolors=PORTRAIT_WIDTH * PORTRAIT_HEIGHT)
    if colors is None or {color for _, color in colors} - set(DISPLAY_PALETTE):
        raise DisplayPhotoProcessingError("stored display photo is not four-color")
    return rgb.transpose(Image.Transpose.ROTATE_90)


def active_display_photo(
    household: Household,
    photos: list[DisplayPhoto],
    *,
    now: datetime | None = None,
) -> DisplayPhoto | None:
    confirmed = [
        photo for photo in photos if photo.status == DisplayPhotoStatus.CONFIRMED
    ]
    if not confirmed:
        return None
    confirmed.sort(key=lambda photo: (photo.sequence, photo.created_at, photo.id))

    base_index = 0
    if household.active_display_photo_id:
        for index, photo in enumerate(confirmed):
            if photo.id == household.active_display_photo_id:
                base_index = index
                break

    started_at = household.photo_rotation_started_at
    if started_at is None:
        return confirmed[base_index]
    if started_at.tzinfo is None:
        started_at = started_at.replace(tzinfo=timezone.utc)
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    elapsed_seconds = max(0.0, (current - started_at).total_seconds())
    step_seconds = household.photo_rotation_hours * 60 * 60
    steps = int(elapsed_seconds // step_seconds)
    return confirmed[(base_index + steps) % len(confirmed)]
