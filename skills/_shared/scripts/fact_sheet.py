#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从 results.json 自动生成「数字事实表」，供论文写作与审查环节引用。

用法：
    python fact_sheet.py --results work/results.json --out work/fact_sheet.md

输出：markdown 表，按顶层键（q1/q2/...）分组，每个数值给出
  - 原值（results.json 口径）
  - 百分比写法（自动 ×100，供论文直接引用）
  - 常见四舍五入写法

写作环节：直接从事实表抄数字，避免手抄结果文件出错；
审查环节：论文中的每个数字都应能在事实表/正文中溯源。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def flatten(obj, prefix: str = "") -> list[tuple[str, float]]:
    items: list[tuple[str, float]] = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            key = f"{prefix}.{k}" if prefix else str(k)
            items.extend(flatten(v, key))
    elif isinstance(obj, (list, tuple)):
        for i, v in enumerate(obj):
            items.extend(flatten(v, f"{prefix}[{i}]"))
    elif isinstance(obj, (int, float)) and not isinstance(obj, bool):
        items.append((prefix, float(obj)))
    return items


def fmt(value: float) -> str:
    if value != value:
        return "nan"
    if value in (float("inf"), float("-inf")):
        return "inf" if value > 0 else "-inf"
    s = f"{value:.6g}"
    return s


def main() -> int:
    ap = argparse.ArgumentParser(description="results.json -> 数字事实表")
    ap.add_argument("--results", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    results_path = Path(args.results)
    if not results_path.exists():
        print(f"[错误] results 文件不存在: {results_path}")
        return 2
    results = json.loads(results_path.read_text(encoding="utf-8"))

    # 按顶层分组
    groups: dict[str, list[tuple[str, float]]] = {}
    for key, value in flatten(results):
        top = key.split(".")[0]
        groups.setdefault(top, []).append((key, value))

    lines = [
        f"# 数字事实表 fact_sheet.md",
        "",
        f"> 自动生成于 {results_path}。论文中每个关键数字都应能从本表或正文图表溯源。",
        "",
    ]
    for top in sorted(groups):
        lines.append(f"## {top}")
        lines.append("")
        lines.append("| 路径 | 原值 | 百分比写法 | 常用四舍五入 |")
        lines.append("|---|---|---|---|")
        for key, value in groups[top]:
            pct = f"{value * 100:.2f}%" if abs(value) <= 10 else "-"
            rounded = f"{value:.4f}" if abs(value) >= 1e-3 else f"{value:.2e}"
            lines.append(f"| `{key}` | {fmt(value)} | {pct} | {rounded} |")
        lines.append("")

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines), encoding="utf-8")
    n = sum(len(v) for v in groups.values())
    print(f"[OK] 事实表已生成: {out_path}（{n} 个数值）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
