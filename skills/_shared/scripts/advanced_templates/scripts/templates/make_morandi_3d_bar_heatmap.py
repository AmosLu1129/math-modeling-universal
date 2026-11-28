#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Morandi 2D Tiled Heatmap + 3D Shaded Bar Heatmap Dual-Panel Template (`morandi-3d-bar-heatmap`)."""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("MPLCONFIGDIR", str(ROOT / ".mplconfig"))

import matplotlib as mpl

mpl.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.colors import LinearSegmentedColormap


def _try_import_plot_style():
    candidates = []
    if os.environ.get("MATHFIG_SHARED_SCRIPTS"):
        candidates.append(Path(os.environ["MATHFIG_SHARED_SCRIPTS"]))
    p = Path(__file__).resolve()
    for anc in p.parents:
        if (anc / "plot_style.py").is_file():
            candidates.append(anc)
            break
    for c in candidates:
        if str(c) not in sys.path:
            sys.path.insert(0, str(c))
        try:
            import plot_style as ps  # type: ignore

            return ps
        except ImportError:
            pass
    return None


def configure_style(cmap_name: str = "morandi_seq"):
    ps = _try_import_plot_style()
    if ps is not None:
        ps.apply("morandi_journal")
        mpl.rcParams["figure.autolayout"] = False
        return ps.get_cmap(cmap_name), ps

    mpl.rcParams.update(
        {
            "font.family": "sans-serif",
            "font.sans-serif": ["Arial", "Helvetica", "Microsoft YaHei", "DejaVu Sans"],
            "axes.unicode_minus": False,
            "mathtext.fontset": "stixsans",
            "axes.edgecolor": "#3A3F47",
            "axes.labelcolor": "#2C3137",
            "xtick.color": "#3A3F47",
            "ytick.color": "#3A3F47",
            "axes.linewidth": 0.8,
            "figure.autolayout": False,
            "svg.fonttype": "none",
            "pdf.fonttype": 42,
        }
    )
    cmaps = {
        "morandi_seq": LinearSegmentedColormap.from_list("morandi_seq", ["#F5F2EC", "#C5D5D8", "#7599AA", "#3B5875"], N=256),
        "morandi_div": LinearSegmentedColormap.from_list("morandi_div", ["#4B6C8C", "#A8BFD0", "#F7F5F0", "#DFAC9D", "#B85D4E"], N=256),
        "morandi_warm": LinearSegmentedColormap.from_list("morandi_warm", ["#F7F3EC", "#E5C8A6", "#D49B7A", "#B5614E"], N=256),
    }
    return cmaps.get(cmap_name, cmaps["morandi_seq"]), None


def compute_anti_occlusion_azim(matrix: np.ndarray) -> float:
    """Compute viewing azimuth so lower bars sit in the foreground and tall bars sit in back."""
    nrows, ncols = matrix.shape
    z = matrix - np.min(matrix)
    total = float(np.sum(z))
    if total <= 1e-12:
        return -52.0
    # X corresponds to col index j in [0, 1], Y corresponds to row index i in [0, 1]
    ys, xs = np.meshgrid(np.linspace(0.0, 1.0, ncols), np.linspace(0.0, 1.0, nrows))
    # Wait: bar at (col=j, row=i) uses x=j, y=i; use normalized coordinates cleanly:
    ri = np.linspace(0.0, 1.0, nrows)[:, None]
    cj = np.linspace(0.0, 1.0, ncols)[None, :]
    cx = float(np.sum(cj * z) / total)
    cy = float(np.sum(ri * z) / total)
    # Camera should sit opposite to the tall-bar centroid in (x=col, y=row)
    vx = -1.0 if cx >= 0.5 else 1.0
    vy = -1.0 if cy >= 0.5 else 1.0
    # Slight non-45 deg offset prevents exact diagonal bar lining up
    angle_deg = math.degrees(math.atan2(vy * 0.92, vx * 1.08))
    return round(angle_deg, 1)


def default_payload() -> dict:
    # Realistic Li-ion effective battery discharge time (hours) across ambient temp & SOH
    return {
        "matrix": [
            [2.1, 2.8, 3.5, 4.1, 4.7, 5.2],
            [3.2, 4.0, 4.8, 5.5, 6.2, 6.8],
            [4.5, 5.4, 6.3, 7.1, 7.9, 8.6],
            [5.4, 6.5, 7.5, 8.4, 9.2, 10.0],
            [5.8, 7.0, 8.1, 9.1, 10.1, 10.9],
            [5.1, 6.2, 7.3, 8.3, 9.2, 9.9],
        ],
        "row_labels": ["-15°C", "-5°C", "5°C", "15°C", "25°C", "35°C"],
        "col_labels": ["70%", "76%", "82%", "88%", "94%", "100%"],
        "row_axis_label": "Ambient Temperature",
        "col_axis_label": "Battery State of Health (SOH)",
        "value_label": "Effective Runtime (h)",
        "fmt": "{:.1f}",
        "cmap": "morandi_seq",
        "panel_a_title": "(a) Precision Grid Readout (2D)",
        "panel_b_title": "(b) Coupled Volumetric Response (3D)",
    }


def make_figure(output_stem: Path, cfg: dict | None = None) -> None:
    payload = default_payload()
    if cfg:
        payload.update(cfg)

    mat = np.asarray(payload["matrix"], dtype=float)
    nrows, ncols = mat.shape
    cmap, ps = configure_style(str(payload.get("cmap", "morandi_seq")))

    vmin = float(payload.get("vmin", np.min(mat)))
    vmax = float(payload.get("vmax", np.max(mat)))
    norm = mpl.colors.Normalize(vmin=vmin, vmax=vmax)

    fig = plt.figure(figsize=(12.2, 5.1), facecolor="white")

    # Panel (a): 2D Morandi tiled heatmap with pure-vector pcolormesh & crisp white grout
    ax2d = fig.add_axes([0.075, 0.16, 0.34, 0.72])
    x_edges = np.arange(ncols + 1) - 0.5
    y_edges = np.arange(nrows + 1) - 0.5
    ax2d.pcolormesh(
        x_edges,
        y_edges,
        mat,
        cmap=cmap,
        norm=norm,
        edgecolors="#FFFFFF",
        linewidth=2.0,
        shading="flat",
    )
    ax2d.set_aspect("equal")
    ax2d.set_xlim(-0.5, ncols - 0.5)
    ax2d.set_ylim(-0.5, nrows - 0.5)
    ax2d.grid(False)
    for spine in ax2d.spines.values():
        spine.set_visible(False)

    ax2d.set_xticks(np.arange(ncols))
    ax2d.set_xticklabels(payload["col_labels"], fontsize=9.2, color="#2C3137")
    ax2d.set_yticks(np.arange(nrows))
    ax2d.set_yticklabels(payload["row_labels"], fontsize=9.2, color="#2C3137")
    ax2d.set_xlabel(payload["col_axis_label"], fontsize=10.5, labelpad=8, fontweight="medium")
    ax2d.set_ylabel(payload["row_axis_label"], fontsize=10.5, labelpad=8, fontweight="medium")
    ax2d.set_title(payload["panel_a_title"], fontsize=11.5, fontweight="bold", pad=11, color="#1F242A")

    fmt = str(payload.get("fmt", "{:.1f}"))
    for i in range(nrows):
        for j in range(ncols):
            val = mat[i, j]
            txt_color = "#FFFFFF" if norm(val) > 0.54 else "#232830"
            ax2d.text(j, i, fmt.format(val), ha="center", va="center", fontsize=8.8, fontweight="bold", color=txt_color)

    # Shared Morandi colorbar cleanly centered between panels
    cax = fig.add_axes([0.435, 0.19, 0.014, 0.66])
    sm = mpl.cm.ScalarMappable(norm=norm, cmap=cmap)
    sm.set_array([])
    cbar = fig.colorbar(sm, cax=cax)
    if getattr(cbar, "solids", None) is not None:
        cbar.solids.set_rasterized(False)
        cbar.solids.set_edgecolor("face")
    cbar.outline.set_edgecolor("#B9C2CC")
    cbar.outline.set_linewidth(0.7)
    cbar.ax.tick_params(labelsize=8.8, color="#3A3F47", labelcolor="#2C3137")
    cbar.set_label(payload["value_label"], fontsize=9.8, labelpad=8, color="#2C3137")

    # Panel (b): 3D Morandi shaded bar heatmap with breathing gaps & anti-occlusion camera
    ax3d = fig.add_axes([0.495, 0.06, 0.48, 0.85], projection="3d")
    if ps is not None:
        ps.style_3d_axes(ax3d)
    else:
        for axis in (ax3d.xaxis, ax3d.yaxis, ax3d.zaxis):
            axis.pane.set_facecolor((0.97, 0.98, 0.99, 0.65))
            axis.pane.set_edgecolor("#DCE2EA")
            axis._axinfo["grid"]["color"] = (0.85, 0.87, 0.90, 0.8)
            axis._axinfo["grid"]["linewidth"] = 0.55

    dx = dy = 0.68
    xs_grid, ys_grid = np.meshgrid(np.arange(ncols), np.arange(nrows))
    x_pos = xs_grid.ravel() - dx / 2.0
    y_pos = ys_grid.ravel() - dy / 2.0
    z_base = np.zeros_like(x_pos, dtype=float)
    heights = mat.ravel()
    rgba_colors = cmap(norm(heights))

    ax3d.bar3d(
        x_pos,
        y_pos,
        z_base,
        dx,
        dy,
        heights,
        color=rgba_colors,
        edgecolor="#FFFFFF",
        linewidth=0.4,
        alpha=0.93,
        shade=True,
    )

    azim = float(payload.get("azim", compute_anti_occlusion_azim(mat)))
    elev = float(payload.get("elev", 27.0))
    ax3d.view_init(elev=elev, azim=azim)
    ax3d.set_box_aspect((1.12, 1.08, 0.78))

    ax3d.set_xlim(-0.55, ncols - 0.45)
    ax3d.set_ylim(-0.55, nrows - 0.45)
    ax3d.set_zlim(0.0, vmax * 1.10)
    ax3d.set_xticks(np.arange(ncols))
    ax3d.set_xticklabels(payload["col_labels"], fontsize=8.2)
    ax3d.set_yticks(np.arange(nrows))
    ax3d.set_yticklabels(payload["row_labels"], fontsize=8.2)
    ax3d.tick_params(axis="z", labelsize=8.4, pad=2)
    ax3d.set_xlabel(payload["col_axis_label"], fontsize=9.6, labelpad=10)
    ax3d.set_ylabel(payload["row_axis_label"], fontsize=9.6, labelpad=10)
    ax3d.set_zlabel(payload["value_label"], fontsize=9.6, labelpad=8)
    ax3d.set_title(payload["panel_b_title"], fontsize=11.5, fontweight="bold", pad=10, color="#1F242A")

    output_stem.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_stem.with_suffix(".png"), dpi=300, bbox_inches="tight", pad_inches=0.14)
    fig.savefig(output_stem.with_suffix(".pdf"), bbox_inches="tight", pad_inches=0.14)
    fig.savefig(output_stem.with_suffix(".svg"), bbox_inches="tight", pad_inches=0.14)
    plt.close(fig)


def main() -> None:
    ap = argparse.ArgumentParser(description="Render morandi-3d-bar-heatmap figure.")
    ap.add_argument("--config", default="", help="Optional JSON config path overriding matrix & labels")
    ap.add_argument("--out-stem", default="", help="Output file path without extension")
    args = ap.parse_args()

    cfg = json.loads(Path(args.config).read_text(encoding="utf-8")) if args.config else None
    out_stem = Path(args.out_stem) if args.out_stem else (ROOT / "outputs" / "morandi_3d_bar_heatmap_replica")
    make_figure(out_stem, cfg=cfg)


if __name__ == "__main__":
    main()
