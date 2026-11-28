#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""将 work/results.json 单源绑定并编译为 LaTeX 宏、Typst 数据模块与三线表片段。

用法：
    python export_paper_macros.py --results work/results.json \
        --out-tex output/paper/results_macros.tex \
        --out-typ output/paper/results_data.typ \
        --tables-dir work/tables --table-format both \
        --format-mode smart
    python export_paper_macros.py --results work/results.json --tables-dir work/tables --tables-spec work/tables_spec.json
    python export_paper_macros.py --self-test

设计目标：
- 让论文正文与表格直接引用 \ResVal{path} / \ResPct{path} / \ResSmart{path} / \ResPctSmart{path} / \ResInt{path}（或 Typst #res("path") / #res_smart("path")），
  一旦阶段 5/6 重跑更新了 results.json，重跑本脚本并重编译 PDF 即可全自动同步全文数字。
- 错用不存在的 key 在 LaTeX/Typst 编译期直接报错，杜绝静默错漏或过时数字。
"""

from __future__ import annotations

import argparse
import json
import math
import re
import shutil
import subprocess
import sys
import tempfile
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any

GENERATED_HEADER_TEX = "% GENERATED-BY: export_paper_macros.py — DO NOT HAND-EDIT; re-run after results.json updates."
GENERATED_HEADER_TYP = "// GENERATED-BY: export_paper_macros.py — DO NOT HAND-EDIT; re-run after results.json updates."

_DIGIT_WORDS = {
    "0": "Zero",
    "1": "One",
    "2": "Two",
    "3": "Three",
    "4": "Four",
    "5": "Five",
    "6": "Six",
    "7": "Seven",
    "8": "Eight",
    "9": "Nine",
}

_LATEX_ESCAPES = {
    "\\": r"\textbackslash{}",
    "{": r"\{",
    "}": r"\}",
    "$": r"\$",
    "&": r"\&",
    "%": r"\%",
    "#": r"\#",
    "_": r"\_",
    "^": r"\textasciicircum{}",
    "~": r"\textasciitilde{}",
}


def escape_latex(text: str) -> str:
    """Escape LaTeX special characters and normalize Unicode minus in one pass."""
    text = text.replace("\u2212", "-")
    return re.sub(r"[\\{}$&%#_^~]", lambda m: _LATEX_ESCAPES[m.group(0)], text)


def escape_typst_str(text: str) -> str:
    """Escape string literal contents for Typst double-quoted strings."""
    text = text.replace("\u2212", "-")
    return text.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n").replace("\r", "")


def _is_safe_tex_key(key: str) -> bool:
    """Keys used in TeX lookup tables cannot contain raw TeX comment/brace/escape tokens."""
    return not any(ch in key for ch in ("\\", "%", "{", "}", "#", "\r", "\n"))


def is_num(val: Any) -> bool:
    return isinstance(val, (int, float)) and not isinstance(val, bool) and math.isfinite(float(val))


def format_int_str(n: int, latex: bool) -> str:
    sep = "{,}" if latex else ","
    s = f"{abs(n):,}".replace(",", sep)
    return f"-{s}" if n < 0 else s


def format_num_latex(val: float | int, digits: int = 4) -> str:
    if isinstance(val, int) and not isinstance(val, bool):
        return format_int_str(val, latex=True)
    fv = float(val)
    if fv == 0.0:
        return f"{0.0:.{digits}f}"
    if 0.0 < abs(fv) < 1e-4:
        sci = f"{fv:.{max(1, digits - 1)}e}"
        mant, exp_s = sci.split("e")
        exp = int(exp_s)
        return rf"\ensuremath{{{mant} \times 10^{{{exp}}}}}"
    return f"{fv:.{digits}f}"


def format_num_typst(val: float | int, digits: int = 4) -> str:
    if isinstance(val, int) and not isinstance(val, bool):
        return format_int_str(val, latex=False)
    fv = float(val)
    if fv == 0.0:
        return f"{0.0:.{digits}f}"
    if 0.0 < abs(fv) < 1e-4:
        sci = f"{fv:.{max(1, digits - 1)}e}"
        mant, exp_s = sci.split("e")
        exp = int(exp_s)
        return f"{mant}e{exp}"
    return f"{fv:.{digits}f}"


def format_raw(val: Any) -> str:
    if isinstance(val, int) and not isinstance(val, bool):
        return str(val)
    if isinstance(val, float):
        return f"{val:.6g}"
    if isinstance(val, bool):
        return "true" if val else "false"
    return str(val)


def _trim_decimal_str(s: str) -> str:
    """Strip meaningless trailing fractional zeros while normalizing negative zero."""
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return "0" if s in ("-0", "-0.0", "") else s


def _round_half_up_str(val: float | Decimal, digits: int, thousands: bool = False) -> str:
    """Deterministic decimal half-up rounding to avoid binary IEEE-754 tie drift (e.g. 94.55 -> 94.6)."""
    d = max(0, int(digits))
    dec = val if isinstance(val, Decimal) else Decimal(str(float(val)))
    q = Decimal("1") if d == 0 else Decimal(f"1e-{d}")
    rounded = dec.quantize(q, rounding=ROUND_HALF_UP)
    if rounded == 0:
        rounded = Decimal("0").quantize(q)
    s = f"{rounded:,f}" if thousands else f"{rounded:f}"
    return "0" if s in ("-0", "-0.0") else s


def _lookup_precision_spec(path: str, display_precision: dict[str, Any] | None) -> Any:
    if not display_precision or not path:
        return None
    if path in display_precision:
        return display_precision[path]
    best_match = None
    best_len = -1
    for key, spec in display_precision.items():
        if (path == key or path.endswith(f".{key}")) and len(key) > best_len:
            best_match = spec
            best_len = len(key)
    return best_match


def format_smart_number(
    val: float | int,
    path: str = "",
    display_precision: dict[str, Any] | None = None,
    latex: bool = True,
) -> str:
    """Semantic significant-digit number formatting (eliminates 47.0900 trailing-zero walls)."""
    if isinstance(val, int) and not isinstance(val, bool):
        return format_int_str(val, latex=latex)
    fv = float(val)
    if fv == 0.0:
        return "0"

    spec = _lookup_precision_spec(path, display_precision)
    if isinstance(spec, int) and not isinstance(spec, bool):
        d = max(0, spec)
        s = _round_half_up_str(fv, d, thousands=abs(fv) >= 1000.0)
        if latex and abs(fv) >= 1000.0:
            s = s.replace(",", "{,}")
        return "0" if s in ("-0", "-0.0") else s
    if isinstance(spec, dict):
        d = int(spec.get("digits", 2))
        trim = bool(spec.get("trim_zeros", True))
        use_sci = bool(spec.get("sci", False))
        if use_sci or (0.0 < abs(fv) < 1e-4 and "digits" not in spec):
            sci = f"{fv:.{max(0, d)}e}"
            mant, exp_s = sci.split("e")
            if trim:
                mant = _trim_decimal_str(mant)
            exp = int(exp_s)
            return rf"\ensuremath{{{mant} \times 10^{{{exp}}}}}" if latex else f"{mant}e{exp}"
        s = _round_half_up_str(fv, d, thousands=abs(fv) >= 1000.0)
        if trim:
            s = _trim_decimal_str(s)
        if latex and abs(fv) >= 1000.0:
            s = s.replace(",", "{,}")
        return "0" if s in ("-0", "-0.0") else s

    av = abs(fv)
    if av < 1e-4:
        sci = f"{fv:.2e}"
        mant, exp_s = sci.split("e")
        mant = _trim_decimal_str(mant)
        exp = int(exp_s)
        return rf"\ensuremath{{{mant} \times 10^{{{exp}}}}}" if latex else f"{mant}e{exp}"
    if av >= 1000.0:
        out = _trim_decimal_str(_round_half_up_str(fv, 1, thousands=True))
        if latex:
            out = out.replace(",", "{,}")
        return "0" if out in ("-0", "-0.0") else out
    if av >= 10.0:
        max_d = 2
    elif av >= 0.1:
        max_d = 3
    else:
        max_d = 4
    return _trim_decimal_str(_round_half_up_str(fv, max_d))


def format_smart_pct(
    val: float | int,
    path: str = "",
    display_precision: dict[str, Any] | None = None,
    latex: bool = True,
) -> str:
    """Semantic percentage formatting with exact decimal half-up rounding (58.1000% -> 58.1%, 0.9455 -> 94.6%)."""
    fv = float(val)
    pct_dec = Decimal(str(fv)) * Decimal("100")
    spec = _lookup_precision_spec(path, display_precision)
    pct_suffix = r"\%" if latex else "%"
    if isinstance(spec, int) and not isinstance(spec, bool):
        if abs(fv) <= 1.0:
            eff_d = max(1, min(spec, 2))
            s = _trim_decimal_str(_round_half_up_str(pct_dec, eff_d))
        else:
            s = _round_half_up_str(pct_dec, max(0, spec))
        return ("0" if s in ("-0", "-0.0") else s) + pct_suffix
    if isinstance(spec, dict) and ("pct_digits" in spec or "digits" in spec):
        d = int(spec.get("pct_digits", spec.get("digits", 2)))
        trim = bool(spec.get("trim_zeros", True))
        s = _round_half_up_str(pct_dec, max(0, d))
        if trim:
            s = _trim_decimal_str(s)
        return ("0" if s in ("-0", "-0.0") else s) + pct_suffix
    max_d = 3 if (Decimal("0") < abs(pct_dec) < Decimal("0.05")) else 2
    s = _trim_decimal_str(_round_half_up_str(pct_dec, max_d))
    return s + pct_suffix


def flatten_leaves(obj: Any, prefix: str = "") -> list[tuple[str, Any]]:
    """递归展平 JSON，保留有限数值与单行短标量字符串（≤80 字符），跳过 display_precision 元数据。"""
    items: list[tuple[str, Any]] = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if not prefix and k == "display_precision":
                continue
            key = f"{prefix}.{k}" if prefix else str(k)
            items.extend(flatten_leaves(v, key))
    elif isinstance(obj, (list, tuple)):
        for i, v in enumerate(obj):
            items.extend(flatten_leaves(v, f"{prefix}[{i}]"))
    elif is_num(obj):
        items.append((prefix, obj))
    elif isinstance(obj, str) and "\n" not in obj and "\r" not in obj and len(obj.strip()) <= 80:
        items.append((prefix, obj))
    return items


def path_to_macro_name(path: str, prefix: str = "Val") -> str:
    """将 JSON 路径转为纯字母 LaTeX 命令名（如 Q1.elim_consistency_rate -> ValQOneElimConsistencyRate）。"""
    clean_prefix = re.sub(r"[^A-Za-z]", "", prefix) or "Val"
    raw_tokens = re.split(r"[^A-Za-z0-9]+", path)
    parts: list[str] = []
    for tok in raw_tokens:
        if not tok:
            continue
        expanded = []
        i = 0
        while i < len(tok):
            ch = tok[i]
            if ch in _DIGIT_WORDS:
                expanded.append(_DIGIT_WORDS[ch])
                i += 1
            else:
                j = i
                while j < len(tok) and tok[j] not in _DIGIT_WORDS:
                    j += 1
                word = tok[i:j]
                if word:
                    expanded.append(word[0].upper() + word[1:])
                i = j
        parts.extend(expanded)
    body = "".join(parts) or "Item"
    return clean_prefix + body


def _dedupe_macro_name(base: str, used: set[str]) -> str:
    cand = base
    if cand not in used:
        used.add(cand)
        return cand
    suffix_idx = 0
    while True:
        letters = []
        n = suffix_idx
        while True:
            letters.append(chr(ord("A") + (n % 26)))
            n = n // 26 - 1
            if n < 0:
                break
        cand = base + "".join(reversed(letters))
        if cand not in used:
            used.add(cand)
            return cand
        suffix_idx += 1


def generate_latex_macros(
    results: dict[str, Any],
    digits: int = 4,
    pct_digits: int = 2,
    prefix: str = "Val",
    format_mode: str = "fixed",
) -> str:
    leaves = flatten_leaves(results)
    raw_dp = results.get("display_precision")
    display_precision = raw_dp if isinstance(raw_dp, dict) else None
    lines = [
        GENERATED_HEADER_TEX + f" format_mode={format_mode}",
        r"\makeatletter",
        "",
        r"% ---- Compile-time checked lookup macros ----",
        r"\providecommand{\ResVal}[1]{%",
        r"  \@ifundefined{res@val@\detokenize{#1}}{%",
        r"    \PackageError{results_macros}{Missing results.json key: \detokenize{#1}}{Re-run export_paper_macros.py after updating work/results.json}%",
        r"  }{\@nameuse{res@val@\detokenize{#1}}}%",
        r"}",
        r"\providecommand{\ResPct}[1]{%",
        r"  \@ifundefined{res@pct@\detokenize{#1}}{%",
        r"    \PackageError{results_macros}{Missing percentage results.json key: \detokenize{#1}}{Key missing or |value| > 10}%",
        r"  }{\@nameuse{res@pct@\detokenize{#1}}}%",
        r"}",
        r"\providecommand{\ResSmart}[1]{%",
        r"  \@ifundefined{res@smart@\detokenize{#1}}{%",
        r"    \PackageError{results_macros}{Missing smart results.json key: \detokenize{#1}}{Re-run export_paper_macros.py after updating work/results.json}%",
        r"  }{\@nameuse{res@smart@\detokenize{#1}}}%",
        r"}",
        r"\providecommand{\ResPctSmart}[1]{%",
        r"  \@ifundefined{res@pctsmart@\detokenize{#1}}{%",
        r"    \PackageError{results_macros}{Missing smart percentage results.json key: \detokenize{#1}}{Key missing or |value| > 10}%",
        r"  }{\@nameuse{res@pctsmart@\detokenize{#1}}}%",
        r"}",
        r"\providecommand{\ResInt}[1]{%",
        r"  \@ifundefined{res@int@\detokenize{#1}}{%",
        r"    \PackageError{results_macros}{Missing integer results.json key: \detokenize{#1}}{Key missing or non-integer}%",
        r"  }{\@nameuse{res@int@\detokenize{#1}}}%",
        r"}",
        r"\providecommand{\ResRaw}[1]{%",
        r"  \@ifundefined{res@raw@\detokenize{#1}}{%",
        r"    \PackageError{results_macros}{Missing raw results.json key: \detokenize{#1}}{Re-run export_paper_macros.py after updating work/results.json}%",
        r"  }{\@nameuse{res@raw@\detokenize{#1}}}%",
        r"}",
        "",
        "% ---- Lookup definitions (@namedef) ----",
    ]

    aliases: list[tuple[str, str, str]] = []
    used_names: set[str] = set()

    for path, val in leaves:
        if not path or not _is_safe_tex_key(path):
            continue
        if is_num(val):
            smart_tex = format_smart_number(val, path=path, display_precision=display_precision, latex=True)
            v_tex = smart_tex if format_mode == "smart" else format_num_latex(val, digits=digits)
            r_tex = format_raw(val)
            lines.append(rf"\@namedef{{res@val@\detokenize{{{path}}}}}{{{v_tex}}}")
            lines.append(rf"\@namedef{{res@smart@\detokenize{{{path}}}}}{{{smart_tex}}}")
            lines.append(rf"\@namedef{{res@raw@\detokenize{{{path}}}}}{{{r_tex}}}")
            fv = float(val)
            if abs(fv) <= 10.0:
                pct_smart_tex = format_smart_pct(val, path=path, display_precision=display_precision, latex=True)
                pct_tex = pct_smart_tex if format_mode == "smart" else (f"{fv * 100.0:.{pct_digits}f}" + r"\%")
                lines.append(rf"\@namedef{{res@pct@\detokenize{{{path}}}}}{{{pct_tex}}}")
                lines.append(rf"\@namedef{{res@pctsmart@\detokenize{{{path}}}}}{{{pct_smart_tex}}}")
            if (isinstance(val, int) and not isinstance(val, bool)) or (abs(fv) < 1e15 and fv.is_integer()):
                int_tex = format_int_str(int(round(fv)), latex=True)
                lines.append(rf"\@namedef{{res@int@\detokenize{{{path}}}}}{{{int_tex}}}")
            if "[" not in path:
                mname = _dedupe_macro_name(path_to_macro_name(path, prefix=prefix), used_names)
                aliases.append((mname, v_tex, path))
        else:
            s_tex = escape_latex(str(val))
            lines.append(rf"\@namedef{{res@val@\detokenize{{{path}}}}}{{{s_tex}}}")
            lines.append(rf"\@namedef{{res@smart@\detokenize{{{path}}}}}{{{s_tex}}}")
            lines.append(rf"\@namedef{{res@raw@\detokenize{{{path}}}}}{{{s_tex}}}")

    lines += [
        "",
        "% ---- Alphabetic macro aliases (non-indexed numeric leaves) ----",
    ]
    for mname, v_tex, path in aliases:
        lines.append(rf"\providecommand{{\{mname}}}{{{v_tex}}} % {path}")

    lines += ["", r"\makeatother", ""]
    return "\n".join(lines)


def generate_typst_data(
    results: dict[str, Any],
    digits: int = 4,
    pct_digits: int = 2,
    format_mode: str = "fixed",
) -> str:
    leaves = flatten_leaves(results)
    raw_dp = results.get("display_precision")
    display_precision = raw_dp if isinstance(raw_dp, dict) else None
    lines = [GENERATED_HEADER_TYP + f" format_mode={format_mode}", ""]

    raw_entries: list[str] = []
    fmt_entries: list[str] = []
    smart_entries: list[str] = []
    pct_entries: list[str] = []
    pct_smart_entries: list[str] = []
    int_entries: list[str] = []

    for path, val in leaves:
        if not path:
            continue
        k_lit = f'"{escape_typst_str(path)}"'
        if is_num(val):
            raw_lit = str(val) if (isinstance(val, int) and not isinstance(val, bool)) else f"{float(val):.6g}"
            smart_str = format_smart_number(val, path=path, display_precision=display_precision, latex=False)
            smart_lit = f'"{escape_typst_str(smart_str)}"'
            fmt_lit = smart_lit if format_mode == "smart" else f'"{format_num_typst(val, digits=digits)}"'
            raw_entries.append(f"  {k_lit}: {raw_lit},")
            fmt_entries.append(f"  {k_lit}: {fmt_lit},")
            smart_entries.append(f"  {k_lit}: {smart_lit},")
            fv = float(val)
            if abs(fv) <= 10.0:
                pct_smart_lit = f'"{format_smart_pct(val, path=path, display_precision=display_precision, latex=False)}"'
                pct_lit = pct_smart_lit if format_mode == "smart" else f'"{fv * 100.0:.{pct_digits}f}%"'
                pct_entries.append(f"  {k_lit}: {pct_lit},")
                pct_smart_entries.append(f"  {k_lit}: {pct_smart_lit},")
            if (isinstance(val, int) and not isinstance(val, bool)) or (abs(fv) < 1e15 and fv.is_integer()):
                int_lit = f'"{format_int_str(int(round(fv)), latex=False)}"'
                int_entries.append(f"  {k_lit}: {int_lit},")
        else:
            s_lit = f'"{escape_typst_str(str(val))}"'
            raw_entries.append(f"  {k_lit}: {s_lit},")
            fmt_entries.append(f"  {k_lit}: {s_lit},")
            smart_entries.append(f"  {k_lit}: {s_lit},")

    lines.append("#let results_flat = (")
    lines.extend(raw_entries)
    lines.append(")")
    lines.append("")
    lines.append("#let results_fmt = (")
    lines.extend(fmt_entries)
    lines.append(")")
    lines.append("")
    lines.append("#let results_smart = (")
    lines.extend(smart_entries)
    lines.append(")")
    lines.append("")
    lines.append("#let results_pct = (")
    lines.extend(pct_entries)
    lines.append(")")
    lines.append("")
    lines.append("#let results_pct_smart = (")
    lines.extend(pct_smart_entries)
    lines.append(")")
    lines.append("")
    lines.append("#let results_int = (")
    lines.extend(int_entries)
    lines.append(")")
    lines.extend([
        "",
        '#let res(key) = {',
        '  assert(key in results_fmt, message: "Missing results.json key: " + key)',
        '  results_fmt.at(key)',
        '}',
        '#let res_smart(key) = {',
        '  assert(key in results_smart, message: "Missing smart results.json key: " + key)',
        '  results_smart.at(key)',
        '}',
        '#let res_pct(key) = {',
        '  assert(key in results_pct, message: "Missing percentage results.json key: " + key)',
        '  results_pct.at(key)',
        '}',
        '#let res_pct_smart(key) = {',
        '  assert(key in results_pct_smart, message: "Missing smart percentage results.json key: " + key)',
        '  results_pct_smart.at(key)',
        '}',
        '#let res_int(key) = {',
        '  assert(key in results_int, message: "Missing integer results.json key: " + key)',
        '  results_int.at(key)',
        '}',
        "",
    ])
    return "\n".join(lines)


def resolve_path(data: Any, path: str) -> Any:
    """按 dot/bracket 路径（如 Q4.eps_main.pareto 或 a[0].b）在 JSON 对象中取值。"""
    if not path:
        return data
    cur = data
    for tok in re.split(r"\.", path):
        m = re.fullmatch(r"([^\[\]]*)((?:\[\d+\])+)?", tok)
        if not m:
            raise KeyError(f"非法路径段 {tok!r}（完整路径 {path!r}）")
        name, idxs = m.group(1), m.group(2)
        if name:
            if isinstance(cur, dict) and name in cur:
                cur = cur[name]
            else:
                raise KeyError(f"路径 {path!r} 缺少键 {name!r}")
        if idxs:
            for idx_s in re.findall(r"\[(\d+)\]", idxs):
                idx = int(idx_s)
                if isinstance(cur, list) and 0 <= idx < len(cur):
                    cur = cur[idx]
                else:
                    raise KeyError(f"路径 {path!r} 下标 [{idx}] 越界")
    return cur


def _format_cell(val: Any, fmt: str | None, digits: int, latex: bool, format_mode: str = "fixed") -> str:
    if val is None:
        return "--"
    if fmt == "bool" or isinstance(val, bool):
        return "Yes" if bool(val) else "No"
    if fmt == "str" or isinstance(val, str):
        s = str(val)
        return escape_latex(s) if latex else s
    if is_num(val):
        fv = float(val)
        if fmt == "raw":
            return format_raw(val)
        if fmt == "int":
            return format_int_str(int(round(fv)), latex=latex)
        if fmt == "smart":
            return format_smart_number(val, latex=latex)
        if fmt == "pct_smart":
            return format_smart_pct(val, latex=latex)
        if fmt and re.fullmatch(r"f\d+", fmt):
            d = int(fmt[1:])
            return f"{fv:.{d}f}"
        if fmt and re.fullmatch(r"pct\d+", fmt):
            d = int(fmt[3:])
            pct_sign = r"\%" if latex else "%"
            return f"{fv * 100.0:.{d}f}{pct_sign}"
        if fmt == "sci":
            sci = f"{fv:.2e}"
            if latex:
                mant, exp_s = sci.split("e")
                return rf"\ensuremath{{{mant} \times 10^{{{int(exp_s)}}}}}"
            return sci
        if format_mode == "smart":
            return format_smart_number(val, latex=latex)
        return format_num_latex(val, digits=digits) if latex else format_num_typst(val, digits=digits)
    s = str(val)
    return escape_latex(s) if latex else s


def discover_table_specs(results: Any, digits: int = 4) -> list[dict[str, Any]]:
    """自动发现均匀字典列表（2..50 行 × 2..10 标量列），生成表格规范。"""
    specs: list[dict[str, Any]] = []

    def walk(obj: Any, path: str) -> None:
        if isinstance(obj, dict):
            for k, v in obj.items():
                if k in ("key_metrics", "display_precision"):
                    continue
                sub_path = f"{path}.{k}" if path else str(k)
                walk(v, sub_path)
        elif isinstance(obj, list):
            if 2 <= len(obj) <= 50 and all(isinstance(row, dict) for row in obj):
                col_keys: list[str] = []
                seen_k: set[str] = set()
                for row in obj:
                    for k, v in row.items():
                        if isinstance(v, (dict, list)):
                            continue
                        if k not in seen_k:
                            seen_k.add(k)
                            col_keys.append(str(k))
                scalar_cols: list[str] = []
                for ck in col_keys:
                    vals = [row.get(ck) for row in obj if ck in row and row.get(ck) is not None]
                    if vals and all(isinstance(v, (int, float, bool, str)) for v in vals):
                        scalar_cols.append(ck)
                if 2 <= len(scalar_cols) <= 10:
                    cols = []
                    for ck in scalar_cols:
                        vals = [row.get(ck) for row in obj if row.get(ck) is not None]
                        align = "r" if vals and all(is_num(v) for v in vals) else "l"
                        fmt = "int" if vals and all(isinstance(v, int) and not isinstance(v, bool) for v in vals) else None
                        cols.append({"key": ck, "header": ck, "align": align, "fmt": fmt})
                    slug = re.sub(r"[^A-Za-z0-9]+", "_", path).strip("_").lower() or "table"
                    specs.append({"name": f"tab_{slug}", "data_path": path, "columns": cols})
                    return
            for i, item in enumerate(obj):
                if isinstance(item, (dict, list)):
                    walk(item, f"{path}[{i}]")

    walk(results, "")
    return specs


def render_latex_table(
    spec: dict[str, Any],
    rows: list[dict[str, Any]],
    digits: int = 4,
    format_mode: str = "fixed",
) -> str:
    cols = spec["columns"]
    align_str = "".join(c.get("align", "l") for c in cols)
    headers = " & ".join(escape_latex(str(c.get("header", c["key"]))) for c in cols)

    body_lines = [
        GENERATED_HEADER_TEX,
        rf"\begin{{tabular}}{{{align_str}}}",
        r"\toprule",
        headers + r" \\",
        r"\midrule",
    ]
    for row in rows:
        cells = [
            _format_cell(row.get(c["key"]), c.get("fmt"), digits=digits, latex=True, format_mode=format_mode)
            for c in cols
        ]
        body_lines.append(" & ".join(cells) + r" \\")
    body_lines += [r"\bottomrule", r"\end{tabular}"]

    caption = spec.get("caption")
    label = spec.get("label")
    if caption or label:
        wrapped = [GENERATED_HEADER_TEX, r"\begin{table}[H]", r"\centering"]
        if caption:
            wrapped.append(rf"\caption{{{escape_latex(str(caption))}}}")
        if label:
            wrapped.append(rf"\label{{{label}}}")
        wrapped.extend(body_lines[1:])
        wrapped.append(r"\end{table}")
        return "\n".join(wrapped) + "\n"
    return "\n".join(body_lines) + "\n"


def render_typst_table(
    spec: dict[str, Any],
    rows: list[dict[str, Any]],
    digits: int = 4,
    format_mode: str = "fixed",
) -> str:
    cols = spec["columns"]
    align_map = {"r": "right", "c": "center", "l": "left"}
    aligns = ", ".join(align_map.get(c.get("align", "l"), "left") for c in cols)
    headers = ", ".join(f'[*{escape_typst_str(str(c.get("header", c["key"])))}*]' for c in cols)

    lines = [
        GENERATED_HEADER_TYP,
        "#table(",
        f"  columns: {len(cols)},",
        f"  align: ({aligns}),",
        "  stroke: none,",
        "  table.hline(y: 0, stroke: 1.2pt),",
        f"  {headers},",
        "  table.hline(stroke: 0.7pt),",
    ]
    for row in rows:
        cells = []
        for c in cols:
            txt = _format_cell(row.get(c["key"]), c.get("fmt"), digits=digits, latex=False, format_mode=format_mode)
            cells.append(f"[{txt}]")
        lines.append("  " + ", ".join(cells) + ",")
    lines.extend([
        "  table.hline(stroke: 1.2pt),",
        ")",
    ])
    caption = spec.get("caption")
    label = spec.get("label")
    if caption or label:
        wrapped = [GENERATED_HEADER_TYP, "#figure("]
        wrapped.extend("  " + ln for ln in lines[1:])
        if caption:
            wrapped.append(f'  caption: [{escape_typst_str(str(caption))}],')
        wrapped.append(")" + (f" <{label}>" if label else ""))
        return "\n".join(wrapped) + "\n"
    return "\n".join(lines) + "\n"


def export_tables(
    results: dict[str, Any],
    tables_dir: Path,
    tables_spec_path: Path | None,
    table_format: str,
    digits: int,
    format_mode: str = "fixed",
) -> list[Path]:
    tables_dir.mkdir(parents=True, exist_ok=True)
    if tables_spec_path is not None:
        raw_spec = json.loads(tables_spec_path.read_text(encoding="utf-8"))
        specs = raw_spec["tables"] if isinstance(raw_spec, dict) and "tables" in raw_spec else raw_spec
    else:
        specs = discover_table_specs(results, digits=digits)

    written: list[Path] = []
    for spec in specs:
        name = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(spec["name"])).strip("_") or "table"
        data = resolve_path(results, spec["data_path"])
        if not isinstance(data, list):
            raise ValueError(f"表格 {name} 对应路径 {spec['data_path']} 不是列表")
        rows = [r for r in data if isinstance(r, dict)]
        if table_format in ("latex", "both"):
            tex_p = tables_dir / f"{name}.tex"
            tex_p.write_text(render_latex_table(spec, rows, digits=digits, format_mode=format_mode), encoding="utf-8")
            written.append(tex_p)
        if table_format in ("typst", "both"):
            typ_p = tables_dir / f"{name}.typ"
            typ_p.write_text(render_typst_table(spec, rows, digits=digits, format_mode=format_mode), encoding="utf-8")
            written.append(typ_p)
    return written


def self_test() -> int:
    assert escape_latex("Actor/Actress & Social_Media 100% −0.5") == r"Actor/Actress \& Social\_Media 100\% -0.5"
    m = path_to_macro_name("Q1.elim_consistency_rate", prefix="Val")
    assert m == "ValQOneElimConsistencyRate" and m.isalpha(), m

    sample = {
        "Q1": {"obj": 0.961, "delta_coef": -0.184, "n_samples": 2777, "p_val": 2.3e-5},
        "Q2": {
            "era_breakdown": {"Percent (S3-S27)": {"jar_rank": 0.1937}},
            "pareto": [
                {"model": "A_1 & Co", "z1": 0.754, "z2": 0.5805, "feasible": True},
                {"model": "B/C", "z1": 0.812, "z2": 0.491, "feasible": False},
            ],
        },
        "Q3": {"ind_Singer/Rapper": {"judge_beta": 0.0123}},
    }

    with tempfile.TemporaryDirectory(prefix="export_macros_test_") as td:
        tdir = Path(td)
        tex_macros = generate_latex_macros(sample, digits=4, pct_digits=2, prefix="Val")
        typ_data = generate_typst_data(sample, digits=4, pct_digits=2)
        macros_path = tdir / "results_macros.tex"
        typ_path = tdir / "results_data.typ"
        macros_path.write_text(tex_macros, encoding="utf-8")
        typ_path.write_text(typ_data, encoding="utf-8")

        assert "GENERATED-BY: export_paper_macros.py" in tex_macros
        assert "GENERATED-BY: export_paper_macros.py" in typ_data
        assert r"\providecommand{\ValQOneObj}{0.9610}" in tex_macros
        assert r"\providecommand{\ValQOneNSamples}{2{,}777}" in tex_macros
        assert r'"Q1.n_samples": "2,777"' in typ_data
        assert r'"Q1.obj": "96.10%"' in typ_data

        # Auto-discovered table + custom spec table
        tables_dir = tdir / "tables"
        auto_written = export_tables(sample, tables_dir, None, "both", digits=4)
        assert (tables_dir / "tab_q2_pareto.tex").exists(), auto_written
        assert (tables_dir / "tab_q2_pareto.typ").exists(), auto_written

        spec_file = tdir / "spec.json"
        spec_file.write_text(
            json.dumps([
                {
                    "name": "tab_custom_front",
                    "data_path": "Q2.pareto",
                    "caption": "Pareto Front Check 100% & Co",
                    "label": "tab:front",
                    "columns": [
                        {"key": "model", "header": "Model_ID", "align": "l", "fmt": "str"},
                        {"key": "z1", "header": "Z1 (%)", "align": "r", "fmt": "pct1"},
                        {"key": "feasible", "header": "OK", "align": "c", "fmt": "bool"},
                    ],
                }
            ]),
            encoding="utf-8",
        )
        spec_written = export_tables(sample, tables_dir, spec_file, "both", digits=4)
        tab_tex = (tables_dir / "tab_custom_front.tex").read_text(encoding="utf-8")
        assert r"A\_1 \& Co & 75.4\% & Yes \\" in tab_tex, tab_tex
        assert (tables_dir / "tab_custom_front.typ").exists(), spec_written

        if shutil.which("xelatex"):
            doc_tex = tdir / "test_ok.tex"
            doc_tex.write_text(
                r"""\documentclass{article}
\usepackage{booktabs,float}
\input{results_macros.tex}
\begin{document}
Samples=\ResInt{Q1.n_samples}; ECR=\ResPct{Q1.obj}; Delta=\ResVal{Q1.delta_coef};
P=\ResVal{Q1.p_val}; Era=\ResVal{Q2.era_breakdown.Percent (S3-S27).jar_rank};
Rapper=\ResVal{Q3.ind_Singer/Rapper.judge_beta}; Alias=\ValQOneDeltaCoef.
\input{tables/tab_custom_front.tex}
\end{document}
""",
                encoding="utf-8",
            )
            res = subprocess.run(
                ["xelatex", "-interaction=nonstopmode", "-halt-on-error", "test_ok.tex"],
                cwd=tdir,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            assert res.returncode == 0, res.stdout + "\n" + res.stderr
            if shutil.which("pdftotext"):
                pt = subprocess.run(
                    ["pdftotext", str(tdir / "test_ok.pdf"), "-"],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                )
                assert pt.returncode == 0
                out_txt = pt.stdout
                for tok in ("2,777", "96.10%", "-0.1840", "0.1937", "0.0123", "75.4%"):
                    assert tok in out_txt, f"Missing {tok!r} in PDF text:\n{out_txt}"

            # Broken key must fail at TeX compile time
            bad_tex = tdir / "test_bad.tex"
            bad_tex.write_text(
                r"""\documentclass{article}
\input{results_macros.tex}
\begin{document}
Bad=\ResVal{Q9.missing_key}.
\end{document}
""",
                encoding="utf-8",
            )
            bad_res = subprocess.run(
                ["xelatex", "-interaction=nonstopmode", "-halt-on-error", "test_bad.tex"],
                cwd=tdir,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            assert bad_res.returncode != 0, "Missing results key MUST fail TeX compilation"
            log_txt = (tdir / "test_bad.log").read_text(encoding="utf-8", errors="replace") if (tdir / "test_bad.log").exists() else bad_res.stdout
            assert "Missing results.json key" in log_txt, log_txt[-600:]
            print("[SELF-TEST] PASS (including live xelatex macro, table & missing-key compile checks)")
        else:
            print("[SELF-TEST] PASS (macro/table generation verified; xelatex not installed)")

    # Smart precision & display_precision verification (v4.2 + v4.3 decimal rounding & pct separation)
    smart_sample = {
        "T1": {"temp": 47.0900, "gain": 0.5810, "small_err": 0.0045, "big_n": 12450.0, "exact": 12.3456, "tie": 0.9455, "frac_int": 0.167, "frac_pct_dict": 0.9178},
        "display_precision": {
            "T1.exact": {"digits": 3, "trim_zeros": False},
            "T1.tie": {"digits": 4, "pct_digits": 1},
            "T1.frac_int": 3,
            "T1.frac_pct_dict": {"digits": 3, "pct_digits": 2, "trim_zeros": False},
        },
    }
    smart_fixed_tex = generate_latex_macros(smart_sample, digits=4, pct_digits=2, format_mode="fixed")
    assert r"\@namedef{res@smart@\detokenize{T1.temp}}{47.09}" in smart_fixed_tex, smart_fixed_tex
    assert r"\@namedef{res@pctsmart@\detokenize{T1.gain}}{58.1\%}" in smart_fixed_tex, smart_fixed_tex
    assert r"\@namedef{res@smart@\detokenize{T1.big_n}}{12{,}450}" in smart_fixed_tex, smart_fixed_tex
    assert r"\@namedef{res@smart@\detokenize{T1.exact}}{12.346}" in smart_fixed_tex, smart_fixed_tex
    assert r"\@namedef{res@pctsmart@\detokenize{T1.tie}}{94.6\%}" in smart_fixed_tex, smart_fixed_tex
    assert r"\@namedef{res@pctsmart@\detokenize{T1.frac_int}}{16.7\%}" in smart_fixed_tex, smart_fixed_tex
    assert r"\@namedef{res@pctsmart@\detokenize{T1.frac_pct_dict}}{91.78\%}" in smart_fixed_tex, smart_fixed_tex
    assert r"\@namedef{res@val@\detokenize{T1.temp}}{47.0900}" in smart_fixed_tex, smart_fixed_tex

    smart_mode_tex = generate_latex_macros(smart_sample, digits=4, pct_digits=2, format_mode="smart")
    assert "format_mode=smart" in smart_mode_tex
    assert r"\@namedef{res@val@\detokenize{T1.temp}}{47.09}" in smart_mode_tex, smart_mode_tex
    assert r"\@namedef{res@pct@\detokenize{T1.gain}}{58.1\%}" in smart_mode_tex, smart_mode_tex
    assert r"\@namedef{res@pct@\detokenize{T1.tie}}{94.6\%}" in smart_mode_tex, smart_mode_tex
    assert r"\@namedef{res@pct@\detokenize{T1.frac_int}}{16.7\%}" in smart_mode_tex, smart_mode_tex
    smart_mode_typ = generate_typst_data(smart_sample, digits=4, pct_digits=2, format_mode="smart")
    assert '"T1.gain": "58.1%"' in smart_mode_typ and "res_smart" in smart_mode_typ, smart_mode_typ
    assert "display_precision" not in smart_mode_tex
    print("[SELF-TEST] PASS v4.2/v4.3 smart precision, decimal rounding & pct separation checks")
    return 0


def main() -> int:
    if "--self-test" in sys.argv:
        return self_test()

    ap = argparse.ArgumentParser(description="将 work/results.json 编译为 LaTeX/Typst 单源宏与三线表")
    ap.add_argument("--results", help="work/results.json 路径")
    ap.add_argument("--out-tex", default="", help="输出 LaTeX 宏文件路径（如 output/paper/results_macros.tex）")
    ap.add_argument("--out-typ", default="", help="输出 Typst 数据文件路径（如 output/paper/results_data.typ）")
    ap.add_argument("--tables-dir", default="", help="输出自动/规格三线表目录（如 work/tables）")
    ap.add_argument("--tables-spec", default="", help="可选：自定义表格规范 JSON")
    ap.add_argument("--table-format", choices=("latex", "typst", "both"), default="latex")
    ap.add_argument("--digits", type=int, default=4, help="默认浮点数小数位数（默认 4）")
    ap.add_argument("--pct-digits", type=int, default=2, help="默认百分比小数位数（默认 2）")
    ap.add_argument(
        "--format-mode",
        choices=("fixed", "smart"),
        default="fixed",
        help="数字格式模式：fixed 保留固定小数位（兼容 v4.1）；smart 按量级智能控位并剥离无效尾零（o_award 推荐）",
    )
    ap.add_argument("--prefix", default="Val", help="纯字母 \\newcommand 别名前缀（默认 Val）")
    ap.add_argument("--self-test", action="store_true", help="运行内置自检")
    args = ap.parse_args()

    if not args.results:
        ap.error("必须提供 --results（除非使用 --self-test）")
    results_path = Path(args.results)
    if not results_path.is_file():
        print(f"[错误] results.json 不存在: {results_path}")
        return 2
    if not (args.out_tex or args.out_typ or args.tables_dir):
        ap.error("至少指定 --out-tex、--out-typ 或 --tables-dir 之一")

    results = json.loads(results_path.read_text(encoding="utf-8"))
    if not isinstance(results, dict):
        print("[错误] results.json 顶层必须是 JSON 对象")
        return 2

    if args.out_tex:
        out_tex = Path(args.out_tex)
        out_tex.parent.mkdir(parents=True, exist_ok=True)
        out_tex.write_text(
            generate_latex_macros(
                results,
                digits=args.digits,
                pct_digits=args.pct_digits,
                prefix=args.prefix,
                format_mode=args.format_mode,
            ),
            encoding="utf-8",
        )
        print(f"[OK] LaTeX 宏已生成: {out_tex} (format_mode={args.format_mode})")

    if args.out_typ:
        out_typ = Path(args.out_typ)
        out_typ.parent.mkdir(parents=True, exist_ok=True)
        out_typ.write_text(
            generate_typst_data(
                results,
                digits=args.digits,
                pct_digits=args.pct_digits,
                format_mode=args.format_mode,
            ),
            encoding="utf-8",
        )
        print(f"[OK] Typst 数据已生成: {out_typ} (format_mode={args.format_mode})")

    if args.tables_dir:
        spec_path = Path(args.tables_spec) if args.tables_spec else None
        if spec_path is not None and not spec_path.is_file():
            print(f"[错误] tables-spec 文件不存在: {spec_path}")
            return 2
        written = export_tables(
            results,
            Path(args.tables_dir),
            spec_path,
            args.table_format,
            args.digits,
            format_mode=args.format_mode,
        )
        print(f"[OK] 已生成 {len(written)} 个表格文件 -> {args.tables_dir}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
