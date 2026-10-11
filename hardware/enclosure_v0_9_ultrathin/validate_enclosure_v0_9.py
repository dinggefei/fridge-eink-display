#!/usr/bin/env python3
"""Validate the generated V0.9 STL package and its locked dimensions."""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import zipfile

import numpy as np
import trimesh


ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "output"
PACKAGE = ROOT / "RFM_enclosure_v0_9_STL"


def close(actual: float, expected: float, tolerance: float = 0.02) -> bool:
    return abs(actual - expected) <= tolerance


def main() -> None:
    manifest = json.loads((OUTPUT / "manifest_v0_9.json").read_text(encoding="utf-8"))
    errors: list[str] = []

    expected = {
        "front_bezel_v0_9_1p0mm.stl": (120.0, 184.0, 4.6),
        "electronics_carrier_v0_9_1p2mm.stl": (115.4, 179.4, None),
        "rear_cover_v0_9_15p0mm.stl": (120.0, 184.0, 14.0),
        "fit_test_front_corner_v0_9_1p0mm.stl": (35.0, 37.0, 4.6),
        "fit_test_usb_c_opening_11p5x7p5_v0_9.stl": (20.0, 8.0, 14.0),
        "fit_test_boot_reset_buttons_4p5mm_v0_9.stl": (30.5, 13.5, 5.5),
        "fit_test_lipo_indicator_opening_5p2x18_v0_9.stl": (39.0, 37.0, 14.0),
    }
    checks = []
    for filename, wanted in expected.items():
        path = OUTPUT / filename
        if not path.exists():
            errors.append(f"missing {filename}")
            continue
        # Weld coincident STL triangle vertices before topology checks.
        mesh = trimesh.load_mesh(path, process=True)
        body_count = len(mesh.split(only_watertight=False))
        checks.append(
            {
                "file": filename,
                "watertight": bool(mesh.is_watertight),
                "body_count": body_count,
                "extents_mm": [round(float(v), 3) for v in mesh.extents],
                "volume_mm3": round(float(abs(mesh.volume)), 3),
            }
        )
        if not mesh.is_watertight:
            errors.append(f"{filename} is not watertight")
        if mesh.volume <= 0:
            errors.append(f"{filename} has non-positive volume")
        if body_count != 1:
            errors.append(f"{filename} has {body_count} disconnected bodies, expected 1")
        for axis, target in enumerate(wanted):
            if target is not None and not close(float(mesh.extents[axis]), target):
                errors.append(
                    f"{filename} axis {axis} extent {mesh.extents[axis]:.3f}, expected {target:.3f}"
                )

    usb = manifest["usb_c_opening"]
    if usb["size"] != [11.5, 7.5]:
        errors.append(f"USB-C opening changed unexpectedly: {usb['size']}")
    if not close(float(usb["model_center"][0]), 0.0, 0.001):
        errors.append(f"USB-C X is not aligned to the Lipo port: {usb['model_center'][0]}")
    if not close(float(usb["model_center"][2]), 6.6, 0.001):
        errors.append(f"USB-C Z was not recalculated to 6.6 mm: {usb['model_center'][2]}")
    carrier_spec = manifest["carrier"]
    if not close(float(carrier_spec["thickness"]), 1.2, 0.001):
        errors.append("carrier ordinary thickness is not 1.2 mm")
    if not close(float(carrier_spec["battery_local_floor"]), 0.6, 0.001):
        errors.append("battery local floor is not 0.6 mm")
    if not close(float(carrier_spec["esp_post_top"]), 2.6, 0.001):
        errors.append("ESP32 post top is not model Z=2.6 mm")
    if not close(float(carrier_spec["lipo_post_top"]), 1.8, 0.001):
        errors.append("Lipo Rider post top is not model Z=1.8 mm")
    if not close(float(carrier_spec["lipo_post_top"]) - float(carrier_spec["thickness"]), 0.6, 0.001):
        errors.append("Lipo Rider post is not 0.6 mm above the carrier surface")
    carrier_mesh = trimesh.load_mesh(
        OUTPUT / "electronics_carrier_v0_9_1p2mm.stl", process=True
    )
    carrier_z_planes = {
        str(z): int(np.sum(np.isclose(carrier_mesh.vertices[:, 2], z, atol=0.01)))
        for z in (0.6, 1.2)
    }
    if carrier_z_planes["0.6"] < 4:
        errors.append("actual carrier STL does not contain the 0.6 mm battery floor")
    if carrier_z_planes["1.2"] < 4:
        errors.append("actual carrier STL does not contain the 1.2 mm ordinary top plane")
    actual_lipo_post_tops = {}
    post_radius = float(carrier_spec["lipo_post_diameter"]) / 2.0
    for index, centre in enumerate(carrier_spec["lipo_post_centers_xy"], start=1):
        cx, cy = [float(value) for value in centre]
        radial_distance = np.hypot(
            carrier_mesh.vertices[:, 0] - cx,
            carrier_mesh.vertices[:, 1] - cy,
        )
        local_vertices = carrier_mesh.vertices[radial_distance <= post_radius + 0.02]
        actual_top = round(float(local_vertices[:, 2].max()), 3)
        actual_lipo_post_tops[f"P{index}"] = actual_top
        if not close(actual_top, 1.8, 0.02):
            errors.append(f"Lipo Rider post P{index} top is {actual_top}, expected 1.8")
    if not close(float(manifest["clearances"]["m2x12_estimated_engagement"]), 3.2, 0.001):
        errors.append("M2x12 engagement is not 3.2 mm")
    if not close(float(manifest["clearances"]["battery_to_magnet_pocket"]), 0.8, 0.001):
        errors.append("battery-to-magnet clearance is not 0.8 mm")

    rear_spec = manifest["rear"]
    if not close(float(rear_spec["normal_skin"]), 1.0, 0.001):
        errors.append("rear normal skin is not 1.0 mm")
    if not close(float(rear_spec["magnet_outer_skin"]), 0.6, 0.001):
        errors.append("magnet outer skin is not 0.6 mm")
    if not close(float(rear_spec["left_restored_band_thickness"]), 1.2, 0.001):
        errors.append("rear left restored band is not 1.2 mm")
    if rear_spec.get("button_access_holes") != []:
        errors.append("BOOT/RESET through-holes are still declared")
    if rear_spec.get("integrated_buttons") != ["BOOT", "RESET"]:
        errors.append("BOOT/RESET integrated buttons are not declared")
    if rear_spec.get("engraved_button_labels") != []:
        errors.append("BOOT/RESET engraving is still declared")

    # Verify the actual boolean opening in the STL, not only the manifest.
    rear = trimesh.load_mesh(OUTPUT / "rear_cover_v0_9_15p0mm.stl", process=True)
    rear_z_planes = {
        str(z): int(np.sum(np.isclose(rear.vertices[:, 2], z, atol=0.01)))
        for z in (0.6, 1.0)
    }
    if rear_z_planes["0.6"] < 4:
        errors.append("actual rear STL does not contain the 0.6 mm magnet outer skin")
    if rear_z_planes["1.0"] < 4:
        errors.append("actual rear STL does not contain the 1.0 mm normal inner plane")
    left_band_inner_x = -60.0 + float(rear_spec["left_restored_band_thickness"])
    left_band_vertices = rear.vertices[
        np.isclose(rear.vertices[:, 0], left_band_inner_x, atol=0.01)
        & (rear.vertices[:, 2] >= 12.19)
    ]
    if len(left_band_vertices) < 2:
        errors.append("actual rear STL does not contain the 1.2 mm left restored band")
    opening_vertices = rear.vertices[
        (rear.vertices[:, 1] > 88.0)
        & (np.abs(rear.vertices[:, 0]) < 8.0)
        & (rear.vertices[:, 2] > 2.0)
        & (rear.vertices[:, 2] < 12.0)
    ]
    opening_x = sorted(set(np.round(opening_vertices[:, 0], 3)))
    opening_z = sorted(set(np.round(opening_vertices[:, 2], 3)))
    if opening_x != [-5.75, 5.75]:
        errors.append(f"actual USB-C X edges are {opening_x}, expected [-5.75, 5.75]")
    if opening_z != [2.85, 10.35]:
        errors.append(f"actual USB-C Z edges are {opening_z}, expected [2.85, 10.35]")

    # The removed lettering formerly created vertices at its 0.6 mm engraving
    # floor.  The same XY regions must now contain only the flat outer and
    # inner rear-skin planes, with no intermediate-depth engraving geometry.
    label_region_depths = {}
    for label, bounds in rear_spec["former_button_label_regions_xy"].items():
        x0, y0, x1, y1 = bounds
        region_vertices = rear.vertices[
            (rear.vertices[:, 0] >= x0 - 0.01)
            & (rear.vertices[:, 0] <= x1 + 0.01)
            & (rear.vertices[:, 1] >= y0 - 0.01)
            & (rear.vertices[:, 1] <= y1 + 0.01)
        ]
        intermediate = sorted(
            set(
                np.round(
                    region_vertices[
                        (region_vertices[:, 2] > 0.05)
                        & (region_vertices[:, 2] < float(rear_spec["normal_skin"]) - 0.01),
                        2,
                    ],
                    3,
                )
            )
        )
        label_region_depths[label] = [float(value) for value in intermediate]
        if intermediate:
            errors.append(
                f"{label} region still has engraving-depth vertices: {intermediate}"
            )

    semi_enclosed_buttons = {}
    expected_tip_z = float(rear_spec["button_plunger_tip_model_z"])
    expected_tip_radius = float(rear_spec["button_plunger_tip_diameter"]) / 2.0
    slot_spec = rear_spec["button_arc_slot"]
    hinge_spec = rear_spec["button_hinge"]
    slot_inner_radius = float(slot_spec["inner_diameter"]) / 2.0
    slot_outer_radius = float(slot_spec["outer_diameter"]) / 2.0
    hinge_thickness = float(hinge_spec["thickness"])
    if not close(float(slot_spec["open_arc_degrees"]), 270.0, 0.001):
        errors.append("BOOT/RESET open arc is not 270 degrees")
    if not close(float(hinge_spec["connected_arc_degrees"]), 90.0, 0.001):
        errors.append("BOOT/RESET connected hinge arc is not 90 degrees")
    if not close(float(slot_spec["width"]), 0.8, 0.001):
        errors.append("BOOT/RESET arc slot width is not 0.8 mm")
    if not close(float(rear_spec["button_plunger_projection_from_inner_face"]), 4.5, 0.001):
        errors.append("BOOT/RESET plunger length is not 4.5 mm")
    if not close(float(rear_spec["button_plunger_diameter"]), 1.8, 0.001):
        errors.append("BOOT/RESET plunger diameter is not 1.8 mm")
    if not close(float(rear_spec["button_plunger_tip_chamfer"]), 0.2, 0.001):
        errors.append("BOOT/RESET plunger tip chamfer is not 0.2 mm")
    if not close(float(rear_spec["button_resting_clearance"]), 0.7, 0.001):
        errors.append("BOOT/RESET nominal resting clearance is not 0.7 mm")

    def nearest_vertex_distance(target: np.ndarray) -> float:
        return float(np.linalg.norm(rear.vertices - target, axis=1).min())

    for button, centre in rear_spec["button_centers_xy"].items():
        cx, cy = centre
        radial_distance = np.hypot(
            rear.vertices[:, 0] - cx,
            rear.vertices[:, 1] - cy,
        )
        tip_ring = rear.vertices[
            (np.abs(radial_distance - expected_tip_radius) < 0.02)
            & (np.abs(rear.vertices[:, 2] - expected_tip_z) < 0.02)
        ]
        local_vertices = rear.vertices[radial_distance <= slot_outer_radius + 0.7]
        actual_tip_z = round(float(local_vertices[:, 2].max()), 3)

        # The 270-degree slot includes the lower side (270 degrees); the
        # retained upper bridge is locally relieved to a 0.4 mm floor at
        # 90 degrees.  Exact cutter endpoints become STL vertices.
        probe_distances = {}
        for label, radius, angle_degrees, z in (
            ("slot_inner_lower_outer_face", slot_inner_radius, 270.0, 0.0),
            ("slot_outer_lower_outer_face", slot_outer_radius, 270.0, 0.0),
            ("slot_inner_lower_inner_face", slot_inner_radius, 270.0, float(rear_spec["normal_skin"])),
            ("slot_outer_lower_inner_face", slot_outer_radius, 270.0, float(rear_spec["normal_skin"])),
            ("hinge_inner_floor", slot_inner_radius, 90.0, hinge_thickness),
            ("hinge_outer_floor", slot_outer_radius, 90.0, hinge_thickness),
        ):
            angle = np.radians(angle_degrees)
            target = np.array(
                [cx + radius * np.cos(angle), cy + radius * np.sin(angle), z]
            )
            probe_distances[label] = round(nearest_vertex_distance(target), 4)

        semi_enclosed_buttons[button] = {
            "model_center_xy": centre,
            "actual_tip_model_z": actual_tip_z,
            "plunger_projection_from_inner_face": round(
                actual_tip_z - float(rear_spec["normal_skin"]), 3
            ),
            "tip_ring_vertices": int(len(tip_ring)),
            "geometry_probe_distance_mm": probe_distances,
        }
        if not close(actual_tip_z, expected_tip_z, 0.02) or len(tip_ring) < 48:
            errors.append(f"{button} 4.5 mm plunger or its chamfered tip has the wrong geometry")
        failed_probes = [
            label for label, distance in probe_distances.items() if distance > 0.03
        ]
        if failed_probes:
            errors.append(
                f"{button} semi-enclosed slot/hinge probes failed: {failed_probes}"
            )

    lipo = manifest["lipo_indicator_opening"]
    if not close(float(lipo["total_height"]), 18.0, 0.001):
        errors.append("Lipo indicator opening total height is not 18 mm")
    if not close(float(lipo["straight_length"]), 16.0, 0.001):
        errors.append("Lipo indicator opening straight length is not 16 mm")
    if not lipo.get("lower_edge_preserved"):
        errors.append("Lipo indicator opening lower edge is not declared preserved")

    # Check the actual rounded-rectangle endpoints in the STL.  Restrict X to
    # the central straight section so the extrema are unambiguous despite R1.
    lipo_cx, _lipo_cy = [float(v) for v in lipo["model_center"]]
    lipo_lower = float(lipo["lower_edge_y"])
    lipo_upper = float(lipo["upper_edge_y"])
    central_opening_vertices = rear.vertices[
        (np.abs(rear.vertices[:, 0] - lipo_cx) <= 1.61)
        & (rear.vertices[:, 1] >= lipo_lower - 0.05)
        & (rear.vertices[:, 1] <= lipo_upper + 0.05)
        & (rear.vertices[:, 2] >= -0.01)
        & (rear.vertices[:, 2] <= float(rear_spec["normal_skin"]) + 0.01)
    ]
    actual_lipo_lower = round(float(central_opening_vertices[:, 1].min()), 3)
    actual_lipo_upper = round(float(central_opening_vertices[:, 1].max()), 3)
    if not close(actual_lipo_lower, lipo_lower, 0.02):
        errors.append(
            f"actual Lipo opening lower edge is {actual_lipo_lower}, expected {lipo_lower}"
        )
    if not close(actual_lipo_upper, lipo_upper, 0.02):
        errors.append(
            f"actual Lipo opening upper edge is {actual_lipo_upper}, expected {lipo_upper}"
        )

    report = {
        "design": "V0.9 ultrathin enclosure validation",
        "result": "PASS" if not errors else "FAIL",
        "checks": checks,
        "locked_usb_c_opening_mm": usb["size"],
        "recalculated_usb_c_model_center_mm": usb["model_center"],
        "actual_usb_c_edges_mm": {"x": opening_x, "z": opening_z},
        "actual_lipo_post_tops_model_z_mm": actual_lipo_post_tops,
        "actual_strength_planes": {
            "carrier_vertex_counts_by_z": carrier_z_planes,
            "rear_vertex_counts_by_z": rear_z_planes,
            "rear_left_band_inner_x": round(left_band_inner_x, 3),
            "rear_left_band_probe_vertices": int(len(left_band_vertices)),
        },
        "removed_button_label_region_depths_mm": label_region_depths,
        "semi_enclosed_buttons": semi_enclosed_buttons,
        "actual_lipo_indicator_edges_y_mm": {
            "lower": actual_lipo_lower,
            "upper": actual_lipo_upper,
        },
        "errors": errors,
    }
    report_path = OUTPUT / "validation_report_v0_9.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    if not errors:
        PACKAGE.mkdir(parents=True, exist_ok=True)
        shutil.copy2(report_path, PACKAGE / report_path.name)
        archive = ROOT / "RFM_enclosure_v0_9_STL.zip"
        with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
            for path in sorted(PACKAGE.iterdir()):
                if path.is_file():
                    bundle.write(path, path.name)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if errors:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
