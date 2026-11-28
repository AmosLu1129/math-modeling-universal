#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Morandi Before-vs-After Dumbbell Comparison Template (`morandi-dumbbell`)."""

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


def default_payload() -> dict:
    return {
        "items": [
            {"label": "Sub-Zero GPS Navigation", "before": 4.2, "after": 5.9},
            {"label": "5G Social Streaming", "before": 6.1, "after": 7.6},
            {"label": "4K Video Recording", "before": 5.3, "after": 6.5},
            {"label": "Mixed Urban Commute", "before": 7.4, "after": 8.8},
            {"label": "Outdoor Map Routing", "before": 6.8, "after": 8.4},
            {"label": "Indoor Office Wi-Fi", "before": 9.8, "after": 11.1},
            {"label": "4G Standby Reserve", "before": 14.5, "after": 16.4},
        ],
        "before_name": "Before (Unoptimized Policy)",
        "after_name": "After (Coupled Control Policy)",
        "xlabel": "Predicted Device Endurance (hours)",
        "unit": "h",
        "delta_mode": "pct",  # "pct" or "abs"
        "higher_is_better": True,
        "title": "Scenario-Level Endurance Gains: Baseline vs. Coupled Optimization",
    }


def make_figure(output_stem: Path, cfg: dict | None = None) -> None:
    payload = default_payload()
    if cfg:
        payload.update(cfg)

    ps = _try_import_plot_style()
    if ps is not None:
        ps.apply("morandi_journal")
    else:
        mpl.rcParams.update(
            {
                "font.family": "sans-serif",
                "font.sans-serif": ["Arial", "Helvetica", "Microsoft YaHei", "DejaVu Sans"],
                "axes.unicode_minus": False,
                "mathtext.fontset": "stixsans",
                "svg.fonttype": "none",
                "pdf.fonttype": 42,
            }
        )

    items = list(payload["items"])
    n = len(items)
    ys = np.arange(n)
    before_vals = np.array([float(it["before"]) for it in items])
    after_vals = np.array([float(it["after"]) for it in items])
    labels = [str(it["label"]) for it in items]

    all_v = np.concatenate([before_vals, after_vals])
    v_min, v_max = float(np.min(all_v)), float(np.max(all_v))
    span = max(v_max - v_min, 1e-6)
    x_left = max(0.0, v_min - 0.14 * span) if v_min >= 0 else (v_min - 0.14 * span)
    x_right = v_max + 0.15 * span
    badge_x = v_max + 0.22 * span

    fig, ax = plt.subplots(figsize=(9.6, max(4.2, 0.56 * n + 1.4)), facecolor="white")
    ax.set_facecolor("white")
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color("#3A3F47")
    ax.spines["bottom"].set_linewidth(0.85)
    ax.xaxis.grid(True, color="#EAECEF", linestyle="-", linewidth=0.65)
    ax.yaxis.grid(False)
    ax.set_axisbelow(True)

    higher_better = bool(payload.get("higher_is_better", True))
    delta_mode = str(payload.get("delta_mode", "pct"))
    unit = str(payload.get("unit", ""))

    # Subtle alternating zebra strips for horizontal readability
    for idx in range(n):
        if idx % 2 == 0:
            ax.axhspan(idx - 0.42, idx + 0.42, color="#F7F8FA", zorder=0)

    for idx in range(n):
        b, a = before_vals[idx], after_vals[idx]
        improved = (a >= b) if higher_better else (a <= b)
        seg_col = "#6D9A87" if improved else "#C86D5B"
        dot_after_col = "#4E6E8E" if improved else "#C86D5B"
        edge_after_col = "#344A61" if improved else "#964E40"

        ax.plot([b, a], [idx, idx], color=seg_col, linewidth=3.4, alpha=0.62, solid_capstyle="round", zorder=2)

        # Direct point annotations away from connector
        left_is_before = b <= a
        pad_pt = span * 0.025
        ax.text(
            b - pad_pt if left_is_before else b + pad_pt,
            idx,
            f"{b:.1f}",
            ha="right" if left_is_before else "left",
            va="center",
            fontsize=8.6,
            color="#6C757D",
            zorder=4,
        )
        ax.text(
            a + pad_pt if left_is_before else a - pad_pt,
            idx,
            f"{a:.1f}",
            ha="left" if left_is_before else "right",
            va="center",
            fontsize=8.8,
            fontweight="bold",
            color="#232830",
            zorder=4,
        )

        # Delta badge on right margin
        if delta_mode == "pct" and abs(b) > 1e-9:
            pct = (a - b) / abs(b) * 100.0
            delta_txt = f"{pct:+.1f}%"
        else:
            diff = a - b
            delta_txt = f"{diff:+.2f}{(' ' + unit) if unit else ''}"
        badge_fc = "#EEF4F1" if improved else "#F9ECE9"
        badge_tc = "#3E6B58" if improved else "#9E4635"
        ax.text(
            badge_x,
            idx,
            delta_txt,
            ha="center",
            va="center",
            fontsize=8.8,
            fontweight="bold",
            color=badge_tc,
            bbox=dict(boxstyle="round,pad=0.26", fc=badge_fc, ec=seg_col, lw=0.7),
            zorder=5,
        )

    ax.scatter(
        before_vals,
        ys,
        s=96,
        color="#FFFFFF",
        edgecolor="#88929E",
        linewidth=2.0,
        zorder=3,
        label=payload["before_name"],
    )
    ax.scatter(
        after_vals,
        ys,
        s=112,
        color="#4E6E8E",
        edgecolor="#33495F",
        linewidth=1.4,
        zorder=4,
        label=payload["after_name"],
    )

    ax.set_yticks(ys)
    ax.set_yticklabels(labels, fontsize=9.8, fontweight="medium", color="#232830")
    ax.tick_params(axis="y", length=0)
    ax.tick_params(axis="x", direction="out", colors="#3A3F47", labelsize=9.2)
    ax.set_xlim(x_left, badge_x + 0.14 * span)
    ax.set_ylim(-0.6, n - 0.35)
    ax.set_xlabel(payload["xlabel"], fontsize=10.8, labelpad=8, color="#2C3137")
    ax.set_title(payload["title"], fontsize=12.0, fontweight="bold", pad=28, color="#1F242A")

    ax.legend(
        frameon=False,
        loc="lower left",
        bbox_to_anchor=(0.0, 1.01),
        ncol=2,
        fontsize=9.5,
        handletextpad=0.4,
        columnspacing=1.8,
    )

    output_stem.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_stem.with_suffix(".png"), dpi=300, bbox_inches="tight", pad_inches=0.14)
    fig.savefig(output_stem.with_suffix(".pdf"), bbox_inches="tight", pad_inches=0.14)
    fig.savefig(output_stem.with_suffix(".svg"), bbox_inches="tight", pad_inches=0.14)
    plt.close(fig)


def main() -> None:
    ap = argparse.ArgumentParser(description="Render morandi-dumbbell figure.")
    ap.add_argument("--config", default="", help="Optional JSON config path")
    ap.add_argument("--out-stem", default="", help="Output file path without extension")
    args = ap.parse_args()

    cfg = json.loads(Path(args.config).read_text(encoding="utf-8")) if args.config else None
    out_stem = Path(args.out_stem) if args.out_stem else (ROOT / "outputs" / "morandi_dumbbell_replica")
    make_figure(out_stem, cfg=cfg)


if __name__ == "__main__":
    main()
