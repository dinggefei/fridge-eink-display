#!/usr/bin/env python3
"""Independent numerical checks for the V0.6 enclosure before coupon printing."""

from __future__ import annotations

import importlib.util
import json
import math
from pathlib import Path
import shutil
import zipfile

import trimesh


ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "output"
GENERATOR = ROOT / "generate_enclosure_v0_6.py"


def load_generator():
    spec = importlib.util.spec_from_file_location("rfm_enclosure_v06_validate", GENERATOR)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load generator: {GENERATOR}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


gen = load_generator()
P = gen.P


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def rectangle_margin(cx, cy, width, height):
    return min(
        P["carrier_width"] / 2.0 - abs(cx) - width / 2.0,
        P["carrier_height"] / 2.0 - abs(cy) - height / 2.0,
    )


def point_to_rectangle(point, cx, cy, width, height):
    x, y = point
    dx = max(abs(x - cx) - width / 2.0, 0.0)
    dy = max(abs(y - cy) - height / 2.0, 0.0)
    return math.hypot(dx, dy)


def main():
    expected = {
        "front_bezel_v0_6.stl": (120.0, 184.0, 6.0),
        "electronics_carrier_v0_6.stl": (115.4, 179.4, 4.2),
        "rear_cover_v0_6.stl": (120.0, 184.0, 19.0),
    }
    checks = {}
    for filename, extents in expected.items():
        mesh = trimesh.load(OUTPUT / filename, force="mesh")
        require(mesh.is_watertight, f"{filename}: not watertight")
        require(mesh.is_volume, f"{filename}: not a positive volume")
        require(len(mesh.split(only_watertight=False)) == 1, f"{filename}: disconnected bodies")
        require(all(abs(float(a) - b) <= 0.03 for a, b in zip(mesh.extents, extents)),
                f"{filename}: unexpected extents {mesh.extents}")
        checks[filename] = "PASS"

    require(abs((P["rear_inner_width"] - P["carrier_width"]) / 2.0 - 0.5) < 1e-6,
            "carrier X fit is not 0.5 mm per side")
    require(abs((P["rear_inner_height"] - P["carrier_height"]) / 2.0 - 0.5) < 1e-6,
            "carrier Y fit is not 0.5 mm per side")
    require(P["screen_pocket_width"] - P["screen_body_width"] >= 0.799,
            "screen X clearance below 0.4 mm per side")
    require(P["screen_pocket_height"] - P["screen_body_height"] >= 0.799,
            "screen Y clearance below 0.4 mm per side")

    component_margins = {
        "battery": rectangle_margin(P["battery_center_x"], P["battery_center_y"], P["battery_width"], P["battery_height"]),
        "esp32": rectangle_margin(P["esp_center_x"], P["esp_center_y"], P["esp_width"], P["esp_height"]),
        "despi": rectangle_margin(P["despi_center_x"], P["despi_center_y"], P["despi_width"], P["despi_height"]),
        "lipo": rectangle_margin(P["lipo_center_x"], P["lipo_center_y"], P["lipo_width"], P["lipo_height"]),
    }
    require(min(component_margins.values()) >= 1.0, f"component edge margin too small: {component_margins}")

    tube_r = P["case_fastener_tube_diameter"] / 2.0
    battery_to_tube = min(
        point_to_rectangle(point, P["battery_center_x"], P["battery_center_y"], P["battery_width"], P["battery_height"]) - tube_r
        for point in gen.CASE_FASTENERS
    )
    require(battery_to_tube >= 3.0, f"battery-to-fastener hard clearance below 3 mm: {battery_to_tube}")

    magnet_clearances = gen.clearance_report()
    require(min(magnet_clearances.values()) >= 2.0, f"magnet clearance below 2 mm: {magnet_clearances}")
    require(abs(gen.LIPO_USB_C_FACE[0] - P["charge_cutout_center_x"]) <= 0.25,
            "Lipo USB-C and top opening are not centred")

    available_above_carrier = gen.available_height_above_carrier()
    component_stack_heights = {
        "battery": P["battery_thickness"],
        "esp32": P["esp_post_top"] - P["carrier_thickness"] + P["esp_body_envelope"],
        "despi": P["despi_body_envelope"],
        "lipo": P["lipo_post_top"] - P["carrier_thickness"] + P["lipo_body_envelope"],
    }
    component_height_clearance = {
        key: available_above_carrier - value for key, value in component_stack_heights.items()
    }
    require(min(component_height_clearance.values()) >= 1.0,
            f"vertical component clearance below 1 mm: {component_height_clearance}")

    screw_engagement = (
        P["case_fastener_length"]
        - (P["assembled_thickness"] - P["case_fastener_counterbore_depth"] - P["front_feature_depth"])
    )
    require(2.8 <= screw_engagement <= 3.5, f"M2x16 engagement out of range: {screw_engagement}")

    report = {
        "result": "PASS",
        "stl_checks": checks,
        "outer_size_mm": [P["case_width"], P["case_height"], P["assembled_thickness"]],
        "carrier_fit_per_side_mm": P["carrier_fit_per_side"],
        "screen_clearance_per_side_mm": [
            (P["screen_pocket_width"] - P["screen_body_width"]) / 2.0,
            (P["screen_pocket_height"] - P["screen_body_height"]) / 2.0,
        ],
        "component_edge_margins_mm": {key: round(value, 3) for key, value in component_margins.items()},
        "available_height_above_carrier_mm": round(available_above_carrier, 3),
        "component_height_clearance_mm": {
            key: round(value, 3) for key, value in component_height_clearance.items()
        },
        "battery_to_fastener_tube_mm": round(battery_to_tube, 3),
        "magnet_clearances_mm": magnet_clearances,
        "m2x16_engagement_mm": round(screw_engagement, 3),
        "physical_validation": "PENDING: print and test four coupons before full parts",
    }
    report_path = OUTPUT / "validation_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    # Rebuild the delivery bundle after validation so it contains the report
    # and the actual-STL assembly rendering as well as all printable parts.
    package = ROOT / "RFM_enclosure_v0_6_STL.zip"
    package_dir = ROOT / "RFM_enclosure_v0_6_STL"
    bundle = [
        *sorted(OUTPUT.glob("*.stl")),
        OUTPUT / "manifest.json",
        OUTPUT / "placement_template_v0_6_1to1.svg",
        report_path,
        ROOT / "previews" / "compact_enclosure_overview_v0_6.png",
        ROOT / "previews" / "electronics_layout_v0_6.png",
        ROOT / "previews" / "assembly_effect_v0_6.png",
        ROOT / "previews" / "installed_effect_v0_6.png",
        ROOT / "previews" / "exploded_view_v0_6.png",
        ROOT / "README.md",
    ]
    require(all(path.exists() for path in bundle), "delivery bundle contains a missing file")
    with zipfile.ZipFile(package, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in bundle:
            archive.write(path, path.name)
    package_dir.mkdir(parents=True, exist_ok=True)
    for path in bundle:
        shutil.copy2(path, package_dir / path.name)

    with zipfile.ZipFile(package) as archive:
        require(archive.testzip() is None, "ZIP CRC failure")
        names = set(archive.namelist())
        for filename in expected:
            require(filename in names, f"ZIP missing {filename}")
    report["zip_crc"] = "PASS"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    shutil.copy2(report_path, package_dir / report_path.name)
    with zipfile.ZipFile(package, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in bundle:
            archive.write(path, path.name)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
