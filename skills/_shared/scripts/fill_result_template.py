#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""结果模板一体化回填与回读校验（官方 xlsx 结果表）。

流程：读取官方模板 → 按 mapping 回填 → 保存 → 重新读回逐项校验（数值带容差）。

用法：
    python fill_result_template.py --template input/data/结果表.xlsx \
        --mapping work/template_mapping.json --results work/results.json \
        --out output/templates/结果表.xlsx

mapping JSON 结构（三类，可同时出现）：
{
  "cells": [                      # 单元格坐标回填
    {"sheet":"结果","cell":"B2","path":"Q1.objective","round":2}
  ],
  "rows": [                       # 按“键列”定位整行，填若干列
    {"sheet":"结果","key_col":"A","key":"问题一","columns":[
        {"col":"B","path":"Q1.objective","round":2},
        {"col":"C","path":"Q1.rmse","round":4}
    ]}
  ],
  "matrix": [                     # 行键×列键矩阵回填
    {"sheet":"方案1","row_key_col":"A","col_key_row":1,
     "data_path":"Q1.plan_matrix", "round":1}
  ]
}

说明：
- path 用点号从 results.json 取值（如 Q1.per_angle.attachment1_sic_10deg.d_um）。
- path 以 @ 开头表示字面量（如 "@N/A"）。
- round 省略则不取整；None 表示写字符串原值。
- matrix 的 data_path 指向 {"行键": {"列键": 值}}；列键与模板表头字符串匹配。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

try:
    import openpyxl
except Exception:  # noqa: BLE001
    sys.exit("缺少 openpyxl：pip install openpyxl")


def resolve(results: dict, path: str):
    """从 results.json 按点号路径取值；@ 开头为字面量。"""
    if path.startswith("@"):
        return path[1:]
    cur = results
    for part in path.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            raise KeyError(f"路径 {path} 在 results.json 中不存在（卡在 {part}）")
    return cur


def to_cell_value(value, round_spec):
    """把值转成写入单元格的形态。round_spec: None=原样；int=小数位数。"""
    if round_spec is None:
        return value
    if isinstance(value, (int, float)):
        return round(float(value), int(round_spec))
    return value


def cell_addr(sheet, cell):
    return f"{sheet}!{cell}"


def fill_cells(ws, spec: dict, results: dict, problems: list[str]):
    cell = spec["cell"]
    value = resolve(results, spec.get("path", "@"))
    v = to_cell_value(value, spec.get("round"))
    ws[cell] = v
    return [(cell_addr(ws.title, cell), v)]


def fill_rows(ws, spec: dict, results: dict, problems: list[str]):
    key = spec["key"]
    key_col = spec["key_col"]
    target_row = None
    for row in ws.iter_rows(min_col=ws[key_col + "1"].column,
                            max_col=ws[key_col + "1"].column):
        c = row[0]
        if c.value == key:
            target_row = c.row
            break
    if target_row is None:
        problems.append(f"[rows] 未找到键 {key} 于 {ws.title} 的 {key_col} 列")
        return []
    written = []
    for colspec in spec["columns"]:
        col = colspec["col"]
        value = resolve(results, colspec.get("path", "@"))
        v = to_cell_value(value, colspec.get("round"))
        addr = f"{col}{target_row}"
        ws[addr] = v
        written.append((cell_addr(ws.title, addr), v))
    return written


def fill_matrix(ws, spec: dict, results: dict, problems: list[str]):
    data = resolve(results, spec["data_path"])
    if not isinstance(data, dict):
        problems.append(f"[matrix] data_path {spec['data_path']} 不是行键→列键字典")
        return []
    row_key_col = spec["row_key_col"]
    col_key_row = int(spec["col_key_row"])
    round_spec = spec.get("round")

    # 表头列键
    header = {}
    max_col = ws.max_column
    for cell in ws[col_key_row]:
        if cell.value is not None:
            header[str(cell.value).strip()] = cell.column_letter
    # 行键
    row_of = {}
    for row in ws.iter_rows(min_col=ws[row_key_col + "1"].column,
                            max_col=ws[row_key_col + "1"].column):
        c = row[0]
        if c.value is not None:
            row_of[str(c.value).strip()] = c.row

    written = []
    for rkey, cols in data.items():
        if rkey not in row_of:
            problems.append(f"[matrix] 行键 {rkey} 不在模板中")
            continue
        if not isinstance(cols, dict):
            problems.append(f"[matrix] 行 {rkey} 的值不是字典")
            continue
        for ckey, val in cols.items():
            if ckey not in header:
                problems.append(f"[matrix] 列键 {ckey} 不在模板表头中")
                continue
            addr = f"{header[ckey]}{row_of[rkey]}"
            v = to_cell_value(val, round_spec)
            ws[addr] = v
            written.append((cell_addr(ws.title, addr), v))
    return written


def verify(wb, written: list[tuple[str, object]], tolerance: float) -> list[str]:
    issues = []
    for addr, expected in written:
        sheet_name, coord = addr.split("!", 1)
        actual = wb[sheet_name][coord].value
        ok = False
        if isinstance(expected, (int, float)) and isinstance(actual, (int, float)):
            ok = abs(float(expected) - float(actual)) <= tolerance
        else:
            ok = (actual == expected)
        if not ok:
            issues.append(f"回读不一致 {addr}: 期望 {expected!r}, 实际 {actual!r}")
    return issues


def main() -> int:
    ap = argparse.ArgumentParser(description="官方结果模板回填 + 回读校验")
    ap.add_argument("--template", required=True, help="官方结果模板 xlsx")
    ap.add_argument("--mapping", required=True, help="mapping JSON")
    ap.add_argument("--results", required=True, help="results.json")
    ap.add_argument("--out", required=True, help="输出 xlsx 路径")
    ap.add_argument("--tolerance", type=float, default=1e-6, help="数值回读容差")
    args = ap.parse_args()

    results = json.load(open(args.results, encoding="utf-8"))
    mapping = json.load(open(args.mapping, encoding="utf-8"))

    wb = openpyxl.load_workbook(args.template)
    problems: list[str] = []
    written: list[tuple[str, object]] = []

    for spec in mapping.get("cells", []):
        ws = wb[spec["sheet"]]
        written += fill_cells(ws, spec, results, problems)
    for spec in mapping.get("rows", []):
        ws = wb[spec["sheet"]]
        written += fill_rows(ws, spec, results, problems)
    for spec in mapping.get("matrix", []):
        ws = wb[spec["sheet"]]
        written += fill_matrix(ws, spec, results, problems)

    if not written and not problems:
        problems.append("mapping 为空，未回填任何单元格")

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    wb.save(out)

    # 回读校验
    wb2 = openpyxl.load_workbook(out)
    issues = verify(wb2, written, args.tolerance)

    print(f"已回填 {len(written)} 个单元格 -> {out}")
    for p in problems:
        print(f"  [警告] {p}")
    if issues:
        print(f"回读校验失败 {len(issues)} 项：")
        for i in issues:
            print("  [FAIL]", i)
        return 1
    print(f"回读校验通过：{len(written)} 项全部一致")
    return 0


if __name__ == "__main__":
    sys.exit(main())
