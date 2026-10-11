#!/usr/bin/env python3
"""Generate V0.4 with the ESP32 moved left and BOOT/RESET access holes."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import zipfile

from PIL import Image, ImageDraw, ImageFont
import trimesh


ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "output"
PREVIEWS = ROOT / "previews"
V03_FILE = ROOT.parent / "enclosure_v0_3" / "generate_enclosure_v0_3.py"


def load_v03_module():
    spec = importlib.util.spec_from_file_location("rfm_enclosure_v03", V03_FILE)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load V0.3 generator: {V03_FILE}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


v03 = load_v03_module()
P = dict(v03.P)
P.update(
    {
        # Restores the ESP32 to the left-side position measured from the
        # approved physical reference photo.  Y remains unchanged.
        "esp_center_x": -35.0,
        # Rear-cover tool-access holes.  A 2-3 mm non-metallic pin is used to
        # reach the recessed board buttons; these are not fingertip openings.
        "esp_button_access_diameter": 5.5,
        "esp_button_counterbore_diameter": 8.5,
        "esp_button_counterbore_depth": 1.2,
    }
)
v03.P = P
v03.v01.P = P


# Calibrated from the same perspective-corrected physical photo as V0.3.
# Values are relative to the ESP32 board-envelope centre when viewed from the
# component side, antenna up and USB-C down.
BOOT_OFFSET = (-8.146, -29.095)
RESET_OFFSET = (7.242, -29.322)
BOOT_CENTRE = (P["esp_center_x"] + BOOT_OFFSET[0], P["esp_center_y"] + BOOT_OFFSET[1])
RESET_CENTRE = (P["esp_center_x"] + RESET_OFFSET[0], P["esp_center_y"] + RESET_OFFSET[1])


def cylinder(radius, height, center, sections=48):
    return v03.cylinder(radius, height, center, sections=sections)


def cuboid(size, center):
    return v03.cuboid(size, center)


def difference(base, cutters):
    return v03.difference(base, cutters)


def build_rear_cover_v04():
    body = v03.build_rear_cover()
    cutters = []
    through_radius = P["esp_button_access_diameter"] / 2.0
    counterbore_radius = P["esp_button_counterbore_diameter"] / 2.0
    for x, y in (BOOT_CENTRE, RESET_CENTRE):
        # Through the 4 mm rear skin, with 1.5 mm extra on both sides.
        cutters.append(cylinder(through_radius, 7.0, (x, y, 2.5), sections=48))
        # Shallow outside recess makes the access point easy to locate and
        # removes the sharp print edge without creating a large accidental
        # finger-press opening.
        cutters.append(
            cylinder(
                counterbore_radius,
                P["esp_button_counterbore_depth"] + 0.2,
                (x, y, P["esp_button_counterbore_depth"] / 2.0),
                sections=64,
            )
        )
    return difference(body, cutters)


def build_button_hole_coupon():
    """Small coupon for checking the access-hole and counterbore diameters."""
    spacing = RESET_CENTRE[0] - BOOT_CENTRE[0]
    left = -spacing / 2.0
    right = spacing / 2.0
    body = v03.v01.rounded_prism(34.0, 18.0, 2.0, 4.0)
    cutters = []
    for x in (left, right):
        cutters.append(cylinder(P["esp_button_access_diameter"] / 2.0, 6.0, (x, 0.0, 2.0), sections=48))
        cutters.append(
            cylinder(
                P["esp_button_counterbore_diameter"] / 2.0,
                P["esp_button_counterbore_depth"] + 0.2,
                (x, 0.0, P["esp_button_counterbore_depth"] / 2.0),
                sections=64,
            )
        )
    return difference(body, cutters)


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
        draw.text(
            ((x0 + x1 - box[2] + box[0]) / 2, (y0 + y1 - box[3] + box[1]) / 2),
            label,
            fill="#17352b",
            font=label_font,
        )

    x0, y0 = point(-P["midplate_width"] / 2, P["midplate_height"] / 2)
    x1, y1 = point(P["midplate_width"] / 2, -P["midplate_height"] / 2)
    draw.rounded_rectangle((x0, y0, x1, y1), radius=34, fill="#ffffff", outline="#193a30", width=6)
    draw.text((65, 35), "V0.4 中层托板与后盖孔位", fill="#17352b", font=title_font)

    rect(P["lipo_rider_center_x"], P["lipo_rider_center_y"], P["lipo_rider_width"], P["lipo_rider_height"], "#d9c3ef", "#735497", "Lipo Rider")
    rect(P["esp_center_x"], P["esp_center_y"], P["esp_width"], P["esp_height"], "#bcd7ef", "#3f6f9e", "ESP32-S3")
    rect(P["despi_center_x"], P["despi_center_y"], P["despi_width"], P["despi_height"], "#b8dfd1", "#28765e", "DESPI-C02")
    rect(P["battery_center_x"], P["battery_center_y"], P["battery_width"], P["battery_height"], "#f6d58a", "#b47a12", "806090 电池")

    px, py = point(*v03.LIPO_USB_C_FACE)
    draw.ellipse((px - 10, py - 10, px + 10, py + 10), fill="#d9463e")
    draw.text((px + 20, py - 15), "顶部中线 USB-C", fill="#a62e28", font=small_font)

    for label, centre in (("BOOT", BOOT_CENTRE), ("RESET", RESET_CENTRE)):
        bx, by = point(*centre)
        radius = P["esp_button_counterbore_diameter"] / 2.0 * scale
        draw.ellipse((bx - radius, by - radius, bx + radius, by + radius), outline="#d9463e", width=5)
        draw.text((bx - 35, by + radius + 8), label, fill="#a62e28", font=small_font)

    esp_left = P["esp_center_x"] - P["esp_width"] / 2.0
    edge_clearance = esp_left + P["midplate_width"] / 2.0
    draw.text((70, 1625), f"ESP32 左边缘距托板边缘 {edge_clearance:.1f} mm；后盖双孔需用细塑料杆按压", fill="#17352b", font=small_font)
    image.save(path)


def svg_rect(cx, cy, w, h, stroke, label, carrier_w=123.0, carrier_h=195.0):
    x = cx + carrier_w / 2.0 - w / 2.0
    y = carrier_h / 2.0 - cy - h / 2.0
    return (
        f'<rect x="{x:.3f}" y="{y:.3f}" width="{w:.3f}" height="{h:.3f}" '
        f'rx="1.5" fill="none" stroke="{stroke}" stroke-width="0.35"/>'
        f'<text x="{x + w / 2:.3f}" y="{y + h / 2:.3f}" text-anchor="middle" '
        f'dominant-baseline="middle" font-size="3.2">{label}</text>'
    )


def draw_placement_svg(path: Path):
    parts = [
        svg_rect(P["lipo_rider_center_x"], P["lipo_rider_center_y"], P["lipo_rider_width"], P["lipo_rider_height"], "#735497", "Lipo Rider"),
        svg_rect(P["esp_center_x"], P["esp_center_y"], P["esp_width"], P["esp_height"], "#3f6f9e", "ESP32-S3"),
        svg_rect(P["despi_center_x"], P["despi_center_y"], P["despi_width"], P["despi_height"], "#28765e", "DESPI-C02"),
        svg_rect(P["battery_center_x"], P["battery_center_y"], P["battery_width"], P["battery_height"], "#b47a12", "806090 battery"),
    ]
    for label, (x, y) in (("B", BOOT_CENTRE), ("R", RESET_CENTRE)):
        sx = x + P["midplate_width"] / 2.0
        sy = P["midplate_height"] / 2.0 - y
        parts.append(f'<circle cx="{sx:.3f}" cy="{sy:.3f}" r="2.75" fill="none" stroke="#d9463e" stroke-width="0.35"/>')
        parts.append(f'<text x="{sx:.3f}" y="{sy + 0.9:.3f}" text-anchor="middle" font-size="2.8">{label}</text>')
    svg = f'''<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="{P['midplate_width']}mm" height="{P['midplate_height']}mm" viewBox="0 0 {P['midplate_width']} {P['midplate_height']}">
  <rect x="0.2" y="0.2" width="{P['midplate_width'] - 0.4}" height="{P['midplate_height'] - 0.4}" rx="4" fill="white" stroke="#111" stroke-width="0.4"/>
  {''.join(parts)}
  <text x="3" y="192" font-size="2.8">Print at 100% / Actual size / No scaling</text>
</svg>
'''
    path.write_text(svg, encoding="utf-8")


def draw_rear_hole_svg(path: Path):
    w, h = P["case_width"], P["case_height"]
    items = [f'<rect x="0.2" y="0.2" width="{w - 0.4}" height="{h - 0.4}" rx="6" fill="white" stroke="#111" stroke-width="0.4"/>']
    for label, (x, y) in (("BOOT", BOOT_CENTRE), ("RESET", RESET_CENTRE)):
        sx, sy = x + w / 2.0, h / 2.0 - y
        items.append(f'<circle cx="{sx:.3f}" cy="{sy:.3f}" r="2.75" fill="none" stroke="#d9463e" stroke-width="0.4"/>')
        items.append(f'<circle cx="{sx:.3f}" cy="{sy:.3f}" r="4.25" fill="none" stroke="#d9463e" stroke-dasharray="1,1" stroke-width="0.25"/>')
        items.append(f'<text x="{sx:.3f}" y="{sy + 7:.3f}" text-anchor="middle" font-size="3">{label}</text>')
    port_x = w / 2.0 - P["charge_cutout_width"] / 2.0
    items.append(f'<rect x="{port_x:.3f}" y="0" width="{P["charge_cutout_width"]:.3f}" height="4.5" fill="none" stroke="#735497" stroke-width="0.4"/>')
    items.append(f'<text x="{w / 2.0:.3f}" y="8" text-anchor="middle" font-size="3">USB-C top centre</text>')
    svg = f'''<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="{w}mm" height="{h}mm" viewBox="0 0 {w} {h}">
  {''.join(items)}
  <text x="4" y="196" font-size="2.8">Rear view - print at 100% - verify before full cover print</text>
</svg>
'''
    path.write_text(svg, encoding="utf-8")


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    PREVIEWS.mkdir(parents=True, exist_ok=True)

    meshes = {
        "middle_carrier_v0_4": v03.ensure_mesh("middle_carrier_v0_4", v03.build_middle_carrier()),
        "rear_cover_v0_4": v03.ensure_mesh("rear_cover_v0_4", build_rear_cover_v04()),
        "fit_test_lipo_top_port_v0_4": v03.ensure_mesh("fit_test_lipo_top_port_v0_4", v03.build_lipo_port_fit_coupon()),
        "fit_test_button_hole_diameter_v0_4": v03.ensure_mesh("fit_test_button_hole_diameter_v0_4", build_button_hole_coupon()),
    }
    paths = {}
    for name, mesh in meshes.items():
        path = OUTPUT / f"{name}.stl"
        path.write_bytes(trimesh.exchange.stl.export_stl(mesh))
        paths[name] = path

    layout_path = PREVIEWS / "enclosure_v0_4_layout.png"
    placement_path = OUTPUT / "placement_template_v0_4_1to1.svg"
    rear_hole_path = OUTPUT / "rear_button_hole_template_v0_4_1to1.svg"
    draw_layout(layout_path)
    draw_placement_svg(placement_path)
    draw_rear_hole_svg(rear_hole_path)

    esp_left = P["esp_center_x"] - P["esp_width"] / 2.0
    esp_right = P["esp_center_x"] + P["esp_width"] / 2.0
    despi_left = P["despi_center_x"] - P["despi_width"] / 2.0
    manifest = {
        "design": "RefrigeratorFoodManagement enclosure replacement V0.4",
        "units": "mm",
        "status": "verify 1:1 templates and fit coupons before full-size print",
        "reuse_without_reprint": ["front_bezel_v0_1.stl"],
        "changes_from_v0_3": [
            "ESP32 moved left to match the physical placement photo",
            "rear cover adds BOOT and RESET tool-access holes",
        ],
        "layout": {
            "esp32_center": [P["esp_center_x"], P["esp_center_y"]],
            "despi_center": [P["despi_center_x"], P["despi_center_y"]],
            "lipo_rider_center": [P["lipo_rider_center_x"], P["lipo_rider_center_y"]],
            "battery_center": [P["battery_center_x"], P["battery_center_y"]],
            "boot_access_center": [round(v, 3) for v in BOOT_CENTRE],
            "reset_access_center": [round(v, 3) for v in RESET_CENTRE],
            "button_through_diameter": P["esp_button_access_diameter"],
            "button_counterbore_diameter": P["esp_button_counterbore_diameter"],
            "rear_charge_cutout_center": [P["charge_cutout_center_x"], P["charge_cutout_center_y"], P["charge_cutout_center_z"]],
        },
        "verified_nominal_clearances_mm": {
            "esp32_left_edge_to_carrier": round(esp_left + P["midplate_width"] / 2.0, 3),
            "esp32_to_despi_horizontal": round(despi_left - esp_right, 3),
            "button_center_spacing": round(RESET_CENTRE[0] - BOOT_CENTRE[0], 3),
            "usb_c_face_to_case_center_x": round(v03.LIPO_USB_C_FACE[0], 3),
        },
        "photo_calibrated_button_offsets": {
            "boot_from_esp_center": list(BOOT_OFFSET),
            "reset_from_esp_center": list(RESET_OFFSET),
        },
        "parameters": P,
        "parts": {name: v03.part_info(path) for name, path in paths.items()},
        "templates": [placement_path.name, rear_hole_path.name],
    }
    manifest_path = OUTPUT / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    package_path = ROOT / "RFM_enclosure_v0_4_STL.zip"
    with zipfile.ZipFile(package_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in paths.values():
            archive.write(path, path.name)
        archive.write(manifest_path, manifest_path.name)
        archive.write(placement_path, placement_path.name)
        archive.write(rear_hole_path, rear_hole_path.name)
        archive.write(layout_path, layout_path.name)
        for preview_name in ("installation_open_v0_4.png", "rear_cover_installed_v0_4.png"):
            preview_path = PREVIEWS / preview_name
            if preview_path.exists():
                archive.write(preview_path, preview_name)
        archive.write(ROOT / "README.md", "README.md")
        archive.write(ROOT / "ASSEMBLY_GUIDE.md", "ASSEMBLY_GUIDE.md")

    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
