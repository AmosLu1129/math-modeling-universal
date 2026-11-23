#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""数学建模 workflow 环境检查与安装（跨平台：Windows / macOS / Linux）。

用法：
    python setup_env.py            # 只检查，输出状态表
    python setup_env.py --install  # 检查 + 安装可免密安装的依赖
    python setup_env.py --install-homebrew   # macOS 下额外尝试安装 Homebrew
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
import zipfile
from pathlib import Path

IS_WIN = platform.system() == "Windows"
IS_MAC = platform.system() == "Darwin"
IS_LINUX = platform.system() == "Linux"

HOME = Path.home()
LOCAL_BIN = HOME / ".local" / "bin"
TEX_DIR = HOME / ".local" / "tex"

PY_REQUIRED = [
    "numpy", "pandas", "scipy", "statsmodels", "matplotlib", "seaborn",
    "networkx", "sympy", "scikit-learn", "openpyxl", "xlrd", "olefile",
    "pypdf", "pdfplumber",
    "svglib", "reportlab", "pillow", "pygments", "arxiv", "habanero",
    "tenacity", "requests",
    "ortools", "pymoo",  # 优化/多目标小问：CP-SAT 精确求解 + NSGA-II/超体积
]

STATE: dict[str, dict] = {}  # name -> {ok, detail, install_cmd, auto}

IMPORT_NAMES = {
    "scikit-learn": "sklearn",
    "pillow": "PIL",
}


def sh(name: str) -> str | None:
    return shutil.which(name)


def check_bin(name: str, store: str | None = None, install_hint: str = "") -> str | None:
    found = sh(name)
    key = store or name
    STATE[key] = {
        "ok": found is not None,
        "detail": found or "",
        "install_cmd": install_hint,
        "auto": False,
    }
    return found


def py_pkg_ok(name: str) -> bool:
    try:
        __import__(IMPORT_NAMES.get(name, name))
        return True
    except Exception:
        return False


def python_bin() -> str:
    return sys.executable


def arch_suffix() -> str:
    m = platform.machine().lower()
    if m in ("arm64", "aarch64"):
        return "aarch64"
    return "x86_64"


def latest_gh_release_asset(repo: str, name_contains: str) -> tuple[str, str]:
    req = urllib.request.Request(
        f"https://api.github.com/repos/{repo}/releases/latest",
        headers={"User-Agent": "setup-env"},
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.load(r)
    for a in data.get("assets", []):
        if name_contains in a["name"]:
            return a["browser_download_url"], a["name"]
    raise RuntimeError(f"no asset matching {name_contains} in {repo}")


def download(url: str, dest: Path, timeout: int = 600) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": "setup-env"})
    with urllib.request.urlopen(req, timeout=timeout) as r, open(dest, "wb") as f:
        shutil.copyfileobj(r, f)


def _extract_binary_from_archive(archive_path: Path, bin_name: str, dest: Path) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        if archive_path.suffix == ".zip":
            with zipfile.ZipFile(archive_path, "r") as zf:
                zf.extractall(tmp)
        else:
            with tarfile.open(archive_path) as tf:
                tf.extractall(tmp)
        exe_name = f"{bin_name}.exe" if IS_WIN else bin_name
        bin_src = next(p for p in Path(tmp).rglob(exe_name) if p.is_file())
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(bin_src, dest)
        if not IS_WIN:
            os.chmod(dest, 0o755)


def install_tectonic() -> bool:
    try:
        suffix = arch_suffix()
        if IS_WIN:
            url, asset_name = latest_gh_release_asset("tectonic-typesetting/tectonic", f"{suffix}-pc-windows-msvc.zip")
        elif IS_MAC:
            url, asset_name = latest_gh_release_asset("tectonic-typesetting/tectonic", f"{suffix}-apple-darwin.tar.gz")
        else:
            url, asset_name = latest_gh_release_asset("tectonic-typesetting/tectonic", f"{suffix}-unknown-linux-gnu.tar.gz")
        with tempfile.TemporaryDirectory() as tmp:
            arc = Path(tmp) / asset_name
            download(url, arc)
            if IS_WIN:
                dest = LOCAL_BIN / "tectonic.exe"
                _extract_binary_from_archive(arc, "tectonic", dest)
            else:
                dest = TEX_DIR / "tectonic"
                _extract_binary_from_archive(arc, "tectonic", dest)
                auto_symlink("tectonic", str(dest))
        return True
    except Exception as e:  # noqa: BLE001
        STATE["tectonic"]["detail"] = f"install failed: {e}"
        return False


def install_typst() -> bool:
    try:
        suffix = arch_suffix()
        if IS_WIN:
            target = f"{suffix}-pc-windows-msvc.zip"
        elif IS_MAC:
            target = f"{suffix}-apple-darwin.tar.xz"
        else:
            target = f"{suffix}-unknown-linux-musl.tar.xz"
        url = f"https://github.com/typst/typst/releases/latest/download/typst-{target}"
        with tempfile.TemporaryDirectory() as tmp:
            arc = Path(tmp) / f"typst-{target}"
            download(url, arc)
            dest = LOCAL_BIN / ("typst.exe" if IS_WIN else "typst")
            _extract_binary_from_archive(arc, "typst", dest)
        return True
    except Exception as e:  # noqa: BLE001
        STATE["typst"]["detail"] = f"install failed: {e}"
        return False


def install_python_packages() -> tuple[int, list[str]]:
    missing = [p for p in PY_REQUIRED if not py_pkg_ok(p)]
    if not missing:
        return 0, []
    cmd = [sys.executable, "-m", "pip", "install", "--quiet"] + missing
    try:
        subprocess.run(cmd, check=True, timeout=900)
        still = [p for p in missing if not py_pkg_ok(p)]
        return (0 if not still else 1), still
    except Exception as e:  # noqa: BLE001
        return 1, [f"{p}({e})" for p in missing]


def install_playwright_chromium() -> bool:
    npx = sh("npx")
    if not npx:
        return False
    try:
        subprocess.run(
            [npx, "--yes", "playwright@latest", "install", "chromium"],
            check=True, timeout=1800, capture_output=True,
        )
        return True
    except Exception as e:  # noqa: BLE001
        STATE["browser"]["detail"] = f"playwright install failed: {e}"
        return False


def find_binary_multi(name: str, extra_dirs: list[Path] | None = None) -> tuple[str | None, str]:
    found = shutil.which(name)
    if found:
        return found, found

    exe_name = f"{name}.exe" if IS_WIN else name
    dirs = [LOCAL_BIN, TEX_DIR]
    if extra_dirs:
        dirs += list(extra_dirs)
    for d in dirs:
        cand = Path(d) / exe_name
        if cand.is_file():
            return str(cand), str(cand)

    if IS_WIN:
        prog = Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
        prog86 = Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"))
        local_app = Path(os.environ.get("LOCALAPPDATA", ""))
        win_globs = {
            "drawio": [
                prog / "draw.io" / "draw.io.exe",
                prog86 / "draw.io" / "draw.io.exe",
                local_app / "Programs" / "draw.io" / "draw.io.exe",
            ],
        }
        for cand in win_globs.get(name, []):
            if cand.is_file():
                return str(cand), str(cand)

    if IS_MAC:
        for hb in (Path("/opt/homebrew/bin"), Path("/usr/local/bin")):
            cand = hb / name
            if cand.is_file() and os.access(cand, os.X_OK):
                return str(cand), str(cand)
        app_globs = {
            "drawio": [
                "Applications/draw.io.app/Contents/MacOS/draw.io",
                "Applications/Draw.io.app/Contents/MacOS/draw.io",
            ],
        }
        for globpat in app_globs.get(name, []):
            hits = list(Path("/").glob(globpat))
            if hits:
                return str(hits[0]), str(hits[0])

    return None, ""


def auto_symlink(name: str, src: str) -> str:
    LOCAL_BIN.mkdir(parents=True, exist_ok=True)
    link = LOCAL_BIN / name
    srcp = Path(src)
    if link.exists() and link.resolve() == srcp.resolve():
        return str(link)
    if link.exists() or link.is_symlink():
        link.unlink()
    link.symlink_to(srcp)
    return str(link)


def browser_status() -> tuple[bool, str, str]:
    cands: list[Path] = []
    if IS_WIN:
        prog = Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
        prog86 = Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"))
        local_app = Path(os.environ.get("LOCALAPPDATA", ""))
        cands += [
            prog / "Google" / "Chrome" / "Application" / "chrome.exe",
            prog86 / "Google" / "Chrome" / "Application" / "chrome.exe",
            local_app / "Google" / "Chrome" / "Application" / "chrome.exe",
            prog / "Microsoft" / "Edge" / "Application" / "msedge.exe",
            prog86 / "Microsoft" / "Edge" / "Application" / "msedge.exe",
        ]
        for pat in ("ms-playwright/chromium-*/chrome-win*/chrome.exe",):
            cands += list(local_app.glob(pat))
    elif IS_MAC:
        cands += [
            Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
            Path("/Applications/Chromium.app/Contents/MacOS/Chromium"),
            Path("/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"),
        ]
        for pat in (
            "Library/Caches/ms-playwright/chromium-*/chrome-mac*/Google Chrome for Testing.app/Contents/MacOS/*",
            "Library/Caches/ms-playwright/chromium-*/chrome-mac*/Chromium.app/Contents/MacOS/Chromium",
        ):
            cands += list(HOME.glob(pat))
    else:
        for b in ("google-chrome", "chromium", "chromium-browser", "microsoft-edge"):
            found = sh(b)
            if found:
                return True, found, ""

    for app in cands:
        if app.exists():
            return True, str(app), ""
    return False, "", "npx playwright install chromium"


def font_status() -> list[str]:
    if IS_WIN:
        fdir = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
        required = {
            "Times New Roman": [fdir / "times.ttf"],
            "Arial": [fdir / "arial.ttf"],
            "Courier New": [fdir / "cour.ttf"],
            "宋体/微软雅黑": [fdir / "simsun.ttc", fdir / "msyh.ttc", fdir / "simhei.ttf"],
        }
        return [label for label, paths in required.items() if not any(p.exists() for p in paths)]
    if IS_MAC:
        sup = Path("/System/Library/Fonts/Supplemental")
        english = [sup / "Times New Roman.ttf", sup / "Arial.ttf", sup / "Courier New.ttf"]
        chinese = [sup / "Songti.ttc"]
        pingfang = list(Path("/System/Library/Fonts").glob("PingFang.ttc")) or \
            list(Path("/System/Library/AssetsV2/com_apple_MobileAsset_Font7").glob("*/AssetData/PingFang.ttc"))
        if pingfang:
            chinese.append(pingfang[0])
        return [f.name for f in english + chinese if not f.exists()]
    # Linux: check fc-list if available
    if sh("fc-list"):
        out = subprocess.run(["fc-list", ":family"], capture_output=True, text=True, timeout=10).stdout.lower()
        missing = []
        if not any(k in out for k in ("noto sans cjk", "noto serif cjk", "source han", "wqy")):
            missing.append("Noto Sans CJK / 思源字体")
        return missing
    return []


def install_homebrew() -> bool:
    if not IS_MAC:
        return False
    script = ("/bin/bash -c \"$(curl -fsSL "
              "https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)\"")
    env = dict(os.environ, NONINTERACTIVE="1", CI="1")
    try:
        subprocess.run(["bash", "-lc", script], check=True, timeout=1800, capture_output=True, env=env)
        return sh("brew") is not None
    except Exception as e:  # noqa: BLE001
        STATE["homebrew"]["detail"] = f"install failed: {e}"
        return False


def run(install: bool, install_hb: bool) -> int:
    LOCAL_BIN.mkdir(parents=True, exist_ok=True)
    # ---- 1. Python ----
    STATE["python"] = {"ok": True, "detail": python_bin(), "install_cmd": "", "auto": False}
    missing_py = [p for p in PY_REQUIRED if not py_pkg_ok(p)]
    STATE["pip_packages"] = {
        "ok": not missing_py,
        "detail": ("all ok" if not missing_py else "missing: " + ", ".join(missing_py)),
        "install_cmd": f'"{python_bin()}" -m pip install ' + " ".join(missing_py),
        "auto": True,
    }

    # ---- 2. TeX / Typst ----
    tec_path, tec_src = find_binary_multi("tectonic")
    STATE["tectonic"] = {
        "ok": tec_path is not None,
        "detail": tec_src or "not found（已有 xelatex 时可选）",
        "install_cmd": "setup_env.py --install",
        "auto": True,
    }
    check_bin(
        "xelatex",
        install_hint=("winget install MiKTeX.MiKTeX" if IS_WIN else ("brew install --cask basictex" if IS_MAC else "sudo apt install texlive-xetex")),
    )
    typ_path, typ_src = find_binary_multi("typst")
    STATE["typst"] = {
        "ok": typ_path is not None,
        "detail": typ_src or "not found",
        "install_cmd": "setup_env.py --install" + (" 或 winget install Typst.Typst" if IS_WIN else ""),
        "auto": True,
    }

    # ---- 3. PDF ----
    check_bin("pdftoppm", install_hint=("随 MiKTeX 附带或 winget install oschwartz10612.Poppler" if IS_WIN else "brew install poppler / apt install poppler-utils"))
    check_bin("pdftotext", install_hint=("可选：已有 pdfplumber 兜底"))

    # ---- 4. SVG ----
    check_bin("rsvg-convert", install_hint=("可选：已有 cairosvg/svglib 兜底" if IS_WIN else "brew install librsvg"))
    try:
        import cairosvg  # noqa: F401
        STATE["cairosvg"] = {"ok": True, "detail": "python cairosvg", "install_cmd": "", "auto": False}
    except Exception:
        STATE["cairosvg"] = {"ok": False, "detail": "not installed", "install_cmd": "pip install cairosvg", "auto": False}
    STATE["svglib"] = {"ok": py_pkg_ok("svglib"), "detail": "", "install_cmd": "pip install svglib", "auto": True}
    svg_any = any(STATE[k]["ok"] for k in ("rsvg-convert", "cairosvg", "svglib"))
    STATE["svg_render_ok"] = {"ok": svg_any, "detail": "rsvg/cairosvg/svglib 任一可用即可", "install_cmd": "", "auto": False}

    # ---- 5. Browser ----
    ok_br, detail_br, cmd_br = browser_status()
    STATE["browser"] = {"ok": ok_br, "detail": detail_br or "not found", "install_cmd": cmd_br or "", "auto": True}

    # ---- 6. Node ----
    node_hint = "winget install OpenJS.NodeJS.LTS" if IS_WIN else "brew install node"
    check_bin("node", install_hint=node_hint)
    check_bin("npx", install_hint=node_hint)

    # ---- 7. Fonts ----
    miss_fonts = font_status()
    STATE["fonts"] = {
        "ok": not miss_fonts,
        "detail": "missing: " + ", ".join(miss_fonts) if miss_fonts else "Times/Arial/Courier + 中文字体 ok",
        "install_cmd": "安装缺失字体" if miss_fonts else "",
        "auto": False,
    }

    # ---- 8. Homebrew (macOS only) ----
    if IS_MAC:
        check_bin("brew", "homebrew", install_hint="setup_env.py --install-homebrew")

    # ---- 9. DrawIO ----
    drw_path, drw_src = find_binary_multi("drawio")
    STATE["drawio"] = {
        "ok": drw_path is not None,
        "detail": drw_src or "not found（可选）",
        "install_cmd": "",
        "auto": False,
    }

    if install:
        print("\n[install] 开始安装可免密安装的依赖 ...")
        if not STATE["pip_packages"]["ok"]:
            print("  - pip 安装 Python 包 ...")
            rc, still = install_python_packages()
            STATE["pip_packages"]["ok"] = rc == 0
            STATE["pip_packages"]["detail"] = "still missing: " + ", ".join(still) if still else "all ok"
        if not STATE["typst"]["ok"]:
            print("  - 安装 typst ...")
            STATE["typst"]["ok"] = install_typst()
        if not STATE["tectonic"]["ok"] and not STATE["xelatex"]["ok"]:
            print("  - 安装 tectonic ...")
            STATE["tectonic"]["ok"] = install_tectonic()
        if not STATE["browser"]["ok"]:
            print("  - 安装 playwright chromium ...")
            STATE["browser"]["ok"] = install_playwright_chromium()
            if STATE["browser"]["ok"]:
                okb, detb, _ = browser_status()
                STATE["browser"]["detail"] = detb

    if install_hb and IS_MAC and not STATE.get("homebrew", {}).get("ok"):
        STATE["homebrew"]["ok"] = install_homebrew()

    print(f"\n=== 环境状态 ({platform.system()}) ===")
    width = max(len(k) for k in STATE) + 2
    for name, st in STATE.items():
        mark = "OK " if st["ok"] else "MISS"
        print(f"{mark}  {name:<{width}} {st['detail'][:80]}")
        if not st["ok"] and st["install_cmd"]:
            print(f"         -> {st['install_cmd']}")
    path_entries = [Path(p) for p in os.environ.get("PATH", "").split(os.pathsep) if p]
    if LOCAL_BIN not in path_entries and (LOCAL_BIN / ("typst.exe" if IS_WIN else "typst")).exists():
        print(f"\n提示：请把 {LOCAL_BIN} 加入 PATH 环境变量")

    # 关键发布与计算能力就绪判据：python + pip_packages + (xelatex or tectonic or typst) + svg_render_ok + browser + fonts
    core_ok = (
        STATE["pip_packages"]["ok"]
        and (STATE["xelatex"]["ok"] or STATE["tectonic"]["ok"] or STATE["typst"]["ok"])
        and STATE["svg_render_ok"]["ok"]
        and STATE["browser"]["ok"]
        and STATE["fonts"]["ok"]
    )
    return 0 if core_ok else 1


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="数学建模 workflow 环境检查与安装")
    ap.add_argument("--install", action="store_true", help="检查并安装可免密安装的依赖")
    ap.add_argument("--install-homebrew", action="store_true", help="macOS 尝试安装 Homebrew")
    args = ap.parse_args()
    sys.exit(run(args.install, args.install_homebrew))
