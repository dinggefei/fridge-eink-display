#!/usr/bin/env python3
"""Generate the V0.5 carrier-to-rear-cover tolerance correction."""

from __future__ import annotations

import importlib.util
import json
import math
from pathlib import Path
import shutil
import zipfile

from PIL import Image, ImageDraw, ImageFont
import trimesh


ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "output"
PREVIEWS = ROOT / "previews"
V04_FILE = ROOT.parent / "enclosure_v0_4" / "generate_enclosure_v0_4.py"


def load_v04_module():
    spec = importlib.util.spec_from_file_location("rfm_enclosure_v04", V04_FILE)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load V0.4 generator: {V04_FILE}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


v04 = load_v04_module()
P = dict(v04.P)
P.update(
    {
        # V0.4 had only 0.4 mm clearance per side.  V0.5 increases this to
        # 0.8 mm per side while retaining the 128 x 200 mm outer envelope.
        "rear_inner_width": 124.6,
        "rear_inner_height": 196.6,
        # 2026-08-22: move the complete ESP32 assembly 25 mm toward the top
        # charging edge.  Lipo Rider stays in place; their X envelopes remain
        # separated, so the overlapping Y ranges do not create a collision.
        "esp_center_y": 45.00,
        # Waveshare ESP32-S3-DEV-KIT-N8R8 official mechanical drawing.
        # Board-side button coordinates are kept in carrier coordinates; the
        # rear-cover openings are mirrored separately for the outside view.
        "esp_board_width": 25.40,
        "esp_board_height": 63.30,
        "esp_mount_hole_diameter": 2.00,
        # 2026-08-22: use the user's physical N16R8 measurements.  The
        # official drawing's 1.80 mm corner offsets are also consistent with
        # an approximately 59.70 mm nominal longitudinal pitch.
        "esp_mount_pitch_x": 22.00,
        "esp_mount_pitch_y": 60.00,
        "esp_mount_bottom_offset_y": -30.00,
        "esp_mount_top_offset_y": 30.00,
        # M2 x 4 self-tapping screw through a nominal 1.6 mm PCB leaves
        # 2.4 mm engagement.  A 2.5 mm blind pilot gives 0.1 mm axial margin.
        "esp_mount_post_diameter": 5.80,
        "esp_mount_post_top": 4.60,
        "esp_mount_pilot": 1.70,
        "esp_mount_pilot_depth": 2.50,
        "esp_board_thickness": 1.60,
        "esp_mount_screw_length": 4.00,
        # The USB-side mounting holes are close to BOOT/RESET.  A compact head
        # plus a thin non-metallic tool keeps both rear access paths usable.
        "esp_screw_head_max_diameter": 3.60,
        "esp_button_tool_max_diameter": 1.50,
    }
)
v04.P = P
v04.v03.P = P
v04.v03.v01.P = P

# Ten Ø10 x 3 mm magnets, redistributed away from the ESP32 PCB antenna,
# ESP32 board body, DESPI-C02 and Lipo Rider Plus.  These coordinates describe
# the installed/component-side projection because that is the view in which
# electrical clearance matters.
MAGNETS_ASSEMBLED_V05 = [
    (-52.0, -70.0),
    (0.0, -70.0),
    (52.0, -70.0),
    (-52.0, -40.0),
    (0.0, -40.0),
    (52.0, -40.0),
    (-52.0, -10.0),
    (0.0, 30.0),
    (52.0, 35.0),
    (52.0, 70.0),
]
# The rear cover flips left-to-right when closed.  Store the blind pockets in
# rear-cover model coordinates so their installed projections land at the
# safety-reviewed positions above.  The Ø10.4 x 3.2 mm pockets retain the
# proven 0.2 mm radial/depth allowance and 0.8 mm PETG outer skin.
MAGNETS_V05 = [(-x, y) for x, y in MAGNETS_ASSEMBLED_V05]
v04.v03.MAGNETS = list(MAGNETS_V05)
# V0.4 calculated these module-level coordinates before V0.5 overrode the
# board centre.  Recalculate them so the rear-cover holes follow the board.
v04.BOOT_CENTRE = (
    P["esp_center_x"] + v04.BOOT_OFFSET[0],
    P["esp_center_y"] + v04.BOOT_OFFSET[1],
)
v04.RESET_CENTRE = (
    P["esp_center_x"] + v04.RESET_OFFSET[0],
    P["esp_center_y"] + v04.RESET_OFFSET[1],
)

# The rear cover is viewed and operated from its outside (-Z).  That view is
# mirrored left-to-right relative to the component-side (+Z) carrier layout.
# Store the holes in rear-cover model coordinates so BOOT and RESET appear on
# the left in the physical bottom view while still landing over the buttons
# after the cover is flipped closed.
REAR_BOOT_CENTRE = (-v04.BOOT_CENTRE[0], v04.BOOT_CENTRE[1])
REAR_RESET_CENTRE = (-v04.RESET_CENTRE[0], v04.RESET_CENTRE[1])

REAR_LABEL_DEPTH = 0.55
REAR_LABEL_PIXEL = 0.45
REAR_LABEL_GAP = 0.45
REAR_LABEL_OFFSET_Y = -7.20
REAR_LABEL_PIXEL_OVERLAP = 0.04

# V0.3 introduced two 12 x 2 mm pressure/air-relief slots in the bottom wall.
# V0.5 closes both slots at the user's request while retaining the top USB-C
# charging opening.  The plugs overlap the surrounding wall by 0.2-0.6 mm so
# the exported rear cover remains one watertight body.
LEGACY_BOTTOM_RELIEF_CENTRES = [(17.0, -99.0, 7.0), (35.0, -99.0, 7.0)]

BITMAP_FONT_5X7 = {
    "B": ("11110", "10001", "10001", "11110", "10001", "10001", "11110"),
    "E": ("11111", "10000", "10000", "11110", "10000", "10000", "11111"),
    "O": ("01110", "10001", "10001", "10001", "10001", "10001", "01110"),
    "R": ("11110", "10001", "10001", "11110", "10100", "10010", "10001"),
    "S": ("01111", "10000", "10000", "01110", "00001", "00001", "11110"),
    "T": ("11111", "00100", "00100", "00100", "00100", "00100", "00100"),
}


ESP_MOUNT_OFFSETS = [
    (-P["esp_mount_pitch_x"] / 2.0, P["esp_mount_bottom_offset_y"]),
    (P["esp_mount_pitch_x"] / 2.0, P["esp_mount_bottom_offset_y"]),
    (-P["esp_mount_pitch_x"] / 2.0, P["esp_mount_top_offset_y"]),
    (P["esp_mount_pitch_x"] / 2.0, P["esp_mount_top_offset_y"]),
]
ESP_MOUNT_HOLES = [
    (P["esp_center_x"] + dx, P["esp_center_y"] + dy)
    for dx, dy in ESP_MOUNT_OFFSETS
]


def rear_label_cutters(text: str, center_x: float, center_y: float):
    """Return shallow 5x7 recessed lettering readable from the outside.

    The rear exterior is viewed from -Z, so each glyph is mirrored in model X
    and becomes normally readable after the rear cover is turned over.
    """
    pixel = REAR_LABEL_PIXEL
    char_width = 5.0 * pixel
    text_width = len(text) * char_width + (len(text) - 1) * REAR_LABEL_GAP
    cutters = []
    for char_index, char in enumerate(text):
        rows = BITMAP_FONT_5X7[char]
        char_visual_left = -text_width / 2.0 + char_index * (char_width + REAR_LABEL_GAP)
        for row_index, row in enumerate(rows):
            for column_index, enabled in enumerate(row):
                if enabled != "1":
                    continue
                visual_x = char_visual_left + (column_index + 0.5) * pixel
                visual_y = (3.0 - row_index) * pixel
                model_x = center_x - visual_x
                model_y = center_y + visual_y
                cutters.append(
                    v04.v03.cuboid(
                        (
                            pixel + REAR_LABEL_PIXEL_OVERLAP,
                            pixel + REAR_LABEL_PIXEL_OVERLAP,
                            REAR_LABEL_DEPTH + 0.3,
                        ),
                        (model_x, model_y, REAR_LABEL_DEPTH / 2.0),
                    )
                )
    return cutters


def build_rear_cover_v05():
    """Rear cover with correctly mirrored access holes and recessed labels."""
    body = v04.v03.build_rear_cover()
    outer_y = -P["case_height"] / 2.0
    inner_y = -P["rear_inner_height"] / 2.0
    plug_inner_overlap = 0.6
    plug_depth_y = inner_y + plug_inner_overlap - outer_y
    plug_center_y = outer_y + plug_depth_y / 2.0
    relief_plugs = [
        v04.v03.cuboid(
            (12.4, plug_depth_y, 2.4),
            (x, plug_center_y, z),
        )
        for x, _y, z in LEGACY_BOTTOM_RELIEF_CENTRES
    ]
    body = v04.v03.union([body, *relief_plugs])
    cutters = []
    through_radius = P["esp_button_access_diameter"] / 2.0
    counterbore_radius = P["esp_button_counterbore_diameter"] / 2.0
    for x, y in (REAR_BOOT_CENTRE, REAR_RESET_CENTRE):
        cutters.append(v04.v03.cylinder(through_radius, 7.0, (x, y, 2.5), sections=48))
        cutters.append(
            v04.v03.cylinder(
                counterbore_radius,
                P["esp_button_counterbore_depth"] + 0.2,
                (x, y, P["esp_button_counterbore_depth"] / 2.0),
                sections=64,
            )
        )
    cutters.extend(
        rear_label_cutters(
            "BOOT",
            REAR_BOOT_CENTRE[0],
            REAR_BOOT_CENTRE[1] + REAR_LABEL_OFFSET_Y,
        )
    )
    cutters.extend(
        rear_label_cutters(
            "RESET",
            REAR_RESET_CENTRE[0],
            REAR_RESET_CENTRE[1] + REAR_LABEL_OFFSET_Y,
        )
    )
    return v04.v03.difference(body, cutters)


def esp_mount_posts(holes=ESP_MOUNT_HOLES):
    """Four independent bosses under the board's native mounting holes."""
    base_top = P["midplate_thickness"] - 0.2
    post_top = P["esp_mount_post_top"]
    height = post_top - base_top
    return [
        v04.v03.cylinder(
            P["esp_mount_post_diameter"] / 2.0,
            height,
            (x, y, base_top + height / 2.0),
            sections=48,
        )
        for x, y in holes
    ]


def esp_mount_pilot_cutters(holes=ESP_MOUNT_HOLES):
    """Blind pilots sized for M2 x 4 self-tapping screws."""
    depth = P["esp_mount_pilot_depth"]
    top = P["esp_mount_post_top"]
    cutter_height = depth + 0.2
    cutter_z = top - depth / 2.0 + 0.1
    return [
        v04.v03.cylinder(
            P["esp_mount_pilot"] / 2.0,
            cutter_height,
            (x, y, cutter_z),
            sections=40,
        )
        for x, y in holes
    ]


def build_middle_carrier_v05():
    """V0.5 carrier with four-point ESP32 screw mounting.

    All non-ESP geometry is intentionally retained from V0.3/V0.4.  Only the
    four ESP strap slots are removed and replaced by four screw bosses.
    """
    v03 = v04.v03
    base = v03.v01.rounded_prism(
        P["midplate_width"], P["midplate_height"], 4.0, P["midplate_thickness"]
    )
    body = v03.union(
        [
            base,
            *v03.battery_guides(),
            *v03.despi_guides(),
            *v03.lipo_mount_posts(),
            *esp_mount_posts(),
            *v03.rear_insert_bosses(),
        ]
    )

    cutters = []

    # Screen FPC relief and the existing front/rear fastener holes.
    cutters.append(v03.cuboid((8.0, 36.0, 6.0), (60.0, P["despi_center_y"], 1.0)))
    for x, y in v03.FRONT_FASTENERS:
        cutters.append(v03.cylinder(P["m2_clearance"] / 2.0, 5.0, (x, y, 1.0), sections=36))

    rear_boss_height = 5.0
    for x, y in v03.REAR_FASTENERS:
        cutters.append(
            v03.cylinder(
                P["m2_insert_hole"] / 2.0,
                4.7,
                (x, y, P["midplate_thickness"] + rear_boss_height - 4.7 / 2.0 + 0.1),
                sections=36,
            )
        )

    # Existing Lipo Rider mounting pilots.
    for x, y in v03.LIPO_MOUNT_HOLES:
        cutters.append(v03.cylinder(P["lipo_mount_pilot"] / 2.0, 3.3, (x, y, 3.25), sections=36))

    # New ESP32 four-point screw mounting.  There are deliberately no ESP
    # strap slots in this version.
    cutters.extend(esp_mount_pilot_cutters())

    # DESPI and battery straps are unchanged.
    cutters.append(v03.slot(P["despi_center_x"], -22.5, 12.0, 3.0))
    cutters.append(v03.slot(P["despi_center_x"], 10.5, 12.0, 3.0))
    for x in (-20.0, 24.0):
        cutters.append(v03.slot(x, -23.0, 12.0, 3.0))
        cutters.append(v03.slot(x, -92.5, 12.0, 3.0))

    # Existing cable-management anchors are unchanged.
    cutters.append(v03.slot(-3.5, -2.0, 8.0, 3.0))
    cutters.append(v03.slot(-3.5, 44.0, 8.0, 3.0))
    cutters.append(v03.slot(46.0, 35.0, 8.0, 3.0))
    cutters.append(v03.slot(46.0, 22.0, 8.0, 3.0))
    return v03.difference(body, cutters)


def build_esp_mount_fit_coupon():
    """Low-cost four-hole coupon for validating the real ESP32 before a full print."""
    base = v04.v03.v01.rounded_prism(31.4, 69.3, 2.0, P["midplate_thickness"])
    body = v04.v03.union([base, *esp_mount_posts(ESP_MOUNT_OFFSETS)])
    cutters = esp_mount_pilot_cutters(ESP_MOUNT_OFFSETS)
    # USB-side orientation notch; this does not affect the four-hole test.
    cutters.append(v04.v03.cuboid((9.0, 3.0, 4.0), (0.0, -34.65, 1.0)))
    return v04.v03.difference(body, cutters)


def intersection(meshes):
    return trimesh.boolean.intersection(meshes, engine="manifold")


def translated(mesh, xyz):
    result = mesh.copy()
    result.apply_translation(xyz)
    return result


def build_fit_corners(carrier, rear_cover):
    """Return the carrier top-right and mating rear-cover top-left coupons.

    The rear cover mirrors X when it closes over the carrier.  Cropping the
    same side from both source parts (the pre-2026-08-16 V0.5 behavior) makes
    the coupon screw holes impossible to align after the carrier is flipped.
    """
    carrier_crop = v04.v03.cuboid((36.0, 37.0, 26.0), (46.0, 81.5, 10.0))
    rear_crop = v04.v03.cuboid((36.0, 37.0, 26.0), (-46.0, 81.5, 10.0))
    carrier_corner = intersection([carrier, carrier_crop])
    rear_corner = intersection([rear_cover, rear_crop])
    return (
        translated(carrier_corner, (-28.0, -63.0, 0.0)),
        translated(rear_corner, (64.0, -63.0, 0.0)),
    )


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


def draw_clearance_diagram(path: Path):
    image = Image.new("RGB", (1400, 1900), "#f5f3ed")
    draw = ImageDraw.Draw(image)
    title_font = load_font(48)
    label_font = load_font(30)
    small_font = load_font(25)
    scale = 7.6
    cx, cy = 700, 950

    def rect(w, h, color, width):
        return (
            cx - w * scale / 2,
            cy - h * scale / 2,
            cx + w * scale / 2,
            cy + h * scale / 2,
        ), color, width

    draw.text((70, 45), "V0.5 托板与后盖装配公差", fill="#17352b", font=title_font)
    box, color, width = rect(P["case_width"], P["case_height"], "#304d70", 8)
    draw.rounded_rectangle(box, radius=40, outline=color, width=width)
    box, color, width = rect(P["rear_inner_width"], P["rear_inner_height"], "#bf7d26", 7)
    draw.rounded_rectangle(box, radius=34, outline=color, width=width)
    box, color, width = rect(P["midplate_width"], P["midplate_height"], "#2b7a5e", 7)
    draw.rounded_rectangle(box, radius=30, outline=color, width=width)

    draw.text((80, 1610), "蓝：后盖外轮廓 128 × 200 mm", fill="#304d70", font=label_font)
    draw.text((80, 1660), "橙：后盖内腔 124.6 × 196.6 mm", fill="#bf7d26", font=label_font)
    draw.text((80, 1710), "绿：中层托板 123 × 195 mm", fill="#2b7a5e", font=label_font)
    draw.text((80, 1780), "托板与内腔：总间隙 1.6 mm，每边 0.8 mm", fill="#9d2f2a", font=label_font)
    draw.text((80, 1825), "后盖侧壁 1.7 mm；承托台阶有效搭接 1.2 mm", fill="#17352b", font=small_font)
    image.save(path)


def draw_esp_mount_alignment(path: Path):
    """Render the four screws and existing rear-cover button holes together."""
    image = Image.new("RGB", (1400, 1900), "#f5f3ed")
    draw = ImageDraw.Draw(image)
    title_font = load_font(46)
    label_font = load_font(29)
    small_font = load_font(24)
    scale = 17.0
    cx, cy = 700, 910

    def point(x, y):
        return cx + x * scale, cy - y * scale

    draw.text((65, 45), "V0.5 ESP32 四孔螺丝固定与按键对位", fill="#17352b", font=title_font)
    left = -P["esp_board_width"] / 2.0
    right = P["esp_board_width"] / 2.0
    bottom = -P["esp_board_height"] / 2.0
    top = P["esp_board_height"] / 2.0
    x0, y0 = point(left, top)
    x1, y1 = point(right, bottom)
    draw.rounded_rectangle((x0, y0, x1, y1), radius=16, fill="#bcd7ef", outline="#3f6f9e", width=6)
    draw.text((cx - 48, y0 - 55), "天线端", fill="#17352b", font=label_font)
    draw.text((cx - 55, y1 - 70), "USB-C 端", fill="#17352b", font=small_font)

    for index, (x, y) in enumerate(ESP_MOUNT_OFFSETS, start=1):
        px, py = point(x, y)
        post_r = P["esp_mount_post_diameter"] / 2.0 * scale
        head_r = P["esp_screw_head_max_diameter"] / 2.0 * scale
        draw.ellipse((px - post_r, py - post_r, px + post_r, py + post_r), fill="#d7b55b", outline="#8b6417", width=4)
        draw.ellipse((px - head_r, py - head_r, px + head_r, py + head_r), fill="#70777e", outline="#30363b", width=3)
        label_x = px - 105 if x < 0 else px + 38
        draw.text((label_x, py - 16), f"M2-{index}", fill="#17352b", font=small_font)

    for label, absolute in (("BOOT", v04.BOOT_CENTRE), ("RESET", v04.RESET_CENTRE)):
        relative = (absolute[0] - P["esp_center_x"], absolute[1] - P["esp_center_y"])
        px, py = point(*relative)
        access_r = P["esp_button_counterbore_diameter"] / 2.0 * scale
        through_r = P["esp_button_access_diameter"] / 2.0 * scale
        draw.ellipse((px - access_r, py - access_r, px + access_r, py + access_r), outline="#d9463e", width=5)
        draw.ellipse((px - through_r, py - through_r, px + through_r, py + through_r), outline="#d9463e", width=3)
        draw.text((px - 48, py + access_r + 12), label, fill="#a62e28", font=small_font)

    draw.text((70, 1570), "四个蓝板原生孔全部使用：Ø2.0 mm", fill="#17352b", font=label_font)
    draw.text((70, 1620), "实测孔距：横向 22.00 mm；纵向 60.00 mm", fill="#17352b", font=label_font)
    draw.text((70, 1670), "固定：4 × M2×4 自攻螺丝；螺钉头直径 ≤ 3.6 mm", fill="#17352b", font=label_font)
    draw.text((70, 1720), "下方两颗螺钉禁止加垫圈，以免遮挡 BOOT/RESET", fill="#9d2f2a", font=label_font)
    draw.text((70, 1785), "ESP 与后盖双孔同步向顶部移动 25.00 mm", fill="#2b7a5e", font=label_font)
    draw.text((70, 1835), "先打印四孔检具并用真实板卡试装，通过后再打印完整中托。", fill="#17352b", font=small_font)
    image.save(path)


def draw_carrier_layout_v05(path: Path):
    """Full carrier layout with the new posts superimposed on V0.4 geometry."""
    v04.draw_layout(path)
    image = Image.open(path).convert("RGB")
    draw = ImageDraw.Draw(image)
    width, height = image.size
    margin = 120
    scale = min(
        (width - 2 * margin) / P["midplate_width"],
        (height - 2 * margin) / P["midplate_height"],
    )
    title_font = load_font(42)
    small_font = load_font(23)

    def point(x, y):
        return width / 2 + x * scale, height / 2 - y * scale

    draw.rectangle((55, 25, 930, 100), fill="#f4f2ec")
    draw.text((65, 35), "V0.5 中层托板：ESP32 四孔固定", fill="#17352b", font=title_font)
    for index, (x, y) in enumerate(ESP_MOUNT_HOLES, start=1):
        px, py = point(x, y)
        post_r = P["esp_mount_post_diameter"] / 2.0 * scale
        pilot_r = P["esp_mount_pilot"] / 2.0 * scale
        draw.ellipse((px - post_r, py - post_r, px + post_r, py + post_r), outline="#0b6fbd", width=5)
        draw.ellipse((px - pilot_r, py - pilot_r, px + pilot_r, py + pilot_r), fill="#0b6fbd")
        draw.text((px + 10, py - 28), str(index), fill="#0b6fbd", font=small_font)
    draw.rectangle((55, 1590, 1145, 1685), fill="#f4f2ec")
    draw.text(
        (70, 1610),
        "蓝圈：4 个 Ø5.8 螺丝柱；蓝点：Ø1.7 盲孔；ESP 与后盖双孔同步上移 25 mm",
        fill="#17352b",
        font=small_font,
    )
    image.save(path)


def draw_placement_svg_v05(path: Path):
    """Extend the proven 1:1 layout with the four exact ESP mounting holes."""
    v04.draw_placement_svg(path)
    svg = path.read_text(encoding="utf-8")
    items = []
    for index, (x, y) in enumerate(ESP_MOUNT_HOLES, start=1):
        sx = x + P["midplate_width"] / 2.0
        sy = P["midplate_height"] / 2.0 - y
        items.append(
            f'<circle cx="{sx:.3f}" cy="{sy:.3f}" r="1.000" fill="none" '
            f'stroke="#0b6fbd" stroke-width="0.35"/>'
        )
        items.append(
            f'<text x="{sx + 2.0:.3f}" y="{sy + 0.8:.3f}" font-size="2.2">M{index}</text>'
        )
    items.append('<text x="3" y="188" font-size="2.5" fill="#0b6fbd">ESP holes: 22.00 x 60.00 mm / M2x4 / measured N16R8</text>')
    path.write_text(svg.replace("</svg>", "  " + "".join(items) + "\n</svg>"), encoding="utf-8")


def draw_rear_hole_svg_v05(path: Path):
    """Create a 1:1 template as seen from the physical rear exterior."""
    w, h = P["case_width"], P["case_height"]
    items = [
        f'<rect x="0.2" y="0.2" width="{w - 0.4}" height="{h - 0.4}" '
        'rx="6" fill="white" stroke="#111" stroke-width="0.4"/>'
    ]
    for label, (x, y) in (("BOOT", REAR_BOOT_CENTRE), ("RESET", REAR_RESET_CENTRE)):
        # Outside (-Z) view mirrors model X.
        sx, sy = w / 2.0 - x, h / 2.0 - y
        items.append(
            f'<circle cx="{sx:.3f}" cy="{sy:.3f}" r="2.75" fill="none" '
            'stroke="#d9463e" stroke-width="0.4"/>'
        )
        items.append(
            f'<circle cx="{sx:.3f}" cy="{sy:.3f}" r="4.25" fill="none" '
            'stroke="#d9463e" stroke-dasharray="1,1" stroke-width="0.25"/>'
        )
        items.append(
            f'<text x="{sx:.3f}" y="{sy + 7.2:.3f}" text-anchor="middle" '
            f'font-size="3">{label}</text>'
        )
    port_x = w / 2.0 - P["charge_cutout_width"] / 2.0
    items.append(
        f'<rect x="{port_x:.3f}" y="0" width="{P["charge_cutout_width"]:.3f}" '
        'height="4.5" fill="none" stroke="#735497" stroke-width="0.4"/>'
    )
    items.append(
        f'<text x="{w / 2.0:.3f}" y="8" text-anchor="middle" '
        'font-size="3">USB-C top centre</text>'
    )
    for x, y in MAGNETS_V05:
        sx, sy = w / 2.0 - x, h / 2.0 - y
        items.append(
            f'<circle cx="{sx:.3f}" cy="{sy:.3f}" r="{P["magnet_diameter"] / 2.0:.3f}" '
            'fill="none" stroke="#6b7280" stroke-dasharray="1.5,1" stroke-width="0.25"/>'
        )
    svg = f'''<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="{w}mm" height="{h}mm" viewBox="0 0 {w} {h}">
  {''.join(items)}
  <text x="4" y="196" font-size="2.8">OUTSIDE BOTTOM VIEW - print at 100% - no mirroring</text>
</svg>
'''
    path.write_text(svg, encoding="utf-8")


def draw_rear_bottom_view(path: Path):
    """Render the rear exterior orientation, including recessed labels."""
    width, height = 1300, 1900
    margin = 120
    scale = min(
        (width - 2 * margin) / P["case_width"],
        (height - 2 * margin) / P["case_height"],
    )
    image = Image.new("RGB", (width, height), "#f5f3ed")
    draw = ImageDraw.Draw(image)
    title_font = load_font(44)
    label_font = load_font(27)
    small_font = load_font(23)
    cx, cy = width / 2.0, height / 2.0

    def outside_point(x, y):
        return cx - x * scale, cy - y * scale

    x0, y0 = outside_point(P["case_width"] / 2.0, P["case_height"] / 2.0)
    x1, y1 = outside_point(-P["case_width"] / 2.0, -P["case_height"] / 2.0)
    draw.rounded_rectangle((x0, y0, x1, y1), radius=42, fill="#ffffff", outline="#17352b", width=6)
    draw.text((55, 35), "V0.5 后盖外侧底视图", fill="#17352b", font=title_font)

    for label, (x, y) in (("BOOT", REAR_BOOT_CENTRE), ("RESET", REAR_RESET_CENTRE)):
        px, py = outside_point(x, y)
        outer_r = P["esp_button_counterbore_diameter"] / 2.0 * scale
        inner_r = P["esp_button_access_diameter"] / 2.0 * scale
        draw.ellipse((px - outer_r, py - outer_r, px + outer_r, py + outer_r), outline="#d9463e", width=5)
        draw.ellipse((px - inner_r, py - inner_r, px + inner_r, py + inner_r), outline="#d9463e", width=3)
        box = draw.textbbox((0, 0), label, font=label_font)
        draw.text((px - (box[2] - box[0]) / 2.0, py + outer_r + 10), label, fill="#a62e28", font=label_font)

    for index, (x, y) in enumerate(MAGNETS_V05, start=1):
        px, py = outside_point(x, y)
        radius = P["magnet_diameter"] / 2.0 * scale
        draw.ellipse((px - radius, py - radius, px + radius, py + radius), outline="#6b7280", width=3)
        draw.text((px - 8, py - 11), str(index), fill="#6b7280", font=small_font)

    charge_x, _ = outside_point(P["charge_cutout_center_x"], P["case_height"] / 2.0)
    port_w = P["charge_cutout_width"] * scale
    draw.rectangle((charge_x - port_w / 2.0, y0 - 3, charge_x + port_w / 2.0, y0 + 28), outline="#735497", width=5)
    draw.text((charge_x - 105, y0 + 38), "顶部 USB-C", fill="#735497", font=small_font)
    draw.text((60, 1810), "10 × Ø10×3 mm 磁铁；灰圈为内侧盲孔投影", fill="#6b7280", font=small_font)
    draw.text((60, 1850), "观察方向：从后盖外表面看；BOOT/RESET 位于左侧", fill="#17352b", font=small_font)
    image.save(path)


def circle_to_rect_clearance(point, rect):
    """Return planar edge clearance from one magnet pocket to a rectangle."""
    x, y = point
    x0, x1, y0, y1 = rect
    dx = max(x0 - x, 0.0, x - x1)
    dy = max(y0 - y, 0.0, y - y1)
    return math.hypot(dx, dy) - P["magnet_diameter"] / 2.0


def magnet_electronics_clearances():
    """Conservative planar clearances in the assembled component-side view."""
    esp_rect = (
        P["esp_center_x"] - P["esp_board_width"] / 2.0,
        P["esp_center_x"] + P["esp_board_width"] / 2.0,
        P["esp_center_y"] - P["esp_board_height"] / 2.0,
        P["esp_center_y"] + P["esp_board_height"] / 2.0,
    )
    # The top 15 mm of the ESP32 board envelope is conservatively treated as
    # the complete PCB-antenna region.
    antenna_rect = (esp_rect[0], esp_rect[1], esp_rect[3] - 15.0, esp_rect[3])
    despi_rect = (
        P["despi_center_x"] - P["despi_width"] / 2.0,
        P["despi_center_x"] + P["despi_width"] / 2.0,
        P["despi_center_y"] - P["despi_height"] / 2.0,
        P["despi_center_y"] + P["despi_height"] / 2.0,
    )
    lipo_rect = (
        P["lipo_rider_center_x"] - P["lipo_rider_width"] / 2.0,
        P["lipo_rider_center_x"] + P["lipo_rider_width"] / 2.0,
        P["lipo_rider_center_y"] - P["lipo_rider_height"] / 2.0,
        P["lipo_rider_center_y"] + P["lipo_rider_height"] / 2.0,
    )
    rectangles = {
        "esp32_board": esp_rect,
        "esp32_pcb_antenna": antenna_rect,
        "despi_c02": despi_rect,
        "lipo_rider_plus": lipo_rect,
    }
    return {
        name: round(
            min(circle_to_rect_clearance(point, rect) for point in MAGNETS_ASSEMBLED_V05),
            3,
        )
        for name, rect in rectangles.items()
    }


def draw_magnet_clearance_layout(path: Path):
    """Show the installed magnet projections and electronics keep-out result."""
    width, height = 1300, 1900
    margin = 120
    scale = min(
        (width - 2 * margin) / P["case_width"],
        (height - 2 * margin) / P["case_height"],
    )
    image = Image.new("RGB", (width, height), "#f5f3ed")
    draw = ImageDraw.Draw(image)
    title_font = load_font(42)
    label_font = load_font(24)
    small_font = load_font(21)
    cx, cy = width / 2.0, height / 2.0

    def point(x, y):
        return cx + x * scale, cy - y * scale

    def rectangle(cx_mm, cy_mm, w_mm, h_mm, fill, outline, label):
        x0, y0 = point(cx_mm - w_mm / 2.0, cy_mm + h_mm / 2.0)
        x1, y1 = point(cx_mm + w_mm / 2.0, cy_mm - h_mm / 2.0)
        draw.rounded_rectangle((x0, y0, x1, y1), radius=12, fill=fill, outline=outline, width=4)
        box = draw.textbbox((0, 0), label, font=small_font)
        draw.text(
            ((x0 + x1 - (box[2] - box[0])) / 2.0, (y0 + y1 - (box[3] - box[1])) / 2.0),
            label,
            fill=outline,
            font=small_font,
        )

    x0, y0 = point(-P["case_width"] / 2.0, P["case_height"] / 2.0)
    x1, y1 = point(P["case_width"] / 2.0, -P["case_height"] / 2.0)
    draw.rounded_rectangle((x0, y0, x1, y1), radius=42, fill="#ffffff", outline="#17352b", width=6)
    draw.text((48, 30), "V0.5 磁铁与电子器件安全位置图", fill="#17352b", font=title_font)

    rectangle(
        P["battery_center_x"], P["battery_center_y"],
        P["battery_width"], P["battery_height"],
        "#fff3cf", "#a56d00", "806090 电池",
    )
    rectangle(
        P["despi_center_x"], P["despi_center_y"],
        P["despi_width"], P["despi_height"],
        "#d9f2e8", "#28765e", "DESPI-C02",
    )
    rectangle(
        P["lipo_rider_center_x"], P["lipo_rider_center_y"],
        P["lipo_rider_width"], P["lipo_rider_height"],
        "#e8e0f3", "#735497", "Lipo Rider",
    )
    rectangle(
        P["esp_center_x"], P["esp_center_y"],
        P["esp_board_width"], P["esp_board_height"],
        "#dceaf7", "#315f8c", "ESP32-S3",
    )
    antenna_cy = P["esp_center_y"] + P["esp_board_height"] / 2.0 - 7.5
    ax0, ay0 = point(P["esp_center_x"] - P["esp_board_width"] / 2.0, antenna_cy + 7.5)
    ax1, ay1 = point(P["esp_center_x"] + P["esp_board_width"] / 2.0, antenna_cy - 7.5)
    draw.rectangle((ax0, ay0, ax1, ay1), outline="#d9463e", width=5)
    draw.text((ax0 + 6, ay0 + 5), "PCB 天线", fill="#a62e28", font=small_font)

    for index, (x, y) in enumerate(MAGNETS_ASSEMBLED_V05, start=1):
        px, py = point(x, y)
        radius = P["magnet_diameter"] / 2.0 * scale
        draw.ellipse(
            (px - radius, py - radius, px + radius, py + radius),
            fill="#c9ced6",
            outline="#4b5563",
            width=4,
        )
        draw.text((px - 8, py - 11), str(index), fill="#111827", font=small_font)

    clearances = magnet_electronics_clearances()
    draw.rectangle((45, 1675, 1255, 1860), fill="#eef7f2", outline="#28765e", width=3)
    draw.text((65, 1695), "装配视图：负 X 在左，顶部 USB-C 方向为 Y+", fill="#17352b", font=label_font)
    draw.text(
        (65, 1740),
        f"最小平面净距  天线 {clearances['esp32_pcb_antenna']:.2f} mm  "
        f"ESP32 {clearances['esp32_board']:.2f} mm  DESPI {clearances['despi_c02']:.2f} mm",
        fill="#17352b",
        font=small_font,
    )
    draw.text(
        (65, 1780),
        f"Lipo Rider {clearances['lipo_rider_plus']:.2f} mm；灰圈为 10 颗 Ø10×3 mm 磁铁的安装投影",
        fill="#17352b",
        font=small_font,
    )
    draw.text((65, 1820), "此图是装好后的相对位置，不是后盖 STL 原始建模视图。", fill="#6b7280", font=small_font)
    image.save(path)


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    PREVIEWS.mkdir(parents=True, exist_ok=True)

    carrier = v04.v03.ensure_mesh("middle_carrier_v0_5", build_middle_carrier_v05())
    rear_cover = v04.v03.ensure_mesh("rear_cover_v0_5", build_rear_cover_v05())
    carrier_corner, rear_corner = build_fit_corners(carrier, rear_cover)

    meshes = {
        "middle_carrier_v0_5": carrier,
        "rear_cover_v0_5": rear_cover,
        "fit_test_carrier_corner_v0_5": v04.v03.ensure_mesh("fit_test_carrier_corner_v0_5", carrier_corner),
        "fit_test_rear_corner_v0_5": v04.v03.ensure_mesh("fit_test_rear_corner_v0_5", rear_corner),
        "fit_test_lipo_top_port_v0_5": v04.v03.ensure_mesh("fit_test_lipo_top_port_v0_5", v04.v03.build_lipo_port_fit_coupon()),
        "fit_test_button_hole_diameter_v0_5": v04.v03.ensure_mesh("fit_test_button_hole_diameter_v0_5", v04.build_button_hole_coupon()),
        "fit_test_esp32_four_hole_mount_v0_5": v04.v03.ensure_mesh(
            "fit_test_esp32_four_hole_mount_v0_5", build_esp_mount_fit_coupon()
        ),
    }
    paths = {}
    for name, mesh in meshes.items():
        path = OUTPUT / f"{name}.stl"
        path.write_bytes(trimesh.exchange.stl.export_stl(mesh))
        paths[name] = path

    placement_path = OUTPUT / "placement_template_v0_5_1to1.svg"
    rear_hole_path = OUTPUT / "rear_button_hole_template_v0_5_1to1.svg"
    clearance_path = PREVIEWS / "carrier_rear_clearance_v0_5.png"
    esp_mount_preview_path = PREVIEWS / "esp32_four_hole_alignment_v0_5.png"
    carrier_layout_path = PREVIEWS / "enclosure_v0_5_four_hole_layout.png"
    rear_bottom_preview_path = PREVIEWS / "rear_cover_bottom_view_v0_5.png"
    magnet_clearance_path = PREVIEWS / "magnet_electronics_clearance_v0_5.png"
    draw_placement_svg_v05(placement_path)
    draw_rear_hole_svg_v05(rear_hole_path)
    draw_clearance_diagram(clearance_path)
    draw_esp_mount_alignment(esp_mount_preview_path)
    draw_carrier_layout_v05(carrier_layout_path)
    draw_rear_bottom_view(rear_bottom_preview_path)
    draw_magnet_clearance_layout(magnet_clearance_path)

    total_x = P["rear_inner_width"] - P["midplate_width"]
    total_y = P["rear_inner_height"] - P["midplate_height"]
    wall_x = (P["case_width"] - P["rear_inner_width"]) / 2.0
    wall_y = (P["case_height"] - P["rear_inner_height"]) / 2.0
    ledge_open_w = P["rear_inner_width"] - 4.0
    ledge_open_h = P["rear_inner_height"] - 4.0
    ledge_overlap_x = (P["midplate_width"] - ledge_open_w) / 2.0
    ledge_overlap_y = (P["midplate_height"] - ledge_open_h) / 2.0

    manifest = {
        "design": "RefrigeratorFoodManagement enclosure tolerance correction V0.5",
        "units": "mm",
        "status": "print matched corner coupons before full-size parts",
        "reuse_without_reprint": ["front_bezel_v0_1.stl"],
        "changes_from_v0_4": [
            "rear cavity enlarged from 123.8 x 195.8 to 124.6 x 196.6",
            "ESP32 strap slots removed and replaced by four native-hole M2 screw posts",
            "ESP32 assembly and rear BOOT/RESET holes moved 25 mm toward the top charging edge",
            "rear BOOT/RESET holes mirrored in X for the physical outside bottom view",
            "BOOT and RESET recessed labels added to the rear exterior",
            "rear magnets increased from 6 to 10 and redistributed away from the ESP32 antenna and electronics",
            "two legacy bottom pressure-relief slots closed; top USB-C opening retained",
            "Lipo Rider and charging opening unchanged",
            "2026-08-16: fit coupon corrected to carrier top-right plus rear-cover top-left",
        ],
        "fit": {
            "carrier_outer": [P["midplate_width"], P["midplate_height"]],
            "rear_inner": [P["rear_inner_width"], P["rear_inner_height"]],
            "total_clearance": [round(total_x, 3), round(total_y, 3)],
            "per_side_clearance": [round(total_x / 2.0, 3), round(total_y / 2.0, 3)],
            "minimum_side_wall": [round(wall_x, 3), round(wall_y, 3)],
            "ledge_opening": [round(ledge_open_w, 3), round(ledge_open_h, 3)],
            "ledge_overlap_per_side": [round(ledge_overlap_x, 3), round(ledge_overlap_y, 3)],
        },
        "esp32_mount": {
            "mechanical_source": "https://docs.waveshare.com/ESP32-S3-DEV-KIT-N8R8",
            "measurement_basis": "user-measured Waveshare ESP32-S3-DEV-KIT-N16R8 on 2026-08-22",
            "board_size": [P["esp_board_width"], P["esp_board_height"]],
            "native_hole_diameter": P["esp_mount_hole_diameter"],
            "hole_pitch": [P["esp_mount_pitch_x"], P["esp_mount_pitch_y"]],
            "carrier_hole_centres": [[round(x, 3), round(y, 3)] for x, y in ESP_MOUNT_HOLES],
            "post_diameter": P["esp_mount_post_diameter"],
            "post_top_z": P["esp_mount_post_top"],
            "blind_pilot_diameter": P["esp_mount_pilot"],
            "blind_pilot_depth": P["esp_mount_pilot_depth"],
            "fastener": "4 x M2 x 4 mm self-tapping, head diameter <= 3.6 mm",
            "nominal_thread_engagement": round(P["esp_mount_screw_length"] - P["esp_board_thickness"], 3),
            "washers": "do not use washers on the two USB-side screws",
            "button_tool": "non-metallic pin diameter <= 1.5 mm",
        },
        "button_alignment": {
            "esp32_center": [P["esp_center_x"], P["esp_center_y"]],
            "esp32_center_delta_from_previous_v0_5": [0.0, 25.0],
            "board_boot_center_component_view": [round(value, 3) for value in v04.BOOT_CENTRE],
            "board_reset_center_component_view": [round(value, 3) for value in v04.RESET_CENTRE],
            "rear_boot_hole_model_center": [round(value, 3) for value in REAR_BOOT_CENTRE],
            "rear_reset_hole_model_center": [round(value, 3) for value in REAR_RESET_CENTRE],
            "outside_bottom_view": "BOOT and RESET appear on the left; do not mirror the STL or SVG",
            "rear_button_hole_y_delta_from_original_v0_5": 25.0,
            "rear_button_hole_x_rule": "rear model x = negative board component-view x",
            "rear_label": {
                "type": "recessed 5x7 lettering",
                "depth": REAR_LABEL_DEPTH,
                "pixel": REAR_LABEL_PIXEL,
            },
        },
        "magnet_mount": {
            "quantity": len(MAGNETS_V05),
            "magnet_size": [10.0, 3.0],
            "blind_pocket_size": [P["magnet_diameter"], P["magnet_depth"]],
            "outer_skin_remaining": 0.8,
            "rear_model_centres": [[x, y] for x, y in MAGNETS_V05],
            "assembled_projection_centres": [[x, y] for x, y in MAGNETS_ASSEMBLED_V05],
            "arrangement": "asymmetric ten-point layout with electronics and antenna keep-outs",
            "minimum_planar_clearance": magnet_electronics_clearances(),
        },
        "bottom_wall": {
            "legacy_pressure_relief_slots": "removed and closed",
            "former_slot_centres": [[x, y, z] for x, y, z in LEGACY_BOTTOM_RELIEF_CENTRES],
            "top_usb_c_opening": "retained",
        },
        "parameters": P,
        "parts": {name: v04.v03.part_info(path) for name, path in paths.items()},
        "templates": [placement_path.name, rear_hole_path.name],
        "previews": [
            clearance_path.name,
            esp_mount_preview_path.name,
            carrier_layout_path.name,
            rear_bottom_preview_path.name,
            magnet_clearance_path.name,
        ],
    }
    manifest_path = OUTPUT / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    package_path = ROOT / "RFM_enclosure_v0_5_STL.zip"
    with zipfile.ZipFile(package_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in paths.values():
            archive.write(path, path.name)
        archive.write(manifest_path, manifest_path.name)
        archive.write(placement_path, placement_path.name)
        archive.write(rear_hole_path, rear_hole_path.name)
        archive.write(clearance_path, clearance_path.name)
        archive.write(esp_mount_preview_path, esp_mount_preview_path.name)
        archive.write(carrier_layout_path, carrier_layout_path.name)
        archive.write(rear_bottom_preview_path, rear_bottom_preview_path.name)
        archive.write(magnet_clearance_path, magnet_clearance_path.name)
        archive.write(ROOT / "README.md", "README.md")

    package_dir = ROOT / "RFM_enclosure_v0_5_STL"
    package_dir.mkdir(parents=True, exist_ok=True)
    package_files = [
        *paths.values(),
        manifest_path,
        placement_path,
        rear_hole_path,
        clearance_path,
        esp_mount_preview_path,
        carrier_layout_path,
        rear_bottom_preview_path,
        ROOT / "README.md",
    ]
    obsolete_preview_names = (
        "installation_open_v0_5.png",
        "installation_exploded_v0_5.png",
        "rear_cover_installed_v0_5.png",
    )
    for preview_name in obsolete_preview_names:
        obsolete_path = package_dir / preview_name
        if obsolete_path.exists():
            obsolete_path.unlink()
    for path in package_files:
        shutil.copy2(path, package_dir / path.name)

    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
