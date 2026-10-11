#!/usr/bin/env python3
"""Generate the V0.9 ultrathin packaging study without producing any STL.

This study deliberately leaves enclosure_v0_7 untouched.  It reuses the
measured V0.7 footprints, but explores a thinner front stack, carrier and
rear skin.  The current 2 mm flexible magnets remain in their confirmed XY
positions.  Outputs are an exact-size SVG, a review PNG and a JSON report.
"""

from __future__ import annotations

import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parent
PREVIEWS = ROOT / "previews"


OUTER_W = 120.0
OUTER_H = 184.0
INNER_W = 116.4
INNER_H = 180.4

# Assembled rear-view coordinates: (centre x, centre y, width x, height y).
COMPONENTS = {
    "battery": (0.0, -50.5, 94.0, 62.0),
    "esp32": (-42.0, 44.0, 25.4, 63.3),
    "lipo_rider": (5.461, 67.4885, 25.48, 40.877),
    "despi_c02": (29.0, 1.0, 42.0, 24.0),
}

MAGNETS = {
    "magnet_90x50_left": (-25.0, -36.5, 50.6, 90.6),
    "magnet_90x50_right": (25.0, -36.5, 50.6, 90.6),
    "magnet_50x20": (46.0, 55.0, 20.6, 50.6),
}

FASTENERS = [(-38.0, -87.9), (38.0, -87.9), (-38.0, 87.9), (38.0, 87.9)]

# Revised structural stack proposed for V0.9.
FRONT_STACK = 2.8  # 1.4 mm face + 1.2 mm display + 0.2 mm allowance.
NORMAL_REAR_SKIN = 0.8
MAGNET_SKIN = 0.4
MAGNET_THICKNESS = 2.0
MAGNET_ADHESIVE_ALLOWANCE = 0.2
MAGNET_STACK = MAGNET_SKIN + MAGNET_THICKNESS + MAGNET_ADHESIVE_ALLOWANCE
BATTERY_THICKNESS = 8.0
BATTERY_CARRIER_FLOOR = 0.4
FORMAL_BATTERY_CLEARANCE = 1.0
PROTOTYPE_BATTERY_CLEARANCE = 0.8

# Low-profile electronics mounts.  The ESP32 solderless terminal clamp must be
# revised so only 1.4 mm is needed below the PCB; its 8 mm upper envelope stays.
ESP32_STACK = 0.8 + 1.4 + 8.0
LIPO_STACK = 0.8 + 1.4 + 7.5
DESPI_STACK = 0.8 + 4.0


def bounds(rect: tuple[float, float, float, float]) -> tuple[float, float, float, float]:
    cx, cy, w, h = rect
    return cx - w / 2.0, cy - h / 2.0, cx + w / 2.0, cy + h / 2.0


def overlap(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> bool:
    ax0, ay0, ax1, ay1 = bounds(a)
    bx0, by0, bx1, by1 = bounds(b)
    return min(ax1, bx1) > max(ax0, bx0) and min(ay1, by1) > max(ay0, by0)


def battery_stack(tape: float) -> float:
    return BATTERY_CARRIER_FLOOR + tape + BATTERY_THICKNESS


def required_total_with_magnets(tape: float, clearance: float) -> float:
    return FRONT_STACK + MAGNET_STACK + battery_stack(tape) + clearance


def screw_engagement(total: float, screw_length: float, counterbore: float, front_post_top: float) -> float:
    return screw_length - (total - counterbore - front_post_top)


def svg_rect(rect, klass, label):
    cx, cy, w, h = rect
    x = cx + OUTER_W / 2.0 - w / 2.0
    y = OUTER_H / 2.0 - (cy + h / 2.0)
    return (
        f'<rect class="{klass}" x="{x:.3f}" y="{y:.3f}" width="{w:.3f}" height="{h:.3f}" rx="1.2"/>'
        f'<text x="{x + w / 2:.3f}" y="{y + h / 2:.3f}" text-anchor="middle">{label}</text>'
    )


def write_exact_svg(path: Path) -> None:
    parts = [
        '<svg xmlns="http://www.w3.org/2000/svg" width="120mm" height="184mm" viewBox="0 0 120 184">',
        '<style>text{font-family:Arial,"PingFang SC",sans-serif;font-size:2.7px;fill:#162b25}.outer{fill:#fafbf9;stroke:#173d32;stroke-width:.45}.inner{fill:none;stroke:#9aaba5;stroke-width:.3;stroke-dasharray:1.2 1}.battery{fill:#f4d47a;stroke:#9b6d00;stroke-width:.35}.board{fill:#bedbd0;stroke:#26745d;stroke-width:.35}.despi{fill:#cfd7ec;stroke:#526a9a;stroke-width:.35}.magnet{fill:#efb2a0;stroke:#a3422d;stroke-width:.35;fill-opacity:.72}.fastener{fill:none;stroke:#b42525;stroke-width:.35}.note{font-size:2.2px;fill:#566c64}</style>',
        '<rect class="outer" x="0.25" y="0.25" width="119.5" height="183.5" rx="8"/>',
        f'<rect class="inner" x="{(OUTER_W-INNER_W)/2:.3f}" y="{(OUTER_H-INNER_H)/2:.3f}" width="{INNER_W:.3f}" height="{INNER_H:.3f}" rx="6.2"/>',
        '<text x="60" y="6" text-anchor="middle">V0.9 超薄排布研究｜1:1｜USB-C 在上</text>',
    ]
    for name, rect in MAGNETS.items():
        label = "90×50×2" if "90x50" in name else "50×20×2"
        parts.append(svg_rect(rect, "magnet", label))
    parts.append(svg_rect(COMPONENTS["battery"], "battery", "电池 94×62×8"))
    parts.append(svg_rect(COMPONENTS["esp32"], "board", "ESP32"))
    parts.append(svg_rect(COMPONENTS["lipo_rider"], "board", "Lipo"))
    parts.append(svg_rect(COMPONENTS["despi_c02"], "despi", "DESPI"))
    for x, y in FASTENERS:
        parts.append(f'<circle class="fastener" cx="{x + 60:.3f}" cy="{92-y:.3f}" r="2.6"/>')
    parts.extend([
        '<text class="note" x="60" y="178" text-anchor="middle">橙色为后盖磁片投影；元件与磁片可投影重叠，但必须满足 Z 向净空</text>',
        '<text class="note" x="60" y="181.5" text-anchor="middle">研究图，不可直接用于制造；正式结构须先通过局部检具</text>',
        '</svg>',
    ])
    path.write_text("\n".join(parts), encoding="utf-8")


def font(size: int, bold: bool = False):
    candidates = [
        "/System/Library/Fonts/PingFang.ttc",
        "/System/Library/Fonts/STHeiti Medium.ttc" if bold else "/System/Library/Fonts/STHeiti Light.ttc",
        "/Library/Fonts/Arial Unicode.ttf",
    ]
    for candidate in candidates:
        try:
            return ImageFont.truetype(candidate, size=size, index=2 if bold and "PingFang" in candidate else 0)
        except OSError:
            continue
    return ImageFont.load_default()


def draw_review_png(path: Path, report: dict) -> None:
    image = Image.new("RGB", (1800, 1220), "#f6f5ef")
    draw = ImageDraw.Draw(image)
    title = font(48, True)
    heading = font(30, True)
    body = font(24)
    small = font(20)
    draw.text((55, 38), "V0.9 超薄结构可行性研究", fill="#17382f", font=title)
    draw.text((58, 102), "保持 V0.7 文件不变｜120 × 184 mm｜本轮不生成 STL", fill="#586b65", font=body)

    # Left: exact XY layout, scaled from millimetres.
    sx, sy = 70, 180
    scale = 5.0
    draw.rounded_rectangle((sx, sy, sx + OUTER_W * scale, sy + OUTER_H * scale), radius=40,
                           fill="#ffffff", outline="#315f50", width=4)

    def px_rect(rect):
        cx, cy, w, h = rect
        x0 = sx + (cx + OUTER_W / 2 - w / 2) * scale
        y0 = sy + (OUTER_H / 2 - cy - h / 2) * scale
        return x0, y0, x0 + w * scale, y0 + h * scale

    for name, rect in MAGNETS.items():
        draw.rounded_rectangle(px_rect(rect), radius=12, fill="#efad8f", outline="#a64a2e", width=3)
        label = "90×50×2" if "90x50" in name else "50×20×2"
        box = px_rect(rect)
        draw.text(((box[0] + box[2]) / 2, (box[1] + box[3]) / 2), label,
                  anchor="mm", fill="#6d2819", font=small)

    styles = {
        "battery": ("#f3d275", "#876200", "电池 8 mm"),
        "esp32": ("#b9d9cd", "#216850", "ESP32"),
        "lipo_rider": ("#d8c8e9", "#6f4a91", "Lipo Rider"),
        "despi_c02": ("#c9d4eb", "#48618d", "DESPI-C02"),
    }
    for key, rect in COMPONENTS.items():
        fill, outline, label = styles[key]
        draw.rounded_rectangle(px_rect(rect), radius=12, fill=fill, outline=outline, width=3)
        box = px_rect(rect)
        draw.text(((box[0] + box[2]) / 2, (box[1] + box[3]) / 2), label,
                  anchor="mm", fill="#172b25", font=small)
    for x, y in FASTENERS:
        px = sx + (x + OUTER_W / 2) * scale
        py = sy + (OUTER_H / 2 - y) * scale
        draw.ellipse((px - 12, py - 12, px + 12, py + 12), outline="#ba2929", width=4)
    draw.text((sx + OUTER_W * scale / 2, sy + 22), "USB-C", anchor="ma", fill="#17382f", font=small)

    # Right: result cards and thickness sections.
    rx = 750
    draw.text((rx, 180), "精算结论", fill="#17382f", font=heading)
    rows = [
        ("保留 1 mm 双面胶", "15.8 mm", "可做，但达不到 15 mm"),
        ("改用 ≤0.2 mm 转移胶", "15.0 mm", "推荐正式目标"),
        ("同上，缩小安全余量", "14.8 mm", "只建议先做工程样机"),
        ("再改用 1 mm 磁片", "13.8 mm", "需要重新购买磁片"),
    ]
    y = 235
    for label, value, note in rows:
        draw.rounded_rectangle((rx, y, 1715, y + 118), radius=18, fill="#ffffff", outline="#cad5d1", width=2)
        draw.text((rx + 24, y + 18), label, fill="#17382f", font=body)
        draw.text((rx + 940, y + 18), value, anchor="ra", fill="#17382f", font=heading)
        color = "#a03a2b" if "达不到" in note or "样机" in note else "#416259"
        draw.text((rx + 24, y + 70), note, fill=color, font=small)
        y += 134

    draw.text((rx, 800), "15.0 mm 推荐堆叠", fill="#17382f", font=heading)
    sections = [
        ("前框 + 屏幕", 2.8, "#a9cbbb"),
        ("电池底板 + 0.2胶 + 8mm电池", 8.6, "#f1cf65"),
        ("电池安全余量", 1.0, "#dceade"),
        ("2mm磁片 + 胶 + 0.4外皮", 2.6, "#eaa68b"),
    ]
    bar_x, bar_y, bar_w, bar_h = rx, 865, 900, 90
    cursor = bar_x
    total = sum(v for _, v, _ in sections)
    for label, value, color in sections:
        width = bar_w * value / total
        draw.rectangle((cursor, bar_y, cursor + width, bar_y + bar_h), fill=color)
        if width > 95:
            draw.text((cursor + width / 2, bar_y + 29), f"{value:.1f}", anchor="mm", fill="#172b25", font=small)
        cursor += width
    draw.rectangle((bar_x, bar_y, bar_x + bar_w, bar_y + bar_h), outline="#17382f", width=3)
    y = 975
    for label, value, color in sections:
        draw.rectangle((rx, y + 5, rx + 22, y + 27), fill=color, outline="#6e7c77")
        draw.text((rx + 35, y), f"{label}：{value:.1f} mm", fill="#374e47", font=small)
        y += 42
    draw.text((rx, 1158), "M2×12：新沉孔 1.6 mm、前框螺丝柱顶高 4.6 mm，预计咬合 3.2 mm",
              fill="#374e47", font=small)
    image.save(path)


def main() -> None:
    ROOT.mkdir(parents=True, exist_ok=True)
    PREVIEWS.mkdir(parents=True, exist_ok=True)

    current_tape_formal = required_total_with_magnets(1.0, FORMAL_BATTERY_CLEARANCE)
    thin_tape_formal = required_total_with_magnets(0.2, FORMAL_BATTERY_CLEARANCE)
    thin_tape_prototype = required_total_with_magnets(0.2, PROTOTYPE_BATTERY_CLEARANCE)
    one_mm_magnet_stack = MAGNET_SKIN + 1.0 + MAGNET_ADHESIVE_ALLOWANCE
    thin_magnet_formal = FRONT_STACK + one_mm_magnet_stack + battery_stack(0.2) + PROTOTYPE_BATTERY_CLEARANCE

    assert abs(current_tape_formal - 15.8) < 1e-9
    assert abs(thin_tape_formal - 15.0) < 1e-9
    assert abs(thin_tape_prototype - 14.8) < 1e-9
    assert abs(thin_magnet_formal - 13.8) < 1e-9

    target = thin_tape_formal
    normal_available = target - FRONT_STACK - NORMAL_REAR_SKIN
    magnet_available = target - FRONT_STACK - MAGNET_STACK
    stacks = {
        "battery_with_0p2_tape": battery_stack(0.2),
        "esp32_revised_solderless_mount": ESP32_STACK,
        "lipo_rider_low_mount": LIPO_STACK,
        "despi_c02_low_mount": DESPI_STACK,
    }
    clearances = {
        "battery_in_magnet_zone": magnet_available - stacks["battery_with_0p2_tape"],
        "esp32_normal_zone": normal_available - stacks["esp32_revised_solderless_mount"],
        "lipo_rider_normal_zone": normal_available - stacks["lipo_rider_low_mount"],
        "despi_c02_in_magnet_zone": magnet_available - stacks["despi_c02_low_mount"],
    }
    assert min(clearances.values()) >= 1.0 - 1e-9
    assert overlap(COMPONENTS["battery"], MAGNETS["magnet_90x50_left"])
    assert overlap(COMPONENTS["battery"], MAGNETS["magnet_90x50_right"])
    assert not any(overlap(COMPONENTS["esp32"], magnet) for magnet in MAGNETS.values())
    assert not any(overlap(COMPONENTS["lipo_rider"], magnet) for magnet in MAGNETS.values())
    assert any(overlap(COMPONENTS["despi_c02"], magnet) for magnet in MAGNETS.values())

    engagement = screw_engagement(target, 12.0, 1.6, 4.6)
    assert abs(engagement - 3.2) < 1e-9

    report = {
        "design": "V0.9 ultrathin layout study",
        "status": "LAYOUT STUDY ONLY - NO STL GENERATED",
        "preserves": [
            "hardware/enclosure_v0_7 remains unchanged",
            "120 x 184 mm exterior footprint",
            "current V0.7 component and magnet XY positions for the 15.0 mm proposal",
            "two 90 x 50 x 2 mm and one 50 x 20 x 2 mm flexible magnets",
            "0.4 mm PLA skin outside the magnets",
        ],
        "key_result_mm": {
            "with_existing_1p0_tape_formal_minimum": round(current_tape_formal, 3),
            "with_0p2_transfer_tape_formal_target": round(thin_tape_formal, 3),
            "with_0p2_transfer_tape_prototype_limit": round(thin_tape_prototype, 3),
            "with_0p2_tape_and_1p0_magnets_prototype": round(thin_magnet_formal, 3),
        },
        "recommended_15p0_stack_mm": {
            "front_frame_display_and_allowance": FRONT_STACK,
            "battery_carrier_floor_tape_and_cell": stacks["battery_with_0p2_tape"],
            "battery_clearance": FORMAL_BATTERY_CLEARANCE,
            "magnet_adhesive_and_outer_skin": MAGNET_STACK,
            "total": target,
        },
        "available_heights_mm": {
            "normal_zone": round(normal_available, 3),
            "magnet_zone": round(magnet_available, 3),
        },
        "component_stacks_mm": {k: round(v, 3) for k, v in stacks.items()},
        "component_clearances_mm": {k: round(v, 3) for k, v in clearances.items()},
        "m2x12_fastener_study_mm": {
            "screw_length": 12.0,
            "counterbore_depth": 1.6,
            "front_post_top_from_front_outer_face": 4.6,
            "estimated_engagement": round(engagement, 3),
        },
        "required_changes_before_stl": [
            "replace 1.0 mm battery foam tape with <=0.2 mm acrylic transfer tape for the 15.0 mm target",
            "reduce front stack from 4.0 mm to 2.8 mm while retaining the measured 1.2 mm display",
            "replace the 1.4 mm carrier with a ribbed 0.8 mm carrier and a 0.4 mm local battery floor",
            "redesign the solderless ESP32 terminal clamp so under-board clearance falls from 2.8 mm to 1.4 mm without exposing conductive pins",
            "redesign all four case fastener posts for M2 x 12 mm and verify with a corner coupon",
            "verify the actual maximum battery thickness including protection board and folded wire exit",
        ],
        "stop_conditions": [
            "battery plus selected adhesive measures above 8.2 mm at any point",
            "ESP32 revised clamp needs more than 1.4 mm below the PCB",
            "any conductive terminal can touch the carrier or display backplane",
            "M2 x 12 screw bottoms out or produces less than 3.0 mm thread engagement",
        ],
    }

    (ROOT / "feasibility_report_v0_9.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    write_exact_svg(ROOT / "layout_15p0_v0_9_1to1.svg")
    draw_review_png(PREVIEWS / "layout_and_thickness_study_v0_9.png", report)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
