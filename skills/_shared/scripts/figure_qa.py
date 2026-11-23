#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""图表自检工具（math-figures 配套）。

三件事：
1. render_preview(fig, out, dpi=150)  —— 把画好的 Figure 渲染成 PNG 预览
2. audit_figure(fig, out_png=None)    —— 绘制时捕获 matplotlib 缺字/渲染警告，返回问题列表
3. check_files(paths, min_dpi=300)    —— 检查已导出文件：格式/DPI/非空/禁用 JPEG（原生展开通配符与目录）

用法（在绘图脚本末尾）：
    import sys; sys.path.insert(0, "<本文件所在目录>")
    import figure_qa as fq

    fq.render_preview(fig, "work/figures/_preview.png")
    issues = fq.audit_figure(fig)
    fq.report(issues)

检查已导出文件：
    python figure_qa.py check "work/figures/*.png" --min-dpi 300
    python figure_qa.py check work/figures/ --min-dpi 300
    python figure_qa.py --self-test

需要环境：matplotlib；PNG DPI 检查需要 Pillow（可选，缺失时跳过）。
"""

from __future__ import annotations

import argparse
import glob
import os
import sys
import tempfile
import warnings

import matplotlib

IMAGE_EXTS = {".png", ".svg", ".pdf", ".jpg", ".jpeg", ".tif", ".tiff"}


def render_preview(fig, out: str, dpi: int = 150) -> str:
    """把 Figure 渲染成 PNG 预览（供 AI 读图复核）。"""
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    fig.savefig(out, dpi=dpi, bbox_inches="tight")
    return out


def audit_figure(fig, out_png: str | None = None) -> list[tuple[str, str]]:
    """绘制时捕获缺字/字体/渲染警告，返回 [(级别, 说明), ...]。

    级别：FAIL（必须修）/ WARN（建议确认）。缺字（Glyph missing）判 FAIL。
    """
    issues: list[tuple[str, str]] = []
    with warnings.catch_warnings(record=True) as wlist:
        warnings.simplefilter("always")
        try:
            fig.canvas.draw()
            if out_png:
                render_preview(fig, out_png)
        except Exception as exc:  # noqa: BLE001
            issues.append(("FAIL", f"渲染异常：{exc}"))
    for w in wlist:
        msg = str(w.message)
        low = msg.lower()
        if "glyph" in low or "missing" in low or "font" in low or "cmap" in low:
            issues.append(("FAIL", f"缺字/字体/色图问题：{msg[:180]}"))
        else:
            issues.append(("WARN", f"matplotlib 警告：{msg[:180]}"))
    return issues


def _check_png(path: str, min_dpi: int) -> tuple[str, str, str]:
    try:
        from PIL import Image
    except ImportError:
        return (path, "WARN", "未安装 Pillow，跳过 DPI 检查")
    try:
        with Image.open(path) as im:
            dpi = round(im.info.get("dpi", (72, 72))[0])
        if dpi < min_dpi:
            return (path, "FAIL", f"DPI 不足：{dpi} < {min_dpi}")
        return (path, "PASS", f"DPI={dpi}")
    except Exception as exc:  # noqa: BLE001
        return (path, "FAIL", f"无法读取 PNG：{exc}")


def expand_paths(raw_paths: list[str]) -> list[str]:
    """在 Python 内部展开通配符（适配 Windows PowerShell 不自动展开 `*`）与目录。"""
    expanded: list[str] = []
    seen: set[str] = set()

    def add(item: str) -> None:
        if item not in seen:
            seen.add(item)
            expanded.append(item)

    for raw in raw_paths:
        if glob.has_magic(raw):
            matches = sorted(glob.glob(raw, recursive=True))
            files = [m for m in matches if os.path.isfile(m)]
            if files:
                for m in files:
                    add(m)
                continue
            dirs = [m for m in matches if os.path.isdir(m)]
            if dirs:
                for d in dirs:
                    for fn in sorted(os.listdir(d)):
                        fp = os.path.join(d, fn)
                        if os.path.isfile(fp) and os.path.splitext(fn)[1].lower() in IMAGE_EXTS:
                            add(fp)
                continue
            # 未匹配到任何文件：保留原模式串以便 check_files 显式报 FAIL
            add(raw)
        elif os.path.isdir(raw):
            hits = [
                os.path.join(raw, fn)
                for fn in sorted(os.listdir(raw))
                if os.path.isfile(os.path.join(raw, fn))
                and os.path.splitext(fn)[1].lower() in IMAGE_EXTS
            ]
            if hits:
                for h in hits:
                    add(h)
            else:
                add(raw)
        else:
            add(raw)
    return expanded


def check_files(paths: list[str], min_dpi: int = 300) -> list[tuple[str, str, str]]:
    """检查已导出图文件：存在性、格式、DPI、非空。返回 [(路径, 级别, 说明)]。"""
    results: list[tuple[str, str, str]] = []
    expanded = expand_paths(paths)
    skipped_preview = False
    for p in expanded:
        if os.path.basename(p).startswith("_"):
            skipped_preview = True
            continue  # 内部预览图（_preview.png）不参与正式检查
        if not os.path.exists(p):
            reason = "未匹配到文件" if glob.has_magic(p) else "文件不存在"
            results.append((p, "FAIL", reason))
            continue
        if os.path.isdir(p):
            results.append((p, "WARN", "目录内未发现图文件"))
            continue
        ext = os.path.splitext(p)[1].lower()
        if ext in (".jpg", ".jpeg"):
            results.append((p, "FAIL", "数据图禁用 JPEG"))
            continue
        if os.path.getsize(p) == 0:
            results.append((p, "FAIL", "空文件"))
            continue
        if ext == ".png":
            results.append(_check_png(p, min_dpi))
        elif ext == ".svg":
            with open(p, encoding="utf-8", errors="ignore") as fh:
                content = fh.read(200_000)
            if "data:image" in content and "base64" in content:
                results.append((p, "WARN", "SVG 内嵌 base64 位图，破坏矢量优势"))
            else:
                results.append((p, "PASS", "SVG 未发现内嵌位图"))
        elif ext == ".pdf":
            with open(p, "rb") as fh:
                head = fh.read(8)
            if head.startswith(b"%PDF"):
                results.append((p, "PASS", "PDF 文件头正常"))
            else:
                results.append((p, "FAIL", "PDF 文件头异常（缺少 %PDF 头）"))
        else:
            results.append((p, "WARN", f"未识别格式 {ext}（数据图优先 PDF/SVG/PNG）"))
    if not results and skipped_preview:
        results.append(("<input>", "WARN", "未发现正式图文件（已跳过下划线前缀预览图）"))
    return results


def report(issues: list[tuple[str, str]]) -> bool:
    """打印自检结果，全部无 FAIL 返回 True。"""
    if not issues:
        print("[figure_qa] PASS：未发现问题")
        return True
    ok = True
    for level, detail in issues:
        print(f"[figure_qa] {level}: {detail}")
        if level == "FAIL":
            ok = False
    if not ok:
        print("[figure_qa] 存在 FAIL，请修复后重新出图。")
    return ok


def self_test() -> int:
    from PIL import Image

    with tempfile.TemporaryDirectory(prefix="figqa_test_") as td:
        tdir = os.path.abspath(td)
        ok_png = os.path.join(tdir, "fig_ok.png")
        low_png = os.path.join(tdir, "fig_low.png")
        prev_png = os.path.join(tdir, "_preview.png")
        bad_jpg = os.path.join(tdir, "bad.jpg")
        good_pdf = os.path.join(tdir, "good.pdf")
        corrupt_pdf = os.path.join(tdir, "corrupt.pdf")

        Image.new("RGB", (20, 20), "white").save(ok_png, dpi=(300, 300))
        Image.new("RGB", (20, 20), "white").save(low_png, dpi=(72, 72))
        Image.new("RGB", (20, 20), "white").save(prev_png, dpi=(72, 72))
        with open(bad_jpg, "wb") as fh:
            fh.write(b"\xff\xd8\xff\xe0dummy")
        with open(good_pdf, "wb") as fh:
            fh.write(b"%PDF-1.4\n%%EOF\n")
        with open(corrupt_pdf, "wb") as fh:
            fh.write(b"NOT_A_PDF_HEADER")

        # 1. Windows glob "*.png" skips _preview.png, passes 300dpi, fails 72dpi
        r_png = {os.path.basename(p): lvl for p, lvl, _ in check_files([os.path.join(tdir, "*.png")], min_dpi=300)}
        assert r_png == {"fig_ok.png": "PASS", "fig_low.png": "FAIL"}, r_png

        # 2. Unmatched glob must FAIL explicitly
        r_none = check_files([os.path.join(tdir, "*.nope")], min_dpi=300)
        assert len(r_none) == 1 and r_none[0][1] == "FAIL", r_none

        # 3. JPEG disallowed, valid PDF passes, corrupt PDF MUST FAIL (bugfix)
        r_jpg = check_files([bad_jpg], min_dpi=300)
        assert r_jpg[0][1] == "FAIL", r_jpg
        r_pdf_ok = check_files([good_pdf], min_dpi=300)
        assert r_pdf_ok[0][1] == "PASS", r_pdf_ok
        r_pdf_bad = check_files([corrupt_pdf], min_dpi=300)
        assert r_pdf_bad[0][1] == "FAIL", r_pdf_bad

        # 4. Directory path expands cleanly and skips _preview.png
        r_dir = {os.path.basename(p): lvl for p, lvl, _ in check_files([tdir], min_dpi=300)}
        assert r_dir == {
            "fig_ok.png": "PASS",
            "fig_low.png": "FAIL",
            "bad.jpg": "FAIL",
            "good.pdf": "PASS",
            "corrupt.pdf": "FAIL",
        }, r_dir

        # 5. Preview-only glob warns instead of silent empty pass
        r_prev = check_files([os.path.join(tdir, "_*.png")], min_dpi=300)
        assert len(r_prev) == 1 and r_prev[0][1] == "WARN", r_prev

    print("[SELF-TEST] PASS 5/5")
    return 0


def main() -> int:
    if "--self-test" in sys.argv:
        return self_test()
    ap = argparse.ArgumentParser(description="图表文件合规检查")
    ap.add_argument("cmd", choices=["check"], help="check：检查已导出图文件")
    ap.add_argument("paths", nargs="+", help="图文件路径或目录（内置展开通配符）")
    ap.add_argument("--min-dpi", type=int, default=300, help="位图最低 DPI（默认 300）")
    args = ap.parse_args()
    results = check_files(args.paths, min_dpi=args.min_dpi)
    failed = False
    for path, level, detail in results:
        print(f"[{level}] {path}: {detail}")
        if level == "FAIL":
            failed = True
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
