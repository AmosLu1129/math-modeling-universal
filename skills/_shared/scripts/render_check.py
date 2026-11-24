#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""论文 PDF 版面快速检查：逐页渲染 + 空白页/四边触边检测。

用法：
    python render_check.py output/paper/paper.pdf --out work/scratch/paper_pages --dpi 90
    python render_check.py --self-test

检测项：
  - 每页像素占比过低（疑似空白页/图片丢失）
  - 四边边距触边检测（top / bottom / left / right 任一侧内容距边界小于 --min-margin）
输出渲染 PNG 到 --out，供原生多模态视觉逐页复核。

依赖：pdftoppm（poppler）+ Pillow + numpy；缺 pdftoppm 时仅提示跳过渲染。
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

try:
    from PIL import Image
    import numpy as np
    HAVE_PIL = True
except Exception:
    HAVE_PIL = False


def audit_page_array(
    a: "np.ndarray",
    min_ink: float = 0.01,
    min_margin: float = 0.015,
) -> tuple[float, dict[str, float], list[str]]:
    """检测灰阶页面图像是否为空白页或四边（top/bottom/left/right）内容触边。"""
    h, w = a.shape
    mask = a < 245
    ink = float(mask.mean())
    issues: list[str] = []
    if ink < min_ink or not mask.any():
        issues.append("近空白页")
        return ink, {}, issues

    ys, xs = np.where(mask)
    margins = {
        "top": float(ys.min()) / h,
        "bottom": float(h - 1 - ys.max()) / h,
        "left": float(xs.min()) / w,
        "right": float(w - 1 - xs.max()) / w,
    }
    clipped = [f"{k}={v * 100:.1f}%" for k, v in margins.items() if v < min_margin]
    if clipped:
        issues.append(f"内容触边({', '.join(clipped)})")
    return ink, margins, issues


def self_test() -> int:
    if not HAVE_PIL:
        print("[SELF-TEST] SKIP (numpy/PIL unavailable)")
        return 0

    h, w = 200, 150
    clean = np.full((h, w), 255, dtype=np.uint8)
    clean[30:170, 25:125] = 0
    _, _, iss_clean = audit_page_array(clean, min_ink=0.01, min_margin=0.015)
    assert not iss_clean, iss_clean

    clipped = clean.copy()
    clipped[80:110, w - 1 : w] = 0
    _, margins_clip, iss_clip = audit_page_array(clipped, min_ink=0.01, min_margin=0.015)
    assert any("right=0.0%" in x for x in iss_clip), (margins_clip, iss_clip)

    blank = np.full((h, w), 255, dtype=np.uint8)
    blank[10:12, 10:12] = 0
    _, _, iss_blank = audit_page_array(blank, min_ink=0.01, min_margin=0.015)
    assert iss_blank == ["近空白页"], iss_blank

    print("[SELF-TEST] PASS 3/3 (clean centered, right-edge clip, near-blank)")
    return 0


def main() -> int:
    if "--self-test" in sys.argv:
        return self_test()

    ap = argparse.ArgumentParser(description="论文 PDF 版面快速检查")
    ap.add_argument("pdf")
    ap.add_argument("--out", default=str(Path(tempfile.gettempdir()) / "paper_pages"), help="PNG 输出目录")
    ap.add_argument("--dpi", type=int, default=60)
    ap.add_argument("--min-ink", type=float, default=0.01, help="空白页最小非白像素占比（默认 0.01）")
    ap.add_argument("--min-margin", type=float, default=0.015, help="四边最小留白比例（默认 0.015 = 1.5%%）")
    ap.add_argument("--self-test", action="store_true", help="运行内置自检")
    args = ap.parse_args()

    pdf = Path(args.pdf)
    if not pdf.exists():
        print(f"[错误] PDF 不存在: {pdf}")
        return 2

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    for old_png in out.glob("pg-*.png"):
        old_png.unlink()

    if shutil.which("pdftoppm"):
        subprocess.run(["pdftoppm", "-png", "-r", str(args.dpi), str(pdf), str(out / "pg")],
                       check=True)
    else:
        print("[警告] 未找到 pdftoppm，跳过渲染（可安装 poppler 或先跑 setup_env.py --install）")

    pages = sorted(out.glob("pg-*.png"))
    if not pages:
        print("[警告] 未生成页面渲染，跳过像素检查")
        return 0

    print(f"渲染 {len(pages)} 页 -> {out}")
    problems = 0
    if HAVE_PIL:
        for p in pages:
            a = np.asarray(Image.open(p).convert("L"))
            ink, _, issues = audit_page_array(a, min_ink=args.min_ink, min_margin=args.min_margin)
            if issues:
                problems += 1
                print(f"  [检查] {p.name}: " + ", ".join(issues) + f"（墨迹占比 {ink:.4f}）")
    print(f"\n版面检查完成：{len(pages)} 页，{problems} 页有疑点。"
          f"\n下一步：用原生多模态读图逐页核查关键页与疑点页（如 {out / 'pg-01.png'} 等）。")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
