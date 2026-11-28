#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""外包 3D/写实视觉资产近白背景自动去背与羽化裁剪工具（纯 Pillow + NumPy）。

用法：
    python asset_cutout.py --in raw_battery.png --out work/figures/assets/battery_cutout.png
    python asset_cutout.py --in raw.png --out cutout.png --threshold 242 --chroma-tol 18 --feather 1.5 --pad 8
    python asset_cutout.py --self-test

原理：
- 仅从图像四条外边界向内执行 4-连通泛洪扩散，精确剥离外部近白底，
  完整保护主体内部高光与纯白局部（绝不把内部白色区域镂空）。
- 对前景边缘执行轻微羽化与极轻微去白边净化（de-fringe），并紧凑裁边留出安全透明边距。
"""

from __future__ import annotations

import argparse
import sys
import tempfile
from collections import deque
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageFilter


def cutout_white_bg(
    in_path: Path,
    out_path: Path,
    threshold: int = 242,
    chroma_tol: int = 18,
    feather_px: float = 1.5,
    pad_px: int = 8,
) -> dict[str, Any]:
    """Strip exterior near-white background via 4-connected border flood-fill, feather edges, and tight-crop."""
    if not in_path.is_file():
        raise FileNotFoundError(f"Input image not found: {in_path}")

    with Image.open(in_path) as im:
        rgba = im.convert("RGBA")

    arr = np.array(rgba, dtype=np.uint8)
    h, w, _ = arr.shape
    rgb = arr[:, :, :3].astype(np.int16)
    orig_alpha = arr[:, :, 3]

    rgb_min = rgb.min(axis=2)
    rgb_max = rgb.max(axis=2)
    bg_cand = (rgb_min >= threshold) & ((rgb_max - rgb_min) <= chroma_tol)

    # 4-connected BFS strictly seeded from outer 4 image borders so internal white highlights survive
    ext_bg = np.zeros((h, w), dtype=bool)
    q: deque[tuple[int, int]] = deque()

    def try_seed(r: int, c: int) -> None:
        if bg_cand[r, c] and not ext_bg[r, c]:
            ext_bg[r, c] = True
            q.append((r, c))

    for c in range(w):
        try_seed(0, c)
        try_seed(h - 1, c)
    for r in range(1, h - 1):
        try_seed(r, 0)
        try_seed(r, w - 1)

    while q:
        r, c = q.popleft()
        if r > 0 and bg_cand[r - 1, c] and not ext_bg[r - 1, c]:
            ext_bg[r - 1, c] = True
            q.append((r - 1, c))
        if r + 1 < h and bg_cand[r + 1, c] and not ext_bg[r + 1, c]:
            ext_bg[r + 1, c] = True
            q.append((r + 1, c))
        if c > 0 and bg_cand[r, c - 1] and not ext_bg[r, c - 1]:
            ext_bg[r, c - 1] = True
            q.append((r, c - 1))
        if c + 1 < w and bg_cand[r, c + 1] and not ext_bg[r, c + 1]:
            ext_bg[r, c + 1] = True
            q.append((r, c + 1))

    fg_mask = (~ext_bg) & (orig_alpha > 0)
    fg_u8 = (fg_mask.astype(np.uint8)) * 255

    if feather_px > 0.1 and np.any(fg_mask):
        # Smooth only the thin outer rim of the foreground mask without bleeding outside or eroding deep interior
        blurred = np.array(
            Image.fromarray(fg_u8, mode="L").filter(ImageFilter.GaussianBlur(radius=float(feather_px))),
            dtype=np.float32,
        )
        # Remap blurred exterior spill to zero, and preserve interior (>~1px inside) fully opaque
        eroded = np.array(
            Image.fromarray(fg_u8, mode="L").filter(ImageFilter.MinFilter(size=3)),
            dtype=bool,
        )
        alpha_f = np.where(ext_bg, 0.0, np.where(eroded, 255.0, np.clip((blurred - 40.0) * (255.0 / 200.0), 0.0, 255.0)))
        new_alpha = np.minimum(orig_alpha.astype(np.float32), alpha_f).round().astype(np.uint8)
    else:
        new_alpha = np.where(fg_mask, orig_alpha, 0).astype(np.uint8)

    out_arr = arr.copy()
    out_arr[:, :, 3] = new_alpha

    # Clean semi-transparent rim pixels from chalky white fringing (unmix toward border fg tone slightly)
    semi = (new_alpha > 0) & (new_alpha < 255) & (rgb_min > 180)
    if np.any(semi):
        a_norm = np.clip(new_alpha[semi] / 255.0, 0.15, 1.0)[:, None]
        fg_est = (rgb[semi] - (1.0 - a_norm) * 255.0) / a_norm
        out_arr[semi, :3] = np.clip(np.round(fg_est), 0, 255).astype(np.uint8)

    # Tight bounding-box crop with safe transparent padding
    nz = np.argwhere(new_alpha > 0)
    if nz.size > 0:
        r0, c0 = nz.min(axis=0)
        r1, c1 = nz.max(axis=0) + 1
        cropped = out_arr[r0:r1, c0:c1]
        if pad_px > 0:
            ch, cw, _ = cropped.shape
            canvas = np.zeros((ch + 2 * pad_px, cw + 2 * pad_px, 4), dtype=np.uint8)
            canvas[pad_px : pad_px + ch, pad_px : pad_px + cw] = cropped
            cropped = canvas
    else:
        cropped = out_arr

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_im = Image.fromarray(cropped, mode="RGBA")
    out_im.save(out_path, format="PNG")

    removed_ratio = float(np.mean(ext_bg))
    return {
        "in_path": str(in_path),
        "out_path": str(out_path),
        "orig_size": [int(w), int(h)],
        "cropped_size": [int(out_im.width), int(out_im.height)],
        "bg_removed_ratio": round(removed_ratio, 4),
    }


def self_test() -> int:
    with tempfile.TemporaryDirectory(prefix="cutout_test_") as td:
        tdir = Path(td)
        raw_p = tdir / "raw.png"
        out_p = tdir / "cutout.png"

        # Construct synthetic 120x120 image:
        # - pure white outer background (255,255,255)
        # - Morandi blue square object at [20:100, 20:100]
        # - pure white interior highlight square at [45:75, 45:75] (MUST stay opaque!)
        arr = np.full((120, 120, 3), 255, dtype=np.uint8)
        arr[20:100, 20:100] = (78, 110, 142)
        arr[45:75, 45:75] = (255, 255, 255)
        Image.fromarray(arr, mode="RGB").save(raw_p)

        info = cutout_white_bg(raw_p, out_p, threshold=242, feather_px=1.2, pad_px=6)
        assert out_p.is_file()
        with Image.open(out_p) as res:
            res_arr = np.array(res.convert("RGBA"))
            # Cropped should be smaller than original (80 + 2*6 = 92)
            assert res.width <= 96 and res.height <= 96, info
            # Outer corner padding must be completely transparent
            assert res_arr[0, 0, 3] == 0
            # Object rim (inside padding) must be opaque
            assert res_arr[20, 20, 3] == 255
            # Interior white highlight MUST remain opaque (alpha == 255), NOT punched out!
            ch, cw = res_arr.shape[0] // 2, res_arr.shape[1] // 2
            assert res_arr[ch, cw, 3] == 255, f"Interior white highlight was punched out: {res_arr[ch, cw]}"

    print("[SELF-TEST] PASS asset_cutout (exterior border flood-fill, internal white preserved, tight crop)")
    return 0


def main() -> int:
    if "--self-test" in sys.argv:
        return self_test()
    ap = argparse.ArgumentParser(description="外包 3D/写实视觉资产近白背景自动去背工具")
    ap.add_argument("--in", dest="in_path", required=True, help="输入 PNG/JPG/WebP 图片路径")
    ap.add_argument("--out", dest="out_path", required=True, help="输出透明通道 PNG 路径")
    ap.add_argument("--threshold", type=int, default=242, help="近白亮度阈值 0..255（默认 242）")
    ap.add_argument("--chroma-tol", type=int, default=18, help="最大通道差容忍度（默认 18）")
    ap.add_argument("--feather", type=float, default=1.5, help="边缘柔化半径 px（默认 1.5）")
    ap.add_argument("--pad", type=int, default=8, help="紧凑裁边透明边距 px（默认 8）")
    ap.add_argument("--self-test", action="store_true", help="运行内置自检")
    args = ap.parse_args()

    info = cutout_white_bg(
        Path(args.in_path),
        Path(args.out_path),
        threshold=args.threshold,
        chroma_tol=args.chroma_tol,
        feather_px=args.feather,
        pad_px=args.pad,
    )
    print(
        f"[asset_cutout] OK: {info['in_path']} {info['orig_size']} -> "
        f"{info['out_path']} {info['cropped_size']} (removed {info['bg_removed_ratio']:.1%})"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
