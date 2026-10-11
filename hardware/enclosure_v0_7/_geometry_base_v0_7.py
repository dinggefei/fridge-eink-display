#!/usr/bin/env python3
"""Standalone geometry primitives and measured V0.7 baseline dimensions.

This module intentionally lives beside the V0.7 generator so the published
hardware package does not depend on any removed historical enclosure version.
All units are millimetres. Boolean operations use Manifold through trimesh.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
import shutil
import zipfile

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from shapely.geometry import box as shapely_box
import trimesh


ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "output"
PREVIEWS = ROOT / "previews"


P = {
    "case_width": 120.0,
    "case_height": 184.0,
    "corner_radius": 8.0,
    "front_face_thickness": 2.4,
    "front_feature_depth": 6.0,
    "rear_depth": 19.0,
    "assembled_thickness": 21.4,
    "rear_skin": 4.0,
    "rear_inner_width": 116.4,
    "rear_inner_height": 180.4,
    "rear_wall_min": 1.8,
    "carrier_width": 115.4,
    "carrier_height": 179.4,
    "carrier_thickness": 1.6,
    "carrier_fit_per_side": 0.5,
    "screen_body_width": 111.2,
    "screen_body_height": 170.2,
    "screen_pocket_width": 112.0,
    "screen_pocket_height": 171.0,
    "screen_window_width": 99.0,
    "screen_window_height": 164.0,
    "screen_locator_outer_width": 116.0,
    "screen_locator_outer_height": 175.0,
    "screen_locator_depth": 1.8,
    "battery_width": 94.0,
    "battery_height": 62.0,
    "battery_thickness": 10.0,
    "battery_center_x": 0.0,
    # Lift the battery away from the two lower case-fastener tubes.  The
    # 3.2 mm edge clearance is intentional: it accommodates the cell's taped
    # edge and prevents a hard screw boss from touching the pouch.
    "battery_center_y": -50.5,
    "esp_width": 25.4,
    "esp_height": 63.3,
    "esp_center_x": -42.0,
    "esp_center_y": 44.0,
    "esp_mount_pitch_x": 22.0,
    "esp_mount_pitch_y": 60.0,
    "esp_post_diameter": 5.8,
    "esp_post_top": 4.2,
    "esp_body_envelope": 8.0,
    "esp_pilot": 1.7,
    "esp_pilot_depth": 2.5,
    "despi_width": 42.0,
    "despi_height": 24.0,
    "despi_center_x": 29.0,
    "despi_center_y": 1.0,
    "despi_body_envelope": 4.0,
    "lipo_width": 25.48,
    "lipo_height": 40.877,
    "lipo_center_x": 5.461,
    "lipo_center_y": 67.4885,
    "lipo_post_diameter": 6.2,
    "lipo_post_top": 4.0,
    "lipo_body_envelope": 7.5,
    "lipo_pilot": 1.8,
    "case_fastener_pilot": 1.7,
    "case_fastener_clearance": 2.4,
    "case_fastener_post_diameter": 5.2,
    "case_fastener_tube_diameter": 6.4,
    "case_fastener_counterbore_diameter": 4.8,
    "case_fastener_counterbore_depth": 2.4,
    "case_fastener_length": 16.0,
    "magnet_diameter": 10.4,
    "magnet_depth": 3.2,
    "magnet_outer_skin": 0.8,
    "charge_cutout_width": 15.0,
    "charge_cutout_height": 8.0,
    "charge_cutout_center_x": 0.0,
    "charge_cutout_center_y": 91.0,
    "charge_cutout_center_z": 12.4,
    "button_access_diameter": 4.2,
    "button_counterbore_diameter": 7.2,
    "button_counterbore_depth": 1.0,
}


CASE_FASTENERS = [(-38.0, -87.9), (38.0, -87.9), (-38.0, 87.9), (38.0, 87.9)]
ESP_HOLES = [
    (P["esp_center_x"] + sx * P["esp_mount_pitch_x"] / 2.0,
     P["esp_center_y"] + sy * P["esp_mount_pitch_y"] / 2.0)
    for sy in (-1.0, 1.0)
    for sx in (-1.0, 1.0)
]

# Official Lipo Rider Plus Eagle hole coordinates, rotated -90 degrees so the
# USB-C input faces the compact shell's top-centre opening.
LIPO_BOARD_CENTRE_EAGLE = (20.4385, 15.24)
LIPO_MOUNT_HOLES_EAGLE = [
    (10.778, 25.567),
    (10.778, 5.040),
    (38.337, 25.567),
    (38.337, 5.040),
]


def lipo_to_carrier(x: float, y: float) -> tuple[float, float]:
    ex, ey = LIPO_BOARD_CENTRE_EAGLE
    return (
        P["lipo_center_x"] + (y - ey),
        P["lipo_center_y"] - (x - ex),
    )


LIPO_HOLES = [lipo_to_carrier(x, y) for x, y in LIPO_MOUNT_HOLES_EAGLE]
LIPO_USB_C_FACE = lipo_to_carrier(-0.873, 9.779)

BOOT_OFFSET = (-8.146, -29.095)
RESET_OFFSET = (7.242, -29.322)
BOARD_BOOT = (P["esp_center_x"] + BOOT_OFFSET[0], P["esp_center_y"] + BOOT_OFFSET[1])
BOARD_RESET = (P["esp_center_x"] + RESET_OFFSET[0], P["esp_center_y"] + RESET_OFFSET[1])
REAR_BOOT = (-BOARD_BOOT[0], BOARD_BOOT[1])
REAR_RESET = (-BOARD_RESET[0], BOARD_RESET[1])

# Installed/component-side projections.  Rear-model X coordinates are mirrored
# when the cover is closed.
MAGNETS_ASSEMBLED = [
    (-42.0, -74.0),
    (0.0, -74.0),
    (42.0, -74.0),
    (-50.0, -45.0),
    (0.0, -45.0),
    (50.0, -45.0),
    (-50.0, -15.0),
    (0.0, 25.0),
    (50.0, 35.0),
    (50.0, 65.0),
]
MAGNETS_MODEL = [(-x, y) for x, y in MAGNETS_ASSEMBLED]


def rounded_rect_polygon(width: float, height: float, radius: float):
    radius = max(0.0, min(radius, width / 2.0, height / 2.0))
    core = shapely_box(
        -width / 2.0 + radius,
        -height / 2.0 + radius,
        width / 2.0 - radius,
        height / 2.0 - radius,
    )
    return core.buffer(radius, quad_segs=12)


def rounded_prism(width, height, radius, depth, z0=0.0):
    mesh = trimesh.creation.extrude_polygon(
        rounded_rect_polygon(width, height, radius), depth, engine="earcut"
    )
    mesh.apply_translation((0.0, 0.0, z0))
    return mesh


def cuboid(size, center):
    mesh = trimesh.creation.box(extents=np.asarray(size, dtype=float))
    mesh.apply_translation(np.asarray(center, dtype=float))
    return mesh


def cylinder(radius, height, center, sections=48):
    mesh = trimesh.creation.cylinder(radius=radius, height=height, sections=sections)
    mesh.apply_translation(np.asarray(center, dtype=float))
    return mesh


def union(meshes):
    meshes = [mesh for mesh in meshes if mesh is not None]
    if len(meshes) == 1:
        return meshes[0]
    return trimesh.boolean.union(meshes, engine="manifold")


def difference(base, cutters):
    cutters = [cutter for cutter in cutters if cutter is not None]
    if not cutters:
        return base
    return trimesh.boolean.difference([base, *cutters], engine="manifold")


def intersection(meshes):
    return trimesh.boolean.intersection(meshes, engine="manifold")


def rounded_ring(outer_w, outer_h, outer_r, inner_w, inner_h, inner_r, depth, z0):
    outer = rounded_prism(outer_w, outer_h, outer_r, depth, z0)
    inner = rounded_prism(inner_w, inner_h, inner_r, depth + 0.4, z0 - 0.2)
    return difference(outer, [inner])


BITMAP_FONT_5X7 = {
    "B": ("11110", "10001", "10001", "11110", "10001", "10001", "11110"),
    "E": ("11111", "10000", "10000", "11110", "10000", "10000", "11111"),
    "O": ("01110", "10001", "10001", "10001", "10001", "10001", "01110"),
    "R": ("11110", "10001", "10001", "11110", "10100", "10010", "10001"),
    "S": ("01111", "10000", "10000", "01110", "00001", "00001", "11110"),
    "T": ("11111", "00100", "00100", "00100", "00100", "00100", "00100"),
}


def label_cutters(text: str, centre_x: float, centre_y: float):
    pixel = 0.38
    gap = 0.38
    depth = 0.42
    overlap = 0.04
    widths = [len(BITMAP_FONT_5X7[ch][0]) * pixel for ch in text]
    total = sum(widths) + gap * (len(text) - 1)
    cursor = centre_x - total / 2.0
    cutters = []
    for ch, char_width in zip(text, widths):
        bitmap = BITMAP_FONT_5X7[ch]
        for row, line in enumerate(bitmap):
            for column, value in enumerate(line):
                if value != "1":
                    continue
                model_x = cursor + column * pixel + pixel / 2.0
                model_y = centre_y + (3 - row) * pixel
                cutters.append(
                    cuboid(
                        (pixel + overlap, pixel + overlap, depth + 0.3),
                        (model_x, model_y, depth / 2.0),
                    )
                )
        cursor += char_width + gap
    return cutters


def build_front_bezel():
    face = rounded_prism(
        P["case_width"], P["case_height"], P["corner_radius"], P["front_face_thickness"]
    )
    window = rounded_prism(
        P["screen_window_width"], P["screen_window_height"], 2.0,
        P["front_face_thickness"] + 1.0, -0.5,
    )
    face = difference(face, [window])

    locator = rounded_ring(
        P["screen_locator_outer_width"], P["screen_locator_outer_height"], 5.0,
        P["screen_pocket_width"], P["screen_pocket_height"], 3.5,
        P["screen_locator_depth"], P["front_face_thickness"] - 0.2,
    )
    # The right-side internal tunnel lets the screen FPC fold behind the panel
    # without opening the exterior side wall.
    locator = difference(locator, [cuboid((8.0, 38.0, 3.0), (56.0, P["despi_center_y"], 3.1))])

    boss_bottom = P["front_face_thickness"] - 0.2
    boss_top = P["front_feature_depth"]
    bosses = [
        cylinder(
            P["case_fastener_post_diameter"] / 2.0,
            boss_top - boss_bottom,
            (x, y, (boss_bottom + boss_top) / 2.0),
            sections=48,
        )
        for x, y in CASE_FASTENERS
    ]
    body = union([face, locator, *bosses])
    pilots = [
        cylinder(
            P["case_fastener_pilot"] / 2.0,
            3.3,
            (x, y, 4.45),
            sections=40,
        )
        for x, y in CASE_FASTENERS
    ]
    return difference(body, pilots)


def short_guides(cx, cy, width, height):
    z = P["carrier_thickness"] + 1.25
    half_w, half_h = width / 2.0, height / 2.0
    return [
        cuboid((2.0, 16.0, 2.5), (cx - half_w - 1.0, cy, z)),
        cuboid((2.0, 16.0, 2.5), (cx + half_w + 1.0, cy, z)),
        cuboid((16.0, 2.0, 2.5), (cx - min(20.0, half_w - 8.0), cy - half_h - 1.0, z)),
        cuboid((16.0, 2.0, 2.5), (cx + min(20.0, half_w - 8.0), cy - half_h - 1.0, z)),
        cuboid((16.0, 2.0, 2.5), (cx - min(20.0, half_w - 8.0), cy + half_h + 1.0, z)),
        cuboid((16.0, 2.0, 2.5), (cx + min(20.0, half_w - 8.0), cy + half_h + 1.0, z)),
    ]


def mount_posts(holes, diameter, top):
    bottom = P["carrier_thickness"] - 0.2
    return [
        cylinder(diameter / 2.0, top - bottom, (x, y, (bottom + top) / 2.0), sections=48)
        for x, y in holes
    ]


def pilot_cutters(holes, diameter, depth, top):
    return [
        cylinder(diameter / 2.0, depth + 0.2, (x, y, top - depth / 2.0 + 0.1), sections=40)
        for x, y in holes
    ]


def build_carrier():
    base = rounded_prism(
        P["carrier_width"], P["carrier_height"], 6.0, P["carrier_thickness"]
    )
    # Battery and DESPI use shallow locating rails plus 0.5 mm EVA/VHB tape;
    # all rails remain below the 14 mm rear-cavity budget.
    battery_guides = short_guides(
        P["battery_center_x"], P["battery_center_y"],
        P["battery_width"], P["battery_height"],
    )
    despi_guides = short_guides(
        P["despi_center_x"], P["despi_center_y"],
        P["despi_width"], P["despi_height"],
    )
    body = union(
        [
            base,
            *battery_guides,
            *despi_guides,
            *mount_posts(ESP_HOLES, P["esp_post_diameter"], P["esp_post_top"]),
            *mount_posts(LIPO_HOLES, P["lipo_post_diameter"], P["lipo_post_top"]),
        ]
    )
    cutters = []
    # FPC opening reaches the carrier edge but remains behind the closed shell.
    cutters.append(cuboid((8.0, 38.0, 4.0), (56.0, P["despi_center_y"], 0.8)))
    for x, y in CASE_FASTENERS:
        cutters.append(
            cylinder(P["case_fastener_clearance"] / 2.0, 4.0, (x, y, 1.0), sections=40)
        )
    cutters.extend(
        pilot_cutters(ESP_HOLES, P["esp_pilot"], P["esp_pilot_depth"], P["esp_post_top"])
    )
    cutters.extend(
        pilot_cutters(LIPO_HOLES, P["lipo_pilot"], 2.3, P["lipo_post_top"])
    )
    # Internal cable-management slots; none reach an exterior wall.
    for x, y, w, h in [(-8.0, 4.0, 10.0, 3.0), (-8.0, 24.0, 10.0, 3.0),
                        (25.0, 30.0, 10.0, 3.0), (42.0, -18.0, 10.0, 3.0)]:
        cutters.append(cuboid((w, h, 4.0), (x, y, 0.8)))
    return difference(body, cutters)


def build_rear_cover():
    depth = P["rear_depth"]
    shell = rounded_prism(P["case_width"], P["case_height"], P["corner_radius"], depth)
    cavity = rounded_prism(
        P["rear_inner_width"], P["rear_inner_height"], 6.2,
        depth - P["rear_skin"] + 1.0, P["rear_skin"],
    )
    shell = difference(shell, [cavity])

    # A 1.6 mm internal ledge supports the carrier with 1.3 mm overlap per side.
    ledge = rounded_ring(
        P["rear_inner_width"], P["rear_inner_height"], 6.2,
        P["carrier_width"] - 2.6, P["carrier_height"] - 2.6, 5.0,
        1.6, depth - 1.6,
    )
    # Compression tubes stop at the front-bezel bosses; the carrier clearance
    # holes are sandwiched between them without carrying screw torque.
    tube_bottom = P["rear_skin"] - 0.2
    tube_top = P["assembled_thickness"] - P["front_feature_depth"]
    tubes = [
        cylinder(
            P["case_fastener_tube_diameter"] / 2.0,
            tube_top - tube_bottom,
            (x, y, (tube_bottom + tube_top) / 2.0),
            sections=48,
        )
        for x, y in CASE_FASTENERS
    ]
    body = union([shell, ledge, *tubes])

    cutters = []
    for x, y in CASE_FASTENERS:
        cutters.append(
            cylinder(P["case_fastener_clearance"] / 2.0, depth + 1.0, (x, y, depth / 2.0), sections=40)
        )
        cutters.append(
            cylinder(
                P["case_fastener_counterbore_diameter"] / 2.0,
                P["case_fastener_counterbore_depth"] + 0.2,
                (x, y, P["case_fastener_counterbore_depth"] / 2.0),
                sections=48,
            )
        )

    for x, y in MAGNETS_MODEL:
        cutters.append(
            cylinder(
                P["magnet_diameter"] / 2.0,
                P["magnet_depth"] + 0.2,
                (x, y, P["magnet_outer_skin"] + (P["magnet_depth"] + 0.2) / 2.0),
                sections=64,
            )
        )

    cutters.append(
        cuboid(
            (P["charge_cutout_width"], 6.0, P["charge_cutout_height"]),
            (P["charge_cutout_center_x"], P["charge_cutout_center_y"], P["charge_cutout_center_z"]),
        )
    )
    for x, y in (REAR_BOOT, REAR_RESET):
        cutters.append(cylinder(P["button_access_diameter"] / 2.0, 6.0, (x, y, 2.5), sections=48))
        cutters.append(
            cylinder(
                P["button_counterbore_diameter"] / 2.0,
                P["button_counterbore_depth"] + 0.2,
                (x, y, P["button_counterbore_depth"] / 2.0),
                sections=56,
            )
        )
    cutters.extend(label_cutters("BOOT", REAR_BOOT[0], REAR_BOOT[1] - 6.0))
    cutters.extend(label_cutters("RESET", REAR_RESET[0], REAR_RESET[1] - 6.0))
    return difference(body, cutters)


def available_assembled_carrier_height():
    """Space from the carrier underside/ledge to the rear inner skin."""
    return P["assembled_thickness"] - P["rear_skin"] - 4.0


def available_height_above_carrier():
    return available_assembled_carrier_height() - P["carrier_thickness"]


def build_depth_gauge():
    """Open-sided gauge for the complete populated-carrier height."""
    opening_height = available_assembled_carrier_height()
    outer_height = opening_height + 4.0
    outer = cuboid((42.0, 20.0, outer_height), (0.0, 0.0, outer_height / 2.0))
    opening = cuboid((39.6, 22.0, opening_height), (1.2, 0.0, outer_height / 2.0))
    return difference(outer, [opening])


def corner_coupon(mesh, x_min=25.0, y_min=55.0):
    cutter = cuboid((35.0, 37.0, 30.0), ((x_min + 60.0) / 2.0, (y_min + 92.0) / 2.0, 10.0))
    result = intersection([mesh, cutter])
    result.apply_translation(-result.bounds[0])
    return result


def ensure_mesh(name: str, mesh: trimesh.Trimesh):
    mesh.remove_unreferenced_vertices()
    mesh.fix_normals()
    if not mesh.is_watertight:
        raise RuntimeError(f"{name} is not watertight")
    if not mesh.is_volume:
        raise RuntimeError(f"{name} is not a valid positive volume")
    if len(mesh.split(only_watertight=False)) != 1:
        raise RuntimeError(f"{name} contains disconnected bodies")
    return mesh


def export_stl(name: str, mesh: trimesh.Trimesh):
    path = OUTPUT / f"{name}.stl"
    path.write_bytes(trimesh.exchange.stl.export_stl(mesh))
    return path


def part_info(path: Path):
    mesh = trimesh.load(path, force="mesh")
    return {
        "file": path.name,
        "watertight": bool(mesh.is_watertight),
        "is_volume": bool(mesh.is_volume),
        "body_count": len(mesh.split(only_watertight=False)),
        "size_mm": [round(float(value), 3) for value in mesh.extents],
        "volume_mm3": round(float(mesh.volume), 2),
    }


def rect_clearance(point, rect):
    x, y = point
    x0, x1, y0, y1 = rect
    dx = max(x0 - x, 0.0, x - x1)
    dy = max(y0 - y, 0.0, y - y1)
    return math.hypot(dx, dy) - P["magnet_diameter"] / 2.0


def clearance_report():
    esp = (
        P["esp_center_x"] - P["esp_width"] / 2.0,
        P["esp_center_x"] + P["esp_width"] / 2.0,
        P["esp_center_y"] - P["esp_height"] / 2.0,
        P["esp_center_y"] + P["esp_height"] / 2.0,
    )
    rectangles = {
        "esp32_board": esp,
        "esp32_antenna": (esp[0], esp[1], esp[3] - 15.0, esp[3]),
        "despi_c02": (
            P["despi_center_x"] - P["despi_width"] / 2.0,
            P["despi_center_x"] + P["despi_width"] / 2.0,
            P["despi_center_y"] - P["despi_height"] / 2.0,
            P["despi_center_y"] + P["despi_height"] / 2.0,
        ),
        "lipo_rider": (
            P["lipo_center_x"] - P["lipo_width"] / 2.0,
            P["lipo_center_x"] + P["lipo_width"] / 2.0,
            P["lipo_center_y"] - P["lipo_height"] / 2.0,
            P["lipo_center_y"] + P["lipo_height"] / 2.0,
        ),
    }
    result = {
        name: round(min(rect_clearance(point, rect) for point in MAGNETS_ASSEMBLED), 3)
        for name, rect in rectangles.items()
    }
    magnet_r = P["magnet_diameter"] / 2.0
    tube_r = P["case_fastener_tube_diameter"] / 2.0
    result["magnet_to_fastener_tube"] = round(
        min(math.dist(a, b) - magnet_r - tube_r for a in MAGNETS_MODEL for b in CASE_FASTENERS), 3
    )
    result["magnet_to_magnet"] = round(
        min(
            math.dist(a, b) - 2.0 * magnet_r
            for index, a in enumerate(MAGNETS_MODEL)
            for b in MAGNETS_MODEL[index + 1:]
        ),
        3,
    )
    return result


def load_font(size: int):
    for path in (
        "/System/Library/Fonts/PingFang.ttc",
        "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
    ):
        try:
            return ImageFont.truetype(path, size=size)
        except OSError:
            continue
    return ImageFont.load_default()


def draw_overview(path: Path):
    image = Image.new("RGB", (1800, 1250), "#f3f1eb")
    draw = ImageDraw.Draw(image)
    title = load_font(46)
    subtitle = load_font(26)
    label = load_font(22)
    small = load_font(18)
    draw.text((55, 35), "V0.6 紧凑封闭外壳设计", fill="#17352b", font=title)
    draw.text((58, 95), "120 × 184 × 21.4 mm｜竖屏｜隐藏磁铁｜底边完全封闭", fill="#52665f", font=subtitle)

    panels = [(55, 160, 560, 1050), (625, 160, 1130, 1050), (1195, 160, 1745, 1050)]
    for panel in panels:
        draw.rounded_rectangle(panel, radius=32, fill="#ffffff", outline="#d8ddd9", width=3)

    # Front exterior.
    x0, y0, x1, y1 = panels[0]
    scale = min((x1 - x0 - 80) / P["case_width"], (y1 - y0 - 110) / P["case_height"])
    cx, cy = (x0 + x1) / 2.0, (y0 + y1) / 2.0 + 15
    ow, oh = P["case_width"] * scale, P["case_height"] * scale
    draw.rounded_rectangle((cx - ow/2, cy - oh/2, cx + ow/2, cy + oh/2), radius=28,
                           fill="#f7f8f5", outline="#1e3b31", width=5)
    ww, wh = P["screen_window_width"] * scale, P["screen_window_height"] * scale
    draw.rounded_rectangle((cx - ww/2, cy - wh/2, cx + ww/2, cy + wh/2), radius=10,
                           fill="#e7e3d8", outline="#73766f", width=3)
    draw.text((x0 + 25, y0 + 20), "正面", fill="#17352b", font=subtitle)
    draw.text((x0 + 25, y1 - 55), "对称窄边框，无外露线束", fill="#52665f", font=label)

    # Rear exterior.
    x0, y0, x1, y1 = panels[1]
    cx, cy = (x0 + x1) / 2.0, (y0 + y1) / 2.0 + 15
    draw.rounded_rectangle((cx - ow/2, cy - oh/2, cx + ow/2, cy + oh/2), radius=28,
                           fill="#eef1ed", outline="#1e3b31", width=5)
    for x, y in CASE_FASTENERS:
        px, py = cx - x * scale, cy - y * scale
        draw.ellipse((px-8, py-8, px+8, py+8), fill="#c9ceca", outline="#5f6862", width=2)
    for text, (x, y) in (("BOOT", REAR_BOOT), ("RESET", REAR_RESET)):
        px, py = cx - x * scale, cy - y * scale
        draw.ellipse((px-10, py-10, px+10, py+10), fill="#f7f8f5", outline="#7d857f", width=2)
        text_box = draw.textbbox((0, 0), text, font=small)
        text_width = text_box[2] - text_box[0]
        draw.text((px-text_width/2, py+14), text, fill="#52665f", font=small)
    draw.text((x0 + 25, y0 + 20), "背面", fill="#17352b", font=subtitle)
    draw.text((x0 + 25, y1 - 55), "4 颗下沉螺丝，磁铁全部内藏", fill="#52665f", font=label)

    # Side stack.
    x0, y0, x1, y1 = panels[2]
    draw.text((x0 + 25, y0 + 20), "侧面剖面", fill="#17352b", font=subtitle)
    left, right = x0 + 70, x1 - 70
    top = y0 + 280
    unit = 24
    layers = [
        ("2.4 mm 前框", 2.4, "#d5e5dc"),
        ("屏幕 + EVA", 1.4, "#e7e3d8"),
        ("1.6 mm 器件托板", 1.6, "#e9d5b5"),
        ("11.8 mm 托板上方可用高度", 12.0, "#dbe7f0"),
        ("4.0 mm 后层/磁铁盲孔", 4.0, "#c7d1cc"),
    ]
    y = top
    for text_value, value, color in layers:
        h = max(28, value * unit)
        draw.rectangle((left, y, right, y+h), fill=color, outline="#66736d", width=2)
        draw.text((left+18, y+h/2-12), text_value, fill="#17352b", font=label)
        y += h
    draw.line((right+28, top, right+28, y), fill="#a33b34", width=4)
    draw.text((right-30, y+20), "整机 21.4 mm", fill="#a33b34", font=subtitle)
    draw.text((x0 + 25, y1 - 90), "顶部仅保留 USB-C 功能口", fill="#52665f", font=label)

    draw.rounded_rectangle((55, 1080, 1745, 1200), radius=24, fill="#e9f3ed", outline="#7ca08f", width=3)
    draw.text((85, 1105), "结构：薄前框 + 内嵌托板 + 连续后壳；三层由 4 颗 M2×16 mm 螺丝夹紧。", fill="#17352b", font=subtitle)
    draw.text((85, 1150), "外观开口：顶部 USB-C、BOOT/RESET 细孔、4 个下沉螺丝孔；底边和四周全封闭。", fill="#52665f", font=label)
    image.save(path)


def draw_layout(path: Path):
    width, height = 1250, 1750
    margin = 100
    scale = min((width - 2*margin)/P["case_width"], (height - 2*margin)/P["case_height"])
    image = Image.new("RGB", (width, height), "#f4f2ec")
    draw = ImageDraw.Draw(image)
    title = load_font(40)
    label = load_font(22)
    small = load_font(19)
    cx, cy = width/2, height/2

    def point(x, y):
        return cx + x*scale, cy - y*scale

    def rect(cx0, cy0, w, h, fill, outline, text_value):
        x0,y0=point(cx0-w/2,cy0+h/2); x1,y1=point(cx0+w/2,cy0-h/2)
        draw.rounded_rectangle((x0,y0,x1,y1),radius=12,fill=fill,outline=outline,width=4)
        box=draw.textbbox((0,0),text_value,font=label)
        draw.text(((x0+x1-box[2]+box[0])/2,(y0+y1-box[3]+box[1])/2),text_value,fill=outline,font=label)

    x0,y0=point(-P["case_width"]/2,P["case_height"]/2)
    x1,y1=point(P["case_width"]/2,-P["case_height"]/2)
    draw.rounded_rectangle((x0,y0,x1,y1),radius=40,fill="#fff",outline="#17352b",width=6)
    draw.text((45,30),"V0.6 封闭腔内布局",fill="#17352b",font=title)
    rect(P["battery_center_x"],P["battery_center_y"],P["battery_width"],P["battery_height"],"#fff0c9","#a36a00","806090 电池")
    rect(P["esp_center_x"],P["esp_center_y"],P["esp_width"],P["esp_height"],"#dceaf7","#315f8c","ESP32-S3")
    rect(P["despi_center_x"],P["despi_center_y"],P["despi_width"],P["despi_height"],"#d9f2e8","#28765e","DESPI-C02")
    rect(P["lipo_center_x"],P["lipo_center_y"],P["lipo_width"],P["lipo_height"],"#e8e0f3","#735497","Lipo Rider")
    antenna_y=P["esp_center_y"]+P["esp_height"]/2-7.5
    ax0,ay0=point(P["esp_center_x"]-P["esp_width"]/2,antenna_y+7.5)
    ax1,ay1=point(P["esp_center_x"]+P["esp_width"]/2,antenna_y-7.5)
    draw.rectangle((ax0,ay0,ax1,ay1),outline="#d9463e",width=5)
    for index,(x,y) in enumerate(MAGNETS_ASSEMBLED,1):
        px,py=point(x,y); r=P["magnet_diameter"]/2*scale
        draw.ellipse((px-r,py-r,px+r,py+r),fill="#c8cdd3",outline="#4b5563",width=3)
        draw.text((px-7,py-10),str(index),fill="#111827",font=small)
    for x,y in CASE_FASTENERS:
        px,py=point(x,y)
        draw.ellipse((px-6,py-6,px+6,py+6),fill="#fff",outline="#a33b34",width=3)
    report=clearance_report()
    draw.rectangle((45,1590,1205,1710),fill="#e9f3ed",outline="#7ca08f",width=3)
    draw.text((65,1610),f"磁铁净距：天线 {report['esp32_antenna']:.1f} / ESP32 {report['esp32_board']:.1f} / DESPI {report['despi_c02']:.1f} / Lipo {report['lipo_rider']:.1f} mm",fill="#17352b",font=label)
    draw.text((65,1650),"红圈为外壳夹紧螺丝；灰圈为后盖内藏磁铁的装配投影。",fill="#52665f",font=label)
    image.save(path)


def draw_placement_svg(path: Path):
    w, h = P["carrier_width"], P["carrier_height"]
    items = [f'<rect x="0.2" y="0.2" width="{w-0.4}" height="{h-0.4}" rx="6" fill="white" stroke="#111" stroke-width="0.35"/>']

    def svg_rect(cx, cy, width, height, colour, label):
        x=cx+w/2-width/2; y=h/2-cy-height/2
        return f'<rect x="{x:.3f}" y="{y:.3f}" width="{width:.3f}" height="{height:.3f}" fill="none" stroke="{colour}" stroke-width="0.35"/><text x="{x+1:.3f}" y="{y+3:.3f}" font-size="2.5">{label}</text>'

    items.extend([
        svg_rect(P["battery_center_x"],P["battery_center_y"],P["battery_width"],P["battery_height"],"#a36a00","806090"),
        svg_rect(P["esp_center_x"],P["esp_center_y"],P["esp_width"],P["esp_height"],"#315f8c","ESP32"),
        svg_rect(P["despi_center_x"],P["despi_center_y"],P["despi_width"],P["despi_height"],"#28765e","DESPI"),
        svg_rect(P["lipo_center_x"],P["lipo_center_y"],P["lipo_width"],P["lipo_height"],"#735497","LIPO"),
    ])
    for x,y in ESP_HOLES+LIPO_HOLES:
        items.append(f'<circle cx="{x+w/2:.3f}" cy="{h/2-y:.3f}" r="1" fill="none" stroke="#0b6fbd" stroke-width="0.3"/>')
    for x,y in CASE_FASTENERS:
        items.append(f'<circle cx="{x+w/2:.3f}" cy="{h/2-y:.3f}" r="1.2" fill="none" stroke="#a33b34" stroke-width="0.3"/>')
    svg=f'''<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="{w}mm" height="{h}mm" viewBox="0 0 {w} {h}">
  {''.join(items)}
  <text x="3" y="{h-3}" font-size="2.5">V0.6 CARRIER COMPONENT VIEW - PRINT 100% - TOP IS USB-C</text>
</svg>\n'''
    path.write_text(svg,encoding="utf-8")


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    PREVIEWS.mkdir(parents=True, exist_ok=True)

    front = ensure_mesh("front_bezel_v0_6", build_front_bezel())
    carrier = ensure_mesh("electronics_carrier_v0_6", build_carrier())
    rear = ensure_mesh("rear_cover_v0_6", build_rear_cover())
    depth_gauge = ensure_mesh("fit_test_13_4mm_assembled_height_v0_6", build_depth_gauge())
    front_corner = ensure_mesh("fit_test_front_corner_v0_6", corner_coupon(front))
    carrier_corner = ensure_mesh("fit_test_carrier_corner_v0_6", corner_coupon(carrier))
    rear_corner = ensure_mesh("fit_test_rear_corner_v0_6", corner_coupon(rear))

    meshes = {
        "front_bezel_v0_6": front,
        "electronics_carrier_v0_6": carrier,
        "rear_cover_v0_6": rear,
        "fit_test_13_4mm_assembled_height_v0_6": depth_gauge,
        "fit_test_front_corner_v0_6": front_corner,
        "fit_test_carrier_corner_v0_6": carrier_corner,
        "fit_test_rear_corner_v0_6": rear_corner,
    }
    paths = {name: export_stl(name, mesh) for name, mesh in meshes.items()}
    overview = PREVIEWS / "compact_enclosure_overview_v0_6.png"
    layout = PREVIEWS / "electronics_layout_v0_6.png"
    template = OUTPUT / "placement_template_v0_6_1to1.svg"
    draw_overview(overview)
    draw_layout(layout)
    draw_placement_svg(template)

    manifest = {
        "design": "FridgeEInkDisplay compact closed enclosure V0.6",
        "units": "mm",
        "status": "engineering prototype; print fit/depth coupons before full shell",
        "preserves": ["V0.5 remains unchanged", "existing screen, battery, ESP32, DESPI and Lipo Rider"],
        "target_outer_size": [P["case_width"], P["case_height"], P["assembled_thickness"]],
        "comparison_to_v0_5": {
            "v0_5_nominal": [128.0, 200.0, 29.0],
            "v0_6_nominal": [P["case_width"], P["case_height"], P["assembled_thickness"]],
            "width_reduction": 8.0,
            "height_reduction": 16.0,
            "thickness_reduction": 7.6,
        },
        "enclosure": {
            "architecture": "front bezel + nested electronics carrier + continuous rear shell",
            "bottom_and_sides": "fully closed",
            "functional_openings": ["top USB-C", "BOOT tool hole", "RESET tool hole", "four recessed rear fasteners"],
            "fasteners": "4 x M2 x 16 mm self-tapping, head diameter <= 4.6 mm, head height <= 1.5 mm",
            "fastener_engagement_in_front_boss": round(
                P["case_fastener_length"]
                - (P["assembled_thickness"] - P["case_fastener_counterbore_depth"] - P["front_feature_depth"]),
                3,
            ),
            "rear_cavity_depth": P["rear_depth"] - P["rear_skin"],
            "assembled_carrier_height": round(available_assembled_carrier_height(), 3),
            "usable_height_above_carrier": round(available_height_above_carrier(), 3),
        },
        "screen": {
            "body": [P["screen_body_width"], P["screen_body_height"]],
            "pocket": [P["screen_pocket_width"], P["screen_pocket_height"]],
            "window": [P["screen_window_width"], P["screen_window_height"]],
        },
        "components": {
            "battery_center": [P["battery_center_x"], P["battery_center_y"]],
            "esp32_center": [P["esp_center_x"], P["esp_center_y"]],
            "esp32_holes": [[round(x,3),round(y,3)] for x,y in ESP_HOLES],
            "despi_center": [P["despi_center_x"], P["despi_center_y"]],
            "lipo_center": [P["lipo_center_x"], P["lipo_center_y"]],
            "lipo_holes": [[round(x,3),round(y,3)] for x,y in LIPO_HOLES],
            "lipo_usb_c_face": [round(value,3) for value in LIPO_USB_C_FACE],
        },
        "buttons": {
            "board_boot": [round(value,3) for value in BOARD_BOOT],
            "board_reset": [round(value,3) for value in BOARD_RESET],
            "rear_boot_model": [round(value,3) for value in REAR_BOOT],
            "rear_reset_model": [round(value,3) for value in REAR_RESET],
        },
        "magnets": {
            "quantity": 10,
            "nominal": [10.0, 3.0],
            "pocket": [P["magnet_diameter"], P["magnet_depth"]],
            "assembled_centres": [[x,y] for x,y in MAGNETS_ASSEMBLED],
            "rear_model_centres": [[x,y] for x,y in MAGNETS_MODEL],
            "clearances": clearance_report(),
        },
        "parts": {name: part_info(path) for name, path in paths.items()},
        "previews": [overview.name, layout.name, "assembly_effect_v0_6.png"],
        "templates": [template.name],
        "parameters": P,
    }
    manifest_path = OUTPUT / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    package = ROOT / "RFM_enclosure_v0_6_STL.zip"
    with zipfile.ZipFile(package, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in paths.values():
            archive.write(path, path.name)
        archive.write(manifest_path, manifest_path.name)
        archive.write(template, template.name)
        archive.write(overview, overview.name)
        archive.write(layout, layout.name)
        assembly_effect = PREVIEWS / "assembly_effect_v0_6.png"
        if assembly_effect.exists():
            archive.write(assembly_effect, assembly_effect.name)
        archive.write(ROOT / "README.md", "README.md")

    package_dir = ROOT / "RFM_enclosure_v0_6_STL"
    package_dir.mkdir(parents=True, exist_ok=True)
    for obsolete in (
        OUTPUT / "fit_test_14mm_depth_v0_6.stl",
        package_dir / "fit_test_14mm_depth_v0_6.stl",
    ):
        obsolete.unlink(missing_ok=True)
    generated_files = [*paths.values(), manifest_path, template, overview, layout, ROOT / "README.md"]
    assembly_effect = PREVIEWS / "assembly_effect_v0_6.png"
    if assembly_effect.exists():
        generated_files.append(assembly_effect)
    for path in generated_files:
        shutil.copy2(path, package_dir / path.name)
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
