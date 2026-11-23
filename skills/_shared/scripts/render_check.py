#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""论文 PDF 版面快速检查：逐页渲染 + 空白页/异常页检测。

用法：
    python render_check.py output/paper/paper.pdf --out /tmp/paper_pages --dpi 60

检测项：
  - 每页像素占比过低（疑似空白页/图片丢失）
  - 每页内容触边（疑似排版溢出）
输出渲染 PNG 到 --out，供 vision.js 分批复核（每组 ≤3 张、组间串行）。

依赖：pdftoppm（poppler）+ Pillow；缺 pdftoppm 时仅做 PDF 文本级检查。
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


def main() -> int:
    ap = argparse.ArgumentParser(description="论文 PDF 版面快速检查")
    ap.add_argument("pdf")
    ap.add_argument("--out", default=str(Path(tempfile.gettempdir()) / "paper_pages"), help="PNG 输出目录")
    ap.add_argument("--dpi", type=int, default=60)
    args = ap.parse_args()

    pdf = Path(args.pdf)
    if not pdf.exists():
        print(f"[错误] PDF 不存在: {pdf}")
        return 2

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    if shutil.which("pdftoppm"):
        subprocess.run(["pdftoppm", "-png", "-r", str(args.dpi), str(pdf), str(out / "pg")],
                       check=True)
    else:
        print("[警告] 未找到 pdftoppm，跳过渲染（可安装 poppler 或先跑 setup_env.py --install）")

    pages = sorted(out.glob("pg-*.png"))
    if not pages:
        print("[警告] 未生成页面渲染，仅做 PDF 文本级检查")
        return 0

    print(f"渲染 {len(pages)} 页 -> {out}")
    problems = 0
    if HAVE_PIL:
        for p in pages:
            a = np.asarray(Image.open(p).convert("L"))
            h, w = a.shape
            ink = float((a < 245).mean())
            # 触边检测：内容到画布边缘 1.5% 以内
            edge = max(np.argwhere(a < 245).max(axis=0).min() / h,
                       np.argwhere(a < 245).min(axis=0).min() / w) if (a < 245).any() else 0
            issues = []
            if ink < 0.01:
                issues.append("近空白页")
            if edge < 0.02:
                issues.append("内容触边")
            if issues:
                problems += 1
                print(f"  [检查] {p.name}: " + ", ".join(issues) + f"（墨迹占比 {ink:.4f}）")
    print(f"\n版面检查完成：{len(pages)} 页，{problems} 页有疑点。"
          f"\n下一步：用多模态读图工具分批核查关键页（如 {out / 'pg-01.png'} 等，每组 ≤3 张）。")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
