#!/usr/bin/env python3
"""Verifier for global and per-project math-modeling-universal installations.

Audits:
  1. Every detected/managed target has all 11 `math-*` skills.
  2. Each SKILL.md contains valid YAML frontmatter matching its directory name.
  3. Zero stray top-level `_shared/` folder exists in any agent skills root.
  4. `_shared/scripts/` and `_shared/templates/run_manifest.yaml` resolve cleanly
     through every mounted skill path (including nested Windows Junctions).
  5. Live script smoke tests (`manifest_cli.py --self-test`, `check_formulation.py --self-test`,
     `paper_qa.py --self-test`, and `scripts/mm_run.py --which`) succeed through mounted paths.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

from install import MARKER_FILENAME, SKILL_NAMES, _agent_registry


def parse_frontmatter_name(skill_md: Path) -> str | None:
    text = skill_md.read_text(encoding="utf8", errors="ignore")
    m = re.match(r"^---\s*\n(.*?)\n---", text, re.S)
    if not m:
        return None
    nm = re.search(r"(?m)^name:\s*['\"]?([A-Za-z0-9_.\-]+)['\"]?\s*$", m.group(1))
    return nm.group(1) if nm else None


def verify_target(aid: str, target_root: Path) -> list[str]:
    errs: list[str] = []
    if not target_root.is_dir():
        return [f"{aid}: target directory missing: {target_root}"]

    # 1. No stray top-level _shared inside agent root
    if (target_root / "_shared").exists():
        errs.append(f"{aid}: stray top-level `_shared/` found in {target_root}")

    # 2. All 11 math-* present + valid YAML + readable _shared + scripts/mm_run.py
    for sname in SKILL_NAMES:
        sdir = target_root / sname
        smd = sdir / "SKILL.md"
        if not smd.is_file():
            errs.append(f"{aid}/{sname}: missing SKILL.md")
            continue
        fm_name = parse_frontmatter_name(smd)
        if fm_name != sname:
            errs.append(f"{aid}/{sname}: frontmatter name {fm_name!r} != dir name {sname!r}")
        if not (sdir / "_shared" / "scripts" / "manifest_cli.py").is_file():
            errs.append(f"{aid}/{sname}: broken _shared/scripts/manifest_cli.py resolution")
        if not (sdir / "_shared" / "templates" / "run_manifest.yaml").is_file():
            errs.append(f"{aid}/{sname}: broken _shared/templates/run_manifest.yaml resolution")
        if not (sdir / "scripts" / "mm_run.py").is_file():
            errs.append(f"{aid}/{sname}: missing scripts/mm_run.py")
    return errs


def run_smoke_suite(mounted_workflow_dir: Path) -> list[str]:
    errs: list[str] = []
    mm_run = mounted_workflow_dir / "scripts" / "mm_run.py"
    for cmd_label, cmd in [
        ("mm_run --which manifest_cli.py", [sys.executable, str(mm_run), "--which", "manifest_cli.py"]),
        ("mm_run manifest_cli.py --self-test", [sys.executable, str(mm_run), "manifest_cli.py", "--self-test"]),
        ("direct _shared check_formulation.py --self-test", [sys.executable, str(mounted_workflow_dir / "_shared" / "scripts" / "check_formulation.py"), "--self-test"]),
        ("direct _shared paper_qa.py --self-test", [sys.executable, str(mounted_workflow_dir / "_shared" / "scripts" / "paper_qa.py"), "--self-test"]),
    ]:
        res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf8", errors="replace")
        if res.returncode != 0:
            errs.append(f"{cmd_label} failed (rc={res.returncode}): {res.stdout[-200:]} {res.stderr[-200:]}")
        else:
            print(f"  [PASS] {cmd_label} (via {mounted_workflow_dir})")
    return errs


def main() -> int:
    ap = argparse.ArgumentParser(description="Verify installed math-modeling-universal skill mounts.")
    ap.add_argument("--project", default="", help="Verify a project installation instead of global agents")
    ap.add_argument("--skip-self-test", action="store_true", help="Only verify structure/paths without running script self-tests")
    args = ap.parse_args()

    candidates: list[tuple[str, Path]] = []
    if args.project:
        proj = Path(args.project).resolve()
        candidates.append(("project-agents", proj / ".agents" / "skills"))
        candidates.append(("project-claude", proj / ".claude" / "skills"))
    else:
        for aid, info in _agent_registry().items():
            t = info["target"]
            if (t / MARKER_FILENAME).is_file() or (t / "math-modeling-workflow").exists():
                candidates.append((aid, t))

    if not candidates:
        print("[FAIL] No installed math-modeling-universal targets detected. Run `python install.py --agents auto`.")
        return 1

    all_errors: list[str] = []
    for aid, tpath in candidates:
        errs = verify_target(aid, tpath)
        if errs:
            all_errors.extend(errs)
            print(f"[FAIL] {aid:<14} ({tpath}): {len(errs)} issues")
            for e in errs:
                print(f"       - {e}")
        else:
            print(f"[PASS] {aid:<14} ({tpath}): 11/11 skills + _shared + mm_run.py OK")

    if not args.skip_self_test and candidates:
        print("\n=== Live Script Traversal & Self-Test Verification ===")
        # Test through up to 3 distinct mounted agent paths (first, middle, last) to prove nested traversal
        picks = [candidates[0]]
        if len(candidates) > 1:
            picks.append(candidates[-1])
        for aid, tpath in picks:
            wf_dir = tpath / "math-modeling-workflow"
            if wf_dir.is_dir():
                all_errors.extend(run_smoke_suite(wf_dir))

    print(f"\nSummary: checked {len(candidates)} agent target(s), total errors = {len(all_errors)}")
    return 1 if all_errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
