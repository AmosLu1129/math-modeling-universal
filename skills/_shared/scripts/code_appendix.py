#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成「代码附件」PDF，完整收录建模最终代码（Python/MATLAB 等）。

用法：
    python code_appendix.py --code work/code --out output/code_appendix.pdf \
        --title "数学建模竞赛代码附件" [--engine auto|pandoc|xelatex|typst|reportlab]
    python code_appendix.py --self-test

引擎优先级（auto）：
    1) pandoc + xelatex 可用 → Markdown 转 PDF
    2) xelatex + listings 原生排版 → 目录 + 语法高亮 + 跨平台 CJK 字体（无 pandoc 兜底首选）
    3) typst 原生编译 → 自动动态反引号围栏 + 目录
    4) reportlab 兜底 → Pygments 语法高亮（可选）+ 中文字体处理
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

CODE_EXTENSIONS = {
    ".py", ".m", ".r", ".jl", ".c", ".cpp", ".h", ".hpp",
    ".sh", ".sql", ".java", ".ipynb",
}

LISTINGS_LANG_MAP = {
    ".py": "Python",
    ".m": "Matlab",
    ".r": "R",
    ".c": "C",
    ".cpp": "C++",
    ".h": "C++",
    ".hpp": "C++",
    ".java": "Java",
    ".sql": "SQL",
    ".sh": "bash",
}

TYPST_LANG_MAP = {
    ".py": "python",
    ".m": "matlab",
    ".r": "r",
    ".jl": "julia",
    ".c": "c",
    ".cpp": "cpp",
    ".h": "cpp",
    ".hpp": "cpp",
    ".java": "java",
    ".sql": "sql",
    ".sh": "bash",
    ".ipynb": "python",
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


def _escape_latex(text: str) -> str:
    """Escape LaTeX special characters in a single pass."""
    return re.sub(r"[\\{}$&%#_^~]", lambda m: _LATEX_ESCAPES[m.group(0)], text)


def _escape_typst_markup(text: str) -> str:
    """Escape Typst markup delimiters."""
    return re.sub(r"([\\#*_\[\]$`<>/])", r"\\\1", text)


def _sanitize_source(text: str) -> str:
    """Normalize line endings and strip NUL / non-printable control characters."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", text)


def collect_files(code_dir: Path) -> list[Path]:
    files = sorted(
        p for p in code_dir.rglob("*")
        if p.is_file() and p.suffix.lower() in CODE_EXTENSIONS
    )
    if not files:
        print(f"[警告] {code_dir} 下未找到代码文件。")
    return files


def read_source(path: Path) -> str:
    if path.suffix.lower() == ".ipynb":
        cells = json.loads(path.read_text(encoding="utf-8"))
        parts = []
        for cell in cells.get("cells", []):
            if cell.get("cell_type") == "code":
                parts.append("".join(cell.get("source", [])))
        return "\n".join(parts)
    return path.read_text(encoding="utf-8", errors="ignore")


def first_comment_line(source: str, ext: str) -> str:
    for line in source.splitlines():
        line = line.strip()
        if line.startswith("#") or line.startswith("%") or line.startswith("//"):
            return line.lstrip("#%// ").strip()
    return ""


# ---------------- reportlab 引擎 ----------------

def _register_cjk_font():
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont

    try:
        from reportlab.pdfbase.ttfonts import TTFont

        candidates = [
            "/System/Library/Fonts/PingFang.ttc",
            "/System/Library/Fonts/Supplemental/Songti.ttc",
            "/System/Library/Fonts/Supplemental/STHeiti Medium.ttc",
            "/Library/Fonts/Arial Unicode.ttf",
            "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
            "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
            "C:/Windows/Fonts/msyh.ttc",
            "C:/Windows/Fonts/simhei.ttf",
        ]
        for path in candidates:
            if Path(path).exists():
                try:
                    pdfmetrics.registerFont(TTFont("CJKCode", path, subfontIndex=0))
                    return "CJKCode"
                except Exception:
                    continue
    except ImportError:
        pass

    pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
    return "STSong-Light"


def _pygments_colored(source: str, filename: str) -> str | None:
    try:
        from pygments import lex
        from pygments.lexers import get_lexer_for_filename
        from pygments.token import Token
    except ImportError:
        return None

    colors = {
        Token.Keyword: "#8959A8",
        Token.String: "#718C00",
        Token.Number: "#C18401",
        Token.Comment: "#8E908C",
        Token.Name.Function: "#4271AE",
        Token.Name.Class: "#4271AE",
        Token.Name.Builtin: "#C18401",
        Token.Operator: "#3E999F",
    }

    def esc(text: str) -> str:
        return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    try:
        lexer = get_lexer_for_filename(filename)
    except Exception:
        return None

    out_lines = []
    for line in source.split("\n"):
        spans = []
        for tok, text in lex(line, lexer):
            color = None
            for token_type, hex_color in colors.items():
                if tok in token_type:
                    color = hex_color
                    break
            spans.append(f'<font color="{color}">{esc(text)}</font>' if color else esc(text))
        out_lines.append("".join(spans))
    return "\n".join(out_lines)


def build_with_reportlab(code_dir: Path, out: Path, title: str) -> None:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.platypus import (
        PageBreak,
        Paragraph,
        Preformatted,
        SimpleDocTemplate,
        Spacer,
    )

    cjk_font = _register_cjk_font()
    files = collect_files(code_dir)

    title_style = ParagraphStyle("title", fontName=cjk_font, fontSize=18, leading=24, alignment=1)
    meta_style = ParagraphStyle("meta", fontName=cjk_font, fontSize=10, leading=14, alignment=1)
    file_style = ParagraphStyle("file", fontName=cjk_font, fontSize=13, leading=18, spaceBefore=6)
    desc_style = ParagraphStyle("desc", fontName=cjk_font, fontSize=9.5, leading=13, textColor="#555555")
    code_style = ParagraphStyle(
        "code",
        fontName=cjk_font,
        fontSize=8,
        leading=9.8,
        backColor="#F7F7F7",
        borderPadding=6,
    )

    story = [
        Paragraph(title, title_style),
        Spacer(1, 6),
        Paragraph(
            f"生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}　共 {len(files)} 个代码文件",
            meta_style,
        ),
        Spacer(1, 12),
        Paragraph("文件清单", file_style),
    ]
    for f in files:
        rel = f.relative_to(code_dir).as_posix()
        story.append(Paragraph(f"・ {rel}", desc_style))
    story.append(PageBreak())

    for f in files:
        rel = f.relative_to(code_dir).as_posix()
        source = read_source(f)
        note = first_comment_line(source, f.suffix)
        story.append(Paragraph(f"## {rel}", file_style))
        if note:
            story.append(Paragraph(f"说明：{note}", desc_style))
        story.append(Spacer(1, 4))

        colored = _pygments_colored(source, f.name)
        story.append(Preformatted(colored if colored else source, code_style))
        story.append(PageBreak())

    doc = SimpleDocTemplate(
        str(out),
        pagesize=A4,
        leftMargin=2 * cm,
        rightMargin=2 * cm,
        topMargin=2 * cm,
        bottomMargin=2 * cm,
        title=title,
    )
    doc.build(story)
    print(f"[OK] 已生成代码附件: {out}")


# ---------------- pandoc 引擎 ----------------

def build_with_pandoc(code_dir: Path, out: Path, title: str) -> bool:
    if not (shutil.which("pandoc") and shutil.which("xelatex")):
        return False
    files = collect_files(code_dir)
    if not files:
        return False
    with tempfile.TemporaryDirectory() as tmp:
        md_path = Path(tmp) / "appendix.md"
        lines = [f"# {title}", "", f"共 {len(files)} 个代码文件。", ""]
        for f in files:
            rel = f.relative_to(code_dir).as_posix()
            source = read_source(f)
            lines += [f"## {rel}", "", "```", source, "```", ""]
        md_path.write_text("\n".join(lines), encoding="utf-8")
        cjk_font = (
            "Microsoft YaHei" if sys.platform == "win32"
            else ("PingFang SC" if sys.platform == "darwin" else "Noto Sans CJK SC")
        )
        cmd = [
            "pandoc", str(md_path), "-o", str(out),
            "--pdf-engine=xelatex",
            "-V", f"CJKmainfont={cjk_font}",
            "-V", "geometry:margin=2cm",
            "--highlight-style", "tango",
        ]
        subprocess.run(cmd, check=True)
    print(f"[OK] 已生成代码附件: {out}")
    return True


# ---------------- xelatex + listings 原生引擎 ----------------

def build_with_xelatex(code_dir: Path, out: Path, title: str) -> bool:
    if not shutil.which("xelatex"):
        return False
    files = collect_files(code_dir)
    if not files:
        return False

    cjk_font = (
        "Microsoft YaHei" if sys.platform == "win32"
        else ("PingFang SC" if sys.platform == "darwin" else "Noto Sans CJK SC")
    )
    mono_font = (
        "Consolas" if sys.platform == "win32"
        else ("Menlo" if sys.platform == "darwin" else "DejaVu Sans Mono")
    )
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")

    with tempfile.TemporaryDirectory(prefix="code_app_tex_") as tmp:
        tdir = Path(tmp)
        sec_blocks: list[str] = []
        for idx, f in enumerate(files, 1):
            rel = f.relative_to(code_dir).as_posix()
            source = _sanitize_source(read_source(f))
            src_name = f"src_{idx:03d}.txt"
            (tdir / src_name).write_text(source, encoding="utf-8")

            note = _sanitize_source(first_comment_line(source, f.suffix))
            lang = LISTINGS_LANG_MAP.get(f.suffix.lower(), "")
            opts = [f"language={lang}"] if lang else []
            opts.append("caption=")
            opt_str = ",".join(opts)

            block = [f"\\section{{{_escape_latex(rel)}}}"]
            if note:
                block.append(f"{{\\small\\color{{metagray}}说明：{_escape_latex(note)}}}\\\\[4pt]")
            block.append(f"\\lstinputlisting[{opt_str}]{{{src_name}}}")
            block.append("\\clearpage")
            sec_blocks.append("\n".join(block))

        tex_src = rf"""\documentclass[10pt,a4paper]{{article}}
\usepackage[margin=2cm]{{geometry}}
\usepackage{{fontspec}}
\IfFontExistsTF{{{mono_font}}}{{\setmonofont{{{mono_font}}}}}{{\IfFontExistsTF{{DejaVu Sans Mono}}{{\setmonofont{{DejaVu Sans Mono}}}}{{}}}}
\IfFileExists{{xeCJK.sty}}{{%
  \usepackage{{xeCJK}}
  \IfFontExistsTF{{{cjk_font}}}{{\setCJKmainfont{{{cjk_font}}}\setCJKmonofont{{{cjk_font}}}}}{{}}
}}{{}}
\usepackage[dvipsnames]{{xcolor}}
\usepackage{{listings}}
\usepackage[hidelinks]{{hyperref}}

\definecolor{{codebg}}{{RGB}}{{248,249,250}}
\definecolor{{codeborder}}{{RGB}}{{218,222,226}}
\definecolor{{kwcolor}}{{RGB}}{{0,92,197}}
\definecolor{{strcolor}}{{RGB}}{{3,47,98}}
\definecolor{{cmtcolor}}{{RGB}}{{106,115,125}}
\definecolor{{numcolor}}{{RGB}}{{110,119,129}}
\definecolor{{metagray}}{{RGB}}{{90,98,106}}

\lstset{{
  extendedchars=false,
  columns=flexible,
  keepspaces=true,
  breaklines=true,
  breakatwhitespace=false,
  showstringspaces=false,
  tabsize=4,
  numbers=left,
  numberstyle=\tiny\color{{numcolor}},
  numbersep=7pt,
  basicstyle=\ttfamily\footnotesize,
  keywordstyle=\bfseries\color{{kwcolor}},
  stringstyle=\color{{strcolor}},
  commentstyle=\itshape\color{{cmtcolor}},
  frame=single,
  rulecolor=\color{{codeborder}},
  backgroundcolor=\color{{codebg}},
  xleftmargin=12pt,
  framexleftmargin=8pt
}}

\begin{{document}}
\begin{{center}}
  {{\LARGE\bfseries {_escape_latex(title)}\par}}
  \vspace{{6pt}}
  {{\small\color{{metagray}}生成时间：{now_str}\quad 共 {len(files)} 个代码文件\par}}
\end{{center}}
\vspace{{10pt}}
\tableofcontents
\clearpage

{"".join(sec_blocks)}
\end{{document}}
"""
        tex_path = tdir / "appendix.tex"
        tex_path.write_text(tex_src, encoding="utf-8")

        cmd = ["xelatex", "-interaction=nonstopmode", "-halt-on-error", "appendix.tex"]
        for _run in range(2):
            res = subprocess.run(cmd, cwd=tdir, capture_output=True, text=True, encoding="utf-8", errors="replace")
            if res.returncode != 0:
                log_path = tdir / "appendix.log"
                tail_src = log_path.read_text(encoding="utf-8", errors="replace") if log_path.exists() else (res.stdout + "\n" + res.stderr)
                tail = "\n".join(tail_src.splitlines()[-25:])
                print(f"[警告] xelatex 编译失败（最后 25 行日志）：\n{tail}")
                return False

        pdf_tmp = tdir / "appendix.pdf"
        if not pdf_tmp.exists() or pdf_tmp.read_bytes()[:4] != b"%PDF":
            print("[警告] xelatex 未产出有效 PDF。")
            return False
        shutil.copyfile(pdf_tmp, out)

    print(f"[OK] 已生成代码附件 (xelatex): {out}")
    return True


# ---------------- typst 原生引擎 ----------------

def _render_typst_source(files: list[Path], code_dir: Path, title: str) -> str:
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    parts = [
        '#set page(paper: "a4", margin: 2cm, numbering: "1 / 1")',
        '#set text(font: ("Microsoft YaHei", "PingFang SC", "Noto Sans CJK SC", "Segoe UI"), size: 10pt)',
        '#show raw: set text(font: ("Consolas", "Menlo", "DejaVu Sans Mono", "Microsoft YaHei"), size: 8pt)',
        "",
        f"#align(center)[#text(size: 18pt, weight: \"bold\")[{_escape_typst_markup(title)}]\\ #text(size: 9pt, fill: luma(100))[生成时间：{now_str}  共 {len(files)} 个代码文件]]",
        "#outline(indent: auto)",
        "#pagebreak()",
        "",
    ]
    for f in files:
        rel = f.relative_to(code_dir).as_posix()
        source = _sanitize_source(read_source(f))
        note = _sanitize_source(first_comment_line(source, f.suffix))
        runs = re.findall(r"`+", source)
        fence = "`" * max(3, max((len(r) for r in runs), default=0) + 1)
        lang = TYPST_LANG_MAP.get(f.suffix.lower(), "txt")
        parts.append(f"== {_escape_typst_markup(rel)}")
        if note:
            parts.append(f"#text(size: 9pt, fill: luma(90))[说明：{_escape_typst_markup(note)}]")
        parts.append(f"{fence}{lang}")
        parts.append(source)
        parts.append(fence)
        parts.append("#pagebreak(weak: true)")
        parts.append("")
    return "\n".join(parts)


def build_with_typst(code_dir: Path, out: Path, title: str) -> bool:
    if not shutil.which("typst"):
        return False
    files = collect_files(code_dir)
    if not files:
        return False
    typ_src = _render_typst_source(files, code_dir, title)
    with tempfile.TemporaryDirectory(prefix="code_app_typ_") as tmp:
        tdir = Path(tmp)
        typ_path = tdir / "appendix.typ"
        typ_path.write_text(typ_src, encoding="utf-8")
        res = subprocess.run(
            ["typst", "compile", str(typ_path), str(out.resolve())],
            cwd=tdir,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if res.returncode != 0 or not out.exists() or out.read_bytes()[:4] != b"%PDF":
            print(f"[警告] typst 编译失败：{res.stderr[-500:]}")
            return False
    print(f"[OK] 已生成代码附件 (typst): {out}")
    return True


def self_test() -> int:
    assert _escape_latex(r"\a_{1}$&%#^~") == r"\textbackslash{}a\_\{1\}\$\&\%\#\textasciicircum{}\textasciitilde{}"
    with tempfile.TemporaryDirectory(prefix="code_app_test_") as td:
        tdir = Path(td)
        code_dir = tdir / "code"
        code_dir.mkdir()
        py_src = (
            "# 中文注释：测试 α, ε, → 与特殊结束串\n"
            "def solve(alpha=0.75, eps=1e-4):\n"
            '    marker = "\\end{lstlisting}"\n'
            '    ticks = "```python"\n'
            "    # 映射关系: raw -> norm\n"
            "    return alpha + eps\n"
        )
        m_src = "% MATLAB 求解脚本示例: x -> Ax = b\nA = eye(3); b = [1; 2; 3]; x = A \\ b;\n"
        nb_src = json.dumps({
            "cells": [{"cell_type": "code", "source": ["x = 42\n", "print(x)\n"]}],
        })
        (code_dir / "q1_solver.py").write_text(py_src, encoding="utf-8")
        (code_dir / "q2_matrix.m").write_text(m_src, encoding="utf-8")
        (code_dir / "demo.ipynb").write_text(nb_src, encoding="utf-8")

        assert "print(x)" in read_source(code_dir / "demo.ipynb")
        files = collect_files(code_dir)
        typ_txt = _render_typst_source(files, code_dir, "Self Test Appendix")
        assert "````python" in typ_txt, "Triple backtick inside code must trigger 4-backtick fence"

        if shutil.which("xelatex"):
            out_pdf = tdir / "out.pdf"
            ok = build_with_xelatex(code_dir, out_pdf, "Self Test Code Appendix / 代码附件")
            assert ok and out_pdf.exists() and out_pdf.stat().st_size > 1000
            assert out_pdf.read_bytes()[:4] == b"%PDF"
            if shutil.which("pdftotext"):
                pt = subprocess.run(
                    ["pdftotext", str(out_pdf), "-"],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                )
                assert pt.returncode == 0
                extracted = pt.stdout
                for tok in ("q1_solver.py", "solve(alpha=0.75", "中文注释", "MATLAB", "α", "ε", "→"):
                    assert tok in extracted, f"Missing token {tok!r} in rendered PDF text:\n{extracted[:600]}"
            print("[SELF-TEST] PASS (including live xelatex + listings compilation & glyph check)")
        else:
            print("[SELF-TEST] PASS (helpers verified; xelatex not installed)")
    return 0


def main() -> int:
    if "--self-test" in sys.argv:
        return self_test()

    parser = argparse.ArgumentParser(description="生成代码附件 PDF")
    parser.add_argument("--code", help="最终代码目录（work/code）")
    parser.add_argument("--out", help="输出 PDF 路径")
    parser.add_argument("--title", default="数学建模竞赛代码附件", help="附件标题")
    parser.add_argument(
        "--engine",
        choices=["auto", "pandoc", "xelatex", "typst", "reportlab"],
        default="auto",
        help="排版引擎（默认 auto: pandoc -> xelatex -> typst -> reportlab）",
    )
    parser.add_argument("--self-test", action="store_true", help="运行内置自检")
    args = parser.parse_args()

    if not args.code or not args.out:
        parser.error("必须提供 --code 与 --out（除非使用 --self-test）")

    code_dir = Path(args.code)
    out = Path(args.out)
    if not code_dir.is_dir():
        print(f"[错误] 代码目录不存在: {code_dir}")
        return 2
    out.parent.mkdir(parents=True, exist_ok=True)

    eng = args.engine
    if eng == "auto":
        for runner in (build_with_pandoc, build_with_xelatex, build_with_typst):
            if runner(code_dir, out, args.title):
                return 0
        try:
            build_with_reportlab(code_dir, out, args.title)
            return 0
        except ImportError as exc:
            print(f"[错误] 缺少可用引擎（pandoc/xelatex/typst 均不可用，且缺少 reportlab）：{exc}")
            return 2

    if eng == "pandoc":
        return 0 if build_with_pandoc(code_dir, out, args.title) else 2
    if eng == "xelatex":
        return 0 if build_with_xelatex(code_dir, out, args.title) else 2
    if eng == "typst":
        return 0 if build_with_typst(code_dir, out, args.title) else 2
    try:
        build_with_reportlab(code_dir, out, args.title)
        return 0
    except ImportError as exc:
        print(f"[错误] 缺少依赖 reportlab：{exc}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
