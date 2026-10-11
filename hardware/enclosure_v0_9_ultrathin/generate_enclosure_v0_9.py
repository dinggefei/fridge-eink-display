#!/usr/bin/env python3
"""Generate the independent V0.9 15.0 mm ultrathin enclosure prototype.

V0.7 is imported only as a geometry library.  All generated files stay below
``hardware/enclosure_v0_9_ultrathin`` so the confirmed V0.7 files are never
overwritten.

The V0.9 front face is 1.0 mm PLA with local tapered reinforcement around the
four M2 posts.  The USB-C opening keeps the confirmed V0.7 size of
11.5 x 7.5 mm, but its vertical position is recalculated from the lowered
Lipo Rider mount instead of copying the old coordinate blindly.  BOOT and
RESET use semi-enclosed, one-piece flexure buttons with internal plungers.
"""

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
PACKAGE = ROOT / "RFM_enclosure_v0_9_STL"
V07_FILE = ROOT.parent / "enclosure_v0_7" / "generate_enclosure_v0_7.py"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load module: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


v07 = load_module("rfm_enclosure_v07_geometry_for_v09", V07_FILE)


# Approved V0.9 envelope and material stack.
ASSEMBLED_THICKNESS = 15.0
FRONT_FACE_THICKNESS = 1.0
FRONT_FEATURE_DEPTH = 4.6
SCREEN_LOCATOR_DEPTH = 1.8
REAR_DEPTH = ASSEMBLED_THICKNESS - FRONT_FACE_THICKNESS
REAR_SKIN = 1.0
CARRIER_THICKNESS = 1.2
BATTERY_RECESS_DEPTH = 0.6

# The carrier rests immediately behind the screen locator.  This is the same
# relationship used by V0.7 (2.4 - 0.2 + 1.8 = 4.0 mm), recalculated for the
# 1.0 mm V0.9 face.
CARRIER_ASSEMBLED_Z = FRONT_FACE_THICKNESS - 0.2 + SCREEN_LOCATOR_DEPTH

# Low mounts keep the conductive ESP32 pins clear while recovering Z height.
ESP_UNDER_BOARD_CLEARANCE = 1.4
LIPO_UNDER_BOARD_CLEARANCE = 0.6
ESP_POST_TOP = CARRIER_THICKNESS + ESP_UNDER_BOARD_CLEARANCE
LIPO_POST_TOP = CARRIER_THICKNESS + LIPO_UNDER_BOARD_CLEARANCE

# BOOT/RESET stack, measured from the rear cover's normal inner face.  The
# Waveshare board uses a nominal 1.6 mm PCB and 2.0 mm-high PTS820 switches.
ESP_PCB_THICKNESS = 1.6
ESP_BUTTON_HEIGHT_ABOVE_PCB = 2.0
REAR_INNER_GLOBAL_Z = ASSEMBLED_THICKNESS - REAR_SKIN
ESP_BUTTON_TOP_GLOBAL_Z = (
    CARRIER_ASSEMBLED_Z
    + ESP_POST_TOP
    + ESP_PCB_THICKNESS
    + ESP_BUTTON_HEIGHT_ABOVE_PCB
)
BUTTON_UNPRESSED_GAP = REAR_INNER_GLOBAL_Z - ESP_BUTTON_TOP_GLOBAL_Z
BUTTON_PLUNGER_LENGTH = 4.5
BUTTON_RESTING_CLEARANCE = BUTTON_UNPRESSED_GAP - BUTTON_PLUNGER_LENGTH
BUTTON_PLUNGER_DIAMETER = 1.8
BUTTON_PLUNGER_TIP_CHAMFER = 0.2
BUTTON_PLUNGER_TIP_DIAMETER = (
    BUTTON_PLUNGER_DIAMETER - 2.0 * BUTTON_PLUNGER_TIP_CHAMFER
)
BUTTON_ARC_SLOT_WIDTH = 0.8
BUTTON_ARC_SLOT_INNER_RADIUS = 2.3
BUTTON_ARC_SLOT_OUTER_RADIUS = BUTTON_ARC_SLOT_INNER_RADIUS + BUTTON_ARC_SLOT_WIDTH
BUTTON_ARC_SLOT_START_DEG = 135.0
BUTTON_ARC_SLOT_SWEEP_DEG = 270.0
BUTTON_HINGE_START_DEG = 45.0
BUTTON_HINGE_SWEEP_DEG = 90.0
BUTTON_HINGE_THICKNESS = 0.4
# Stop before the tall assembled-right side wall while retaining both buttons.
BUTTON_COUPON_BOUNDS = (25.0, 55.5, 11.0, 24.5)

# Preserve the lower edge of the inherited 5.2 x 21.0 mm R1.0 opening and
# lower only its upper edge by 3.0 mm.  The straight section becomes 16 mm
# and the total rounded-rectangle height becomes 18 mm.
LIPO_OPENING_ORIGINAL_CENTER = tuple(float(v) for v in v07.LIPO_REGULAR_OPENING_MODEL)
LIPO_OPENING_ORIGINAL_HEIGHT = float(v07.P["lipo_regular_opening_height"])
LIPO_OPENING_UPPER_REDUCTION = 3.0
LIPO_OPENING_HEIGHT = LIPO_OPENING_ORIGINAL_HEIGHT - LIPO_OPENING_UPPER_REDUCTION
LIPO_OPENING_LOWER_Y = LIPO_OPENING_ORIGINAL_CENTER[1] - LIPO_OPENING_ORIGINAL_HEIGHT / 2.0
LIPO_OPENING_CENTER = (
    LIPO_OPENING_ORIGINAL_CENTER[0],
    LIPO_OPENING_LOWER_Y + LIPO_OPENING_HEIGHT / 2.0,
)

# Derive the new USB-C centre from the physically corrected V0.7 position.
# V0.7 assembly: carrier Z=4.0, Lipo board underside Z=4.0, and the corrected
# opening has global Z=19-7=12.  Therefore the receptacle centre is 4.0 mm
# above the board underside.  With the Lipo Rider lowered to 0.6 mm above the
# carrier, rear-model Z becomes 15-(2.6+1.8+4.0)=6.6 mm.
V07_CARRIER_ASSEMBLED_Z = 4.0
V07_LIPO_POST_TOP = float(v07.P["lipo_post_top"])
V07_USB_GLOBAL_Z = float(v07.P["assembled_thickness"] - v07.P["charge_cutout_center_z"])
USB_CENTRE_ABOVE_LIPO_BOARD = V07_USB_GLOBAL_Z - (
    V07_CARRIER_ASSEMBLED_Z + V07_LIPO_POST_TOP
)
USB_GLOBAL_Z = CARRIER_ASSEMBLED_Z + LIPO_POST_TOP + USB_CENTRE_ABOVE_LIPO_BOARD
USB_MODEL_Z = ASSEMBLED_THICKNESS - USB_GLOBAL_Z


P = dict(v07.P)
P.update(
    {
        "assembled_thickness": ASSEMBLED_THICKNESS,
        "front_face_thickness": FRONT_FACE_THICKNESS,
        "front_feature_depth": FRONT_FEATURE_DEPTH,
        "screen_locator_depth": SCREEN_LOCATOR_DEPTH,
        "rear_depth": REAR_DEPTH,
        "rear_skin": REAR_SKIN,
        "rear_left_restored_band_thickness": 1.2,
        "magnet_bar_outer_skin": 0.6,
        "carrier_thickness": CARRIER_THICKNESS,
        "battery_thickness": 8.0,
        "battery_recess_depth": BATTERY_RECESS_DEPTH,
        "battery_underlay_max": 0.2,
        "esp_post_top": ESP_POST_TOP,
        "lipo_post_top": LIPO_POST_TOP,
        "case_fastener_length": 12.0,
        "case_fastener_counterbore_depth": 1.6,
        # Size remains exactly the same as the confirmed V0.7 opening.
        "charge_cutout_width": 11.5,
        "charge_cutout_height": 7.5,
        "charge_cutout_center_x": float(v07.LIPO_USB_C_FACE[0]),
        "charge_cutout_center_y": 91.0,
        "charge_cutout_center_z": USB_MODEL_Z,
        "charge_cutout_vertical_drop": float(v07.P["charge_cutout_center_z"] - USB_MODEL_Z),
        "lipo_regular_opening_height": LIPO_OPENING_HEIGHT,
    }
)

# V0.7 helpers read both module dictionaries, so keep them synchronized only
# in this imported process.  No V0.7 source or output file is written.
v07.P = P
v07.v06.P = P


def build_front_bezel_v0_9():
    """Build the 1.0 mm face and add local post-root reinforcement."""
    front = v07.build_front_bezel()

    # A tapered R4.0 -> R2.6 collar transfers screw load into the thin face.
    gusset_z0 = FRONT_FACE_THICKNESS - 0.2
    gusset_height = 0.8
    gussets = [
        v07.conical_frustum(
            4.0,
            P["case_fastener_post_diameter"] / 2.0,
            gusset_height,
            x,
            y,
            gusset_z0,
            sections=72,
        )
        for x, y in v07.CASE_FASTENERS
    ]
    front = v07.union([front, *gussets])

    # The inherited V0.7 function drills a fixed-Z pilot.  Re-drill from the
    # V0.9 post top so the full 3.3 mm pilot depth remains available.
    pilot_depth = 3.3
    pilots = [
        v07.cylinder(
            P["case_fastener_pilot"] / 2.0,
            pilot_depth + 0.1,
            (x, y, FRONT_FEATURE_DEPTH - pilot_depth / 2.0 + 0.05),
            sections=48,
        )
        for x, y in v07.CASE_FASTENERS
    ]
    return v07.difference(front, pilots)


def annular_sector_prism(
    inner_radius: float,
    outer_radius: float,
    start_degrees: float,
    sweep_degrees: float,
    height: float,
    z0: float,
    center_x: float,
    center_y: float,
    sections: int,
) -> trimesh.Trimesh:
    """Create a watertight annular-sector cutter without optional CAD modules."""
    vertices = []
    for index in range(sections + 1):
        angle = math.radians(start_degrees + sweep_degrees * index / sections)
        cosine = math.cos(angle)
        sine = math.sin(angle)
        for z, radius in (
            (z0, inner_radius),
            (z0, outer_radius),
            (z0 + height, inner_radius),
            (z0 + height, outer_radius),
        ):
            vertices.append(
                [center_x + radius * cosine, center_y + radius * sine, z]
            )

    faces = []
    for index in range(sections):
        current = 4 * index
        following = current + 4
        bottom_inner, bottom_outer, top_inner, top_outer = range(current, current + 4)
        next_bottom_inner, next_bottom_outer, next_top_inner, next_top_outer = range(
            following, following + 4
        )
        faces.extend(
            [
                [top_inner, top_outer, next_top_outer],
                [top_inner, next_top_outer, next_top_inner],
                [bottom_inner, next_bottom_outer, bottom_outer],
                [bottom_inner, next_bottom_inner, next_bottom_outer],
                [bottom_inner, top_inner, next_top_inner],
                [bottom_inner, next_top_inner, next_bottom_inner],
                [bottom_outer, next_bottom_outer, next_top_outer],
                [bottom_outer, next_top_outer, top_outer],
            ]
        )

    start = 0
    end = 4 * sections
    faces.extend(
        [
            [start, start + 1, start + 3],
            [start, start + 3, start + 2],
            [end, end + 3, end + 1],
            [end, end + 2, end + 3],
        ]
    )
    return trimesh.Trimesh(vertices=vertices, faces=faces, process=True)


def build_rear_cover_v0_9():
    """Build the rear cover with 3/4-slot flexure buttons and shorter LED window."""
    inherited_label_cutters = v07.rear_label_cutters
    inherited_lipo_opening_center = v07.LIPO_REGULAR_OPENING_MODEL
    try:
        v07.rear_label_cutters = lambda *_args, **_kwargs: []
        v07.LIPO_REGULAR_OPENING_MODEL = LIPO_OPENING_CENTER
        rear = v07.build_rear_cover()
    finally:
        v07.rear_label_cutters = inherited_label_cutters
        v07.LIPO_REGULAR_OPENING_MODEL = inherited_lipo_opening_center

    # Refill each inherited access opening with a flush full-skin button disk,
    # then cut a 270-degree annular slot.  The uncut upper 90-degree sector is
    # relieved from the inside to leave a 0.4 mm elastic bridge.  A 1.8 mm rod
    # projects 4.5 mm inward and ends in a 0.2 mm chamfer.
    button_disk_diameter = float(P["button_counterbore_diameter"]) + 0.2
    button_solids = []
    button_cutters = []
    for x, y in (v07.REAR_BOOT, v07.REAR_RESET):
        button_solids.extend(
            [
                v07.cylinder(
                    button_disk_diameter / 2.0,
                    REAR_SKIN,
                    (x, y, REAR_SKIN / 2.0),
                    sections=72,
                ),
                v07.cylinder(
                    BUTTON_PLUNGER_DIAMETER / 2.0,
                    BUTTON_PLUNGER_LENGTH - BUTTON_PLUNGER_TIP_CHAMFER + 0.02,
                    (
                        x,
                        y,
                        REAR_SKIN
                        + (BUTTON_PLUNGER_LENGTH - BUTTON_PLUNGER_TIP_CHAMFER + 0.02)
                        / 2.0,
                    ),
                    sections=48,
                ),
                v07.conical_frustum(
                    BUTTON_PLUNGER_DIAMETER / 2.0,
                    BUTTON_PLUNGER_TIP_DIAMETER / 2.0,
                    BUTTON_PLUNGER_TIP_CHAMFER,
                    x,
                    y,
                    REAR_SKIN + BUTTON_PLUNGER_LENGTH - BUTTON_PLUNGER_TIP_CHAMFER,
                    sections=48,
                ),
            ]
        )
        button_cutters.extend(
            [
                annular_sector_prism(
                    BUTTON_ARC_SLOT_INNER_RADIUS,
                    BUTTON_ARC_SLOT_OUTER_RADIUS,
                    BUTTON_ARC_SLOT_START_DEG,
                    BUTTON_ARC_SLOT_SWEEP_DEG,
                    REAR_SKIN + 0.4,
                    -0.2,
                    x,
                    y,
                    sections=54,
                ),
                annular_sector_prism(
                    BUTTON_ARC_SLOT_INNER_RADIUS,
                    BUTTON_ARC_SLOT_OUTER_RADIUS,
                    BUTTON_HINGE_START_DEG,
                    BUTTON_HINGE_SWEEP_DEG,
                    REAR_SKIN - BUTTON_HINGE_THICKNESS + 0.2,
                    BUTTON_HINGE_THICKNESS,
                    x,
                    y,
                    sections=18,
                ),
            ]
        )
    return v07.difference(v07.union([rear, *button_solids]), button_cutters)


def former_button_label_regions() -> dict[str, list[float]]:
    """Return XY bounds used to verify the old engraving is absent."""
    regions = {}
    for text, centre in (
        ("BOOT", v07.REAR_BOOT_LABEL),
        ("RESET", v07.REAR_RESET_LABEL),
    ):
        cutters = v07.rear_label_cutters(text, *centre)
        lower = [min(float(mesh.bounds[0][axis]) for mesh in cutters) for axis in (0, 1)]
        upper = [max(float(mesh.bounds[1][axis]) for mesh in cutters) for axis in (0, 1)]
        regions[text] = [
            round(lower[0], 3),
            round(lower[1], 3),
            round(upper[0], 3),
            round(upper[1], 3),
        ]
    return regions


def cleaned(name: str, mesh: trimesh.Trimesh) -> trimesh.Trimesh:
    if isinstance(mesh, trimesh.Scene):
        mesh = mesh.dump(concatenate=True)
    mesh.remove_unreferenced_vertices()
    if not mesh.is_watertight:
        raise RuntimeError(f"{name} is not watertight")
    if mesh.volume <= 0:
        raise RuntimeError(f"{name} has non-positive volume")
    return mesh


def export(name: str, mesh: trimesh.Trimesh) -> Path:
    path = OUTPUT / f"{name}.stl"
    path.write_bytes(trimesh.exchange.stl.export_stl(mesh))
    return path


def mesh_record(path: Path) -> dict:
    # STL duplicates triangle vertices by definition; process=True welds the
    # coincident vertices before topology checks.
    mesh = trimesh.load_mesh(path, process=True)
    return {
        "file": path.name,
        "watertight": bool(mesh.is_watertight),
        "bounds_mm": [[round(float(v), 3) for v in row] for row in mesh.bounds],
        "extents_mm": [round(float(v), 3) for v in mesh.extents],
        "volume_mm3": round(float(abs(mesh.volume)), 3),
        "triangles": int(len(mesh.faces)),
    }


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    PACKAGE.mkdir(parents=True, exist_ok=True)
    # Remove superseded generated artifacts so the output folder cannot mix
    # earlier carrier or button revisions with the current package.
    for stale in (
        OUTPUT / "electronics_carrier_v0_9_0p8mm.stl",
        OUTPUT / "fit_test_boot_reset_buttons_3p5mm_v0_9.stl",
        OUTPUT / "fit_test_boot_reset_buttons_5p0mm_v0_9.stl",
        OUTPUT / "fit_test_boot_reset_buttons_5p5mm_v0_9.stl",
        OUTPUT / "validation_report_v0_9.json",
    ):
        stale.unlink(missing_ok=True)

    front = cleaned("front_bezel_v0_9", build_front_bezel_v0_9())
    carrier = cleaned("electronics_carrier_v0_9", v07.build_carrier())
    rear = cleaned("rear_cover_v0_9", build_rear_cover_v0_9())
    front_coupon = cleaned(
        "fit_test_front_corner_v0_9",
        v07.corner_coupon(front),
    )
    usb_coupon = cleaned(
        "fit_test_usb_c_opening_v0_9",
        v07.rear_usb_c_opening_coupon(rear),
    )
    button_coupon = cleaned(
        "fit_test_boot_reset_buttons_v0_9",
        v07.cropped_coupon(rear, BUTTON_COUPON_BOUNDS),
    )
    lipo_opening_coupon = cleaned(
        "fit_test_lipo_indicator_opening_v0_9",
        v07.rear_openings_coupon(rear),
    )

    meshes = {
        "front_bezel_v0_9_1p0mm": front,
        "electronics_carrier_v0_9_1p2mm": carrier,
        "rear_cover_v0_9_15p0mm": rear,
        "fit_test_front_corner_v0_9_1p0mm": front_coupon,
        "fit_test_usb_c_opening_11p5x7p5_v0_9": usb_coupon,
        "fit_test_boot_reset_buttons_4p5mm_v0_9": button_coupon,
        "fit_test_lipo_indicator_opening_5p2x18_v0_9": lipo_opening_coupon,
    }
    paths = {name: export(name, mesh) for name, mesh in meshes.items()}

    screw_engagement = P["case_fastener_length"] - (
        ASSEMBLED_THICKNESS
        - P["case_fastener_counterbore_depth"]
        - FRONT_FEATURE_DEPTH
    )
    battery_top_global = (
        CARRIER_ASSEMBLED_Z
        + (CARRIER_THICKNESS - BATTERY_RECESS_DEPTH)
        + P["battery_underlay_max"]
        + P["battery_thickness"]
    )
    magnet_inner_global = ASSEMBLED_THICKNESS - (
        P["magnet_bar_outer_skin"] + P["magnet_bar_pocket_depth"]
    )

    manifest = {
        "design": "RefrigeratorFoodManagement V0.9 ultrathin enclosure prototype",
        "units": "mm",
        "status": "engineering prototype; print all required coupons before full shell",
        "preserves": [
            "V0.7 source and generated files remain unchanged",
            "120 x 184 mm outer footprint",
            "V0.7 front opening and XY component layout",
            "two 90 x 50 x 2 mm plus one 50 x 20 x 2 mm flexible magnets",
            "0.6 mm PLA skin outside the magnets",
            "V0.7 USB-C opening size 11.5 x 7.5 mm",
        ],
        "target_outer_size": [120.0, 184.0, ASSEMBLED_THICKNESS],
        "front": {
            "face_thickness": FRONT_FACE_THICKNESS,
            "local_post_root_reinforcement": "tapered R4.0 to R2.6, 0.8 mm high",
            "feature_depth": FRONT_FEATURE_DEPTH,
            "screen_locator_depth": SCREEN_LOCATOR_DEPTH,
        },
        "carrier": {
            "thickness": CARRIER_THICKNESS,
            "battery_local_floor": CARRIER_THICKNESS - BATTERY_RECESS_DEPTH,
            "assembled_z_from_front_outer_face": CARRIER_ASSEMBLED_Z,
            "esp_post_top": round(ESP_POST_TOP, 3),
            "lipo_post_top": round(LIPO_POST_TOP, 3),
            "lipo_under_board_clearance": LIPO_UNDER_BOARD_CLEARANCE,
            "lipo_post_diameter": P["lipo_post_diameter"],
            "lipo_post_centers_xy": [
                [round(float(x), 3), round(float(y), 3)] for x, y in v07.LIPO_HOLES
            ],
        },
        "rear": {
            "depth": REAR_DEPTH,
            "normal_skin": REAR_SKIN,
            "magnet_outer_skin": P["magnet_bar_outer_skin"],
            "left_restored_band_thickness": P["rear_left_restored_band_thickness"],
            "button_access_holes": [],
            "integrated_buttons": ["BOOT", "RESET"],
            "button_centers_xy": {
                "BOOT": [round(float(value), 3) for value in v07.REAR_BOOT],
                "RESET": [round(float(value), 3) for value in v07.REAR_RESET],
            },
            "button_type": "semi-enclosed 270-degree arc slot with 90-degree upper hinge",
            "button_union_overlap_diameter": round(
                float(P["button_counterbore_diameter"]) + 0.2, 3
            ),
            "button_center_island_diameter": 2.0 * BUTTON_ARC_SLOT_INNER_RADIUS,
            "button_arc_slot": {
                "width": BUTTON_ARC_SLOT_WIDTH,
                "inner_diameter": 2.0 * BUTTON_ARC_SLOT_INNER_RADIUS,
                "outer_diameter": 2.0 * BUTTON_ARC_SLOT_OUTER_RADIUS,
                "open_arc_degrees": BUTTON_ARC_SLOT_SWEEP_DEG,
            },
            "button_hinge": {
                "connected_arc_degrees": BUTTON_HINGE_SWEEP_DEG,
                "direction": "positive model Y / upper side",
                "thickness": BUTTON_HINGE_THICKNESS,
            },
            "button_plunger_diameter": BUTTON_PLUNGER_DIAMETER,
            "button_plunger_projection_from_inner_face": round(BUTTON_PLUNGER_LENGTH, 3),
            "button_plunger_tip_chamfer": BUTTON_PLUNGER_TIP_CHAMFER,
            "button_plunger_tip_diameter": BUTTON_PLUNGER_TIP_DIAMETER,
            "button_plunger_tip_model_z": round(REAR_SKIN + BUTTON_PLUNGER_LENGTH, 3),
            "button_resting_clearance": round(BUTTON_RESTING_CLEARANCE, 3),
            "button_stack_calculation": {
                "rear_inner_global_z": REAR_INNER_GLOBAL_Z,
                "esp_board_underside_global_z": CARRIER_ASSEMBLED_Z + ESP_POST_TOP,
                "esp_pcb_thickness": ESP_PCB_THICKNESS,
                "switch_height_above_pcb": ESP_BUTTON_HEIGHT_ABOVE_PCB,
                "switch_top_global_z": ESP_BUTTON_TOP_GLOBAL_Z,
                "unpressed_gap": BUTTON_UNPRESSED_GAP,
            },
            "engraved_button_labels": [],
            "removed_engraved_button_labels": ["BOOT", "RESET"],
            "former_button_label_regions_xy": former_button_label_regions(),
        },
        "lipo_indicator_opening": {
            "width": P["lipo_regular_opening_width"],
            "total_height": LIPO_OPENING_HEIGHT,
            "straight_length": LIPO_OPENING_HEIGHT
            - 2.0 * float(P["lipo_regular_opening_corner_radius"]),
            "corner_radius": P["lipo_regular_opening_corner_radius"],
            "model_center": [round(float(v), 3) for v in LIPO_OPENING_CENTER],
            "lower_edge_y": round(LIPO_OPENING_LOWER_Y, 3),
            "upper_edge_y": round(LIPO_OPENING_LOWER_Y + LIPO_OPENING_HEIGHT, 3),
            "lower_edge_preserved": True,
            "upper_edge_reduction": LIPO_OPENING_UPPER_REDUCTION,
        },
        "usb_c_opening": {
            "size": [P["charge_cutout_width"], P["charge_cutout_height"]],
            "model_center": [
                round(float(P["charge_cutout_center_x"]), 3),
                round(float(P["charge_cutout_center_y"]), 3),
                round(float(P["charge_cutout_center_z"]), 3),
            ],
            "lipo_usb_face_xy": [round(float(v), 3) for v in v07.LIPO_USB_C_FACE],
            "calculation": {
                "carrier_assembled_z": CARRIER_ASSEMBLED_Z,
                "lipo_board_mount_z": LIPO_POST_TOP,
                "connector_center_above_board": USB_CENTRE_ABOVE_LIPO_BOARD,
                "connector_global_z": USB_GLOBAL_Z,
                "rear_model_z": USB_MODEL_Z,
            },
        },
        "clearances": {
            "battery_to_magnet_pocket": round(magnet_inner_global - battery_top_global, 3),
            "m2x12_estimated_engagement": round(float(screw_engagement), 3),
        },
        "print_material": "PLA, 0.4 mm nozzle",
        "required_coupons": [
            paths["fit_test_front_corner_v0_9_1p0mm"].name,
            paths["fit_test_usb_c_opening_11p5x7p5_v0_9"].name,
            paths["fit_test_boot_reset_buttons_4p5mm_v0_9"].name,
            paths["fit_test_lipo_indicator_opening_5p2x18_v0_9"].name,
        ],
        "parts": [mesh_record(path) for path in paths.values()],
    }
    manifest_path = OUTPUT / "manifest_v0_9.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    readme = "# V0.9 STL 打印包\n\n"
    readme += "本包是独立 V0.9 工程样机，不会覆盖 V0.7。正式外壳目标尺寸为 120 × 184 × 15.0 mm。\n\n"
    readme += "中托普通区厚 1.2 mm，电池下方底板厚 0.6 mm；后盖普通面厚 1.0 mm，磁片外侧厚 0.6 mm，左侧补强带厚 1.2 mm。\n\n"
    readme += "ESP32 螺丝柱高出中托表面 1.4 mm（柱顶模型 Z=2.6 mm），Lipo Rider 螺丝柱高出中托表面 0.6 mm（柱顶模型 Z=1.8 mm）；Lipo Rider 对应的 Type-C 开口中心为后盖模型 Z=6.6 mm。\n\n"
    readme += "电池与磁片槽之间的名义余量为 0.8 mm；电池连同转移胶实测总厚度不得超过 8.2 mm。\n\n"
    readme += "后盖的 BOOT、RESET 已改为半封闭悬臂按键：周围开 270°、宽 0.8 mm 的圆弧贯穿槽，上方保留 90°、厚 0.4 mm 的连接桥；内侧 Ø1.8 mm 按压杆从后盖内表面伸出 4.5 mm，杆端带 0.2 mm 倒角，名义静止间隙为 0.7 mm，不再凹刻文字。\n\n"
    readme += "Lipo Rider 指示灯开孔保持下边缘不动，上边缘下移 3 mm；R1 圆角之间的直边由 19 mm 改为 16 mm，总开孔为 5.2 × 18 mm、R1 mm。\n\n"
    readme += "## 首先打印\n\n"
    readme += "1. `fit_test_front_corner_v0_9_1p0mm.stl`：验证 1.0 mm 前框、加强区和 M2×12 螺丝。\n"
    readme += "2. `fit_test_usb_c_opening_11p5x7p5_v0_9.stl`：验证低位 Lipo Rider 对准 Type-C 公头。\n\n"
    readme += "3. `fit_test_boot_reset_buttons_4p5mm_v0_9.stl`：装上 ESP32 后确认两根按压杆是否能分别触发 BOOT、RESET，且合盖后没有持续压住开关。\n"
    readme += "4. `fit_test_lipo_indicator_opening_5p2x18_v0_9.stl`：确认缩短后的窗口满足实际指示灯观察范围。\n\n"
    readme += "四个检具均通过后，再打印前三个正式零件。Type-C 净开口保持 V0.7 的 11.5 × 7.5 mm。\n"
    (OUTPUT / "README.md").write_text(readme, encoding="utf-8")

    for old in PACKAGE.iterdir():
        if old.is_file():
            old.unlink()
    for path in [*paths.values(), manifest_path, OUTPUT / "README.md"]:
        shutil.copy2(path, PACKAGE / path.name)

    archive = ROOT / "RFM_enclosure_v0_9_STL.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        for path in sorted(PACKAGE.iterdir()):
            bundle.write(path, path.name)

    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    print(f"Generated: {archive}")


if __name__ == "__main__":
    main()
