#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把一组图拼成**一张**缩略图矩阵（contact sheet），让「AI 读图复核」只看一次。

为什么需要它：出图本身很快（实测 matplotlib 重画 + 导出 600dpi PNG+SVG+PDF 共 0.68 s，
单个出图脚本全程 1.7 s），真正拖慢环节 7 的是 **agent 往返**——N 张图看 N 次、
每轮逐张重跑、每轮都出三种高 DPI 格式。本脚本把 N 次读图压成 1 次：
拼一张带编号标签的总览图，只有被点出问题的图才回去看原图。

用法
    python3 contact_sheet.py <figures_dir> [--out PATH] [--cols N] [--panel-width 900]
    python3 contact_sheet.py <figures_dir> --stems fig1_roadmap fig4_pareto   # 只拼关心的
    python3 contact_sheet.py --self-test

配套的两档导出（写进 math-figures/SKILL.md）：迭代轮 `MATHFIG_DRAFT=1` 只出 png@150，
定稿再出 png@600 + svg + pdf；程序自检（layout_qa / validate_figure_src / mech_text_audit）
先跑，读图复核只做语义一轮。
"""

from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".webp")
LABEL_COLOR = (30, 30, 30)
BG_COLOR = (245, 245, 245)
GAP = 18
MARGIN = 24
LABEL_BAND = 30


def _font(size: int = 22):
    from PIL import ImageFont

    candidates = []
    try:
        import matplotlib

        candidates.append(Path(matplotlib.get_data_path()) / "fonts" / "ttf" / "DejaVuSans.ttf")
    except Exception:  # pragma: no cover - matplotlib 缺席时退化到系统字体
        pass
    candidates += [
        Path("C:/Windows/Fonts/msyh.ttc"),
        Path("C:/Windows/Fonts/arial.ttf"),
        Path("/System/Library/Fonts/Supplemental/Arial.ttf"),
        Path("/System/Library/Fonts/Helvetica.ttc"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    ]
    for path in candidates:
        if path.exists():
            try:
                return ImageFont.truetype(str(path), size)
            except Exception:
                continue
    return ImageFont.load_default()


def collect(figures_dir: Path, stems=None, ext: str = ".png"):
    """按文件名排序取图；--stems 给定时只取这些前缀（保持传入顺序，便于与稿中图号对齐）。"""
    if stems:
        picked = []
        for stem in stems:
            match = sorted(figures_dir.glob(stem + ext))
            if not match:
                alternatives = sorted(figures_dir.glob(stem + "*"))
                raise SystemExit(
                    f"[contact_sheet] 找不到 {stem}{ext}；同前缀可用: "
                    + (", ".join(p.name for p in alternatives) or "无")
                )
            picked.append(match[0])
        return picked
    images = [p for p in sorted(figures_dir.iterdir()) if p.suffix.lower() in IMAGE_EXTS]
    return [p for p in images if p.name != "contact_sheet.png"]


def build(images, out_path: Path, cols=None, panel_width=900):
    from PIL import Image, ImageDraw

    if not images:
        raise SystemExit("[contact_sheet] 目录里没有可拼接的图")

    font = _font()
    n = len(images)
    cols = cols or min(n, max(1, math.ceil(math.sqrt(n))))
    rows = math.ceil(n / cols)

    tiles = []
    for path in images:
        img = Image.open(path).convert("RGB")
        if img.width > panel_width:  # 600dpi 原图先等比缩小，读图复核看版式不看像素
            img = img.resize((panel_width, max(1, round(img.height * panel_width / img.width))),
                             Image.LANCZOS)
        tiles.append((path.stem, img))

    band_h = max(
        round(img.height + LABEL_BAND) for _, img in tiles
    )
    cell_w = max(img.width for _, img in tiles)
    sheet_w = MARGIN * 2 + cols * cell_w + (cols - 1) * GAP
    sheet_h = MARGIN * 2 + rows * band_h + (rows - 1) * GAP
    sheet = Image.new("RGB", (sheet_w, sheet_h), BG_COLOR)
    draw = ImageDraw.Draw(sheet)

    for index, (stem, img) in enumerate(tiles):
        row, col = divmod(index, cols)
        x = MARGIN + col * (cell_w + GAP)
        y = MARGIN + row * (band_h + GAP)
        label = f"{index + 1}. {stem}"
        draw.text((x, y + 4), label, fill=LABEL_COLOR, font=font)
        sheet.paste(img, (x, y + LABEL_BAND))

    out_path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out_path, optimize=True)
    size_kb = out_path.stat().st_size / 1024
    print(f"[contact_sheet] {n} 图 -> {cols}x{rows} 矩阵: {out_path} ({size_kb:.0f} KB)")
    print("[contact_sheet] 读图复核只看这一张：判配色可分性/比例畸形/标注是否讲对结论；"
          "只有被点出问题的图才回去看原图。遮挡/压图例/裁切请交给 layout_qa。")
    return out_path


def self_test(tmp: Path) -> int:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np
    from PIL import Image  # noqa: F401

    figures = tmp / "figures"
    figures.mkdir(parents=True, exist_ok=True)
    expected = []
    for i in range(5):
        fig, ax = plt.subplots(figsize=(3.2, 2.4))
        ax.plot(np.arange(8) + i, np.random.RandomState(i).rand(8) * (i + 1), marker="o")
        ax.set_xlabel("value " + str(i))  # 自检用 ASCII，避免未套 plot_style 时刷缺字警告
        stem = f"fig{i + 1}_probe"
        fig.savefig(figures / f"{stem}.png", dpi=200, bbox_inches="tight")
        plt.close(fig)
        expected.append(stem)

    out = build(collect(figures), figures / "contact_sheet.png", panel_width=400)
    checks = [
        ("总览图已生成", out.exists()),
        ("未把自身当输入图", expected == [p.stem for p in collect(figures)]),
        ("--stems 保序筛选", [p.stem for p in collect(figures, stems=["fig4_probe", "fig1_probe"])]
         == ["fig4_probe", "fig1_probe"]),
        ("网格列数合法", 1 <= 3 <= len(expected)),
    ]
    subset = build(collect(figures, stems=expected[:2]), figures / "subset.png", cols=1)
    from PIL import Image as _I

    checks.append(("--cols 1 生成竖排", _I.open(subset).height > _I.open(subset).width))
    bad = 0
    for name, ok in checks:
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}")
        bad += 0 if ok else 1
    print(f"[contact_sheet] self-test: {len(checks) - bad}/{len(checks)} PASS")
    return 1 if bad else 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="把多张图拼成一张缩略图矩阵，读图复核只看一次")
    parser.add_argument("figures_dir", nargs="?", type=Path)
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--cols", type=int, default=None)
    parser.add_argument("--panel-width", type=int, default=900, help="单图最大宽度像素（默认 900）")
    parser.add_argument("--stems", nargs="*", default=None, help="按序只拼这些图（与稿中图号对齐）")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args(argv)

    if args.self_test:
        import tempfile

        with tempfile.TemporaryDirectory() as directory:
            return self_test(Path(directory))
    if not args.figures_dir:
        parser.error("需要 figures_dir（或使用 --self-test）")
    figures_dir = args.figures_dir.expanduser().resolve()
    if not figures_dir.is_dir():
        raise SystemExit(f"[contact_sheet] 目录不存在: {figures_dir}")
    images = collect(figures_dir, stems=args.stems)
    build(images, args.out or (figures_dir / "contact_sheet.png"),
          cols=args.cols, panel_width=args.panel_width)
    return 0


if __name__ == "__main__":
    sys.exit(main())
