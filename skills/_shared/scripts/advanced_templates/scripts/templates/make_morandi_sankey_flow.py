#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Morandi Pure-Matplotlib Multi-Stage Sankey / Alluvial Flow Template (`morandi-sankey-flow`)."""

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
from matplotlib.patches import FancyBboxPatch, PathPatch
from matplotlib.path import Path as MplPath


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


def default_payload() -> dict:
    return {
        "title": "System Energy Budget & Optimization Allocation Flow (mWh)",
        "unit": "mWh",
        "stages": [
            {
                "header": "Operating Demand",
                "nodes": [
                    {"id": "disp", "label": "Display & Backlight", "color": "#4E6E8E"},
                    {"id": "soc", "label": "SoC Compute", "color": "#D9A462"},
                    {"id": "rf", "label": "5G / Radio Front-End", "color": "#C86D5B"},
                    {"id": "bg", "label": "Background Daemons", "color": "#8E7A9E"},
                ],
            },
            {
                "header": "Coupled Subsystems",
                "nodes": [
                    {"id": "active", "label": "Active Pipeline", "color": "#4E6E8E"},
                    {"id": "thermal", "label": "Thermal Throttling", "color": "#C86D5B"},
                    {"id": "idle", "label": "Scheduled Sleep", "color": "#6D9A87"},
                ],
            },
            {
                "header": "Final Outcome",
                "nodes": [
                    {"id": "saved", "label": "Useful Work Saved", "color": "#6D9A87"},
                    {"id": "joule", "label": "Joule Dissipation", "color": "#C86D5B"},
                    {"id": "reserve", "label": "Margin Reserve", "color": "#9BA4AE"},
                ],
            },
        ],
        "flows": [
            {"source": "disp", "target": "active", "value": 920},
            {"source": "disp", "target": "idle", "value": 280},
            {"source": "soc", "target": "active", "value": 640},
            {"source": "soc", "target": "thermal", "value": 310},
            {"source": "rf", "target": "active", "value": 420},
            {"source": "rf", "target": "thermal", "value": 390},
            {"source": "bg", "target": "idle", "value": 340},
            {"source": "bg", "target": "thermal", "value": 100},
            {"source": "active", "target": "saved", "value": 1520},
            {"source": "active", "target": "joule", "value": 460},
            {"source": "thermal", "target": "joule", "value": 690},
            {"source": "thermal", "target": "reserve", "value": 110},
            {"source": "idle", "target": "saved", "value": 240},
            {"source": "idle", "target": "reserve", "value": 380},
        ],
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
                "svg.fonttype": "none",
                "pdf.fonttype": 42,
            }
        )

    stages = payload["stages"]
    flows = payload["flows"]
    unit = str(payload.get("unit", ""))

    # Compute flow totals per node
    in_sum: dict[str, float] = {}
    out_sum: dict[str, float] = {}
    for fl in flows:
        v = float(fl["value"])
        out_sum[fl["source"]] = out_sum.get(fl["source"], 0.0) + v
        in_sum[fl["target"]] = in_sum.get(fl["target"], 0.0) + v

    node_vals: dict[str, float] = {}
    stage_totals: list[float] = []
    for st in stages:
        st_tot = 0.0
        for nd in st["nodes"]:
            nid = nd["id"]
            val = float(nd.get("value", max(in_sum.get(nid, 0.0), out_sum.get(nid, 0.0), 1e-6)))
            node_vals[nid] = val
            st_tot += val
        stage_totals.append(st_tot)

    max_stage_val = max(stage_totals) or 1.0
    max_nodes = max(len(st["nodes"]) for st in stages)
    gap_y = 0.06
    usable_h = 0.82 - max(0, max_nodes - 1) * gap_y
    scale = usable_h / max_stage_val

    fig, ax = plt.subplots(figsize=(10.8, 5.6), facecolor="white")
    ax.set_facecolor("white")
    ax.axis("off")

    n_cols = len(stages)
    col_xs = [0.22 + i * ((0.78 - 0.22) / max(n_cols - 1, 1)) for i in range(n_cols)]
    bar_w = 0.030

    node_geom: dict[str, dict] = {}
    for ci, st in enumerate(stages):
        cx = col_xs[ci]
        col_h = stage_totals[ci] * scale + max(0, len(st["nodes"]) - 1) * gap_y
        # Center column vertically around y=0.49
        cur_top = 0.49 + col_h / 2.0
        ax.text(
            cx,
            0.945,
            st["header"],
            ha="center",
            va="bottom",
            fontsize=10.5,
            fontweight="bold",
            color="#2C3137",
        )
        ax.plot([cx - 0.06, cx + 0.06], [0.932, 0.932], color="#D6DCE3", lw=1.0)

        for nd in st["nodes"]:
            nid = nd["id"]
            h = node_vals[nid] * scale
            y0 = cur_top - h
            node_geom[nid] = {
                "col": ci,
                "x": cx,
                "y0": y0,
                "y1": cur_top,
                "color": nd["color"],
                "out_cursor": cur_top,
                "in_cursor": cur_top,
                "val": node_vals[nid],
                "label": nd["label"],
            }
            cur_top = y0 - gap_y

    # Draw cubic Bezier ribbons behind nodes
    for fl in flows:
        src = node_geom[fl["source"]]
        dst = node_geom[fl["target"]]
        h = float(fl["value"]) * scale

        sy1 = src["out_cursor"]
        sy0 = sy1 - h
        src["out_cursor"] = sy0

        dy1 = dst["in_cursor"]
        dy0 = dy1 - h
        dst["in_cursor"] = dy0

        x0 = src["x"] + bar_w / 2.0
        x1 = dst["x"] - bar_w / 2.0
        xm = (x0 + x1) / 2.0

        verts = [
            (x0, sy1),
            (xm, sy1),
            (xm, dy1),
            (x1, dy1),
            (x1, dy0),
            (xm, dy0),
            (xm, sy0),
            (x0, sy0),
            (x0, sy1),
        ]
        codes = [
            MplPath.MOVETO,
            MplPath.CURVE4,
            MplPath.CURVE4,
            MplPath.CURVE4,
            MplPath.LINETO,
            MplPath.CURVE4,
            MplPath.CURVE4,
            MplPath.CURVE4,
            MplPath.CLOSEPOLY,
        ]
        patch = PathPatch(
            MplPath(verts, codes),
            facecolor=src["color"],
            edgecolor="#FFFFFF",
            linewidth=0.5,
            alpha=0.40,
            zorder=2,
        )
        ax.add_patch(patch)

    # Draw crisp vertical rounded node bars + non-overlapping labels
    for nid, g in node_geom.items():
        h = g["y1"] - g["y0"]
        rect = FancyBboxPatch(
            (g["x"] - bar_w / 2.0, g["y0"]),
            bar_w,
            h,
            boxstyle="round,pad=0.002,rounding_size=0.008",
            facecolor=g["color"],
            edgecolor=_darken_hex(g["color"], 0.72),
            linewidth=1.0,
            zorder=4,
        )
        ax.add_patch(rect)

        val_str = f"{g['val']:.0f} {unit}".strip() if unit else f"{g['val']:.0f}"
        ym = (g["y0"] + g["y1"]) / 2.0
        if g["col"] == 0:
            ax.text(
                g["x"] - bar_w / 2.0 - 0.015,
                ym,
                f"{g['label']}\n({val_str})",
                ha="right",
                va="center",
                fontsize=9.0,
                fontweight="medium",
                color="#232830",
                zorder=5,
            )
        elif g["col"] == n_cols - 1:
            ax.text(
                g["x"] + bar_w / 2.0 + 0.015,
                ym,
                f"{g['label']}\n({val_str})",
                ha="left",
                va="center",
                fontsize=9.0,
                fontweight="medium",
                color="#232830",
                zorder=5,
            )
        else:
            ax.text(
                g["x"],
                ym,
                f"{g['label']}\n({val_str})",
                ha="center",
                va="center",
                fontsize=8.6,
                fontweight="bold",
                color="#232830",
                zorder=6,
                bbox=dict(boxstyle="round,pad=0.22", fc=(1.0, 1.0, 1.0, 0.88), ec="#DCE2EA", lw=0.6),
            )

    ax.set_xlim(0.0, 1.0)
    ax.set_ylim(0.02, 1.01)
    fig.suptitle(payload["title"], x=0.5, y=0.99, fontsize=12.2, fontweight="bold", color="#1F242A")

    output_stem.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_stem.with_suffix(".png"), dpi=300, bbox_inches="tight", pad_inches=0.14)
    fig.savefig(output_stem.with_suffix(".pdf"), bbox_inches="tight", pad_inches=0.14)
    fig.savefig(output_stem.with_suffix(".svg"), bbox_inches="tight", pad_inches=0.14)
    plt.close(fig)


def main() -> None:
    ap = argparse.ArgumentParser(description="Render morandi-sankey-flow figure.")
    ap.add_argument("--config", default="", help="Optional JSON config path")
    ap.add_argument("--out-stem", default="", help="Output file path without extension")
    args = ap.parse_args()

    cfg = json.loads(Path(args.config).read_text(encoding="utf-8")) if args.config else None
    out_stem = Path(args.out_stem) if args.out_stem else (ROOT / "outputs" / "morandi_sankey_flow_replica")
    make_figure(out_stem, cfg=cfg)


if __name__ == "__main__":
    main()
