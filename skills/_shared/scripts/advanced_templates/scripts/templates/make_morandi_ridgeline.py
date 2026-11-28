#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Morandi Layered KDE Ridgeline Plot Template (`morandi-ridgeline`)."""

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


def _darken_hex(hex_color: str, factor: float = 0.72) -> str:
    h = hex_color.strip().lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"#{int(round(r * factor)):02x}{int(round(g * factor)):02x}{int(round(b * factor)):02x}"


def _gaussian_kde(samples: np.ndarray, grid: np.ndarray) -> np.ndarray:
    x = np.asarray(samples, dtype=float)
    n = max(len(x), 2)
    std = float(np.std(x, ddof=1)) if np.std(x) > 1e-9 else 1.0
    q75, q25 = np.percentile(x, [75, 25])
    iqr_scale = (q75 - q25) / 1.34 if q75 > q25 else std
    sigma = min(std, iqr_scale) if iqr_scale > 1e-9 else std
    bw = max(1.06 * sigma * (n ** (-0.2)) * 1.15, (grid[-1] - grid[0]) * 0.025)
    diff = (grid[:, None] - x[None, :]) / bw
    dens = np.mean(np.exp(-0.5 * diff * diff), axis=1) / (bw * np.sqrt(2.0 * np.pi))
    return dens


def default_payload() -> dict:
    rng = np.random.default_rng(2026042)
    groups = [
        {"label": "High-Load Navigation", "samples": np.concatenate([rng.normal(4.8, 0.65, 220), rng.normal(6.0, 0.45, 70)]).tolist()},
        {"label": "Urban Commute Mixed", "samples": rng.normal(6.3, 0.78, 280).tolist()},
        {"label": "Adaptive Thermal Policy", "samples": rng.normal(7.7, 0.62, 280).tolist()},
        {"label": "Mild 실내 Baseline".replace("실내", "Office"), "samples": rng.normal(8.8, 0.72, 280).tolist()},
        {"label": "Power-Saving Standby", "samples": np.concatenate([rng.normal(10.1, 0.60, 230), rng.normal(11.3, 0.50, 60)]).tolist()},
    ]
    return {
        "groups": groups,
        "xlabel": "Effective Battery Endurance (hours)",
        "title": "Posterior Endurance Distributions Across Operating Regimes",
        "unit": "h",
        "overlap": 0.42,
    }


def make_figure(output_stem: Path, cfg: dict | None = None) -> None:
    payload = default_payload()
    if cfg:
        payload.update(cfg)

    ps = _try_import_plot_style()
    if ps is not None:
        pal = ps.apply("morandi_journal")
    else:
        pal = ["#4E6E8E", "#C86D5B", "#6D9A87", "#D9A462", "#8E7A9E", "#9BA4AE"]
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

    groups = payload["groups"]
    all_vals = np.concatenate([np.asarray(g["samples"], dtype=float) for g in groups])
    pad = (np.max(all_vals) - np.min(all_vals)) * 0.14 + 1e-6
    x_min, x_max = float(np.min(all_vals) - pad), float(np.max(all_vals) + pad)
    x_grid = np.linspace(x_min, x_max, 420)

    kdes = [_gaussian_kde(np.asarray(g["samples"], dtype=float), x_grid) for g in groups]
    max_dens = max(float(np.max(d)) for d in kdes) or 1.0
    step = 0.72
    height_scale = (step * (1.0 + float(payload.get("overlap", 0.42)))) / max_dens

    fig, ax = plt.subplots(figsize=(9.0, 5.4), facecolor="white")
    ax.set_facecolor("white")
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color("#3A3F47")
    ax.spines["bottom"].set_linewidth(0.85)
    ax.xaxis.grid(True, color="#EAECEF", linestyle="-", linewidth=0.6)
    ax.yaxis.grid(False)
    ax.set_axisbelow(True)

    n = len(groups)
    unit = str(payload.get("unit", ""))
    for idx, (grp, dens) in enumerate(zip(groups, kdes)):
        # Bottom-to-top ordering so upper peaks sit neatly behind lower foreground crests
        layer = n - 1 - idx
        y0 = idx * step
        y_top = y0 + dens * height_scale
        color = pal[idx % len(pal)]
        edge_col = _darken_hex(color, 0.72)
        z_base = (n - idx) * 10

        ax.fill_between(x_grid, y0, y_top, color=color, alpha=0.80, zorder=z_base)
        # White outer crest halo makes overlapping ridges crisp and legible
        ax.plot(x_grid, y_top, color="#FFFFFF", linewidth=2.8, zorder=z_base + 1)
        ax.plot(x_grid, y_top, color=edge_col, linewidth=1.25, zorder=z_base + 2)
        ax.hlines(y0, x_min, x_max, colors="#DCE1E8", linewidths=0.75, zorder=z_base + 0.5)

        med = float(np.median(grp["samples"]))
        med_y = float(np.interp(med, x_grid, y_top))
        ax.vlines(med, y0, med_y, colors="#232830", linestyles="--", linewidths=1.1, alpha=0.85, zorder=z_base + 3)
        ax.scatter([med], [med_y], color="#FFFFFF", edgecolor=edge_col, s=28, linewidth=1.2, zorder=z_base + 4)

        suffix = f" {unit}".rstrip() if unit else ""
        ax.text(
            med + (x_max - x_min) * 0.015,
            y0 + step * 0.14,
            f"Med = {med:.2f}{suffix}",
            ha="left",
            va="bottom",
            fontsize=8.6,
            fontweight="medium",
            color="#2C3137",
            zorder=z_base + 5,
        )

    ax.set_xlim(x_min, x_max)
    ax.set_ylim(-0.08, (n - 1) * step + step * (1.12 + float(payload.get("overlap", 0.42))))
    ax.set_yticks([i * step + 0.16 * step for i in range(n)])
    ax.set_yticklabels([grp["label"] for grp in groups], fontsize=9.8, fontweight="bold", color="#232830")
    ax.tick_params(axis="y", length=0, pad=8)
    ax.tick_params(axis="x", direction="out", colors="#3A3F47", labelsize=9.5)
    ax.set_xlabel(payload["xlabel"], fontsize=11.0, labelpad=8, color="#2C3137")
    ax.set_title(payload["title"], fontsize=12.0, fontweight="bold", pad=12, color="#1F242A")

    output_stem.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_stem.with_suffix(".png"), dpi=300, bbox_inches="tight", pad_inches=0.12)
    fig.savefig(output_stem.with_suffix(".pdf"), bbox_inches="tight", pad_inches=0.12)
    fig.savefig(output_stem.with_suffix(".svg"), bbox_inches="tight", pad_inches=0.12)
    plt.close(fig)


def main() -> None:
    ap = argparse.ArgumentParser(description="Render morandi-ridgeline figure.")
    ap.add_argument("--config", default="", help="Optional JSON config path")
    ap.add_argument("--out-stem", default="", help="Output file path without extension")
    args = ap.parse_args()

    cfg = json.loads(Path(args.config).read_text(encoding="utf-8")) if args.config else None
    out_stem = Path(args.out_stem) if args.out_stem else (ROOT / "outputs" / "morandi_ridgeline_replica")
    make_figure(out_stem, cfg=cfg)


if __name__ == "__main__":
    main()
