#!/usr/bin/env python3
"""Generate the V0.3 carrier, rear cover, and low-cost fit coupon.

V0.3 follows the physical placement approved from the 2026-08-15 reference
photo.  The front bezel remains the proven V0.1 part.  Coordinates are in
millimetres, with (0, 0) at the centre of the 123 x 195 mm carrier, +Y toward
the enclosure top, and +X toward the display-FPC edge.

The Seeed Lipo Rider Plus outline and mounting-hole coordinates come from the
official Eagle board file.  The board is rotated so its USB-C input faces the
top wall.  Its centre is offset horizontally so the *connector*, rather than
the PCB centre, is exactly on the enclosure centreline.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import zipfile

import numpy as np
from PIL import Image, ImageDraw, ImageFont
import trimesh


ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "output"
PREVIEWS = ROOT / "previews"
V01_FILE = ROOT.parent / "enclosure_v0_1" / "generate_enclosure.py"


def load_v01_module():
    spec = importlib.util.spec_from_file_location("rfm_enclosure_v01", V01_FILE)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load V0.1 generator: {V01_FILE}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


v01 = load_v01_module()
P = dict(v01.P)
P.update(
    {
        # Approved V0.3 layout.  The battery envelope includes protection PCB,
        # edge tape, and 1-2 mm handling clearance around a nominal 806090 cell.
        "battery_width": 94.0,
        "battery_height": 62.0,
        "battery_center_x": 3.0,
        "battery_center_y": -58.0,
        "esp_width": 27.0,
        "esp_height": 65.0,
        "esp_center_x": -14.5,
        "esp_center_y": 20.0,
        "despi_width": 42.0,
        "despi_height": 24.0,
        "despi_center_x": 27.0,
        "despi_center_y": -6.0,
        # Official Lipo Rider Plus PCB outline after rotation: 25.48 x 40.877.
        "lipo_rider_width": 25.48,
        "lipo_rider_height": 40.877,
        # USB-C face is 5.461 mm left of the rotated board centre and
        # 21.3115 mm above it.  These values place the connector at (0, 97).
        "lipo_rider_center_x": 5.461,
        "lipo_rider_center_y": 75.6885,
        "lipo_mount_post_top": 4.4,
        "lipo_mount_pilot": 1.8,
        # Rear-cover cavity.  Kept as parameters so later tolerance revisions
        # can change the slip fit without changing the proven outer envelope.
        "rear_inner_width": 123.8,
        "rear_inner_height": 195.8,
        # New rear-cover top-centre charge opening.
        "charge_cutout_width": 16.0,
        "charge_cutout_height": 9.0,
        "charge_cutout_center_x": 0.0,
        "charge_cutout_center_y": 99.0,
        "charge_cutout_center_z": 15.0,
    }
)
v01.P = P


FRONT_FASTENERS = list(v01.FRONT_FASTENERS)
REAR_FASTENERS = list(v01.REAR_FASTENERS)
MAGNETS = list(v01.MAGNETS)


# Official Eagle coordinates, transformed by -90 degrees so USB-C faces +Y.
LIPO_BOARD_CENTRE_EAGLE = (20.4385, 15.24)
LIPO_MOUNT_HOLES_EAGLE = [
    (10.778, 25.567),
    (10.778, 5.040),
    (38.337, 25.567),
    (38.337, 5.040),
]


def lipo_to_carrier(x: float, y: float) -> tuple[float, float]:
    """Rotate Eagle coordinates -90 degrees and translate to the carrier."""
    ex, ey = LIPO_BOARD_CENTRE_EAGLE
    return (
        P["lipo_rider_center_x"] + (y - ey),
        P["lipo_rider_center_y"] - (x - ex),
    )


LIPO_MOUNT_HOLES = [lipo_to_carrier(x, y) for x, y in LIPO_MOUNT_HOLES_EAGLE]
LIPO_USB_C_CENTRE = lipo_to_carrier(6.477, 9.779)
LIPO_USB_C_FACE = lipo_to_carrier(-0.873, 9.779)


def cuboid(size, center):
    return v01.cuboid(size, center)


def cylinder(radius, height, center, sections=48):
    return v01.cylinder(radius, height, center, sections=sections)


def union(meshes):
    return v01.union(meshes)


def difference(base, cutters):
    return v01.difference(base, cutters)


def slot(x, y, width=3.0, height=12.0):
    return v01.slot(x, y, width, height)


def battery_guides():
    """Low, discontinuous rails locate the pouch without clamping it."""
    cx, cy = P["battery_center_x"], P["battery_center_y"]
    half_w = P["battery_width"] / 2.0
    half_h = P["battery_height"] / 2.0
    z = P["midplate_thickness"] + 1.4
    return [
        cuboid((2.5, 20.0, 3.2), (cx - half_w - 1.25, cy, z)),
        cuboid((2.5, 20.0, 3.2), (cx + half_w + 1.25, cy, z)),
        cuboid((18.4, 2.5, 3.2), (cx - 22.0, cy + half_h + 1.25, z)),
        cuboid((18.4, 2.5, 3.2), (cx + 22.0, cy + half_h + 1.25, z)),
        cuboid((18.4, 2.5, 3.2), (cx - 22.0, cy - half_h - 1.25, z)),
        cuboid((18.4, 2.5, 3.2), (cx + 22.0, cy - half_h - 1.25, z)),
    ]


def despi_guides():
    """Short rails leave the left pin header and right ZIF/FPC unobstructed."""
    cx, cy = P["despi_center_x"], P["despi_center_y"]
    half_h = P["despi_height"] / 2.0
    z = P["midplate_thickness"] + 1.4
    return [
        cuboid((12.0, 2.5, 3.2), (cx - 9.0, cy - half_h - 1.25, z)),
        cuboid((12.0, 2.5, 3.2), (cx + 9.0, cy - half_h - 1.25, z)),
        cuboid((12.0, 2.5, 3.2), (cx - 9.0, cy + half_h + 1.25, z)),
        cuboid((12.0, 2.5, 3.2), (cx + 9.0, cy + half_h + 1.25, z)),
    ]


def lipo_mount_posts(holes=LIPO_MOUNT_HOLES):
    # Start 0.2 mm inside the carrier skin to avoid tangent-only STL bodies.
    base_top = P["midplate_thickness"] - 0.2
    post_top = P["lipo_mount_post_top"]
    height = post_top - base_top
    return [
        cylinder(3.25, height, (x, y, base_top + height / 2.0), sections=48)
        for x, y in holes
    ]


def rear_insert_bosses():
    boss_height = 5.0
    bottom = P["midplate_thickness"] - 0.2
    top = P["midplate_thickness"] + boss_height
    return [
        cylinder(3.8, top - bottom, (x, y, (bottom + top) / 2.0), sections=48)
        for x, y in REAR_FASTENERS
    ]


def build_middle_carrier():
    base = v01.rounded_prism(
        P["midplate_width"], P["midplate_height"], 4.0, P["midplate_thickness"]
    )
    body = union(
        [
            base,
            *battery_guides(),
            *despi_guides(),
            *lipo_mount_posts(),
            *rear_insert_bosses(),
        ]
    )

    cutters = []

    # Screen FPC exits at the right edge and enters DESPI-C02 without folding.
    cutters.append(cuboid((8.0, 36.0, 6.0), (60.0, P["despi_center_y"], 1.0)))

    for x, y in FRONT_FASTENERS:
        cutters.append(cylinder(P["m2_clearance"] / 2.0, 5.0, (x, y, 1.0), sections=36))

    rear_boss_height = 5.0
    for x, y in REAR_FASTENERS:
        cutters.append(
            cylinder(
                P["m2_insert_hole"] / 2.0,
                4.7,
                (x, y, P["midplate_thickness"] + rear_boss_height - 4.7 / 2.0 + 0.1),
                sections=36,
            )
        )

    # Four exact Lipo Rider pilot holes; M2 x 4 mm self-tapping screws.
    for x, y in LIPO_MOUNT_HOLES:
        cutters.append(cylinder(P["lipo_mount_pilot"] / 2.0, 3.3, (x, y, 3.25), sections=36))

    # ESP32: two horizontal straps.  The antenna remains at the top and its
    # Type-C connector remains open at the bottom.
    esp_strap_offset_x = P["esp_width"] / 2.0 + 3.0
    for y in (8.0, 34.0):
        cutters.append(slot(P["esp_center_x"] - esp_strap_offset_x, y, 3.0, 12.0))
        cutters.append(slot(P["esp_center_x"] + esp_strap_offset_x, y, 3.0, 12.0))

    # DESPI: one vertical strap; neither the left pins nor right FPC are crossed.
    cutters.append(slot(P["despi_center_x"], -22.5, 12.0, 3.0))
    cutters.append(slot(P["despi_center_x"], 10.5, 12.0, 3.0))

    # Battery: two straps cross its short direction.  Slots stay clear of the
    # bottom rear-cover screw pillars.
    for x in (-20.0, 24.0):
        cutters.append(slot(x, -23.0, 12.0, 3.0))
        cutters.append(slot(x, -92.5, 12.0, 3.0))

    # Cable-tie anchors: short SPI bundle between ESP32 and DESPI, USB power
    # cable below Lipo Rider, and battery lead along the right-hand side.
    cutters.append(slot(-3.5, -2.0, 8.0, 3.0))
    cutters.append(slot(-3.5, 44.0, 8.0, 3.0))
    cutters.append(slot(46.0, 35.0, 8.0, 3.0))
    cutters.append(slot(46.0, 22.0, 8.0, 3.0))

    return difference(body, cutters)


def build_rear_cover():
    """V0.1 rear shell with only the requested top-centre USB-C opening."""
    depth = P["rear_cover_depth"]
    shell = v01.rounded_prism(P["case_width"], P["case_height"], P["corner_radius"], depth)
    inner_width = P["rear_inner_width"]
    inner_height = P["rear_inner_height"]
    cavity = v01.rounded_prism(
        inner_width,
        inner_height,
        4.0,
        depth - P["rear_skin_thickness"] + 1.0,
        P["rear_skin_thickness"],
    )
    shell = difference(shell, [cavity])

    ledge_outer = v01.rounded_prism(inner_width, inner_height, 4.0, 2.0, depth - 2.0)
    ledge_inner = v01.rounded_prism(inner_width - 4.0, inner_height - 4.0, 3.0, 4.0, depth - 3.0)
    ledge = difference(ledge_outer, [ledge_inner])

    pillar_top = 14.2
    pillars = [
        cylinder(
            3.8,
            pillar_top - P["rear_skin_thickness"],
            (x, y, (pillar_top + P["rear_skin_thickness"]) / 2.0),
        )
        for x, y in REAR_FASTENERS
    ]
    body = union([shell, ledge, *pillars])

    cutters = []
    for x, y in REAR_FASTENERS:
        cutters.append(cylinder(P["m2_clearance"] / 2.0, depth + 2.0, (x, y, depth / 2.0), sections=36))
        cutters.append(cylinder(2.3, 2.2, (x, y, 1.0), sections=36))

    for x, y in MAGNETS:
        cutters.append(
            cylinder(
                P["magnet_diameter"] / 2.0,
                P["magnet_depth"] + 0.2,
                (x, y, 0.8 + (P["magnet_depth"] + 0.2) / 2.0),
                sections=64,
            )
        )

    # USB-C charging opening: top edge, connector centre exactly x=0.
    cutters.append(
        cuboid(
            (P["charge_cutout_width"], 7.0, P["charge_cutout_height"]),
            (
                P["charge_cutout_center_x"],
                P["charge_cutout_center_y"],
                P["charge_cutout_center_z"],
            ),
        )
    )

    # Retain only the two bottom pressure/air-relief slots.  V0.1's incorrect
    # bottom charge and switch openings are deliberately absent.
    cutters.append(cuboid((12.0, 7.0, 2.0), (17.0, -99.0, 7.0)))
    cutters.append(cuboid((12.0, 7.0, 2.0), (35.0, -99.0, 7.0)))
    return difference(body, cutters)


def coupon_lipo_to_local(x: float, y: float) -> tuple[float, float]:
    """Move the main-layout USB-C face to local (0, 0)."""
    return x - LIPO_USB_C_FACE[0], y - LIPO_USB_C_FACE[1]


def build_lipo_port_fit_coupon():
    """Cheap L-bracket to validate all four holes and USB-C plug clearance."""
    local_holes = [coupon_lipo_to_local(x, y) for x, y in LIPO_MOUNT_HOLES]
    base = cuboid((40.0, 48.0, 2.0), (0.0, -24.0, 1.0))
    wall = cuboid((40.0, 2.1, 15.0), (0.0, 1.05, 7.5))
    body = union([base, wall, *lipo_mount_posts(local_holes)])
    cutters = [cuboid((P["charge_cutout_width"], 4.5, 8.0), (0.0, 1.0, 6.0))]
    for x, y in local_holes:
        cutters.append(cylinder(P["lipo_mount_pilot"] / 2.0, 3.3, (x, y, 3.25), sections=36))
    return difference(body, cutters)


def ensure_mesh(name: str, mesh: trimesh.Trimesh):
    mesh.remove_unreferenced_vertices()
    mesh.fix_normals()
    if not mesh.is_watertight:
        raise RuntimeError(f"{name} is not watertight")
    if not mesh.is_volume:
        raise RuntimeError(f"{name} is not a valid positive volume")
    if len(mesh.split(only_watertight=False)) != 1:
        raise RuntimeError(f"{name} contains more than one disconnected body")
    return mesh


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


def draw_layout(path: Path):
    width, height = 1200, 1700
    margin = 120
    scale = min((width - 2 * margin) / P["midplate_width"], (height - 2 * margin) / P["midplate_height"])
    image = Image.new("RGB", (width, height), "#f4f2ec")
    draw = ImageDraw.Draw(image)
    title_font = load_font(42)
    label_font = load_font(28)
    small_font = load_font(23)

    def point(x, y):
        return width / 2 + x * scale, height / 2 - y * scale

    def rect(cx, cy, w, h, fill, outline, label):
        x0, y0 = point(cx - w / 2, cy + h / 2)
        x1, y1 = point(cx + w / 2, cy - h / 2)
        draw.rounded_rectangle((x0, y0, x1, y1), radius=14, fill=fill, outline=outline, width=4)
        box = draw.textbbox((0, 0), label, font=label_font)
        draw.text(((x0 + x1 - box[2] + box[0]) / 2, (y0 + y1 - box[3] + box[1]) / 2), label, fill="#17352b", font=label_font)

    x0, y0 = point(-P["midplate_width"] / 2, P["midplate_height"] / 2)
    x1, y1 = point(P["midplate_width"] / 2, -P["midplate_height"] / 2)
    draw.rounded_rectangle((x0, y0, x1, y1), radius=34, fill="#ffffff", outline="#193a30", width=6)
    draw.text((65, 35), "V0.3 中层托板最终布局", fill="#17352b", font=title_font)

    rect(P["lipo_rider_center_x"], P["lipo_rider_center_y"], P["lipo_rider_width"], P["lipo_rider_height"], "#d9c3ef", "#735497", "Lipo Rider")
    rect(P["esp_center_x"], P["esp_center_y"], P["esp_width"], P["esp_height"], "#bcd7ef", "#3f6f9e", "ESP32-S3")
    rect(P["despi_center_x"], P["despi_center_y"], P["despi_width"], P["despi_height"], "#b8dfd1", "#28765e", "DESPI-C02")
    rect(P["battery_center_x"], P["battery_center_y"], P["battery_width"], P["battery_height"], "#f6d58a", "#b47a12", "806090 电池")

    px, py = point(*LIPO_USB_C_FACE)
    draw.ellipse((px - 10, py - 10, px + 10, py + 10), fill="#d9463e")
    draw.line((px, py, *point(0, 99)), fill="#d9463e", width=5)
    draw.text((px + 20, py - 15), "顶部中线 USB-C", fill="#a62e28", font=small_font)

    esp_right = P["esp_center_x"] + P["esp_width"] / 2
    despi_left = P["despi_center_x"] - P["despi_width"] / 2
    y_mark = 0.0
    draw.line((*point(esp_right, y_mark), *point(despi_left, y_mark)), fill="#d9463e", width=5)
    draw.text(point((esp_right + despi_left) / 2.0 - 8.0, 3.5), f"净距 {despi_left - esp_right:.1f} mm", fill="#a62e28", font=small_font)

    draw.text((70, 1625), "前框继续使用 V0.1；中层托板和后盖改为 V0.3", fill="#17352b", font=small_font)
    image.save(path)


def draw_svg_template(path: Path):
    """Write a physical-size 1:1 placement template in millimetres."""
    def svg_rect(cx, cy, w, h, stroke, label):
        x = cx + P["midplate_width"] / 2 - w / 2
        y = P["midplate_height"] / 2 - cy - h / 2
        return (
            f'<rect x="{x:.3f}" y="{y:.3f}" width="{w:.3f}" height="{h:.3f}" '
            f'rx="1.5" fill="none" stroke="{stroke}" stroke-width="0.35"/>'
            f'<text x="{x + w / 2:.3f}" y="{y + h / 2:.3f}" text-anchor="middle" '
            f'dominant-baseline="middle" font-size="3.2">{label}</text>'
        )

    parts = [
        svg_rect(P["lipo_rider_center_x"], P["lipo_rider_center_y"], P["lipo_rider_width"], P["lipo_rider_height"], "#735497", "Lipo Rider"),
        svg_rect(P["esp_center_x"], P["esp_center_y"], P["esp_width"], P["esp_height"], "#3f6f9e", "ESP32-S3"),
        svg_rect(P["despi_center_x"], P["despi_center_y"], P["despi_width"], P["despi_height"], "#28765e", "DESPI-C02"),
        svg_rect(P["battery_center_x"], P["battery_center_y"], P["battery_width"], P["battery_height"], "#b47a12", "806090 battery"),
    ]
    for x, y in REAR_FASTENERS:
        sx = x + P["midplate_width"] / 2
        sy = P["midplate_height"] / 2 - y
        parts.append(f'<circle cx="{sx:.3f}" cy="{sy:.3f}" r="1.2" fill="none" stroke="#333" stroke-width="0.3"/>')
    port_x = LIPO_USB_C_FACE[0] + P["midplate_width"] / 2
    port_y = P["midplate_height"] / 2 - LIPO_USB_C_FACE[1]
    parts.append(f'<circle cx="{port_x:.3f}" cy="{port_y:.3f}" r="1.0" fill="#d9463e"/>')
    parts.append(f'<text x="{port_x + 2:.3f}" y="{port_y + 3:.3f}" font-size="2.8">USB-C centre</text>')
    svg = f'''<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="{P['midplate_width']}mm" height="{P['midplate_height']}mm" viewBox="0 0 {P['midplate_width']} {P['midplate_height']}">
  <rect x="0.2" y="0.2" width="{P['midplate_width'] - 0.4}" height="{P['midplate_height'] - 0.4}" rx="4" fill="white" stroke="#111" stroke-width="0.4"/>
  {''.join(parts)}
  <text x="3" y="192" font-size="2.8">Print at 100% / Actual size / No scaling</text>
</svg>
'''
    path.write_text(svg, encoding="utf-8")


def part_info(path: Path):
    # Reload exported STL with processing enabled.  This catches float32 STL
    # cracks and disconnected tangent bodies that in-memory validation misses.
    mesh = trimesh.load(path, force="mesh", process=True)
    bodies = mesh.split(only_watertight=False)
    if not mesh.is_watertight or not mesh.is_volume or len(bodies) != 1:
        raise RuntimeError(
            f"Reload validation failed for {path.name}: watertight={mesh.is_watertight}, "
            f"volume={mesh.is_volume}, bodies={len(bodies)}"
        )
    return {
        "file": path.name,
        "watertight_after_reload": bool(mesh.is_watertight),
        "is_volume_after_reload": bool(mesh.is_volume),
        "body_count_after_reload": int(len(bodies)),
        "vertices": int(len(mesh.vertices)),
        "faces": int(len(mesh.faces)),
        "volume_mm3": round(float(mesh.volume), 2),
        "bounds_mm": [[round(float(v), 3) for v in row] for row in mesh.bounds],
        "size_mm": [round(float(v), 3) for v in (mesh.bounds[1] - mesh.bounds[0])],
    }


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    PREVIEWS.mkdir(parents=True, exist_ok=True)

    meshes = {
        "middle_carrier_v0_3": ensure_mesh("middle_carrier_v0_3", build_middle_carrier()),
        "rear_cover_v0_3": ensure_mesh("rear_cover_v0_3", build_rear_cover()),
        "fit_test_lipo_top_port_v0_3": ensure_mesh("fit_test_lipo_top_port_v0_3", build_lipo_port_fit_coupon()),
    }
    paths = {}
    for name, mesh in meshes.items():
        path = OUTPUT / f"{name}.stl"
        path.write_bytes(trimesh.exchange.stl.export_stl(mesh))
        paths[name] = path

    layout_path = PREVIEWS / "enclosure_v0_3_layout.png"
    template_path = OUTPUT / "placement_template_v0_3_1to1.svg"
    draw_layout(layout_path)
    draw_svg_template(template_path)

    esp_right = P["esp_center_x"] + P["esp_width"] / 2.0
    despi_left = P["despi_center_x"] - P["despi_width"] / 2.0
    lipo_bottom = P["lipo_rider_center_y"] - P["lipo_rider_height"] / 2.0
    esp_top = P["esp_center_y"] + P["esp_height"] / 2.0
    despi_bottom = P["despi_center_y"] - P["despi_height"] / 2.0
    battery_top = P["battery_center_y"] + P["battery_height"] / 2.0

    manifest = {
        "design": "RefrigeratorFoodManagement enclosure replacement V0.3",
        "units": "mm",
        "status": "full parts require fit-coupon approval before printing",
        "reuse_without_reprint": ["front_bezel_v0_1.stl"],
        "photo_calibration_reference": {
            "carrier": [123.0, 195.0],
            "note": "photo positions calibrated from four known rear-fastener centres; ESP32 then moved toward DESPI as requested",
        },
        "layout": {
            "lipo_rider_center": [P["lipo_rider_center_x"], P["lipo_rider_center_y"]],
            "lipo_mount_holes": [[round(x, 3), round(y, 3)] for x, y in LIPO_MOUNT_HOLES],
            "lipo_usb_c_center": [round(v, 3) for v in LIPO_USB_C_CENTRE],
            "lipo_usb_c_face": [round(v, 3) for v in LIPO_USB_C_FACE],
            "esp32_center": [P["esp_center_x"], P["esp_center_y"]],
            "despi_center": [P["despi_center_x"], P["despi_center_y"]],
            "battery_center": [P["battery_center_x"], P["battery_center_y"]],
            "rear_charge_cutout_center": [
                P["charge_cutout_center_x"],
                P["charge_cutout_center_y"],
                P["charge_cutout_center_z"],
            ],
            "rear_charge_cutout_size": [P["charge_cutout_width"], 7.0, P["charge_cutout_height"]],
        },
        "verified_nominal_clearances_mm": {
            "esp32_to_despi_horizontal": round(despi_left - esp_right, 3),
            "lipo_to_esp32_vertical": round(lipo_bottom - esp_top, 3),
            "despi_to_battery_vertical": round(despi_bottom - battery_top, 3),
            "usb_c_face_to_case_center_x": round(LIPO_USB_C_FACE[0], 3),
            "usb_c_face_to_carrier_top_edge": round(P["midplate_height"] / 2.0 - LIPO_USB_C_FACE[1], 3),
        },
        "parameters": P,
        "parts": {name: part_info(path) for name, path in paths.items()},
        "template": template_path.name,
    }
    manifest_path = OUTPUT / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    package_path = ROOT / "RFM_enclosure_v0_3_STL.zip"
    with zipfile.ZipFile(package_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in paths.values():
            archive.write(path, path.name)
        archive.write(manifest_path, manifest_path.name)
        archive.write(template_path, template_path.name)
        archive.write(layout_path, layout_path.name)
        archive.write(ROOT / "README.md", "README.md")
        archive.write(ROOT / "ASSEMBLY_GUIDE.md", "ASSEMBLY_GUIDE.md")

    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
