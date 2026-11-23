#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""论文源码与编译产物一体化终审门禁（Paper Pre-Submission QA Gate）。

把分散的终审手工检查合并为一个单命令脚本，覆盖六大项：
  1. SOURCE-HYGIENE   源码卫生：防 Markdown 语法泄漏进 .tex（**粗体** / ## 标题 / 链接 / 单反引号代码）或 LaTeX 残留进 .typ、待补充占位符
  2. COMPILE-LOG      编译日志：双编译/日志核对（^! 错误、未定义引用、Overfull \hbox 阈值、\headheight 警告）
  3. PAGE-LIMIT       竞赛页数：MCM/ICM ≤25p（自动排除文末 Report on Use of AI）、CUMCM ≤20p、华为杯等
  4. SUMMARY-OVERFLOW 摘要页检查：MCM/ICM Summary Sheet 严格占第 1 页不溢出到第 2 页；国赛摘要与关键词在预算页内
  5. FONT-EMBED       字体嵌入：pdffonts 全嵌入核查，严禁 emb=no 或 Type 3 点阵字体
  6. FIGURE-AUDIT     插图引用：检查全部 \includegraphics / #image 文件存在性，并对嵌入的 .pdf 图运行 audit_pdf_text 字号审计

用法：
    python paper_qa.py --paper-dir output/paper --competition mcm
    python paper_qa.py --paper-dir output/paper --compile --clean --competition mcm --out work/paper_qa_report.md
    python paper_qa.py --self-test

退出码：0 = 通过（0 FAIL，可能有 WARN）；1 = 存在 FAIL；2 = 用法或关键输入缺失错误。
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import audit_pdf_text  # noqa: E402

COMPETITION_DEFAULTS: dict[str, tuple[int, int]] = {
    "mcm": (25, 1),
    "icm": (25, 1),
    "cumcm": (20, 2),
    "huaweibei": (40, 2),
    "custom": (0, 0),
}


@dataclass
class CheckResult:
    check_id: str
    level: str  # PASS | WARN | FAIL
    message: str
    details: list[str]


def _read_text(p: Path) -> str:
    return p.read_text(encoding="utf-8", errors="ignore")


def _is_generated_macro_file(raw: str) -> bool:
    head = "\n".join(raw.splitlines()[:10])
    return "GENERATED-BY: export_paper_macros.py" in head


def _preserve_newlines(m: re.Match[str]) -> str:
    return "\n" * m.group(0).count("\n") or " "


def _strip_tex_nonprose(raw: str) -> str:
    """剔除 .tex 注释、代码环境、数学环境（防止 ^{**} 显著性星号误报）、URL、texttt 后再查泄漏。"""
    text = re.sub(
        r"\\begin\{(?:lstlisting|verbatim|Verbatim|minted|comment|equation\*?|align\*?|gather\*?)\}.*?\\end\{(?:lstlisting|verbatim|Verbatim|minted|comment|equation\*?|align\*?|gather\*?)\}",
        _preserve_newlines,
        raw,
        flags=re.S,
    )
    text = re.sub(r"\\lstinline(?:\[[^\]]*\])?(?:(.)(.*?)\1|\{[^}]*\})", _preserve_newlines, text, flags=re.S)
    text = re.sub(r"\\verb\*?(.)(.*?)\1", _preserve_newlines, text, flags=re.S)
    text = re.sub(r"\\(?:url|texttt)\{[^}]*\}", _preserve_newlines, text)
    text = re.sub(r"\\href\{[^}]*\}\{([^}]*)\}", r"\1", text)
    text = re.sub(r"(?<!\\)%[^\n]*", "", text)
    text = re.sub(r"(?<!\\)\$\$[^$]+\$\$", lambda m: " MATH" + ("\n" * m.group(0).count("\n")) + " ", text, flags=re.S)
    text = re.sub(r"(?<!\\)\$[^$\n]+\$", " MATH ", text)
    text = re.sub(r"\\\([^)]*\\\)", lambda m: " MATH" + ("\n" * m.group(0).count("\n")) + " ", text, flags=re.S)
    text = re.sub(r"\\\[[^\]]*\\\]", lambda m: " MATH" + ("\n" * m.group(0).count("\n")) + " ", text, flags=re.S)
    return text


def _strip_typ_nonprose(raw: str) -> str:
    text = re.sub(r"/\*.*?\*/", _preserve_newlines, raw, flags=re.S)
    text = re.sub(r"(?<!:)//[^\n]*", "", text)
    text = re.sub(r"```.*?```", _preserve_newlines, text, flags=re.S)
    return text


def check_source_hygiene(paper_dir: Path, main_name: str | None = None) -> CheckResult:
    """检查源码中的 Markdown/LaTeX 混用泄漏与未清理占位符。"""
    main_ext = Path(main_name).suffix.lower() if main_name else ""
    tex_files = sorted(p for p in paper_dir.rglob("*.tex") if p.is_file())
    typ_files = sorted(p for p in paper_dir.rglob("*.typ") if p.is_file())

    if main_ext == ".typ":
        targets = typ_files
        mode = "typ"
    elif main_ext == ".tex" or tex_files:
        targets = tex_files
        mode = "tex"
    elif typ_files:
        targets = typ_files
        mode = "typ"
    else:
        return CheckResult("SOURCE-HYGIENE", "FAIL", f"{paper_dir} 内未找到 .tex 或 .typ 源文件", [])

    issues: list[str] = []
    placeholder_pat = re.compile(r"\b(?:TODO|TBD|FIXME)\b|待补充|请填写|在此输入")

    for path in targets:
        raw = _read_text(path)
        if _is_generated_macro_file(raw):
            continue
        rel = path.relative_to(paper_dir).as_posix()
        if mode == "tex":
            clean = _strip_tex_nonprose(raw)
            for lno, line in enumerate(clean.splitlines(), 1):
                if re.search(r"(?<!\*)\*\*(?!\s|\*)[^*\n]+?(?<!\s|\*)\*\*(?!\*)", line):
                    issues.append(f"{rel}:{lno}: 检测到裸 Markdown 加粗 **...** -> 应改为 \\textbf{{...}}")
                if re.match(r"^\s*#{1,6}\s+\S", line):
                    issues.append(f"{rel}:{lno}: 检测到 Markdown 标题 #{line.strip()[:40]}")
                if re.search(r"(?<!!)\[[^\]\n]{1,60}\]\(https?://[^)\s]+\)", line):
                    issues.append(f"{rel}:{lno}: 检测到 Markdown 链接 [text](url) -> 应改为 \\href / \\url")
                if "```" in line:
                    issues.append(f"{rel}:{lno}: 检测到 Markdown 代码围栏 ```")
                # 只抓 Markdown 行内代码 `ident_or_file.py`，不误伤 LaTeX 正反引号 ``quote'' 或 `quote'
                m_bt = re.search(r"(?<![`\\])`([A-Za-z0-9_./:-]{2,})`(?!`)", line)
                if m_bt:
                    issues.append(f"{rel}:{lno}: 检测到 Markdown 行内代码 `{m_bt.group(1)}` -> 应改为 \\texttt{{...}}")
                m_ph = placeholder_pat.search(line)
                if m_ph:
                    issues.append(f"{rel}:{lno}: 检测到未清理占位符 `{m_ph.group(0)}`")
        else:
            clean = _strip_typ_nonprose(raw)
            for lno, line in enumerate(clean.splitlines(), 1):
                m_tex = re.search(r"\\(?:textbf|textit|section|subsection|begin|cite|ref|eqref)\s*\{", line)
                if m_tex:
                    issues.append(f"{rel}:{lno}: Typst 源码残留 LaTeX 命令 `{m_tex.group(0)}`")
                m_ph = placeholder_pat.search(line)
                if m_ph:
                    issues.append(f"{rel}:{lno}: 检测到未清理占位符 `{m_ph.group(0)}`")

    if issues:
        return CheckResult(
            "SOURCE-HYGIENE",
            "FAIL",
            f"发现 {len(issues)} 处源码格式泄漏或未清理占位符",
            issues[:30],
        )
    return CheckResult("SOURCE-HYGIENE", "PASS", f"源码卫生通过（核查 {len(targets)} 个文件，0 泄漏/占位）", [])


def audit_compile_log(log_text: str, overfull_pt: float = 10.0, compile_rc: int | None = None) -> CheckResult:
    """解析 LaTeX .log（或编译结果），分级判定 fatal / undefined / Overfull / headheight。"""
    fails: list[str] = []
    warns: list[str] = []

    if compile_rc is not None and compile_rc != 0:
        fails.append(f"编译器返回非零退出码 {compile_rc}")

    for lno, ln in enumerate(log_text.splitlines(), 1):
        s = ln.rstrip()
        if s.startswith("! "):
            fails.append(f"L{lno}: {s}")
        elif "LaTeX Error:" in s:
            fails.append(f"L{lno}: {s.strip()}")
        elif re.search(r"LaTeX Warning:\s*(?:Reference|Citation)\s+.*undefined", s):
            fails.append(f"L{lno}: {s.strip()}")
        elif re.search(r"There were undefined (?:references|citations)", s):
            fails.append(f"L{lno}: {s.strip()}")
        elif "There were multiply-defined labels" in s:
            warns.append(f"L{lno}: {s.strip()}")
        elif "headheight is too small" in s:
            warns.append(f"L{lno}: {s.strip()}")

    overfulls = [float(x) for x in re.findall(r"Overfull \\hbox \(([0-9]+(?:\.[0-9]+)?)pt too wide\)", log_text)]
    max_ov = max(overfulls, default=0.0)
    if overfulls:
        if max_ov > overfull_pt:
            fails.append(
                f"Overfull \\hbox {len(overfulls)} 处超阈值（最大 {max_ov:.2f}pt > {overfull_pt:g}pt）"
            )
        else:
            warns.append(
                f"存在 {len(overfulls)} 处轻微 Overfull \\hbox（最大 {max_ov:.2f}pt <= {overfull_pt:g}pt）"
            )

    if fails:
        return CheckResult(
            "COMPILE-LOG",
            "FAIL",
            f"编译日志发现 {len(fails)} 项阻断问题（含 Overfull/错误/未定义引用）",
            (fails + warns)[:25],
        )
    if warns:
        return CheckResult(
            "COMPILE-LOG",
            "WARN",
            f"编译日志无报错，但有 {len(warns)} 项排版警告",
            warns[:20],
        )
    return CheckResult("COMPILE-LOG", "PASS", "编译日志干净（0 错误、0 未定义引用、0 Overfull \\hbox）", [])


def _extract_pdf_pages_text(pdf_path: Path) -> tuple[int | None, list[str], str]:
    """提取总页数与每页文本列表（优先 pdfinfo + 一次 pdftotext，异常时退回逐页）。"""
    total_pages: int | None = None
    if shutil.which("pdfinfo"):
        pi = subprocess.run(
            ["pdfinfo", str(pdf_path)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if pi.returncode == 0:
            m = re.search(r"^Pages:\s*(\d+)", pi.stdout, re.M)
            if m:
                total_pages = int(m.group(1))

    if total_pages is None:
        raw_bytes = pdf_path.read_bytes()
        counts = [int(x) for x in re.findall(rb"/Type\s*/Pages\b[^<>]*/Count\s+(\d+)", raw_bytes)]
        if counts:
            total_pages = max(counts)
        else:
            leaf_pages = len(re.findall(rb"/Type\s*/Page(?![A-Za-z])", raw_bytes))
            if leaf_pages:
                total_pages = leaf_pages

    pages: list[str] = []
    if shutil.which("pdftotext"):
        pt = subprocess.run(
            ["pdftotext", str(pdf_path), "-"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if pt.returncode == 0:
            chunks = pt.stdout.split("\x0c")
            if chunks and not chunks[-1].strip():
                chunks = chunks[:-1]
            if total_pages is None or len(chunks) == total_pages:
                pages = chunks
                total_pages = len(chunks)
            elif total_pages:
                for pno in range(1, total_pages + 1):
                    one = subprocess.run(
                        ["pdftotext", "-f", str(pno), "-l", str(pno), str(pdf_path), "-"],
                        capture_output=True,
                        text=True,
                        encoding="utf-8",
                        errors="replace",
                    )
                    pages.append(one.stdout if one.returncode == 0 else "")
        return total_pages, pages, "pdftotext"

    return total_pages, pages, "missing_pdftotext"


def check_page_limit(
    total_pages: int | None,
    pages_text: list[str],
    competition: str,
    max_pages: int,
) -> CheckResult:
    if max_pages <= 0:
        return CheckResult("PAGE-LIMIT", "PASS", f"总页数 {total_pages or '?'}（custom 模式不限页数）", [])
    if total_pages is None:
        return CheckResult("PAGE-LIMIT", "WARN", "无法获取 PDF 总页数（缺少 pdfinfo/pdftotext）", [])

    comp = competition.lower()
    excluded = 0
    note = ""
    if comp in ("mcm", "icm") and pages_text:
        ai_start: int | None = None
        for idx in range(2, len(pages_text)):  # Page 3+
            top_lines = "\n".join([ln.strip() for ln in pages_text[idx].splitlines() if ln.strip()][:12])
            if re.search(
                r"(?im)^\s*(?:Appendix\s+[A-Z0-9]+\s*[:：.\-]?\s*)?(?:Report\s+on\s+Use\s+of\s+AI|AI\s+Use\s+Report)\b",
                top_lines,
            ):
                ai_start = idx + 1
                break
        if ai_start is not None:
            excluded = total_pages - ai_start + 1
            note = f"，已自动排除第 {ai_start}–{total_pages} 页 Report on Use of AI（{excluded} 页）"
    elif comp == "cumcm" and pages_text:
        appx_start: int | None = None
        for idx in range(3, len(pages_text)):  # Page 4+
            top_lines = "\n".join([ln.strip() for ln in pages_text[idx].splitlines() if ln.strip()][:10])
            if re.search(r"^\s*(?:附录\s*[A-Z0-9一二三四]?|AI\s*使用情况说明)", top_lines):
                appx_start = idx + 1
                break
        if appx_start is not None:
            excluded = total_pages - appx_start + 1
            note = f"，已排除第 {appx_start}–{total_pages} 页附录/AI说明（{excluded} 页）"

    counted = total_pages - excluded
    if counted > max_pages:
        return CheckResult(
            "PAGE-LIMIT",
            "FAIL",
            f"计分页数超限：{counted} 页 > 上限 {max_pages} 页（PDF 总 {total_pages} 页{note}）",
            [],
        )
    return CheckResult(
        "PAGE-LIMIT",
        "PASS",
        f"页数合规：{counted} 页 <= 上限 {max_pages} 页（PDF 总 {total_pages} 页{note}）",
        [],
    )


def check_summary_overflow(
    pages_text: list[str],
    competition: str,
    summary_max_pages: int,
) -> CheckResult:
    if summary_max_pages <= 0:
        return CheckResult("SUMMARY-OVERFLOW", "PASS", "custom 模式跳过摘要页溢出检查", [])
    if not pages_text:
        return CheckResult("SUMMARY-OVERFLOW", "WARN", "缺少 pdftotext 页面文本，跳过摘要溢出检查", [])

    comp = competition.lower()
    if comp in ("mcm", "icm") and summary_max_pages == 1:
        p1 = pages_text[0] if len(pages_text) >= 1 else ""
        p2 = pages_text[1] if len(pages_text) >= 2 else ""
        p1_clean = [ln.strip() for ln in p1.splitlines() if ln.strip()]
        p2_clean = [ln.strip() for ln in p2.splitlines() if ln.strip()]

        issues: list[str] = []
        if not re.search(r"\bSummary\b", p1, re.I):
            issues.append("第 1 页未检测到 Summary 标题")
        if any(re.match(r"^Keywords?\s*[:：]", ln, re.I) for ln in p2_clean):
            issues.append("第 2 页出现 `Keywords:` —— Summary Sheet 疑似溢出到第 2 页")

        # 去掉第 2 页可能出现的页眉（Team #xxxx / Page 2）后核对首行
        p2_body = [
            ln for ln in p2_clean
            if not re.match(r"^(?:Team\s*#?\d+|Page\s+\d+|\d+)$", ln, re.I)
        ]
        p2_head = p2_body[0] if p2_body else ""
        has_kw_p1 = any(re.match(r"^Keywords?\s*[:：]", ln, re.I) for ln in p1_clean)
        ok_p2_start = bool(
            re.match(r"^(?:Contents|Table\s+of\s+Contents|1(?:\.0)?\s+\S|Introduction\b|Section\s+1\b)", p2_head, re.I)
        )
        if not has_kw_p1 and not ok_p2_start:
            issues.append(f"第 1 页未见 Keywords 且第 2 页首行为 `{p2_head[:60]}`，疑似 Summary Sheet 跨页")

        if issues:
            return CheckResult("SUMMARY-OVERFLOW", "FAIL", "MCM/ICM Summary Sheet 疑似未严格收束在第 1 页", issues)
        return CheckResult("SUMMARY-OVERFLOW", "PASS", f"Summary Sheet 严格收束于第 1 页（第 2 页起始：`{p2_head[:40]}`）", [])

    # CUMCM / 华为杯等摘要 ≤ summary_max_pages
    front_text = "\n".join(pages_text[:summary_max_pages])
    next_page = pages_text[summary_max_pages] if len(pages_text) > summary_max_pages else ""
    next_clean = [ln.strip() for ln in next_page.splitlines() if ln.strip()]
    issues = []
    if "摘要" not in (pages_text[0] if pages_text else ""):
        issues.append("第 1 页未检测到「摘要」")
    if "关键词" not in front_text and "Key words" not in front_text and "Keywords" not in front_text:
        issues.append(f"前 {summary_max_pages} 页未检测到「关键词」")
    if any(re.match(r"^(?:关键词|Keywords?)\s*[:：]", ln, re.I) for ln in next_clean):
        issues.append(f"第 {summary_max_pages + 1} 页出现关键词行，摘要疑似超页")
    if issues:
        return CheckResult("SUMMARY-OVERFLOW", "FAIL", f"摘要未严格收束在前 {summary_max_pages} 页", issues)
    return CheckResult("SUMMARY-OVERFLOW", "PASS", f"摘要与关键词位于前 {summary_max_pages} 页内", [])


def parse_pdffonts_output(stdout: str) -> list[dict[str, str]]:
    """从右向左锚定 emb sub uni obj gen 5 列，稳健解析多词字体类型（CID TrueType / Type 1C）。"""
    rows: list[dict[str, str]] = []
    row_re = re.compile(
        r"^(?P<head>.*?)\s+(?P<emb>yes|no)\s+(?P<sub>yes|no)\s+(?P<uni>yes|no)\s+(?P<obj>\d+)\s+(?P<gen>\d+)\s*$"
    )
    for ln in stdout.splitlines():
        s = ln.rstrip()
        if not s or s.startswith("name ") or s.startswith("----"):
            continue
        m = row_re.match(s)
        if not m:
            continue
        head = m.group("head").strip()
        # encoding 是无空格末段（如 Identity-H / Builtin / Custom / WinAnsi），name 是首段，中间是 type
        hm = re.match(r"^(\S+)\s+(.+?)\s+(\S+)$", head)
        if hm:
            fname, ftype, fenc = hm.group(1), hm.group(2).strip(), hm.group(3)
        else:
            parts = head.split(None, 1)
            fname, ftype, fenc = parts[0], (parts[1] if len(parts) > 1 else ""), ""
        rows.append({
            "name": fname,
            "type": ftype,
            "encoding": fenc,
            "emb": m.group("emb"),
            "sub": m.group("sub"),
            "uni": m.group("uni"),
        })
    return rows


def check_font_embed(pdf_path: Path) -> CheckResult:
    if not shutil.which("pdffonts"):
        return CheckResult("FONT-EMBED", "WARN", "未检测到 pdffonts，跳过 PDF 字体嵌入核查", [])
    res = subprocess.run(
        ["pdffonts", str(pdf_path)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if res.returncode != 0:
        return CheckResult("FONT-EMBED", "WARN", f"pdffonts 执行失败（code={res.returncode}）", [res.stderr.strip()])
    rows = parse_pdffonts_output(res.stdout)
    return audit_pdffonts_rows(rows)


def audit_pdffonts_rows(rows: list[dict[str, str]]) -> CheckResult:
    if not rows:
        return CheckResult("FONT-EMBED", "WARN", "pdffonts 未解析出字体表项（纯栅格或空文档）", [])
    bad: list[str] = []
    for r in rows:
        if r["emb"] != "yes":
            bad.append(f"{r['name']} ({r['type']}): emb={r['emb']} 未嵌入")
        if re.search(r"\bType\s*3\b", r["type"], re.I):
            bad.append(f"{r['name']}: 含 Type 3 点阵字体")
    if bad:
        return CheckResult("FONT-EMBED", "FAIL", f"发现 {len(bad)} 项字体嵌入/Type 3 隐患", bad[:20])
    return CheckResult("FONT-EMBED", "PASS", f"全部 {len(rows)} 项字体均已嵌入（0 Type 3 / 0 emb=no）", [])


def _resolve_figure_path(
    ref: str,
    src_file: Path,
    paper_dir: Path,
    graphics_paths: list[str],
    is_typ: bool,
) -> Path | None:
    ref_clean = ref.strip()
    if not ref_clean:
        return None
    candidates: list[Path] = []
    if is_typ:
        if ref_clean.startswith("/"):
            candidates.append(paper_dir / ref_clean.lstrip("/"))
        else:
            candidates.append(src_file.parent / ref_clean)
            candidates.append(paper_dir / ref_clean)
    else:
        candidates.append(paper_dir / ref_clean)
        for gp in graphics_paths:
            candidates.append(paper_dir / gp / ref_clean)
        candidates.append(src_file.parent / ref_clean)

    exts = ("", ".pdf", ".png", ".svg", ".jpg", ".jpeg") if not Path(ref_clean).suffix else ("",)
    for cand in candidates:
        for ext in exts:
            p = Path(str(cand) + ext)
            if p.is_file():
                return p.resolve()
    return None


def check_figures(paper_dir: Path, main_name: str | None = None, min_fig_pt: float = 5.0) -> CheckResult:
    main_ext = Path(main_name).suffix.lower() if main_name else ""
    tex_files = sorted(p for p in paper_dir.rglob("*.tex") if p.is_file())
    typ_files = sorted(p for p in paper_dir.rglob("*.typ") if p.is_file())
    if main_ext == ".typ":
        targets, is_typ = typ_files, True
    elif tex_files:
        targets, is_typ = tex_files, False
    else:
        targets, is_typ = typ_files, True

    graphics_paths: list[str] = []
    if not is_typ:
        for f in targets:
            raw = _read_text(f)
            for gp_blk in re.findall(r"\\graphicspath\s*\{((?:\{[^}]+\}\s*)+)\}", raw):
                graphics_paths.extend(re.findall(r"\{([^}]+)\}", gp_blk))

    refs: list[tuple[Path, str]] = []
    for f in targets:
        raw = _read_text(f)
        if _is_generated_macro_file(raw):
            continue
        clean = _strip_typ_nonprose(raw) if is_typ else re.sub(r"(?<!\\)%[^\n]*", "", raw)
        if is_typ:
            for m in re.finditer(r'#image\(\s*"([^"]+)"', clean):
                refs.append((f, m.group(1)))
        else:
            for m in re.finditer(r"\\includegraphics(?:\[[^\]]*\])?\{([^}]+)\}", clean):
                refs.append((f, m.group(1)))

    if not refs:
        return CheckResult("FIGURE-AUDIT", "PASS", "源码未引用外部插图", [])

    missing: list[str] = []
    fails: list[str] = []
    warns: list[str] = []
    audited_pdfs: set[Path] = set()
    ok_refs = 0

    for src_f, ref in refs:
        resolved = _resolve_figure_path(ref, src_f, paper_dir, graphics_paths, is_typ=is_typ)
        if resolved is None:
            missing.append(f"{src_f.relative_to(paper_dir).as_posix()}: 缺失插图 `{ref}`")
            continue
        ok_refs += 1
        if resolved.suffix.lower() == ".pdf" and resolved not in audited_pdfs:
            audited_pdfs.add(resolved)
            res = audit_pdf_text.audit_pdf(resolved.read_bytes(), minimum_pt=min_fig_pt)
            if res["below_minimum_count"]:
                fails.append(
                    f"{resolved.name}: 含 {res['below_minimum_count']} 处 < {min_fig_pt:g}pt 小字（最小 {res['minimum_found_pt']}pt）"
                )
            elif res.get("scaling_present"):
                warns.append(f"{resolved.name}: 含缩放矩阵（UNVERIFIED），需核对渲染后字号")

    all_fails = missing + fails
    if all_fails:
        return CheckResult(
            "FIGURE-AUDIT",
            "FAIL",
            f"插图审计失败：{len(missing)} 个缺失文件，{len(fails)} 个 PDF 小字不达标",
            (all_fails + warns)[:25],
        )
    if warns:
        return CheckResult(
            "FIGURE-AUDIT",
            "WARN",
            f"{ok_refs} 处插图文件齐备（{len(audited_pdfs)} 张 PDF 已审计），{len(warns)} 张含缩放告警",
            warns,
        )
    return CheckResult(
        "FIGURE-AUDIT",
        "PASS",
        f"全部 {ok_refs} 处插图文件齐备，{len(audited_pdfs)} 张 PDF 插图字号均 ≥ {min_fig_pt:g}pt",
        [],
    )


def detect_competition(paper_dir: Path, pages_text: list[str], explicit: str) -> str:
    if explicit != "auto":
        return explicit.lower()
    manifest = paper_dir.parent.parent / "work" / "run_manifest.yaml"
    if manifest.is_file():
        m = re.search(r"(?m)^\s*competition:\s*[\"']?([A-Za-z0-9_\u4e00-\u9fff-]+)", _read_text(manifest))
        if m:
            val = m.group(1).strip().lower()
            if val in ("mcm", "icm", "cumcm", "huaweibei"):
                return val
            if "国赛" in val:
                return "cumcm"
            if "华为" in val:
                return "huaweibei"
    if pages_text:
        p1 = pages_text[0]
        if re.search(r"\bMCM/ICM\b|Summary\s+Sheet", p1, re.I):
            return "mcm"
        if "摘要" in p1:
            return "cumcm"
    return "mcm"


def resolve_main_and_pdf(paper_dir: Path, main_arg: str, pdf_arg: str) -> tuple[Path | None, Path | None]:
    main_path: Path | None = None
    if main_arg:
        cand = Path(main_arg)
        main_path = cand if cand.is_absolute() else (paper_dir / cand)
    else:
        for name in ("main.tex", "main.typ", "paper.tex", "paper.typ"):
            if (paper_dir / name).is_file():
                main_path = paper_dir / name
                break

    pdf_path: Path | None = None
    if pdf_arg:
        cand = Path(pdf_arg)
        pdf_path = cand if cand.is_absolute() else (paper_dir / cand)
    else:
        candidates = [paper_dir / "paper.pdf"]
        if main_path is not None:
            candidates.append(paper_dir / f"{main_path.stem}.pdf")
        for c in candidates:
            if c.is_file():
                pdf_path = c
                break
        if pdf_path is None:
            pdf_path = candidates[-1]
    return main_path, pdf_path


def run_compile(paper_dir: Path, main_path: Path, clean: bool) -> tuple[int, str]:
    suf = main_path.suffix.lower()
    stem = main_path.stem
    if clean:
        for ext in (".aux", ".log", ".toc", ".out", ".bbl", ".blg"):
            p = paper_dir / f"{stem}{ext}"
            if p.exists():
                p.unlink()
        for aux in paper_dir.glob("sections/*.aux"):
            aux.unlink()

    if suf == ".tex":
        if not shutil.which("xelatex"):
            return 2, "! xelatex not installed"
        cmd = ["xelatex", "-interaction=nonstopmode", "-halt-on-error", main_path.name]
        rc = 0
        for _ in range(2):
            r = subprocess.run(cmd, cwd=paper_dir, capture_output=True, text=True, encoding="utf-8", errors="replace")
            rc = r.returncode
            if rc != 0:
                break
        log_file = paper_dir / f"{stem}.log"
        log_text = _read_text(log_file) if log_file.is_file() else (r.stdout + "\n" + r.stderr)
        return rc, log_text

    if suf == ".typ":
        if not shutil.which("typst"):
            return 2, "! typst not installed"
        out_pdf = paper_dir / f"{stem}.pdf"
        r = subprocess.run(
            ["typst", "compile", main_path.name, out_pdf.name],
            cwd=paper_dir,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        return r.returncode, r.stderr + "\n" + r.stdout

    return 2, f"! Unsupported main source suffix: {suf}"


def run_qa(
    paper_dir: Path,
    main_name: str = "",
    pdf_path_arg: str = "",
    competition: str = "auto",
    max_pages: int | None = None,
    summary_max_pages: int | None = None,
    overfull_pt: float = 10.0,
    min_fig_pt: float = 5.0,
    compile_pdf: bool = False,
    clean: bool = False,
) -> dict[str, Any]:
    main_path, pdf_path = resolve_main_and_pdf(paper_dir, main_name, pdf_path_arg)
    checks: list[CheckResult] = []

    # 1. SOURCE-HYGIENE
    checks.append(check_source_hygiene(paper_dir, main_path.name if main_path else None))

    # 2. COMPILE-LOG
    if compile_pdf:
        if main_path is None or not main_path.is_file():
            checks.append(CheckResult("COMPILE-LOG", "FAIL", "请求了 --compile，但未找到主源文件", []))
        else:
            rc, log_text = run_compile(paper_dir, main_path, clean=clean)
            if main_path.suffix.lower() == ".tex":
                checks.append(audit_compile_log(log_text, overfull_pt=overfull_pt, compile_rc=rc))
            else:
                checks.append(
                    CheckResult(
                        "COMPILE-LOG",
                        "PASS" if rc == 0 else "FAIL",
                        "typst 编译成功" if rc == 0 else f"typst 编译失败 (exit={rc})",
                        [] if rc == 0 else log_text.splitlines()[-15:],
                    )
                )
            compiled_pdf = paper_dir / f"{main_path.stem}.pdf"
            if compiled_pdf.is_file() and (not pdf_path or not pdf_path.exists()):
                pdf_path = compiled_pdf
    else:
        log_file = (paper_dir / f"{main_path.stem}.log") if main_path else (paper_dir / "main.log")
        if log_file.is_file():
            checks.append(audit_compile_log(_read_text(log_file), overfull_pt=overfull_pt, compile_rc=None))
        elif main_path and main_path.suffix.lower() == ".tex":
            checks.append(CheckResult("COMPILE-LOG", "WARN", f"未找到编译日志 {log_file.name}（可加 --compile）", []))
        else:
            checks.append(CheckResult("COMPILE-LOG", "PASS", "非 LaTeX 源码或未提供 .log，跳过日志扫描", []))

    # 3-5. PDF checks
    if pdf_path is None or not pdf_path.is_file():
        checks.append(CheckResult("PAGE-LIMIT", "FAIL", f"未找到输出 PDF: {pdf_path}", []))
        checks.append(CheckResult("SUMMARY-OVERFLOW", "FAIL", f"未找到输出 PDF: {pdf_path}", []))
        checks.append(CheckResult("FONT-EMBED", "FAIL", f"未找到输出 PDF: {pdf_path}", []))
    else:
        total_pages, pages_text, _ = _extract_pdf_pages_text(pdf_path)
        comp = detect_competition(paper_dir, pages_text, competition)
        def_max, def_sum = COMPETITION_DEFAULTS.get(comp, (0, 0))
        eff_max = def_max if max_pages is None else max_pages
        eff_sum = def_sum if summary_max_pages is None else summary_max_pages
        checks.append(check_page_limit(total_pages, pages_text, comp, eff_max))
        checks.append(check_summary_overflow(pages_text, comp, eff_sum))
        checks.append(check_font_embed(pdf_path))

    # 6. FIGURE-AUDIT
    checks.append(check_figures(paper_dir, main_path.name if main_path else None, min_fig_pt=min_fig_pt))

    counts = {lvl: sum(1 for c in checks if c.level == lvl) for lvl in ("PASS", "WARN", "FAIL")}
    return {
        "paper_dir": str(paper_dir),
        "main": str(main_path) if main_path else None,
        "pdf": str(pdf_path) if pdf_path else None,
        "counts": counts,
        "ready": counts["FAIL"] == 0,
        "checks": [asdict(c) for c in checks],
    }


def render_markdown(report: dict[str, Any]) -> str:
    c = report["counts"]
    lines = [
        "# 论文终审质量门禁报告 (`paper_qa.py`)",
        "",
        f"- 源码目录：`{report['paper_dir']}`",
        f"- PDF：`{report['pdf']}`",
        f"- 汇总：**{c['PASS']} PASS / {c['WARN']} WARN / {c['FAIL']} FAIL** -> **{'PASS' if report['ready'] else 'FAIL'}**",
        "",
        "| 检查项 | 级别 | 结论 |",
        "|---|---|---|",
    ]
    for item in report["checks"]:
        lines.append(f"| `{item['check_id']}` | **{item['level']}** | {item['message']} |")
    details_sec = [item for item in report["checks"] if item["details"]]
    if details_sec:
        lines += ["", "## 明细"]
        for item in details_sec:
            lines.append(f"\n### {item['check_id']} ({item['level']})")
            for d in item["details"]:
                lines.append(f"- {d}")
    return "\n".join(lines) + "\n"


def self_test() -> int:
    with tempfile.TemporaryDirectory(prefix="paper_qa_test_") as td:
        root = Path(td)

        # 1. SOURCE-HYGIENE: catches **bold**, ## heading, [url](...), `code.py`, TBD; ignores LaTeX ``quotes'' & lstlisting
        hyg_bad = root / "hyg_bad"
        hyg_bad.mkdir()
        (hyg_bad / "main.tex").write_text(
            "% comment with **ignored** and `ignored_code`\n"
            "\\begin{lstlisting}\n**not flagged**\n# not heading\n\\end{lstlisting}\n"
            "We say ``properly quoted'' and `single', and significance ($^*p<0.05$, $^{**}p<0.01$, $^{***}p<0.001$).\n"
            "Bad **markdown $Z_1$ bold** and `leak_var` and TBD.\n"
            "## Leaked Heading\n"
            "See [COMAP](https://www.comap.com) and \\href{https://a.com}{ok}.\n",
            encoding="utf-8",
        )
        r1 = check_source_hygiene(hyg_bad, "main.tex")
        assert r1.level == "FAIL" and len(r1.details) == 5, r1

        (hyg_bad / "main.tex").write_text(
            "Clean LaTeX with ``quotes'', `single', \\texttt{leak_var}, ($^*p<0.05$, $^{**}p<0.01$, $^{***}p<0.001$), and \\textbf{bold}.\n",
            encoding="utf-8",
        )
        assert check_source_hygiene(hyg_bad, "main.tex").level == "PASS"

        # 2. COMPILE-LOG parser
        r_ov_fail = audit_compile_log("Overfull \\hbox (18.5pt too wide) in paragraph\n", overfull_pt=10.0)
        assert r_ov_fail.level == "FAIL", r_ov_fail
        r_ov_warn = audit_compile_log("Overfull \\hbox (4.2pt too wide) in paragraph\n", overfull_pt=10.0)
        assert r_ov_warn.level == "WARN", r_ov_warn
        r_undef = audit_compile_log("LaTeX Warning: Reference `tab:x' on page 3 undefined.\n")
        assert r_undef.level == "FAIL", r_undef
        r_head = audit_compile_log("Package Fancyhdr Warning: \\headheight is too small (12.0pt): make it at least 15.0pt.\n")
        assert r_head.level == "WARN", r_head
        assert audit_compile_log("Output written on main.pdf (2 pages).\n").level == "PASS"

        # 3. pdffonts parser
        sample_fonts = (
            "name                                 type              encoding         emb sub uni object ID\n"
            "------------------------------------ ----------------- ---------------- --- --- --- ---------\n"
            "QVIUWV+TimesNewRomanPS-BoldMT        CID TrueType      Identity-H       yes yes yes      4  0\n"
            "KOOBRH+CMMI10                        Type 1C           Builtin          yes yes yes     12  0\n"
        )
        assert audit_pdffonts_rows(parse_pdffonts_output(sample_fonts)).level == "PASS"
        bad_fonts = sample_fonts + "ABCD+BadFont                         Type 3            Custom           no  no  no      99  0\n"
        assert audit_pdffonts_rows(parse_pdffonts_output(bad_fonts)).level == "FAIL"

        # 4. SUMMARY-OVERFLOW detector
        assert check_summary_overflow(["Summary\n...\nKeywords: A, B", "Contents\n1 Introduction"], "mcm", 1).level == "PASS"
        assert check_summary_overflow(["Summary\n...\nMore text", "Keywords: A, B\nContents"], "mcm", 1).level == "FAIL"

        # 5. PAGE-LIMIT with AI report exclusion
        pages27 = [f"Body p{i}" for i in range(1, 26)] + ["Report on Use of AI\nTool list...", "Section 2..."]
        assert check_page_limit(27, pages27, "mcm", 25).level == "PASS"
        pages28 = [f"Body p{i}" for i in range(1, 27)] + ["Report on Use of AI\nTool list...", "Section 2..."]
        assert check_page_limit(28, pages28, "mcm", 25).level == "FAIL"

        # 6. Live xelatex --compile --clean E2E check when available
        if shutil.which("xelatex"):
            e2e = root / "e2e"
            e2e.mkdir()
            (e2e / "main.tex").write_text(
                r"""\documentclass{article}
\begin{document}
\thispagestyle{empty}
\begin{center}\textbf{2026 MCM/ICM Summary Sheet}\\[0.5em]\textbf{Summary}\end{center}
We model the system quantitatively and present validated improvements.

\noindent\textbf{Keywords:} Optimization; Simulation
\newpage
\tableofcontents
\section{Introduction}
Clean minimal end-to-end test page.
\newpage
\section*{Report on Use of AI}
Used AI tools for proofreading.
\end{document}
""",
                encoding="utf-8",
            )
            rep = run_qa(e2e, main_name="main.tex", competition="mcm", compile_pdf=True, clean=True)
            assert rep["ready"], rep
            print("[SELF-TEST] PASS 6/6 (including live xelatex --compile --clean E2E)")
        else:
            print("[SELF-TEST] PASS 5/5 + unit checks (xelatex not installed)")
    return 0


def main() -> int:
    if "--self-test" in sys.argv:
        return self_test()

    ap = argparse.ArgumentParser(description="论文源码与编译产物一体化终审门禁")
    ap.add_argument("--paper-dir", default="output/paper", help="论文源码目录（默认 output/paper）")
    ap.add_argument("--main", default="", help="主源码文件名（自动探测 main.tex / main.typ）")
    ap.add_argument("--pdf", default="", help="已编译 PDF 路径（默认 paper.pdf 或 <main>.pdf）")
    ap.add_argument("--competition", default="auto", choices=("auto", "mcm", "icm", "cumcm", "huaweibei", "custom"))
    ap.add_argument("--max-pages", type=int, default=None, help="覆盖页数上限（0 表示不限）")
    ap.add_argument("--summary-max-pages", type=int, default=None, help="覆盖摘要最大页数（0 表示跳过）")
    ap.add_argument("--overfull-pt", type=float, default=10.0, help="Overfull \\hbox FAIL 阈值 pt（默认 10.0）")
    ap.add_argument("--min-fig-pt", type=float, default=5.0, help="PDF 插图最小字号阈值 pt（默认 5.0）")
    ap.add_argument("--compile", action="store_true", help="检查前先执行干净双编译（xelatex / typst）")
    ap.add_argument("--clean", action="store_true", help="配合 --compile 清理旧辅助文件后再编译")
    ap.add_argument("--out", default="", help="可选：输出 Markdown 报告路径")
    ap.add_argument("--json", action="store_true", help="输出机器可读 JSON")
    ap.add_argument("--self-test", action="store_true", help="运行内置自检")
    args = ap.parse_args()

    paper_dir = Path(args.paper_dir)
    if not paper_dir.is_dir():
        print(f"[错误] 论文目录不存在: {paper_dir}")
        return 2

    rep = run_qa(
        paper_dir=paper_dir,
        main_name=args.main,
        pdf_path_arg=args.pdf,
        competition=args.competition,
        max_pages=args.max_pages,
        summary_max_pages=args.summary_max_pages,
        overfull_pt=args.overfull_pt,
        min_fig_pt=args.min_fig_pt,
        compile_pdf=args.compile,
        clean=args.clean,
    )

    if args.out:
        out_p = Path(args.out)
        out_p.parent.mkdir(parents=True, exist_ok=True)
        out_p.write_text(render_markdown(rep), encoding="utf-8")

    if args.json:
        print(json.dumps(rep, ensure_ascii=False, indent=2))
    else:
        for c in rep["checks"]:
            print(f"[{c['level']}] {c['check_id']}: {c['message']}")
            for d in c["details"][:8]:
                print(f"    - {d}")
            if len(c["details"]) > 8:
                print(f"    ... 等共 {len(c['details'])} 条")
        cnt = rep["counts"]
        print(f"\n汇总：{cnt['PASS']} PASS / {cnt['WARN']} WARN / {cnt['FAIL']} FAIL")

    return 0 if rep["ready"] else 1


if __name__ == "__main__":
    sys.exit(main())
