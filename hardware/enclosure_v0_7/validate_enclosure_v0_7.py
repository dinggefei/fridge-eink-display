#!/usr/bin/env python3
"""Independent numerical and STL checks for the V0.7 enclosure."""

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
GENERATOR = ROOT / "generate_enclosure_v0_7.py"


def load_generator():
    spec = importlib.util.spec_from_file_location("rfm_enclosure_v07_validate", GENERATOR)
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
        "front_bezel_v0_7.stl": (120.0, 184.0, 6.0),
        "electronics_carrier_v0_7.stl": (115.4, 179.4, 4.2),
        "rear_cover_v0_7.stl": (120.0, 184.0, 16.6),
        "rear_cover_v0_7_soft_magnets_2x90x50_1x50x20.stl": (120.0, 184.0, 16.6),
        "rear_cover_v0_7_rev_e_dfm_clearance.stl": (120.0, 184.0, 16.6),
        "rear_cover_v0_7_rev_f_flat_left_wall_0p8mm.stl": (120.0, 184.0, 16.6),
        "rear_cover_v0_7_rev_g_lipo_switch_access.stl": (120.0, 184.0, 16.6),
        "rear_cover_v0_7_rev_h_combined_lipo_led_switch_opening.stl": (120.0, 184.0, 16.6),
        "rear_cover_v0_7_rev_i_regular_lipo_led_switch_opening.stl": (120.0, 184.0, 16.6),
        "fit_test_soft_magnet_2mm_skin_0p4_v0_7.stl": (26.6, 56.6, 2.6),
        "fit_test_lipo_usb_led_openings_v0_7.stl": (39.0, 37.0, 16.6),
        "fit_test_lipo_usb_led_switch_openings_v0_7_rev_g.stl": (39.0, 37.0, 16.6),
        "fit_test_lipo_combined_led_switch_opening_v0_7_rev_h.stl": (39.0, 37.0, 16.6),
        "fit_test_lipo_regular_led_switch_opening_v0_7_rev_i.stl": (39.0, 37.0, 16.6),
        "fit_test_usb_c_opening_11p5x7p5_v0_7.stl": (20.0, 8.0, 16.6),
        "fit_test_rear_left_flat_wall_0p8mm_v0_7_rev_f.stl": (8.0, 14.0, 16.6),
        "fit_test_boot_reset_labels_v0_7.stl": (33.0, 13.5, 1.4),
        "fit_test_front_corner_v0_7_rev_b_uniform_3_6mm.stl": (35.0, 37.0, 6.0),
        "fit_test_front_left_retainer_v0_7_rev_e_square_inner.stl": (35.0, 37.0, 6.0),
        "fit_test_front_right_open_v0_7_rev_f_continuous_edge.stl": (35.0, 37.0, 6.0),
        "fit_test_carrier_corner_v0_7_rev_b_boss_relief_r2_9.stl": (32.7, 34.7, 1.4),
        "fit_test_rear_corner_v0_7_rev_b_opposite_side.stl": (35.0, 37.0, 16.6),
        "fit_test_rear_corner_v0_7_rev_c_boss_relief_r2_9.stl": (35.0, 37.0, 16.6),
        "fit_test_rear_corner_clearance_v0_7_rev_e.stl": (35.0, 37.0, 16.6),
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

    require(P["assembled_thickness"] == 19.0, "assembled thickness is not 19 mm")
    require(abs((P["rear_inner_width"] - P["carrier_width"]) / 2.0 - 0.5) < 1e-6,
            "carrier X fit is not 0.5 mm per side")
    require(abs((P["rear_inner_height"] - P["carrier_height"]) / 2.0 - 0.5) < 1e-6,
            "carrier Y fit is not 0.5 mm per side")
    require(P["carrier_thickness"] - P["battery_recess_depth"] >= 0.899,
            "battery recess leaves less than 0.9 mm carrier floor")
    require(P["screen_pocket_width"] - P["screen_body_width"] >= 0.799,
            "screen X clearance below 0.4 mm per side")
    require(P["screen_pocket_height"] - P["screen_body_height"] >= 0.799,
            "screen Y clearance below 0.4 mm per side")
    require(abs(P["front_retainer_width"] - 2.9) <= 0.001,
            f"Rev F front retainer width is not 2.9 mm: {P['front_retainer_width']}")
    require(abs(P["front_retainer_edge_inset"] - 3.6) <= 0.001,
            f"Rev F left/right retainer edge inset is not 3.6 mm: {P['front_retainer_edge_inset']}")
    require(abs(P["front_retainer_top_bottom_edge_inset"] - 3.6) <= 0.001,
            "Rev F top/bottom edge inset is not 3.6 mm")
    require("front_retainer_right_clear_span" not in P,
            "obsolete independent 170 mm right-clear-span constraint still exists")
    require(P["front_retainer_right_end_style"] == "continuous_inner_edges_to_outer_arcs_no_step",
            "right retainer end style is not the Rev F continuous horizontal edge")
    require(abs(P["front_retainer_outer_radius"] - 4.4) <= 0.001,
            f"Rev F retainer outer corner is not R4.4: {P['front_retainer_outer_radius']}")
    require(abs(P["front_retainer_inner_radius"] - 1.5) <= 0.001,
            f"Rev F transition radius is not R1.5: {P['front_retainer_inner_radius']}")
    require(P["front_retainer_left_inner_corner_radius"] == 0.0,
            "Rev F left inner corner radius is not zero")
    require(P["front_retainer_left_inner_corner_style"] == "square_90_degree",
            "Rev F left inner corners are not marked as square")
    require(abs(P["front_retainer_outer_radius"] - P["front_retainer_inner_radius"]
                - P["front_retainer_width"]) <= 0.001,
            "front retainer corner radii do not form a constant-width 2.9 mm arc")
    require(abs(P["rear_inner_corner_radius"] - P["front_retainer_outer_radius"]
                - P["front_retainer_to_rear_radial_clearance"]) <= 0.001,
            "front retainer outer arc does not match the rear inner arc clearance")
    require(P["front_right_retainer_removed"] is True,
            "Rev F right front retainer is not marked as removed")
    left_retainer_overlap = (
        P["screen_body_width"] / 2.0
        - (P["case_width"] / 2.0 - P["front_retainer_edge_inset"] - P["front_retainer_width"])
    )
    require(2.0 <= left_retainer_overlap <= 2.2,
            f"left retainer overlap on the physical panel is unexpected: {left_retainer_overlap}")
    measured_left_inactive_border_remaining = 9.0 - left_retainer_overlap
    require(measured_left_inactive_border_remaining >= 6.8,
            "left retainer encroaches too far into the measured 9 mm inactive border")

    component_margins = {
        "battery": rectangle_margin(P["battery_center_x"], P["battery_center_y"], P["battery_width"], P["battery_height"]),
        "esp32": rectangle_margin(P["esp_center_x"], P["esp_center_y"], P["esp_width"], P["esp_height"]),
        "despi": rectangle_margin(P["despi_center_x"], P["despi_center_y"], P["despi_width"], P["despi_height"]),
        "lipo": rectangle_margin(P["lipo_center_x"], P["lipo_center_y"], P["lipo_width"], P["lipo_height"]),
    }
    require(min(component_margins.values()) >= 1.0, f"component edge margin too small: {component_margins}")

    tube_radius = P["case_fastener_tube_diameter"] / 2.0
    battery_to_tube = min(
        point_to_rectangle(point, P["battery_center_x"], P["battery_center_y"], P["battery_width"], P["battery_height"]) - tube_radius
        for point in gen.CASE_FASTENERS
    )
    require(battery_to_tube >= 3.0, f"battery-to-fastener hard clearance below 3 mm: {battery_to_tube}")

    magnet_clearances = gen.magnet_clearance_report()
    require(magnet_clearances["boss_to_esp32_antenna"] >= 30.0,
            f"magnet boss to ESP32 antenna clearance below 30 mm: {magnet_clearances}")
    require(magnet_clearances["boss_to_esp32_board"] >= 2.5,
            f"magnet boss to ESP32 board clearance below 2.5 mm: {magnet_clearances}")
    require(magnet_clearances["boss_to_despi_c02"] == 0.0,
            f"paired lower pocket no longer passes under the DESPI footprint: {magnet_clearances}")
    require(magnet_clearances["boss_to_lipo_rider"] >= 15.0,
            f"magnet boss to Lipo Rider clearance below 15 mm: {magnet_clearances}")
    require(magnet_clearances["boss_to_fastener_tube"] >= 2.0,
            f"magnet boss to fastener clearance below 2 mm: {magnet_clearances}")
    require(magnet_clearances["boss_to_button_counterbore"] >= 1.4,
            f"magnet boss to BOOT/RESET counterbore below 1.4 mm: {magnet_clearances}")
    require(magnet_clearances["boss_to_boss"] == 0.0,
            f"the two lower magnet bosses no longer merge into one pocket: {magnet_clearances}")
    require(len(gen.MAGNET_BARS_ASSEMBLED) == 3, "flexible magnet count is not three")
    require(gen.MAGNET_BARS_ASSEMBLED == [
        (-25.0, -36.5, 50.0, 90.0),
        (25.0, -36.5, 50.0, 90.0),
        (46.0, 55.0, 20.0, 50.0),
    ], "flexible magnet layout differs from the confirmed arrangement")
    require(P["magnet_bar_length"] == 90.0 and P["magnet_bar_width"] == 50.0
            and P["magnet_bar_thickness"] == 2.0,
            "large flexible magnet nominal size is not 90 x 50 x 2 mm")
    require(abs(P["magnet_bar_pocket_depth"] - 2.2) <= 0.001,
            "flexible magnet pocket depth is not 2.2 mm")
    require(abs(P["magnet_bar_outer_skin"] - 0.4) <= 0.001,
            "flexible magnet outer PLA skin is not the confirmed 0.4 mm")
    require(P["rear_label_pre_mirrored_for_bottom_view"],
            "rear BOOT/RESET labels are not pre-mirrored for outside viewing")
    require(P["rear_label_position"] == "above_button_hole",
            "rear BOOT/RESET label position is not recorded as above the holes")
    require(abs(P["rear_label_vertical_offset"] - 6.0) <= 0.001,
            "rear BOOT/RESET label vertical offset is not 6.0 mm")
    require(abs(gen.REAR_BOOT_LABEL[0] - gen.REAR_BOOT[0]) <= 0.001
            and gen.REAR_BOOT_LABEL[1] > gen.REAR_BOOT[1],
            "BOOT legend is not centred above its access hole")
    require(abs(gen.REAR_RESET_LABEL[0] - gen.REAR_RESET[0]) <= 0.001
            and gen.REAR_RESET_LABEL[1] > gen.REAR_RESET[1],
            "RESET legend is not centred above its access hole")
    require(P["rear_label_pixel"] + P["rear_label_overlap"] >= 0.55,
            "rear BOOT/RESET label stroke is too thin for a 0.4 mm nozzle")
    require(P["rear_label_depth"] >= 0.6,
            "rear BOOT/RESET engraving is shallower than three 0.2 mm layers")
    require(P["rear_skin"] - P["rear_label_depth"] >= 0.799,
            "rear BOOT/RESET engraving leaves less than 0.8 mm base skin")
    old_round_face_area = 10.0 * math.pi * 5.0**2
    require(abs(magnet_clearances["nominal_face_area_total_mm2"] - 10000.0) <= 0.001,
            f"magnet face area is not 10000 mm2: {magnet_clearances}")
    require(magnet_clearances["nominal_face_area_total_mm2"] / old_round_face_area >= 12.7,
            f"magnet face-area increase below 12.7-fold: {magnet_clearances}")
    magnet_case_edge_margin = min(
        min(
            P["case_width"] / 2.0 - rect[1],
            rect[0] + P["case_width"] / 2.0,
            P["case_height"] / 2.0 - rect[3],
            rect[2] + P["case_height"] / 2.0,
        )
        for rect in (gen.magnet_bar_rect(bar, boss=True) for bar in gen.MAGNET_BARS_ASSEMBLED)
    )
    require(magnet_case_edge_margin >= 1.5,
            f"magnet boss to outer case edge below 1.5 mm: {magnet_case_edge_margin}")

    normal_height = gen.available_assembled_carrier_height()
    component_stacks = {
        "battery_normal_zone": gen.battery_stack_height(),
        "esp32": P["esp_post_top"] + P["esp_body_envelope"],
        "despi": P["carrier_thickness"] + P["despi_body_envelope"],
        "lipo": P["lipo_post_top"] + P["lipo_body_envelope"],
    }
    component_height_clearance = {key: normal_height - value for key, value in component_stacks.items()}
    require(min(component_height_clearance.values()) >= 1.0,
            f"normal vertical clearance below 1 mm: {component_height_clearance}")
    battery_local_clearance = gen.magnet_bar_local_height() - gen.battery_stack_height()
    require(battery_local_clearance >= 1.0,
            f"battery-to-magnet-bar-boss vertical clearance below 1 mm: {battery_local_clearance}")

    screw_engagement = P["case_fastener_length"] - (
        P["assembled_thickness"] - P["case_fastener_counterbore_depth"] - P["front_feature_depth"]
    )
    require(3.0 <= screw_engagement <= 3.6, f"M2x14 engagement out of range: {screw_engagement}")
    require(abs(gen.LIPO_USB_C_FACE[0] - P["charge_cutout_center_x"]) <= 0.25,
            "Lipo USB-C and top opening are not centred")
    require(abs(P["charge_cutout_width"] - 11.5) <= 0.001
            and abs(P["charge_cutout_height"] - 7.5) <= 0.001,
            "USB-C opening is not the revised 11.5 x 7.5 mm size")
    require(P["charge_cutout_width"] >= 8.25 + 2.0
            and P["charge_cutout_height"] >= 2.4 + 2.0,
            "USB-C opening leaves less than 1 mm nominal clearance per side")
    require(abs(P["charge_cutout_center_z"] - 7.0) <= 0.001,
            f"USB-C opening centre was not lowered to Z=7.0 mm: {P['charge_cutout_center_z']}")
    require(abs(P["charge_cutout_vertical_drop"] - 3.0) <= 0.001,
            f"USB-C opening vertical drop is not 3.0 mm: {P['charge_cutout_vertical_drop']}")
    require(P["charge_cutout_center_y"] - 3.0 <= gen.LIPO_USB_C_FACE[1],
            "USB-C side-wall cutter does not reach the connector face")
    require(abs(P["lipo_switch_window_width"] - 3.8) <= 0.001
            and abs(P["lipo_switch_window_height"] - 7.0) <= 0.001,
            "Lipo Rider switch opening is not the compact 3.8 x 7.0 mm size")
    require(P["lipo_switch_window_width"] - P["lipo_switch_package_width"] >= 1.099,
            "Lipo switch opening has less than 0.55 mm nominal side clearance")
    require(P["lipo_switch_window_height"] - P["lipo_switch_package_length"] >= 0.299,
            "Lipo switch opening has less than 0.15 mm nominal end clearance")
    require(P["lipo_switch_window_corner_radius"] >= 1.0,
            "Lipo switch opening corner radius is too small for clean PLA printing")
    switch_x, switch_y = gen.LIPO_SWITCH_POINT_ASSEMBLED
    require(math.dist((switch_x, switch_y), (15.407, 59.352)) <= 0.001,
            f"Lipo switch transform no longer matches the official Eagle SW1 position: {(switch_x, switch_y)}")
    require(P["lipo_regular_opening_enabled"] is True,
            "Rev I regular LED/SW1 opening is not enabled")
    require(abs(P["lipo_regular_opening_width"] - 5.2) <= 0.001
            and abs(P["lipo_regular_opening_height"] - 21.0) <= 0.001,
            "Rev I opening is not the confirmed 5.2 x 21.0 mm size")
    require(abs(P["lipo_regular_opening_corner_radius"] - 1.0) <= 0.001,
            "Rev I opening corner radius is not R1.0 mm")

    pure_left_straight = P["case_height"] - 2.0 * P["corner_radius"]
    left_transition_extension = (
        P["rear_left_flat_span"] - pure_left_straight
    ) / 2.0
    require(abs(pure_left_straight - 168.0) <= 0.001,
            f"rear left pure straight edge is not 168 mm: {pure_left_straight}")
    require(abs(P["rear_left_flat_span"] - 170.0) <= 0.001,
            f"rear left flat/thinned span is not 170 mm: {P['rear_left_flat_span']}")
    require(abs(left_transition_extension - 1.0) <= 0.001,
            f"rear left flat/thinned region does not extend 1 mm into each corner: {left_transition_extension}")
    require(abs(P["rear_left_edge_drop"]) <= 0.001,
            f"rear left edge is still lowered: {P['rear_left_edge_drop']}")
    require(abs(P["rear_left_lower_wall_thickness"] - 1.8) <= 0.001,
            f"rear left lower wall thickness is not 1.8 mm: {P['rear_left_lower_wall_thickness']}")
    require(abs(P["rear_left_restored_band_height"] - 1.8) <= 0.001,
            f"rear left restored band height is not 1.8 mm: {P['rear_left_restored_band_height']}")
    require(abs(P["rear_left_restored_band_thickness"] - 0.8) <= 0.001,
            f"rear left restored band thickness is not 0.8 mm: {P['rear_left_restored_band_thickness']}")
    require(abs(P["rear_left_flat_y_min"] + 85.0) <= 0.001
            and abs(P["rear_left_flat_y_max"] - 85.0) <= 0.001,
            "rear left flat/thinned Y range is not -85..+85 mm")
    require(P["rear_left_inward_ledge_removed"] is True,
            "rear left inward ledge is not marked as removed")

    rear_raw = trimesh.load(OUTPUT / "rear_cover_v0_7.stl", force="mesh")

    def rear_probe_volume(x, y, z, size=0.4):
        probe = trimesh.creation.box((size, size, size))
        probe.apply_translation((x, y, z))
        hit = trimesh.boolean.intersection([rear_raw, probe], engine="manifold")
        return abs(float(hit.volume)) if hit is not None and len(hit.faces) else 0.0

    left_wall_probes = {
        "restored_top_band_outer_wall": rear_probe_volume(-59.6, 0.0, 15.5),
        "restored_top_band_inner_clearance": rear_probe_volume(-58.8, 0.0, 15.5),
        "removed_inward_ledge": rear_probe_volume(-56.7, 0.0, 15.5),
        "original_lower_wall_inner_part": rear_probe_volume(-58.6, 0.0, 10.0),
        "lower_wall_interior_clearance": rear_probe_volume(-58.0, 0.0, 10.0),
        "upper_wall_outside_170mm_zone": rear_probe_volume(-59.0, 86.0, 15.5),
        "lower_wall_outside_170mm_zone": rear_probe_volume(-59.0, -86.0, 15.5),
    }
    right_wall_restore_probes = {
        "restored_wall_top": rear_probe_volume(59.0, 0.0, 15.5),
        "restored_inward_ledge": rear_probe_volume(56.7, 0.0, 15.5),
    }
    expected_probe_volume = 0.4**3
    require(left_wall_probes["restored_top_band_outer_wall"] >= expected_probe_volume - 0.005,
            f"restored 0.8 mm top band is missing: {left_wall_probes}")
    require(left_wall_probes["restored_top_band_inner_clearance"] <= 0.001,
            f"restored top band was not thinned to 0.8 mm: {left_wall_probes}")
    require(left_wall_probes["removed_inward_ledge"] <= 0.001,
            f"left inward ledge remains: {left_wall_probes}")
    require(left_wall_probes["original_lower_wall_inner_part"] >= expected_probe_volume - 0.005,
            f"original 1.8 mm lower wall was incorrectly thinned: {left_wall_probes}")
    require(left_wall_probes["lower_wall_interior_clearance"] <= 0.001,
            f"lower wall is thicker than the original 1.8 mm: {left_wall_probes}")
    require(left_wall_probes["upper_wall_outside_170mm_zone"] >= expected_probe_volume - 0.005
            and left_wall_probes["lower_wall_outside_170mm_zone"] >= expected_probe_volume - 0.005,
            f"left wall transition is missing outside the 170 mm thin zone: {left_wall_probes}")
    require(right_wall_restore_probes["restored_wall_top"] >= expected_probe_volume - 0.005,
            f"right wall top was not restored: {right_wall_restore_probes}")
    require(right_wall_restore_probes["restored_inward_ledge"] >= expected_probe_volume - 0.005,
            f"right inward ledge was not restored: {right_wall_restore_probes}")
    # Measure the long wall at its Y=0 mid-plane.  Using all mesh vertices here
    # would incorrectly include nearby ledges, bosses and cutter end faces.
    flat_wall_section = rear_raw.section(
        plane_origin=[0.0, 0.0, 0.0], plane_normal=[0.0, 1.0, 0.0]
    )
    require(flat_wall_section is not None, "rear Y=0 section is missing")
    flat_wall_section_vertices = flat_wall_section.vertices
    actual_flat_edge_height = max(
        float(z) for x, _, z in flat_wall_section_vertices if x < -59.15
    )
    actual_top_band_inner_x = max(
        float(x)
        for x, _, z in flat_wall_section_vertices
        if x < -58.0 and z > P["rear_depth"] - P["rear_left_restored_band_height"] + 0.1
    )
    actual_lower_wall_inner_x = max(
        float(x)
        for x, _, z in flat_wall_section_vertices
        if x < -58.0 and 5.0 < z < 10.0
    )
    actual_top_band_thickness = actual_top_band_inner_x + P["case_width"] / 2.0
    actual_lower_wall_thickness = actual_lower_wall_inner_x + P["case_width"] / 2.0
    require(abs(actual_flat_edge_height - P["rear_depth"]) <= 0.001,
            f"actual rear left edge is not level at 16.6 mm: {actual_flat_edge_height}")
    require(abs(actual_top_band_thickness - 0.8) <= 0.001,
            f"actual rear left restored band is not 0.8 mm thick: {actual_top_band_thickness}")
    require(abs(actual_lower_wall_thickness - 1.8) <= 0.001,
            f"actual rear left lower wall is not 1.8 mm thick: {actual_lower_wall_thickness}")

    usb_half_height = P["charge_cutout_height"] / 2.0
    usb_opening_probes = {
        "new_centre_open": rear_probe_volume(0.0, 91.0, 7.0),
        "upper_inside_open": rear_probe_volume(
            0.0, 91.0, P["charge_cutout_center_z"] + usb_half_height - 0.3
        ),
        "lower_inside_open": rear_probe_volume(
            0.0, 91.0, P["charge_cutout_center_z"] - usb_half_height + 0.3
        ),
        "above_new_opening_closed": rear_probe_volume(
            0.0, 91.0, P["charge_cutout_center_z"] + usb_half_height + 0.5
        ),
        "below_new_opening_closed": rear_probe_volume(
            0.0, 91.0, P["charge_cutout_center_z"] - usb_half_height - 0.5
        ),
    }
    require(usb_opening_probes["new_centre_open"] <= 0.001,
            f"USB-C opening is not open at Z=7.0 mm: {usb_opening_probes}")
    require(usb_opening_probes["upper_inside_open"] <= 0.001
            and usb_opening_probes["lower_inside_open"] <= 0.001,
            f"USB-C opening did not expand 1 mm above and below: {usb_opening_probes}")
    require(usb_opening_probes["above_new_opening_closed"] >= expected_probe_volume - 0.005
            and usb_opening_probes["below_new_opening_closed"] >= expected_probe_volume - 0.005,
            f"USB-C opening height is not bounded around the lowered centre: {usb_opening_probes}")

    indicator_x, indicator_y = gen.LIPO_INDICATOR_WINDOW_ASSEMBLED
    indicator_half_width = P["lipo_indicator_window_width"] / 2.0
    indicator_half_height = P["lipo_indicator_window_height"] / 2.0
    regular_x, regular_y = gen.LIPO_REGULAR_OPENING_ASSEMBLED
    regular_half_width = P["lipo_regular_opening_width"] / 2.0
    regular_half_height = P["lipo_regular_opening_height"] / 2.0
    led_edge_margins = [
        min(
            regular_half_width - abs(x - regular_x),
            regular_half_height - abs(y - regular_y),
        )
        for x, y in gen.LIPO_LED_POINTS_ASSEMBLED
    ]
    require(min(led_edge_margins) >= 0.75,
            f"LED viewing slot does not cover all five LEDs with 0.75 mm margin: {led_edge_margins}")
    indicator_rect = (
        indicator_x - indicator_half_width,
        indicator_x + indicator_half_width,
        indicator_y - indicator_half_height,
        indicator_y + indicator_half_height,
    )
    regular_rect = (
        regular_x - regular_half_width,
        regular_x + regular_half_width,
        regular_y - regular_half_height,
        regular_y + regular_half_height,
    )
    regular_to_magnet_boss = min(
        gen.rect_to_rect(regular_rect, gen.magnet_bar_rect(bar, boss=True))
        for bar in gen.MAGNET_BARS_ASSEMBLED
    )
    require(regular_to_magnet_boss >= 15.0,
            f"Rev I regular opening is less than 15 mm from a magnet boss: {regular_to_magnet_boss}")
    switch_half_width = P["lipo_switch_window_width"] / 2.0
    switch_half_height = P["lipo_switch_window_height"] / 2.0
    switch_rect = (
        switch_x - switch_half_width,
        switch_x + switch_half_width,
        switch_y - switch_half_height,
        switch_y + switch_half_height,
    )
    switch_to_indicator = gen.rect_to_rect(switch_rect, indicator_rect)
    require(switch_to_indicator >= 1.5,
            f"original Lipo switch-to-LED separation is unexpectedly small: {switch_to_indicator}")
    switch_to_magnet_boss = min(
        gen.rect_to_rect(switch_rect, gen.magnet_bar_rect(bar, boss=True))
        for bar in gen.MAGNET_BARS_ASSEMBLED
    )
    require(switch_to_magnet_boss >= 15.0,
            f"Lipo switch opening is less than 15 mm from a magnet boss: {switch_to_magnet_boss}")
    switch_model_x, switch_model_y = gen.LIPO_SWITCH_WINDOW_MODEL
    indicator_model_x, indicator_model_y = gen.LIPO_INDICATOR_WINDOW_MODEL
    regular_model_x, regular_model_y = gen.LIPO_REGULAR_OPENING_MODEL
    regular_half_width = P["lipo_regular_opening_width"] / 2.0
    regular_half_height = P["lipo_regular_opening_height"] / 2.0
    regular_geometry_probes = {
        "centre_open": rear_probe_volume(regular_model_x, regular_model_y, 0.7, size=0.2),
        "led_centre_open": rear_probe_volume(indicator_model_x, indicator_model_y, 0.7, size=0.2),
        "switch_centre_open": rear_probe_volume(switch_model_x, switch_model_y, 0.7, size=0.2),
        "left_skin_closed": rear_probe_volume(
            regular_model_x - regular_half_width - 0.5, regular_model_y, 0.7, size=0.2
        ),
        "right_skin_closed": rear_probe_volume(
            regular_model_x + regular_half_width + 0.5, regular_model_y, 0.7, size=0.2
        ),
        "lower_skin_closed": rear_probe_volume(
            regular_model_x, regular_model_y - regular_half_height - 0.5, 0.7, size=0.2
        ),
        "upper_skin_closed": rear_probe_volume(
            regular_model_x, regular_model_y + regular_half_height + 0.5, 0.7, size=0.2
        ),
    }
    expected_switch_probe_volume = 0.2**3
    require(max(
        regular_geometry_probes["centre_open"],
        regular_geometry_probes["led_centre_open"],
        regular_geometry_probes["switch_centre_open"],
    ) <= 0.001,
            f"Rev I regular opening does not cover LED and SW1 centres: {regular_geometry_probes}")
    require(min(
        regular_geometry_probes["left_skin_closed"],
        regular_geometry_probes["right_skin_closed"],
        regular_geometry_probes["lower_skin_closed"],
        regular_geometry_probes["upper_skin_closed"],
    ) >= expected_switch_probe_volume - 0.001,
            f"Rev I opening extends outside its 5.2 x 21.0 mm envelope: {regular_geometry_probes}")
    front_post_radius = P["case_fastener_post_diameter"] / 2.0
    rear_boss_relief_radius = front_post_radius + P["front_boss_relief_radial_clearance"]
    require(abs(front_post_radius - 2.6) <= 0.001,
            f"unexpected front screw-post radius: {front_post_radius}")
    require(abs(rear_boss_relief_radius - 3.3) <= 0.001,
            f"unexpected rear boss-relief radius: {rear_boss_relief_radius}")
    require(rear_boss_relief_radius - front_post_radius >= 0.699,
            "rear boss relief has less than 0.7 mm radial clearance")
    require(abs(P["rear_boss_relief_axial_depth_into_tube"] - 0.6) <= 0.001,
            "rear boss relief does not reach 0.6 mm into the screw tube")
    require(abs(P["rear_boss_relief_entry_chamfer"] - 0.5) <= 0.001,
            "rear boss relief entry chamfer is not 0.5 mm")
    require(abs(P["rear_corner_entry_relief_depth"] - 1.2) <= 0.001,
            "rear corner entry relief depth is not 1.2 mm")
    require(abs(P["rear_corner_entry_radial_relief"] - 0.4) <= 0.001,
            "rear corner entry radial relief is not 0.4 mm")
    require(abs(P["rear_corner_entry_chamfer"] - 0.5) <= 0.001,
            "rear corner entry chamfer is not 0.5 mm")
    require(abs(P["rear_corner_contact_relief"] - 0.3) <= 0.001,
            "rear corner contact/elephant-foot relief is not 0.3 mm")
    carrier_boss_relief_radius = P["carrier_front_boss_relief_diameter"] / 2.0
    require(abs(carrier_boss_relief_radius - 2.9) <= 0.001,
            f"unexpected carrier boss-relief radius: {carrier_boss_relief_radius}")

    tube_top = P["assembled_thickness"] - P["front_feature_depth"]
    fastener_x, fastener_y = gen.CASE_FASTENERS[0]
    # Inside the new R3.3 relief, material must be removed 0.6 mm into the
    # screw tube; immediately below that depth the original tube remains.
    rear_boss_dfm_probes = {
        "inside_relief_0_3mm_into_tube": rear_probe_volume(
            fastener_x + 2.85, fastener_y, tube_top - 0.3
        ),
        "tube_preserved_below_0_6mm_relief": rear_probe_volume(
            fastener_x + 2.85, fastener_y, tube_top - 0.85
        ),
        "mouth_chamfer_outer_radius": rear_probe_volume(
            fastener_x + 3.55, fastener_y, P["rear_depth"] - 0.2
        ),
    }
    require(rear_boss_dfm_probes["inside_relief_0_3mm_into_tube"] <= 0.001,
            f"rear boss relief does not reach into the screw tube: {rear_boss_dfm_probes}")
    require(rear_boss_dfm_probes["tube_preserved_below_0_6mm_relief"] >= expected_probe_volume - 0.005,
            f"rear screw tube was cut deeper than the Rev E allowance: {rear_boss_dfm_probes}")
    require(rear_boss_dfm_probes["mouth_chamfer_outer_radius"] <= 0.001,
            f"rear boss relief mouth chamfer is missing: {rear_boss_dfm_probes}")

    corner_cx = P["rear_inner_width"] / 2.0 - P["rear_inner_corner_radius"]
    corner_cy = P["rear_inner_height"] / 2.0 - P["rear_inner_corner_radius"]
    diagonal = 1.0 / math.sqrt(2.0)

    corner_probe_size = 0.1

    def corner_probe(radius, z):
        return rear_probe_volume(
            corner_cx + radius * diagonal,
            corner_cy + radius * diagonal,
            z,
            size=corner_probe_size,
        )

    rear_corner_dfm_probes = {
        "base_cavity_unchanged_below_entry": corner_probe(6.4, P["rear_depth"] - 1.55),
        "radial_relief_in_first_1_2mm": corner_probe(6.4, P["rear_depth"] - 0.85),
        "mouth_chamfer_at_r6_8": corner_probe(6.8, P["rear_depth"] - 0.15),
        "r6_8_preserved_below_chamfer": corner_probe(6.8, P["rear_depth"] - 0.85),
    }
    expected_corner_probe_volume = corner_probe_size**3
    require(rear_corner_dfm_probes["base_cavity_unchanged_below_entry"] >= expected_corner_probe_volume - 0.0001,
            f"base R6.2 cavity changed below the local entry: {rear_corner_dfm_probes}")
    require(rear_corner_dfm_probes["radial_relief_in_first_1_2mm"] <= 0.00005,
            f"rear corner +0.4 mm entry relief is missing: {rear_corner_dfm_probes}")
    require(rear_corner_dfm_probes["mouth_chamfer_at_r6_8"] <= 0.00005,
            f"rear corner mouth chamfer is missing: {rear_corner_dfm_probes}")
    require(rear_corner_dfm_probes["r6_8_preserved_below_chamfer"] >= expected_corner_probe_volume - 0.0001,
            f"rear corner mouth chamfer extends too deep: {rear_corner_dfm_probes}")

    front_mesh = trimesh.load(OUTPUT / "front_bezel_v0_7.stl", force="mesh")
    retainer_z0 = P["front_face_thickness"] - 0.2
    retainer_z1 = retainer_z0 + P["screen_locator_depth"]
    # Probe only above the 2.4 mm face so the right-side reading cannot include
    # the unchanged bezel face below the retainer.
    retainer_probe_z0 = P["front_face_thickness"] + 0.05
    outer_half_width = P["case_width"] / 2.0 - P["front_retainer_edge_inset"]
    left_retainer_probe = trimesh.creation.box(
        (P["front_retainer_width"], 40.0, retainer_z1 - retainer_probe_z0)
    )
    left_retainer_probe.apply_translation(
        (-outer_half_width + P["front_retainer_width"] / 2.0, 0.0, (retainer_probe_z0 + retainer_z1) / 2.0)
    )
    right_retainer_probe = left_retainer_probe.copy()
    right_retainer_probe.apply_translation((2.0 * outer_half_width - P["front_retainer_width"], 0.0, 0.0))
    left_retainer_intersection = trimesh.boolean.intersection(
        [front_mesh, left_retainer_probe], engine="manifold"
    )
    right_retainer_intersection = trimesh.boolean.intersection(
        [front_mesh, right_retainer_probe], engine="manifold"
    )
    left_retainer_probe_volume = abs(float(left_retainer_intersection.volume))
    right_retainer_probe_volume = (
        abs(float(right_retainer_intersection.volume))
        if right_retainer_intersection is not None and len(right_retainer_intersection.faces)
        else 0.0
    )
    expected_left_probe_volume = P["front_retainer_width"] * 40.0 * (retainer_z1 - retainer_probe_z0)
    require(abs(left_retainer_probe_volume - expected_left_probe_volume) <= 0.05,
            f"actual left retainer geometry is incomplete: {left_retainer_probe_volume}")
    require(right_retainer_probe_volume <= 0.001,
            f"actual right retainer geometry still exists: {right_retainer_probe_volume}")

    arc_centre_x = outer_half_width - P["front_retainer_outer_radius"]
    outer_half_height = P["case_height"] / 2.0 - P["front_retainer_edge_inset"]
    arc_centre_y = outer_half_height - P["front_retainer_outer_radius"]
    arc_mid_radius = (P["front_retainer_outer_radius"] + P["front_retainer_inner_radius"]) / 2.0
    arc_offset = arc_mid_radius / math.sqrt(2.0)
    four_corner_arc_probe_volumes = {}
    for sx, sy, label in (
        (-1, 1, "upper_left"),
        (1, 1, "upper_right"),
        (-1, -1, "lower_left"),
        (1, -1, "lower_right"),
    ):
        probe = trimesh.creation.box((0.5, 0.5, retainer_z1 - retainer_probe_z0))
        probe.apply_translation((
            sx * (arc_centre_x + arc_offset),
            sy * (arc_centre_y + arc_offset),
            (retainer_probe_z0 + retainer_z1) / 2.0,
        ))
        intersection = trimesh.boolean.intersection([front_mesh, probe], engine="manifold")
        volume = (
            abs(float(intersection.volume))
            if intersection is not None and len(intersection.faces)
            else 0.0
        )
        four_corner_arc_probe_volumes[label] = volume
    expected_arc_probe_volume = 0.5 * 0.5 * (retainer_z1 - retainer_probe_z0)
    require(min(four_corner_arc_probe_volumes.values()) >= expected_arc_probe_volume - 0.01,
            f"one or more front-retainer corner arcs are missing: {four_corner_arc_probe_volumes}")

    # Rev E left-side inner-corner check.  These probes sit wholly inside the
    # material left by the old R1.5 inner arc, but inside the new square screen
    # opening.  Both volumes must therefore be empty above the bezel face.
    inner_half_width = outer_half_width - P["front_retainer_width"]
    inner_half_height = outer_half_height - P["front_retainer_width"]
    left_square_corner_probe_volumes = {}
    for sy, label in ((1, "upper_left"), (-1, "lower_left")):
        probe = trimesh.creation.box((0.2, 0.2, retainer_z1 - retainer_probe_z0))
        probe.apply_translation((
            -inner_half_width + 0.25,
            sy * (inner_half_height - 0.25),
            (retainer_probe_z0 + retainer_z1) / 2.0,
        ))
        hit = trimesh.boolean.intersection([front_mesh, probe], engine="manifold")
        left_square_corner_probe_volumes[label] = (
            abs(float(hit.volume)) if hit is not None and len(hit.faces) else 0.0
        )
    require(max(left_square_corner_probe_volumes.values()) <= 0.001,
            f"a rounded residue remains in a Rev E left inner corner: {left_square_corner_probe_volumes}")

    right_arc_tangent_x = outer_half_width - P["front_retainer_outer_radius"]
    natural_right_opening_span = 2.0 * inner_half_height
    right_horizontal_edge_probe_volumes = {}
    right_clearance_probe_volumes = {}
    for sy, label in ((1, "upper_right"), (-1, "lower_right")):
        flat_probe = trimesh.creation.box((0.5, 0.5, retainer_z1 - retainer_probe_z0))
        flat_probe.apply_translation((
            right_arc_tangent_x + 2.0,
            sy * (inner_half_height + 0.25),
            (retainer_probe_z0 + retainer_z1) / 2.0,
        ))
        flat_hit = trimesh.boolean.intersection([front_mesh, flat_probe], engine="manifold")
        right_horizontal_edge_probe_volumes[label] = (
            abs(float(flat_hit.volume)) if flat_hit is not None and len(flat_hit.faces) else 0.0
        )

        gap_probe = trimesh.creation.box((0.5, 0.5, retainer_z1 - retainer_probe_z0))
        gap_probe.apply_translation((
            right_arc_tangent_x + 2.0,
            sy * (inner_half_height - 0.5),
            (retainer_probe_z0 + retainer_z1) / 2.0,
        ))
        gap_hit = trimesh.boolean.intersection([front_mesh, gap_probe], engine="manifold")
        right_clearance_probe_volumes[label] = (
            abs(float(gap_hit.volume)) if gap_hit is not None and len(gap_hit.faces) else 0.0
        )
    require(min(right_horizontal_edge_probe_volumes.values()) >= expected_arc_probe_volume - 0.01,
            f"one or more horizontally trimmed right arc edges are missing: {right_horizontal_edge_probe_volumes}")
    require(max(right_clearance_probe_volumes.values()) <= 0.001,
            f"a right-side feature intrudes into the natural opening: {right_clearance_probe_volumes}")
    # These probes cover the former 0.5 mm land/step zone.  Rev F requires it
    # to be completely empty so the top and bottom inner edges continue at
    # their original heights directly to the outer arcs.
    right_no_step_probe_volumes = {}
    for sy, label in ((1, "upper_right"), (-1, "lower_right")):
        probe = trimesh.creation.box((0.2, 0.2, retainer_z1 - retainer_probe_z0))
        probe.apply_translation((
            right_arc_tangent_x + 0.25,
            sy * (inner_half_height - 0.25),
            (retainer_probe_z0 + retainer_z1) / 2.0,
        ))
        hit = trimesh.boolean.intersection([front_mesh, probe], engine="manifold")
        right_no_step_probe_volumes[label] = (
            abs(float(hit.volume)) if hit is not None and len(hit.faces) else 0.0
        )
    require(max(right_no_step_probe_volumes.values()) <= 0.001,
            f"a Rev F tongue or height step remains at the right edge: {right_no_step_probe_volumes}")
    right_end_vertices = front_mesh.vertices[
        (front_mesh.vertices[:, 0] > right_arc_tangent_x + 0.1)
        & (front_mesh.vertices[:, 2] > retainer_probe_z0)
    ]
    right_upper_inner_y = min(float(y) for y in right_end_vertices[:, 1] if y > 0.0)
    right_lower_inner_y = max(float(y) for y in right_end_vertices[:, 1] if y < 0.0)
    actual_right_clear_span = right_upper_inner_y - right_lower_inner_y
    require(abs(actual_right_clear_span - natural_right_opening_span) <= 0.001,
            "actual STL right opening does not follow the unmodified top/bottom inner edges: "
            f"{actual_right_clear_span} vs {natural_right_opening_span}")
    rear_assembled = trimesh.load(OUTPUT / "rear_cover_v0_7.stl", force="mesh")
    rear_assembled.vertices[:, 2] = P["assembled_thickness"] - rear_assembled.vertices[:, 2]
    rear_assembled.invert()
    corner_collision_volumes = {}
    for x, y in gen.CASE_FASTENERS:
        inspection_box = trimesh.creation.box((12.0, 12.0, 8.0))
        inspection_box.apply_translation((x, y, 6.0))
        front_local = trimesh.boolean.intersection([front_mesh, inspection_box], engine="manifold")
        rear_local = trimesh.boolean.intersection([rear_assembled, inspection_box], engine="manifold")
        collision = trimesh.boolean.intersection([front_local, rear_local], engine="manifold")
        volume = abs(float(collision.volume)) if collision is not None and len(collision.faces) else 0.0
        corner_collision_volumes[f"{x:.1f},{y:.1f}"] = volume
    require(max(corner_collision_volumes.values()) <= 0.001,
            f"front screw post still collides with rear cover: {corner_collision_volumes}")

    carrier_assembled = trimesh.load(OUTPUT / "electronics_carrier_v0_7.stl", force="mesh")
    carrier_assembled.apply_translation((0.0, 0.0, 4.0))
    pair_collision_volumes = {"front_carrier": {}, "carrier_rear": {}}
    for x, y in gen.CASE_FASTENERS:
        key = f"{x:.1f},{y:.1f}"
        inspection_box = trimesh.creation.box((12.0, 12.0, 10.0))
        inspection_box.apply_translation((x, y, 6.0))
        front_local = trimesh.boolean.intersection([front_mesh, inspection_box], engine="manifold")
        carrier_local = trimesh.boolean.intersection([carrier_assembled, inspection_box], engine="manifold")
        rear_local = trimesh.boolean.intersection([rear_assembled, inspection_box], engine="manifold")
        for pair_name, left, right in (
            ("front_carrier", front_local, carrier_local),
            ("carrier_rear", carrier_local, rear_local),
        ):
            collision = trimesh.boolean.intersection([left, right], engine="manifold")
            volume = abs(float(collision.volume)) if collision is not None and len(collision.faces) else 0.0
            pair_collision_volumes[pair_name][key] = volume
    require(
        max(value for pair in pair_collision_volumes.values() for value in pair.values()) <= 0.001,
        f"three-layer corner collision remains: {pair_collision_volumes}",
    )

    front_x0, front_x1, front_y0, _ = gen.COUPON_BOUNDS_FRONT
    rear_x0, rear_x1, rear_y0, _ = gen.COUPON_BOUNDS_REAR_REV_B
    raw_coupon_hole_centres = {
        "front": (38.0 - front_x0, 87.9 - front_y0),
        "carrier": (38.0 - front_x0, 87.9 - front_y0),
        "rear_rev_b": (-38.0 - rear_x0, 87.9 - rear_y0),
    }
    rear_coupon_width = rear_x1 - rear_x0
    assembled_coupon_hole_centres = {
        "front": raw_coupon_hole_centres["front"],
        "carrier": raw_coupon_hole_centres["carrier"],
        "rear_rev_b_after_turnover": (
            rear_coupon_width - raw_coupon_hole_centres["rear_rev_b"][0],
            raw_coupon_hole_centres["rear_rev_b"][1],
        ),
    }
    require(abs(raw_coupon_hole_centres["rear_rev_b"][0] - 22.0) <= 0.001,
            f"rear Rev B raw hole is not on the opposite side: {raw_coupon_hole_centres}")
    require(
        max(math.dist(assembled_coupon_hole_centres["front"], centre)
            for centre in assembled_coupon_hole_centres.values()) <= 0.001,
        f"corner coupon fastener holes are not coaxial after turnover: {assembled_coupon_hole_centres}",
    )

    report = {
        "result": "PASS",
        "stl_checks": checks,
        "outer_size_mm": [P["case_width"], P["case_height"], P["assembled_thickness"]],
        "carrier_fit_per_side_mm": P["carrier_fit_per_side"],
        "screen_clearance_per_side_mm": [
            (P["screen_pocket_width"] - P["screen_body_width"]) / 2.0,
            (P["screen_pocket_height"] - P["screen_body_height"]) / 2.0,
        ],
        "front_retainer_rev_f": {
            "retained_sides": ["top", "bottom", "left", "upper-right arc", "lower-right arc"],
            "right_retainer_removed": P["front_right_retainer_removed"],
            "width_mm": P["front_retainer_width"],
            "left_right_outer_edge_inset_mm": P["front_retainer_edge_inset"],
            "top_bottom_outer_edge_inset_mm": P["front_retainer_top_bottom_edge_inset"],
            "outer_corner_radius_mm": P["front_retainer_outer_radius"],
            "right_transition_inner_radius_mm": P["front_retainer_inner_radius"],
            "left_inner_corner_radius_mm": P["front_retainer_left_inner_corner_radius"],
            "left_inner_corner_style": P["front_retainer_left_inner_corner_style"],
            "rear_inner_corner_radius_mm": P["rear_inner_corner_radius"],
            "radial_clearance_to_rear_mm": P["front_retainer_to_rear_radial_clearance"],
            "four_corner_arc_probe_volumes_mm3": {
                key: round(value, 6) for key, value in four_corner_arc_probe_volumes.items()
            },
            "left_square_corner_residual_probe_volumes_mm3": {
                key: round(value, 6) for key, value in left_square_corner_probe_volumes.items()
            },
            "right_end_style": P["front_retainer_right_end_style"],
            "independent_clear_span_constraint_mm": None,
            "natural_right_opening_span_mm": round(natural_right_opening_span, 3),
            "actual_right_opening_span_from_stl_mm": round(actual_right_clear_span, 3),
            "right_horizontal_edge_probe_volumes_mm3": {
                key: round(value, 6) for key, value in right_horizontal_edge_probe_volumes.items()
            },
            "right_clearance_probe_volumes_mm3": {
                key: round(value, 6) for key, value in right_clearance_probe_volumes.items()
            },
            "right_no_step_probe_volumes_mm3": {
                key: round(value, 6) for key, value in right_no_step_probe_volumes.items()
            },
            "left_overlap_on_physical_panel_mm": round(left_retainer_overlap, 3),
            "measured_left_inactive_border_remaining_mm": round(measured_left_inactive_border_remaining, 3),
            "actual_left_probe_volume_mm3": round(left_retainer_probe_volume, 3),
            "actual_right_probe_volume_mm3": round(right_retainer_probe_volume, 6),
        },
        "component_edge_margins_mm": {key: round(value, 3) for key, value in component_margins.items()},
        "normal_height_from_carrier_underside_mm": round(normal_height, 3),
        "component_height_clearance_mm": {key: round(value, 3) for key, value in component_height_clearance.items()},
        "battery_magnet_bar_clearance_mm": round(battery_local_clearance, 3),
        "battery_to_fastener_tube_mm": round(battery_to_tube, 3),
        "magnet_clearances_mm": magnet_clearances,
        "magnet_boss_to_case_edge_mm": round(magnet_case_edge_margin, 3),
        "m2x14_engagement_mm": round(screw_engagement, 3),
        "usb_c_opening_mm": [P["charge_cutout_width"], P["charge_cutout_height"]],
        "usb_c_opening_center_z_mm": P["charge_cutout_center_z"],
        "usb_c_vertical_drop_mm": P["charge_cutout_vertical_drop"],
        "usb_c_geometry_probe_volumes_mm3": {
            key: round(value, 6) for key, value in usb_opening_probes.items()
        },
        "usb_c_face_to_case_outer_edge_mm": round(P["case_height"] / 2.0 - gen.LIPO_USB_C_FACE[1], 3),
        "rear_left_edge_revision": {
            "pure_straight_length_mm": round(pure_left_straight, 3),
            "corner_transition_extension_each_end_mm": round(left_transition_extension, 3),
            "required_flat_thinned_span_mm": P["rear_left_flat_span"],
            "edge_drop_mm": P["rear_left_edge_drop"],
            "required_lower_wall_thickness_mm": P["rear_left_lower_wall_thickness"],
            "actual_lower_wall_thickness_from_stl_mm": round(actual_lower_wall_thickness, 3),
            "required_restored_band_height_mm": P["rear_left_restored_band_height"],
            "required_restored_band_thickness_mm": P["rear_left_restored_band_thickness"],
            "actual_restored_band_thickness_from_stl_mm": round(actual_top_band_thickness, 3),
            "actual_flat_edge_height_from_stl_mm": round(actual_flat_edge_height, 3),
            "inward_ledge_removed": P["rear_left_inward_ledge_removed"],
            "opposite_right_edge_restored": True,
            "geometry_probe_volumes_mm3": {
                key: round(value, 6) for key, value in left_wall_probes.items()
            },
            "right_restore_probe_volumes_mm3": {
                key: round(value, 6) for key, value in right_wall_restore_probes.items()
            },
        },
        "lipo_indicator_window_mm": [
            P["lipo_indicator_window_width"],
            P["lipo_indicator_window_height"],
        ],
        "lipo_indicator_window_assembled_center_mm": [round(indicator_x, 3), round(indicator_y, 3)],
        "lipo_led_min_window_edge_margin_mm": round(min(led_edge_margins), 3),
        "regular_opening_to_magnet_boss_mm": round(regular_to_magnet_boss, 3),
        "lipo_switch_access_mm": [
            P["lipo_switch_window_width"],
            P["lipo_switch_window_height"],
        ],
        "lipo_switch_access_assembled_center_mm": [round(switch_x, 3), round(switch_y, 3)],
        "lipo_switch_to_indicator_original_gap_removed_mm": round(switch_to_indicator, 3),
        "lipo_switch_to_magnet_boss_mm": round(switch_to_magnet_boss, 3),
        "lipo_regular_opening_mm": [
            P["lipo_regular_opening_width"],
            P["lipo_regular_opening_height"],
        ],
        "lipo_regular_opening_corner_radius_mm": P["lipo_regular_opening_corner_radius"],
        "lipo_regular_opening_assembled_center_mm": [
            round(value, 3) for value in gen.LIPO_REGULAR_OPENING_ASSEMBLED
        ],
        "lipo_regular_opening_geometry_probe_volumes_mm3": {
            key: round(value, 6) for key, value in regular_geometry_probes.items()
        },
        "front_screw_post_radius_mm": round(front_post_radius, 3),
        "rear_internal_boss_relief_radius_mm": round(rear_boss_relief_radius, 3),
        "carrier_front_boss_relief_radius_mm": round(carrier_boss_relief_radius, 3),
        "boss_relief_radial_clearance_mm": round(rear_boss_relief_radius - front_post_radius, 3),
        "rear_boss_relief_axial_depth_into_tube_mm": P["rear_boss_relief_axial_depth_into_tube"],
        "rear_boss_relief_entry_chamfer_mm": P["rear_boss_relief_entry_chamfer"],
        "rear_boss_dfm_probe_volumes_mm3": {
            key: round(value, 6) for key, value in rear_boss_dfm_probes.items()
        },
        "rear_corner_entry_dfm": {
            "base_corner_radius_mm": P["rear_inner_corner_radius"],
            "entry_depth_mm": P["rear_corner_entry_relief_depth"],
            "radial_relief_mm": P["rear_corner_entry_radial_relief"],
            "entry_radius_mm": round(
                P["rear_inner_corner_radius"] + P["rear_corner_entry_radial_relief"], 3
            ),
            "mouth_chamfer_mm": P["rear_corner_entry_chamfer"],
            "contact_relief_mm": P["rear_corner_contact_relief"],
            "geometry_probe_volumes_mm3": {
                key: round(value, 6) for key, value in rear_corner_dfm_probes.items()
            },
        },
        "front_to_rear_corner_collision_volume_mm3": {
            key: round(value, 6) for key, value in corner_collision_volumes.items()
        },
        "three_layer_corner_collision_volume_mm3": {
            pair_name: {key: round(value, 6) for key, value in values.items()}
            for pair_name, values in pair_collision_volumes.items()
        },
        "corner_coupon_raw_hole_centres_mm": {
            key: [round(value[0], 3), round(value[1], 3)]
            for key, value in raw_coupon_hole_centres.items()
        },
        "corner_coupon_assembled_hole_centres_mm": {
            key: [round(value[0], 3), round(value[1], 3)]
            for key, value in assembled_coupon_hole_centres.items()
        },
        "physical_validation": (
            "PENDING: first print fit_test_front_left_retainer_v0_7_rev_e_square_inner.stl "
            "and fit_test_front_right_open_v0_7_rev_f_continuous_edge.stl to verify the square left "
            "inner corners and continuous right horizontal edges before printing the full front bezel; "
            "print fit_test_lipo_regular_led_switch_opening_v0_7_rev_i.stl and confirm all five "
            "LEDs remain visible plus full ON/OFF travel before printing the full rear cover; "
            "other rear-cover coupons remain required"
        ),
    }
    report_path = OUTPUT / "validation_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    package = ROOT / "RFM_enclosure_v0_7_STL.zip"
    package_dir = ROOT / "RFM_enclosure_v0_7_STL"
    bundle = [
        *sorted(OUTPUT.glob("*.stl")),
        OUTPUT / "manifest.json",
        OUTPUT / "placement_template_v0_7_1to1.svg",
        report_path,
        ROOT / "previews" / "compact_enclosure_overview_v0_7.png",
        ROOT / "previews" / "electronics_layout_v0_7.png",
        ROOT / "previews" / "assembly_effect_v0_7.png",
        ROOT / "previews" / "installed_effect_v0_7.png",
        ROOT / "previews" / "exploded_view_v0_7.png",
        ROOT / "previews" / "corner_fit_assembly_v0_7.png",
        ROOT / "previews" / "rear_coupon_hole_revision_v0_7_rev_b.png",
        ROOT / "previews" / "rear_openings_detail_v0_7.png",
        ROOT / "previews" / "rear_left_wall_flat_revision_v0_7_rev_f.png",
        ROOT / "previews" / "front_retainer_revision_v0_7_rev_f.png",
        ROOT / "previews" / "rear_button_labels_outside_v0_7.png",
        ROOT / "previews" / "rear_dfm_clearance_revision_v0_7_rev_e.png",
        ROOT / "README.md",
        ROOT / "ASSEMBLY_GUIDE.md",
    ]
    guide_previews = [
        ROOT / "previews" / "electronics_layout_v0_7.png",
        ROOT / "previews" / "exploded_view_v0_7.png",
        ROOT / "previews" / "rear_openings_detail_v0_7.png",
        ROOT / "previews" / "installed_effect_v0_7.png",
        ROOT / "previews" / "rear_dfm_clearance_revision_v0_7_rev_e.png",
    ]
    require(all(path.exists() for path in bundle), "delivery bundle contains a missing file")
    package_dir.mkdir(parents=True, exist_ok=True)
    for path in bundle:
        shutil.copy2(path, package_dir / path.name)
    package_preview_dir = package_dir / "previews"
    package_preview_dir.mkdir(parents=True, exist_ok=True)
    for path in guide_previews:
        shutil.copy2(path, package_preview_dir / path.name)
    with zipfile.ZipFile(package, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in bundle:
            archive.write(path, path.name)
        for path in guide_previews:
            archive.write(path, f"previews/{path.name}")
    with zipfile.ZipFile(package) as archive:
        require(archive.testzip() is None, "ZIP CRC failure")
        for filename in expected:
            require(filename in set(archive.namelist()), f"ZIP missing {filename}")
    report["zip_crc"] = "PASS"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    shutil.copy2(report_path, package_dir / report_path.name)
    with zipfile.ZipFile(package, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in bundle:
            archive.write(path, path.name)
        for path in guide_previews:
            archive.write(path, f"previews/{path.name}")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
