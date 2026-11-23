#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""核对论文文本中的数字是否覆盖 results.json 的全部关键结果（增强版）。

用法：
    python consistency_check.py --results work/results.json --paper output/paper/
    python consistency_check.py --results work/results.json --paper output/paper/main.tex --tolerance 1e-3
    python consistency_check.py --results work/results.json --paper output/paper/ --percent --check-fabricated
    python consistency_check.py --self-test

增强能力（v3）：
- 支持 .tex/.typ/.md/.txt 单文件或目录自动合并（跳过 .tex `%` 注释与 Typst `//` / `/* ... */` 注释）。
- Unicode 负号（U+2212 `−`）与 LaTeX 千分位写法（`2{,}777` / `2,777`）自动归一化。
- --percent：同时尝试 value、value*100、value/100 匹配比例与百分比写法。
- 区分 CRITICAL_MISSING（核心结论漏写）与 DETAIL_OMITTED（标准误/网格点/seed 等辅助明细）：
  支持 --key-metrics（或 results.json 顶层 `key_metrics` 列表）、--ignore-patterns 与 --strict-all。
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

PAPER_SUFFIXES = (".tex", ".md", ".txt", ".typ")
NUMBER_RE = re.compile(r"[-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?")
THOUSAND_RE = re.compile(r"(\d)\{,\}(\d{3})(?!\d)")
THOUSAND_COMMA_RE = re.compile(r"(\d),(\d{3})(?!\d)")

DEFAULT_DETAIL_PATTERNS: tuple[str, ...] = (
    "meta.params.*",
    "*seed*",
    "*_se",
    "*.se",
    "*.std_err",
    "*.ci_low",
    "*.ci_high",
    "*_hat",
    "*_norm",
    "*.z1_hat",
    "*.z2_hat",
    "*.hypervolume_ref[*]",
    "*.hypervolume_crosscheck",
    "*.pareto[*].*",
    "*.sensitivity[*].*",
    "*.n_draws",
    "*.n_*_draws",
    "*.n_grid_*",
    "*_grid[*]",
    "*.plan_ref",
)


def flatten(obj, prefix: str = "") -> list[tuple[str, float]]:
    """递归展平 JSON，返回 (路径, 数值) 列表。"""
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


def _strip_comments_for_suffix(raw: str, suffix: str) -> str:
    suf = suffix.lower()
    if suf == ".typ":
        raw = re.sub(r"/\*.*?\*/", " ", raw, flags=re.S)
        raw = re.sub(r"(?<!:)//[^\n]*", " ", raw)
        return raw
    if suf == ".tex":
        # 去掉整行 % 注释及行内未转义 % 注释（保留 \% 百分号）
        return re.sub(r"(?<!\\)%[^\n]*", " ", raw)
    return raw


def _is_generated_macro_file(raw: str) -> bool:
    head = "\n".join(raw.splitlines()[:10])
    return "GENERATED-BY: export_paper_macros.py" in head


def _read_braced(text: str, start_brace_idx: int) -> tuple[str, int] | None:
    """从 `{` 下标读取平衡大括号内容，返回 `(inner, index_after_closing_brace)`。"""
    if start_brace_idx < 0 or start_brace_idx >= len(text) or text[start_brace_idx] != "{":
        return None
    depth = 0
    i = start_brace_idx
    n = len(text)
    while i < n:
        ch = text[i]
        if ch == "\\" and i + 1 < n and text[i + 1] in ("{", "}", "\\"):
            i += 2
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start_brace_idx + 1 : i], i + 1
        i += 1
    return None


def _parse_generated_tex_macros(raw: str) -> tuple[dict[tuple[str, str], str], dict[str, str]]:
    """解析 export_paper_macros.py 生成的 LaTeX 宏查找表与纯字母别名。"""
    named_vals: dict[tuple[str, str], str] = {}
    aliases: dict[str, str] = {}
    raw_fallback: dict[str, str] = {}

    for ln in raw.splitlines():
        s = ln.strip()
        m = re.match(r"^\\@namedef\{res@(val|pct|int|raw)@", s)
        if m:
            kind = m.group(1)
            pos = m.end()
            if s.startswith(r"\detokenize{", pos):
                key_res = _read_braced(s, pos + len(r"\detokenize"))
                if not key_res:
                    continue
                key, after_detok = key_res
                if after_detok >= len(s) or s[after_detok] != "}":
                    continue
                val_pos = after_detok + 1
            else:
                close = s.find("}", pos)
                if close < 0:
                    continue
                key = s[pos:close]
                val_pos = close + 1
            val_res = _read_braced(s, val_pos)
            if not val_res:
                continue
            val = val_res[0].replace(r"\%", "%")
            named_vals[(kind, key)] = val
            if kind == "raw":
                raw_fallback[key] = val
            continue

        am = re.match(r"^\\(?:provide|new)command\{\\([A-Za-z]+)\}(?=\{)", s)
        if am:
            cmd = am.group(1)
            val_res = _read_braced(s, am.end())
            if val_res:
                aliases[cmd] = val_res[0].replace(r"\%", "%")

    for (kind, key), val in list(named_vals.items()):
        if kind == "val" and r"\ensuremath" in val and key in raw_fallback:
            named_vals[(kind, key)] = raw_fallback[key]
    return named_vals, aliases


def _parse_generated_typ_data(raw: str) -> dict[tuple[str, str], str]:
    """解析 export_paper_macros.py 生成的 Typst results_fmt/results_pct/results_int 字典。"""
    typ_vals: dict[tuple[str, str], str] = {}
    section_map = {
        "results_flat": "flat",
        "results_fmt": "fmt",
        "results_pct": "pct",
        "results_int": "int",
    }
    block_re = re.compile(r"#let\s+(results_(?:flat|fmt|pct|int))\s*=\s*\((.*?)\n\)", re.S)
    entry_re = re.compile(r'"((?:[^"\\]|\\.)+)"\s*:\s*(?:"((?:[^"\\]|\\.)*)"|([-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?))')
    for bm in block_re.finditer(raw):
        kind = section_map[bm.group(1)]
        for em in entry_re.finditer(bm.group(2)):
            key = em.group(1).replace('\\"', '"').replace("\\\\", "\\")
            val_raw = em.group(2) if em.group(2) is not None else em.group(3)
            val = val_raw.replace('\\"', '"').replace("\\\\", "\\")
            typ_vals[(kind, key)] = val
    return typ_vals


def _expand_macros_in_text(
    text: str,
    suffix: str,
    tex_named: dict[tuple[str, str], str],
    tex_aliases: dict[str, str],
    typ_vals: dict[tuple[str, str], str],
) -> str:
    suf = suffix.lower()
    if suf == ".tex":
        cmd_map = {"ResVal": "val", "ResPct": "pct", "ResInt": "int", "ResRaw": "raw"}
        if tex_named:
            call_re = re.compile(r"\\(ResVal|ResPct|ResInt|ResRaw)\s*\{")
            out: list[str] = []
            pos = 0
            while True:
                m = call_re.search(text, pos)
                if not m:
                    out.append(text[pos:])
                    break
                out.append(text[pos : m.start()])
                br = _read_braced(text, m.end() - 1)
                if not br:
                    out.append(m.group(0))
                    pos = m.end()
                    continue
                key, next_pos = br
                kind = cmd_map[m.group(1)]
                val = tex_named.get((kind, key))
                out.append(f" {val} " if val is not None else text[m.start() : next_pos])
                pos = next_pos
            text = "".join(out)
        if tex_aliases:
            text = re.sub(
                r"\\([A-Za-z]+)(?![A-Za-z])",
                lambda m: f" {tex_aliases[m.group(1)]} " if m.group(1) in tex_aliases else m.group(0),
                text,
            )
    elif suf == ".typ" and typ_vals:
        def _repl_typ(m: re.Match[str]) -> str:
            sub = m.group(1)
            kind = "pct" if sub == "_pct" else ("int" if sub == "_int" else "fmt")
            key = m.group(2).replace('\\"', '"').replace("\\\\", "\\")
            val = typ_vals.get((kind, key))
            return f" {val} " if val is not None else m.group(0)

        text = re.sub(r'#?\bres(_pct|_int)?\(\s*"((?:[^"\\]|\\.)*)"\s*\)', _repl_typ, text)
    return text


def collect_paper_text(paper_path: Path) -> str:
    """收集论文源码文本（单文件或目录，自动解析生成的宏定义且不把未使用定义算作正文）。"""
    tex_named: dict[tuple[str, str], str] = {}
    tex_aliases: dict[str, str] = {}
    typ_vals: dict[tuple[str, str], str] = {}

    if paper_path.is_dir():
        files = sorted(
            p for p in paper_path.rglob("*")
            if p.suffix.lower() in PAPER_SUFFIXES and p.is_file()
        )
        if not files:
            print(f"[错误] 目录内未找到 .tex/.typ/.md/.txt 文件: {paper_path}")
            sys.exit(2)
        prose_files: list[tuple[Path, str]] = []
        for f in files:
            raw = f.read_text(encoding="utf-8", errors="ignore")
            if _is_generated_macro_file(raw):
                if f.suffix.lower() == ".tex":
                    nv, al = _parse_generated_tex_macros(raw)
                    tex_named.update(nv)
                    tex_aliases.update(al)
                elif f.suffix.lower() == ".typ":
                    typ_vals.update(_parse_generated_typ_data(raw))
                continue
            prose_files.append((f, raw))
        chunks = [
            _expand_macros_in_text(
                _strip_comments_for_suffix(raw, f.suffix),
                f.suffix,
                tex_named,
                tex_aliases,
                typ_vals,
            )
            for f, raw in prose_files
        ]
        return "\n\n".join(chunks)

    if paper_path.suffix.lower() == ".pdf":
        print("[错误] 请传入论文源码（.tex/.typ/.md/.txt）或源码目录，PDF 无法直接核对数字。")
        sys.exit(2)

    for sibling in sorted(paper_path.parent.glob("*")):
        if not sibling.is_file() or sibling.suffix.lower() not in (".tex", ".typ"):
            continue
        s_raw = sibling.read_text(encoding="utf-8", errors="ignore")
        if not _is_generated_macro_file(s_raw):
            continue
        if sibling.suffix.lower() == ".tex":
            nv, al = _parse_generated_tex_macros(s_raw)
            tex_named.update(nv)
            tex_aliases.update(al)
        else:
            typ_vals.update(_parse_generated_typ_data(s_raw))

    raw = paper_path.read_text(encoding="utf-8", errors="ignore")
    if _is_generated_macro_file(raw):
        return ""
    stripped = _strip_comments_for_suffix(raw, paper_path.suffix)
    return _expand_macros_in_text(stripped, paper_path.suffix, tex_named, tex_aliases, typ_vals)


def normalize_text(text: str) -> str:
    """归一化 Unicode 负号与 LaTeX 千分位写法：'−0.5'->'-0.5'，'2{,}777'、'2,777'->'2777'。"""
    text = text.replace("\u2212", "-")
    text = THOUSAND_RE.sub(r"\1\2", text)
    text = THOUSAND_COMMA_RE.sub(r"\1\2", text)
    return text


def extract_numbers(text: str) -> list[float]:
    return [float(m) for m in NUMBER_RE.findall(text)]


def clean_paper_text(text: str, strip_tex_comments: bool = True) -> str:
    r"""去掉「不是结果数字」的文本：参考文献、代码清单、LaTeX/Typst 指令参数、排版尺寸。"""
    text = re.sub(r"```.*?```", " ", text, flags=re.S)
    text = re.sub(r"\\begin\{thebibliography\}.*?\\end\{thebibliography\}", " ", text, flags=re.S)
    text = re.sub(r"\\begin\{lstlisting\}.*?\\end\{lstlisting\}", " ", text, flags=re.S)
    text = re.sub(r"\\lstinputlisting[^\n]*", " ", text)
    text = re.sub(
        r"\\(cite|ref|eqref|autoref|label|hyperref|usepackage|input|includegraphics)\b(\[[^\]]*\])?\{[^}]*\}",
        " ",
        text,
    )
    text = re.sub(r"#(?:cite|ref|label|import|include|image|bibliography)\s*\([^)]*\)", " ", text)
    text = re.sub(r"#(?:set|show)\s+[^\n]*", " ", text)
    text = re.sub(r"\\texttt\{[^}]*\}", " ", text)
    if strip_tex_comments:
        text = re.sub(r"(?<!\\)%[^\n]*", " ", text)
    # 排版尺寸与表格列定义里的数字不是结果（p{6.6cm}、0.95\textwidth、1fr 等）
    text = re.sub(r"\d+(?:\.\d+)?\s*(?:cm|mm|pt|em|ex|bp|in|fr)\b", " ", text)
    text = re.sub(r"\\(?:begin|end)\{tabular\}(?:\{@?[^}]*@?\})?", " ", text)
    text = re.sub(r"\\renewcommand\{[^}]*\}\{[^}]*\}", " ", text)
    text = re.sub(r"\\cftdotsep|\\linespread\{[^}]*\}", " ", text)
    return text


def find_untraceable(paper_text: str, checklist, tolerance: float, percent: bool,
                     min_abs: float = 1.0) -> list[tuple[str, float]]:
    """反向核对：论文里写了、但在 results.json 中找不到出处的「带小数」数字。"""
    known = [float(v) for _, v in checklist]
    out = []
    for m in re.finditer(r"[-+]?\d[\d,]*\.\d+", paper_text):
        try:
            n = float(m.group().replace(",", ""))
        except ValueError:
            continue
        if abs(n) < min_abs:
            continue
        cands = [n, abs(n)]
        if percent:
            cands += [n * 100.0, n / 100.0]
        hit = False
        for c in cands:
            for k in known:
                k = abs(k)
                if k >= 1e-12 and abs(c - k) <= max(tolerance * abs(c), 1e-6):
                    hit = True
                    break
            if hit:
                break
        if not hit:
            out.append((m.group(), n))
    return out


def _compile_path_glob(pat: str) -> re.Pattern[str]:
    """把结果路径模式编译为正则：'*' 匹配任意字符，'[*]' 匹配数组下标 '[0]'，其余 '['/']' 按字面匹配。"""
    parts = ["^"]
    i = 0
    n = len(pat)
    while i < n:
        if pat.startswith("[*]", i):
            parts.append(r"\[\d+\]")
            i += 3
        elif pat[i] == "*":
            parts.append(".*")
            i += 1
        elif pat[i] == "?":
            parts.append(".")
            i += 1
        else:
            parts.append(re.escape(pat[i]))
            i += 1
    parts.append("$")
    return re.compile("".join(parts))


def _matches_any(key: str, patterns: list[str] | tuple[str, ...]) -> bool:
    return any(_compile_path_glob(pat).match(key) is not None for pat in patterns)


def _parse_pattern_arg(items: list[str]) -> list[str]:
    out: list[str] = []
    for raw in items:
        for part in raw.split(","):
            s = part.strip()
            if s:
                out.append(s)
    return out


def _load_key_metrics_spec(spec: str, results: dict) -> list[str]:
    if spec:
        p = Path(spec)
        if p.is_file():
            raw = p.read_text(encoding="utf-8", errors="ignore").strip()
            if p.suffix.lower() == ".json":
                loaded = json.loads(raw)
                if isinstance(loaded, list):
                    return [str(x).strip() for x in loaded if str(x).strip()]
            return [
                ln.strip() for ln in raw.splitlines()
                if ln.strip() and not ln.lstrip().startswith("#")
            ]
        return _parse_pattern_arg([spec])
    auto = results.get("key_metrics")
    if isinstance(auto, list):
        return [str(x).strip() for x in auto if isinstance(x, str) and x.strip()]
    return []


def check(
    results_path: Path,
    paper_path: Path,
    tolerance: float,
    percent: bool,
    ignore_patterns: list[str] | tuple[str, ...] = (),
    key_metrics_spec: str = "",
) -> dict:
    """核对 results.json 与论文源码，返回统计与分类缺失列表。"""
    results = json.loads(results_path.read_text(encoding="utf-8"))
    checklist = flatten(results)
    key_metrics = _load_key_metrics_spec(key_metrics_spec, results if isinstance(results, dict) else {})

    paper_text = normalize_text(collect_paper_text(paper_path))
    numbers = extract_numbers(paper_text)

    def candidates(value: float) -> list[float]:
        cands = [value]
        if percent:
            cands += [value * 100.0, value / 100.0]
        return cands

    matched = 0
    ignored = 0
    critical_missing: list[tuple[str, float]] = []
    detail_omitted: list[tuple[str, float]] = []
    atol = 1e-6

    for key, value in checklist:
        if value != value or value in (float("inf"), float("-inf")):
            continue
        if ignore_patterns and _matches_any(key, ignore_patterns):
            ignored += 1
            continue
        ok = any(
            abs(n - c) <= max(tolerance * abs(c), atol)
            for c in candidates(value)
            for n in numbers
        )
        if ok:
            matched += 1
        elif key_metrics:
            if _matches_any(key, key_metrics):
                critical_missing.append((key, value))
            else:
                detail_omitted.append((key, value))
        else:
            if _matches_any(key, DEFAULT_DETAIL_PATTERNS):
                detail_omitted.append((key, value))
            else:
                critical_missing.append((key, value))

    return {
        "matched": matched,
        "ignored": ignored,
        "critical_missing": critical_missing,
        "detail_omitted": detail_omitted,
        "key_metrics_active": bool(key_metrics),
        "checklist": checklist,
    }


def self_test() -> int:
    with tempfile.TemporaryDirectory(prefix="ccheck_") as td:
        root = Path(td)
        res_path = root / "results.json"
        res_data = {
            "meta": {"params": {"q1_seed": 20260201}},
            "Q1": {"obj": 0.961, "delta_coef": -0.184, "beta_se": 0.032},
            "Q2": {
                "pareto": [{"eps": 0.416, "z1": 0.754, "z2": 0.5805, "z1_hat": 0.684, "z2_hat": 0.449}],
                "total_samples": 2777,
            },
        }
        res_path.write_text(json.dumps(res_data, ensure_ascii=False), encoding="utf-8")

        # 1. LaTeX + percent + thousand sep + Unicode minus -> only detail_omitted (beta_se, seed, pareto[0].*), exit 0
        tex_dir = root / "paper_tex"
        tex_dir.mkdir()
        (tex_dir / "main.tex").write_text(
            "% comment 99.999 should be skipped\n"
            r"Sample size is 2{,}777, ECR reaches 96.1\%, $\delta = −0.184$, anchors $0.754$ and $0.5805$." "\n"
            r"\includegraphics[width=12.5cm]{fig1.pdf}" "\n",
            encoding="utf-8",
        )
        rep1 = check(res_path, tex_dir, 1e-3, percent=True)
        assert rep1["matched"] == 5, rep1
        assert not rep1["critical_missing"], rep1["critical_missing"]
        detail_keys1 = {k for k, _ in rep1["detail_omitted"]}
        assert (
            "Q1.beta_se" in detail_keys1
            and "Q2.pareto[0].z1_hat" in detail_keys1
            and "Q2.pareto[0].eps" in detail_keys1
        ), detail_keys1

        # 5. CLI check: without --strict-all exits 0; with --strict-all exits 1 on detail_omitted
        base_cmd = [sys.executable, str(Path(__file__).resolve()), "--results", str(res_path), "--paper", str(tex_dir), "--percent"]
        r_ok = subprocess.run(base_cmd, capture_output=True, text=True)
        assert r_ok.returncode == 0, r_ok.stdout + r_ok.stderr
        r_strict = subprocess.run([*base_cmd, "--strict-all"], capture_output=True, text=True)
        assert r_strict.returncode == 1, r_strict.stdout + r_strict.stderr

        # 2. Typst support + comments/image stripping + check-fabricated catches hallucination 12.345 only
        typ_dir = root / "paper_typ"
        typ_dir.mkdir()
        (typ_dir / "main.typ").write_text(
            "#set page(margin: 2.5cm)\n"
            "#grid(columns: (1fr, 2fr))\n"
            "// 88.888 inline comment must be stripped\n"
            "/* 77.777 block comment must be stripped */\n"
            '#image("fig_3.14.svg", width: 90%)\n'
            "Total n = 2,777, rate = 96.1%, shift = −0.184, z = (0.754, 0.5805), fake = 12.345.\n",
            encoding="utf-8",
        )
        rep2 = check(res_path, typ_dir, 1e-3, percent=True)
        assert rep2["matched"] == 5 and not rep2["critical_missing"], rep2
        cleaned_typ = clean_paper_text(normalize_text(collect_paper_text(typ_dir)), strip_tex_comments=False)
        bad2 = find_untraceable(cleaned_typ, rep2["checklist"], 1e-3, percent=True)
        bad_lits = [lit for lit, _ in bad2]
        assert bad_lits == ["12.345"], bad2

        # 3. Core metric missing -> CRITICAL_MISSING; --ignore-patterns filters it cleanly
        (tex_dir / "main.tex").write_text(r"Only $n=2{,}777$, $z=(0.754, 0.5805)$." "\n", encoding="utf-8")
        rep3 = check(res_path, tex_dir, 1e-3, percent=True)
        crit3 = {k for k, _ in rep3["critical_missing"]}
        assert "Q1.obj" in crit3 and "Q1.delta_coef" in crit3, crit3
        rep3_ign = check(res_path, tex_dir, 1e-3, percent=True, ignore_patterns=["Q1.*"])
        assert not rep3_ign["critical_missing"] and rep3_ign["ignored"] >= 3, rep3_ign

        # 4. --key-metrics focuses strictness only on listed key metrics
        rep4 = check(res_path, tex_dir, 1e-3, percent=True, key_metrics_spec="Q2.total_samples,Q2.pareto[*].z1")
        assert not rep4["critical_missing"], rep4["critical_missing"]
        assert any(k == "Q1.obj" for k, _ in rep4["detail_omitted"]), rep4["detail_omitted"]

        # 6. Generated results_macros.tex expansion WITHOUT masking unreferenced keys
        macro_dir = root / "paper_macro"
        macro_dir.mkdir()
        (macro_dir / "results_macros.tex").write_text(
            "% GENERATED-BY: export_paper_macros.py\n"
            r"\makeatletter" "\n"
            r"\@namedef{res@pct@\detokenize{Q1.obj}}{96.10\%}" "\n"
            r"\@namedef{res@val@\detokenize{Q1.delta_coef}}{-0.1840}" "\n"
            r"\@namedef{res@int@\detokenize{Q2.total_samples}}{2{,}777}" "\n"
            r"\@namedef{res@val@\detokenize{Q2.pareto[0].z1}}{0.7540}" "\n"
            r"\providecommand{\ValQOneObj}{0.9610}" "\n"
            r"\providecommand{\ValQOneDeltaCoef}{-0.1840}" "\n"
            r"\makeatother" "\n",
            encoding="utf-8",
        )
        (macro_dir / "main.tex").write_text(
            r"ECR is \ResPct{Q1.obj} over \ResInt{Q2.total_samples} couples; z1=\ResVal{Q2.pareto[0].z1}, z2=0.5805." "\n",
            encoding="utf-8",
        )
        rep6 = check(res_path, macro_dir, 1e-3, percent=True)
        crit6 = {k for k, _ in rep6["critical_missing"]}
        assert crit6 == {"Q1.delta_coef"}, f"Unused Q1.delta_coef must stay missing, got {crit6}"
        assert rep6["matched"] == 4, rep6

    print("[SELF-TEST] PASS 6/6")
    return 0


def main() -> int:
    if "--self-test" in sys.argv:
        return self_test()

    parser = argparse.ArgumentParser(description="核对论文数字与 results.json 的一致性")
    parser.add_argument("--results", required=True, help="work/results.json")
    parser.add_argument("--paper", required=True, help="论文源码 .tex/.typ/.md/.txt 或其所在目录")
    parser.add_argument("--tolerance", type=float, default=1e-3, help="相对容差，默认 1e-3")
    parser.add_argument("--percent", action="store_true",
                        help="同时尝试 value、value*100、value/100 的匹配（兼容百分比表述）")
    parser.add_argument("--check-fabricated", action="store_true",
                        help="反向核对：列出论文里带小数、但在 results.json 中找不到出处的数字")
    parser.add_argument("--ignore-patterns", action="append", default=[],
                        help="可重复或逗号分隔 fnmatch 通配符，匹配路径将从正向核对中忽略")
    parser.add_argument("--key-metrics", default="",
                        help="核心指标路径模式（逗号分隔 fnmatch 或 JSON/文本清单路径）；未传时自动读取 results.json 顶层 key_metrics")
    parser.add_argument("--strict-all", action="store_true",
                        help="严格模式：连同辅助明细省略（DETAIL_OMITTED）也视为未通过并返回退出码 1")
    parser.add_argument("--self-test", action="store_true", help="运行内置回归自检")
    args = parser.parse_args()

    results_path = Path(args.results)
    paper_path = Path(args.paper)
    if not results_path.exists():
        print(f"[错误] results 文件不存在: {results_path}")
        return 2
    if not paper_path.exists():
        print(f"[错误] paper 文件/目录不存在: {paper_path}")
        return 2

    ignore_patterns = _parse_pattern_arg(args.ignore_patterns)
    rep = check(
        results_path,
        paper_path,
        args.tolerance,
        args.percent,
        ignore_patterns=ignore_patterns,
        key_metrics_spec=args.key_metrics,
    )

    if args.check_fabricated:
        raw = normalize_text(collect_paper_text(paper_path))
        cleaned = clean_paper_text(raw, strip_tex_comments=False)
        bad = find_untraceable(cleaned, rep["checklist"], args.tolerance, args.percent)
        print(f"\n反向核对：论文中带小数且无出处的数字 {len(bad)} 个"
              f"（差值/比值/单位换算等合法派生量也会入选，需逐条人工确认）：")
        seen = set()
        for lit, val in bad:
            if lit in seen:
                continue
            seen.add(lit)
            print(f"  ? {lit}")

    crit = rep["critical_missing"]
    detail = rep["detail_omitted"]
    print(
        f"核对完成：匹配 {rep['matched']} 个，关键缺失 {len(crit)} 个，"
        f"辅助明细省略 {len(detail)} 个（已忽略 {rep['ignored']} 个）。"
    )
    if crit:
        print("\n[CRITICAL_MISSING] 以下关键结果未在论文中找到对应数字（请核实补全）：")
        for key, value in crit:
            print(f"  - {key} = {value}")
    if detail:
        print("\n[DETAIL_OMITTED] 以下辅助/中间明细未直接见于正文（标准误、网格明细或归一化坐标等，抽样前 15 项）：")
        for key, value in detail[:15]:
            print(f"  - {key} = {value}")
        if len(detail) > 15:
            print(f"  ... 等共 {len(detail)} 项")

    if crit or (args.strict_all and detail):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
