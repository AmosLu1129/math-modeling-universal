#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""run_manifest.yaml 状态机、SHA-256 指纹与 DAG 失效传播 CLI（纯 Python 标准库，无 PyYAML 依赖）。

严格遵循 `../_shared/references/workflow-contract.md`：
- 阶段状态枚举仅限：PENDING | READY | BLOCKED | WAITING_HUMAN | RUNNING | PASS | FAIL | N/A | WAIVED
- 决策状态枚举仅限：pending | defaulted | confirmed | waived
- 产物状态枚举仅限：current | stale（绝不自动删除 stale 文件）

用法：
    python manifest_cli.py init --project . --competition MCM --language en --mode o_award
    python manifest_cli.py status --manifest work/run_manifest.yaml [--strict] [--json]
    python manifest_cli.py sync --manifest work/run_manifest.yaml [--dry-run] [--fail-on-stale]
    python manifest_cli.py mark-current --manifest work/run_manifest.yaml --stage S7_figures
    python manifest_cli.py invalidate --manifest work/run_manifest.yaml --artifact work/results.json
    python manifest_cli.py approve --manifest work/run_manifest.yaml --id P1_model_formulation --status confirmed
    python manifest_cli.py request --manifest work/run_manifest.yaml --id req_01 --stage S7_figures --kind visual_asset --status pending --ticket work/human_requests/req_01.md
    python manifest_cli.py --self-test
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import tempfile
from collections import deque
from pathlib import Path
from typing import Any

SCRIPTS_DIR = Path(__file__).resolve().parent
TEMPLATE_MANIFEST = SCRIPTS_DIR.parent / "templates" / "run_manifest.yaml"

STAGE_STATES = frozenset({"PENDING", "READY", "BLOCKED", "WAITING_HUMAN", "RUNNING", "PASS", "FAIL", "N/A", "WAIVED"})

STAGE_ORDER: tuple[str, ...] = (
    "S0_setup",
    "S1_problem_analysis",
    "S2_data_prep",
    "S3_literature_review",
    "S4_model_design",
    "S5_solver",
    "S6_validation",
    "S7_figures",
    "S8_paper_writing",
    "S9_humanize",
    "S10_review_deliver",
)

STAGE_SPECS: dict[str, dict[str, Any]] = {
    "S0_setup": {
        "deps": (),
        "outputs": [],
        "cmd": "python ../_shared/scripts/setup_env.py",
    },
    "S1_problem_analysis": {
        "deps": ("S0_setup",),
        "outputs": ["work/problem_integrity_report.md", "work/brief.md"],
        "cmd": "python ../_shared/scripts/problem_integrity_check.py input/problem.pdf --out work/problem_integrity_report.md",
    },
    "S2_data_prep": {
        "deps": ("S1_problem_analysis",),
        "outputs": ["work/data_clean/", "work/data_dictionary.md", "work/eda_report.md"],
        "cmd": "重新执行数据清洗与 EDA 脚本（math-data-prep）",
    },
    "S3_literature_review": {
        "deps": ("S1_problem_analysis",),
        "outputs": ["work/references.csv", "work/lit_review.md"],
        "cmd": "python ../_shared/scripts/verify_references.py work/references.csv",
    },
    "S4_model_design": {
        "deps": ("S1_problem_analysis", "S2_data_prep", "S3_literature_review"),
        "outputs": ["work/model_doc.md", "work/graph_abstraction.md"],
        "cmd": "python ../_shared/scripts/check_formulation.py --work work/ --phase p1",
    },
    "S5_solver": {
        "deps": ("S4_model_design",),
        "outputs": ["work/code/", "work/results.json", "work/constraint_check.md", "work/iteration_log.md"],
        "cmd": "重跑 work/code/ 求解并执行 check_formulation.py --work work/ --phase p3",
    },
    "S6_validation": {
        "deps": ("S5_solver",),
        "outputs": ["work/validation_report.md", "work/final_models.md", "work/fact_sheet.md"],
        "cmd": "重跑模型验证后生成 fact_sheet.md 并执行 check_formulation.py --work work/ --phase all",
    },
    "S7_figures": {
        "deps": ("S6_validation",),
        "outputs": ["work/figures/", "work/tables/", "work/figures/qa_ledger.md"],
        "cmd": "重跑绘图脚本并执行 figure_qa.py / layout_qa.py / contact_sheet.py",
    },
    "S8_paper_writing": {
        "deps": ("S6_validation", "S7_figures"),
        "outputs": ["output/paper/results_macros.tex", "output/paper/results_data.typ", "output/paper/main.tex", "output/paper/paper.pdf"],
        "cmd": "python ../_shared/scripts/export_paper_macros.py --results work/results.json ... 并重编译论文",
    },
    "S9_humanize": {
        "deps": ("S8_paper_writing",),
        "outputs": ["output/paper/sections/B_ai_report.tex"],
        "cmd": "执行 math-paper-humanize 润色与 invariance_check.py",
    },
    "S10_review_deliver": {
        "deps": ("S8_paper_writing", "S9_humanize"),
        "outputs": ["work/review_report.md", "output/code_appendix.pdf", "output/submission/"],
        "cmd": "执行 paper_qa.py + consistency_check.py + code_appendix.py 并刷新 output/submission/",
    },
}

SKIP_DIR_NAMES = {"__pycache__", ".git", ".pytest_cache"}
SKIP_FILE_SUFFIXES = {".pyc", ".pyo", ".aux", ".log", ".out", ".toc", ".bbl", ".blg"}
SKIP_FILE_NAMES = {".DS_Store", "Thumbs.db", "contact_sheet.png"}


# ==========================================================================
# Pure-Stdlib YAML Subset Parser & Canonical Emitter
# ==========================================================================

def _strip_yaml_comment(line: str) -> str:
    in_sq = False
    in_dq = False
    i = 0
    n = len(line)
    while i < n:
        ch = line[i]
        if in_dq:
            if ch == "\\" and i + 1 < n:
                i += 2
                continue
            if ch == '"':
                in_dq = False
        elif in_sq:
            if ch == "'" and i + 1 < n and line[i + 1] == "'":
                i += 2
                continue
            if ch == "'":
                in_sq = False
        else:
            if ch == '"':
                in_dq = True
            elif ch == "'":
                in_sq = True
            elif ch == "#" and (i == 0 or line[i - 1].isspace()):
                return line[:i]
        i += 1
    return line


def _split_top_level(s: str, sep: str = ",") -> list[str]:
    parts: list[str] = []
    buf: list[str] = []
    depth_sq = 0
    depth_cb = 0
    in_sq = False
    in_dq = False
    i = 0
    n = len(s)
    while i < n:
        ch = s[i]
        if in_dq:
            buf.append(ch)
            if ch == "\\" and i + 1 < n:
                buf.append(s[i + 1])
                i += 2
                continue
            if ch == '"':
                in_dq = False
        elif in_sq:
            buf.append(ch)
            if ch == "'" and i + 1 < n and s[i + 1] == "'":
                buf.append("'")
                i += 2
                continue
            if ch == "'":
                in_sq = False
        else:
            if ch == '"':
                in_dq = True
                buf.append(ch)
            elif ch == "'":
                in_sq = True
                buf.append(ch)
            elif ch == "[":
                depth_sq += 1
                buf.append(ch)
            elif ch == "]":
                depth_sq = max(0, depth_sq - 1)
                buf.append(ch)
            elif ch == "{":
                depth_cb += 1
                buf.append(ch)
            elif ch == "}":
                depth_cb = max(0, depth_cb - 1)
                buf.append(ch)
            elif ch == sep and depth_sq == 0 and depth_cb == 0:
                parts.append("".join(buf).strip())
                buf = []
            else:
                buf.append(ch)
        i += 1
    tail = "".join(buf).strip()
    if tail or parts:
        parts.append(tail)
    return [p for p in parts if p]


def _split_kv(s: str) -> tuple[str, str] | None:
    depth_sq = 0
    depth_cb = 0
    in_sq = False
    in_dq = False
    i = 0
    n = len(s)
    while i < n:
        ch = s[i]
        if in_dq:
            if ch == "\\" and i + 1 < n:
                i += 2
                continue
            if ch == '"':
                in_dq = False
        elif in_sq:
            if ch == "'" and i + 1 < n and s[i + 1] == "'":
                i += 2
                continue
            if ch == "'":
                in_sq = False
        else:
            if ch == '"':
                in_dq = True
            elif ch == "'":
                in_sq = True
            elif ch == "[":
                depth_sq += 1
            elif ch == "]":
                depth_sq = max(0, depth_sq - 1)
            elif ch == "{":
                depth_cb += 1
            elif ch == "}":
                depth_cb = max(0, depth_cb - 1)
            elif ch == ":" and depth_sq == 0 and depth_cb == 0:
                if i + 1 == n or s[i + 1].isspace():
                    return s[:i].strip(), s[i + 1 :].strip()
        i += 1
    return None


def _parse_scalar(tok: str) -> Any:
    s = tok.strip()
    if not s or s in ("null", "Null", "NULL", "~"):
        return None
    if s in ("true", "True", "TRUE"):
        return True
    if s in ("false", "False", "FALSE"):
        return False
    if len(s) >= 2 and s[0] == '"' and s[-1] == '"':
        inner = s[1:-1]
        inner = inner.replace('\\"', '"').replace("\\n", "\n").replace("\\t", "\t").replace("\\\\", "\\")
        return inner
    if len(s) >= 2 and s[0] == "'" and s[-1] == "'":
        return s[1:-1].replace("''", "'")
    if re.fullmatch(r"-?(?:0|[1-9]\d*)", s):
        return int(s)
    if re.fullmatch(r"-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][-+]?\d+)?", s) and ("." in s or "e" in s.lower()):
        return float(s)
    return s


def _parse_value(tok: str) -> Any:
    s = tok.strip()
    if not s:
        return None
    if s.startswith("[") and s.endswith("]"):
        inner = s[1:-1].strip()
        if not inner:
            return []
        return [_parse_value(p) for p in _split_top_level(inner)]
    if s.startswith("{") and s.endswith("}"):
        inner = s[1:-1].strip()
        if not inner:
            return {}
        out: dict[str, Any] = {}
        for part in _split_top_level(inner):
            kv = _split_kv(part)
            if kv is None:
                raise ValueError(f"Invalid YAML flow mapping item: {part!r}")
            k_raw, v_raw = kv
            k = str(_parse_scalar(k_raw))
            out[k] = _parse_value(v_raw)
        return out
    return _parse_scalar(s)


def _parse_block(lines: list[tuple[int, str]], idx: int, base_indent: int) -> tuple[Any, int]:
    if idx >= len(lines):
        return {}, idx
    first_indent, first_txt = lines[idx]
    if first_txt == "-" or first_txt.startswith("- "):
        return _parse_seq(lines, idx, first_indent)
    return _parse_map(lines, idx, base_indent)


def _parse_seq(lines: list[tuple[int, str]], idx: int, seq_indent: int) -> tuple[list[Any], int]:
    items: list[Any] = []
    n = len(lines)
    while idx < n:
        indent, txt = lines[idx]
        if indent < seq_indent:
            break
        if indent > seq_indent:
            raise ValueError(f"Unexpected indent in YAML sequence near: {txt!r}")
        if not (txt == "-" or txt.startswith("- ")):
            break
        rest = "" if txt == "-" else txt[2:].lstrip()
        idx += 1
        if not rest:
            if idx < n and lines[idx][0] > seq_indent:
                child, idx = _parse_block(lines, idx, lines[idx][0])
                items.append(child)
            else:
                items.append(None)
            continue

        kv = _split_kv(rest)
        if kv is not None and not (rest.startswith("{") or rest.startswith("[") or rest.startswith('"') or rest.startswith("'")):
            k_raw, v_raw = kv
            item_dict: dict[str, Any] = {}
            k = str(_parse_scalar(k_raw))
            if v_raw == "":
                if idx < n and lines[idx][0] > seq_indent + 1:
                    val, idx = _parse_block(lines, idx, lines[idx][0])
                else:
                    val = None
            else:
                val = _parse_value(v_raw)
            item_dict[k] = val
            if idx < n and lines[idx][0] > seq_indent:
                more, idx = _parse_map(lines, idx, lines[idx][0])
                if isinstance(more, dict):
                    item_dict.update(more)
            items.append(item_dict)
        else:
            items.append(_parse_value(rest))
    return items, idx


def _parse_map(lines: list[tuple[int, str]], idx: int, map_indent: int) -> tuple[dict[str, Any], int]:
    mapping: dict[str, Any] = {}
    n = len(lines)
    while idx < n:
        indent, txt = lines[idx]
        if indent < map_indent:
            break
        if indent > map_indent:
            raise ValueError(f"Unexpected indent in YAML mapping near: {txt!r}")
        if txt == "-" or txt.startswith("- "):
            break
        kv = _split_kv(txt)
        if kv is None:
            raise ValueError(f"Invalid YAML mapping line: {txt!r}")
        k_raw, v_raw = kv
        key = str(_parse_scalar(k_raw))
        idx += 1
        if v_raw == "":
            if idx < n:
                nxt_ind, nxt_txt = lines[idx]
                if nxt_ind > indent:
                    val, idx = _parse_block(lines, idx, nxt_ind)
                elif nxt_ind == indent and (nxt_txt == "-" or nxt_txt.startswith("- ")):
                    val, idx = _parse_seq(lines, idx, nxt_ind)
                else:
                    val = None
            else:
                val = None
        else:
            val = _parse_value(v_raw)
        mapping[key] = val
    return mapping, idx


def parse_yaml(text: str) -> dict[str, Any]:
    """解析受支持子集 YAML，返回顶层 dict。"""
    cleaned: list[tuple[int, str]] = []
    for raw_ln in text.splitlines():
        stripped_comment = _strip_yaml_comment(raw_ln).rstrip()
        if not stripped_comment.strip():
            continue
        indent = len(stripped_comment) - len(stripped_comment.lstrip(" "))
        cleaned.append((indent, stripped_comment.strip()))
    if not cleaned:
        return {}
    res, _ = _parse_block(cleaned, 0, cleaned[0][0])
    if not isinstance(res, dict):
        raise ValueError("Manifest root must be a YAML mapping")
    return res


def _yaml_scalar(val: Any) -> str:
    if val is None:
        return "null"
    if isinstance(val, bool):
        return "true" if val else "false"
    if isinstance(val, (int, float)):
        return str(val)
    s = str(val)
    if s == "":
        return '""'
    needs_quote = (
        s in ("null", "Null", "NULL", "~", "true", "True", "TRUE", "false", "False", "FALSE")
        or bool(re.fullmatch(r"-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?", s))
        or s[0].isspace()
        or s[-1].isspace()
        or any(ch in s for ch in (": ", "#", "{", "}", "[", "]", ",", '"', "'", "\n", "\r", "\\"))
        or s.endswith(":")
    )
    if not needs_quote:
        return s
    escaped = s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
    return f'"{escaped}"'


def _yaml_flow(val: Any) -> str:
    if isinstance(val, list):
        return "[" + ", ".join(_yaml_flow(x) for x in val) + "]"
    if isinstance(val, dict):
        items = [f"{_yaml_scalar(k)}: {_yaml_flow(v)}" for k, v in val.items()]
        return "{" + ", ".join(items) + "}"
    return _yaml_scalar(val)


def _is_leaf_flow_dict(val: Any) -> bool:
    if not isinstance(val, dict) or not val:
        return False
    return all(
        not isinstance(v, dict)
        and (not isinstance(v, list) or all(not isinstance(x, (dict, list)) for x in v))
        for v in val.values()
    )


def dump_yaml(data: dict[str, Any]) -> str:
    """以清晰规范格式输出 run_manifest.yaml。"""
    lines: list[str] = []
    preferred = ["schema", "project", "decisions", "stages", "artifacts", "approvals", "human_requests"]
    keys = [k for k in preferred if k in data] + [k for k in data if k not in preferred]

    def emit_kv(k: str, v: Any, indent: int, flow_leaf_dicts: bool) -> None:
        pad = " " * indent
        k_str = _yaml_scalar(k)
        if v is None or isinstance(v, (bool, int, float, str)):
            lines.append(f"{pad}{k_str}: {_yaml_scalar(v)}")
        elif isinstance(v, list):
            if not v or all(not isinstance(x, (dict, list)) for x in v):
                lines.append(f"{pad}{k_str}: {_yaml_flow(v)}")
            else:
                lines.append(f"{pad}{k_str}:")
                for item in v:
                    if isinstance(item, dict) and item:
                        first = True
                        for ik, iv in item.items():
                            prefix = f"{pad}  - " if first else f"{pad}    "
                            first = False
                            if isinstance(iv, (dict, list)):
                                lines.append(f"{prefix}{_yaml_scalar(ik)}: {_yaml_flow(iv)}")
                            else:
                                lines.append(f"{prefix}{_yaml_scalar(ik)}: {_yaml_scalar(iv)}")
                    else:
                        lines.append(f"{pad}  - {_yaml_flow(item)}")
        elif isinstance(v, dict):
            if not v:
                lines.append(f"{pad}{k_str}: {{}}")
            elif flow_leaf_dicts and _is_leaf_flow_dict(v):
                lines.append(f"{pad}{k_str}: {_yaml_flow(v)}")
            else:
                lines.append(f"{pad}{k_str}:")
                for sk, sv in v.items():
                    emit_kv(str(sk), sv, indent + 2, flow_leaf_dicts=flow_leaf_dicts)

    for k in keys:
        emit_kv(k, data[k], 0, flow_leaf_dicts=(k in ("decisions", "artifacts")))
    return "\n".join(lines) + "\n"


# ==========================================================================
# Deterministic SHA-256 Hashing & Canonical DAG Propagation
# ==========================================================================

def norm_rel(p: str) -> str:
    s = p.replace("\\", "/").strip()
    while s.startswith("./"):
        s = s[2:]
    return s


def compute_artifact_hash(project_root: Path, rel_path: str) -> tuple[str | None, bool]:
    """计算文件或目录的确定性 SHA-256；返回 `(sha256_hex_or_None, exists)`。"""
    rel = norm_rel(rel_path).rstrip("/")
    target = project_root / rel
    if not target.exists():
        return None, False
    if target.is_file():
        h = hashlib.sha256()
        with target.open("rb") as fh:
            for chunk in iter(lambda: fh.read(65536), b""):
                h.update(chunk)
        return h.hexdigest(), True
    if target.is_dir():
        h = hashlib.sha256()
        files: list[Path] = []
        for f in sorted(target.rglob("*")):
            if not f.is_file():
                continue
            parts = set(f.relative_to(target).parts)
            if parts & SKIP_DIR_NAMES:
                continue
            if f.name in SKIP_FILE_NAMES or f.name.startswith("_preview"):
                continue
            if f.suffix.lower() in SKIP_FILE_SUFFIXES:
                continue
            files.append(f)
        if not files:
            return None, False
        for f in files:
            rel_f = f.relative_to(target).as_posix()
            fh_hash = hashlib.sha256(f.read_bytes()).hexdigest()
            h.update(f"{rel_f}:{fh_hash}\n".encode("utf-8"))
        return h.hexdigest(), True
    return None, False


def _infer_producer(rel_path: str) -> str:
    n = norm_rel(rel_path)
    if n.startswith("input/"):
        return "user"
    for st, spec in STAGE_SPECS.items():
        for out in spec["outputs"]:
            if n == out or (out.endswith("/") and n.startswith(out)):
                return st
    if n.startswith("output/paper/"):
        return "S8_paper_writing"
    return "workflow"


def _infer_kind(rel_path: str, producer: str) -> str:
    n = norm_rel(rel_path)
    if n.startswith("input/") or n in ("work/model_doc.md", "work/results.json", "work/code/"):
        return "source"
    if any(tok in n for tok in ("integrity_report", "constraint_check", "validation_report", "review_report", "qa_ledger")):
        return "audit"
    if producer in ("S1_problem_analysis", "S4_model_design") and n.endswith(("problem_integrity_report.md",)):
        return "audit"
    return "derived"


def _infer_project_root(manifest_path: Path, project_arg: str) -> Path:
    if project_arg:
        return Path(project_arg).resolve()
    mp = manifest_path.resolve()
    if mp.parent.name == "work":
        return mp.parent.parent
    return mp.parent


def _discover_artifacts(project_root: Path, existing: dict[str, Any], stages: dict[str, Any]) -> dict[str, Any]:
    artifacts = dict(existing)

    def ensure_entry(key: str, depends_on: list[str] | None = None) -> None:
        if key in artifacts:
            return
        prod = _infer_producer(key)
        artifacts[key] = {
            "kind": _infer_kind(key, prod),
            "producer": prod,
            "depends_on": depends_on or [],
            "status": "current",
        }

    # 1. Input files
    inp_dir = project_root / "input"
    if inp_dir.is_dir():
        for f in sorted(inp_dir.rglob("*")):
            if f.is_file() and f.name not in SKIP_FILE_NAMES:
                ensure_entry(f.relative_to(project_root).as_posix(), [])

    # 2. Existing outputs from tracked stages or canonical stage outputs that exist on disk
    for st in STAGE_ORDER:
        st_info = stages.get(st, {})
        cand_outs = list(st_info.get("outputs") or []) + list(STAGE_SPECS[st]["outputs"])
        seen: set[str] = set()
        for out in cand_outs:
            if out == "work/run_manifest.yaml" or out in seen:
                continue
            seen.add(out)
            if out in artifacts or (project_root / out.rstrip("/")).exists():
                deps = list(st_info.get("inputs") or [])
                ensure_entry(out, deps)

    return artifacts


def _build_dependency_graph(artifacts: dict[str, Any], stages: dict[str, Any]) -> dict[str, set[str]]:
    """构建有向传播边：upstream_artifact -> {downstream_artifacts}。"""
    edges: dict[str, set[str]] = {k: set() for k in artifacts}

    def add_edge(u: str, v: str) -> None:
        if u != v and u in artifacts and v in artifacts:
            edges[u].add(v)

    # 1. Explicit artifact depends_on
    for art_key, meta in artifacts.items():
        if not isinstance(meta, dict):
            continue
        for dep in meta.get("depends_on") or []:
            dep_norm = norm_rel(str(dep))
            if dep_norm in artifacts:
                add_edge(dep_norm, art_key)
            elif dep_norm.endswith("/"):
                for k in artifacts:
                    if k.startswith(dep_norm):
                        add_edge(k, art_key)

    # 2. Canonical intra-stage & cross-stage dependency edges from workflow-contract §4
    stage_idx = {st: i for i, st in enumerate(STAGE_ORDER)}
    by_producer: dict[str, list[str]] = {}
    for k, meta in artifacts.items():
        prod = str((meta or {}).get("producer") or _infer_producer(k))
        by_producer.setdefault(prod, []).append(k)

    # Cross-stage edges according to STAGE_SPECS deps
    for downstream_st, spec in STAGE_SPECS.items():
        for upstream_st in spec["deps"]:
            for u in by_producer.get(upstream_st, []):
                for v in by_producer.get(downstream_st, []):
                    add_edge(u, v)

    # Special intra-stage workflow-contract dependencies:
    # - work/code/ changes invalidate work/results.json, work/constraint_check.md
    for code_art in [k for k in artifacts if k.rstrip("/") == "work/code"]:
        for v in ("work/results.json", "work/constraint_check.md"):
            add_edge(code_art, v)
    # - work/problem_integrity_report.md feeds work/brief.md
    add_edge("work/problem_integrity_report.md", "work/brief.md")
    # - results_macros / main.tex / sections -> paper.pdf -> sections/B_ai_report.tex / review / appendix
    for paper_src in [k for k in artifacts if k.startswith("output/paper/") and not k.endswith("paper.pdf")]:
        add_edge(paper_src, "output/paper/paper.pdf")
    # - work/results.json changes must propagate to validation/figures/tables/paper even if producer heuristic differs
    if "work/results.json" in artifacts:
        for k, meta in artifacts.items():
            prod = str((meta or {}).get("producer") or _infer_producer(k))
            if stage_idx.get(prod, -1) >= stage_idx["S6_validation"]:
                add_edge("work/results.json", k)
    return edges


def _propagate_stale(start_nodes: list[str], edges: dict[str, set[str]], artifacts: dict[str, Any]) -> list[str]:
    """从变更起点按 BFS 标记全部传递下游为 stale，返回新被标脏的产物列表。"""
    newly_staled: list[str] = []
    q: deque[str] = deque()
    visited: set[str] = set()
    for s in start_nodes:
        for nxt in edges.get(s, ()):
            if nxt not in visited:
                visited.add(nxt)
                q.append(nxt)
    while q:
        cur = q.popleft()
        meta = artifacts.get(cur)
        if isinstance(meta, dict):
            if meta.get("status") != "stale":
                newly_staled.append(cur)
            meta["status"] = "stale"
        for nxt in edges.get(cur, ()):
            if nxt not in visited:
                visited.add(nxt)
                q.append(nxt)
    return newly_staled


def _update_stages_from_artifacts(data: dict[str, Any]) -> list[str]:
    """根据当前 stale 产物更新受影响下游阶段状态（严格遵循 workflow-contract §2 枚举）。"""
    stages = data.setdefault("stages", {})
    artifacts = data.get("artifacts", {})
    stale_set = {k for k, m in artifacts.items() if isinstance(m, dict) and m.get("status") == "stale"}

    # Check if any stage owns a stale artifact
    affected_stages: list[str] = []
    for st in STAGE_ORDER:
        if st == "S0_setup":
            continue
        st_info = stages.get(st)
        if not isinstance(st_info, dict):
            continue
        cur_status = str(st_info.get("status") or "PENDING")
        if cur_status in ("N/A", "WAIVED"):
            continue
        owned_outs = set(st_info.get("outputs") or []) | set(STAGE_SPECS[st]["outputs"])
        owns_stale = any(
            k in owned_outs or any(out.endswith("/") and k.startswith(out) for out in owned_outs)
            for k in stale_set
        )
        if not owns_stale:
            continue

        affected_stages.append(st)
        if cur_status == "BLOCKED":
            continue
        # Direct upstream stages must be PASS / N/A / WAIVED and not in affected_stages
        deps_ok = True
        for dep_st in STAGE_SPECS[st]["deps"]:
            dep_info = stages.get(dep_st, {})
            dep_stat = str(dep_info.get("status") or "PASS") if isinstance(dep_info, dict) else "PASS"
            if dep_st in affected_stages or dep_stat not in ("PASS", "N/A", "WAIVED"):
                deps_ok = False
                break
        st_info["status"] = "READY" if deps_ok else "PENDING"
        if "gate" in st_info and st_info["gate"] == "PASS":
            st_info["gate"] = "PENDING"
    return affected_stages


def cmd_init(args: argparse.Namespace) -> int:
    proj = Path(args.project).resolve()
    manifest_path = Path(args.manifest)
    if not manifest_path.is_absolute():
        manifest_path = proj / manifest_path

    if manifest_path.exists() and not args.force:
        print(f"[提示] manifest 已存在：{manifest_path}（如需重置请加 --force，或直接执行 sync/status）")
        return 0

    if TEMPLATE_MANIFEST.is_file():
        data = parse_yaml(TEMPLATE_MANIFEST.read_text(encoding="utf-8"))
    else:
        data = {"schema": 1, "project": {}, "decisions": {}, "stages": {}, "artifacts": {}, "approvals": [], "human_requests": []}

    proj_blk = data.setdefault("project", {})
    if args.competition:
        proj_blk["competition"] = args.competition
    if args.language:
        proj_blk["language"] = args.language
    if args.mode:
        proj_blk["mode"] = args.mode
    if args.time_budget is not None:
        proj_blk["time_budget_hours"] = args.time_budget

    decisions = data.setdefault("decisions", {})
    if str(proj_blk.get("mode", "")).lower() == "o_award":
        fs_dec = decisions.get("figure_style")
        if not isinstance(fs_dec, dict) or fs_dec.get("status") != "confirmed":
            decisions["figure_style"] = {"value": "morandi_journal", "status": "defaulted", "source": "workflow"}
    data.setdefault("human_requests", [])

    stages = data.setdefault("stages", {})
    for st in STAGE_ORDER:
        if st not in stages:
            stages[st] = {
                "status": "PASS" if st == "S0_setup" else ("READY" if st == "S1_problem_analysis" else "PENDING"),
                "outputs": ["work/run_manifest.yaml"] if st == "S0_setup" else list(STAGE_SPECS[st]["outputs"]),
            }

    artifacts = _discover_artifacts(proj, data.get("artifacts", {}), stages)
    for k, meta in artifacts.items():
        digest, exists = compute_artifact_hash(proj, k)
        if digest:
            meta["sha256"] = digest
        meta["status"] = "current" if exists else "stale"
    data["artifacts"] = artifacts

    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(dump_yaml(data), encoding="utf-8")
    print(f"[OK] 初始化 manifest 完成：{manifest_path}（收录 {len(artifacts)} 项产物指纹）")
    return 0


def cmd_sync(args: argparse.Namespace) -> int:
    manifest_path = Path(args.manifest).resolve()
    if not manifest_path.is_file():
        print(f"[错误] manifest 不存在: {manifest_path}")
        return 2
    proj = _infer_project_root(manifest_path, args.project)
    data = parse_yaml(manifest_path.read_text(encoding="utf-8"))
    stages = data.setdefault("stages", {})
    artifacts = _discover_artifacts(proj, data.get("artifacts", {}), stages)
    data["artifacts"] = artifacts
    edges = _build_dependency_graph(artifacts, stages)

    changed_sources: list[str] = []
    missing_items: list[str] = []
    initialized_hashes = 0

    for k, meta in artifacts.items():
        if not isinstance(meta, dict):
            continue
        old_hash = meta.get("sha256")
        live_hash, exists = compute_artifact_hash(proj, k)
        if not exists:
            if old_hash or meta.get("status") == "current":
                meta["status"] = "stale"
                missing_items.append(k)
            continue
        if not old_hash:
            meta["sha256"] = live_hash
            initialized_hashes += 1
        elif old_hash != live_hash:
            meta["sha256"] = live_hash
            meta["status"] = "current"
            changed_sources.append(k)

    newly_staled = _propagate_stale(changed_sources + missing_items, edges, artifacts)
    affected_stages = _update_stages_from_artifacts(data)

    if not args.dry_run:
        manifest_path.write_text(dump_yaml(data), encoding="utf-8")

    stale_all = [k for k, m in artifacts.items() if isinstance(m, dict) and m.get("status") == "stale"]
    print(
        f"[SYNC{' (DRY-RUN)' if args.dry_run else ''}] 产物总数 {len(artifacts)} | "
        f"新增指纹 {initialized_hashes} | 哈希变更 {len(changed_sources)} | "
        f"缺失 {len(missing_items)} | 当前 stale {len(stale_all)}"
    )
    if changed_sources:
        print("  变更源产物:")
        for k in changed_sources:
            print(f"    * {k}")
    if newly_staled or stale_all:
        print("  stale 下游产物:")
        for k in stale_all:
            print(f"    ! {k}")
    if affected_stages:
        print("  最小重跑计划 (Minimal Rerun Plan):")
        for i, st in enumerate(affected_stages, 1):
            st_stat = stages.get(st, {}).get("status", "?")
            print(f"    {i}. {st} [{st_stat}] -> {STAGE_SPECS[st]['cmd']}")

    if args.fail_on_stale and stale_all:
        return 1
    return 0


def cmd_mark_current(args: argparse.Namespace) -> int:
    manifest_path = Path(args.manifest).resolve()
    if not manifest_path.is_file():
        print(f"[错误] manifest 不存在: {manifest_path}")
        return 2
    proj = _infer_project_root(manifest_path, args.project)
    data = parse_yaml(manifest_path.read_text(encoding="utf-8"))
    stages = data.setdefault("stages", {})
    artifacts = _discover_artifacts(proj, data.get("artifacts", {}), stages)
    data["artifacts"] = artifacts
    edges = _build_dependency_graph(artifacts, stages)

    targets: list[str] = []
    if args.stage:
        if args.stage not in STAGE_SPECS:
            print(f"[错误] 未知阶段名: {args.stage}")
            return 2
        st_info = stages.setdefault(args.stage, {"status": "PASS", "outputs": list(STAGE_SPECS[args.stage]["outputs"])})
        st_info["status"] = "PASS"
        st_info["gate"] = "PASS"
        owned = set(st_info.get("outputs") or []) | set(STAGE_SPECS[args.stage]["outputs"])
        for k, meta in artifacts.items():
            if k in owned or (isinstance(meta, dict) and meta.get("producer") == args.stage):
                targets.append(k)
    for art in args.artifact or []:
        n = norm_rel(art)
        if n not in artifacts:
            artifacts[n] = {
                "kind": _infer_kind(n, _infer_producer(n)),
                "producer": _infer_producer(n),
                "depends_on": [],
                "status": "current",
            }
        targets.append(n)

    use_all = bool(getattr(args, "all", False))
    if not use_all and not args.stage and not args.artifact:
        print("[错误] 请至少指定 --stage、--artifact 或 --all")
        return 2

    if use_all:
        targets = []
        for st_name in STAGE_ORDER:
            st_info = stages.get(st_name)
            if isinstance(st_info, dict) and st_info.get("status") in ("N/A", "WAIVED"):
                continue
            spec = STAGE_SPECS[st_name]
            owned = set((st_info or {}).get("outputs") or []) | set(spec["outputs"])
            stage_arts = [
                k for k, meta in artifacts.items()
                if k in owned or (isinstance(meta, dict) and meta.get("producer") == st_name)
            ]
            has_any = any((proj / k.rstrip("/")).exists() for k in stage_arts)
            if has_any:
                st_entry = stages.setdefault(st_name, {"status": "PASS", "outputs": list(spec["outputs"])})
                st_entry["status"] = "PASS"
                if st_name != "S0_setup":
                    st_entry["gate"] = "PASS"
            targets.extend(stage_arts)

        refreshed = 0
        for k in dict.fromkeys(targets):
            live_hash, exists = compute_artifact_hash(proj, k)
            if not exists:
                continue
            artifacts[k]["sha256"] = live_hash
            artifacts[k]["status"] = "current"
            refreshed += 1
        _update_stages_from_artifacts(data)
        manifest_path.write_text(dump_yaml(data), encoding="utf-8")
        print(f"[OK] --all 拓扑一键刷新 {refreshed} 项现有产物为 current")
        return 0

    if args.stage and not targets:
        _update_stages_from_artifacts(data)
        manifest_path.write_text(dump_yaml(data), encoding="utf-8")
        print(f"[OK] 阶段 `{args.stage}` 已置 PASS（当前磁盘无可登记产物指纹）")
        return 0

    rehashed_changed: list[str] = []
    for k in dict.fromkeys(targets):
        live_hash, exists = compute_artifact_hash(proj, k)
        if not exists:
            print(f"[警告] 产物尚未存在于磁盘: {k}（无法标记为 current）")
            continue
        meta = artifacts[k]
        old_hash = meta.get("sha256")
        meta["sha256"] = live_hash
        meta["status"] = "current"
        if old_hash and old_hash != live_hash:
            rehashed_changed.append(k)

    # 若重刷阶段产物的同时新哈希变了，则其更下游产物（排除本批刚刚刷新的 targets）须标 stale
    downstream_staled = _propagate_stale(rehashed_changed, edges, artifacts)
    if args.stage:
        # 不让同阶段刚 mark-current 的目标反向被标脏（例如同时包含 main.tex 和 paper.pdf）
        for k in targets:
            if (proj / k.rstrip("/")).exists():
                artifacts[k]["status"] = "current"
    _update_stages_from_artifacts(data)
    manifest_path.write_text(dump_yaml(data), encoding="utf-8")
    print(f"[OK] 已刷新 {len(targets)} 项为 current" + (f"，下游标脏 {len(downstream_staled)} 项" if downstream_staled else ""))
    return 0


def cmd_invalidate(args: argparse.Namespace) -> int:
    manifest_path = Path(args.manifest).resolve()
    if not manifest_path.is_file():
        print(f"[错误] manifest 不存在: {manifest_path}")
        return 2
    data = parse_yaml(manifest_path.read_text(encoding="utf-8"))
    stages = data.setdefault("stages", {})
    artifacts = data.setdefault("artifacts", {})
    art_key = norm_rel(args.artifact)
    if art_key not in artifacts:
        print(f"[错误] artifacts 中不存在该产物路径: {art_key}")
        return 2
    edges = _build_dependency_graph(artifacts, stages)
    staled = _propagate_stale([art_key], edges, artifacts)
    affected_stages = _update_stages_from_artifacts(data)
    manifest_path.write_text(dump_yaml(data), encoding="utf-8")
    reason = f"（原因：{args.reason}）" if args.reason else ""
    print(f"[OK] 自 `{art_key}` 向下游传播 stale{reason}：标脏 {len(staled)} 个产物，受影响阶段 {affected_stages}")
    return 0


def cmd_approve(args: argparse.Namespace) -> int:
    manifest_path = Path(args.manifest).resolve()
    if not manifest_path.is_file():
        print(f"[错误] manifest 不存在: {manifest_path}")
        return 2
    data = parse_yaml(manifest_path.read_text(encoding="utf-8"))
    approvals = data.setdefault("approvals", [])
    if not isinstance(approvals, list):
        approvals = []
        data["approvals"] = approvals

    found = None
    for item in approvals:
        if isinstance(item, dict) and item.get("id") == args.id:
            found = item
            break
    if found is None:
        found = {"id": args.id, "stage": args.stage or "workflow", "class": "BLOCKING", "status": args.status}
        approvals.append(found)
    else:
        found["status"] = args.status
        if args.stage:
            found["stage"] = args.stage
    if args.note:
        found["summary"] = args.note

    manifest_path.write_text(dump_yaml(data), encoding="utf-8")
    print(f"[OK] 人工确认条目 `{args.id}` 状态已更新为 `{args.status}`")
    return 0


def cmd_request(args: argparse.Namespace) -> int:
    manifest_path = Path(args.manifest).resolve()
    if not manifest_path.is_file():
        print(f"[错误] manifest 不存在: {manifest_path}")
        return 2
    if args.stage not in STAGE_SPECS:
        print(f"[错误] 未知阶段名: {args.stage}")
        return 2
    data = parse_yaml(manifest_path.read_text(encoding="utf-8"))
    stages = data.setdefault("stages", {})
    requests = data.setdefault("human_requests", [])
    if not isinstance(requests, list):
        requests = []
        data["human_requests"] = requests

    entry = None
    for item in requests:
        if isinstance(item, dict) and item.get("id") == args.id:
            entry = item
            break
    if entry is None:
        entry = {"id": args.id, "stage": args.stage, "kind": args.kind, "status": args.status}
        requests.append(entry)
    else:
        entry["stage"] = args.stage
        entry["status"] = args.status
        if args.kind:
            entry["kind"] = args.kind
    if args.ticket:
        entry["ticket"] = norm_rel(args.ticket)
    if args.expected_output:
        entry["expected_output"] = norm_rel(args.expected_output)
    if args.fallback:
        entry["fallback"] = args.fallback
    if args.summary:
        entry["summary"] = args.summary

    st_info = stages.setdefault(
        args.stage, {"status": "READY", "outputs": list(STAGE_SPECS[args.stage]["outputs"])}
    )
    if args.status == "pending":
        st_info["status"] = "WAITING_HUMAN"
    elif st_info.get("status") == "WAITING_HUMAN":
        other_pending = any(
            isinstance(r, dict) and r.get("stage") == args.stage and r.get("status") == "pending"
            for r in requests
        )
        if not other_pending:
            st_info["status"] = "READY"

    manifest_path.write_text(dump_yaml(data), encoding="utf-8")
    print(
        f"[OK] 人工协助工单 `{args.id}` ({args.stage}, kind={entry.get('kind')}) "
        f"-> status={args.status}, 阶段状态={st_info.get('status')}"
    )
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    manifest_path = Path(args.manifest).resolve()
    if not manifest_path.is_file():
        print(f"[错误] manifest 不存在: {manifest_path}")
        return 2
    proj = _infer_project_root(manifest_path, args.project)
    data = parse_yaml(manifest_path.read_text(encoding="utf-8"))
    stages = data.get("stages") or {}
    artifacts = data.get("artifacts") or {}
    approvals = data.get("approvals") or []
    human_requests = data.get("human_requests") or []

    drifted: list[str] = []
    missing: list[str] = []
    stale_list: list[str] = []
    unhashed: list[str] = []

    for k, meta in artifacts.items():
        if not isinstance(meta, dict):
            continue
        status = meta.get("status", "current")
        if status == "stale":
            stale_list.append(k)
        stored_hash = meta.get("sha256")
        live_hash, exists = compute_artifact_hash(proj, k)
        if not exists:
            missing.append(k)
        elif not stored_hash:
            unhashed.append(k)
        elif stored_hash != live_hash:
            drifted.append(k)

    pending_blocking = [
        a for a in approvals
        if isinstance(a, dict) and str(a.get("class", "")).upper() == "BLOCKING" and a.get("status") == "pending"
    ]
    pending_human_requests = [
        r for r in human_requests
        if isinstance(r, dict) and r.get("status") == "pending"
    ]
    waiting_human_stages = [
        st for st, info in stages.items()
        if isinstance(info, dict) and info.get("status") == "WAITING_HUMAN"
    ]
    failed_or_blocked_stages = [
        st for st, info in stages.items()
        if isinstance(info, dict) and info.get("status") in ("FAIL", "BLOCKED")
    ]
    bad_stage_enums = [
        (st, info.get("status"))
        for st, info in stages.items()
        if isinstance(info, dict) and info.get("status") not in STAGE_STATES
    ]

    strict_fail = bool(
        stale_list
        or drifted
        or missing
        or pending_blocking
        or pending_human_requests
        or waiting_human_stages
        or failed_or_blocked_stages
        or bad_stage_enums
    )
    payload = {
        "manifest": str(manifest_path),
        "project_root": str(proj),
        "project": data.get("project", {}),
        "stages": {st: (stages[st].get("status") if isinstance(stages.get(st), dict) else None) for st in STAGE_ORDER if st in stages},
        "pending_blocking_approvals": pending_blocking,
        "pending_human_requests": pending_human_requests,
        "waiting_human_stages": waiting_human_stages,
        "stale_artifacts": stale_list,
        "drifted_artifacts": drifted,
        "missing_artifacts": missing,
        "unhashed_artifacts": unhashed,
        "failed_or_blocked_stages": failed_or_blocked_stages,
        "strict_ok": not strict_fail,
    }

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        pinfo = data.get("project", {})
        print(f"Manifest: {manifest_path} (competition={pinfo.get('competition')}, mode={pinfo.get('mode')}, lang={pinfo.get('language')})")
        print(
            f"阶段数: {len(stages)} | 跟踪产物: {len(artifacts)} | stale: {len(stale_list)} | "
            f"live 哈希漂移: {len(drifted)} | 未哈希: {len(unhashed)} | 缺失: {len(missing)} | "
            f"待人工协作工单: {len(pending_human_requests)}"
        )
        if pending_blocking:
            print("待确认 BLOCKING 审批:")
            for a in pending_blocking:
                print(f"  - [{a.get('stage')}] {a.get('id')}: {a.get('status')} — {a.get('summary', '')}")
        if pending_human_requests:
            print("待交付/降级人工协作工单 (WAITING_HUMAN):")
            for r in pending_human_requests:
                print(
                    f"  - [{r.get('stage')}] {r.get('id')} ({r.get('kind')}): "
                    f"ticket={r.get('ticket', '')} | out={r.get('expected_output', '')}"
                )
        if drifted:
            print(f"检测到磁盘哈希漂移（建议运行 sync 传播失效）: {drifted}")
        if stale_list:
            print(f"当前 stale 产物: {stale_list}")
        if missing:
            print(f"缺失产物: {missing}")

    if args.strict and strict_fail:
        return 1
    return 0


def self_test() -> int:
    # 1. Round-trip parse official template
    if TEMPLATE_MANIFEST.is_file():
        tpl_data = parse_yaml(TEMPLATE_MANIFEST.read_text(encoding="utf-8"))
        assert tpl_data["schema"] == 1
        assert tpl_data["decisions"]["figure_route"]["export"]["value"] == ["png", "svg", "pdf"]
        reparsed = parse_yaml(dump_yaml(tpl_data))
        assert reparsed == tpl_data, "Template round-trip mismatch"

    # 2. Complex MCM-style multi-line approvals + flow artifacts round-trip
    complex_yaml = """schema: 1
project:
  competition: MCM
  problem: "2026 MCM Problem C: Data With The Stars"
  language: en
  time_budget_hours: 72
  mode: competition
decisions:
  template: {value: en/mcm-latex, status: defaulted, source: workflow}
  figure_route:
    export: {value: [png, svg, pdf], status: defaulted, source: workflow}
stages:
  S5_solver:
    status: PASS
    outputs: [work/code/, work/results.json]
artifacts:
  work/results.json: {kind: source, producer: S5_solver, depends_on: [work/code/], status: current}
approvals:
  - id: P1_model_formulation
    stage: S4_model_design
    class: BLOCKING
    status: pending
    summary: "Confirm Q1-Q4 math models"
"""
    d_c = parse_yaml(complex_yaml)
    assert parse_yaml(dump_yaml(d_c)) == d_c

    # 3. Full temp project lifecycle: init -> sync clean -> modify results.json -> sync propagates downstream -> mark-current -> approve -> status --strict
    with tempfile.TemporaryDirectory(prefix="manifest_cli_test_") as td:
        proj = Path(td)
        (proj / "input").mkdir(parents=True)
        (proj / "work" / "code").mkdir(parents=True)
        (proj / "work" / "figures").mkdir(parents=True)
        (proj / "output" / "paper").mkdir(parents=True)
        (proj / "output" / "submission").mkdir(parents=True)

        (proj / "input" / "problem.pdf").write_bytes(b"%PDF-1.4 problem")
        (proj / "work" / "brief.md").write_text("# Brief\n", encoding="utf-8")
        (proj / "work" / "model_doc.md").write_text("# Model\n", encoding="utf-8")
        (proj / "work" / "code" / "solve.py").write_text("print(1)\n", encoding="utf-8")
        (proj / "work" / "results.json").write_text('{"Q1": {"x": 1.0}}', encoding="utf-8")
        (proj / "work" / "validation_report.md").write_text("# Val\n", encoding="utf-8")
        (proj / "work" / "fact_sheet.md").write_text("# Fact\n", encoding="utf-8")
        (proj / "work" / "figures" / "fig1.png").write_bytes(b"PNG1")
        (proj / "output" / "paper" / "sections").mkdir(parents=True, exist_ok=True)
        (proj / "output" / "paper" / "paper.pdf").write_bytes(b"%PDF-1.4 v1")
        (proj / "output" / "paper" / "sections" / "B_ai_report.tex").write_text("AI report", encoding="utf-8")
        (proj / "output" / "submission" / "MD5.txt").write_text("abc", encoding="utf-8")

        mp = proj / "work" / "run_manifest.yaml"
        assert cmd_init(argparse.Namespace(project=str(proj), manifest=str(mp), competition="MCM", language="en", mode="competition", time_budget=72, force=True)) == 0

        # Mark all discovered stages PASS for lifecycle check
        data = parse_yaml(mp.read_text(encoding="utf-8"))
        for st in STAGE_ORDER:
            if st in data["stages"]:
                data["stages"][st]["status"] = "PASS"
        data["approvals"] = [{"id": "P1_model_formulation", "stage": "S4_model_design", "class": "BLOCKING", "status": "confirmed"}]
        mp.write_text(dump_yaml(data), encoding="utf-8")

        # Strict status clean -> 0
        assert cmd_status(argparse.Namespace(manifest=str(mp), project=str(proj), strict=True, json=False)) == 0

        # Edit work/results.json -> sync must invalidate S6..S10 ONLY, keeping input/ & brief.md current
        (proj / "work" / "results.json").write_text('{"Q1": {"x": 2.0}}', encoding="utf-8")
        rc_sync = cmd_sync(argparse.Namespace(manifest=str(mp), project=str(proj), dry_run=False, fail_on_stale=True))
        assert rc_sync == 1, "Changed upstream results.json must yield downstream stale (exit 1 with --fail-on-stale)"

        d_after = parse_yaml(mp.read_text(encoding="utf-8"))
        arts = d_after["artifacts"]
        assert arts["input/problem.pdf"]["status"] == "current"
        assert arts["work/brief.md"]["status"] == "current"
        assert arts["work/results.json"]["status"] == "current"
        assert arts["work/validation_report.md"]["status"] == "stale"
        assert arts["work/figures/"]["status"] == "stale"
        assert arts["output/paper/paper.pdf"]["status"] == "stale"
        assert arts["output/submission/"]["status"] == "stale"
        assert d_after["stages"]["S6_validation"]["status"] == "READY"
        assert d_after["stages"]["S7_figures"]["status"] == "PENDING"
        assert d_after["stages"]["S1_problem_analysis"]["status"] == "PASS"

        # Refresh remaining stages cleanly -> strict status returns 0 again
        for st in ("S6_validation", "S7_figures", "S8_paper_writing", "S9_humanize", "S10_review_deliver"):
            assert cmd_mark_current(argparse.Namespace(manifest=str(mp), project=str(proj), stage=st, artifact=[])) == 0
        assert cmd_status(argparse.Namespace(manifest=str(mp), project=str(proj), strict=True, json=False)) == 0

        # Pending BLOCKING approval fails --strict
        assert cmd_approve(argparse.Namespace(manifest=str(mp), id="P1_model_formulation", status="pending", stage=None, note=None)) == 0
        assert cmd_status(argparse.Namespace(manifest=str(mp), project=str(proj), strict=True, json=False)) == 1
        assert cmd_approve(argparse.Namespace(manifest=str(mp), id="P1_model_formulation", status="confirmed", stage=None, note=None)) == 0
        assert cmd_status(argparse.Namespace(manifest=str(mp), project=str(proj), strict=True, json=False)) == 0

        # Manual invalidate propagates downstream without deleting files or dirtying upstream results.json
        assert cmd_invalidate(argparse.Namespace(manifest=str(mp), artifact="work/figures/", reason="replot fig1")) == 0
        d_inv = parse_yaml(mp.read_text(encoding="utf-8"))
        assert d_inv["artifacts"]["work/results.json"]["status"] == "current"
        assert d_inv["artifacts"]["output/paper/paper.pdf"]["status"] == "stale"
        assert cmd_status(argparse.Namespace(manifest=str(mp), project=str(proj), strict=True, json=False)) == 1

    # 4. v4.2 o_award mode auto-defaults morandi_journal & WAITING_HUMAN request lifecycle
    with tempfile.TemporaryDirectory(prefix="manifest_o_award_test_") as td2:
        proj2 = Path(td2)
        (proj2 / "work").mkdir(parents=True)
        mp2 = proj2 / "work" / "run_manifest.yaml"
        assert (
            cmd_init(
                argparse.Namespace(
                    project=str(proj2),
                    manifest=str(mp2),
                    competition="MCM",
                    language="en",
                    mode="o_award",
                    time_budget=96,
                    force=True,
                )
            )
            == 0
        )
        d_oa = parse_yaml(mp2.read_text(encoding="utf-8"))
        assert d_oa["project"]["mode"] == "o_award"
        assert d_oa["decisions"]["figure_style"]["value"] == "morandi_journal", d_oa["decisions"]
        for st in STAGE_ORDER:
            d_oa["stages"][st]["status"] = "PASS"
        mp2.write_text(dump_yaml(d_oa), encoding="utf-8")

        assert (
            cmd_request(
                argparse.Namespace(
                    manifest=str(mp2),
                    id="req_01",
                    stage="S7_figures",
                    kind="visual_asset",
                    status="pending",
                    ticket="work/human_requests/req_01.md",
                    expected_output="work/figures/assets/battery_cutout.png",
                    fallback="Use pure HTML/SVG schematic without raster cutout",
                    summary="Nano Banana 3D cutout battery component",
                )
            )
            == 0
        )
        d_wait = parse_yaml(mp2.read_text(encoding="utf-8"))
        assert d_wait["stages"]["S7_figures"]["status"] == "WAITING_HUMAN"
        assert cmd_status(argparse.Namespace(manifest=str(mp2), project=str(proj2), strict=True, json=False)) == 1

        assert (
            cmd_request(
                argparse.Namespace(
                    manifest=str(mp2),
                    id="req_01",
                    stage="S7_figures",
                    kind="visual_asset",
                    status="fallback",
                    ticket="",
                    expected_output="",
                    fallback="",
                    summary="Switched to pure SVG schematic fallback",
                )
            )
            == 0
        )
        d_res = parse_yaml(mp2.read_text(encoding="utf-8"))
        assert d_res["stages"]["S7_figures"]["status"] == "READY"
        assert cmd_mark_current(argparse.Namespace(manifest=str(mp2), project=str(proj2), stage="S7_figures", artifact=[])) == 0
        assert cmd_status(argparse.Namespace(manifest=str(mp2), project=str(proj2), strict=True, json=False)) == 0

        # mark-current --all refreshes multiple drifted stages atomically without churn
        (proj2 / "work" / "brief.md").write_text("# Brief v2\n", encoding="utf-8")
        (proj2 / "output").mkdir(parents=True, exist_ok=True)
        (proj2 / "output" / "code_appendix.pdf").write_bytes(b"%PDF-1.4\n%%EOF\n")
        assert cmd_mark_current(argparse.Namespace(manifest=str(mp2), project=str(proj2), stage="", artifact=[], all=True)) == 0
        assert cmd_status(argparse.Namespace(manifest=str(mp2), project=str(proj2), strict=True, json=False)) == 0

    print("[SELF-TEST] PASS 4/4 (including mark-current --all)")
    return 0


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="run_manifest.yaml 状态机与 SHA-256 DAG 失效传播工具")
    ap.add_argument("--self-test", action="store_true", help="运行内置自检")
    sub = ap.add_subparsers(dest="subcmd")

    p_init = sub.add_parser("init", help="从模板初始化 run_manifest.yaml 并记录初始产物指纹")
    p_init.add_argument("--project", default=".", help="项目根目录")
    p_init.add_argument("--manifest", default="work/run_manifest.yaml")
    p_init.add_argument("--competition", default="")
    p_init.add_argument("--language", default="")
    p_init.add_argument("--mode", default="", choices=("", "competition", "o_award", "high_assurance", "testbed"))
    p_init.add_argument("--time-budget", type=int, default=None)
    p_init.add_argument("--force", action="store_true")

    p_sync = sub.add_parser("sync", help="重算 SHA-256 指纹，向传递下游传播 stale 并给出最小重跑计划")
    p_sync.add_argument("--manifest", default="work/run_manifest.yaml")
    p_sync.add_argument("--project", default="")
    p_sync.add_argument("--dry-run", action="store_true")
    p_sync.add_argument("--fail-on-stale", action="store_true")

    p_mc = sub.add_parser("mark-current", help="刷新产物哈希并标为 current，将对应阶段置 PASS")
    p_mc.add_argument("--manifest", default="work/run_manifest.yaml")
    p_mc.add_argument("--project", default="")
    p_mc.add_argument("--stage", default="")
    p_mc.add_argument("--artifact", action="append", default=[])
    p_mc.add_argument("--all", action="store_true", help="按拓扑顺序一次性刷新所有已产出阶段的产物为 current")

    p_inv = sub.add_parser("invalidate", help="手动从指定产物向下游传播 stale（不删文件）")
    p_inv.add_argument("--manifest", default="work/run_manifest.yaml")
    p_inv.add_argument("--artifact", required=True)
    p_inv.add_argument("--reason", default="")

    p_app = sub.add_parser("approve", help="更新人工确认条目（confirmed / waived / pending）")
    p_app.add_argument("--manifest", default="work/run_manifest.yaml")
    p_app.add_argument("--id", required=True)
    p_app.add_argument("--status", required=True, choices=("confirmed", "waived", "pending"))
    p_app.add_argument("--stage", default="")
    p_app.add_argument("--note", default="")

    p_req = sub.add_parser("request", help="登记或更新人工协作外包工单（触发 WAITING_HUMAN / 恢复 READY）")
    p_req.add_argument("--manifest", default="work/run_manifest.yaml")
    p_req.add_argument("--id", required=True, help="工单编号，如 req_01")
    p_req.add_argument("--stage", required=True, help="所属阶段，如 S5_solver / S7_figures")
    p_req.add_argument("--kind", default="external_sim", choices=("visual_asset", "external_sim", "manual_data", "decision"))
    p_req.add_argument("--status", default="pending", choices=("pending", "fulfilled", "fallback", "waived"))
    p_req.add_argument("--ticket", default="", help="工单说明书路径，如 work/human_requests/req_01.md")
    p_req.add_argument("--expected-output", default="", help="预期落盘产物路径")
    p_req.add_argument("--fallback", default="", help="用户跳过时的保底降级方案说明")
    p_req.add_argument("--summary", default="", help="一句话协作摘要")

    p_st = sub.add_parser("status", help="只读实时审计状态与哈希漂移")
    p_st.add_argument("--manifest", default="work/run_manifest.yaml")
    p_st.add_argument("--project", default="")
    p_st.add_argument("--strict", action="store_true")
    p_st.add_argument("--json", action="store_true")
    return ap


def main() -> int:
    if "--self-test" in sys.argv:
        return self_test()
    ap = build_parser()
    args = ap.parse_args()
    if not args.subcmd:
        ap.print_help()
        return 2
    dispatch = {
        "init": cmd_init,
        "sync": cmd_sync,
        "mark-current": cmd_mark_current,
        "invalidate": cmd_invalidate,
        "approve": cmd_approve,
        "request": cmd_request,
        "status": cmd_status,
    }
    return dispatch[args.subcmd](args)


if __name__ == "__main__":
    sys.exit(main())
