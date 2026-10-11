#!/usr/bin/env python3
"""Render the two original V0.5 corner coupons in their assembled pose."""

from __future__ import annotations

from pathlib import Path

import matplotlib as mpl
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d.art3d import Poly3DCollection
import numpy as np
import trimesh


ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "output"
PREVIEWS = ROOT / "previews"


def carrier_vertices_in_rear_frame(mesh: trimesh.Trimesh, explode_z: float = 0.0) -> np.ndarray:
    """Apply the physical Y flip and place the carrier in the rear coupon."""
    vertices = mesh.vertices.copy()
    vertices[:, 0] = 36.0 - vertices[:, 0]
    vertices[:, 2] = 23.0 - vertices[:, 2] + explode_z
    return vertices


def add_mesh(ax, mesh, vertices, color, alpha=1.0):
    triangles = vertices[mesh.faces]
    ax.add_collection3d(
        Poly3DCollection(
            triangles,
            facecolors=color,
            edgecolors=color,
            linewidth=0.0,
            alpha=alpha,
            shade=True,
        )
    )


def configure_axis(ax, title):
    ax.set_xlim(-3, 40)
    ax.set_ylim(-3, 41)
    ax.set_zlim(0, 40)
    ax.set_box_aspect((43, 44, 40))
    ax.view_init(elev=27, azim=-58)
    ax.set_axis_off()
    ax.set_title(title, fontsize=18, color="#17352b", pad=18)


def main():
    mpl.rcParams["font.sans-serif"] = [
        "PingFang SC",
        "Arial Unicode MS",
        "Heiti SC",
        "DejaVu Sans",
    ]
    mpl.rcParams["axes.unicode_minus"] = False

    rear = trimesh.load_mesh(OUTPUT / "fit_test_rear_corner_v0_5.stl")
    carrier = trimesh.load_mesh(OUTPUT / "fit_test_carrier_corner_v0_5.stl")

    fig = plt.figure(figsize=(16, 8.8), facecolor="#f5f3ed")
    exploded = fig.add_subplot(1, 2, 1, projection="3d")
    assembled = fig.add_subplot(1, 2, 2, projection="3d")

    add_mesh(exploded, rear, rear.vertices, "#d9e2ea", 0.96)
    add_mesh(exploded, carrier, carrier_vertices_in_rear_frame(carrier, 12.0), "#dca35b", 0.96)
    configure_axis(exploded, "装入前：托板翻面，5 mm外露柱朝下")
    exploded.text(4.0, 37.0, 39.0, "V0.5 中层托板角件", color="#9b5b13", fontsize=13)
    exploded.text(1.5, 5.0, 2.0, "V0.5 后盖角件（空腔朝上）", color="#304d70", fontsize=13)

    add_mesh(assembled, rear, rear.vertices, "#d9e2ea", 0.96)
    add_mesh(assembled, carrier, carrier_vertices_in_rear_frame(carrier), "#dca35b", 0.98)
    configure_axis(assembled, "装入后：托板落在后盖内腔台阶上")
    assembled.text(1.0, 38.0, 25.0, "相对后盖外边缘内缩 2.5 mm", color="#b23b33", fontsize=13)
    assembled.text(4.0, 5.0, 18.0, "孔中心同轴", color="#8b5516", fontsize=13)

    fig.suptitle("V0.5 两个原始检具的实际试装效果（按原始 STL 渲染）", fontsize=25, color="#17352b", y=0.96)
    fig.text(
        0.5,
        0.035,
        "V0.5 原结构：螺母柱总高 7 mm = 2 mm 托板基板 + 5 mm 外露柱；外圆角不应重合。",
        ha="center",
        fontsize=16,
        color="#9d2f2a",
    )
    PREVIEWS.mkdir(parents=True, exist_ok=True)
    fig.savefig(PREVIEWS / "fit_coupon_assembled_effect_v0_5.png", dpi=180, bbox_inches="tight")
    plt.close(fig)


if __name__ == "__main__":
    main()
