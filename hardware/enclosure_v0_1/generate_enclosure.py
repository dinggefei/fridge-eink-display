#!/usr/bin/env python3
"""Generate the RefrigeratorFoodManagement portrait enclosure prototype.

The model is intentionally parameterized and conservative.  It is a V0.1 fit
prototype for the measured GDEM075F53, ESP32-S3 board, DESPI-C02, an 806090
battery, and a Seeed Lipo Rider Plus.  All dimensions are millimetres.

Outputs are standard binary STL files, an exploded GLB preview, a PNG preview,
and a JSON validation manifest.  Boolean operations use Manifold through
trimesh so every STL can be checked as a watertight solid before release.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw
from shapely.geometry import box as shapely_box
import trimesh


ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "output"
PREVIEWS = ROOT / "previews"


P = {
    # Finished enclosure envelope.  The extra 4 mm versus the early 124 mm
    # estimate gives safe side structure around the 112 mm glass pocket.
    "case_width": 128.0,
    "case_height": 200.0,
    "corner_radius": 6.0,
    "front_face_thickness": 3.0,
    "screen_gap_depth": 2.2,
    "midplate_thickness": 2.0,
    "rear_cover_depth": 21.0,
    "rear_skin_thickness": 4.0,
    "rear_wall_thickness": 2.1,
    # Good Display GDEM075F53.  Body clearance is 0.4 mm per side.
    "screen_body_width": 111.2,
    "screen_body_height": 170.2,
    "screen_pocket_width": 112.0,
    "screen_pocket_height": 171.0,
    "screen_window_width": 99.0,
    "screen_window_height": 164.0,
    "screen_center_y": -7.9,
    # Carrier and electronics envelopes.
    "midplate_width": 123.0,
    "midplate_height": 195.0,
    "battery_width": 63.0,
    "battery_height": 95.0,
    "battery_max_thickness": 10.0,
    "battery_center_x": 20.0,
    "battery_center_y": -38.0,
    "esp_width": 27.0,
    "esp_height": 65.0,
    "esp_center_x": 0.0,
    "esp_center_y": 59.0,
    "despi_width": 42.0,
    "despi_height": 24.0,
    "despi_center_x": 35.0,
    "despi_center_y": 24.0,
    "lipo_rider_width": 27.0,
    "lipo_rider_height": 43.0,
    "lipo_rider_center_x": -40.0,
    "lipo_rider_center_y": -78.0,
    # Hardware.
    "magnet_diameter": 10.4,
    "magnet_depth": 3.2,
    "m2_clearance": 2.4,
    "m2_insert_hole": 3.2,
}


FRONT_FASTENERS = [
    (-59.5, -65.0),
    (-59.5, 0.0),
    (-59.5, 65.0),
    (59.5, -65.0),
    (59.5, 0.0),
    (59.5, 65.0),
]
REAR_FASTENERS = [(-54.5, -90.0), (54.5, -90.0), (-54.5, 90.0), (54.5, 90.0)]
MAGNETS = [(-52.0, -65.0), (52.0, -65.0), (-52.0, -20.0), (52.0, -20.0), (-52.0, 25.0), (52.0, 25.0)]


def rounded_rect_polygon(width: float, height: float, radius: float):
    radius = max(0.0, min(radius, width / 2.0, height / 2.0))
    core = shapely_box(
        -width / 2.0 + radius,
        -height / 2.0 + radius,
        width / 2.0 - radius,
        height / 2.0 - radius,
    )
    return core.buffer(radius, quad_segs=12)


def rounded_prism(width: float, height: float, radius: float, depth: float, z0: float = 0.0):
    mesh = trimesh.creation.extrude_polygon(
        rounded_rect_polygon(width, height, radius), depth, engine="earcut"
    )
    mesh.apply_translation((0.0, 0.0, z0))
    return mesh


def cuboid(size, center):
    mesh = trimesh.creation.box(extents=np.asarray(size, dtype=float))
    mesh.apply_translation(np.asarray(center, dtype=float))
    return mesh


def cylinder(radius: float, height: float, center, sections: int = 48, axis: str = "z"):
    mesh = trimesh.creation.cylinder(radius=radius, height=height, sections=sections)
    if axis == "x":
        transform = trimesh.transformations.rotation_matrix(math.pi / 2.0, (0.0, 1.0, 0.0))
        mesh.apply_transform(transform)
    elif axis == "y":
        transform = trimesh.transformations.rotation_matrix(math.pi / 2.0, (1.0, 0.0, 0.0))
        mesh.apply_transform(transform)
    mesh.apply_translation(np.asarray(center, dtype=float))
    return mesh


def union(meshes):
    meshes = [m for m in meshes if m is not None]
    if len(meshes) == 1:
        return meshes[0]
    return trimesh.boolean.union(meshes, engine="manifold")


def difference(base, cutters):
    cutters = [c for c in cutters if c is not None]
    if not cutters:
        return base
    return trimesh.boolean.difference([base, *cutters], engine="manifold")


def slot(x: float, y: float, width: float = 3.0, height: float = 12.0):
    return cuboid((width, height, 5.0), (x, y, 1.0))


def build_front_bezel():
    face = rounded_prism(
        P["case_width"],
        P["case_height"],
        P["corner_radius"],
        P["front_face_thickness"],
    )
    window = cuboid(
        (P["screen_window_width"], P["screen_window_height"], 6.0),
        (0.0, P["screen_center_y"], 2.0),
    )
    face = difference(face, [window])

    # A shallow locator ring centers the glass without clamping it.  0.5 mm
    # EVA tape is applied inside this ring during assembly.
    locator_outer = cuboid(
        (116.0, 175.0, P["screen_gap_depth"]),
        (0.0, P["screen_center_y"], P["front_face_thickness"] + P["screen_gap_depth"] / 2.0),
    )
    locator_inner = cuboid(
        (P["screen_pocket_width"], P["screen_pocket_height"], P["screen_gap_depth"] + 2.0),
        (0.0, P["screen_center_y"], P["front_face_thickness"] + P["screen_gap_depth"] / 2.0),
    )
    locator = difference(locator_outer, [locator_inner])

    boss_height = 5.0
    bosses = [
        cylinder(3.5, boss_height, (x, y, P["front_face_thickness"] + boss_height / 2.0))
        for x, y in FRONT_FASTENERS
    ]
    body = union([face, locator, *bosses])
    insert_holes = [
        cylinder(
            P["m2_insert_hole"] / 2.0,
            4.7,
            (x, y, P["front_face_thickness"] + 5.0 - 4.7 / 2.0 + 0.1),
            sections=36,
        )
        for x, y in FRONT_FASTENERS
    ]
    return difference(body, insert_holes)


def battery_guides():
    cx, cy = P["battery_center_x"], P["battery_center_y"]
    half_w = P["battery_width"] / 2.0
    half_h = P["battery_height"] / 2.0
    z = P["midplate_thickness"] + 1.5
    guides = []
    for sy in (-1.0, 1.0):
        y = cy + sy * (half_h - 9.0)
        guides.append(cuboid((2.5, 18.0, 3.0), (cx - half_w - 1.25, y, z)))
        guides.append(cuboid((2.5, 18.0, 3.0), (cx + half_w + 1.25, y, z)))
    for sx in (-1.0, 1.0):
        x = cx + sx * (half_w - 9.0)
        guides.append(cuboid((18.0, 2.5, 3.0), (x, cy - half_h - 1.25, z)))
        guides.append(cuboid((18.0, 2.5, 3.0), (x, cy + half_h + 1.25, z)))
    return guides


def build_midplate():
    base = rounded_prism(
        P["midplate_width"], P["midplate_height"], 4.0, P["midplate_thickness"]
    )

    # M2 heat-set insert bosses used by the removable rear cover.
    boss_height = 5.0
    rear_bosses = [
        cylinder(3.8, boss_height, (x, y, P["midplate_thickness"] + boss_height / 2.0))
        for x, y in REAR_FASTENERS
    ]
    body = union([base, *battery_guides(), *rear_bosses])

    cutters = []
    # Right-side FPC relief; the screen orientation can be rotated 180 degrees
    # if the physical batch exits on the opposite side.
    cutters.append(cuboid((8.0, 38.0, 6.0), (60.0, P["screen_center_y"], 1.0)))

    # Front frame screws.
    for x, y in FRONT_FASTENERS:
        cutters.append(cylinder(P["m2_clearance"] / 2.0, 5.0, (x, y, 1.0), sections=36))

    # Rear cover insert holes, open only from the component side.
    for x, y in REAR_FASTENERS:
        cutters.append(
            cylinder(
                P["m2_insert_hole"] / 2.0,
                4.7,
                (x, y, P["midplate_thickness"] + boss_height - 4.7 / 2.0 + 0.1),
                sections=36,
            )
        )

    # Battery hook-and-loop strap slots, two independent straps.
    for y in (-58.0, -24.0):
        cutters.append(slot(-14.0, y, 3.0, 14.0))
        cutters.append(slot(54.0, y, 3.0, 14.0))

    # ESP32-S3: two straps around a vertical 27 x 65 mm envelope.
    for y in (47.0, 73.0):
        cutters.append(slot(-16.5, y, 3.0, 12.0))
        cutters.append(slot(16.5, y, 3.0, 12.0))

    # DESPI-C02: one horizontal strap around a 42 x 24 mm envelope.
    cutters.append(slot(10.5, P["despi_center_y"], 3.0, 12.0))
    cutters.append(slot(58.0, P["despi_center_y"], 3.0, 12.0))

    # Lipo Rider Plus: one strap.  The Type-C input is oriented toward the
    # bottom opening in the rear shell.
    cutters.append(slot(-55.5, -72.0, 3.0, 12.0))
    cutters.append(slot(-24.5, -72.0, 3.0, 12.0))

    # General cable tie points between the driver and controller.
    cutters.append(slot(-18.0, 18.0, 10.0, 3.0))
    cutters.append(slot(-18.0, 30.0, 10.0, 3.0))
    return difference(body, cutters)


def build_rear_cover():
    depth = P["rear_cover_depth"]
    shell = rounded_prism(
        P["case_width"], P["case_height"], P["corner_radius"], depth
    )
    inner_width = 123.8
    inner_height = 195.8
    cavity = rounded_prism(
        inner_width,
        inner_height,
        4.0,
        depth - P["rear_skin_thickness"] + 1.0,
        P["rear_skin_thickness"],
    )
    shell = difference(shell, [cavity])

    # A 2 mm wide ledge captures the midplate 2 mm below the open rim.
    ledge_outer = rounded_prism(inner_width, inner_height, 4.0, 2.0, depth - 2.0)
    ledge_inner = rounded_prism(inner_width - 4.0, inner_height - 4.0, 3.0, 4.0, depth - 3.0)
    ledge = difference(ledge_outer, [ledge_inner])

    # Screw pillars stop before the insert bosses, which extend from the
    # midplate into the cavity.  M2 x 18 mm screws are the nominal choice.
    pillar_top = 14.2
    pillars = [
        cylinder(3.8, pillar_top - P["rear_skin_thickness"], (x, y, (pillar_top + P["rear_skin_thickness"]) / 2.0))
        for x, y in REAR_FASTENERS
    ]
    body = union([shell, ledge, *pillars])

    cutters = []
    for x, y in REAR_FASTENERS:
        cutters.append(cylinder(P["m2_clearance"] / 2.0, depth + 2.0, (x, y, depth / 2.0), sections=36))
        cutters.append(cylinder(2.3, 2.2, (x, y, 1.0), sections=36))

    # Six blind magnet pockets leave a 0.8 mm PETG skin against the fridge.
    for x, y in MAGNETS:
        cutters.append(
            cylinder(
                P["magnet_diameter"] / 2.0,
                P["magnet_depth"] + 0.2,
                (x, y, 0.8 + (P["magnet_depth"] + 0.2) / 2.0),
                sections=64,
            )
        )

    # Bottom access: charge Type-C and the Lipo Rider switch.  These openings
    # are deliberately generous for the first fit iteration.
    cutters.append(cuboid((15.0, 7.0, 9.0), (-40.0, -99.0, 16.0)))
    cutters.append(cuboid((9.0, 7.0, 8.0), (-24.0, -99.0, 16.5)))
    # Two small pressure/air relief slots on the bottom edge, away from the
    # electronics and invisible in normal portrait use.
    cutters.append(cuboid((12.0, 7.0, 2.0), (17.0, -99.0, 7.0)))
    cutters.append(cuboid((12.0, 7.0, 2.0), (35.0, -99.0, 7.0)))
    return difference(body, cutters)


def build_screen_width_gauge():
    base = rounded_prism(120.0, 18.0, 2.0, 3.0)
    rail_z = 4.1
    left = cuboid((2.0, 18.0, 2.2), (-57.0, 0.0, rail_z))
    right = cuboid((2.0, 18.0, 2.2), (57.0, 0.0, rail_z))
    return union([base, left, right])


def build_insert_magnet_coupon():
    block = rounded_prism(42.0, 24.0, 3.0, 6.0)
    magnet = cylinder(P["magnet_diameter"] / 2.0, 3.4, (-10.0, 0.0, 4.3), sections=64)
    insert = cylinder(P["m2_insert_hole"] / 2.0, 5.2, (10.0, 0.0, 3.9), sections=36)
    clearance = cylinder(P["m2_clearance"] / 2.0, 8.0, (17.0, 0.0, 3.0), sections=36)
    return difference(block, [magnet, insert, clearance])


def build_battery_thickness_gauge():
    outer = cuboid((30.0, 20.0, 14.0), (0.0, 0.0, 7.0))
    # A 9 mm open-ended slot checks a nominal 8 mm protected pouch without
    # squeezing it.  Do not force a cell into a rough or undersized print.
    slot_mesh = cuboid((27.0, 22.0, 9.0), (3.0, 0.0, 7.0))
    return difference(outer, [slot_mesh])


def ensure_mesh(name: str, mesh: trimesh.Trimesh):
    mesh.remove_unreferenced_vertices()
    mesh.fix_normals()
    if not mesh.is_watertight:
        raise RuntimeError(f"{name} is not watertight")
    if not mesh.is_volume:
        raise RuntimeError(f"{name} is not a valid positive volume")
    return mesh


def export_binary_stl(name: str, mesh: trimesh.Trimesh):
    path = OUTPUT / f"{name}.stl"
    path.write_bytes(trimesh.exchange.stl.export_stl(mesh))
    return path


def render_meshes(items, path: Path):
    canvas = Image.new("RGB", (1800, 900), "#f6f4ef")
    draw = ImageDraw.Draw(canvas)
    title_font = None
    draw.text((60, 40), "RefrigeratorFoodManagement enclosure V0.1", fill="#18332a", font=title_font)
    palette = [(54, 114, 88), (224, 178, 79), (74, 99, 137)]
    panels = [(40, 100, 560, 840), (620, 100, 1140, 840), (1200, 100, 1720, 840)]
    angles = np.radians([58.0, 0.0, -38.0])
    rx = np.array(
        [[1, 0, 0], [0, math.cos(angles[0]), -math.sin(angles[0])], [0, math.sin(angles[0]), math.cos(angles[0])]]
    )
    rz = np.array(
        [[math.cos(angles[2]), -math.sin(angles[2]), 0], [math.sin(angles[2]), math.cos(angles[2]), 0], [0, 0, 1]]
    )
    rot = rz @ rx
    light = np.array([0.25, -0.35, 0.9])
    light /= np.linalg.norm(light)

    for (label, mesh), panel, base_color in zip(items, panels, palette):
        x0, y0, x1, y1 = panel
        vertices = mesh.vertices @ rot.T
        faces = mesh.faces
        projected = vertices[:, :2].copy()
        span = np.ptp(projected, axis=0)
        scale = min((x1 - x0 - 40) / max(span[0], 1), (y1 - y0 - 80) / max(span[1], 1))
        projected *= scale
        projected[:, 0] += (x0 + x1) / 2.0 - projected[:, 0].mean()
        projected[:, 1] = -projected[:, 1]
        projected[:, 1] += (y0 + y1) / 2.0 - projected[:, 1].mean()
        face_depth = vertices[faces][:, :, 2].mean(axis=1)
        order = np.argsort(face_depth)
        normals = mesh.face_normals @ rot.T
        for idx in order:
            pts = [tuple(projected[v]) for v in faces[idx]]
            brightness = 0.55 + 0.40 * max(0.0, float(np.dot(normals[idx], light)))
            color = tuple(int(min(255, c * brightness + 25)) for c in base_color)
            draw.polygon(pts, fill=color)
        draw.rounded_rectangle(panel, radius=20, outline="#d8d3c7", width=3)
        draw.text((x0 + 20, y1 - 34), label, fill="#18332a", font=title_font)
    canvas.save(path)


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    PREVIEWS.mkdir(parents=True, exist_ok=True)

    parts = {
        "front_bezel_v0_1": ensure_mesh("front_bezel", build_front_bezel()),
        "middle_carrier_v0_1": ensure_mesh("middle_carrier", build_midplate()),
        "rear_cover_v0_1": ensure_mesh("rear_cover", build_rear_cover()),
        "fit_test_screen_width_112mm": ensure_mesh("screen_gauge", build_screen_width_gauge()),
        "fit_test_m2_insert_and_magnet": ensure_mesh("insert_magnet_coupon", build_insert_magnet_coupon()),
        "fit_test_battery_thickness_9mm": ensure_mesh("battery_gauge", build_battery_thickness_gauge()),
    }

    manifest = {
        "design": "RefrigeratorFoodManagement portrait enclosure V0.1",
        "units": "mm",
        "status": "fit prototype; physical re-measurement required before production",
        "parameters": P,
        "parts": {},
    }
    for name, mesh in parts.items():
        file_path = export_binary_stl(name, mesh)
        bounds = mesh.bounds
        manifest["parts"][name] = {
            "file": file_path.name,
            "watertight": bool(mesh.is_watertight),
            "is_volume": bool(mesh.is_volume),
            "body_count": int(len(mesh.split(only_watertight=False))),
            "vertices": int(len(mesh.vertices)),
            "faces": int(len(mesh.faces)),
            "volume_mm3": round(float(mesh.volume), 2),
            "bounds_mm": [[round(float(v), 3) for v in row] for row in bounds],
            "size_mm": [round(float(v), 3) for v in (bounds[1] - bounds[0])],
        }

    # Exploded preview for common 3D viewers.  Print files remain separate STL.
    scene = trimesh.Scene()
    for idx, key in enumerate(("front_bezel_v0_1", "middle_carrier_v0_1", "rear_cover_v0_1")):
        mesh = parts[key].copy()
        mesh.visual.face_colors = [
            (54, 114, 88, 255),
            (224, 178, 79, 255),
            (74, 99, 137, 255),
        ][idx]
        transform = np.eye(4)
        transform[0, 3] = (idx - 1) * 145.0
        scene.add_geometry(mesh, node_name=key, transform=transform)
    (PREVIEWS / "enclosure_exploded_preview.glb").write_bytes(scene.export(file_type="glb"))
    render_meshes(
        [
            ("Front bezel", parts["front_bezel_v0_1"]),
            ("Middle carrier", parts["middle_carrier_v0_1"]),
            ("Rear cover", parts["rear_cover_v0_1"]),
        ],
        PREVIEWS / "enclosure_exploded_preview.png",
    )
    (OUTPUT / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(manifest["parts"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
