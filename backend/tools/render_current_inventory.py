from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

from PIL import Image

from app.services.device_frame import (
    FRAME_HEIGHT,
    FRAME_WIDTH,
    load_inventory_frame,
)
from app.services.inventory_store import get_inventory_store


COLORS = {
    0b00: (17, 17, 17),
    0b01: (255, 255, 255),
    0b10: (224, 160, 0),
    0b11: (196, 43, 37),
}


def decode_frame(frame: bytes) -> Image.Image:
    image = Image.new("RGB", (FRAME_WIDTH, FRAME_HEIGHT))
    pixels = image.load()
    frame_index = 0
    for y in range(FRAME_HEIGHT):
        for x in range(0, FRAME_WIDTH, 4):
            packed = frame[frame_index]
            for offset in range(4):
                code = (packed >> (6 - offset * 2)) & 0b11
                pixels[x + offset, y] = COLORS[code]
            frame_index += 1
    return image


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Render the current persisted inventory frame as PNG.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("../docs/assets/current_inventory_preview.png"),
    )
    args = parser.parse_args()

    snapshot = get_inventory_store().snapshot()
    frame = load_inventory_frame(snapshot, date.today())
    image = decode_frame(frame.data)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    image.save(args.output, format="PNG", optimize=True)
    print(
        f"{args.output.resolve()} "
        f"revision={snapshot.revision} etag={frame.etag}"
    )


if __name__ == "__main__":
    main()
