from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from io import BytesIO

from PIL import Image

from app.services.device_frame import FRAME_HEIGHT, FRAME_SIZE, FRAME_WIDTH, DeviceFrame


KINDLE_MODEL = "Kindle-Paperwhite-3"
KINDLE_WIDTH = 1072
KINDLE_HEIGHT = 1448
KINDLE_RENDER_VERSION = "v1"

# Preserve the semantic contrast of the four-color source on a grayscale panel.
# Red becomes dark gray, yellow becomes light gray, while black/white stay exact.
GRAY_CODES = {
    0b00: 17,
    0b01: 255,
    0b10: 184,
    0b11: 80,
}


@dataclass(frozen=True, slots=True)
class KindleFrame:
    data: bytes
    sha256: str
    version: str
    etag: str
    width: int = KINDLE_WIDTH
    height: int = KINDLE_HEIGHT


def decode_native_frame(frame: bytes) -> Image.Image:
    if len(frame) != FRAME_SIZE:
        raise ValueError(f"expected {FRAME_SIZE} bytes, got {len(frame)}")

    pixels = bytearray(FRAME_WIDTH * FRAME_HEIGHT)
    output_index = 0
    for packed in frame:
        pixels[output_index] = GRAY_CODES[(packed >> 6) & 0b11]
        pixels[output_index + 1] = GRAY_CODES[(packed >> 4) & 0b11]
        pixels[output_index + 2] = GRAY_CODES[(packed >> 2) & 0b11]
        pixels[output_index + 3] = GRAY_CODES[packed & 0b11]
        output_index += 4
    return Image.frombytes("L", (FRAME_WIDTH, FRAME_HEIGHT), bytes(pixels))


def render_kindle_frame(frame: DeviceFrame) -> KindleFrame:
    native = decode_native_frame(frame.data)
    if frame.orientation == "landscape":
        source = native
    else:
        source = native.transpose(Image.Transpose.ROTATE_270)

    scale = min(KINDLE_WIDTH / source.width, KINDLE_HEIGHT / source.height)
    rendered_size = (
        round(source.width * scale),
        round(source.height * scale),
    )
    rendered = source.resize(rendered_size, Image.Resampling.LANCZOS)
    canvas = Image.new("L", (KINDLE_WIDTH, KINDLE_HEIGHT), 255)
    canvas.paste(
        rendered,
        (
            (KINDLE_WIDTH - rendered.width) // 2,
            (KINDLE_HEIGHT - rendered.height) // 2,
        ),
    )

    output = BytesIO()
    canvas.save(output, format="PNG", optimize=True)
    data = output.getvalue()
    digest = sha256(data).hexdigest()
    version = f"kindle-pw3-{KINDLE_RENDER_VERSION}-{digest[:16]}"
    return KindleFrame(
        data=data,
        sha256=digest,
        version=version,
        etag=f'"{version}"',
    )
