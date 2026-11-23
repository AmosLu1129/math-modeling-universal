#!/usr/bin/env python3
"""Universal cross-agent runner for math-modeling shared scripts & resources.

Locates `_shared/scripts/<script>` cleanly whether invoked from inside an
installed skill directory (`~/.claude/skills/math-*/`), a canonical repo tree
(`skills/_shared/`), `$MATH_MODELING_SHARED`, or `~/.math-modeling-skills/_shared`.

Usage:
    python scripts/mm_run.py manifest_cli.py init --project . --competition mcm --language en
    python scripts/mm_run.py --which check_formulation.py
    python scripts/mm_run.py --shared-dir
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def find_shared_dir() -> Path:
    here = Path(__file__).resolve()
    skill_root = here.parent.parent  # skills/math-*/
    candidates = [
        skill_root / "_shared",
        skill_root.parent / "_shared",
        Path(os.environ["MATH_MODELING_SHARED"]) if os.environ.get("MATH_MODELING_SHARED") else None,
        Path.home() / ".math-modeling-skills" / "_shared",
        Path.home() / ".agents" / "_math-modeling-shared",
    ]
    for cand in candidates:
        if cand is not None and (cand / "scripts").is_dir():
            return cand.resolve()
    raise FileNotFoundError(
        "Cannot locate math-modeling `_shared/` directory. "
        "Re-run `install.py` or set MATH_MODELING_SHARED."
    )


def main() -> int:
    args = sys.argv[1:]
    if not args or args[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    shared = find_shared_dir()
    if args[0] == "--shared-dir":
        print(shared)
        return 0
    if args[0] == "--which":
        if len(args) < 2:
            print("Usage: mm_run.py --which <script_name.py>", file=sys.stderr)
            return 2
        p = shared / "scripts" / args[1]
        if not p.is_file():
            print(f"Script not found: {p}", file=sys.stderr)
            return 1
        print(p)
        return 0

    script_name = args[0]
    script_path = shared / "scripts" / script_name
    if not script_path.is_file():
        script_path = shared / script_name
    if not script_path.is_file():
        print(f"Shared script not found: {script_name} (looked in {shared / 'scripts'})", file=sys.stderr)
        return 2

    env = os.environ.copy()
    env.setdefault("PYTHONIOENCODING", "utf-8")
    env["MATH_MODELING_SHARED"] = str(shared)
    proc = subprocess.run([sys.executable, str(script_path), *args[1:]], env=env)
    return proc.returncode


if __name__ == "__main__":
    raise SystemExit(main())
