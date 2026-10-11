#!/usr/bin/env python3
"""Standalone Pillow rasterizer helpers used by the V0.7 renderer."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont
import trimesh


ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "output"
PREVIEWS = ROOT / "previews"
GENERATOR = ROOT / "_geometry_base_v0_7.py"


def load_generator():
    spec = importlib.util.spec_from_file_location("rfm_enclosure_v07_render_base", GENERATOR)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load generator: {GENERATOR}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


gen = load_generator()
P = gen.P


def load_font(size):
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


def color_rgb(hex_color):
    value = hex_color.lstrip("#")
    return tuple(int(value[index:index + 2], 16) for index in (0, 2, 4))


def blend(color, background, alpha):
    return tuple(round(alpha * a + (1.0 - alpha) * b) for a, b in zip(color, background))


def shade(color, factor):
    return tuple(max(0, min(255, round(channel * factor))) for channel in color)


def rotation_matrix(yaw_deg=-42.0, pitch_deg=63.0, roll_deg=0.0):
    yaw, pitch, roll = np.radians([yaw_deg, pitch_deg, roll_deg])
    rz = np.array([[np.cos(yaw), -np.sin(yaw), 0], [np.sin(yaw), np.cos(yaw), 0], [0, 0, 1]])
    rx = np.array([[1, 0, 0], [0, np.cos(pitch), -np.sin(pitch)], [0, np.sin(pitch), np.cos(pitch)]])
    ry = np.array([[np.cos(roll), 0, np.sin(roll)], [0, 1, 0], [-np.sin(roll), 0, np.cos(roll)]])
    return ry @ rx @ rz


def component_box(width, height, depth, center_x, center_y, z0):
    mesh = trimesh.creation.box(extents=(width, height, depth))
    mesh.apply_translation((center_x, center_y, z0 + depth / 2.0))
    return mesh


def rear_vertices(mesh, explode=0.0):
    vertices = mesh.vertices.copy()
    vertices[:, 2] = P["assembled_thickness"] - vertices[:, 2] + explode
    return vertices


def carrier_vertices(mesh, explode=0.0):
    vertices = mesh.vertices.copy()
    vertices[:, 2] += 4.0 + explode
    return vertices


def exterior_front_vertices(vertices):
    result = vertices.copy()
    result[:, 2] *= -1.0
    return result


def exterior_rear_vertices(vertices):
    result = vertices.copy()
    result[:, 2] *= -1.0
    return result


def render_panel(image, box, entries, title, yaw=-42, pitch=63):
    """Render entries as (mesh, vertices, colour, alpha) into one panel."""
    draw = ImageDraw.Draw(image)
    x0, y0, x1, y1 = box
    draw.rounded_rectangle(box, radius=28, fill="#ffffff", outline="#d6ddd8", width=3)
    draw.text((x0 + 24, y0 + 20), title, fill="#17352b", font=load_font(24))

    rotation = rotation_matrix(yaw, pitch)
    transformed = []
    for mesh, vertices, colour, alpha in entries:
        rotated = np.asarray(vertices) @ rotation.T
        transformed.append((mesh, rotated, color_rgb(colour), alpha))
    all_vertices = np.vstack([vertices for _, vertices, _, _ in transformed])
    projected = all_vertices[:, :2]
    available_w = x1 - x0 - 70
    available_h = y1 - y0 - 115
    span = np.maximum(projected.max(axis=0) - projected.min(axis=0), 1e-6)
    scale = min(available_w / span[0], available_h / span[1])
    centre_2d = (projected.max(axis=0) + projected.min(axis=0)) / 2.0
    screen_centre = np.array([(x0 + x1) / 2.0, (y0 + y1) / 2.0 + 24])

    triangles = []
    light = np.array([-0.3, -0.45, 0.84])
    light /= np.linalg.norm(light)
    background = color_rgb("#ffffff")
    for mesh, vertices, colour, alpha in transformed:
        for face in mesh.faces:
            tri = vertices[face]
            normal = np.cross(tri[1] - tri[0], tri[2] - tri[0])
            length = np.linalg.norm(normal)
            if length < 1e-9:
                continue
            normal /= length
            lighting = 0.68 + 0.32 * abs(float(np.dot(normal, light)))
            fill = shade(blend(colour, background, alpha), lighting)
            points = (tri[:, :2] - centre_2d) * scale
            points[:, 1] *= -1.0
            points += screen_centre
            triangles.append((float(tri[:, 2].mean()), [tuple(value) for value in points], fill))
    for _, points, fill in sorted(triangles, key=lambda item: item[0]):
        draw.polygon(points, fill=fill)


def main():
    front = trimesh.load_mesh(OUTPUT / "front_bezel_v0_6.stl")
    carrier = trimesh.load_mesh(OUTPUT / "electronics_carrier_v0_6.stl")
    rear = trimesh.load_mesh(OUTPUT / "rear_cover_v0_6.stl")

    image = Image.new("RGB", (1900, 1450), "#f4f2ec")
    draw = ImageDraw.Draw(image)
    draw.text((48, 30), "冰箱水墨屏 V0.6 紧凑封闭外壳", fill="#17352b", font=load_font(44))
    draw.text((51, 88), "按实际 STL 渲染｜120 × 184 × 21.4 mm｜三件式可维护结构", fill="#52665f", font=load_font(24))

    panels = [
        (45, 140, 925, 715),
        (975, 140, 1855, 715),
        (45, 755, 925, 1330),
        (975, 755, 1855, 1330),
    ]
    screen = component_box(
        P["screen_window_width"] - 0.8,
        P["screen_window_height"] - 0.8,
        0.8, 0.0, 0.0, 2.5,
    )
    render_panel(
        image, panels[0],
        [
            (screen, exterior_front_vertices(screen.vertices), "#ddd7c7", 1.0),
            (front, exterior_front_vertices(front.vertices), "#f2f4f0", 1.0),
        ],
        "正面闭合外观｜对称窄边框",
        yaw=0, pitch=0,
    )
    render_panel(
        image, panels[1],
        [(rear, exterior_rear_vertices(rear.vertices), "#bdcec6", 1.0)],
        "背面闭合外观｜下沉螺丝与维护孔",
        yaw=0, pitch=0,
    )
    render_panel(
        image, panels[2],
        [
            (front, front.vertices, "#f2f4f0", 1.0),
            (carrier, carrier_vertices(carrier, 8.0), "#d7a85d", 1.0),
            (rear, rear_vertices(rear, 22.0), "#b4c8bf", 0.92),
        ],
        "爆炸结构：前框 / 托板 / 后壳",
    )

    components = [
        (component_box(P["battery_width"], P["battery_height"], P["battery_thickness"],
                       P["battery_center_x"], P["battery_center_y"], P["carrier_thickness"]), "#e8bb4c"),
        (component_box(P["esp_width"], P["esp_height"], 8.0,
                       P["esp_center_x"], P["esp_center_y"], P["esp_post_top"]), "#3e76a8"),
        (component_box(P["despi_width"], P["despi_height"], 4.0,
                       P["despi_center_x"], P["despi_center_y"], P["carrier_thickness"]), "#429676"),
        (component_box(P["lipo_width"], P["lipo_height"], 7.5,
                       P["lipo_center_x"], P["lipo_center_y"], P["lipo_post_top"]), "#76569b"),
    ]
    render_panel(
        image, panels[3],
        [(carrier, carrier.vertices, "#d7a85d", 1.0), *[(mesh, mesh.vertices, colour, 0.95) for mesh, colour in components]],
        "开盖器件布局（保守高度包络）",
        yaw=-8, pitch=76,
    )

    draw.text(
        (950, 1390),
        "顶部仅保留 USB-C；四周与底边连续封闭；磁铁全部采用内侧盲孔安装。",
        anchor="mm", fill="#52665f", font=load_font(21),
    )
    PREVIEWS.mkdir(parents=True, exist_ok=True)
    image.save(PREVIEWS / "assembly_effect_v0_6.png")

    # Separate high-resolution views for installation review and printing
    # discussions.  These are crops of the same actual-STL rendering, so their
    # geometry remains consistent with the delivered parts.
    installed = image.crop((0, 0, 1900, 755))
    installed.save(PREVIEWS / "installed_effect_v0_6.png")
    exploded = image.crop((0, 715, 970, 1340))
    exploded = exploded.resize((1552, 1000), Image.Resampling.LANCZOS)
    exploded.save(PREVIEWS / "exploded_view_v0_6.png")


if __name__ == "__main__":
    main()
