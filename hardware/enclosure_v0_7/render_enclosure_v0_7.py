#!/usr/bin/env python3
"""Render V0.7 installed and exploded views from the generated STL files."""

from __future__ import annotations

import importlib.util
from pathlib import Path

from PIL import Image, ImageDraw
import trimesh


ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "output"
PREVIEWS = ROOT / "previews"
GENERATOR = ROOT / "generate_enclosure_v0_7.py"
V06_RENDERER = ROOT.parent / "enclosure_v0_6" / "render_enclosure_v0_6.py"


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load module: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


gen = load_module("rfm_enclosure_v07_render_gen", GENERATOR)
r06 = load_module("rfm_enclosure_v06_render_base", V06_RENDERER)
P = gen.P
r06.P = P
r06.OUTPUT = OUTPUT
r06.PREVIEWS = PREVIEWS


def rear_vertices(mesh, explode=0.0):
    vertices = mesh.vertices.copy()
    vertices[:, 2] = P["assembled_thickness"] - vertices[:, 2] + explode
    return vertices


def carrier_vertices(mesh, explode=0.0):
    vertices = mesh.vertices.copy()
    vertices[:, 2] += 4.0 + explode
    return vertices


def coupon_rear_vertices(mesh, explode=0.0):
    """Turn rear Rev B cavity-down and mirror its local X axis."""
    vertices = mesh.vertices.copy()
    width = float(mesh.bounds[1, 0] - mesh.bounds[0, 0])
    vertices[:, 0] = width - vertices[:, 0]
    vertices[:, 2] = P["assembled_thickness"] - vertices[:, 2] + explode
    return vertices


def coupon_carrier_vertices(mesh, explode=0.0):
    vertices = mesh.vertices.copy()
    vertices[:, 2] += 4.0 + explode
    return vertices


def draw_corner_fit_effect():
    front = trimesh.load_mesh(OUTPUT / "fit_test_front_corner_v0_7.stl")
    carrier = trimesh.load_mesh(OUTPUT / "fit_test_carrier_corner_v0_7_rev_b_boss_relief_r2_9.stl")
    rear = trimesh.load_mesh(OUTPUT / "fit_test_rear_corner_v0_7_rev_c_boss_relief_r2_9.stl")
    image = Image.new("RGB", (1900, 1450), "#f4f2ec")
    draw = ImageDraw.Draw(image)
    draw.text((50, 30), "V0.7 三个角部检具的真实组合方向", fill="#17352b", font=r06.load_font(43))
    draw.text((53, 88), "中托/后盖均为 R2.9 螺丝柱让位｜后盖孔位方向已校正", fill="#52665f", font=r06.load_font(24))
    panels = [
        (45, 140, 925, 715),
        (975, 140, 1855, 715),
        (45, 755, 925, 1330),
        (975, 755, 1855, 1330),
    ]
    r06.render_panel(
        image, panels[0],
        [
            (front, front.vertices, "#f2f4f0", 1.0),
            (carrier, coupon_carrier_vertices(carrier, 13.0), "#d7a85d", 1.0),
            (rear, coupon_rear_vertices(rear, 30.0), "#b4c8bf", 0.95),
        ],
        "① 按真实方向分开摆放", yaw=-36, pitch=66,
    )
    r06.render_panel(
        image, panels[1],
        [
            (front, front.vertices, "#f2f4f0", 1.0),
            (carrier, coupon_carrier_vertices(carrier, 5.0), "#d7a85d", 1.0),
            (rear, coupon_rear_vertices(rear, 12.0), "#b4c8bf", 0.95),
        ],
        "② 对准螺丝孔后垂直靠近", yaw=-36, pitch=66,
    )
    r06.render_panel(
        image, panels[2],
        [
            (front, front.vertices, "#f2f4f0", 1.0),
            (carrier, coupon_carrier_vertices(carrier), "#d7a85d", 1.0),
            (rear, coupon_rear_vertices(rear), "#b4c8bf", 0.82),
        ],
        "③ 完全落位后的组合状态", yaw=-36, pitch=66,
    )
    r06.render_panel(
        image, panels[3],
        [
            (front, front.vertices, "#f2f4f0", 0.68),
            (carrier, coupon_carrier_vertices(carrier), "#d7a85d", 0.68),
            (rear, coupon_rear_vertices(rear), "#b4c8bf", 0.55),
        ],
        "④ 沿螺丝轴俯视：三孔应完全重合", yaw=0, pitch=0,
    )
    draw.text((950, 1390), "原始 STL：前框/中托 X=13 mm，后盖 Rev B X=22 mm；后盖翻面后装配坐标均为 X=13 mm。", anchor="mm", fill="#52665f", font=r06.load_font(21))
    image.save(PREVIEWS / "corner_fit_assembly_v0_7.png")


def draw_rear_coupon_revision():
    image = Image.new("RGB", (1500, 780), "#f4f2ec")
    draw = ImageDraw.Draw(image)
    title = r06.load_font(42)
    body = r06.load_font(25)
    note = r06.load_font(22)
    draw.text((60, 38), "后盖角部检具 Rev B：孔位已移动到另一边", fill="#17352b", font=title)
    draw.text((60, 98), "以下为 STL 原始打印朝向；外框尺寸均为 35 × 37 mm", fill="#52665f", font=body)

    panels = [(90, 180, 650, 650), (850, 180, 1410, 650)]
    labels = [("旧版（不要再打印）", 13.0, "X = 13 mm"), ("Rev B（本次新文件）", 22.0, "X = 22 mm")]
    for (x0, y0, x1, y1), (label, hole_x, dimension) in zip(panels, labels):
        draw.rounded_rectangle((x0, y0, x1, y1), radius=24, fill="#e6ece8", outline="#91a49c", width=4)
        scale = 11.0
        bx0 = x0 + 75
        by0 = y0 + 35
        bw = 35.0 * scale
        bh = 37.0 * scale
        draw.rounded_rectangle((bx0, by0, bx0 + bw, by0 + bh), radius=16, fill="#b4c8bf", outline="#17352b", width=4)
        hx = bx0 + hole_x * scale
        hy = by0 + 32.9 * scale
        draw.ellipse((hx - 15, hy - 15, hx + 15, hy + 15), fill="#f4f2ec", outline="#c43f35", width=5)
        draw.line((bx0, hy + 30, hx, hy + 30), fill="#c43f35", width=4)
        draw.text(((bx0 + hx) / 2, hy + 42), dimension, anchor="ma", fill="#c43f35", font=note)
        draw.text(((x0 + x1) / 2, y1 + 28), label, anchor="ma", fill="#17352b", font=body)

    draw.line((670, 410, 825, 410), fill="#c43f35", width=8)
    draw.polygon([(825, 410), (790, 388), (790, 432)], fill="#c43f35")
    draw.text((748, 365), "横向移动 9 mm", anchor="mm", fill="#c43f35", font=body)
    draw.text((750, 742), "请删除切片软件中的旧对象，再导入带 rev_b_opposite_side 的新 STL。", anchor="mm", fill="#52665f", font=note)
    image.save(PREVIEWS / "rear_coupon_hole_revision_v0_7_rev_b.png")


def draw_rear_openings_detail(rear):
    """Render the actual rear STL and state the Rev I regular opening."""
    image = Image.new("RGB", (1700, 920), "#f4f2ec")
    draw = ImageDraw.Draw(image)
    draw.text((55, 30), "V0.7 后盖 Rev I：LED 与开关规则开口", fill="#17352b", font=r06.load_font(43))
    draw.text(
        (58, 88),
        "实际 STL 渲染｜单一圆角长方形｜净尺寸 5.2 × 21.0 mm｜圆角 R1.0 mm",
        fill="#52665f",
        font=r06.load_font(24),
    )
    r06.render_panel(
        image,
        (45, 145, 825, 735),
        [(rear, r06.exterior_rear_vertices(rear.vertices), "#bdcec6", 1.0)],
        "后盖外表面：LED / SW1 共用一个规则开口",
        yaw=0,
        pitch=0,
    )
    r06.render_panel(
        image,
        (875, 145, 1655, 735),
        [(rear, r06.exterior_rear_vertices(rear.vertices), "#bdcec6", 1.0)],
        "顶部透视：USB-C 公头从上方插入",
        yaw=-20,
        pitch=72,
    )
    cards = [
        ((55, 770, 545, 875), "USB-C：11.5 × 7.5 mm", "上下各扩大 1.0 mm"),
        ((605, 770, 1095, 875), "规则开口：5.2 × 21.0 mm", "同一宽度、同一中心线、四边连续"),
        ((1155, 770, 1645, 875), "四角：R1.0 mm", "无窄桥、台阶或局部宽度变化"),
    ]
    for bounds, title, note_text in cards:
        draw.rounded_rectangle(bounds, radius=20, fill="#e9f3ed", outline="#7ca08f", width=3)
        draw.text((bounds[0] + 24, 790), title, fill="#17352b", font=r06.load_font(22))
        draw.text((bounds[0] + 24, 830), note_text, fill="#52665f", font=r06.load_font(18))
    image.save(PREVIEWS / "rear_openings_detail_v0_7.png")


def draw_rear_left_wall_revision(rear):
    """Show the Rev F full-height stepped left wall."""
    image = Image.new("RGB", (1800, 1050), "#f4f2ec")
    draw = ImageDraw.Draw(image)
    title = r06.load_font(43)
    body = r06.load_font(25)
    note = r06.load_font(21)
    draw.text((55, 30), "V0.7 后盖 Rev F：左侧顶部薄带恢复", fill="#17352b", font=title)
    draw.text(
        (58, 88),
        "实际 STL 内侧视图｜左侧恢复全高｜无向内折边｜仅顶部 1.8 mm 高区域减薄",
        fill="#52665f",
        font=body,
    )
    r06.render_panel(
        image,
        (45, 145, 1125, 965),
        [(rear, rear.vertices, "#b9ccc3", 1.0)],
        "正式 rear_cover_v0_7.stl（空腔朝上）",
        yaw=8,
        pitch=18,
    )

    x0, y0, x1, y1 = 1170, 145, 1755, 965
    draw.rounded_rectangle((x0, y0, x1, y1), radius=28, fill="#ffffff", outline="#d6ddd8", width=3)
    draw.text((x0 + 28, y0 + 25), "左侧俯视关系", fill="#17352b", font=body)
    left, top, right, bottom = x0 + 115, y0 + 105, x1 - 90, y0 + 560
    draw.rounded_rectangle((left, top, right, bottom), radius=30, outline="#17352b", width=8)
    tangent_top = top + 30
    tangent_bottom = bottom - 30
    flat_top = tangent_top - 4
    flat_bottom = tangent_bottom + 4
    draw.line((left, flat_top, left, flat_bottom), fill="#c43f35", width=12)
    draw.line((left - 24, flat_top, left - 24, flat_bottom), fill="#315f8c", width=4)
    draw.line((left - 36, flat_top, left - 12, flat_top), fill="#315f8c", width=4)
    draw.line((left - 36, flat_bottom, left - 12, flat_bottom), fill="#315f8c", width=4)
    draw.text((left + 14, (flat_top + flat_bottom) / 2), "顶部恢复带", anchor="lm", fill="#c43f35", font=note)
    draw.text((x0 + 30, y0 + 590), "长度：170.0 mm（Y=-85～+85）", fill="#315f8c", font=note)
    draw.text((x0 + 30, y0 + 630), "纯直边 168 mm + 两端各进入圆角 1 mm；无高度台阶", fill="#52665f", font=note)

    section_y = y0 + 680
    draw.text((x0 + 30, section_y - 28), "局部剖面", fill="#17352b", font=body)
    baseline = section_y + 150
    outer_x = x0 + 50
    lower_inner_x = x0 + 140
    upper_inner_x = x0 + 90
    band_bottom = section_y + 52
    draw.polygon(
        [(outer_x, section_y + 20), (upper_inner_x, section_y + 20),
         (upper_inner_x, band_bottom), (lower_inner_x, band_bottom),
         (lower_inner_x, baseline), (outer_x, baseline)],
        fill="#b9ccc3", outline="#17352b",
    )
    draw.line((outer_x, section_y + 20, upper_inner_x, section_y + 20), fill="#c43f35", width=5)
    draw.line((outer_x, section_y + 4, upper_inner_x, section_y + 4), fill="#315f8c", width=4)
    draw.line((outer_x, section_y - 5, outer_x, section_y + 13), fill="#315f8c", width=4)
    draw.line((upper_inner_x, section_y - 5, upper_inner_x, section_y + 13), fill="#315f8c", width=4)
    draw.text((x0 + 165, section_y - 8), "顶部薄带：高 1.8 mm，厚 0.8 mm", fill="#315f8c", font=note)
    draw.text((x0 + 165, section_y + 48), "下部原墙：厚 1.8 mm，保持不变", fill="#52665f", font=note)
    draw.text((x0 + 50, baseline + 14), "总高 16.6 mm；外侧拉平，内侧形成 1.0 mm 壁厚台阶", fill="#52665f", font=note)
    image.save(PREVIEWS / "rear_left_wall_flat_revision_v0_7_rev_f.png")


def draw_front_retainer_revision(front):
    """Show the actual Rev F front STL and its continuous right inner edges."""
    image = Image.new("RGB", (1800, 1050), "#f4f2ec")
    draw = ImageDraw.Draw(image)
    title = r06.load_font(43)
    body = r06.load_font(25)
    note = r06.load_font(21)
    draw.text((55, 30), "V0.7 前框 Rev F：右端连续水平边", fill="#17352b", font=title)
    draw.text(
        (58, 88),
        "实际 STL 内侧视图｜外侧四角圆弧不变｜右侧中段开放｜取消 170 mm 人为约束",
        fill="#52665f",
        font=body,
    )
    r06.render_panel(
        image,
        (45, 145, 1125, 965),
        [(front, front.vertices, "#b9ccc3", 1.0)],
        "正式 front_bezel_v0_7.stl（内侧朝上）",
        yaw=-7,
        pitch=12,
    )

    x0, y0, x1, y1 = 1170, 145, 1755, 965
    draw.rounded_rectangle((x0, y0, x1, y1), radius=28, fill="#ffffff", outline="#d6ddd8", width=3)
    draw.text((x0 + 28, y0 + 25), "尺寸关系", fill="#17352b", font=body)
    left, top, right, bottom = x0 + 95, y0 + 135, x1 - 70, y1 - 155
    draw.rounded_rectangle((left, top, right, bottom), radius=26, outline="#17352b", width=8)
    inset = 24
    rail = 18
    rail_colour = "#2b8a64"
    gx0, gy0, gx1, gy1 = left + inset, top + inset, right - inset, bottom - inset
    diagram_radius = 30
    draw.rounded_rectangle(
        (gx0, gy0, gx1, gy1), radius=diagram_radius,
        outline=rail_colour, width=rail,
    )
    # Rev F retains the two square LEFT inner corners.  Cover the rounded inner
    # quadrants so the diagram matches the square inner corners in the STL.
    inner_left = gx0 + rail // 2
    inner_top = gy0 + rail // 2
    inner_bottom = gy1 - rail // 2
    draw.rectangle((inner_left, inner_top, inner_left + 20, inner_top + 20), fill="#ffffff")
    draw.line((inner_left, inner_top, inner_left + 22, inner_top), fill=rail_colour, width=rail)
    draw.line((inner_left, inner_top, inner_left, inner_top + 22), fill=rail_colour, width=rail)
    draw.rectangle((inner_left, inner_bottom - 20, inner_left + 20, inner_bottom), fill="#ffffff")
    draw.line((inner_left, inner_bottom, inner_left + 22, inner_bottom), fill=rail_colour, width=rail)
    draw.line((inner_left, inner_bottom - 22, inner_left, inner_bottom), fill=rail_colour, width=rail)
    # Remove only the right-side middle rail.  The upper-right/lower-right
    # rounded corners remain, and their inward-facing edges are horizontal.
    right_tangent = gx1 - diagram_radius
    top_flat = gy0 + rail // 2
    bottom_flat = gy1 - rail // 2
    draw.rectangle(
        (right_tangent, top_flat, gx1 + rail, bottom_flat),
        fill="#ffffff",
    )
    draw.line((right_tangent, top_flat, gx1, top_flat), fill="#c43f35", width=5)
    draw.line((right_tangent, bottom_flat, gx1, bottom_flat), fill="#c43f35", width=5)
    draw.text((right - inset - 8, (top + bottom) / 2), "中段开放\n无竖向定位条", anchor="rm", fill="#c43f35", font=note)
    draw.text(((left + right) / 2, top + inset - 36), "上侧宽 2.9 mm", anchor="mm", fill="#216b50", font=note)
    draw.text(((left + right) / 2, bottom + 8), "下侧宽 2.9 mm", anchor="ma", fill="#216b50", font=note)
    draw.text((left + inset + rail + 12, (top + bottom) / 2), "左侧宽\n2.9 mm", anchor="lm", fill="#216b50", font=note)
    dimension_x = gx1 + 32
    draw.line((dimension_x, top_flat, dimension_x, bottom_flat), fill="#315f8c", width=4)
    draw.line((dimension_x - 10, top_flat, dimension_x + 10, top_flat), fill="#315f8c", width=4)
    draw.line((dimension_x - 10, bottom_flat, dimension_x + 10, bottom_flat), fill="#315f8c", width=4)
    draw.line((left, top - 38, left + inset, top - 38), fill="#315f8c", width=4)
    draw.line((left, top - 50, left, top - 27), fill="#315f8c", width=4)
    draw.line((left + inset, top - 50, left + inset, top - 27), fill="#315f8c", width=4)
    draw.text((left + inset / 2, top - 66), "外边距 3.6 mm", anchor="ms", fill="#315f8c", font=note)
    draw.text((x0 + 32, y1 - 137), "外侧四角 R4.4；左侧两个内角为 90°。", fill="#315f8c", font=note)
    draw.text((x0 + 32, y1 - 102), "上下内边缘自然延伸；当前开口约 171.0 mm。", fill="#315f8c", font=note)
    draw.text((x0 + 32, y1 - 67), "右端无椭圆、舌头或台阶；屏幕从右侧装入。", fill="#17352b", font=note)
    image.save(PREVIEWS / "front_retainer_revision_v0_7_rev_f.png")


def draw_rear_button_labels_outside():
    """Render an actual-STL section in the physical rear viewing direction."""
    coupon = trimesh.load_mesh(OUTPUT / "fit_test_boot_reset_labels_v0_7.stl")
    section = coupon.section(plane_origin=[0.0, 0.0, 0.30], plane_normal=[0.0, 0.0, 1.0])
    if section is None:
        raise RuntimeError("BOOT/RESET coupon has no section at Z=0.30 mm")
    planar, _ = section.to_2D()
    loops = planar.discrete

    image = Image.new("RGB", (1800, 950), "#f4f2ec")
    draw = ImageDraw.Draw(image)
    draw.text((55, 30), "V0.7 后盖 BOOT / RESET 外侧剖面", fill="#17352b", font=r06.load_font(43))
    draw.text(
        (58, 88),
        "取实际 STL 在凹刻中层 Z=0.30 mm 的轮廓；已按后盖外侧方向左右翻转",
        fill="#52665f",
        font=r06.load_font(24),
    )
    panel = (90, 150, 1710, 865)
    draw.rounded_rectangle(panel, radius=28, fill="#ffffff", outline="#d6ddd8", width=3)
    draw.text((120, 175), "外侧正常读取方向（USB-C边朝上）", fill="#17352b", font=r06.load_font(24))

    points = [(-x, y) for loop in loops for x, y in loop]
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    xmin, xmax = min(xs), max(xs)
    ymin, ymax = min(ys), max(ys)
    scale = min(
        (panel[2] - panel[0] - 140) / (xmax - xmin),
        (panel[3] - panel[1] - 150) / (ymax - ymin),
    )
    centre_x = (panel[0] + panel[2]) / 2.0
    centre_y = (panel[1] + panel[3]) / 2.0 + 25.0
    for loop in loops:
        contour = [
            (
                centre_x + ((-x) - (xmin + xmax) / 2.0) * scale,
                centre_y - (y - (ymin + ymax) / 2.0) * scale,
            )
            for x, y in loop
        ]
        draw.line(contour, fill="#17352b", width=4, joint="curve")
    image.save(PREVIEWS / "rear_button_labels_outside_v0_7.png")


def main():
    front = trimesh.load_mesh(OUTPUT / "front_bezel_v0_7.stl")
    carrier = trimesh.load_mesh(OUTPUT / "electronics_carrier_v0_7.stl")
    rear = trimesh.load_mesh(OUTPUT / "rear_cover_v0_7.stl")
    image = Image.new("RGB", (1900, 1450), "#f4f2ec")
    draw = ImageDraw.Draw(image)
    draw.text((48, 30), "冰箱水墨屏 V0.7 轻薄封闭外壳", fill="#17352b", font=r06.load_font(44))
    draw.text((51, 88), "按实际 STL 渲染｜120 × 184 × 19 mm｜9颗 38×9×1.5 mm N45 硬磁条", fill="#52665f", font=r06.load_font(24))
    panels = [
        (45, 140, 925, 715),
        (975, 140, 1855, 715),
        (45, 755, 925, 1330),
        (975, 755, 1855, 1330),
    ]
    screen = r06.component_box(
        P["screen_window_width"] - 0.8,
        P["screen_window_height"] - 0.8,
        0.8, 0.0, 0.0, 2.5,
    )
    r06.render_panel(
        image, panels[0],
        [
            (screen, r06.exterior_front_vertices(screen.vertices), "#ddd7c7", 1.0),
            (front, r06.exterior_front_vertices(front.vertices), "#f2f4f0", 1.0),
        ],
        "正面闭合外观｜19 mm 薄型机身", yaw=0, pitch=0,
    )
    r06.render_panel(
        image, panels[1],
        [(rear, r06.exterior_rear_vertices(rear.vertices), "#bdcec6", 1.0)],
        "背面闭合外观｜SW1 / LED / BOOT / RESET", yaw=0, pitch=0,
    )
    r06.render_panel(
        image, panels[2],
        [
            (front, front.vertices, "#f2f4f0", 1.0),
            (carrier, carrier_vertices(carrier, 8.0), "#d7a85d", 1.0),
            (rear, rear_vertices(rear, 22.0), "#b4c8bf", 0.92),
        ],
        "爆炸结构：前框 / 下沉托板 / 局部加强后壳",
    )
    components = [
        (r06.component_box(P["battery_width"], P["battery_height"], P["battery_thickness"],
                           P["battery_center_x"], P["battery_center_y"],
                           P["carrier_thickness"] - P["battery_recess_depth"]), "#e8bb4c"),
        (r06.component_box(P["esp_width"], P["esp_height"], P["esp_body_envelope"],
                           P["esp_center_x"], P["esp_center_y"], P["esp_post_top"]), "#3e76a8"),
        (r06.component_box(P["despi_width"], P["despi_height"], P["despi_body_envelope"],
                           P["despi_center_x"], P["despi_center_y"], P["carrier_thickness"]), "#429676"),
        (r06.component_box(P["lipo_width"], P["lipo_height"], P["lipo_body_envelope"],
                           P["lipo_center_x"], P["lipo_center_y"], P["lipo_post_top"]), "#76569b"),
    ]
    r06.render_panel(
        image, panels[3],
        [(carrier, carrier.vertices, "#d7a85d", 1.0), *[(mesh, mesh.vertices, colour, 0.95) for mesh, colour in components]],
        "开盖器件布局｜电池区域下沉 0.5 mm", yaw=-8, pitch=76,
    )
    draw.text(
        (950, 1390),
        "B1-B9 使用 38×9×1.5 mm N45 钕铁硼硬磁条；后盖夹紧螺丝仍使用 M2×14 mm。",
        anchor="mm", fill="#52665f", font=r06.load_font(21),
    )
    PREVIEWS.mkdir(parents=True, exist_ok=True)
    image.save(PREVIEWS / "assembly_effect_v0_7.png")
    image.crop((0, 0, 1900, 755)).save(PREVIEWS / "installed_effect_v0_7.png")
    exploded = image.crop((0, 715, 970, 1340)).resize((1552, 1000), Image.Resampling.LANCZOS)
    exploded.save(PREVIEWS / "exploded_view_v0_7.png")
    draw_corner_fit_effect()
    draw_rear_coupon_revision()
    draw_rear_openings_detail(rear)
    draw_rear_left_wall_revision(rear)
    draw_front_retainer_revision(front)
    draw_rear_button_labels_outside()


if __name__ == "__main__":
    main()
