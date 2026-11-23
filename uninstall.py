#!/usr/bin/env python3
"""Safe uninstaller for math-modeling-universal across global & project skill roots.

Removes ONLY the managed `math-*` entries (and `.math-modeling-managed.json` marker)
without deleting canonical source files or any unrelated skills installed by the user.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from install import (
    MARKER_FILENAME,
    SKILL_NAMES,
    _agent_registry,
    is_reparse_or_symlink,
    resolve_targets,
    safe_remove_entry,
)


def uninstall_from_target(target_root: Path, dry_run: bool = False) -> list[str]:
    removed: list[str] = []
    if not target_root.is_dir():
        return removed

    managed: set[str] = set()
    marker = target_root / MARKER_FILENAME
    if marker.is_file():
        try:
            managed = set(json.loads(marker.read_text(encoding="utf8")).get("skills", []))
        except Exception:
            managed = set()

    candidates = sorted(managed | set(SKILL_NAMES))
    for sname in candidates:
        p = target_root / sname
        if not (p.exists() or p.is_symlink()):
            continue
        # Only delete if in marker OR it is a link pointing to math-* in math-modeling-universal
        if sname in managed or is_reparse_or_symlink(p):
            if not dry_run:
                safe_remove_entry(p)
            removed.append(sname)

    if marker.is_file() and not dry_run:
        marker.unlink()
    return removed


def main() -> int:
    ap = argparse.ArgumentParser(description="Uninstall math-modeling-universal skills from agent directories.")
    ap.add_argument("--agents", default="all", help="auto | all | comma-separated agent IDs")
    ap.add_argument("--project", default="", help="Also clean <project>/.agents/skills and <project>/.claude/skills")
    ap.add_argument("--dry-run", action="store_true", help="Show what would be removed without deleting anything")
    args = ap.parse_args()

    registry = _agent_registry()
    targets: list[tuple[str, Path]] = []
    if args.project:
        proj = Path(args.project).resolve()
        targets.append(("project-agents", proj / ".agents" / "skills"))
        targets.append(("project-claude", proj / ".claude" / "skills"))
    else:
        for aid, info in resolve_targets(args.agents, registry):
            targets.append((aid, info["target"]))

    tag = "DRY-RUN" if args.dry_run else "REMOVED"
    total = 0
    for aid, tpath in targets:
        rem = uninstall_from_target(tpath, dry_run=args.dry_run)
        if rem:
            total += len(rem)
            print(f"[{tag}] {aid:<14} <- {tpath} ({len(rem)} entries: {', '.join(rem[:3])}...)")
    if total == 0:
        print("[OK] No managed math-* skill installations found in selected targets.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
