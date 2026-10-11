#!/usr/bin/env python3
"""Generate the V0.2 replacement middle carrier.

Only the middle carrier changes.  The V0.1 front bezel and rear cover are
intentionally left untouched so the already printed parts can be reused.

The Lipo Rider Plus footprint and mounting-hole positions below are derived
from Seeed Studio's official Eagle board file.  All dimensions are millimetres.
"""

from __future__ import annotations

import importlib.util
import json
import math
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


# The enclosure envelope, screen opening, and all front/rear interfaces are
# inherited from V0.1.  Only electronics locations on the carrier change.
P = dict(v01.P)
P.update(
    {
        "battery_center_x": -20.0,
        "battery_center_y": 0.0,
        "esp_center_x": 31.0,
        "esp_center_y": 61.0,
        "despi_width": 42.0,
        "despi_height": 24.0,
        "despi_center_x": 39.0,
        "despi_center_y": -7.9,
        # Official Lipo Rider Plus PCB outline: 40.877 x 25.48 mm.  It is
        # installed vertically, with the USB-C input facing the case bottom.
        "lipo_rider_width": 25.48,
        "lipo_rider_height": 40.877,
        # USB-C is 5.461 mm to the right of the rotated PCB centre.  This x
        # coordinate therefore aligns it with the unchanged x=-40 rear cutout.
        "lipo_rider_center_x": -45.461,
        # Keeps the PCB within the rear cavity while leaving the connector
        # mouth about 1.3 mm behind the outside face of the existing cutout.
        "lipo_rider_center_y": -77.4,
        "lipo_mount_post_top": 4.4,
        "lipo_mount_pilot": 1.8,
    }
)
v01.P = P


FRONT_FASTENERS = list(v01.FRONT_FASTENERS)
REAR_FASTENERS = list(v01.REAR_FASTENERS)
DISABLED_REAR_FASTENER = (-54.5, -90.0)
ACTIVE_REAR_FASTENERS = [point for point in REAR_FASTENERS if point != DISABLED_REAR_FASTENER]


# Official Eagle-board coordinates, transformed into carrier coordinates.
LIPO_BOARD_CENTRE_EAGLE = (20.4385, 15.24)
LIPO_MOUNT_HOLES_EAGLE = [
    (10.778, 25.567),
    (10.778, 5.040),
    (38.337, 25.567),
    (38.337, 5.040),
]


def lipo_to_carrier(x: float, y: float) -> tuple[float, float]:
    """Rotate the Eagle board +90 degrees so USB-C faces case bottom."""
    ex, ey = LIPO_BOARD_CENTRE_EAGLE
    return (
        P["lipo_rider_center_x"] - (y - ey),
        P["lipo_rider_center_y"] + (x - ex),
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


def despi_guides():
    """Low guides that cannot obstruct the left pins or right FPC connector."""
    cy = P["despi_center_y"]
    half_h = P["despi_height"] / 2.0
    # Sink every added feature 0.2 mm into the 2 mm carrier skin.  Boolean
    # unions of merely tangent solids can become non-manifold after STL's
    # float32 conversion even when the in-memory mesh initially looks valid.
    z = P["midplate_thickness"] + 1.4
    return [
        cuboid((12.0, 2.5, 3.2), (31.0, cy - half_h - 1.25, z)),
        cuboid((12.0, 2.5, 3.2), (49.0, cy - half_h - 1.25, z)),
        cuboid((12.0, 2.5, 3.2), (31.0, cy + half_h + 1.25, z)),
        cuboid((12.0, 2.5, 3.2), (49.0, cy + half_h + 1.25, z)),
    ]


def battery_guides_v02():
    cx, cy = P["battery_center_x"], P["battery_center_y"]
    half_w = P["battery_width"] / 2.0
    half_h = P["battery_height"] / 2.0
    z = P["midplate_thickness"] + 1.4
    guides = []
    for sy in (-1.0, 1.0):
        y = cy + sy * (half_h - 9.0)
        guides.append(cuboid((2.5, 18.4, 3.2), (cx - half_w - 1.25, y, z)))
        guides.append(cuboid((2.5, 18.4, 3.2), (cx + half_w + 1.25, y, z)))
    for sx in (-1.0, 1.0):
        x = cx + sx * (half_w - 9.0)
        # The extra 0.4 mm makes each L-corner a true overlapping union rather
        # than two solids meeting at a single vertical edge.
        guides.append(cuboid((18.4, 2.5, 3.2), (x, cy - half_h - 1.25, z)))
        guides.append(cuboid((18.4, 2.5, 3.2), (x, cy + half_h + 1.25, z)))
    return guides


def lipo_mount_posts():
    base_top = P["midplate_thickness"] - 0.2
    post_top = P["lipo_mount_post_top"]
    height = post_top - base_top
    return [
        cylinder(3.25, height, (x, y, base_top + height / 2.0), sections=48)
        for x, y in LIPO_MOUNT_HOLES
    ]


def build_midplate_v02():
    base = v01.rounded_prism(
        P["midplate_width"], P["midplate_height"], 4.0, P["midplate_thickness"]
    )

    # Keep the three rear-cover fasteners that do not conflict with the exact
    # Lipo Rider footprint.  The V0.1 rear cover itself is not modified.
    rear_boss_height = 5.0
    rear_boss_bottom = P["midplate_thickness"] - 0.2
    rear_bosses = [
        cylinder(
            3.8,
            P["midplate_thickness"] + rear_boss_height - rear_boss_bottom,
            (
                x,
                y,
                (rear_boss_bottom + P["midplate_thickness"] + rear_boss_height) / 2.0,
            ),
        )
        for x, y in ACTIVE_REAR_FASTENERS
    ]

    body = union(
        [
            base,
            *battery_guides_v02(),
            *despi_guides(),
            *lipo_mount_posts(),
            *rear_bosses,
        ]
    )

    cutters = []

    # Same right-edge FPC relief as V0.1.  DESPI-C02 now sits directly beside
    # it, horizontal, so the display FPC can enter the ZIF connector straight.
    cutters.append(cuboid((8.0, 38.0, 6.0), (60.0, P["screen_center_y"], 1.0)))

    for x, y in FRONT_FASTENERS:
        cutters.append(cylinder(P["m2_clearance"] / 2.0, 5.0, (x, y, 1.0), sections=36))

    for x, y in ACTIVE_REAR_FASTENERS:
        cutters.append(
            cylinder(
                P["m2_insert_hole"] / 2.0,
                4.7,
                (
                    x,
                    y,
                    P["midplate_thickness"] + rear_boss_height - 4.7 / 2.0 + 0.1,
                ),
                sections=36,
            )
        )

    # Official 3 mm board holes; use four M2 x 4 self-tapping screws.  Pilot
    # holes intentionally do not penetrate the screen-side carrier skin.
    pilot_radius = P["lipo_mount_pilot"] / 2.0
    for x, y in LIPO_MOUNT_HOLES:
        cutters.append(cylinder(pilot_radius, 3.3, (x, y, 3.25), sections=36))

    # Battery: two 10-12 mm hook-and-loop straps.
    for y in (-17.0, 17.0):
        cutters.append(slot(-54.0, y, 3.0, 14.0))
        cutters.append(slot(14.0, y, 3.0, 14.0))

    # ESP32-S3: two narrow straps; USB-C remains open at its lower edge.
    for y in (48.0, 74.0):
        cutters.append(slot(14.5, y, 3.0, 12.0))
        cutters.append(slot(47.5, y, 3.0, 12.0))

    # DESPI-C02: one vertical strap crosses the PCB centre and leaves both the
    # pin header on the left and the display FPC/ZIF connector on the right free.
    cutters.append(slot(36.0, -24.5, 12.0, 3.0))
    cutters.append(slot(36.0, 8.7, 12.0, 3.0))

    # Cable-tie points for short ESP32-to-DESPI wiring and USB power cable.
    cutters.append(slot(16.0, 17.0, 10.0, 3.0))
    cutters.append(slot(28.0, 17.0, 10.0, 3.0))
    cutters.append(slot(-18.0, -58.0, 10.0, 3.0))
    cutters.append(slot(-18.0, -70.0, 10.0, 3.0))

    return difference(body, cutters)


def ensure_mesh(name: str, mesh: trimesh.Trimesh):
    return v01.ensure_mesh(name, mesh)


def load_font(size: int):
    candidates = [
        "/System/Library/Fonts/PingFang.ttc",
        "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
    ]
    for path in candidates:
        try:
            return ImageFont.truetype(path, size=size)
        except OSError:
            continue
    return ImageFont.load_default()


def draw_layout(path: Path):
    width, height = 1100, 1500
    margin = 110
    scale = min((width - 2 * margin) / P["midplate_width"], (height - 2 * margin) / P["midplate_height"])
    image = Image.new("RGB", (width, height), "#f4f2ec")
    draw = ImageDraw.Draw(image)
    title_font = load_font(42)
    label_font = load_font(28)
    small_font = load_font(22)

    def point(x, y):
        return width / 2 + x * scale, height / 2 - y * scale

    def rect(cx, cy, w, h, fill, outline, label):
        x0, y0 = point(cx - w / 2, cy + h / 2)
        x1, y1 = point(cx + w / 2, cy - h / 2)
        draw.rounded_rectangle((x0, y0, x1, y1), radius=14, fill=fill, outline=outline, width=4)
        box = draw.textbbox((0, 0), label, font=label_font)
        tx = (x0 + x1 - (box[2] - box[0])) / 2
        ty = (y0 + y1 - (box[3] - box[1])) / 2
        draw.text((tx, ty), label, fill="#17352b", font=label_font)

    x0, y0 = point(-P["midplate_width"] / 2, P["midplate_height"] / 2)
    x1, y1 = point(P["midplate_width"] / 2, -P["midplate_height"] / 2)
    draw.rounded_rectangle((x0, y0, x1, y1), radius=34, fill="#ffffff", outline="#193a30", width=6)
    draw.text((70, 32), "V0.2 中层托板布局（复用 V0.1 后盖）", fill="#17352b", font=title_font)

    rect(P["battery_center_x"], P["battery_center_y"], P["battery_width"], P["battery_height"], "#f6d58a", "#b47a12", "806090 电池")
    rect(P["esp_center_x"], P["esp_center_y"], P["esp_width"], P["esp_height"], "#bcd7ef", "#3f6f9e", "ESP32-S3")
    rect(P["despi_center_x"], P["despi_center_y"], P["despi_width"], P["despi_height"], "#b8dfd1", "#28765e", "DESPI-C02")
    rect(P["lipo_rider_center_x"], P["lipo_rider_center_y"], P["lipo_rider_width"], P["lipo_rider_height"], "#d9c3ef", "#735497", "Lipo Rider")

    # Mark existing rear-cover charge cutout and exact USB-C mouth alignment.
    px, py = point(-40.0, -99.0)
    draw.ellipse((px - 9, py - 9, px + 9, py + 9), fill="#d9463e")
    draw.line((px, py, *point(*LIPO_USB_C_FACE)), fill="#d9463e", width=5)
    draw.text((px + 18, py - 10), "原后盖充电口", fill="#a62e28", font=small_font)

    # Grey cross: this existing rear-cover screw is intentionally not used.
    sx, sy = point(*DISABLED_REAR_FASTENER)
    draw.line((sx - 14, sy - 14, sx + 14, sy + 14), fill="#777777", width=6)
    draw.line((sx - 14, sy + 14, sx + 14, sy - 14), fill="#777777", width=6)
    draw.text((sx + 20, sy - 30), "此处后盖螺钉停用", fill="#555555", font=small_font)

    # FPC direction.
    fx0, fy0 = point(61.0, P["despi_center_y"])
    fx1, fy1 = point(52.0, P["despi_center_y"])
    draw.line((fx0, fy0, fx1, fy1), fill="#d9463e", width=7)
    draw.polygon([(fx1, fy1), (fx1 + 18, fy1 - 10), (fx1 + 18, fy1 + 10)], fill="#d9463e")
    draw.text((650, 1380), "FPC 从右侧直插，不折弯", fill="#a62e28", font=small_font)
    image.save(path)


def render_mesh(mesh: trimesh.Trimesh, path: Path):
    canvas = Image.new("RGB", (1400, 1000), "#f4f2ec")
    draw = ImageDraw.Draw(canvas)
    title_font = load_font(38)
    small_font = load_font(25)
    draw.text((50, 35), "Middle carrier V0.2", fill="#17352b", font=title_font)

    # A true top view is more useful than a decorative isometric render here:
    # it exposes every strap slot, post, guide, and the right-side FPC relief
    # without coplanar-triangle painter artefacts.
    vertices = mesh.vertices.copy()
    projected = vertices[:, :2].copy()
    span = np.ptp(projected, axis=0)
    scale = min(1280 / max(span[0], 1), 820 / max(span[1], 1))
    projected *= scale
    projected[:, 0] += 700 - projected[:, 0].mean()
    projected[:, 1] = -projected[:, 1]
    projected[:, 1] += 520 - projected[:, 1].mean()
    faces = mesh.faces
    order = np.argsort(vertices[faces][:, :, 2].mean(axis=1))
    light = np.array([0.25, -0.35, 0.9])
    light /= np.linalg.norm(light)
    normals = mesh.face_normals
    max_z = max(float(mesh.bounds[1, 2]), 1.0)
    for index in order:
        points = [tuple(projected[v]) for v in faces[index]]
        face_z = float(vertices[faces[index], 2].mean())
        height_tint = 0.68 + 0.28 * max(0.0, min(1.0, face_z / max_z))
        brightness = height_tint * (0.72 + 0.25 * max(0.0, float(np.dot(normals[index], light))))
        base = (73, 130, 105)
        color = tuple(int(min(255, c * brightness + 28)) for c in base)
        draw.polygon(points, fill=color)
    draw.text((50, 950), "仅重打这一件；前框和原后盖继续使用", fill="#17352b", font=small_font)
    canvas.save(path)


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    PREVIEWS.mkdir(parents=True, exist_ok=True)

    mesh = ensure_mesh("middle_carrier_v0_2", build_midplate_v02())
    stl_path = OUTPUT / "middle_carrier_v0_2.stl"
    stl_path.write_bytes(trimesh.exchange.stl.export_stl(mesh))

    manifest = {
        "design": "RefrigeratorFoodManagement replacement middle carrier V0.2",
        "units": "mm",
        "reuse_without_reprint": ["front_bezel_v0_1.stl", "rear_cover_v0_1.stl"],
        "rear_cover_fasteners": {
            "active": ACTIVE_REAR_FASTENERS,
            "unused_due_to_lipo_conflict": list(DISABLED_REAR_FASTENER),
        },
        "layout": {
            "battery_center": [P["battery_center_x"], P["battery_center_y"]],
            "esp32_center": [P["esp_center_x"], P["esp_center_y"]],
            "despi_center": [P["despi_center_x"], P["despi_center_y"]],
            "lipo_rider_center": [P["lipo_rider_center_x"], P["lipo_rider_center_y"]],
            "lipo_mount_holes": [[round(x, 3), round(y, 3)] for x, y in LIPO_MOUNT_HOLES],
            "lipo_usb_c_center": [round(v, 3) for v in LIPO_USB_C_CENTRE],
            "lipo_usb_c_face": [round(v, 3) for v in LIPO_USB_C_FACE],
            "existing_rear_charge_cutout_center": [-40.0, -99.0],
        },
        "verified_clearances_mm": {
            "battery_to_esp32_horizontal": 6.0,
            "battery_to_despi_horizontal": 6.5,
            "battery_to_lipo_vertical": 9.462,
            "despi_to_esp32_vertical": 24.4,
            "lipo_usb_c_x_to_existing_cutout": 0.0,
            "lipo_usb_c_face_y_to_existing_cutout_center": 0.288,
        },
        "part": {
            "file": stl_path.name,
            "watertight": bool(mesh.is_watertight),
            "is_volume": bool(mesh.is_volume),
            "body_count": int(len(mesh.split(only_watertight=False))),
            "vertices": int(len(mesh.vertices)),
            "faces": int(len(mesh.faces)),
            "volume_mm3": round(float(mesh.volume), 2),
            "bounds_mm": [[round(float(v), 3) for v in row] for row in mesh.bounds],
            "size_mm": [round(float(v), 3) for v in (mesh.bounds[1] - mesh.bounds[0])],
        },
    }
    manifest_path = OUTPUT / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    layout_path = PREVIEWS / "middle_carrier_v0_2_layout.png"
    mesh_preview_path = PREVIEWS / "middle_carrier_v0_2.png"
    draw_layout(layout_path)
    render_mesh(mesh, mesh_preview_path)

    package_path = ROOT / "RFM_middle_carrier_v0_2_STL.zip"
    with zipfile.ZipFile(package_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.write(stl_path, stl_path.name)
        archive.write(manifest_path, manifest_path.name)
        archive.write(ROOT / "README.md", "README.md")
        archive.write(layout_path, layout_path.name)

    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
