#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""SVG -> PNG 高保真渲染（机理示意图等矢量图专用）。

背景：macOS qlmanage 渲染 SVG 会非等比缩放并裁切右侧内容（实测），
本脚本按优先级自动选择可靠后端：
  1. rsvg-convert（librsvg，最准确）
  2. cairosvg（需要 cairo 系统库）
  3. svglib -> PDF -> pdftoppm（纯 Python 回退，本项目验证可用）
     （若 pdftoppm 不可用则回退 qlmanage 渲染 PDF，macOS）

用法：
    python render_svg.py input.svg output.png [--dpi 300] [--width 3000]

输出 PNG 会写入 300 DPI 元数据（满足 figure_qa 的 min-dpi 检查）。
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def render_rsvg(svg: Path, out: Path, dpi: int, width: int | None) -> bool:
    if not shutil.which("rsvg-convert"):
        return False
    cmd = ["rsvg-convert", "-d", str(dpi), "-p", str(dpi)]
    if width:
        cmd += ["-w", str(width)]
    cmd += [str(svg), "-o", str(out)]
    subprocess.run(cmd, check=True)
    return True


def render_cairosvg(svg: Path, out: Path, width: int | None) -> bool:
    try:
        import cairosvg
        scale = (width or 3000) / 1000.0  # 以 1000 单位宽为基准
        cairosvg.svg2png(url=str(svg), write_to=str(out), scale=scale)
        return True
    except Exception:
        return False


def render_svglib_pipeline(svg: Path, out: Path, dpi: int) -> bool:
    """svglib -> PDF（原生尺寸）-> pdftoppm/qlmanage 渲染。已验证防裁切。"""
    try:
        from svglib.svglib import svg2rlg
        from reportlab.graphics import renderPDF
    except Exception:
        return False
    with tempfile.TemporaryDirectory() as td:
        pdf = Path(td) / "page.pdf"
        drawing = svg2rlg(str(svg))
        if drawing is None:
            return False
        renderPDF.drawToFile(drawing, str(pdf))
        if shutil.which("pdftoppm"):
            prefix = out.with_suffix("")
            subprocess.run(["pdftoppm", "-png", "-r", str(dpi), str(pdf), str(prefix)],
                           check=True, capture_output=True)
            pngs = sorted(prefix.parent.glob(prefix.name + "-*.png"))
            if not pngs:
                return False
            pngs[0].replace(out)
        elif sys.platform == "darwin" and shutil.which("qlmanage"):
            subprocess.run(["qlmanage", "-t", "-s", str(3000), "-o", td, str(pdf)],
                           check=True, capture_output=True)
            src = Path(td) / "page.pdf.png"
            if not src.exists():
                return False
            src.replace(out)
        else:
            return False
    # 写入 300 DPI 元数据
    try:
        from PIL import Image
        im = Image.open(out)
        im.save(out, dpi=(300, 300))
    except Exception:
        pass
    return True


def main() -> int:
    ap = argparse.ArgumentParser(description="SVG -> PNG 高保真渲染")
    ap.add_argument("svg")
    ap.add_argument("out")
    ap.add_argument("--dpi", type=int, default=300)
    ap.add_argument("--width", type=int, default=0, help="输出宽度 px（默认自动）")
    args = ap.parse_args()

    svg = Path(args.svg)
    out = Path(args.out)
    if not svg.exists():
        print(f"[错误] SVG 不存在: {svg}")
        return 2
    out.parent.mkdir(parents=True, exist_ok=True)

    width = args.width or None
    if render_rsvg(svg, out, args.dpi, width):
        print(f"[OK] rsvg-convert -> {out}")
        return 0
    if render_cairosvg(svg, out, width):
        print(f"[OK] cairosvg -> {out}")
        return 0
    if render_svglib_pipeline(svg, out, args.dpi):
        print(f"[OK] svglib+PDF 回退 -> {out}")
        return 0
    print("[错误] 无可用渲染后端：请安装 librsvg（brew install librsvg）、cairosvg 或 svglib+pdftoppm")
    return 1


if __name__ == "__main__":
    sys.exit(main())
