#!/usr/bin/env python3
"""Generate the 120 x 184 x 19 mm FridgeEInkDisplay V0.7 enclosure.

V0.7 keeps the V0.6 outline and electronics placement.  The current rear-cover
revision replaces the previous nine hard magnet bars with two 90 x 50 x 2 mm
and one 50 x 20 x 2 mm flexible ferrite/rubber permanent-magnet sheets.  The
two large sheets are rotated 90 degrees and touch inside one shared 100.6 x
90.6 mm lower pocket; the small sheet is vertical in the upper-right safety
strip.  The 0.4 mm outer skin is retained for PLA printing.  This layout avoids
the Wi-Fi antenna, BOOT/RESET openings, four case fasteners and the combined
Lipo Rider LED/SW1 opening without cutting any magnet.  Front
bezel Rev F keeps the equal-width top, bottom and left retainers and removes the
right retainer so the display can enter from the right without flexing the
glass.  Its two left inner corners are square, while the top and bottom inner
edges continue horizontally to the right outer arcs without a nose or step.
Rear Rev F restores the assembled-left straight wall to the full 16.6 mm
height and removes its inward ledge.  Only the restored 1.8 mm-high top band
is thinned to a printable 0.8 mm; the original lower wall remains 1.8 mm thick.
Rear Rev G adds a compact rounded access slot over the Lipo Rider Plus SW1
slider while preserving every existing opening, magnet pocket and fastener.
Rear Rev H joins the LED window and SW1 slot with a narrow 2.4 mm capsule
bridge.  The opening is one connected feature without expanding it into the
full 5.2 x 21.0 mm bounding rectangle.
Rear Rev I replaces that stepped/offset opening with one regular 5.2 x 21.0 mm
rounded rectangle (R1.0 mm), centred on the combined LED/SW1 bounding envelope.
"""

from __future__ import annotations

import importlib.util
import json
import math
from pathlib import Path
import shutil
import zipfile

from PIL import Image, ImageDraw
import trimesh


ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "output"
PREVIEWS = ROOT / "previews"
V07_BASE_FILE = ROOT / "_geometry_base_v0_7.py"


def load_v07_base_module():
    spec = importlib.util.spec_from_file_location("rfm_enclosure_v07_base", V07_BASE_FILE)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load V0.7 geometry base: {V07_BASE_FILE}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


v06 = load_v07_base_module()

P = dict(v06.P)
P.update(
    {
        "rear_depth": 16.6,
        "assembled_thickness": 19.0,
        "rear_skin": 1.4,
        "rear_inner_corner_radius": 6.2,
        "carrier_thickness": 1.4,
        # Keep the front locator equally inset from the 120 x 184 mm outline.
        # This makes the two exposed corner reference segments both 3.6 mm.
        "screen_locator_outer_width": 112.8,
        "screen_locator_outer_height": 176.8,
        # Rev F front retainer: keep the Rev D outer position and 2.9 mm rail
        # width.  The upper-left/lower-left INNER corners become exact 90-degree
        # corners; the four OUTER R4.4 arcs remain unchanged.  On the right,
        # the top/bottom inner edges continue naturally to the outer arcs.
        # There is no independent numeric clear-span constraint.
        "front_retainer_width": 2.9,
        "front_retainer_edge_inset": 3.6,
        # Rear inner wall is R6.2.  With 1.8 mm XY clearance, the matching
        # retainer corners are R4.4; their constant 2.9 mm wall gives R1.5.
        "front_retainer_outer_radius": 4.4,
        "front_retainer_inner_radius": 1.5,
        "front_retainer_left_inner_corner_radius": 0.0,
        "front_retainer_left_inner_corner_style": "square_90_degree",
        "front_retainer_to_rear_radial_clearance": 1.8,
        "front_retainer_top_bottom_edge_inset": 3.6,
        "front_retainer_right_end_style": "continuous_inner_edges_to_outer_arcs_no_step",
        "front_right_retainer_removed": True,
        "battery_recess_depth": 0.5,
        "battery_underlay_max": 0.2,
        "case_fastener_length": 14.0,
        # Rev E rear-only DFM relief.  The front screw post remains R2.6 mm,
        # while the rear-side internal relief grows to R3.3 mm and reaches
        # 0.6 mm into the screw tube.  A 0.5 mm x 45-degree mouth chamfer
        # absorbs PLA elephant foot and first-layer spread.
        "front_boss_relief_radial_clearance": 0.7,
        "rear_boss_relief_axial_depth_into_tube": 0.6,
        "rear_boss_relief_entry_chamfer": 0.5,
        # Keep the nominal R6.2 rear cavity unchanged below the opening.  Only
        # the first 1.2 mm at the open edge receives +0.4 mm radial relief,
        # followed by a 0.5 mm x 45-degree lead-in.  The outermost 0.3 mm of
        # that lead-in is the explicit elephant-foot/contact relief.
        "rear_corner_entry_relief_depth": 1.2,
        "rear_corner_entry_radial_relief": 0.4,
        "rear_corner_entry_chamfer": 0.5,
        "rear_corner_contact_relief": 0.3,
        "carrier_front_boss_relief_diameter": 5.8,
        "magnet_bar_length": 90.0,
        "magnet_bar_width": 50.0,
        "magnet_bar_thickness": 2.0,
        # 0.3 mm per side is intentional for PLA FDM fit variation.
        "magnet_bar_xy_clearance_per_side": 0.3,
        "magnet_bar_pocket_depth": 2.2,
        # Keep the flexible magnets fully enclosed while reducing the magnetic
        # air gap.  The user confirmed that the formal PLA rear cover remains
        # at 0.4 mm; thinner skins are intentionally not supported here.
        "magnet_bar_outer_skin": 0.4,
        "magnet_bar_boss_wall": 0.8,
        "magnet_bar_boss_corner_radius": 1.8,
        "magnet_coupon_width": 20.0,
        "magnet_coupon_height": 50.0,
        # Keep the confirmed 11.5 mm width.  Physical fitting requested another
        # 1.0 mm above and below the former 5.5 mm opening, so the new height is
        # 7.5 mm while its centre and horizontal position remain unchanged.
        "charge_cutout_width": 11.5,
        "charge_cutout_height": 7.5,
        # Physical trial showed the connector was partly hidden by the upper
        # wall.  Keep the opening size and XY centre, but lower it 3.0 mm.
        "charge_cutout_center_z": 7.0,
        "charge_cutout_vertical_drop": 3.0,
        # Rev F keeps the assembled-left opening edge level at the full rear
        # depth.  Only the 1.8 mm-high band that replaces the previous height
        # drop is two 0.4 mm extrusion lines thick.  The lower wall remains at
        # the original 1.8 mm thickness.  The 170 mm span includes the 168 mm
        # straight plus 1 mm of transition at each unchanged R8 outer corner.
        "rear_left_flat_span": 170.0,
        "rear_left_lower_wall_thickness": 1.8,
        "rear_left_restored_band_height": 1.8,
        "rear_left_restored_band_thickness": 0.8,
        "rear_left_edge_drop": 0.0,
        "rear_left_flat_y_min": -85.0,
        "rear_left_flat_y_max": 85.0,
        "rear_left_inward_ledge_removed": True,
        # One rear viewing slot covers the charge LED plus the four battery
        # gauge LEDs.  Coordinates come from Seeed's official Eagle board file.
        "lipo_indicator_window_width": 4.5,
        "lipo_indicator_window_height": 12.0,
        "lipo_indicator_window_corner_radius": 1.5,
        # Seeed's official Eagle board places SW1 at (28.575, 25.186) mm and
        # identifies its package as 6.7 x 2.7 x 3.2 mm.  After the board's
        # installed -90 degree rotation, the switch's long axis runs along Y.
        # A 3.8 x 7.0 mm slot exposes the complete slider travel with only
        # 0.55 mm nominal side clearance and 0.15 mm end clearance.  It is
        # intentionally kept small enough to avoid exposing the surrounding
        # Lipo Rider circuitry while remaining printable with a 0.4 mm nozzle.
        "lipo_switch_window_width": 3.8,
        "lipo_switch_window_height": 7.0,
        "lipo_switch_window_corner_radius": 1.0,
        "lipo_switch_package_width": 2.7,
        "lipo_switch_package_length": 6.7,
        # Rev I: user-confirmed single regular opening.  These dimensions are
        # the rounded-up envelope of the existing LED and SW1 access regions.
        "lipo_regular_opening_width": 5.2,
        "lipo_regular_opening_height": 21.0,
        "lipo_regular_opening_corner_radius": 1.0,
        "lipo_regular_opening_enabled": True,
        # Rear legends are read from the physical bottom/outside of the cover.
        # Pre-mirror model-space X so BOOT / RESET read normally after the
        # cover is turned over.  The previous inherited 0.42 mm bitmap stroke
        # was marginal for a 0.4 mm nozzle, so use a wider/deeper engraving.
        "rear_label_pixel": 0.50,
        "rear_label_gap": 0.40,
        "rear_label_overlap": 0.08,
        "rear_label_depth": 0.60,
        "rear_label_pre_mirrored_for_bottom_view": True,
        # Outside/rear view with the USB-C edge at the top: place each legend
        # directly above its matching access hole.  Keep the hole coordinates
        # unchanged; only the engraved text moves by +6 mm in model-space Y.
        "rear_label_vertical_offset": 6.0,
        "rear_label_position": "above_button_hole",
    }
)
# Remove inherited V0.6 round-magnet parameters from the V0.7 manifest so the
# delivery package exposes only the active block-magnet system.
for legacy_key in ("magnet_diameter", "magnet_depth", "magnet_outer_skin"):
    P.pop(legacy_key, None)

# Patch the reused V0.6 helpers so their geometry follows the V0.7 parameters.
v06.P = P
v06.OUTPUT = OUTPUT
v06.PREVIEWS = PREVIEWS

CASE_FASTENERS = v06.CASE_FASTENERS
ESP_HOLES = v06.ESP_HOLES
LIPO_HOLES = v06.LIPO_HOLES
LIPO_USB_C_FACE = v06.LIPO_USB_C_FACE
BOARD_BOOT = v06.BOARD_BOOT
BOARD_RESET = v06.BOARD_RESET
REAR_BOOT = v06.REAR_BOOT
REAR_RESET = v06.REAR_RESET
REAR_BOOT_LABEL = (REAR_BOOT[0], REAR_BOOT[1] + P["rear_label_vertical_offset"])
REAR_RESET_LABEL = (REAR_RESET[0], REAR_RESET[1] + P["rear_label_vertical_offset"])

# Seeed official Eagle coordinates for D2, D3, D4, D5 and D7 (all LED-0402).
# lipo_to_carrier() rotates them into this enclosure's assembled XY frame.
LIPO_LED_POINTS_EAGLE = [
    (13.335, 26.202),
    (14.986, 26.202),
    (18.288, 26.202),
    (16.637, 26.202),
    (22.271, 26.1385),
]
LIPO_LED_POINTS_ASSEMBLED = [v06.lipo_to_carrier(x, y) for x, y in LIPO_LED_POINTS_EAGLE]
LIPO_INDICATOR_WINDOW_ASSEMBLED = (
    sum(x for x, _ in LIPO_LED_POINTS_ASSEMBLED) / len(LIPO_LED_POINTS_ASSEMBLED),
    sum(y for _, y in LIPO_LED_POINTS_ASSEMBLED) / len(LIPO_LED_POINTS_ASSEMBLED),
)
# Rear-cover STL is viewed from the rear, so its model-space X is mirrored.
LIPO_INDICATOR_WINDOW_MODEL = (
    -LIPO_INDICATOR_WINDOW_ASSEMBLED[0],
    LIPO_INDICATOR_WINDOW_ASSEMBLED[1],
)

# Seeed official Eagle coordinate for SW1.  lipo_to_carrier() rotates the
# board into the enclosure; the rear-cover model then mirrors X because it is
# viewed from the physical rear/outside.
LIPO_SWITCH_POINT_EAGLE = (28.575, 25.186)
LIPO_SWITCH_POINT_ASSEMBLED = v06.lipo_to_carrier(*LIPO_SWITCH_POINT_EAGLE)
LIPO_SWITCH_WINDOW_MODEL = (
    -LIPO_SWITCH_POINT_ASSEMBLED[0],
    LIPO_SWITCH_POINT_ASSEMBLED[1],
)

# Rev I regular opening is centred on the exact union envelope of the original
# LED window and SW1 slot.  Its agreed 5.2 x 21.0 mm size rounds that envelope
# outward, preserving coverage despite the approximately 1 mm X offset.
_lipo_union_x_min = min(
    LIPO_INDICATOR_WINDOW_MODEL[0] - P["lipo_indicator_window_width"] / 2.0,
    LIPO_SWITCH_WINDOW_MODEL[0] - P["lipo_switch_window_width"] / 2.0,
)
_lipo_union_x_max = max(
    LIPO_INDICATOR_WINDOW_MODEL[0] + P["lipo_indicator_window_width"] / 2.0,
    LIPO_SWITCH_WINDOW_MODEL[0] + P["lipo_switch_window_width"] / 2.0,
)
_lipo_union_y_min = min(
    LIPO_INDICATOR_WINDOW_MODEL[1] - P["lipo_indicator_window_height"] / 2.0,
    LIPO_SWITCH_WINDOW_MODEL[1] - P["lipo_switch_window_height"] / 2.0,
)
_lipo_union_y_max = max(
    LIPO_INDICATOR_WINDOW_MODEL[1] + P["lipo_indicator_window_height"] / 2.0,
    LIPO_SWITCH_WINDOW_MODEL[1] + P["lipo_switch_window_height"] / 2.0,
)
LIPO_REGULAR_OPENING_MODEL = (
    (_lipo_union_x_min + _lipo_union_x_max) / 2.0,
    (_lipo_union_y_min + _lipo_union_y_max) / 2.0,
)
LIPO_REGULAR_OPENING_ASSEMBLED = (
    -LIPO_REGULAR_OPENING_MODEL[0],
    LIPO_REGULAR_OPENING_MODEL[1],
)

# Magnet tuple: (assembled centre X, centre Y, size X, size Y).
# M1/M2 are the two 90 x 50 mm sheets rotated 90 degrees.  Their nominal edges
# touch at X=0, while the 0.3 mm-per-side pocket clearances overlap to form one
# shared 100.6 x 90.6 mm cavity with no centre divider.  Y=-36.5 mm is the
# lowest position that retains 2.1 mm nominal boss-to-lower-fastener clearance
# and 1.5 mm to the BOOT/RESET counterbores.  M3 is the 50 x 20 mm sheet,
# vertical in the upper-right safety strip.  No sheet enters the antenna or
# Lipo LED/SW1 opening footprints, and no magnet needs to be cut.
MAGNET_BARS_ASSEMBLED = [
    (-25.0, -36.5, 50.0, 90.0),
    (25.0, -36.5, 50.0, 90.0),
    (46.0, 55.0, 20.0, 50.0),
]
# Rear-cover STL is viewed from the rear, hence the X mirror.
MAGNET_BARS_MODEL = [(-x, y, width, height) for x, y, width, height in MAGNET_BARS_ASSEMBLED]


def rear_label_cutters(text: str, centre_x: float, centre_y: float):
    """Engrave text that reads normally from the rear cover's outside.

    The rear cover is modelled cavity-up.  Looking at its physical outside
    mirrors model-space X, so the bitmap is deliberately pre-mirrored here.
    Y remains unchanged so the USB-C edge is still the top edge.
    """
    pixel = P["rear_label_pixel"]
    gap = P["rear_label_gap"]
    overlap = P["rear_label_overlap"]
    depth = P["rear_label_depth"]
    widths = [len(v06.BITMAP_FONT_5X7[ch][0]) * pixel for ch in text]
    total = sum(widths) + gap * (len(text) - 1)
    logical_cursor = -total / 2.0
    cutters = []
    for ch, char_width in zip(text, widths):
        bitmap = v06.BITMAP_FONT_5X7[ch]
        for row, line in enumerate(bitmap):
            for column, value in enumerate(line):
                if value != "1":
                    continue
                logical_x = logical_cursor + column * pixel + pixel / 2.0
                model_x = centre_x - logical_x
                model_y = centre_y + (3 - row) * pixel
                cutters.append(
                    cuboid(
                        (pixel + overlap, pixel + overlap, depth + 0.3),
                        (model_x, model_y, depth / 2.0),
                    )
                )
        logical_cursor += char_width + gap
    return cutters


def cuboid(size, center):
    return v06.cuboid(size, center)


def capsule_bridge_prism(start, end, width, depth, z0=-0.2):
    """Create a narrow rounded bridge between two rear-skin openings."""
    x0, y0 = start
    x1, y1 = end
    dx = x1 - x0
    dy = y1 - y0
    length = math.hypot(dx, dy)
    angle = math.atan2(dy, dx) - math.pi / 2.0
    bridge = trimesh.creation.box((width, length, depth))
    bridge.apply_transform(
        trimesh.transformations.rotation_matrix(angle, (0.0, 0.0, 1.0))
    )
    bridge.apply_translation(
        ((x0 + x1) / 2.0, (y0 + y1) / 2.0, z0 + depth / 2.0)
    )
    radius = width / 2.0
    end_caps = [
        cylinder(radius, depth, (x0, y0, z0 + depth / 2.0), sections=48),
        cylinder(radius, depth, (x1, y1, z0 + depth / 2.0), sections=48),
    ]
    return union([bridge, *end_caps])


def cylinder(radius, height, center, sections=48):
    return v06.cylinder(radius, height, center, sections=sections)


def conical_frustum(radius_bottom, radius_top, height, center_x, center_y, z0, sections=64):
    """Create a solid axial frustum whose lower and upper radii may differ."""
    profile = [
        [0.0, z0],
        [radius_bottom, z0],
        [radius_top, z0 + height],
        [0.0, z0 + height],
        [0.0, z0],
    ]
    mesh = trimesh.creation.revolve(profile, sections=sections)
    mesh.apply_translation((center_x, center_y, 0.0))
    return mesh


def union(meshes):
    return v06.union(meshes)


def difference(base, cutters):
    return v06.difference(base, cutters)


def rounded_rect_prism(width, height, depth, center_x, center_y, z0=0.0, radius=1.8):
    mesh = v06.rounded_prism(width, height, min(radius, width / 2.0, height / 2.0), depth, z0)
    mesh.apply_translation((center_x, center_y, 0.0))
    return mesh


def build_front_bezel():
    face = v06.rounded_prism(
        P["case_width"], P["case_height"], P["corner_radius"], P["front_face_thickness"]
    )
    window = v06.rounded_prism(
        P["screen_window_width"], P["screen_window_height"], 2.0,
        P["front_face_thickness"] + 1.0, -0.5,
    )
    face = difference(face, [window])

    retainer_width = P["front_retainer_width"]
    retainer_depth = P["screen_locator_depth"]
    retainer_z0 = P["front_face_thickness"] - 0.2
    retainer_z = retainer_z0 + retainer_depth / 2.0
    outer_half_width = P["case_width"] / 2.0 - P["front_retainer_edge_inset"]
    outer_half_height = P["case_height"] / 2.0 - P["front_retainer_edge_inset"]
    retainer_outer_width = 2.0 * outer_half_width
    retainer_outer_height = 2.0 * outer_half_height
    retainer_inner_width = retainer_outer_width - 2.0 * retainer_width
    retainer_inner_height = retainer_outer_height - 2.0 * retainer_width

    # Start from the Rev D rounded ring so the outer R4.4 corners continue to
    # match the rear frame.  Two extra opening cutters remove only the rounded
    # residue at the upper-left/lower-left INNER corners, making those corners
    # exact 90-degree corners without changing the outer arcs or rail position.
    retainer = v06.rounded_ring(
        retainer_outer_width,
        retainer_outer_height,
        P["front_retainer_outer_radius"],
        retainer_inner_width,
        retainer_inner_height,
        P["front_retainer_inner_radius"],
        retainer_depth,
        retainer_z0,
    )
    inner_half_width = retainer_inner_width / 2.0
    inner_half_height = retainer_inner_height / 2.0
    left_inner_radius = P["front_retainer_inner_radius"]
    left_inner_square_cutters = [
        cuboid(
            (
                left_inner_radius,
                left_inner_radius,
                retainer_depth + 0.4,
            ),
            (
                -inner_half_width + left_inner_radius / 2.0,
                sy * (inner_half_height - left_inner_radius / 2.0),
                retainer_z,
            ),
        )
        for sy in (-1.0, 1.0)
    ]
    retainer = difference(retainer, left_inner_square_cutters)

    # Open the right side for the full natural height of the inner opening.
    # The cutter starts at the inner-arc tangent and reaches the existing
    # top/bottom straight inner edges.  Therefore each edge continues directly
    # to the outer R4.4 arc with no oval nose, tongue, land or height step.
    right_arc_tangent_x = outer_half_width - P["front_retainer_outer_radius"]
    right_opening_width = P["front_retainer_outer_radius"] + 1.0
    right_region_cutter = cuboid(
        (
            right_opening_width,
            retainer_inner_height,
            retainer_depth + 0.4,
        ),
        (
            right_arc_tangent_x + right_opening_width / 2.0,
            0.0,
            retainer_z,
        ),
    )
    retainer = difference(retainer, [right_region_cutter])

    boss_bottom = P["front_face_thickness"] - 0.2
    boss_top = P["front_feature_depth"]
    bosses = [
        cylinder(
            P["case_fastener_post_diameter"] / 2.0,
            boss_top - boss_bottom,
            (x, y, (boss_bottom + boss_top) / 2.0),
            sections=48,
        )
        for x, y in CASE_FASTENERS
    ]
    body = union([face, retainer, *bosses])
    pilots = [
        cylinder(
            P["case_fastener_pilot"] / 2.0,
            3.3,
            (x, y, 4.45),
            sections=40,
        )
        for x, y in CASE_FASTENERS
    ]
    return difference(body, pilots)


def build_carrier():
    base = v06.rounded_prism(
        P["carrier_width"], P["carrier_height"], 6.0, P["carrier_thickness"]
    )
    battery_guides = v06.short_guides(
        P["battery_center_x"], P["battery_center_y"],
        P["battery_width"], P["battery_height"],
    )
    despi_guides = v06.short_guides(
        P["despi_center_x"], P["despi_center_y"],
        P["despi_width"], P["despi_height"],
    )
    body = union(
        [
            base,
            *battery_guides,
            *despi_guides,
            *v06.mount_posts(ESP_HOLES, P["esp_post_diameter"], P["esp_post_top"]),
            *v06.mount_posts(LIPO_HOLES, P["lipo_post_diameter"], P["lipo_post_top"]),
        ]
    )
    cutters = [
        # Leave a 0.9 mm local carrier floor below the battery.
        cuboid(
            (P["battery_width"], P["battery_height"], P["battery_recess_depth"] + 0.2),
            (
                P["battery_center_x"],
                P["battery_center_y"],
                P["carrier_thickness"] - P["battery_recess_depth"] / 2.0 + 0.1,
            ),
        ),
        cuboid((8.0, 38.0, 4.0), (56.0, P["despi_center_y"], 0.8)),
    ]
    for x, y in CASE_FASTENERS:
        cutters.append(
            cylinder(
                P["carrier_front_boss_relief_diameter"] / 2.0,
                4.0,
                (x, y, 1.0),
                sections=64,
            )
        )
    cutters.extend(v06.pilot_cutters(ESP_HOLES, P["esp_pilot"], P["esp_pilot_depth"], P["esp_post_top"]))
    cutters.extend(v06.pilot_cutters(LIPO_HOLES, P["lipo_pilot"], 2.3, P["lipo_post_top"]))
    for x, y, width, height in [
        (-8.0, 4.0, 10.0, 3.0),
        (-8.0, 24.0, 10.0, 3.0),
        (25.0, 30.0, 10.0, 3.0),
        (42.0, -18.0, 10.0, 3.0),
    ]:
        cutters.append(cuboid((width, height, 4.0), (x, y, 0.8)))
    return difference(body, cutters)


def magnet_bar_total_height() -> float:
    return P["magnet_bar_outer_skin"] + P["magnet_bar_pocket_depth"]


def magnet_bar_pocket_size(width: float, height: float) -> tuple[float, float]:
    clearance = 2.0 * P["magnet_bar_xy_clearance_per_side"]
    return width + clearance, height + clearance


def magnet_bar_boss_size(width: float, height: float) -> tuple[float, float]:
    pocket_width, pocket_height = magnet_bar_pocket_size(width, height)
    wall = 2.0 * P["magnet_bar_boss_wall"]
    return pocket_width + wall, pocket_height + wall


def build_rear_cover():
    depth = P["rear_depth"]
    shell = v06.rounded_prism(P["case_width"], P["case_height"], P["corner_radius"], depth)
    cavity = v06.rounded_prism(
        P["rear_inner_width"], P["rear_inner_height"], P["rear_inner_corner_radius"],
        depth - P["rear_skin"] + 1.0, P["rear_skin"],
    )
    shell = difference(shell, [cavity])

    ledge = v06.rounded_ring(
        P["rear_inner_width"], P["rear_inner_height"], P["rear_inner_corner_radius"],
        P["carrier_width"] - 2.6, P["carrier_height"] - 2.6, 5.0,
        1.6, depth - 1.6,
    )
    tube_bottom = P["rear_skin"] - 0.2
    tube_top = P["assembled_thickness"] - P["front_feature_depth"]
    tubes = [
        cylinder(
            P["case_fastener_tube_diameter"] / 2.0,
            tube_top - tube_bottom,
            (x, y, (tube_bottom + tube_top) / 2.0),
            sections=48,
        )
        for x, y in CASE_FASTENERS
    ]
    local_bosses = []
    boss_height = magnet_bar_total_height()
    for x, y, width, height in MAGNET_BARS_MODEL:
        boss_width, boss_length = magnet_bar_boss_size(width, height)
        local_bosses.append(
            rounded_rect_prism(
                boss_width,
                boss_length,
                boss_height,
                x,
                y,
                radius=P["magnet_bar_boss_corner_radius"],
            )
        )
    body = union([shell, ledge, *tubes, *local_bosses])

    cutters = []
    # Rev E: the nominal rear cavity remains 116.4 x 180.4, R6.2 below this
    # region.  Only the first 1.2 mm at the opening is locally opened around
    # all four corner centres, with a 0.5 mm x 45-degree lead-in at the mouth.
    corner_base_radius = P["rear_inner_corner_radius"]
    corner_relief_radius = corner_base_radius + P["rear_corner_entry_radial_relief"]
    corner_relief_depth = P["rear_corner_entry_relief_depth"]
    corner_chamfer = P["rear_corner_entry_chamfer"]
    corner_centres = [
        (sx * (P["rear_inner_width"] / 2.0 - corner_base_radius),
         sy * (P["rear_inner_height"] / 2.0 - corner_base_radius))
        for sx in (-1.0, 1.0)
        for sy in (-1.0, 1.0)
    ]
    corner_relief_z0 = depth - corner_relief_depth
    corner_chamfer_z0 = depth - corner_chamfer
    for x, y in corner_centres:
        cutters.append(
            cylinder(
                corner_relief_radius,
                corner_relief_depth + 0.1,
                (x, y, corner_relief_z0 + (corner_relief_depth + 0.1) / 2.0),
                sections=72,
            )
        )
        cutters.append(
            conical_frustum(
                corner_relief_radius,
                corner_relief_radius + corner_chamfer,
                corner_chamfer + 0.1,
                x,
                y,
                corner_chamfer_z0,
                sections=72,
            )
        )
    # Rev F assembled-left edge: keep the top at the full 16.6 mm height and
    # remove the inward ledge over Y=-85..+85.  Only the restored top band is
    # reduced to 0.8 mm (two 0.4 mm extrusion lines).  The original lower wall
    # remains 1.8 mm thick, so the cutter starts at Z=16.6-1.8=14.8 mm.
    left_ledge_inner_x = -(P["carrier_width"] - 2.6) / 2.0
    left_thinning_x0 = (
        -P["case_width"] / 2.0 + P["rear_left_restored_band_thickness"]
    )
    left_thinning_x1 = left_ledge_inner_x + 0.5
    left_thinning_z0 = depth - P["rear_left_restored_band_height"]
    left_thinning_height = P["rear_left_restored_band_height"] + 0.4
    cutters.append(
        cuboid(
            (
                left_thinning_x1 - left_thinning_x0,
                P["rear_left_flat_span"],
                left_thinning_height,
            ),
            (
                (left_thinning_x0 + left_thinning_x1) / 2.0,
                0.0,
                left_thinning_z0 + left_thinning_height / 2.0,
            ),
        )
    )
    for x, y in CASE_FASTENERS:
        cutters.append(cylinder(P["case_fastener_clearance"] / 2.0, depth + 1.0, (x, y, depth / 2.0), sections=40))
        cutters.append(
            cylinder(
                P["case_fastener_counterbore_diameter"] / 2.0,
                P["case_fastener_counterbore_depth"] + 0.2,
                (x, y, P["case_fastener_counterbore_depth"] / 2.0),
                sections=48,
            )
        )
        relief_radius = (
            P["case_fastener_post_diameter"] / 2.0
            + P["front_boss_relief_radial_clearance"]
        )
        relief_bottom = tube_top - P["rear_boss_relief_axial_depth_into_tube"]
        relief_top = depth + 0.1
        cutters.append(
            cylinder(
                relief_radius,
                relief_top - relief_bottom,
                (x, y, (relief_bottom + relief_top) / 2.0),
                sections=64,
            )
        )
        chamfer = P["rear_boss_relief_entry_chamfer"]
        cutters.append(
            conical_frustum(
                relief_radius,
                relief_radius + chamfer,
                chamfer + 0.1,
                x,
                y,
                depth - chamfer,
                sections=72,
            )
        )
    pocket_depth = P["magnet_bar_pocket_depth"]
    outer_skin = P["magnet_bar_outer_skin"]
    for x, y, width, height in MAGNET_BARS_MODEL:
        pocket_width, pocket_length = magnet_bar_pocket_size(width, height)
        cutters.append(
            cuboid(
                (pocket_width, pocket_length, pocket_depth + 0.2),
                (x, y, outer_skin + (pocket_depth + 0.2) / 2.0),
            )
        )
    cutters.append(
        cuboid(
            (P["charge_cutout_width"], 6.0, P["charge_cutout_height"]),
            (P["charge_cutout_center_x"], P["charge_cutout_center_y"], P["charge_cutout_center_z"]),
        )
    )
    regular_x, regular_y = LIPO_REGULAR_OPENING_MODEL
    cutters.append(
        rounded_rect_prism(
            P["lipo_regular_opening_width"],
            P["lipo_regular_opening_height"],
            P["rear_skin"] + 0.4,
            regular_x,
            regular_y,
            z0=-0.2,
            radius=P["lipo_regular_opening_corner_radius"],
        )
    )
    for x, y in (REAR_BOOT, REAR_RESET):
        cutters.append(cylinder(P["button_access_diameter"] / 2.0, 6.0, (x, y, 2.5), sections=48))
        cutters.append(
            cylinder(
                P["button_counterbore_diameter"] / 2.0,
                P["button_counterbore_depth"] + 0.2,
                (x, y, P["button_counterbore_depth"] / 2.0),
                sections=56,
            )
        )
    cutters.extend(rear_label_cutters("BOOT", *REAR_BOOT_LABEL))
    cutters.extend(rear_label_cutters("RESET", *REAR_RESET_LABEL))
    return difference(body, cutters)


def available_assembled_carrier_height() -> float:
    return P["assembled_thickness"] - P["rear_skin"] - 4.0


def available_height_above_carrier() -> float:
    return available_assembled_carrier_height() - P["carrier_thickness"]


def magnet_bar_local_height() -> float:
    return P["assembled_thickness"] - magnet_bar_total_height() - 4.0


def battery_stack_height() -> float:
    return (
        P["carrier_thickness"] - P["battery_recess_depth"]
        + P["battery_underlay_max"] + P["battery_thickness"]
    )


def build_height_gauge(opening_height: float):
    outer_height = opening_height + 4.0
    outer = cuboid((42.0, 20.0, outer_height), (0.0, 0.0, outer_height / 2.0))
    opening = cuboid((39.6, 22.0, opening_height), (1.2, 0.0, outer_height / 2.0))
    return difference(outer, [opening])


def build_magnet_bar_fit_coupon():
    """Low-cost coupon for checking 2 mm sheet thickness and 0.4 mm PLA skin."""
    pocket_width, pocket_height = magnet_bar_pocket_size(
        P["magnet_coupon_width"], P["magnet_coupon_height"]
    )
    coupon_width = pocket_width + 6.0
    coupon_height = pocket_height + 6.0
    total_height = magnet_bar_total_height()
    body = rounded_rect_prism(
        coupon_width, coupon_height, total_height, 0.0, 0.0, radius=2.0
    )
    cutter = cuboid(
        (pocket_width, pocket_height, P["magnet_bar_pocket_depth"] + 0.2),
        (
            0.0,
            0.0,
            P["magnet_bar_outer_skin"]
            + (P["magnet_bar_pocket_depth"] + 0.2) / 2.0,
        ),
    )
    return difference(body, [cutter])


OPENINGS_COUPON_BOUNDS = (-27.0, 12.0, 55.0, 92.0)
USB_C_COUPON_BOUNDS = (-10.0, 10.0, 84.0, 92.0)


def rear_openings_coupon(mesh):
    """Low-cost rear crop containing the USB-C and LED openings."""
    x0, x1, y0, y1 = OPENINGS_COUPON_BOUNDS
    cutter = cuboid(
        (x1 - x0, y1 - y0, P["rear_depth"] + 1.0),
        ((x0 + x1) / 2.0, (y0 + y1) / 2.0, P["rear_depth"] / 2.0),
    )
    result = v06.intersection([mesh, cutter])
    result.apply_translation(-result.bounds[0])
    return result


def rear_usb_c_opening_coupon(mesh):
    """Minimal top-wall crop for testing only the enlarged USB-C opening."""
    x0, x1, y0, y1 = USB_C_COUPON_BOUNDS
    cutter = cuboid(
        (x1 - x0, y1 - y0, P["rear_depth"] + 1.0),
        ((x0 + x1) / 2.0, (y0 + y1) / 2.0, P["rear_depth"] / 2.0),
    )
    result = v06.intersection([mesh, cutter])
    result.apply_translation(-result.bounds[0])
    return result


LEFT_WALL_COUPON_BOUNDS = (-60.0, -52.0, 78.0, 92.0)
BUTTON_LABEL_COUPON_BOUNDS = (25.0, 58.0, 11.0, 24.5)


def rear_left_wall_coupon(mesh):
    """Upper end of the stepped left wall and its corner transition."""
    x0, x1, y0, y1 = LEFT_WALL_COUPON_BOUNDS
    cutter = cuboid(
        (x1 - x0, y1 - y0, P["rear_depth"] + 1.0),
        ((x0 + x1) / 2.0, (y0 + y1) / 2.0, P["rear_depth"] / 2.0),
    )
    result = v06.intersection([mesh, cutter])
    result.apply_translation(-result.bounds[0])
    return result


def rear_button_label_coupon(mesh):
    """Crop only the engraved rear skin, excluding the restored right ledge."""
    x0, x1, y0, y1 = BUTTON_LABEL_COUPON_BOUNDS
    cutter = cuboid(
        (x1 - x0, y1 - y0, P["rear_skin"] + 0.1),
        ((x0 + x1) / 2.0, (y0 + y1) / 2.0, P["rear_skin"] / 2.0),
    )
    result = v06.intersection([mesh, cutter])
    result.apply_translation(-result.bounds[0])
    return result


COUPON_BOUNDS_FRONT = (25.0, 60.0, 55.0, 92.0)
COUPON_BOUNDS_FRONT_LEFT = (-60.0, -25.0, 55.0, 92.0)
COUPON_BOUNDS_REAR_REV_B = (-60.0, -25.0, 55.0, 92.0)


def cropped_coupon(mesh, bounds):
    """Crop a watertight low-cost coupon and move it to the print origin."""
    x0, x1, y0, y1 = bounds
    cutter = cuboid((x1 - x0, y1 - y0, 30.0), ((x0 + x1) / 2.0, (y0 + y1) / 2.0, 10.0))
    result = v06.intersection([mesh, cutter])
    result.apply_translation(-result.bounds[0])
    return result


def corner_coupon(mesh, rear_rev_b=False):
    """Extract a corner coupon in the orientation in which it is printed.

    Front and carrier use the model-space upper-right corner.  Rear Rev B uses
    the model-space upper-left corner so its raw STL fastener hole is on the
    opposite side.  Turning the rear coupon cavity-down mirrors local X and
    brings the three fastener axes back into alignment.
    """
    bounds = COUPON_BOUNDS_REAR_REV_B if rear_rev_b else COUPON_BOUNDS_FRONT
    return cropped_coupon(mesh, bounds)


def component_rectangles():
    esp = (
        P["esp_center_x"] - P["esp_width"] / 2.0,
        P["esp_center_x"] + P["esp_width"] / 2.0,
        P["esp_center_y"] - P["esp_height"] / 2.0,
        P["esp_center_y"] + P["esp_height"] / 2.0,
    )
    return {
        "battery": (
            P["battery_center_x"] - P["battery_width"] / 2.0,
            P["battery_center_x"] + P["battery_width"] / 2.0,
            P["battery_center_y"] - P["battery_height"] / 2.0,
            P["battery_center_y"] + P["battery_height"] / 2.0,
        ),
        "esp32_board": esp,
        "esp32_antenna": (esp[0], esp[1], esp[3] - 15.0, esp[3]),
        "despi_c02": (
            P["despi_center_x"] - P["despi_width"] / 2.0,
            P["despi_center_x"] + P["despi_width"] / 2.0,
            P["despi_center_y"] - P["despi_height"] / 2.0,
            P["despi_center_y"] + P["despi_height"] / 2.0,
        ),
        "lipo_rider": (
            P["lipo_center_x"] - P["lipo_width"] / 2.0,
            P["lipo_center_x"] + P["lipo_width"] / 2.0,
            P["lipo_center_y"] - P["lipo_height"] / 2.0,
            P["lipo_center_y"] + P["lipo_height"] / 2.0,
        ),
    }


def point_to_rect(point, rect):
    x, y = point
    x0, x1, y0, y1 = rect
    dx = max(x0 - x, 0.0, x - x1)
    dy = max(y0 - y, 0.0, y - y1)
    return math.hypot(dx, dy)


def rect_to_rect(left, right):
    lx0, lx1, ly0, ly1 = left
    rx0, rx1, ry0, ry1 = right
    dx = max(lx0 - rx1, rx0 - lx1, 0.0)
    dy = max(ly0 - ry1, ry0 - ly1, 0.0)
    return math.hypot(dx, dy)


def magnet_bar_rect(bar, boss=False):
    x, y, width, height = bar
    margin = P["magnet_bar_xy_clearance_per_side"]
    if boss:
        margin += P["magnet_bar_boss_wall"]
    return (
        x - width / 2.0 - margin,
        x + width / 2.0 + margin,
        y - height / 2.0 - margin,
        y + height / 2.0 + margin,
    )


def magnet_clearance_report():
    rects = component_rectangles()
    result = {}
    for name, component in rects.items():
        if name == "battery":
            continue
        result[f"magnet_to_{name}"] = round(
            min(
                rect_to_rect(magnet_bar_rect(bar, boss=False), component)
                for bar in MAGNET_BARS_ASSEMBLED
            ),
            3,
        )
        result[f"boss_to_{name}"] = round(
            min(
                rect_to_rect(magnet_bar_rect(bar, boss=True), component)
                for bar in MAGNET_BARS_ASSEMBLED
            ),
            3,
        )
    tube_radius = P["case_fastener_tube_diameter"] / 2.0
    result["boss_to_fastener_tube"] = round(
        min(
            point_to_rect(fastener, magnet_bar_rect(bar, boss=True)) - tube_radius
            for bar in MAGNET_BARS_ASSEMBLED
            for fastener in CASE_FASTENERS
        ),
        3,
    )
    button_counterbore_radius = P["button_counterbore_diameter"] / 2.0
    result["boss_to_button_counterbore"] = round(
        min(
            point_to_rect(button, magnet_bar_rect(bar, boss=True))
            - button_counterbore_radius
            for bar in MAGNET_BARS_ASSEMBLED
            for button in (BOARD_BOOT, BOARD_RESET)
        ),
        3,
    )
    result["boss_to_boss"] = round(
        min(
            rect_to_rect(magnet_bar_rect(a, boss=True), magnet_bar_rect(b, boss=True))
            for index, a in enumerate(MAGNET_BARS_ASSEMBLED)
            for b in MAGNET_BARS_ASSEMBLED[index + 1 :]
        ),
        3,
    )
    result["nominal_face_area_total_mm2"] = round(
        sum(width * height for _, _, width, height in MAGNET_BARS_ASSEMBLED), 3
    )
    return result


def draw_overview(path: Path):
    image = Image.new("RGB", (1800, 1250), "#f3f1eb")
    draw = ImageDraw.Draw(image)
    title = v06.load_font(46)
    subtitle = v06.load_font(26)
    label = v06.load_font(22)
    draw.text((55, 35), "V0.7 轻薄封闭外壳设计", fill="#17352b", font=title)
    draw.text((58, 95), "120 × 184 × 19 mm｜2片90×50 + 1片50×20软磁片｜前框 Rev F 三边定位", fill="#52665f", font=subtitle)
    panels = [(55, 160, 560, 1050), (625, 160, 1130, 1050), (1195, 160, 1745, 1050)]
    for panel in panels:
        draw.rounded_rectangle(panel, radius=32, fill="#ffffff", outline="#d8ddd9", width=3)

    scale = min(425 / P["case_width"], 780 / P["case_height"])
    outer_w, outer_h = P["case_width"] * scale, P["case_height"] * scale
    for index, heading in enumerate(("正面", "背面")):
        x0, y0, x1, y1 = panels[index]
        cx, cy = (x0 + x1) / 2.0, (y0 + y1) / 2.0 + 15
        draw.rounded_rectangle((cx - outer_w / 2, cy - outer_h / 2, cx + outer_w / 2, cy + outer_h / 2), radius=28, fill="#f2f4f0", outline="#1e3b31", width=5)
        if index == 0:
            window_w, window_h = P["screen_window_width"] * scale, P["screen_window_height"] * scale
            draw.rounded_rectangle((cx-window_w/2, cy-window_h/2, cx+window_w/2, cy+window_h/2), radius=10, fill="#e7e3d8", outline="#73766f", width=3)
        else:
            for x, y in CASE_FASTENERS:
                px, py = cx - x * scale, cy - y * scale
                draw.ellipse((px-8, py-8, px+8, py+8), fill="#c9ceca", outline="#5f6862", width=2)
        draw.text((x0 + 25, y0 + 20), heading, fill="#17352b", font=subtitle)

    x0, y0, x1, y1 = panels[2]
    draw.text((x0 + 25, y0 + 20), "厚度堆叠", fill="#17352b", font=subtitle)
    layers = [
        ("前框外观面", 2.4, "#d5e5dc"),
        ("屏幕 / 内嵌托板区", 4.0, "#e9d5b5"),
        ("器件有效空间", 9.6, "#dbe7f0"),
        ("后盖基础皮层", 1.4, "#c7d1cc"),
        ("结构嵌套余量", 1.6, "#e7e3d8"),
    ]
    left, right, y = x0 + 65, x1 - 65, y0 + 230
    for text_value, value, colour in layers:
        height = max(35, value * 28)
        draw.rectangle((left, y, right, y + height), fill=colour, outline="#66736d", width=2)
        draw.text((left + 15, y + height / 2 - 12), f"{text_value}  {value:.1f} mm", fill="#17352b", font=label)
        y += height
    draw.text((left, y + 28), "整机目标：19.0 mm", fill="#a33b34", font=subtitle)
    draw.rounded_rectangle((55, 1080, 1745, 1200), radius=24, fill="#e9f3ed", outline="#7ca08f", width=3)
    draw.text((85, 1105), "M1-M2：90×50×2 mm；M3：50×20×2 mm；均为橡胶软磁片。", fill="#17352b", font=subtitle)
    draw.text((85, 1150), "下部两片左右贴合；外侧 PLA 0.4 mm；必须先打印软磁片厚度检具。", fill="#52665f", font=label)
    image.save(path)


def draw_rear_dfm_revision(path: Path):
    """Dimensioned Rev E assembly-clearance summary for physical review."""
    image = Image.new("RGB", (1700, 980), "#f3f1eb")
    draw = ImageDraw.Draw(image)
    title = v06.load_font(44)
    heading = v06.load_font(30)
    text_font = v06.load_font(24)
    small = v06.load_font(20)
    draw.text((55, 35), "V0.7 后盖 Rev E｜空壳装配避让", fill="#17352b", font=title)
    draw.text(
        (58, 95),
        "只改后盖内侧装配避让；外形、前框、中托、孔中心与所有外部开口保持不变",
        fill="#52665f",
        font=text_font,
    )

    panels = [(55, 160, 815, 880), (875, 160, 1645, 880)]
    for panel in panels:
        draw.rounded_rectangle(panel, radius=28, fill="#ffffff", outline="#d8ddd9", width=3)

    # Left: fastener tube axial section.
    draw.text((95, 195), "1. 四个螺丝柱让位", fill="#17352b", font=heading)
    cx = 420
    rear_top = 330
    scale = 70
    tube_outer = P["case_fastener_tube_diameter"] / 2.0 * scale
    old_relief = P["case_fastener_post_diameter"] / 2.0 + 0.3
    new_relief = P["case_fastener_post_diameter"] / 2.0 + P["front_boss_relief_radial_clearance"]
    tube_bottom_y = 720
    draw.rectangle((cx-tube_outer, rear_top, cx+tube_outer, tube_bottom_y), fill="#ccd8d3", outline="#29483e", width=3)
    new_half = new_relief * scale
    axial_px = P["rear_boss_relief_axial_depth_into_tube"] * 150
    draw.rectangle((cx-new_half, rear_top-2, cx+new_half, rear_top+axial_px), fill="#ffffff")
    chamfer_px = P["rear_boss_relief_entry_chamfer"] * scale
    draw.polygon(
        [(cx-new_half-chamfer_px, rear_top), (cx+new_half+chamfer_px, rear_top),
         (cx+new_half, rear_top+35), (cx-new_half, rear_top+35)],
        fill="#ffffff",
    )
    draw.line((cx-tube_outer, rear_top, cx-new_half-chamfer_px, rear_top), fill="#29483e", width=3)
    draw.line((cx+new_half+chamfer_px, rear_top, cx+tube_outer, rear_top), fill="#29483e", width=3)
    draw.line((cx-new_half, rear_top+axial_px, cx-new_half, tube_bottom_y), fill="#29483e", width=3)
    draw.line((cx+new_half, rear_top+axial_px, cx+new_half, tube_bottom_y), fill="#29483e", width=3)
    draw.line((cx-new_half, rear_top+axial_px, cx+new_half, rear_top+axial_px), fill="#29483e", width=3)
    draw.text((110, 765), f"旧：Ø{2*old_relief:.1f} mm（径向 0.3 mm）", fill="#8b5d47", font=small)
    draw.text((110, 805), f"新：Ø{2*new_relief:.1f} mm（径向 0.7 mm）", fill="#1c6b50", font=small)
    draw.text((110, 845), "向螺丝管内 0.6 mm；入口 0.5 mm × 45°", fill="#1c6b50", font=small)

    # Right: plan/section explanation of the local corner entry relief.
    draw.text((915, 195), "2. 四个内腔角入口", fill="#17352b", font=heading)
    ccx, ccy = 1260, 505
    rr = 235
    base_r = P["rear_inner_corner_radius"]
    entry_r = base_r + P["rear_corner_entry_radial_relief"]
    mouth_r = entry_r + P["rear_corner_entry_chamfer"]
    draw.arc((ccx-rr, ccy-rr, ccx+rr, ccy+rr), 180, 270, fill="#8b5d47", width=7)
    draw.arc((ccx-rr-16, ccy-rr-16, ccx+rr+16, ccy+rr+16), 180, 270, fill="#1c6b50", width=7)
    draw.arc((ccx-rr-36, ccy-rr-36, ccx+rr+36, ccy+rr+36), 180, 270, fill="#2a8a68", width=4)
    draw.line((ccx-rr-36, ccy, ccx-rr-36, ccy+160), fill="#2a8a68", width=4)
    draw.line((ccx, ccy-rr-36, ccx+160, ccy-rr-36), fill="#2a8a68", width=4)
    draw.text((920, 690), f"基础内腔：R{base_r:.1f} mm（入口以下不变）", fill="#8b5d47", font=small)
    draw.text((920, 735), f"开口前 1.2 mm：R{entry_r:.1f} mm（+0.4 mm）", fill="#1c6b50", font=small)
    draw.text((920, 780), f"最外口：0.5 mm × 45°，最大 R{mouth_r:.1f} mm", fill="#2a8a68", font=small)
    draw.text((920, 825), "包含约 0.3 mm 象脚/接触避让", fill="#2a8a68", font=small)
    image.save(path)


def draw_layout(path: Path):
    width, height = 1250, 1900
    margin = 100
    scale = min((width - 2 * margin) / P["case_width"], 1500 / P["case_height"])
    image = Image.new("RGB", (width, height), "#f4f2ec")
    draw = ImageDraw.Draw(image)
    title, label, small = v06.load_font(40), v06.load_font(22), v06.load_font(18)
    cx, cy = width / 2, 880

    def point(x, y):
        return cx + x * scale, cy - y * scale

    def rect(cx0, cy0, w, h, fill, outline, text_value):
        x0, y0 = point(cx0 - w / 2, cy0 + h / 2)
        x1, y1 = point(cx0 + w / 2, cy0 - h / 2)
        draw.rounded_rectangle((x0, y0, x1, y1), radius=12, fill=fill, outline=outline, width=4)
        box = draw.textbbox((0, 0), text_value, font=label)
        draw.text(((x0+x1-box[2]+box[0])/2, (y0+y1-box[3]+box[1])/2), text_value, fill=outline, font=label)

    x0, y0 = point(-P["case_width"] / 2, P["case_height"] / 2)
    x1, y1 = point(P["case_width"] / 2, -P["case_height"] / 2)
    draw.rounded_rectangle((x0, y0, x1, y1), radius=40, fill="#fff", outline="#17352b", width=6)
    draw.text((45, 30), "V0.7 封闭腔内布局与 3 片软磁片安全区", fill="#17352b", font=title)
    rect(P["battery_center_x"], P["battery_center_y"], P["battery_width"], P["battery_height"], "#fff0c9", "#a36a00", "806090 电池")
    rect(P["esp_center_x"], P["esp_center_y"], P["esp_width"], P["esp_height"], "#dceaf7", "#315f8c", "ESP32-S3")
    rect(P["despi_center_x"], P["despi_center_y"], P["despi_width"], P["despi_height"], "#d9f2e8", "#28765e", "DESPI-C02")
    rect(P["lipo_center_x"], P["lipo_center_y"], P["lipo_width"], P["lipo_height"], "#e8e0f3", "#735497", "Lipo Rider")
    for index, (x, y, bar_width, bar_height) in enumerate(MAGNET_BARS_ASSEMBLED, 1):
        bx0, by0 = point(x - bar_width / 2.0, y + bar_height / 2.0)
        bx1, by1 = point(x + bar_width / 2.0, y - bar_height / 2.0)
        draw.rounded_rectangle(
            (bx0, by0, bx1, by1), radius=8,
            fill="#e0a84b", outline="#374151", width=3,
        )
        draw.text(((bx0 + bx1) / 2.0 - 11, (by0 + by1) / 2.0 - 9), f"B{index}", fill="#111827", font=small)
    for x, y in CASE_FASTENERS:
        px, py = point(x, y)
        draw.ellipse((px-6, py-6, px+6, py+6), fill="#fff", outline="#a33b34", width=3)
    draw.rectangle((45, 1660, 1205, 1845), fill="#e9f3ed", outline="#7ca08f", width=3)
    draw.text((65, 1680), "黄色 M1-M3：2片 90×50×2 mm + 1片 50×20×2 mm 橡胶软磁片。", fill="#17352b", font=label)
    draw.text((65, 1725), "M1/M2 旋转后左右贴合，形成 100×90 mm 下部连续磁区；总磁面 10000 mm²。", fill="#52665f", font=label)
    draw.text((65, 1770), "外侧 PLA 保持 0.4 mm；红圈为 M2×14 mm 后盖夹紧螺丝。", fill="#52665f", font=label)
    image.save(path)


def draw_placement_svg(path: Path):
    w, h = P["carrier_width"], P["carrier_height"]
    items = [f'<rect x="0.2" y="0.2" width="{w-0.4}" height="{h-0.4}" rx="6" fill="white" stroke="#111" stroke-width="0.35"/>']

    def svg_rect(cx, cy, width, height, colour, label):
        x, y = cx + w / 2 - width / 2, h / 2 - cy - height / 2
        return f'<rect x="{x:.3f}" y="{y:.3f}" width="{width:.3f}" height="{height:.3f}" fill="none" stroke="{colour}" stroke-width="0.35"/><text x="{x+1:.3f}" y="{y+3:.3f}" font-size="2.5">{label}</text>'

    items.extend(
        [
            svg_rect(P["battery_center_x"], P["battery_center_y"], P["battery_width"], P["battery_height"], "#a36a00", "806090 RECESS 0.5"),
            svg_rect(P["esp_center_x"], P["esp_center_y"], P["esp_width"], P["esp_height"], "#315f8c", "ESP32"),
            svg_rect(P["despi_center_x"], P["despi_center_y"], P["despi_width"], P["despi_height"], "#28765e", "DESPI"),
            svg_rect(P["lipo_center_x"], P["lipo_center_y"], P["lipo_width"], P["lipo_height"], "#735497", "LIPO"),
        ]
    )
    for x, y in ESP_HOLES + LIPO_HOLES:
        items.append(f'<circle cx="{x+w/2:.3f}" cy="{h/2-y:.3f}" r="1" fill="none" stroke="#0b6fbd" stroke-width="0.3"/>')
    for x, y in CASE_FASTENERS:
        items.append(f'<circle cx="{x+w/2:.3f}" cy="{h/2-y:.3f}" r="1.2" fill="none" stroke="#a33b34" stroke-width="0.3"/>')
    svg = f'''<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="{w}mm" height="{h}mm" viewBox="0 0 {w} {h}">
  {''.join(items)}
  <text x="3" y="{h-3}" font-size="2.5">V0.7 CARRIER - PRINT 100% - TOP IS USB-C - BATTERY TAPE MAX 0.2</text>
</svg>\n'''
    path.write_text(svg, encoding="utf-8")


def ensure_mesh(name, mesh):
    return v06.ensure_mesh(name, mesh)


def export_stl(name, mesh):
    path = OUTPUT / f"{name}.stl"
    path.write_bytes(trimesh.exchange.stl.export_stl(mesh))
    return path


def part_info(path):
    return v06.part_info(path)


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    PREVIEWS.mkdir(parents=True, exist_ok=True)
    # Remove only the superseded generated right-side artifacts.  Keeping them
    # beside the corrected left-side files can cause Bambu Studio to reopen the
    # stale coupon or make the delivery package ambiguous.
    legacy_side_artifacts = [
        OUTPUT / "fit_test_rear_right_lowered_wall_v0_7.stl",
        PREVIEWS / "rear_right_wall_revision_v0_7.png",
        ROOT / "RFM_enclosure_v0_7_STL" / "fit_test_rear_right_lowered_wall_v0_7.stl",
        ROOT / "RFM_enclosure_v0_7_STL" / "rear_right_wall_revision_v0_7.png",
        OUTPUT / "fit_test_magnet_bar_40x10x2_v0_7.stl",
        OUTPUT / "rear_cover_v0_7_magnet_bars_9x40x10x2.stl",
        ROOT / "RFM_enclosure_v0_7_STL" / "fit_test_magnet_bar_40x10x2_v0_7.stl",
        ROOT / "RFM_enclosure_v0_7_STL" / "rear_cover_v0_7_magnet_bars_9x40x10x2.stl",
        OUTPUT / "fit_test_rear_left_lowered_wall_v0_7.stl",
        ROOT / "RFM_enclosure_v0_7_STL" / "fit_test_rear_left_lowered_wall_v0_7.stl",
        PREVIEWS / "rear_left_wall_revision_v0_7.png",
        ROOT / "RFM_enclosure_v0_7_STL" / "rear_left_wall_revision_v0_7.png",
        OUTPUT / "fit_test_front_left_retainer_v0_7_rev_d_2_9mm.stl",
        OUTPUT / "fit_test_front_right_open_v0_7_rev_d.stl",
        PREVIEWS / "front_retainer_revision_v0_7_rev_d.png",
        ROOT / "RFM_enclosure_v0_7_STL" / "fit_test_front_left_retainer_v0_7_rev_d_2_9mm.stl",
        ROOT / "RFM_enclosure_v0_7_STL" / "fit_test_front_right_open_v0_7_rev_d.stl",
        ROOT / "RFM_enclosure_v0_7_STL" / "front_retainer_revision_v0_7_rev_d.png",
        OUTPUT / "fit_test_front_right_open_v0_7_rev_e_flush_land.stl",
        PREVIEWS / "front_retainer_revision_v0_7_rev_e.png",
        ROOT / "RFM_enclosure_v0_7_STL" / "fit_test_front_right_open_v0_7_rev_e_flush_land.stl",
        ROOT / "RFM_enclosure_v0_7_STL" / "front_retainer_revision_v0_7_rev_e.png",
        OUTPUT / "fit_test_magnet_bar_38x9x1p5_v0_7.stl",
        OUTPUT / "rear_cover_v0_7_magnet_bars_9x38x9x1p5.stl",
        ROOT / "RFM_enclosure_v0_7_STL" / "fit_test_magnet_bar_38x9x1p5_v0_7.stl",
        ROOT / "RFM_enclosure_v0_7_STL" / "rear_cover_v0_7_magnet_bars_9x38x9x1p5.stl",
    ]
    for legacy_path in legacy_side_artifacts:
        legacy_path.unlink(missing_ok=True)
    front = ensure_mesh("front_bezel_v0_7", build_front_bezel())
    carrier = ensure_mesh("electronics_carrier_v0_7", build_carrier())
    rear = ensure_mesh("rear_cover_v0_7", build_rear_cover())
    normal_gauge = ensure_mesh("fit_test_13_6mm_assembled_height_v0_7", build_height_gauge(available_assembled_carrier_height()))
    battery_gauge = ensure_mesh("fit_test_12_2mm_battery_magnet_zone_v0_7", build_height_gauge(magnet_bar_local_height()))
    magnet_bar_coupon = ensure_mesh(
        "fit_test_soft_magnet_2mm_skin_0p4_v0_7",
        build_magnet_bar_fit_coupon(),
    )
    rear_openings = ensure_mesh("fit_test_lipo_usb_led_openings_v0_7", rear_openings_coupon(rear))
    usb_c_opening_coupon = ensure_mesh(
        "fit_test_usb_c_opening_11p5x7p5_v0_7",
        rear_usb_c_opening_coupon(rear),
    )
    rear_left_wall = ensure_mesh(
        "fit_test_rear_left_flat_wall_0p8mm_v0_7_rev_f",
        rear_left_wall_coupon(rear),
    )
    button_label_coupon = ensure_mesh(
        "fit_test_boot_reset_labels_v0_7",
        rear_button_label_coupon(rear),
    )
    front_corner = ensure_mesh("fit_test_front_corner_v0_7", corner_coupon(front))
    front_left_retainer = ensure_mesh(
        "fit_test_front_left_retainer_v0_7_rev_e_square_inner",
        cropped_coupon(front, COUPON_BOUNDS_FRONT_LEFT),
    )
    front_right_open = ensure_mesh(
        "fit_test_front_right_open_v0_7_rev_f_continuous_edge",
        cropped_coupon(front, COUPON_BOUNDS_FRONT),
    )
    carrier_corner = ensure_mesh("fit_test_carrier_corner_v0_7", corner_coupon(carrier))
    rear_corner = ensure_mesh("fit_test_rear_corner_v0_7", corner_coupon(rear, rear_rev_b=True))
    meshes = {
        "front_bezel_v0_7": front,
        "electronics_carrier_v0_7": carrier,
        "rear_cover_v0_7": rear,
        "rear_cover_v0_7_soft_magnets_2x90x50_1x50x20": rear.copy(),
        "rear_cover_v0_7_rev_e_dfm_clearance": rear.copy(),
        "rear_cover_v0_7_rev_f_flat_left_wall_0p8mm": rear.copy(),
        "rear_cover_v0_7_rev_g_lipo_switch_access": rear.copy(),
        "rear_cover_v0_7_rev_h_combined_lipo_led_switch_opening": rear.copy(),
        "rear_cover_v0_7_rev_i_regular_lipo_led_switch_opening": rear.copy(),
        "fit_test_13_6mm_assembled_height_v0_7": normal_gauge,
        "fit_test_12_2mm_battery_magnet_zone_v0_7": battery_gauge,
        "fit_test_soft_magnet_2mm_skin_0p4_v0_7": magnet_bar_coupon,
        "fit_test_lipo_usb_led_openings_v0_7": rear_openings,
        "fit_test_lipo_usb_led_switch_openings_v0_7_rev_g": rear_openings.copy(),
        "fit_test_lipo_combined_led_switch_opening_v0_7_rev_h": rear_openings.copy(),
        "fit_test_lipo_regular_led_switch_opening_v0_7_rev_i": rear_openings.copy(),
        "fit_test_usb_c_opening_11p5x7p5_v0_7": usb_c_opening_coupon,
        "fit_test_rear_left_flat_wall_0p8mm_v0_7_rev_f": rear_left_wall,
        "fit_test_boot_reset_labels_v0_7": button_label_coupon,
        "fit_test_front_corner_v0_7": front_corner,
        "fit_test_front_corner_v0_7_rev_b_uniform_3_6mm": front_corner.copy(),
        "fit_test_front_left_retainer_v0_7_rev_e_square_inner": front_left_retainer,
        "fit_test_front_right_open_v0_7_rev_f_continuous_edge": front_right_open,
        "fit_test_carrier_corner_v0_7": carrier_corner,
        "fit_test_carrier_corner_v0_7_rev_b_boss_relief_r2_9": carrier_corner.copy(),
        "fit_test_rear_corner_v0_7": rear_corner,
        "fit_test_rear_corner_v0_7_rev_b_opposite_side": rear_corner.copy(),
        "fit_test_rear_corner_v0_7_rev_c_boss_relief_r2_9": rear_corner.copy(),
        "fit_test_rear_corner_clearance_v0_7_rev_e": rear_corner.copy(),
    }
    paths = {name: export_stl(name, mesh) for name, mesh in meshes.items()}
    # Keep the historical root-level official filename synchronized with the
    # generated output so it cannot silently point to an older front revision.
    shutil.copy2(paths["front_bezel_v0_7"], ROOT / "front_bezel_v0_7.stl")
    overview = PREVIEWS / "compact_enclosure_overview_v0_7.png"
    layout = PREVIEWS / "electronics_layout_v0_7.png"
    rear_dfm_revision = PREVIEWS / "rear_dfm_clearance_revision_v0_7_rev_e.png"
    template = OUTPUT / "placement_template_v0_7_1to1.svg"
    draw_overview(overview)
    draw_layout(layout)
    draw_rear_dfm_revision(rear_dfm_revision)
    draw_placement_svg(template)
    screw_engagement = P["case_fastener_length"] - (
        P["assembled_thickness"] - P["case_fastener_counterbore_depth"] - P["front_feature_depth"]
    )
    manifest = {
        "design": "FridgeEInkDisplay compact closed enclosure V0.7",
        "units": "mm",
        "status": "engineering prototype; coupons required before full shell",
        "preserves": [
            "V0.6 remains unchanged",
            "V0.7 carrier, electronics placement and 19 mm envelope remain unchanged",
            "V0.7 rear outer outline, fastener centres and buttons remain unchanged",
            "V0.7 magnet pockets now fit two 90 x 50 x 2 mm plus one 50 x 20 x 2 mm flexible sheets",
            "V0.7 Rev E rear corner and front-post DFM clearances remain unchanged",
            "V0.7 Rev F restores only the assembled-left top 1.8 mm band at 0.8 mm thickness; the lower wall stays 1.8 mm",
            "V0.7 Rev G adds only the compact Lipo Rider SW1 access slot",
            "V0.7 Rev H joins the LED and SW1 openings with a minimal 2.4 mm bridge",
            "V0.7 Rev I replaces the Rev H profile with one regular 5.2 x 21.0 mm R1.0 opening",
            "V0.7 USB-C opening remains 11.5 mm wide and grows from 5.5 to 7.5 mm high, centred at the same position",
            "V0.7 front window, outer outline and four screw posts remain unchanged",
            "V0.8 remains unchanged",
        ],
        "target_outer_size": [P["case_width"], P["case_height"], P["assembled_thickness"]],
        "comparison_to_v0_6": {
            "v0_6_nominal": [120.0, 184.0, 21.4],
            "v0_7_nominal": [120.0, 184.0, 19.0],
            "thickness_reduction": 2.4,
        },
        "enclosure": {
            "architecture": "front bezel + recessed electronics carrier + locally reinforced rear shell",
            "rear_internal_revision": "Rev I regular 5.2 x 21.0 mm R1.0 Lipo LED/SW1 opening, retaining Rev F left wall and Rev E DFM clearance",
            "bottom_and_sides": "fully closed",
            "fasteners": "4 x M2 x 14 mm self-tapping, head diameter <= 4.6 mm, head height <= 1.5 mm",
            "fastener_engagement_in_front_boss": round(screw_engagement, 3),
            "front_screw_post_radius": round(P["case_fastener_post_diameter"] / 2.0, 3),
            "rear_internal_boss_relief_radius": round(
                P["case_fastener_post_diameter"] / 2.0
                + P["front_boss_relief_radial_clearance"],
                3,
            ),
            "rear_internal_boss_relief_radial_clearance": P["front_boss_relief_radial_clearance"],
            "rear_internal_boss_relief_axial_depth_into_tube": P["rear_boss_relief_axial_depth_into_tube"],
            "rear_internal_boss_relief_entry_chamfer": P["rear_boss_relief_entry_chamfer"],
            "rear_corner_entry_relief": {
                "base_cavity_corner_radius_unchanged": P["rear_inner_corner_radius"],
                "entry_depth": P["rear_corner_entry_relief_depth"],
                "radial_relief": P["rear_corner_entry_radial_relief"],
                "entry_relief_radius": P["rear_inner_corner_radius"] + P["rear_corner_entry_radial_relief"],
                "mouth_chamfer": P["rear_corner_entry_chamfer"],
                "maximum_mouth_radius": (
                    P["rear_inner_corner_radius"]
                    + P["rear_corner_entry_radial_relief"]
                    + P["rear_corner_entry_chamfer"]
                ),
                "elephant_foot_contact_relief_within_chamfer": P["rear_corner_contact_relief"],
            },
            "carrier_front_boss_relief_radius": round(P["carrier_front_boss_relief_diameter"] / 2.0, 3),
            "rear_cavity_depth": round(P["rear_depth"] - P["rear_skin"], 3),
            "assembled_carrier_height": round(available_assembled_carrier_height(), 3),
            "usable_height_above_carrier": round(available_height_above_carrier(), 3),
            "magnet_bar_local_height": round(magnet_bar_local_height(), 3),
            "front_retainer_rev_f": {
                "retained_sides": ["top", "bottom", "left", "upper-right arc", "lower-right arc"],
                "right_retainer_removed": P["front_right_retainer_removed"],
                "retainer_width": P["front_retainer_width"],
                "outer_edge_inset": P["front_retainer_edge_inset"],
                "top_bottom_outer_edge_inset": P["front_retainer_top_bottom_edge_inset"],
                "outer_corner_radius": P["front_retainer_outer_radius"],
                "right_transition_inner_radius": P["front_retainer_inner_radius"],
                "left_inner_corner_radius": P["front_retainer_left_inner_corner_radius"],
                "left_inner_corner_style": P["front_retainer_left_inner_corner_style"],
                "rear_inner_corner_radius": P["rear_inner_corner_radius"],
                "radial_clearance_to_rear": P["front_retainer_to_rear_radial_clearance"],
                "four_outer_corner_radii_equal": True,
                "right_end_style": P["front_retainer_right_end_style"],
                "right_opening_span_from_inner_geometry": (
                    P["screen_locator_outer_height"] - 2.0 * P["front_retainer_width"]
                ),
                "right_horizontal_edges_y": [
                    -(P["screen_locator_outer_height"] - 2.0 * P["front_retainer_width"]) / 2.0,
                    (P["screen_locator_outer_height"] - 2.0 * P["front_retainer_width"]) / 2.0,
                ],
                "independent_clear_span_constraint": None,
                "right_vertical_rail_removed": True,
                "screen_entry_side": "right",
                "left_overlap_on_physical_panel": round(
                    P["screen_body_width"] / 2.0
                    - (P["case_width"] / 2.0 - P["front_retainer_edge_inset"] - P["front_retainer_width"]),
                    3,
                ),
                "measured_left_inactive_border_remaining": round(
                    9.0
                    - (
                        P["screen_body_width"] / 2.0
                        - (P["case_width"] / 2.0 - P["front_retainer_edge_inset"] - P["front_retainer_width"])
                    ),
                    3,
                ),
            },
            "usb_c_opening": {
                "width": P["charge_cutout_width"],
                "height": P["charge_cutout_height"],
                "model_center": [
                    P["charge_cutout_center_x"],
                    P["charge_cutout_center_y"],
                    P["charge_cutout_center_z"],
                ],
                "vertical_drop_from_previous_revision": P["charge_cutout_vertical_drop"],
            },
            "rear_left_edge_revision": {
                "assembled_side": "left",
                "flat_thinned_y_range": [
                    P["rear_left_flat_y_min"],
                    P["rear_left_flat_y_max"],
                ],
                "flat_thinned_span": P["rear_left_flat_span"],
                "edge_drop": P["rear_left_edge_drop"],
                "edge_height": P["rear_depth"],
                "lower_wall_thickness": P["rear_left_lower_wall_thickness"],
                "restored_top_band_height": P["rear_left_restored_band_height"],
                "restored_top_band_thickness": P["rear_left_restored_band_thickness"],
                "minimum_extrusion_lines_at_0p4mm": 2,
                "inward_ledge_removed": P["rear_left_inward_ledge_removed"],
                "opposite_right_edge_restored": True,
                "pure_straight_length": P["case_height"] - 2.0 * P["corner_radius"],
                "corner_transition_extension_each_end": (
                    P["rear_left_flat_span"]
                    - (P["case_height"] - 2.0 * P["corner_radius"])
                ) / 2.0,
            },
            "lipo_indicator_window": {
                "purpose": "charge status LED plus four-segment battery gauge",
                "width": P["lipo_indicator_window_width"],
                "height": P["lipo_indicator_window_height"],
                "assembled_center": [round(value, 3) for value in LIPO_INDICATOR_WINDOW_ASSEMBLED],
                "rear_model_center": [round(value, 3) for value in LIPO_INDICATOR_WINDOW_MODEL],
                "official_led_points_assembled": [
                    [round(x, 3), round(y, 3)] for x, y in LIPO_LED_POINTS_ASSEMBLED
                ],
            },
            "lipo_switch_access": {
                "purpose": "operate the Lipo Rider Plus SW1 slider without removing the rear cover",
                "width": P["lipo_switch_window_width"],
                "height": P["lipo_switch_window_height"],
                "corner_radius": P["lipo_switch_window_corner_radius"],
                "official_eagle_center": list(LIPO_SWITCH_POINT_EAGLE),
                "assembled_center": [round(value, 3) for value in LIPO_SWITCH_POINT_ASSEMBLED],
                "rear_model_center": [round(value, 3) for value in LIPO_SWITCH_WINDOW_MODEL],
                "official_package": [
                    P["lipo_switch_package_width"],
                    P["lipo_switch_package_length"],
                    3.2,
                ],
                "operation": "fingernail or small non-metallic slider tool",
            },
            "lipo_combined_led_switch_opening": {
                "revision": "Rev I",
                "regular_opening_enabled": P["lipo_regular_opening_enabled"],
                "width": P["lipo_regular_opening_width"],
                "height": P["lipo_regular_opening_height"],
                "corner_radius": P["lipo_regular_opening_corner_radius"],
                "assembled_center": [
                    round(value, 3) for value in LIPO_REGULAR_OPENING_ASSEMBLED
                ],
                "rear_model_center": [
                    round(value, 3) for value in LIPO_REGULAR_OPENING_MODEL
                ],
                "shape": "single regular rounded rectangle",
                "full_bounding_rectangle_used": True,
            },
            "rear_button_labels": {
                "outside_view_text": ["BOOT", "RESET"],
                "pre_mirrored_in_model_x": P["rear_label_pre_mirrored_for_bottom_view"],
                "position": P["rear_label_position"],
                "vertical_offset_from_hole_center": P["rear_label_vertical_offset"],
                "boot_label_model_center": [round(value, 3) for value in REAR_BOOT_LABEL],
                "reset_label_model_center": [round(value, 3) for value in REAR_RESET_LABEL],
                "pixel_pitch": P["rear_label_pixel"],
                "nominal_stroke": P["rear_label_pixel"] + P["rear_label_overlap"],
                "engraving_depth": P["rear_label_depth"],
                "viewing_direction": "physical rear/bottom outside, USB-C edge at top",
            },
        },
        "battery": {
            "nominal_envelope": [P["battery_width"], P["battery_height"], P["battery_thickness"]],
            "carrier_recess_depth": P["battery_recess_depth"],
            "underlay_max": P["battery_underlay_max"],
            "stack_from_carrier_underside": round(battery_stack_height(), 3),
            "clearance_below_magnet_bar_boss": round(magnet_bar_local_height() - battery_stack_height(), 3),
        },
        "magnets": {
            "quantity": len(MAGNET_BARS_ASSEMBLED),
            "type": "flexible ferrite magnetic powder plus rubber permanent-magnet sheet",
            "nominal_pieces": [
                [90.0, 50.0, 2.0],
                [90.0, 50.0, 2.0],
                [50.0, 20.0, 2.0],
            ],
            "large_pair_orientation": "each 90 mm side vertical; 50 mm sides touch at X=0",
            "large_pair_shared_pocket": [100.6, 90.6, P["magnet_bar_pocket_depth"]],
            "small_pocket": [20.6, 50.6, P["magnet_bar_pocket_depth"]],
            "xy_clearance_per_outer_edge": P["magnet_bar_xy_clearance_per_side"],
            "outer_skin": P["magnet_bar_outer_skin"],
            "outer_skin_material": "PLA",
            "adhesive": "factory pressure-sensitive backing or thin acrylic transfer adhesive",
            "magnets_require_cutting": False,
            "assembled_bars_xywh": MAGNET_BARS_ASSEMBLED,
            "nominal_face_area_total_mm2": sum(width * height for _, _, width, height in MAGNET_BARS_ASSEMBLED),
            "clearances": magnet_clearance_report(),
        },
        "components": {
            "battery_center": [P["battery_center_x"], P["battery_center_y"]],
            "esp32_center": [P["esp_center_x"], P["esp_center_y"]],
            "esp32_holes": [[round(x, 3), round(y, 3)] for x, y in ESP_HOLES],
            "despi_center": [P["despi_center_x"], P["despi_center_y"]],
            "lipo_center": [P["lipo_center_x"], P["lipo_center_y"]],
        },
        "corner_coupons": {
            "physical_corner": "upper-right",
            "front_and_carrier_crop_bounds": list(COUPON_BOUNDS_FRONT),
            "front_left_retainer_crop_bounds": list(COUPON_BOUNDS_FRONT_LEFT),
            "front_right_open_crop_bounds": list(COUPON_BOUNDS_FRONT),
            "rear_rev_b_crop_bounds": list(COUPON_BOUNDS_REAR_REV_B),
            "raw_stl_fastener_centres": {
                "front": [13.0, 32.9],
                "carrier": [13.0, 32.9],
                "rear_rev_b": [22.0, 32.9],
            },
            "assembled_fastener_centres_after_rear_turnover": {
                "front": [13.0, 32.9],
                "carrier": [13.0, 32.9],
                "rear_rev_b": [13.0, 32.9],
            },
            "preferred_rear_coupon": "fit_test_rear_corner_clearance_v0_7_rev_e.stl",
            "preferred_rear_coupon_validates": [
                "R3.3 front-post relief with 0.7 mm radial clearance",
                "0.6 mm axial relief into the rear screw tube",
                "0.5 mm x 45-degree fastener-mouth lead-in",
                "first 1.2 mm rear-corner entry relief and mouth chamfer",
            ],
        },
        "rear_openings_coupon": {
            "crop_bounds": list(OPENINGS_COUPON_BOUNDS),
            "validates": [
                "USB-C male plug insertion",
                "five Lipo Rider LEDs visible",
                "Lipo Rider SW1 can travel fully between ON and OFF",
                "LED and SW1 share one regular 5.2 x 21.0 mm R1.0 opening",
            ],
        },
        "usb_c_opening_coupon": {
            "crop_bounds": list(USB_C_COUPON_BOUNDS),
            "filename": "fit_test_usb_c_opening_11p5x7p5_v0_7.stl",
            "validates": [
                "USB-C male plug passes through the 11.5 x 7.5 mm opening",
                "opening remains centred at the existing horizontal and vertical position",
                "top wall around the opening prints continuously",
            ],
        },
        "rear_left_wall_coupon": {
            "crop_bounds": list(LEFT_WALL_COUPON_BOUNDS),
            "validates": [
                "left inward ledge removed",
                "left wall opening edge remains level at the full 16.6 mm height",
                "original lower left wall remains 1.8 mm thick",
                "only the restored 1.8 mm-high top band is 0.8 mm thick over the 170 mm span",
                "upper transition reaches Y=85 mm without changing the R8 outer outline",
            ],
        },
        "button_label_coupon": {
            "crop_bounds": list(BUTTON_LABEL_COUPON_BOUNDS),
            "validates": [
                "BOOT and RESET read normally from the rear outside",
                "0.58 mm nominal bitmap stroke slices clearly with a 0.4 mm nozzle",
                "0.60 mm engraving remains visible without cutting through the base skin",
            ],
        },
        "parts": {name: part_info(path) for name, path in paths.items()},
        "previews": [
            overview.name,
            layout.name,
            "assembly_effect_v0_7.png",
            "installed_effect_v0_7.png",
            "exploded_view_v0_7.png",
            "corner_fit_assembly_v0_7.png",
            "rear_coupon_hole_revision_v0_7_rev_b.png",
            "rear_openings_detail_v0_7.png",
            "rear_left_wall_flat_revision_v0_7_rev_f.png",
            "front_retainer_revision_v0_7_rev_f.png",
            "rear_button_labels_outside_v0_7.png",
            rear_dfm_revision.name,
        ],
        "templates": [template.name],
        "parameters": P,
    }
    manifest_path = OUTPUT / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    package_dir = ROOT / "RFM_enclosure_v0_7_STL"
    package_dir.mkdir(parents=True, exist_ok=True)
    docs = [ROOT / "README.md", ROOT / "ASSEMBLY_GUIDE.md"]
    for path in [*paths.values(), manifest_path, template, overview, layout, *docs]:
        shutil.copy2(path, package_dir / path.name)
    package = ROOT / "RFM_enclosure_v0_7_STL.zip"
    with zipfile.ZipFile(package, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in [*paths.values(), manifest_path, template, overview, layout, *docs]:
            archive.write(path, path.name)
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
