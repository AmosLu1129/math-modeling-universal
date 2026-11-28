#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""洁净白名单提交包构建器（Clean-Room Whitelist Submission Packager）。

每次执行先整体清空目标提交目录，仅按白名单复制正式竞赛交付物，彻底杜绝临时截图、
`__pycache__`、`*.pyc` 与历史脏文件混入最终提交包，并自动生成 `README_SUBMISSION.txt`
和全量 `SHA256SUMS.txt` 校验摘要。

用法：
    python pack_submission.py --project .
    python pack_submission.py --project . --out output/submission --dry-run
    python pack_submission.py --self-test
"""

from __future__ import annotations

import argparse
import hashlib
import shutil
import sys
import tempfile
from pathlib import Path

EXCLUDED_DIRS = {
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "scratch",
    "tmp",
    ".git",
    ".ipynb_checkpoints",
}
EXCLUDED_EXTS = {".pyc", ".pyo", ".pyd", ".tmp", ".bak", ".swp"}
EXCLUDED_NAMES = {"Thumbs.db", ".DS_Store", "desktop.ini"}


def _is_clean_relpath(rel_parts: tuple[str, ...]) -> bool:
    for part in rel_parts[:-1]:
        if part in EXCLUDED_DIRS or part.startswith("."):
            return False
    fname = rel_parts[-1]
    if fname in EXCLUDED_NAMES or fname.startswith("._") or fname.startswith("_tmp"):
        return False
    if Path(fname).suffix.lower() in EXCLUDED_EXTS:
        return False
    return True


def _detect_pdf_pages(pdf_path: Path) -> int | None:
    for mod_name in ("pymupdf", "fitz", "pypdf"):
        try:
            mod = __import__(mod_name)
            if mod_name in ("pymupdf", "fitz"):
                with mod.open(str(pdf_path)) as doc:
                    return int(len(doc))
            reader = mod.PdfReader(str(pdf_path))
            return int(len(reader.pages))
        except Exception:
            continue
    return None


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            chunk = f.read(65536)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest().lower()


def _resolve_path(proj: Path, raw: str) -> Path:
    p = Path(raw)
    return p if p.is_absolute() else (proj / p)


def _find_paper_pdf(proj: Path, explicit: str) -> Path | None:
    if explicit:
        cand = _resolve_path(proj, explicit)
        return cand if cand.is_file() else None
    for rel in ("output/paper/paper.pdf", "output/paper/main.pdf", "paper.pdf"):
        cand = proj / rel
        if cand.is_file():
            return cand
    return None


def _collect_clean_tree(src_dir: Path) -> list[tuple[Path, Path]]:
    if not src_dir.is_dir():
        return []
    pairs: list[tuple[Path, Path]] = []
    for p in sorted(src_dir.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(src_dir)
        if _is_clean_relpath(rel.parts):
            pairs.append((p, rel))
    return pairs


def pack_submission(
    project: Path,
    out_raw: str = "output/submission",
    paper_raw: str = "",
    appendix_raw: str = "output/code_appendix.pdf",
    code_raw: str = "work/code",
    data_raw: str = "work/data_clean",
    dry_run: bool = False,
) -> dict[str, object]:
    proj = project.resolve()
    out_dir = _resolve_path(proj, out_raw)
    paper_pdf = _find_paper_pdf(proj, paper_raw)
    if paper_pdf is None:
        raise FileNotFoundError(f"Main submission PDF not found under {proj} (checked output/paper/paper.pdf, main.pdf)")

    appendix_pdf = _resolve_path(proj, appendix_raw) if appendix_raw else None
    has_appendix = bool(appendix_pdf and appendix_pdf.is_file())
    code_files = _collect_clean_tree(_resolve_path(proj, code_raw))
    data_files = _collect_clean_tree(_resolve_path(proj, data_raw))
    page_count = _detect_pdf_pages(paper_pdf)

    planned_rels = ["paper.pdf"]
    if has_appendix:
        planned_rels.append("code_appendix.pdf")
    planned_rels.extend(f"code/{rel.as_posix()}" for _, rel in code_files)
    planned_rels.extend(f"data_clean/{rel.as_posix()}" for _, rel in data_files)
    planned_rels.extend(["README_SUBMISSION.txt", "SHA256SUMS.txt"])

    if dry_run:
        return {
            "out_dir": str(out_dir),
            "page_count": page_count,
            "files": planned_rels,
            "dry_run": True,
        }

    # Clean-room rebuild: wipe existing destination completely before whitelist copy
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    shutil.copy2(paper_pdf, out_dir / "paper.pdf")
    if has_appendix and appendix_pdf is not None:
        shutil.copy2(appendix_pdf, out_dir / "code_appendix.pdf")

    for src, rel in code_files:
        dst = out_dir / "code" / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)

    for src, rel in data_files:
        dst = out_dir / "data_clean" / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)

    pages_desc = f"{page_count} total PDF pages" if page_count is not None else "compiled submission PDF"
    readme_lines = [
        "Reproducible Mathematical Modeling Submission Package",
        "====================================================",
        "",
        "Whitelisted Deliverables in output/submission/:",
        f"1. paper.pdf ({pages_desc})",
    ]
    idx = 2
    if has_appendix:
        readme_lines.append(f"{idx}. code_appendix.pdf (supporting code appendix)")
        idx += 1
    if code_files:
        readme_lines.append(f"{idx}. code/ ({len(code_files)} clean source file(s))")
        for _, rel in code_files:
            readme_lines.append(f"     - code/{rel.as_posix()}")
        idx += 1
    if data_files:
        readme_lines.append(f"{idx}. data_clean/ ({len(data_files)} clean input data file(s))")
        idx += 1
    readme_lines.append(f"{idx}. SHA256SUMS.txt (cryptographic SHA-256 checksums for all packaged files)")
    (out_dir / "README_SUBMISSION.txt").write_text("\n".join(readme_lines) + "\n", encoding="utf-8")

    # Compute sorted SHA-256 digests and verify 1-to-1 completeness
    packaged = sorted(
        (p for p in out_dir.rglob("*") if p.is_file() and p.name != "SHA256SUMS.txt"),
        key=lambda p: p.relative_to(out_dir).as_posix(),
    )
    digest_lines = [f"{_sha256_file(p)}  {p.relative_to(out_dir).as_posix()}" for p in packaged]
    (out_dir / "SHA256SUMS.txt").write_text("\n".join(digest_lines) + "\n", encoding="utf-8")

    return {
        "out_dir": str(out_dir),
        "page_count": page_count,
        "files": [p.relative_to(out_dir).as_posix() for p in packaged] + ["SHA256SUMS.txt"],
        "digests": len(digest_lines),
        "dry_run": False,
    }


def self_test() -> int:
    with tempfile.TemporaryDirectory(prefix="pack_sub_test_") as td:
        proj = Path(td)
        (proj / "output" / "paper").mkdir(parents=True)
        (proj / "output" / "paper" / "main.pdf").write_bytes(b"%PDF-1.4\n%fake main\n%%EOF\n")
        (proj / "output" / "code_appendix.pdf").write_bytes(b"%PDF-1.4\n%fake app\n%%EOF\n")

        # Clean code + dirty caches
        (proj / "work" / "code" / "__pycache__").mkdir(parents=True)
        (proj / "work" / "code" / "solve_q1.py").write_text("print('ok')\n", encoding="utf-8")
        (proj / "work" / "code" / "__pycache__" / "solve_q1.cpython-311.pyc").write_bytes(b"\x00\x01")
        (proj / "work" / "code" / "_tmp_debug.py").write_text("# temp\n", encoding="utf-8")
        (proj / "work" / "data_clean").mkdir(parents=True)
        (proj / "work" / "data_clean" / "inputs.csv").write_text("a,b\n1,2\n", encoding="utf-8")

        # Stale junk pre-existing inside output/submission/ MUST be wiped completely
        stale = proj / "output" / "submission" / "work" / "scratch"
        stale.mkdir(parents=True)
        (stale / "qa_page_1.png").write_bytes(b"PNG")
        (proj / "output" / "submission" / "old_junk.txt").write_text("stale", encoding="utf-8")

        dry = pack_submission(proj, dry_run=True)
        assert dry["dry_run"] is True and (stale / "qa_page_1.png").exists()

        res = pack_submission(proj, dry_run=False)
        out = proj / "output" / "submission"
        assert not (out / "work").exists(), "Stale work/scratch dir was NOT wiped!"
        assert not (out / "old_junk.txt").exists(), "Stale file was NOT wiped!"
        assert not list(out.rglob("*.pyc")), "*.pyc leaked into submission!"
        assert (out / "paper.pdf").is_file()
        assert (out / "code_appendix.pdf").is_file()
        assert (out / "code" / "solve_q1.py").is_file()
        assert not (out / "code" / "_tmp_debug.py").exists()
        assert (out / "data_clean" / "inputs.csv").is_file()

        sums = (out / "SHA256SUMS.txt").read_text(encoding="utf-8").strip().splitlines()
        listed_files = {line.split("  ", 1)[1]: line.split("  ", 1)[0] for line in sums}
        actual_files = {
            p.relative_to(out).as_posix(): _sha256_file(p)
            for p in out.rglob("*")
            if p.is_file() and p.name != "SHA256SUMS.txt"
        }
        assert listed_files == actual_files, f"SHA256SUMS mismatch: {listed_files} vs {actual_files}"
        assert len(sums) == 5, sums  # paper.pdf, code_appendix.pdf, code/solve_q1.py, data_clean/inputs.csv, README_SUBMISSION.txt
        print(f"[SELF-TEST] PASS (clean-room rebuild wiped stale scratch & verified {len(sums)} SHA-256 deliverables)")
    return 0


def main() -> int:
    if "--self-test" in sys.argv:
        return self_test()

    ap = argparse.ArgumentParser(description="洁净白名单构建竞赛提交包 output/submission/")
    ap.add_argument("--project", default=".", help="项目根目录（默认当前目录）")
    ap.add_argument("--out", default="output/submission", help="输出提交目录（默认 output/submission）")
    ap.add_argument("--paper", default="", help="主论文 PDF 路径（默认自动寻找 output/paper/paper.pdf 或 main.pdf）")
    ap.add_argument("--appendix", default="output/code_appendix.pdf", help="代码附录 PDF 路径")
    ap.add_argument("--code", default="work/code", help="源码目录（默认 work/code）")
    ap.add_argument("--data", default="work/data_clean", help="清洗数据目录（默认 work/data_clean）")
    ap.add_argument("--dry-run", action="store_true", help="仅预览拟打包清单，不写入磁盘")
    ap.add_argument("--self-test", action="store_true", help="运行内置自检")
    args = ap.parse_args()

    res = pack_submission(
        project=Path(args.project),
        out_raw=args.out,
        paper_raw=args.paper,
        appendix_raw=args.appendix,
        code_raw=args.code,
        data_raw=args.data,
        dry_run=args.dry_run,
    )
    prefix = "[DRY-RUN]" if res["dry_run"] else "[OK]"
    print(f"{prefix} Submission package -> {res['out_dir']} ({len(res['files'])} files)")
    for rel in res["files"]:
        print(f"  - {rel}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
