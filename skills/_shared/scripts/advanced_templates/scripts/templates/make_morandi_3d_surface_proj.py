#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Morandi 3D Smooth Surface + Bottom Contourf Projection Template (`morandi-3d-surface-proj`)."""

from __future__ import annotations

import argparse
import json
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


def default_payload() -> dict:
    xs = np.linspace(-15.0, 35.0, 72)
    ys = np.linspace(0.65, 1.00, 68)
    X, Y = np.meshgrid(xs, ys)
    # Smooth coupled thermal-aging operational runtime margin surface
    temp_factor = np.exp(-((X - 21.0) / 24.0) ** 2)
    cold_cliff = 1.0 / (1.0 + np.exp(-(X + 3.5) / 4.2))
    soh_gain = (Y - 0.52) ** 0.85
    Z = 1.4 + 13.8 * temp_factor * (0.42 + 0.58 * cold_cliff) * soh_gain
    return {
        "X": X.tolist(),
        "Y": Y.tolist(),
        "Z": Z.tolist(),
        "xlabel": "Ambient Temperature (°C)",
        "ylabel": "State of Health (SOH)",
        "zlabel": "Effective Runtime (h)",
        "critical_level": 5.5,
        "critical_label": "Critical Reserve Threshold (5.5 h)",
        "cmap": "morandi_seq",
        "title": "Coupled Thermal–Aging Response Surface & Reserve Cliff",
        "elev": 32,
        "azim": -138,
    }


def make_figure(output_stem: Path, cfg: dict | None = None) -> None:
    payload = default_payload()
    if cfg:
        payload.update(cfg)

    X = np.asarray(payload["X"], dtype=float)
    Y = np.asarray(payload["Y"], dtype=float)
    Z = np.asarray(payload["Z"], dtype=float)
    cmap, ps = configure_style(str(payload.get("cmap", "morandi_seq")))

    z_min, z_max = float(np.min(Z)), float(np.max(Z))
    z_span = max(z_max - z_min, 1e-6)
    z_floor_raw = z_min - 0.38 * z_span
    z_min_bound = payload.get("z_min_bound", 0.0 if z_min >= 0.0 else None)
    z_floor = max(float(z_min_bound), z_floor_raw) if z_min_bound is not None else z_floor_raw
    norm = mpl.colors.Normalize(vmin=z_min, vmax=z_max)

    fig = plt.figure(figsize=(9.8, 6.6), facecolor="white")
    ax = fig.add_axes([0.04, 0.08, 0.78, 0.83], projection="3d")
    if ps is not None:
        ps.style_3d_axes(ax)
    else:
        for axis in (ax.xaxis, ax.yaxis, ax.zaxis):
            axis.pane.set_facecolor((0.97, 0.98, 0.99, 0.65))
            axis.pane.set_edgecolor("#DCE2EA")
            axis._axinfo["grid"]["color"] = (0.85, 0.87, 0.90, 0.8)
            axis._axinfo["grid"]["linewidth"] = 0.55

    surf = ax.plot_surface(
        X,
        Y,
        Z,
        cmap=cmap,
        norm=norm,
        rstride=2,
        cstride=2,
        linewidth=0.18,
        edgecolor=(1.0, 1.0, 1.0, 0.25),
        antialiased=True,
        shade=True,
        alpha=0.84,
    )

    # Bottom projection contours + critical cliff ridge highlight
    ax.contourf(X, Y, Z, zdir="z", offset=z_floor, levels=16, cmap=cmap, norm=norm, alpha=0.82)
    crit = payload.get("critical_level")
    if crit is not None:
        crit_f = float(crit)
        if z_min < crit_f < z_max:
            ax.contour(X, Y, Z, zdir="z", offset=z_floor, levels=[crit_f], colors=["#C86D5B"], linewidths=2.4)
            ax.contour(
                X,
                Y,
                Z + 0.018 * z_span,
                levels=[crit_f + 0.018 * z_span],
                colors=["#C86D5B"],
                linewidths=2.4,
                linestyles="--",
            )

    ax.set_xlim(float(np.min(X)), float(np.max(X)))
    ax.set_ylim(float(np.min(Y)), float(np.max(Y)))
    ax.set_zlim(z_floor, z_max + 0.08 * z_span)
    ax.view_init(elev=float(payload.get("elev", 32)), azim=float(payload.get("azim", -138)))
    ax.set_box_aspect((1.18, 1.15, 0.82))

    ax.set_xlabel(payload["xlabel"], fontsize=10.5, labelpad=10)
    ax.set_ylabel(payload["ylabel"], fontsize=10.5, labelpad=10)
    ax.set_zlabel(payload["zlabel"], fontsize=10.5, labelpad=8)
    ax.tick_params(labelsize=8.8, pad=3)
    ax.set_title(payload["title"], fontsize=12.0, fontweight="bold", pad=12, color="#1F242A")

    cax = fig.add_axes([0.855, 0.22, 0.020, 0.54])
    cbar = fig.colorbar(surf, cax=cax)
    if getattr(cbar, "solids", None) is not None:
        cbar.solids.set_rasterized(False)
        cbar.solids.set_edgecolor("face")
    cbar.outline.set_edgecolor("#B9C2CC")
    cbar.outline.set_linewidth(0.7)
    cbar.set_label(payload["zlabel"], fontsize=10.0, labelpad=8)
    cbar.ax.tick_params(labelsize=8.8)

    if crit is not None and payload.get("critical_label"):
        fig.text(
            0.44,
            0.035,
            f"Dashed contour boundary: {payload['critical_label']}",
            ha="center",
            fontsize=9.2,
            color="#A4503F",
            fontweight="medium",
        )

    output_stem.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_stem.with_suffix(".png"), dpi=300, bbox_inches="tight", pad_inches=0.14)
    fig.savefig(output_stem.with_suffix(".pdf"), bbox_inches="tight", pad_inches=0.14)
    fig.savefig(output_stem.with_suffix(".svg"), bbox_inches="tight", pad_inches=0.14)
    plt.close(fig)


def main() -> None:
    ap = argparse.ArgumentParser(description="Render morandi-3d-surface-proj figure.")
    ap.add_argument("--config", default="", help="Optional JSON config path")
    ap.add_argument("--out-stem", default="", help="Output file path without extension")
    args = ap.parse_args()

    cfg = json.loads(Path(args.config).read_text(encoding="utf-8")) if args.config else None
    out_stem = Path(args.out_stem) if args.out_stem else (ROOT / "outputs" / "morandi_3d_surface_proj_replica")
    make_figure(out_stem, cfg=cfg)


if __name__ == "__main__":
    main()
