#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""HTML + SVG + 印刷级数学公式 双层总装矢量/高清渲染器（零 pip 额外依赖，自动探测 Edge / Chrome / Chromium）。

用法：
    python render_html_figure.py --init-template work/figures/fig_arch.html
    python render_html_figure.py --html work/figures/fig_arch.html \
        --out-png work/figures/fig_arch.png --out-pdf work/figures/fig_arch.pdf \
        --width 1200 --height 680 --scale 2.5 --dpi 300
    python render_html_figure.py --self-test
"""

from __future__ import annotations

import argparse
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import html as html_lib
import json
import math
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from PIL import Image


def find_browser() -> str | None:
    """Locate Edge / Chrome / Chromium executable across Windows, macOS, and Linux."""
    env_b = os.environ.get("MATHFIG_BROWSER", "").strip()
    if env_b and Path(env_b).is_file():
        return env_b

    for name in (
        "msedge",
        "microsoft-edge",
        "google-chrome",
        "chromium",
        "chromium-browser",
        "chrome",
    ):
        found = shutil.which(name)
        if found:
            return found

    candidates: list[str] = []
    sys_name = platform.system()
    if sys_name == "Windows":
        candidates = [
            r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        ]
    elif sys_name == "Darwin":
        candidates = [
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
            "/Applications/Chromium.app/Contents/MacOS/Chromium",
        ]
    else:
        candidates = [
            "/usr/bin/google-chrome",
            "/usr/bin/chromium",
            "/usr/bin/chromium-browser",
            "/usr/bin/microsoft-edge",
        ]
    for p in candidates:
        if Path(p).is_file():
            return p
    return None


def _default_html_template(title: str, width: int = 1200, height: int = 660) -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<title>{title}</title>
<style>
  @page {{
    size: {width}px {height}px;
    margin: 0;
  }}
  * {{
    box-sizing: border-box;
    margin: 0;
    padding: 0;
  }}
  html, body {{
    width: {width}px;
    height: {height}px;
    overflow: hidden;
    background: #FFFFFF;
    font-family: "Arial", "Helvetica Neue", "Microsoft YaHei", sans-serif;
    color: #232830;
    -webkit-font-smoothing: antialiased;
  }}
  .canvas {{
    position: relative;
    width: {width}px;
    height: {height}px;
    padding: 26px 32px;
    background: #FFFFFF;
    display: flex;
    flex-direction: column;
    justify-content: space-between;
  }}
  .header-row {{
    display: flex;
    align-items: center;
    justify-content: space-between;
    border-bottom: 1.5px solid #DCE2EA;
    padding-bottom: 10px;
  }}
  .title-main {{
    font-size: 20px;
    font-weight: 700;
    color: #1F242A;
    letter-spacing: -0.2px;
  }}
  .badge-pill {{
    background: #EEF3F7;
    color: #3B5875;
    border: 1px solid #C5D5D8;
    border-radius: 14px;
    padding: 4px 12px;
    font-size: 12px;
    font-weight: 700;
  }}
  .grid-stage {{
    position: relative;
    display: grid;
    grid-template-columns: 1fr 74px 1.15fr 74px 1fr;
    align-items: stretch;
    gap: 0;
    height: 490px;
    margin-top: 10px;
  }}
  .card {{
    position: relative;
    z-index: 2;
    background: #F8FAFC;
    border: 1.4px solid #D3DCE6;
    border-radius: 12px;
    padding: 16px 18px;
    display: flex;
    flex-direction: column;
    gap: 12px;
    box-shadow: 0 3px 10px rgba(31, 36, 42, 0.04);
  }}
  .card-head {{
    display: flex;
    align-items: center;
    gap: 9px;
    padding-bottom: 8px;
    border-bottom: 1px solid #E3E8EE;
  }}
  .accent-bar {{
    width: 6px;
    height: 22px;
    border-radius: 3px;
  }}
  .card-title {{
    font-size: 15px;
    font-weight: 700;
    color: #232830;
  }}
  .sub-box {{
    background: #FFFFFF;
    border: 1px solid #E3E8EE;
    border-radius: 8px;
    padding: 10px 12px;
    font-size: 13px;
    line-height: 1.45;
  }}
  .sub-label {{
    font-size: 11px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    margin-bottom: 4px;
  }}
  /* Print-grade mathematical typesetting (works 100% offline with STIX / Cambria / Times) */
  .math-block {{
    font-family: "Times New Roman", "Cambria Math", "STIX Two Math", serif;
    font-size: 15.5px;
    color: #1F242A;
    background: #F4F6F9;
    border-left: 3px solid #4E6E8E;
    padding: 8px 11px;
    border-radius: 0 6px 6px 0;
    line-height: 1.55;
  }}
  .math-i {{
    font-style: italic;
  }}
  .frac {{
    display: inline-flex;
    flex-direction: column;
    vertical-align: middle;
    text-align: center;
    font-size: 0.86em;
    line-height: 1.05;
    margin: 0 2px;
  }}
  .frac .num {{
    border-bottom: 1px solid #1F242A;
    padding: 0 3px 1px;
  }}
  .frac .den {{
    padding: 1px 3px 0;
  }}
  .asset-slot {{
    flex: 1;
    min-height: 145px;
    border: 1.2px dashed #C5D0DC;
    border-radius: 8px;
    background: linear-gradient(145deg, #FFFFFF 0%, #F1F5F8 100%);
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    color: #4E6E8E;
    font-size: 12.5px;
    text-align: center;
    padding: 10px;
  }}
  .connector-svg {{
    width: 74px;
    height: 100%;
    overflow: visible;
    z-index: 3;
  }}
  .footer-note {{
    font-size: 12px;
    color: #5A6470;
    display: flex;
    justify-content: space-between;
    padding-top: 8px;
    border-top: 1px solid #EAECEF;
  }}
  code {{
    white-space: nowrap;
    font-family: "Consolas", "Courier New", monospace;
    font-size: 12px;
    background: #FFFFFF;
    padding: 1px 4px;
    border-radius: 3px;
  }}
</style>
</head>
<body>
<div class="canvas">
  <div class="header-row">
    <div class="title-main">{title}</div>
    <div class="badge-pill">Coupled Modeling Architecture</div>
  </div>

  <div class="grid-stage">
    <!-- Column 1: Problem & Visual Physical Asset -->
    <div class="card">
      <div class="card-head">
        <div class="accent-bar" style="background:#4E6E8E;"></div>
        <div class="card-title">1. Physical Excitation &amp; Cutout Asset</div>
      </div>
      <div class="asset-slot">
        <!-- Replace with <img src="assets/component_cutout.png" style="max-height:135px;"> or inline SVG diagram -->
        <svg width="110" height="84" viewBox="0 0 110 84" aria-label="cutout schematic">
          <g id="asset-battery-module">
            <rect x="14" y="16" width="76" height="52" rx="8" fill="#4E6E8E" fill-opacity="0.16" stroke="#4E6E8E" stroke-width="2"/>
            <rect x="90" y="32" width="8" height="20" rx="2" fill="#4E6E8E"/>
            <path d="M 30 42 L 48 42 L 54 28 L 62 56 L 68 42 L 78 42" fill="none" stroke="#C86D5B" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"/>
          </g>
        </svg>
        <div style="margin-top:6px;font-weight:700;color:#3B5875;">3D Asset Slot (RGBA PNG / SVG)</div>
      </div>
      <div class="sub-box">
        <div class="sub-label" style="color:#4E6E8E;">Observable Inputs</div>
        Workload current <span class="math-i">I</span>(<span class="math-i">t</span>), ambient <span class="math-i">T</span><sub>amb</sub>, and battery SOH.
      </div>
    </div>

    <!-- Connector 1 -> 2 -->
    <svg class="connector-svg" viewBox="0 0 74 490">
      <defs>
        <marker id="arrowBlue" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto">
          <path d="M 0 1 L 9 5 L 0 9 z" fill="#4E6E8E"/>
        </marker>
      </defs>
      <g id="flow-arrows-stage1">
        <path d="M 2 180 C 32 180, 42 180, 68 180" fill="none" stroke="#4E6E8E" stroke-width="2.4" marker-end="url(#arrowBlue)"/>
        <path d="M 2 340 C 32 340, 42 320, 68 320" fill="none" stroke="#6D9A87" stroke-width="2.2" stroke-dasharray="5,4" marker-end="url(#arrowBlue)"/>
      </g>
    </svg>

    <!-- Column 2: Coupled Equations Core -->
    <div class="card">
      <div class="card-head">
        <div class="accent-bar" style="background:#C86D5B;"></div>
        <div class="card-title">2. Coupled Electro-Thermal Governing ODEs</div>
      </div>
      <div class="math-block">
        <span class="math-i">C</span><sub>th</sub>
        <span class="frac"><span class="num">d<span class="math-i">T</span><sub>c</sub></span><span class="den">d<span class="math-i">t</span></span></span>
        = <span class="math-i">I</span><sup>2</sup><span class="math-i">R</span><sub>0</sub>(<span class="math-i">T</span><sub>c</sub>, SOH) &minus;
        <span class="math-i">hA</span>(<span class="math-i">T</span><sub>c</sub> &minus; <span class="math-i">T</span><sub>amb</sub>)
      </div>
      <div class="math-block" style="border-left-color:#6D9A87;">
        <span class="frac"><span class="num">d(SOC)</span><span class="den">d<span class="math-i">t</span></span></span>
        = &minus;
        <span class="frac"><span class="num">&eta;(<span class="math-i">T</span><sub>c</sub>) &middot; <span class="math-i">I</span>(<span class="math-i">t</span>)</span><span class="den">3600 &middot; <span class="math-i">Q</span><sub>eff</sub>(SOH)</span></span>
      </div>
      <div class="sub-box">
        <div class="sub-label" style="color:#C86D5B;">Feedback Mechanism</div>
        Ohmic self-heating shifts polarization resistance <i>R</i><sub>0</sub>(<i>T</i><sub>c</sub>), triggering a sharp cold-to-warm saddle cliff near &minus;5&deg;C.
      </div>
    </div>

    <!-- Connector 2 -> 3 -->
    <svg class="connector-svg" viewBox="0 0 74 490">
      <defs>
        <marker id="arrowSage" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto">
          <path d="M 0 1 L 9 5 L 0 9 z" fill="#6D9A87"/>
        </marker>
      </defs>
      <g id="flow-arrows-stage2">
        <path d="M 2 245 C 32 245, 42 245, 68 245" fill="none" stroke="#6D9A87" stroke-width="2.6" marker-end="url(#arrowSage)"/>
      </g>
    </svg>

    <!-- Column 3: Empirical Verification & Action -->
    <div class="card">
      <div class="card-head">
        <div class="accent-bar" style="background:#6D9A87;"></div>
        <div class="card-title">3. Empirical Validation &amp; Playbook</div>
      </div>
      <div class="sub-box" style="border-left:3px solid #6D9A87;">
        <div class="sub-label" style="color:#3E6B58;">Point-to-Point Real Anchor</div>
        Validated against measured benchmark curves across ambient bands (RMSE &le; 1.8% SOC).
      </div>
      <div class="sub-box" style="border-left:3px solid #D9A462;">
        <div class="sub-label" style="color:#9A6C2E;">Actionable Decision Rule</div>
        Throttle non-critical refresh above peak thermal gradient and trigger reserve alert above cutoff slope.
      </div>
      <div class="sub-box" style="background:#EEF4F1;border-color:#C5D5D8;">
        <div class="sub-label" style="color:#3E6B58;">SVG Layering Ready</div>
        Every arrow sits in named SVG <code>&lt;g id="..."&gt;</code> groups for lossless PDF export or Figma refinement.
      </div>
    </div>
  </div>

  <div class="footer-note">
    <span>Source: Model formulation &amp; coupled solver pipeline</span>
    <span>Values synchronized from results.json</span>
  </div>
</div>
</body>
</html>
"""


def init_template(out_html: Path, title: str = "System Architecture & Coupled Mechanism") -> Path:
    out_html.parent.mkdir(parents=True, exist_ok=True)
    out_html.write_text(_default_html_template(title), encoding="utf-8")
    return out_html


_PLACEHOLDER_RE = re.compile(
    r"\{\{\s*([A-Za-z_][A-Za-z0-9_.\-\[\]]*)(?::([A-Za-z0-9_.,%+ -]+))?\s*\}\}"
)


def _resolve_key_path(data: Any, key_path: str) -> Any:
    """Resolve dotted JSON paths with optional integer indices (e.g. `pareto[0].cost`)."""
    if not key_path:
        raise KeyError("Empty placeholder key path")
    cur = data
    pos = 0
    n = len(key_path)
    while pos < n:
        if key_path[pos] == ".":
            pos += 1
            if pos >= n or key_path[pos] == ".":
                raise KeyError(key_path)
        if key_path[pos] == "[":
            end = key_path.find("]", pos + 1)
            if end == -1:
                raise KeyError(key_path)
            idx_str = key_path[pos + 1 : end]
            if not idx_str.isdigit():
                raise KeyError(key_path)
            idx = int(idx_str)
            if not isinstance(cur, (list, tuple)) or idx >= len(cur):
                raise KeyError(key_path)
            cur = cur[idx]
            pos = end + 1
        else:
            nxt_dot = key_path.find(".", pos)
            nxt_brk = key_path.find("[", pos)
            cuts = [c for c in (nxt_dot, nxt_brk) if c != -1]
            end = min(cuts) if cuts else n
            seg = key_path[pos:end]
            if not seg or not isinstance(cur, dict) or seg not in cur:
                raise KeyError(key_path)
            cur = cur[seg]
            pos = end
    return cur


def _round_sigfigs_decimal(val: float, sig_figs: int = 3) -> str:
    if not math.isfinite(val):
        return str(val)
    if val == 0.0:
        return "0"
    try:
        d = Decimal(str(val))
    except InvalidOperation:
        return f"{val:.{sig_figs}g}"
    exp = d.adjusted()
    if -3 <= exp < 5:
        shift = sig_figs - 1 - exp
        quant = Decimal(1).scaleb(-shift)
        q = d.quantize(quant, rounding=ROUND_HALF_UP)
        txt = f"{q:f}"
        if "." in txt:
            txt = txt.rstrip("0").rstrip(".")
        return "0" if txt in ("-0", "") else txt
    return f"{val:.{max(0, sig_figs - 1)}e}"


def _format_injected_value(
    val: Any,
    spec: str,
    precision_map: dict[str, Any] | None,
    key_path: str,
) -> str:
    """Format a scalar value from results.json using ROUND_HALF_UP and HTML escaping."""
    spec = (spec or "").strip()
    is_num = isinstance(val, (int, float)) and not isinstance(val, bool)
    pmap = precision_map if isinstance(precision_map, dict) else {}

    out: str
    if spec in ("", "smart"):
        prec_spec = pmap.get(key_path)
        if isinstance(val, bool) or val is None:
            out = str(val)
        elif is_num:
            if isinstance(prec_spec, str) and prec_spec.strip():
                return _format_injected_value(val, prec_spec.strip().lstrip(":"), {}, key_path)
            if isinstance(prec_spec, int) and not isinstance(prec_spec, bool) and prec_spec > 0:
                out = _round_sigfigs_decimal(float(val), prec_spec) if isinstance(val, float) else str(val)
            elif isinstance(val, int):
                out = str(val)
            else:
                out = _round_sigfigs_decimal(float(val), 3)
        else:
            out = str(val)
        return html_lib.escape(out, quote=False)

    m_pct_n = re.fullmatch(r"pct(\d+)", spec)
    m_pct_fmt = re.fullmatch(r"\.?(\d+)%", spec)
    m_fixed = re.fullmatch(r"(,?)\.(\d+)f", spec)

    if is_num and (m_pct_n or m_pct_fmt):
        if not math.isfinite(float(val)):
            out = str(val)
        else:
            d = Decimal(str(float(val)))
            if m_pct_n:
                ndigits = int(m_pct_n.group(1))
                if abs(d) <= Decimal("1"):
                    d = d * Decimal("100")
            else:
                assert m_pct_fmt is not None
                ndigits = int(m_pct_fmt.group(1))
                d = d * Decimal("100")
            quant = Decimal("1") if ndigits == 0 else Decimal(1).scaleb(-ndigits)
            q = d.quantize(quant, rounding=ROUND_HALF_UP)
            out = f"{q:f}%"
    elif is_num and m_fixed:
        if not math.isfinite(float(val)):
            out = str(val)
        else:
            has_comma = bool(m_fixed.group(1))
            ndigits = int(m_fixed.group(2))
            d = Decimal(str(float(val)))
            quant = Decimal("1") if ndigits == 0 else Decimal(1).scaleb(-ndigits)
            q = d.quantize(quant, rounding=ROUND_HALF_UP)
            out = f"{q:,f}" if has_comma else f"{q:f}"
    else:
        out = format(val, spec)

    return html_lib.escape(out, quote=False)


def inject_results_into_html(
    raw_html: str,
    results_path: Path,
    strict: bool = True,
) -> tuple[str, list[str], list[str]]:
    """Substitute `{{key}}` or `{{key:spec}}` placeholders in HTML using results.json."""
    if not results_path.is_file():
        raise FileNotFoundError(f"Results JSON not found: {results_path}")
    data = json.loads(results_path.read_text(encoding="utf-8"))
    precision_map = data.get("display_precision", {}) if isinstance(data, dict) else {}

    resolved_keys: list[str] = []
    missing_keys: list[str] = []

    def _repl(match: re.Match[str]) -> str:
        key_path = match.group(1)
        spec = match.group(2) or ""
        try:
            val = _resolve_key_path(data, key_path)
        except KeyError:
            missing_keys.append(key_path)
            return match.group(0)
        resolved_keys.append(key_path)
        return _format_injected_value(val, spec, precision_map, key_path)

    rendered = _PLACEHOLDER_RE.sub(_repl, raw_html)
    if missing_keys and strict:
        raise KeyError(f"Unresolved HTML placeholder(s) in template: {missing_keys}")
    return rendered, resolved_keys, missing_keys


def _inject_base_href(raw: str, base_dir: Path) -> str:
    """Inject `<base href=...>` so relative assets resolve when rendering temp HTML."""
    base_tag = f'<base href="{base_dir.resolve().as_uri()}/">\n'
    if "<base " in raw.lower():
        return raw
    m_head = re.search(r"<head[^>]*>", raw, flags=re.IGNORECASE)
    if m_head:
        idx = m_head.end()
        return raw[:idx] + "\n" + base_tag + raw[idx:]
    return base_tag + raw


def _build_pdf_html_wrapper(src_html: Path, width: int, height: int, work_dir: Path) -> Path:
    """Ensure @page size matches requested canvas dimensions for borderless 1-page vector PDF."""
    raw = src_html.read_text(encoding="utf-8")
    if "@page" not in raw:
        inject = f"<style>@page {{ size: {width}px {height}px; margin: 0; }}</style>\n"
        raw = raw.replace("</head>", inject + "</head>") if "</head>" in raw else (inject + raw)
    raw = _inject_base_href(raw, src_html.parent)
    tmp_html = work_dir / f"_render_{src_html.name}"
    tmp_html.write_text(raw, encoding="utf-8")
    return tmp_html


def _run_headless(browser: str, args: list[str]) -> subprocess.CompletedProcess[str]:
    base_flags = [
        "--disable-gpu",
        "--hide-scrollbars",
        "--allow-file-access-from-files",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-extensions",
    ]
    with tempfile.TemporaryDirectory(prefix="htmlfig_prof_") as prof_dir:
        cmd_new = [browser, "--headless=new", f"--user-data-dir={prof_dir}", *base_flags, *args]
        res = subprocess.run(cmd_new, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=45)
        if res.returncode == 0:
            return res
        cmd_old = [browser, "--headless", f"--user-data-dir={prof_dir}", *base_flags, *args]
        return subprocess.run(cmd_old, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=45)


def render_html(
    html_path: Path,
    out_png: Path | None = None,
    out_pdf: Path | None = None,
    width: int = 1200,
    height: int = 660,
    scale: float = 2.5,
    dpi: int = 300,
    virtual_time_ms: int = 1200,
    results_json: Path | None = None,
    strict_keys: bool = True,
) -> dict[str, Any]:
    if not html_path.is_file():
        raise FileNotFoundError(f"HTML source not found: {html_path}")
    if out_png is None and out_pdf is None:
        raise ValueError("Specify at least one of --out-png or --out-pdf")

    browser = find_browser()
    if browser is None:
        raise RuntimeError(
            "No headless Chromium/Edge/Chrome executable found. Set MATHFIG_BROWSER or install Edge/Chrome."
        )

    info: dict[str, Any] = {"browser": browser, "html": str(html_path)}

    with tempfile.TemporaryDirectory(prefix="htmlfig_render_") as td:
        td_path = Path(td)
        render_src = html_path
        if results_json is not None:
            raw_tpl = html_path.read_text(encoding="utf-8")
            injected, resolved_keys, missing_keys = inject_results_into_html(
                raw_tpl, results_json, strict=strict_keys
            )
            injected = _inject_base_href(injected, html_path.parent)
            render_src = td_path / html_path.name
            render_src.write_text(injected, encoding="utf-8")
            info["results_json"] = str(results_json)
            info["injected_keys"] = resolved_keys
            if missing_keys:
                info["missing_keys"] = missing_keys

        uri = render_src.resolve().as_uri()

        if out_png is not None:
            out_png.parent.mkdir(parents=True, exist_ok=True)
            res = _run_headless(
                browser,
                [
                    f"--force-device-scale-factor={scale}",
                    f"--window-size={width},{height}",
                    f"--virtual-time-budget={virtual_time_ms}",
                    f"--screenshot={out_png.resolve()}",
                    uri,
                ],
            )
            if res.returncode != 0 or not out_png.is_file() or out_png.stat().st_size == 0:
                raise RuntimeError(f"Headless PNG render failed (rc={res.returncode}): {res.stderr[-500:]}")
            # Stamp explicit DPI metadata cleanly using Pillow so figure_qa.py verifies >= 300 DPI
            with Image.open(out_png) as im:
                rgb = im.convert("RGB")
                rgb.save(out_png, format="PNG", dpi=(dpi, dpi))
                info["png"] = str(out_png)
                info["png_size"] = [rgb.width, rgb.height]
                info["dpi"] = dpi

        if out_pdf is not None:
            out_pdf.parent.mkdir(parents=True, exist_ok=True)
            pdf_dir = td_path / "pdf"
            pdf_dir.mkdir(parents=True, exist_ok=True)
            wrapped = _build_pdf_html_wrapper(render_src, width, height, pdf_dir)
            # Ensure base points to original html_path.parent if render_src already had base or was copied
            res = _run_headless(
                browser,
                [
                    "--no-pdf-header-footer",
                    f"--window-size={width},{height}",
                    f"--virtual-time-budget={virtual_time_ms}",
                    f"--print-to-pdf={out_pdf.resolve()}",
                    wrapped.resolve().as_uri(),
                ],
            )
            if res.returncode != 0 or not out_pdf.is_file() or out_pdf.stat().st_size == 0:
                raise RuntimeError(f"Headless PDF render failed (rc={res.returncode}): {res.stderr[-500:]}")
            info["pdf"] = str(out_pdf)

    return info


def self_test() -> int:
    browser = find_browser()
    assert browser is not None, "Expected local Edge/Chrome browser for render_html_figure.py self-test"
    with tempfile.TemporaryDirectory(prefix="render_htmlfig_test_") as td:
        tdir = Path(td)
        html_p = tdir / "arch.html"
        png_p = tdir / "arch.png"
        pdf_p = tdir / "arch.pdf"

        init_template(html_p)
        tpl_text = html_p.read_text(encoding="utf-8")
        assert "Morandi" not in tpl_text, "Default template leaked internal palette token 'Morandi'"
        assert "render_html_figure.py" not in tpl_text, "Default template leaked script filename"

        info = render_html(html_p, out_png=png_p, out_pdf=pdf_p, width=1200, height=660, scale=2.0, dpi=300)
        assert png_p.is_file() and png_p.stat().st_size > 10_000, info
        with Image.open(png_p) as im:
            dpi_val = round(im.info.get("dpi", (72, 72))[0])
            assert dpi_val >= 300, im.info
            arr_std = float(im.convert("L").getextrema()[1] - im.convert("L").getextrema()[0])
            assert arr_std > 20, "Rendered PNG looks blank!"
        assert pdf_p.is_file() and pdf_p.read_bytes().startswith(b"%PDF"), info

        # Test {{key}} injection from results.json without mutating source HTML
        results_p = tdir / "results.json"
        results_p.write_text(
            json.dumps(
                {
                    "summary": {"rmse": 1.454, "rate": 0.9455},
                    "items": [{"name": "Alpha <Core>"}],
                }
            ),
            encoding="utf-8",
        )
        tpl_p = tdir / "metrics_tpl.html"
        tpl_raw = tpl_text.replace(
            "Coupled Modeling Architecture",
            "RMSE={{summary.rmse:.2f}}, Rate={{summary.rate:pct1}}, Top={{items[0].name}}",
        )
        tpl_p.write_text(tpl_raw, encoding="utf-8")

        injected_html, resolved, missing = inject_results_into_html(tpl_raw, results_p, strict=True)
        assert not missing, missing
        assert resolved == ["summary.rmse", "summary.rate", "items[0].name"], resolved
        assert "RMSE=1.45, Rate=94.6%, Top=Alpha &lt;Core&gt;" in injected_html, injected_html

        png_inj = tdir / "metrics.png"
        pdf_inj = tdir / "metrics.pdf"
        info_inj = render_html(
            tpl_p,
            out_png=png_inj,
            out_pdf=pdf_inj,
            width=1200,
            height=660,
            scale=2.0,
            dpi=300,
            results_json=results_p,
            strict_keys=True,
        )
        assert png_inj.is_file() and png_inj.stat().st_size > 10_000, info_inj
        assert pdf_inj.is_file() and pdf_inj.read_bytes().startswith(b"%PDF"), info_inj
        assert tpl_p.read_text(encoding="utf-8") == tpl_raw, "Source template was mutated!"

        try:
            inject_results_into_html("<span>{{does.not.exist}}</span>", results_p, strict=True)
            raise AssertionError("Expected KeyError for missing placeholder in strict mode")
        except KeyError:
            pass

    print(
        f"[SELF-TEST] PASS render_html_figure (browser={Path(browser).name}, "
        "300 DPI PNG + vector PDF + {{key}} injection)"
    )
    return 0


def main() -> int:
    if "--self-test" in sys.argv:
        return self_test()

    ap = argparse.ArgumentParser(description="HTML + SVG + Math 双层向量/高清图渲染器")
    ap.add_argument("--init-template", default="", help="生成学术架构 HTML+SVG 起手模板路径")
    ap.add_argument("--title", default="System Architecture & Coupled Mechanism", help="模板标题")
    ap.add_argument("--html", default="", help="输入 HTML 文件路径")
    ap.add_argument("--results", default="", help="可选 results.json 路径，用于在渲染时注入 {{key}} 占位符")
    ap.add_argument("--allow-missing-keys", action="store_true", help="允许模板存在未解析的 {{key}} 占位符而不报错")
    ap.add_argument("--out-png", default="", help="输出高清 PNG 路径")
    ap.add_argument("--out-pdf", default="", help="输出矢量 PDF 路径")
    ap.add_argument("--width", type=int, default=1200, help="逻辑画布宽度 px（默认 1200）")
    ap.add_argument("--height", type=int, default=660, help="逻辑画布高度 px（默认 660）")
    ap.add_argument("--scale", type=float, default=2.5, help="高分缩放倍率（默认 2.5 -> 3000px 宽）")
    ap.add_argument("--dpi", type=int, default=300, help="PNG DPI 元数据（默认 300）")
    ap.add_argument("--virtual-time-ms", type=int, default=1200, help="渲染等待毫秒（默认 1200）")
    ap.add_argument("--self-test", action="store_true", help="运行内置自检")
    args = ap.parse_args()

    if args.init_template and not args.html:
        out_h = init_template(Path(args.init_template), title=args.title)
        print(f"[render_html_figure] 已生成模板: {out_h}")
        return 0

    if not args.html:
        ap.error("请提供 --html（或 --init-template / --self-test）")

    if args.init_template and not Path(args.html).exists():
        init_template(Path(args.html), title=args.title)

    info = render_html(
        Path(args.html),
        out_png=Path(args.out_png) if args.out_png else None,
        out_pdf=Path(args.out_pdf) if args.out_pdf else None,
        width=args.width,
        height=args.height,
        scale=args.scale,
        dpi=args.dpi,
        virtual_time_ms=args.virtual_time_ms,
        results_json=Path(args.results) if args.results else None,
        strict_keys=not args.allow_missing_keys,
    )
    print(json.dumps(info, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
