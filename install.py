#!/usr/bin/env python3
"""Cross-agent global & project installer for math-modeling-universal skills.

Supports Claude Code, OpenAI Codex, OpenCode, DeepSeek Harness (dsh),
Qoder / Qoder-CN, Trae-CN, Cursor, Windsurf, Gemini CLI, Antigravity,
and the open `.agents/skills` standard across Windows, macOS, and Linux.

Usage:
    python install.py --list-targets
    python install.py --agents auto --mode link
    python install.py --agents claude,codex,opencode,dsh,qoder-cn --mode link
    python install.py --project /path/to/repo --mode copy
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import stat
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent
SKILLS_SRC = REPO_ROOT / "skills"
SHARED_SRC = SKILLS_SRC / "_shared"
MARKER_FILENAME = ".math-modeling-managed.json"
SKILL_NAMES = sorted(
    p.name for p in SKILLS_SRC.iterdir()
    if p.is_dir() and p.name.startswith("math-") and (p / "SKILL.md").is_file()
)


def _home() -> Path:
    return Path.home()


def _agent_registry() -> dict[str, dict[str, Any]]:
    h = _home()
    return {
        "agents": {
            "label": "Open Agent Skills (.agents standard: Codex / Cursor / OpenCode / dsh)",
            "target": h / ".agents" / "skills",
            "detect": h / ".agents",
            "auto": True,
            "minimal": True,
        },
        "claude": {
            "label": "Claude Code",
            "target": h / ".claude" / "skills",
            "detect": h / ".claude",
            "auto": True,
            "minimal": True,
        },
        "codex": {
            "label": "OpenAI Codex CLI / Desktop",
            "target": h / ".codex" / "skills",
            "detect": h / ".codex",
            "auto": True,
            "minimal": False,
        },
        "opencode": {
            "label": "OpenCode",
            "target": h / ".config" / "opencode" / "skills",
            "detect": h / ".config" / "opencode",
            "auto": True,
            "minimal": False,
        },
        "dsh": {
            "label": "DeepSeek Harness (dsh)",
            "target": h / ".dsh" / "skills",
            "detect": h / ".dsh",
            "auto": True,
            "minimal": False,
        },
        "qoder": {
            "label": "Qoder (International)",
            "target": h / ".qoder" / "skills",
            "detect": h / ".qoder",
            "auto": True,
            "minimal": True,
        },
        "qoder-cn": {
            "label": "Qoder CN",
            "target": h / ".qoder-cn" / "skills",
            "detect": h / ".qoder-cn",
            "auto": True,
            "minimal": True,
        },
        "trae-cn": {
            "label": "Trae CN",
            "target": h / ".trae-cn" / "skills",
            "detect": h / ".trae-cn",
            "auto": True,
            "minimal": False,
        },
        "cursor": {
            "label": "Cursor IDE",
            "target": h / ".cursor" / "skills",
            "detect": h / ".cursor",
            "auto": True,
            "minimal": False,
        },
        "windsurf": {
            "label": "Windsurf",
            "target": h / ".codeium" / "windsurf" / "skills",
            "detect": h / ".codeium" / "windsurf",
            "auto": True,
            "minimal": False,
        },
        "gemini-cli": {
            "label": "Gemini CLI",
            "target": h / ".gemini" / "skills",
            "detect": h / ".gemini",
            "auto": False,  # Already covered or separated by Antigravity below
            "minimal": False,
        },
        "antigravity": {
            "label": "Antigravity (Standalone ~/.gemini/antigravity/skills)",
            "target": h / ".gemini" / "antigravity" / "skills",
            "detect": h / ".gemini" / "antigravity",
            # Skip in auto if native Antigravity plugin `math-modeling` is already installed
            "auto": not (h / ".gemini" / "config" / "plugins" / "math-modeling").is_dir(),
            "minimal": False,
        },
    }


def is_reparse_or_symlink(p: Path) -> bool:
    if not p.exists() and not p.is_symlink():
        return False
    if p.is_symlink():
        return True
    if os.name == "nt":
        try:
            st = p.lstat()
            return bool(getattr(st, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))
        except OSError:
            return False
    return False


def safe_remove_entry(p: Path) -> None:
    """Safely remove a directory link/junction WITHOUT deleting link target contents."""
    if is_reparse_or_symlink(p):
        if os.name == "nt" and p.is_dir():
            os.rmdir(p)
        else:
            p.unlink()
    elif p.is_dir():
        shutil.rmtree(p)
    elif p.exists():
        p.unlink()


def create_dir_link(link_path: Path, target_dir: Path, dry_run: bool = False) -> None:
    if dry_run:
        return
    link_path.parent.mkdir(parents=True, exist_ok=True)
    if link_path.exists() or link_path.is_symlink():
        safe_remove_entry(link_path)
    if os.name == "nt":
        res = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link_path), str(target_dir.resolve())],
            capture_output=True,
            text=True,
        )
        if res.returncode != 0:
            raise OSError(f"mklink /J failed for {link_path} -> {target_dir}: {res.stdout} {res.stderr}")
    else:
        os.symlink(str(target_dir.resolve()), str(link_path), target_is_directory=True)


def copy_tree_clean(
    src: Path,
    dst: Path,
    dry_run: bool = False,
    extra_ignore: tuple[str, ...] = (),
) -> None:
    if dry_run:
        return
    if dst.exists() or dst.is_symlink():
        safe_remove_entry(dst)
    ignore = shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo", ".DS_Store", *extra_ignore)
    shutil.copytree(src, dst, ignore=ignore, symlinks=False)


def ensure_canonical_shared_mounts(mode: str, dry_run: bool = False) -> None:
    """Mount or copy `_shared` inside each canonical `skills/math-*/` folder."""
    if not SHARED_SRC.is_dir():
        raise FileNotFoundError(f"Canonical _shared folder not found: {SHARED_SRC}")
    for sname in SKILL_NAMES:
        sk_dir = SKILLS_SRC / sname
        inner_shared = sk_dir / "_shared"
        if mode == "link":
            create_dir_link(inner_shared, SHARED_SRC, dry_run=dry_run)
        else:
            copy_tree_clean(SHARED_SRC, inner_shared, dry_run=dry_run)


def install_into_target(
    target_root: Path,
    mode: str,
    force: bool = False,
    dry_run: bool = False,
) -> tuple[list[str], list[str]]:
    """Install all 11 math-* skills into `target_root`. Never touches unrelated skills."""
    installed: list[str] = []
    skipped: list[str] = []
    if not dry_run:
        target_root.mkdir(parents=True, exist_ok=True)

    # Also remove any stray top-level _shared inside agent root if a previous manual attempt created one
    stray_shared = target_root / "_shared"
    if (stray_shared.exists() or stray_shared.is_symlink()) and is_reparse_or_symlink(stray_shared):
        if not dry_run:
            safe_remove_entry(stray_shared)

    for sname in SKILL_NAMES:
        src = SKILLS_SRC / sname
        dst = target_root / sname
        already_managed = is_reparse_or_symlink(dst)
        marker_file = target_root / MARKER_FILENAME
        if marker_file.is_file():
            try:
                mdata = json.loads(marker_file.read_text(encoding="utf8"))
                if sname in mdata.get("skills", []):
                    already_managed = True
            except Exception:
                pass

        if (dst.exists() or dst.is_symlink()) and not already_managed and not force:
            skipped.append(sname)
            continue

        if mode == "link":
            create_dir_link(dst, src, dry_run=dry_run)
        else:
            copy_tree_clean(src, dst, dry_run=dry_run, extra_ignore=("_shared",))
            # In portable copy mode, copy canonical `_shared` directly into dst/_shared
            copy_tree_clean(SHARED_SRC, dst / "_shared", dry_run=dry_run)
        installed.append(sname)

    if not dry_run:
        marker = {
            "package": "math-modeling-universal",
            "source_repo": str(REPO_ROOT),
            "mode": mode,
            "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "skills": installed,
        }
        (target_root / MARKER_FILENAME).write_text(json.dumps(marker, indent=2, ensure_ascii=False), encoding="utf8")

    return installed, skipped


def resolve_targets(agents_arg: str, registry: dict[str, dict[str, Any]]) -> list[tuple[str, dict[str, Any]]]:
    tok = agents_arg.strip().lower()
    if tok == "auto":
        return [(k, v) for k, v in registry.items() if v["auto"] and v["detect"].exists()]
    if tok == "all":
        return list(registry.items())
    if tok == "minimal":
        return [(k, v) for k, v in registry.items() if v["minimal"] and (k == "agents" or v["detect"].exists())]

    selected: list[tuple[str, dict[str, Any]]] = []
    for name in [x.strip().lower() for x in agents_arg.split(",") if x.strip()]:
        if name not in registry:
            raise ValueError(f"Unknown agent key: {name!r}. Valid keys: {', '.join(registry)}")
        selected.append((name, registry[name]))
    return selected


def main() -> int:
    ap = argparse.ArgumentParser(description="Global & per-project installer for math-modeling-universal skills.")
    ap.add_argument("--agents", default="auto", help="auto | all | minimal | comma-separated agent IDs")
    ap.add_argument("--mode", default="link", choices=["link", "copy"], help="link (Junction/Symlink, default) or copy")
    ap.add_argument("--project", default="", help="Install into <project>/.agents/skills and <project>/.claude/skills")
    ap.add_argument("--list-targets", action="store_true", help="List known global agent targets and detection status")
    ap.add_argument("--force", action="store_true", help="Overwrite existing non-managed math-* folders if present")
    ap.add_argument("--dry-run", action="store_true", help="Print actions without touching disk")
    args = ap.parse_args()

    registry = _agent_registry()
    if args.list_targets:
        print(f"Canonical repo: {REPO_ROOT}")
        print(f"Bundled skills ({len(SKILL_NAMES)}): {', '.join(SKILL_NAMES)}\n")
        print(f"{'ID':<13} {'Detected':<9} {'Auto':<6} {'Target Path':<48} {'Agent'}")
        print("-" * 115)
        for aid, info in registry.items():
            det = "YES" if info["detect"].exists() else "no"
            auto = "yes" if info["auto"] else "skip"
            print(f"{aid:<13} {det:<9} {auto:<6} {str(info['target']):<48} {info['label']}")
        return 0

    if args.mode == "link":
        ensure_canonical_shared_mounts(mode="link", dry_run=args.dry_run)

    targets: list[tuple[str, Path, str]] = []
    if args.project:
        proj = Path(args.project).resolve()
        targets.append(("project-agents", proj / ".agents" / "skills", f"Project .agents/skills ({proj.name})"))
        targets.append(("project-claude", proj / ".claude" / "skills", f"Project .claude/skills ({proj.name})"))
    else:
        for aid, info in resolve_targets(args.agents, registry):
            targets.append((aid, info["target"], info["label"]))

    if not targets:
        print("[WARN] No matching agent directories detected. Use `--agents all` or `--project <dir>`.")
        return 1

    action = "DRY-RUN" if args.dry_run else "OK"
    for aid, tpath, label in targets:
        inst, skip = install_into_target(tpath, mode=args.mode, force=args.force, dry_run=args.dry_run)
        msg = f"[{action}] {aid:<14} -> {tpath} ({len(inst)} installed"
        if skip:
            msg += f", {len(skip)} skipped non-managed: {skip}"
        msg += f") [{args.mode}]"
        print(msg)

    print(f"\nCanonical _shared location: {SHARED_SRC}")
    if not args.dry_run and not args.project:
        print("Next: run `python verify_install.py` to validate every agent symlink/junction & live script check.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
