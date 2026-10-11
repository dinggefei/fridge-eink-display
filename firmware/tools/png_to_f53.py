#!/usr/bin/env python3
"""Convert an exact four-color 800x480 PNG into a GDEM075F53 native frame."""

from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image


WIDTH = 800
HEIGHT = 480
FRAME_SIZE = WIDTH * HEIGHT // 4

# Two-bit wire codes confirmed by the GDEM075F53/JD79665CA official sample
# and the physical four-color bring-up test.
WIRE_CODES = {
    (17, 17, 17): 0b00,       # black
    (255, 255, 255): 0b01,    # white
    (224, 160, 0): 0b10,      # yellow
    (196, 43, 37): 0b11,      # red
}


def encode(image: Image.Image) -> bytes:
    rgb = image.convert("RGB")
    if rgb.size != (WIDTH, HEIGHT):
        raise ValueError(f"expected {WIDTH}x{HEIGHT}, got {rgb.size[0]}x{rgb.size[1]}")

    color_counts = rgb.getcolors(maxcolors=WIDTH * HEIGHT)
    if color_counts is None:
        raise ValueError("image contains more colors than the panel palette supports")
    unknown = {color for _, color in color_counts} - set(WIRE_CODES)
    if unknown:
        sample = sorted(unknown)[:5]
        raise ValueError(f"image contains unsupported colors, for example: {sample}")

    frame = bytearray()
    pixels = rgb.load()
    for y in range(HEIGHT):
        for x in range(0, WIDTH, 4):
            packed = 0
            for offset in range(4):
                packed |= WIRE_CODES[pixels[x + offset, y]] << (6 - 2 * offset)
            frame.append(packed)

    if len(frame) != FRAME_SIZE:
        raise AssertionError(f"expected {FRAME_SIZE} bytes, generated {len(frame)}")
    return bytes(frame)


def write_header(frame: bytes, output: Path) -> None:
    lines = [
        "#pragma once",
        "",
        "#include <Arduino.h>",
        "",
        f"constexpr size_t kPreviewFrameSize = {len(frame)};",
        "const uint8_t kPreviewFrame[kPreviewFrameSize] PROGMEM = {",
    ]
    for start in range(0, len(frame), 16):
        chunk = frame[start : start + 16]
        lines.append("    " + ", ".join(f"0x{value:02X}" for value in chunk) + ",")
    lines.extend(["};", ""])
    output.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("input_png", type=Path)
    parser.add_argument("output_bin", type=Path)
    parser.add_argument("output_header", type=Path)
    args = parser.parse_args()

    with Image.open(args.input_png) as image:
        frame = encode(image)

    args.output_bin.parent.mkdir(parents=True, exist_ok=True)
    args.output_header.parent.mkdir(parents=True, exist_ok=True)
    args.output_bin.write_bytes(frame)
    write_header(frame, args.output_header)
    print(f"generated {len(frame)} bytes")


if __name__ == "__main__":
    main()
