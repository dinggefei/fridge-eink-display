#!/usr/bin/env python3
"""Generate the solderless Dupont-terminal clamp for the V0.7 ESP32 carrier.

This add-on deliberately leaves the existing V0.7 front bezel, electronics
carrier and rear cover untouched.  It uses the two existing mounting holes on
the ESP32's left edge to retain eight housing-free, already-crimped male Dupont
terminals in the plated GPIO holes.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import shutil
import zipfile

from PIL import Image, ImageDraw
import trimesh


ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "output"
PREVIEWS = ROOT / "previews"
PACKAGE_DIR = ROOT / "RFM_esp32_dupont_clamp_v0_7_rev_a"
PACKAGE_ZIP = ROOT / "RFM_esp32_dupont_clamp_v0_7_rev_a.zip"
V07_FILE = ROOT / "generate_enclosure_v0_7.py"


def load_v07_module():
    spec = importlib.util.spec_from_file_location("rfm_enclosure_v07_for_dupont", V07_FILE)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load V0.7 generator: {V07_FILE}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


v07 = load_v07_module()


PARAMETERS = {
    # The actual ESP32 uses the same two left mounting holes already measured
    # for V0.7: 60 mm centre-to-centre.
    "mount_hole_pitch": 60.0,
    "overall_length": 66.0,
    "overall_width": 6.0,
    "screw_clearance_diameter": 2.3,
    # The screw ears add 1.8 mm above the PCB.  M2x6 therefore retains nearly
    # the same thread engagement as the original M2x4 screw without the clamp.
    "screw_ear_thickness": 1.8,
    # The C-shaped terminal rail spans the GPIO row but stops before both
    # corner mounting holes.  It is open toward the board interior so every
    # wire can leave without a sharp bend or a printed bridge over the wire.
    "terminal_rail_length": 54.0,
    "terminal_shelf_height": 2.2,
    "terminal_cavity_height": 1.8,
    "terminal_roof_thickness": 1.2,
    "terminal_outer_wall_thickness": 1.0,
    "terminal_pin_slot_width": 1.25,
    "terminal_pin_slot_offset": 0.15,
    # The shelf lifts a nominal 6 mm male terminal far enough that no more
    # than 2.2 mm protrudes below a nominal 1.6 mm PCB.  V0.7 has 2.8 mm under-
    # board clearance between the PCB and carrier, leaving 0.6 mm nominal.
    "nominal_male_pin_length": 6.0,
    "nominal_pcb_thickness": 1.6,
    "v07_under_board_clearance": 2.8,
    "wire_count": 8,
    "wire_functions": ["3V3", "GPIO7", "GPIO8", "GPIO9", "GPIO10", "GPIO11", "GPIO12", "GND"],
    "left_screw": "M2x6 self-tapping, 2 pcs",
    "right_screw": "M2x4 self-tapping, 2 pcs",
}


def cuboid(size, center):
    return v07.cuboid(size, center)


def cylinder(radius, height, center, sections=48):
    return v07.cylinder(radius, height, center, sections=sections)


def union(meshes):
    return v07.union(meshes)


def difference(base, cutters):
    return v07.difference(base, cutters)


def ensure_mesh(name, mesh):
    return v07.ensure_mesh(name, mesh)


def build_clamp(*, length: float, screw_pitch: float, rail_length: float):
    """Build a one-piece C-rail clamp in its installed orientation."""
    width = PARAMETERS["overall_width"]
    ear = PARAMETERS["screw_ear_thickness"]
    shelf = PARAMETERS["terminal_shelf_height"]
    cavity = PARAMETERS["terminal_cavity_height"]
    roof = PARAMETERS["terminal_roof_thickness"]
    total_height = shelf + cavity + roof
    outer_wall = PARAMETERS["terminal_outer_wall_thickness"]

    # Continuous low ear joins both screw bosses without increasing the screw
    # stack height.  The higher C-rail occupies only the GPIO span.
    low_ear = cuboid((width, length, ear), (0.0, 0.0, ear / 2.0))
    terminal_shelf = cuboid(
        (width, rail_length, shelf),
        (0.0, 0.0, shelf / 2.0),
    )
    outer_wall_body = cuboid(
        (outer_wall, rail_length, total_height),
        (-(width - outer_wall) / 2.0, 0.0, total_height / 2.0),
    )
    terminal_roof = cuboid(
        (width, rail_length, roof),
        (0.0, 0.0, shelf + cavity + roof / 2.0),
    )
    body = union([low_ear, terminal_shelf, outer_wall_body, terminal_roof])

    screw_y = screw_pitch / 2.0
    screw_cutters = [
        cylinder(
            PARAMETERS["screw_clearance_diameter"] / 2.0,
            ear + 0.6,
            (0.0, y, ear / 2.0),
            sections=48,
        )
        for y in (-screw_y, screw_y)
    ]

    # A continuous slot accepts any of the existing 2.54 mm GPIO positions,
    # so the clamp does not depend on a guessed first-pin offset or pin count.
    # The small +X offset biases each square pin toward one plated-hole wall.
    pin_slot = cuboid(
        (
            PARAMETERS["terminal_pin_slot_width"],
            rail_length + 0.4,
            shelf + 0.5,
        ),
        (
            PARAMETERS["terminal_pin_slot_offset"],
            0.0,
            shelf / 2.0,
        ),
    )
    return difference(body, [*screw_cutters, pin_slot])


def build_coupon_base():
    """Replicate PCB thickness and the V0.7 2.8 mm under-board clearance."""
    floor_thickness = 1.4
    pcb_bottom = floor_thickness + PARAMETERS["v07_under_board_clearance"]
    pcb_thickness = PARAMETERS["nominal_pcb_thickness"]
    pcb_top = pcb_bottom + pcb_thickness
    length = 24.0
    width = 10.0
    screw_pitch = 16.0

    floor = cuboid((width, length, floor_thickness), (0.0, 0.0, floor_thickness / 2.0))
    mock_pcb = cuboid((width, 20.0, pcb_thickness), (0.0, 0.0, pcb_bottom + pcb_thickness / 2.0))
    post_height = pcb_bottom - floor_thickness
    posts = [
        cylinder(2.9, post_height, (0.0, y, floor_thickness + post_height / 2.0), sections=48)
        for y in (-screw_pitch / 2.0, screw_pitch / 2.0)
    ]
    body = union([floor, mock_pcb, *posts])

    # Three nominal GPIO holes on 2.54 mm pitch plus two M2 pilot holes.
    gpio_cutters = [
        cylinder(0.55, pcb_thickness + 0.6, (0.0, y, pcb_bottom + pcb_thickness / 2.0), sections=40)
        for y in (-2.54, 0.0, 2.54)
    ]
    pilot_depth = 2.5
    pilot_cutters = [
        cylinder(
            0.85,
            pilot_depth + 0.3,
            (0.0, y, pcb_top - pilot_depth / 2.0),
            sections=40,
        )
        for y in (-screw_pitch / 2.0, screw_pitch / 2.0)
    ]
    return difference(body, [*gpio_cutters, *pilot_cutters])


def export_stl(name: str, mesh: trimesh.Trimesh) -> Path:
    path = OUTPUT / f"{name}.stl"
    path.write_bytes(trimesh.exchange.stl.export_stl(mesh))
    return path


def part_info(path: Path) -> dict:
    return v07.part_info(path)


def draw_preview(path: Path):
    image = Image.new("RGB", (1800, 1160), "#f7f5ee")
    draw = ImageDraw.Draw(image)
    title = v07.v06.load_font(42)
    body = v07.v06.load_font(25)
    small = v07.v06.load_font(21)
    draw.text((60, 42), "V0.7 ESP32 免焊杜邦公端子定位压板 Rev A", fill="#163a31", font=title)
    draw.text((60, 105), "外壳、中托和器件位置不变；只增加一条可拆卸绝缘压板", fill="#546b63", font=body)

    # Top view.
    draw.rounded_rectangle((70, 185, 930, 1030), radius=28, fill="#ffffff", outline="#adc1b8", width=4)
    draw.text((100, 215), "安装俯视图", fill="#173b32", font=body)
    board = (330, 290, 650, 940)
    draw.rounded_rectangle(board, radius=20, fill="#183b55", outline="#0b2638", width=4)
    draw.rectangle((365, 315, 615, 450), fill="#c7ccd0", outline="#69737a", width=3)
    draw.text((490, 375), "ESP32-S3", anchor="mm", fill="#183b55", font=body)
    draw.text((490, 475), "天线区域", anchor="mm", fill="#ffffff", font=small)

    # Left-row clamp and its two reused mounting screws.
    draw.rounded_rectangle((292, 304, 360, 926), radius=18, fill="#efb14a", outline="#7b5317", width=4)
    for y in (325, 905):
        draw.ellipse((310, y - 15, 340, y + 15), fill="#d9dde0", outline="#4f5960", width=3)
        draw.line((317, y, 333, y), fill="#4f5960", width=3)
    draw.text((270, 615), "定位压板", anchor="mm", fill="#7b5317", font=body)

    pin_ys = (365, 470, 565, 625, 670, 715, 760, 855)
    labels = PARAMETERS["wire_functions"]
    colors = ("#cc3333", "#d18c00", "#7b4aa5", "#2b73a6", "#2b9a88", "#5976c8", "#7a7a7a", "#111111")
    for y, label, color in zip(pin_ys, labels, colors):
        draw.ellipse((316, y - 7, 330, y + 7), fill="#e5d14c", outline="#5f5213", width=2)
        draw.line((331, y, 760, y + 24), fill=color, width=8)
        draw.text((674, y + 7), label, anchor="lm", fill="#263b35", font=small)
    draw.line((780, 480, 780, 885), fill="#9aa9a2", width=2)
    draw.rounded_rectangle((790, 520, 900, 870), radius=18, fill="#d9f0e8", outline="#2e7862", width=4)
    draw.text((845, 695), "DESPI\n-C02", anchor="mm", align="center", fill="#2e7862", font=small)
    draw.text((490, 975), "两颗 M2×6 固定压板；右侧两颗 M2×4 继续固定 ESP32", anchor="mm", fill="#52655e", font=small)

    # Cross-section.
    draw.rounded_rectangle((980, 185, 1730, 710), radius=28, fill="#ffffff", outline="#adc1b8", width=4)
    draw.text((1010, 215), "横截面原理", fill="#173b32", font=body)
    draw.rectangle((1050, 560, 1665, 600), fill="#4b806d", outline="#214b3e", width=3)
    draw.text((1400, 580), "ESP32 PCB", anchor="lm", fill="#263b35", font=small)
    draw.rectangle((1050, 600, 1665, 662), fill="#e7eee9", outline="#82948d", width=2)
    draw.text((1400, 632), "板下净空 2.8 mm", anchor="lm", fill="#52655e", font=small)
    # PETG C rail, male terminal and wire.
    draw.rectangle((1170, 410, 1235, 560), fill="#efb14a", outline="#7b5317", width=3)
    draw.rectangle((1235, 410, 1510, 445), fill="#efb14a", outline="#7b5317", width=3)
    draw.rectangle((1235, 520, 1510, 560), fill="#efb14a", outline="#7b5317", width=3)
    draw.rectangle((1310, 455, 1380, 515), fill="#c8a457", outline="#6e5518", width=3)
    draw.rectangle((1336, 515, 1354, 640), fill="#d6b22a", outline="#66550e", width=2)
    draw.arc((1370, 455, 1580, 650), 210, 315, fill="#cc3333", width=9)
    draw.text((1440, 430), "PETG压板", anchor="lm", fill="#7b5317", font=small)
    draw.text((1440, 480), "原厂压接金属端子", anchor="lm", fill="#594b1b", font=small)
    draw.text((1440, 530), "2.2 mm限位台阶", anchor="lm", fill="#52655e", font=small)
    draw.text((1440, 680), "针脚与中托间隙 0.6 mm", anchor="lm", fill="#52655e", font=small)

    draw.rounded_rectangle((980, 750, 1730, 1030), radius=28, fill="#eef5f1", outline="#adc1b8", width=4)
    notes = [
        "1. 男端先从黑色1P外壳中退出，保留原厂压接金属端子。",
        "2. 金属端子从压板开口侧装入，再插入对应GPIO孔。",
        "3. 线束轻拉向DESPI方向后，均匀锁紧两颗M2×6。",
        "4. 先打印检具；通过短路、接触电阻和摇线测试后再装正式件。",
    ]
    y = 785
    for note in notes:
        draw.text((1020, y), note, fill="#263b35", font=small)
        y += 55
    image.save(path)


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    PREVIEWS.mkdir(parents=True, exist_ok=True)
    PACKAGE_DIR.mkdir(parents=True, exist_ok=True)

    formal_clamp = ensure_mesh(
        "esp32_dupont_terminal_clamp_v0_7_rev_a",
        build_clamp(
            length=PARAMETERS["overall_length"],
            screw_pitch=PARAMETERS["mount_hole_pitch"],
            rail_length=PARAMETERS["terminal_rail_length"],
        ),
    )
    coupon_clamp = ensure_mesh(
        "fit_test_dupont_terminal_clamp_v0_7_rev_a",
        build_clamp(length=22.0, screw_pitch=16.0, rail_length=10.0),
    )
    coupon_base = ensure_mesh(
        "fit_test_dupont_terminal_base_v0_7_rev_a",
        build_coupon_base(),
    )

    parts = {
        "esp32_dupont_terminal_clamp_v0_7_rev_a": formal_clamp,
        "fit_test_dupont_terminal_clamp_v0_7_rev_a": coupon_clamp,
        "fit_test_dupont_terminal_base_v0_7_rev_a": coupon_base,
    }
    paths = {name: export_stl(name, mesh) for name, mesh in parts.items()}

    pin_protrusion = (
        PARAMETERS["nominal_male_pin_length"]
        - PARAMETERS["terminal_shelf_height"]
        - PARAMETERS["nominal_pcb_thickness"]
    )
    clearance_to_carrier = PARAMETERS["v07_under_board_clearance"] - pin_protrusion
    screw_engagement = 6.0 - PARAMETERS["screw_ear_thickness"] - PARAMETERS["nominal_pcb_thickness"]
    manifest = {
        "design": "V0.7 ESP32 solderless Dupont-terminal clamp Rev A",
        "units": "mm",
        "status": "fit coupon required before installation",
        "preserves": [
            "front_bezel_v0_7.stl unchanged",
            "electronics_carrier_v0_7.stl unchanged",
            "rear_cover_v0_7_rev_f_flat_left_wall_0p8mm.stl unchanged",
            "ESP32, BOOT, RESET, Lipo Rider, DESPI-C02 and battery positions unchanged",
            "120 x 184 x 19 mm exterior unchanged",
        ],
        "connection": {
            "method": "housing-free pre-crimped male Dupont terminal retained by PETG C-rail; no solder",
            "wire_functions": PARAMETERS["wire_functions"],
            "male_pin_housing": "remove the black 1P shell without cutting the crimped terminal",
            "wire_exit": "open side of rail toward board interior and DESPI-C02",
            "power_warning": "3V3 must never be connected to 5V, VIN or VBUS",
        },
        "fasteners": {
            "left_two": PARAMETERS["left_screw"],
            "right_two": PARAMETERS["right_screw"],
            "nominal_left_thread_engagement_mm": round(screw_engagement, 3),
        },
        "clearance": {
            "nominal_pin_protrusion_below_pcb_mm": round(pin_protrusion, 3),
            "v07_under_board_clearance_mm": PARAMETERS["v07_under_board_clearance"],
            "nominal_pin_to_carrier_clearance_mm": round(clearance_to_carrier, 3),
            "clamp_height_above_pcb_mm": round(
                PARAMETERS["terminal_shelf_height"]
                + PARAMETERS["terminal_cavity_height"]
                + PARAMETERS["terminal_roof_thickness"],
                3,
            ),
            "existing_esp32_component_envelope_mm": v07.P["esp_body_envelope"],
        },
        "coupon_acceptance": [
            "three terminals insert without cutting or forcing",
            "M2x6 screws tighten without bottoming out",
            "metal pins remain above the coupon floor",
            "formal assembly has no adjacent-pin short circuit",
            "each contact remains stable while each wire is gently moved",
            "DESPI 3V3 remains stable during a complete display refresh",
        ],
        "print": {
            "material": "PETG",
            "nozzle_mm": 0.4,
            "layer_height_mm": 0.16,
            "walls": 4,
            "supports": "none; rotate the clamp so the open C-channel faces upward",
            "scale": "100%; do not mirror",
        },
        "parameters": PARAMETERS,
        "parts": {name: part_info(path) for name, path in paths.items()},
    }
    manifest_path = OUTPUT / "dupont_terminal_clamp_manifest_v0_7_rev_a.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    preview = PREVIEWS / "esp32_dupont_terminal_clamp_v0_7_rev_a.png"
    draw_preview(preview)
    guide = ROOT / "DUPONT_TERMINAL_CLAMP_GUIDE_V0.7_REV_A.md"

    deliverables = [*paths.values(), manifest_path, preview, guide]
    for source in deliverables:
        shutil.copy2(source, PACKAGE_DIR / source.name)
    with zipfile.ZipFile(PACKAGE_ZIP, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for source in deliverables:
            archive.write(source, source.name)

    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    print(f"package={PACKAGE_ZIP}")


if __name__ == "__main__":
    main()
