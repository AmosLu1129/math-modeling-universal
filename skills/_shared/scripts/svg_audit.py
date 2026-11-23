#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""SVG / HTML 图件「几何 + 配色」程序化审计（非 matplotlib 通路专用）。

背景（2026-09-10 事故沉淀）：
    matplotlib 图有 `layout_qa.py` 把遮挡/裁切算成几何事实，但**手写 SVG、
    drawio 导出、PPT 截图、AI 基底图**这条通路此前只有「渲染 + vision 读图」，
    于是比例偏差、元素遮挡、配色混乱只能靠肉眼发现 —— 实测 vision 对
    「是否真的重叠 / 贴边 / 对比度不足」判断不可靠（多次 PASS 但实际违规）。

本脚本把那些「肉眼最容易漏」的视觉缺陷算成数值断言：
  - OVERFLOW : 内容出血 / 越出画布
  - TOUCH    : 内容贴边（可读性风险，转 PDF 时易被裁）
  - COLLIDE  : 文本互叠
  - OCCLUDE  : 文本被其它图形遮挡（含近似色遮挡）
  - CONTRAST : 文本与背景对比度低于阈值（WCAG）
  - COLLAPSE : 两个系列色在灰度或色盲模拟下无法区分
  - MERGE    : 配色过于接近（接近同色，可能违背语义固定）
  - TINY     : 最终投放尺寸下字号低于下限（按 pt 折算，不看屏幕缩放）

几何取自 Chrome 的 getBoundingClientRect —— 与浏览器最终排版一致，
比读 SVG 源码自己算坐标可靠（transform/text-anchor/字体度量都被正确处理）。

用法：
    # 审计 + 出 PNG（推荐：审计与回看用同一份渲染）
    python svg_audit.py work/figures/mech_1.svg --png work/figures/mech_1.png --dpi 300

    # 只审计，不出图
    python svg_audit.py probe.html --json work/figures/mech_1.audit.json

    # 阈值可调（默认 competition 档）
    python svg_audit.py fig.svg --thresholds journal
    python svg_audit.py fig.svg --min-pt 5 --min-contrast 4.5 --min-color-dist 40

    # 自检（12 项，改动本脚本后必跑）
    python svg_audit.py --self-test

退出码：0 = 无 FAIL；1 = 有 FAIL（禁止交付）；2 = 用法/环境错误。

运行要求：Python ≥ 3.9，**标准库零依赖**（CDP/WebSocket 客户端为自实现，
不需要 websocket-client / Playwright / node）；PIL 仅用于给 PNG 写 DPI 元数据，缺失时自动跳过。
几何面必须 Chrome/Chromium（`--chrome` 或 `CHROME_PATH` 可指定）；Chrome 缺失时降级为
「仅渲染 PNG 供读图」并打印显式 WARN，不静默放过。
"""

from __future__ import annotations

import argparse
import base64
import json
import math
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

# --------------------------------------------------------------------------
# 阈值档位（用户可切换的技术通路之一）
# --------------------------------------------------------------------------
THRESHOLDS = {
    # 竞赛论文：投放到论文里的最终尺寸
    "competition": {"min_pt": 6.0, "min_contrast": 4.5, "min_color_dist": 30,
                    "edge_tol_px": 1.0, "print_width_mm": 160.0},
    # 期刊出版：更严的字号下限与色距
    "journal": {"min_pt": 5.0, "min_contrast": 4.5, "min_color_dist": 45,
                "edge_tol_px": 1.0, "print_width_mm": 180.0},
    # 屏幕/汇报：只拦硬伤
    "screen": {"min_pt": 8.0, "min_contrast": 3.0, "min_color_dist": 20,
               "edge_tol_px": 1.0, "print_width_mm": 240.0},
}

CSS_COLORS = {
    "white": (255, 255, 255), "black": (0, 0, 0), "red": (255, 0, 0),
    "green": (0, 128, 0), "blue": (0, 0, 255), "gray": (128, 128, 128),
    "grey": (128, 128, 128), "lightgray": (211, 211, 211), "lightgrey": (211, 211, 211),
    "darkgray": (169, 169, 169), "silver": (192, 192, 192), "orange": (255, 165, 0),
    "purple": (128, 0, 128), "navy": (0, 0, 128), "teal": (0, 128, 128),
    "lightblue": (173, 216, 230), "whitesmoke": (245, 245, 245),
    "none": None, "transparent": None,
}

# 色盲模拟矩阵（Viénot-Brettel-Mollon 线性近似，sRGB 空间）
CVD_MATRIX = {
    "deuteranopia": ((0.625, 0.375, 0.0), (0.7, 0.3, 0.0), (0.0, 0.3, 0.7)),
    "protanopia": ((0.567, 0.433, 0.0), (0.558, 0.442, 0.0), (0.0, 0.242, 0.758)),
}


# --------------------------------------------------------------------------
# 工具函数
# --------------------------------------------------------------------------
def _log(level: str, msg: str) -> None:
    print(f"[{level}] {msg}", flush=True)


def parse_color(c) -> tuple | None:
    """CSS 颜色 -> (r,g,b,a)；无法解析或全透明返回 None。"""
    if c is None:
        return None
    c = str(c).strip().lower()
    if c in ("", "none", "transparent", "currentcolor", "inherit"):
        return None
    if c in CSS_COLORS:
        rgb = CSS_COLORS[c]
        return None if rgb is None else (*rgb, 1.0)
    m = re.match(r"^#([0-9a-f]{3,8})$", c)
    if m:
        h = m.group(1)
        if len(h) == 3:
            return (int(h[0] * 2, 16), int(h[1] * 2, 16), int(h[2] * 2, 16), 1.0)
        if len(h) == 4:
            return (int(h[0] * 2, 16), int(h[1] * 2, 16), int(h[2] * 2, 16),
                    int(h[3] * 2, 16) / 255.0)
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
        a = int(h[6:8], 16) / 255.0 if len(h) == 8 else 1.0
        return (r, g, b, a)
    m = re.match(r"^rgba?\(([^)]+)\)$", c)
    if m:
        parts = [p for p in re.split(r"[,\s/]+", m.group(1).strip()) if p]
        try:
            vals = []
            for p in parts[:3]:
                vals.append(float(p[:-1]) * 255.0 / 100.0 if p.endswith("%") else float(p))
            a = 1.0
            if len(parts) >= 4:
                p = parts[3]
                a = float(p[:-1]) / 100.0 if p.endswith("%") else float(p)
            return (int(round(vals[0])), int(round(vals[1])), int(round(vals[2])), a)
        except Exception:
            return None
    return None


def _rel_lum(rgb) -> float:
    def f(v: float) -> float:
        v = v / 255.0
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = (f(x) for x in rgb[:3])
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(rgb1, rgb2) -> float:
    l1, l2 = _rel_lum(rgb1), _rel_lum(rgb2)
    hi, lo = max(l1, l2), min(l1, l2)
    return (hi + 0.05) / (lo + 0.05)


def color_distance(rgb1, rgb2) -> float:
    """带亮度加权的 RGB 欧氏距离（近似感知差，0-765 量级）。"""
    dr, dg, db = (rgb1[i] - rgb2[i] for i in range(3))
    return math.sqrt(2 * dr * dr + 4 * dg * dg + 3 * db * db)


def to_grayscale(rgb):
    """灰度亮度：必须用 Rec.709/WCAG 系数。
    （用 NTSC 的 0.299/0.587/0.114 会算错蓝/红分量的可分性，实测导致 COLLAPSE 漏报。）"""
    y = 0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2]
    return (y, y, y)


def simulate_cvd(rgb, kind: str):
    m = CVD_MATRIX[kind]
    out = []
    for row in m:
        v = sum(row[i] * rgb[i] for i in range(3))
        out.append(max(0.0, min(255.0, v)))
    return tuple(out)


def composite(fg, bg):
    """把带 alpha 的前景合成到不透明背景上。"""
    a = fg[3] if len(fg) > 3 else 1.0
    return tuple(int(round(fg[i] * a + bg[i] * (1 - a))) for i in range(3))


def find_chrome() -> str | None:
    """按优先级探测 Chrome/Chromium/Edge（用户可经 --chrome 覆盖）。"""
    env = os.environ.get("CHROME_PATH") or os.environ.get("MATHFIG_CHROME")
    cands = [env] if env else []
    cands += [
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Chromium.app/Contents/MacOS/Chromium",
        "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
        "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
    ]
    if sys.platform == "win32":
        local_app = os.environ.get("LOCALAPPDATA", "")
        prog_files = os.environ.get("ProgramFiles", r"C:\Program Files")
        prog_files_x86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
        cands += [
            os.path.join(prog_files, "Google", "Chrome", "Application", "chrome.exe"),
            os.path.join(prog_files_x86, "Google", "Chrome", "Application", "chrome.exe"),
            os.path.join(local_app, "Google", "Chrome", "Application", "chrome.exe"),
            os.path.join(prog_files, "Microsoft", "Edge", "Application", "msedge.exe"),
            os.path.join(prog_files_x86, "Microsoft", "Edge", "Application", "msedge.exe"),
            os.path.join(local_app, "Microsoft", "Edge", "Application", "msedge.exe"),
            os.path.join(prog_files, "BraveSoftware", "Brave-Browser", "Application", "brave.exe"),
        ]
    for c in cands:
        if c and Path(c).exists():
            return c
    for name in ("google-chrome", "chromium", "chromium-browser", "chrome", "msedge"):
        p = shutil.which(name)
        if p:
            return p
    return None


# --------------------------------------------------------------------------
# 页内采集器（注入到被测 SVG/HTML；本段 JS 只做采集，不下结论）
# --------------------------------------------------------------------------
HARVEST_JS = r"""
(() => {
  // 裸 .svg 文件在 Chrome 里的真实结构（2026-09-10 实测）：documentElement 就是 <svg>，
  // 且 document.body 为 null（只能读不能写：给 SVG 塞 <body> 不生效）。因此全程不得依赖
  // document.body 存在或 .style 可写，否则抛 TypeError。
  const safeBg = el => {
    try { return el ? getComputedStyle(el).backgroundColor : "rgba(0, 0, 0, 0)"; }
    catch (e) { return "rgba(0, 0, 0, 0)"; }   // documentElement 为 SVG 时 getComputedStyle 会抛
  };
  let svg = document.querySelector("svg");
  if (!svg) {
    if (!document.body) return {error: "document 中找不到 <svg> 元素"};
    const holder = document.createElement("div");
    holder.style.cssText = "position:absolute;left:0;top:0;margin:0;padding:0";
    holder.innerHTML = document.body.innerHTML || "";
    document.body.innerHTML = "";
    document.body.appendChild(holder);
    svg = holder.querySelector("svg");
    if (!svg) return {error: "document 中找不到 <svg> 元素"};
  }
  if (document.body) document.body.style.margin = "0";

  const vbAttr = svg.getAttribute("viewBox");
  let origin = {x: 0, y: 0}, canvas = null;
  const r0 = svg.getBoundingClientRect();
  if (vbAttr) {
    const p = vbAttr.trim().split(/[\s,]+/).map(Number);
    if (p.length === 4 && p.every(v => isFinite(v))) canvas = {x: p[0], y: p[1], w: p[2], h: p[3]};
  }
  if (!canvas) canvas = {x: 0, y: 0, w: r0.width, h: r0.height};
  const scale = r0.width > 0 && canvas.w > 0 ? r0.width / canvas.w : 1;
  origin = {x: r0.left, y: r0.top};

  // 根元素 width/height 属性（带单位）→ 画布的自然物理尺寸。
  // matplotlib 写出 width="526.8pt" 时「1 用户单位 = 1pt」；手写 SVG 的
  // width="600"（无单位）按 CSS 约定是「1 用户单位 = 1px = 0.75pt」。
  // 字号折算必须基于画布自身名义尺寸，不能用论文栏宽的档位默认值反推。
  const natural = (function () {
    const mmPerPx = 25.4 / 96, mmPerPt = 25.4 / 72;
    function toMm(attr) {
      if (!attr) return null;
      const m = String(attr).trim().match(/^([0-9]*\.?[0-9]+)\s*(px|pt|mm|cm|in)?$/i);
      if (!m) return null;
      const v = parseFloat(m[1]);
      if (!isFinite(v) || v <= 0) return null;
      switch ((m[2] || "px").toLowerCase()) {
        case "pt": return v * mmPerPt;
        case "mm": return v;
        case "cm": return v * 10;
        case "in": return v * 25.4;
        default: return v * mmPerPx;
      }
    }
    return {w_mm: toMm(svg.getAttribute("width")), h_mm: toMm(svg.getAttribute("height"))};
  })();

  const TAGS = "text,rect,circle,ellipse,line,polygon,polyline,path,image,foreignObject";
  const els = [...svg.querySelectorAll(TAGS)];
  const nodes = [];
  const parents = new Map();
  els.forEach((el, i) => { el.__ai = i; });
  els.forEach(el => {
    let p = el.parentElement;
    while (p && p !== svg && p.tagName.toLowerCase() === "g") {
      if (p.__ai !== undefined) parents.set(el.__ai, p.__ai);
      p = p.parentElement;
    }
  });

  const toCanvas = b => ({
    x: +((b.left - origin.x) / scale).toFixed(2),
    y: +((b.top - origin.y) / scale).toFixed(2),
    w: +(b.width / scale).toFixed(2),
    h: +(b.height / scale).toFixed(2)
  });

  // 预先算好每个元素在 SVG 文档中的祖先集合（供"文字下方遮挡色"推断用），
  // 同时避免对每个元素重复调用 getComputedStyle 做 DOM 上溯。
  const ancestorIds = {};
  for (const [child, parent] of parents) {
    const chain = [];
    const seen = new Set();
    let cur = parent;
    while (cur !== undefined && cur !== null && !seen.has(cur)) {   // 防环
      seen.add(cur);
      chain.push(cur);
      cur = parents.get(cur);   // parents 是 Map，此处在采集循环内仍可用
    }
    ancestorIds[child] = chain;
  }

  els.forEach(el => {
    const i = el.__ai;
    const tag = el.tagName.toLowerCase();
    const cs = getComputedStyle(el);
    const b = el.getBoundingClientRect();
    const n = {
      i, tag,
      id: el.id || "",
      cls: el.getAttribute("class") || "",
      label: (el.textContent || "").replace(/\s+/g, " ").trim().slice(0, 60),
      parts: tag === "text" ? [...el.querySelectorAll("tspan")].map(t => t.textContent) : [],
      box: toCanvas(b),
      raw: {x: b.x, y: b.y, w: b.width, h: b.height},
      ancestors: ancestorIds[i] || [],
      fill: null, stroke: null, opacity: 1, visible: true,
      fontSizePx: null, fontWeight: null, nChars: null
    };
    n.opacity = parseFloat(cs.opacity) || 1;
    n.visible = cs.visibility !== "hidden" && cs.display !== "none";
    if (tag === "text") {
      n.fill = cs.fill;
      n.fillOpacity = parseFloat(cs.fillOpacity);
      n.fontSizePx = parseFloat(cs.fontSize);
      n.fontWeight = cs.fontWeight;
      n.anchor = cs.textAnchor;
      n.nChars = (el.textContent || "").replace(/\s+/g, " ").trim().length;
    } else if (["rect", "circle", "ellipse", "polygon", "polyline"].includes(tag)) {
      n.fill = cs.fill; n.fillOpacity = parseFloat(cs.fillOpacity);
      n.stroke = cs.stroke; n.strokeOpacity = parseFloat(cs.strokeOpacity);
      // 注意：不能用 el.hasAttribute("fill") 判断有无填充 —— 造型元素常从父级
      // <g fill="..."> 继承填充（实测踩坑：整组柱子被判成"无填充"，遮挡全部漏检）。
      n.hasFill = cs.fill && cs.fill !== "none";
      n.hasStroke = cs.stroke && cs.stroke !== "none";
    } else if (["line", "path"].includes(tag)) {
      n.stroke = cs.stroke; n.fill = cs.fill;
      n.strokeOpacity = parseFloat(cs.strokeOpacity); n.fillOpacity = parseFloat(cs.fillOpacity);
      n.hasStroke = cs.stroke && cs.stroke !== "none";
      n.hasFill = cs.fill && cs.fill !== "none";
      const len = (el.getTotalLength && tag === "path") ? el.getTotalLength() : 0;
      const rb = (() => { try { return el.getBBox(); } catch (e) { return {width: 0, height: 0}; } })();
      n.thin = (rb.width <= 2 || rb.height <= 2) || (tag === "line");
      n.pathLen = len;
    } else if (tag === "image") {
      n.hasFill = true;
    }
    nodes.push(n);
  });

  const insideOwn = (c, t) => (t.ancestors || []).includes(c.i);

  const dist2 = (a, b) => Math.abs(a.i - b.i);

  const rgbOf = raw => {
    const m = /rgba?\(([^)]+)\)/.exec(raw || "");
    if (!m) return null;
    const p = m[1].split(/[,\s/]+/).filter(Boolean).map(Number);
    if (p.length < 3 || p.some(v => !isFinite(v))) return null;
    const a = p.length > 3 && isFinite(p[3]) ? p[3] : 1;
    if (a <= 0.02) return null;
    return [p[0], p[1], p[2], a];
  };

  // 判断某形状的可见内容是否覆盖画布坐标 (cx, cy)：
  // 用 getBoundingClientRect 的紧包围盒（对 path/线/文字是实际笔画范围），再反算回该元素自身像素系。
  const coversPoint = (c, cx, cy) => {
    const b = c.raw;
    if (!b || b.w <= 0 || b.h <= 0) return false;
    const px = origin.x + cx * scale, py = origin.y + cy * scale;
    const tol = 1.0;
    return px >= b.x - tol && px <= b.x + b.w + tol && py >= b.y - tol && py <= b.y + b.h + tol;
  };

  // 参与"文字背景/遮挡"判定的图元：
  //  ① 有填充的造型元素（色块/柱/热力图单元）—— 用包围盒判定
  //  ② 线状元素（line/polyline/path）—— 必须按**真实线段几何**判定：
  //     长折线的紧包围盒会盖住整片区域，用包围盒会把整张图误判成被线覆盖（实测踩坑）。
  const fillShapes = nodes.filter(n =>
    ["rect", "circle", "ellipse", "polygon", "image"].includes(n.tag) && n.hasFill);

  const segsOf = el => {
    const out = [];
    const tag = el.tagName.toLowerCase();
    const num = v => { const x = parseFloat(v); return isFinite(x) ? x : 0; };
    if (tag === "line") {
      out.push([num(el.getAttribute("x1")), num(el.getAttribute("y1")),
                num(el.getAttribute("x2")), num(el.getAttribute("y2"))]);
    } else if (tag === "polyline" || tag === "polygon") {
      const pts = (el.getAttribute("points") || "").trim().split(/[\s,]+/).map(Number).filter(isFinite);
      for (let k = 0; k + 3 < pts.length; k += 2) out.push([pts[k], pts[k + 1], pts[k + 2], pts[k + 3]]);
    } else if (tag === "path" && el.getTotalLength) {
      let total = 0;
      try { total = el.getTotalLength(); } catch (e) { total = 0; }
      const N = Math.max(2, Math.min(200, Math.ceil(total / 6)));
      let prev = null;
      for (let k = 0; k <= N; k++) {
        const pt = el.getPointAtLength(total * k / N);
        if (prev) out.push([prev.x, prev.y, pt.x, pt.y]);
        prev = pt;
      }
    }
    return out;
  };
  const strokes = [];
  for (const n of nodes) {
    if (!["line", "polyline", "polygon", "path"].includes(n.tag)) continue;
    if (!n.hasStroke || !n.visible) continue;
    const el = els[n.i];
    if (!el) continue;
    for (const sg of segsOf(el)) {
      strokes.push({owner: n.i, seg: sg, box: n.raw, color: n.stroke, label: n.label});
    }
  }
  const distSeg = (px, py, sg) => {
    const [x1, y1, x2, y2] = sg;
    const dx = x2 - x1, dy = y2 - y1;
    const L2 = dx * dx + dy * dy;
    let t = L2 > 0 ? ((px - x1) * dx + (py - y1) * dy) / L2 : 0;
    t = Math.max(0, Math.min(1, t));
    const qx = x1 + t * dx, qy = y1 + t * dy;
    return Math.hypot(px - qx, py - qy);
  };
  const strokeOwnerOf = (cx, cy, t, tol) => {
    // 取"离文字最近（=绘制次序最靠上）"的那条线的颜色
    let best = null;
    for (const s of strokes) {
      if (insideOwn({i: s.owner}, t)) continue;
      const px = origin.x + cx * scale, py = origin.y + cy * scale;
      if (s.box && (px < s.box.x - tol || px > s.box.x + s.box.w + tol ||
                    py < s.box.y - tol || py > s.box.y + s.box.h + tol)) continue;
      if (distSeg(px, py, s.seg) <= tol) {
        // 取离文字最近的线（= 绘制次序最靠上）；注意必须先判 best 为空，
        // 否则首次命中就会读 best.owner 抛 TypeError 并静默退化为"无线遮挡"（实测踩坑）。
        if (best === null || dist2({i: s.owner}, t) < dist2({i: best.owner}, t)) best = s;
      }
    }
    return best;
  };
  for (const t of nodes) {
    if (t.tag !== "text") continue;
    if (!t.fill || !t.box || t.box.w <= 0 || t.box.h <= 0) continue;
    // 只采样文字墨迹包围盒内部（小内缩），避免把字盒外空白当成"文字背景"
    const ins = 0.10;
    const x0 = t.box.x + t.box.w * ins, x1 = t.box.x + t.box.w * (1 - ins);
    const y0 = t.box.y + t.box.h * ins, y1 = t.box.y + t.box.h * (1 - ins);
    const hits = [];
    const N = 4;
    for (let a = 0; a <= N; a++) {
      for (let b2 = 0; b2 <= N; b2++) {
        const cx = x0 + (x1 - x0) * (a / N), cy = y0 + (y1 - y0) * (b2 / N);
        let top = null;
        for (const c of fillShapes) {
          if (insideOwn(c, t)) continue;             // 自己的祖先组不算背景
          if (!coversPoint(c, cx, cy)) continue;
          if (top === null || dist2(c, t) < dist2(top, t)) top = c;
        }
        // 线优先于色块：线若穿过文字，无论下面是色块还是白底都必须报出来
        const strokeHit = strokeOwnerOf(cx, cy, t, Math.max(2.5, 1.5 * scale));
        if (strokeHit) {
          hits.push({bg: strokeHit.color, kind: "stroke", opaque: true, under: strokeHit.label});
        } else if (top) {
          hits.push({
            bg: top.fill, kind: "fill",
            opaque: (rgbOf(top.fill)?.[3] ?? 1) >= 0.98,
            under: top.label
          });
        } else {
          hits.push({bg: null, kind: "page", opaque: false, under: ""});
        }
      }
    }
    t.samples = hits;
    // 按出现次数排序的背景色列表（供 Python 侧对"占比够大"的背景分别校验对比度；
    // 细线穿过文字由下方 OCCLUDE 专项判定，不把 stroke 混入填充背景统计）
    const tally = {};
    const nonStrokeHits = hits.filter(h => h.kind !== "stroke");
    for (const h of (nonStrokeHits.length ? nonStrokeHits : hits)) {
      const key = h.bg || "__page__";
      tally[key] = (tally[key] || 0) + 1;
    }
    t.bgDistinct = Object.keys(tally)
      .map(k => ({color: k === "__page__" ? null : k, count: tally[k]}))
      .sort((x, y) => y.count - x.count);
  }

  let bodyBg = safeBg(document.body);
  const pageBg = safeBg(document.documentElement);
  if (bodyBg === "rgba(0, 0, 0, 0)" && pageBg !== "rgba(0, 0, 0, 0)") bodyBg = pageBg;
  if (bodyBg === "rgba(0, 0, 0, 0)") {
    const svgBg = safeBg(svg);
    if (svgBg !== "rgba(0, 0, 0, 0)") bodyBg = svgBg;
  }
  return {
    viewBox: canvas, scale, bodyBg, natural,
    docSize: {w: r0.width, h: r0.height}, nodes, parents: [...parents.entries()]
  };
})()
"""


# --------------------------------------------------------------------------
# Chrome 渲染 + 采集
# --------------------------------------------------------------------------
def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _cdp(ws_url: str, calls: list, timeout: float = 60.0) -> list:
    """极简 CDP 客户端（零依赖：标准库实现 WebSocket，不依赖 websocket-client）。

    按顺序发命令，返回结果列表；CDP 响应可能被分片，这里做完整重组。
    """
    import struct
    host, port, path = _parse_ws_url(ws_url)
    sock = socket.create_connection((host, port), timeout=timeout)
    try:
        key = base64.b64encode(os.urandom(16)).decode()
        req = (f"GET {path} HTTP/1.1\r\nHost: {host}:{port}\r\nUpgrade: websocket\r\n"
               f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\n"
               f"Sec-WebSocket-Version: 13\r\n\r\n")
        sock.sendall(req.encode())
        buf = b""
        while b"\r\n\r\n" not in buf:
            chunk = sock.recv(4096)
            if not chunk:
                raise RuntimeError("WebSocket 握手期间连接被关闭")
            buf += chunk
        if b"101" not in buf.split(b"\r\n")[0]:
            raise RuntimeError(f"WebSocket 握手失败: {buf.split(chr(13).encode())[0]!r}")

        def send_text(payload: str) -> None:
            data = payload.encode()
            mask = os.urandom(4)
            n = len(data)
            header = bytearray([0x81])
            if n < 126:
                header.append(0x80 | n)
            elif n < (1 << 16):
                header.append(0x80 | 126)
                header += struct.pack(">H", n)
            else:
                header.append(0x80 | 127)
                header += struct.pack(">Q", n)
            header += mask
            masked = bytes(b ^ mask[i % 4] for i, b in enumerate(data))
            sock.sendall(bytes(header) + masked)

        def recv_exact(n: int) -> bytes:
            out = b""
            while len(out) < n:
                chunk = sock.recv(n - len(out))
                if not chunk:
                    raise RuntimeError("WebSocket 连接提前关闭")
                out += chunk
            return out

        def recv_message() -> str:
            while True:
                b0, b1 = recv_exact(2)
                opcode = b0 & 0x0F
                masked = bool(b1 & 0x80)
                ln = b1 & 0x7F
                if ln == 126:
                    ln = struct.unpack(">H", recv_exact(2))[0]
                elif ln == 127:
                    ln = struct.unpack(">Q", recv_exact(8))[0]
                mkey = recv_exact(4) if masked else b""
                payload = recv_exact(ln) if ln else b""
                if masked:
                    payload = bytes(b ^ mkey[i % 4] for i, b in enumerate(payload))
                if opcode == 0x9:  # ping -> pong
                    sock.sendall(b"\x8a\x80" + os.urandom(4))
                    continue
                if opcode == 0xA:  # pong
                    continue
                if opcode == 0x8:
                    raise RuntimeError("WebSocket 被对端关闭")
                if opcode in (0x1, 0x0):
                    data = payload
                    while not (b0 & 0x80):  # 继续收后续分片
                        b0, b1 = recv_exact(2)
                        ln = b1 & 0x7F
                        if ln == 126:
                            ln = struct.unpack(">H", recv_exact(2))[0]
                        elif ln == 127:
                            ln = struct.unpack(">Q", recv_exact(8))[0]
                        if b1 & 0x80:
                            mk = recv_exact(4)
                            seg = recv_exact(ln)
                            seg = bytes(b ^ mk[i % 4] for i, b in enumerate(seg))
                        else:
                            seg = recv_exact(ln)
                        data += seg
                    return data.decode("utf-8", "replace")

        out = []
        for i, (method, params) in enumerate(calls, start=1):
            send_text(json.dumps({"id": i, "method": method, "params": params or {}}))
            deadline = time.time() + timeout
            while True:
                if time.time() > deadline:
                    raise TimeoutError(f"CDP 超时: {method}")
                msg = json.loads(recv_message())
                if msg.get("id") == i:
                    if "error" in msg:
                        raise RuntimeError(f"CDP {method} 失败: {msg['error']}")
                    out.append(msg.get("result", {}))
                    break
        return out
    except socket.timeout as e:
        raise TimeoutError(f"CDP socket 超时: {e}")
    finally:
        try:
            sock.close()
        except Exception:
            pass


def _parse_ws_url(ws_url: str) -> tuple:
    m = re.match(r"^ws://([^/:]+):(\d+)(/.*)$", ws_url)
    if not m:
        raise ValueError(f"无法解析 WebSocket URL: {ws_url}")
    return m.group(1), int(m.group(2)), m.group(3)


def render_and_harvest(src: Path, chrome: str, png: Path | None = None,
                       dpi: int = 300, timeout: float = 60.0,
                       device_scale: float = 2.0) -> dict:
    """用 Chrome 打开源文件：同一次渲染里采集几何（closing over 源文件的真实排版）。

    返回 {data: 采集结果, png: 实际产出路径或 None, renderer: 'chrome'}
    """
    import tempfile
    port = _free_port()
    profile = tempfile.mkdtemp(prefix="svgqa-profile-")
    cmd = [
        chrome, "--headless=new", f"--remote-debugging-port={port}",
        f"--user-data-dir={profile}", "--no-first-run", "--no-default-browser-check",
        "--disable-gpu", "--hide-scrollbars", "--disable-extensions",
        "--allow-file-access-from-files",
        f"--force-device-scale-factor={device_scale}",
        "about:blank",
    ]
    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    page_ws = None
    try:
        ws_url = None
        deadline = time.time() + 25
        while time.time() < deadline:
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=1) as r:
                    ws_url = json.load(r).get("webSocketDebuggerUrl")
                if ws_url:
                    break
            except Exception:
                time.sleep(0.15)
        if not ws_url:
            raise RuntimeError("无法连接 Chrome 调试端口（Chrome 启动失败？）")

        # 取一个已存在的 page target（新版 Chrome 的 /json/new 要求 PUT，故不依赖它）
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/list", timeout=5) as r:
            targets = json.load(r)
        pages = [t for t in targets
                 if t.get("type") == "page" and t.get("webSocketDebuggerUrl")]
        if not pages:
            raise RuntimeError("Chrome 未暴露 page target（无法采集几何）")
        page_ws = pages[0]["webSocketDebuggerUrl"]
        url = src.resolve().as_uri()

        calls = [
            ("Page.enable", {}),
            ("Runtime.enable", {}),
            ("Emulation.setDeviceMetricsOverride",
             {"width": 1200, "height": 900, "deviceScaleFactor": device_scale, "mobile": False}),
            ("Page.navigate", {"url": url}),
        ]
        _cdp(page_ws, calls, timeout=timeout)
        time.sleep(0.6)  # 让字体/脚本落定

        (res,) = _cdp(page_ws, [("Runtime.evaluate", {
            "expression": HARVEST_JS, "returnByValue": True, "awaitPromise": False
        })], timeout=timeout)
        if res.get("exceptionDetails"):
            desc = res["exceptionDetails"].get("exception", {}).get("description", "")
            raise RuntimeError(f"页内采集脚本抛错: {desc.splitlines()[0] if desc else res['exceptionDetails']}")
        data = res.get("result", {}).get("value")
        if not isinstance(data, dict):
            raise RuntimeError(f"采集返回异常类型: {type(data).__name__}（期望 dict）")
        if data.get("error"):
            raise RuntimeError(f"采集失败: {data['error']}")

        # 截图（先量画布尺寸再裁剪，保证 PNG 尺寸 == viewBox）
        png_path = None
        if png is not None:
            vb, sc = data["viewBox"], data["scale"]
            w = max(1, int(round(vb["w"] * sc)))
            h = max(1, int(round(vb["h"] * sc)))
            (shot,) = _cdp(page_ws, [("Page.captureScreenshot", {
                "format": "png",
                "clip": {"x": 0, "y": 0, "width": w, "height": h, "scale": 1},
                "captureBeyondViewport": True,
            })], timeout=timeout)
            png.write_bytes(base64.b64decode(shot["data"]))
            png_path = png
            _write_png_dpi(png, dpi)
        return {"data": data, "png": png_path, "renderer": "chrome"}
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except Exception:
            proc.kill()
        shutil.rmtree(profile, ignore_errors=True)


def _write_png_dpi(png: Path, dpi: int) -> None:
    try:
        from PIL import Image
        im = Image.open(png)
        im.save(png, dpi=(dpi, dpi))
    except Exception:
        pass


# --------------------------------------------------------------------------
# 结论层：把采集结果算成数值断言
# --------------------------------------------------------------------------
def audit(src: Path, data: dict, thr: dict, dpi: int, keep_region: bool = True,
          line_occlude: bool = True) -> dict:
    vb = data["viewBox"]
    nodes = data["nodes"]
    body_bg = parse_color(data.get("bodyBg")) or (255, 255, 255, 1.0)
    bg = composite(body_bg, (255, 255, 255))

    # 1 个「用户单位」等于多少 pt —— 由画布根元素 width 属性的单位决定：
    #   * width="526.8pt" → 1 u = 1pt（matplotlib 导出属此类）
    #   * width="600"（无单位，按 CSS 像素）→ 1 u = 1px = 0.75pt
    #
    # 采集到的 fontSizePx 是元素**在自身用户单位系里**的字号，不是物理 CSS 像素：
    # SVG 用户单位由画布宽度定义，缩放后该数值不变。故真实字号 = fontSizePx × unit_pt。
    #
    # 旧实现写成 `fontSizePx / scale × pt_per_u`（scale = 渲染px/viewBox ≈ 1.3333），
    # 等于把真实字号再除以 1.3333：526.8pt 画布上 7pt 的标签被报成 5.2pt，整图密集
    # 误报 TINY（实测 66/66 条文本全部误报）。
    # 交叉验证：audit_pdf_text.py 与 pdfplumber 从同一张图的 PDF 抽出字号 6.0–8.5pt，
    # 与 SVG 声明值一一对应；说明 SVG 里的 6/7/8 就是 pt，不需要任何 scale 折算。
    natural_mm = None
    if isinstance(data.get("natural"), dict):
        natural_mm = data["natural"].get("w_mm")
    have_natural = bool(natural_mm and float(natural_mm) > 0)
    print_w = float(thr["print_width_mm"])

    if have_natural and vb["w"] > 0:
        # 画布名义宽 = vb.w 个用户单位，其物理宽 = natural_mm
        unit_pt = (float(natural_mm) * 72.0 / 25.4) / vb["w"]
    else:
        # 拿不到根元素尺寸时退回旧口径（无 width 的 SVG）
        unit_pt = (72.0 / 25.4) / (vb["w"] / print_w) if vb["w"] > 0 else 1.0
    pt_per_u = unit_pt
    base_w = float(natural_mm) if have_natural else print_w

    # 投放缩放：仅在用户**显式**声明投放宽时才折算。档位里的 print_width_mm 只是兜底
    # 默认值（competition 160 / journal 180 / screen 240mm），不代表该图真会放那么宽；
    # 实测 matplotlib 图按双栏整幅设计（185.8mm ≈ 7.32in），拿 160mm 去缩放会造出假 TINY。
    place_scale = (print_w / base_w) if (have_natural and print_w > 0
                                        and thr.get("_print_width_explicit")) else 1.0

    checks: list[dict] = []

    def add(level, cid, node, detail, fix):
        checks.append({"level": level, "id": cid, "target": node, "detail": detail, "fix": fix})

    texts = [n for n in nodes if n["tag"] == "text" and n["visible"] and (n["label"] or n["parts"])]
    shapes = [n for n in nodes if n["tag"] in ("rect", "circle", "ellipse", "polygon", "image")
              and n["visible"]]

    # ---- 1. 出血 / 贴边 --------------------------------------------------
    tol = float(thr["edge_tol_px"])
    mx0, my0 = vb["x"], vb["y"]
    mx1, my1 = vb["x"] + vb["w"], vb["y"] + vb["h"]
    for n in nodes:
        if not n["visible"]:
            continue
        b = n["box"]
        if b["w"] <= 0 or b["h"] <= 0:
            continue
        over = max(mx0 - b["x"], my0 - b["y"], (b["x"] + b["w"]) - mx1, (b["y"] + b["h"]) - my1)
        if over > tol:
            add("FAIL", "OVERFLOW", _tag(n), f"越出画布 {over:.1f}u（画布 {vb['w']:g}×{vb['h']:g}u）",
                "扩大 viewBox 或移动/缩短该元素；文字可用 text-anchor 或换行")
        elif over > -tol and over != 0:
            add("WARN", "TOUCH", _tag(n), "内容贴到画布边缘（转 PDF 时易被裁）",
                "留 ≥2% 边距")

    # ---- 2. 文本互叠 -----------------------------------------------------
    gap = max(0.5, vb["w"] * 0.001)
    for i in range(len(texts)):
        for j in range(i + 1, len(texts)):
            a, b = texts[i], texts[j]
            if _contains(a, b) or _contains(b, a):
                continue
            ox = min(a["box"]["x"] + a["box"]["w"], b["box"]["x"] + b["box"]["w"]) - \
                max(a["box"]["x"], b["box"]["x"])
            oy = min(a["box"]["y"] + a["box"]["h"], b["box"]["y"] + b["box"]["h"]) - \
                max(a["box"]["y"], b["box"]["y"])
            if ox > gap and oy > max(0.5, vb["h"] * 0.0015):
                area = ox * oy
                small = min(a["box"]["w"] * a["box"]["h"], b["box"]["w"] * b["box"]["h"]) or 1
                if area / small < 0.06:
                    continue
                add("FAIL", "COLLIDE", f"{_tag(a)} × {_tag(b)}",
                    f"文本重叠 {ox:.1f}×{oy:.1f}u（占较小盒 {area / small:.0%}）",
                    "改 text-anchor / 旋转角 / 缩短标签，或把明细移入图注")

    # ---- 3+4. 文本可读性：前景自身色 / 采样得出的背景（遮挡 + 对比度） --------
    # 关键：不能只看画布底色。文字可能压在柱/色块/误差带上，"背景"必须按
    # 谁在它下面且 DOM 序更靠后（更上层）来推断 —— 否则白字压蓝柱会被误判成
    # 白底白衣（实测踩坑：clean 样例误报 1.00:1）。
    def _fg_rgb(n) -> tuple | None:
        if n.get("hasStroke") and not n.get("hasFill"):
            c = parse_color(n.get("stroke"))
            if c is not None:
                so = float(n.get("strokeOpacity", 1.0) if n.get("strokeOpacity") is not None else 1.0)
                a = c[3] * so
                if a > 0.02:
                    return composite((c[0], c[1], c[2], a), (255, 255, 255))
        return _fill_rgb(n)

    for t in texts:
        tf = _fg_rgb(t)
        if tf is None:
            continue
        samples = t.get("samples") or []
        tpt = float(t.get("fontSizePx") or 0) / data["scale"] * pt_per_u
        bold = str(t.get("fontWeight") or "400") in ("700", "bold", "800", "900")
        need = 3.0 if (bold and tpt >= 14.0) else float(thr["min_contrast"])

        # 该文字自身色与背景色近似 -> 它就是「被自身色块吞掉」的前景像素
        def looks_like_bg(rgb_css, fg) -> bool:
            c = parse_color(rgb_css)
            if c is None:
                return False
            return color_distance(composite(c, bg), fg) < 40

        hidden = [s for s in samples if s.get("bg") and looks_like_bg(s["bg"], tf)]
        hidden_frac = len(hidden) / len(samples) if samples else 0.0
        if hidden_frac >= 0.5:
            under = hidden[0].get("under") or "同色图形"
            add("FAIL", "MASKED", _tag(t),
                f"前景色与下方图形同色（{hidden_frac:.0%} 采样点），该文字在图上不可见"
                f"（压住它的图形文字：{under[:20]}）",
                "改文字色或移动位置；色块上文字要按亮度自动选黑/白")

        # 背景集合：只要覆盖 ≥10% 采样点，就必须满足对比度（不能只看"多数背景"）
        total = len(samples) or 1
        present = {}
        for d in (t.get("bgDistinct") or []):
            if d["count"] / total < 0.10:
                continue
            css = d["color"]
            if css is None:
                present["__page__"] = bg
            else:
                c = parse_color(css)
                if c is not None:
                    present[css] = composite(c, bg)
        if not present:
            present["__page__"] = bg
        worst_css, worst_cr, worst_share = None, 99.0, 0.0
        for css, rgbv in present.items():
            cr = contrast_ratio(tf, rgbv)
            if cr < worst_cr:
                worst_css, worst_cr = css, cr
                worst_share = next((d["count"] / total for d in (t.get("bgDistinct") or [])
                                    if (d["color"] or "__page__") == css), 0.0)
        if worst_cr < need:
            where = "画布底色" if worst_css == "__page__" else f"下方图形 {_hex(present[worst_css])}"
            add("FAIL" if worst_cr < need * 0.85 else "WARN", "CONTRAST", _tag(t),
                f"对比度 {worst_cr:.2f}:1 < {need:.1f}:1（字号 {tpt:.1f}pt，背景为{where}，"
                f"占文字面积 {worst_share:.0%}）",
                "加深文字色或改浅底色；压在色块上的标签按背景亮度自动选黑/白")

        # 非自身色、且**不是页面底色**的图形压在文字上 = 真的遮挡（按文字去重）
        # 白色系（页面/画布底板）不算遮挡，否则整张图每个标签都会被判"压在白色图形上"。
        def is_page_layer(css) -> bool:
            c = parse_color(css)
            return c is not None and min(c[0], c[1], c[2]) >= 245

        # 线状遮挡：细线天然只覆盖少数采样点（约 2%），必须用更低阈值判定
        line_hits = [s for s in samples if s.get("kind") == "stroke"
                     and s.get("bg") and not is_page_layer(s["bg"])
                     and not looks_like_bg(s["bg"], tf)]
        if line_hits and line_occlude:
            share = len(line_hits) / max(len(samples), 1)
            if share >= 0.02:
                c = parse_color(line_hits[0]["bg"])
                cr = contrast_ratio(tf, composite(c, bg)) if c else 99.0
                add("FAIL", "OCCLUDE", _tag(t),
                    f"折线/轴线穿过文字（{_hex(composite(c, bg)) if c else ''}，"
                    f"{share:.0%} 采样点命中），此处对比度 {cr:.2f}:1",
                    "把标签移离该线（改 xytext 偏移），或给文字加白底描边"
                    "（paint-order: stroke）；误检可用 --no-line-occlude 关闭")

        # 色块压字：按覆盖面积 + 对比度判定（≥10% 面积才算压住）
        best = None
        for s in samples:
            if not s.get("bg") or s.get("kind") == "stroke" or is_page_layer(s["bg"]):
                continue
            if looks_like_bg(s["bg"], tf):
                continue                      # 同色前景像素，已在 MASKED 处理
            if s.get("opaque") is False:
                continue                      # 半透明遮罩走 VEIL
            if best is None:
                best = s
        if best is not None:
            c = parse_color(best["bg"])
            cr = contrast_ratio(tf, composite(c, bg)) if c else 99.0
            hits = sum(1 for s in samples if s.get("bg") == best["bg"]) / max(len(samples), 1)
            if hits >= 0.10:
                # 色块压字只在对比度不足时才算遮挡，否则它本来就是"色块内数值标签"的正常设计
                if cr < float(thr["min_contrast"]):
                    add("FAIL", "OCCLUDE", _tag(t),
                        f"文字压在图形 {_hex(composite(c, bg)) if c else ''} 上"
                        f"（{hits:.0%} 采样点），对比度 {cr:.2f}:1 不足",
                        "把标签移出色块，或按背景亮度改黑/白文字色")
                else:
                    add("WARN", "OCCLUDE", _tag(t),
                        f"文字压在图形 {_hex(composite(c, bg)) if c else ''} 上"
                        f"（{hits:.0%} 采样点），对比度 {cr:.2f}:1 达标，确认是有意设计",
                        "若为色块内数值标签则无需处理；注意跨图保持同一语义")

        # 半透明遮罩压在数据上（论文里最常见的糊图手法）
        veils = [s for s in samples if s.get("bg") and s.get("opaque") is False
                 and s.get("kind") != "page" and not is_page_layer(s["bg"])]
        if veils and len(veils) / max(len(samples), 1) >= 0.10:
            add("WARN", "VEIL", _tag(t),
                f"文字下方是半透明遮罩（{len(veils) / len(samples):.0%} 采样点），可能压住数据",
                "用不带遮罩的留白区域放图例；或改用图外图例")

    # ---- 5. 字号下限（按最终投放尺寸折算） -------------------------------
    # fontSizePx 已是该元素在用户单位系里的字号；× unit_pt 得真实 pt。
    # 若用户显式声明了投放宽，再乘 place_scale（图被缩小则字更小）。
    for t in texts:
        tpt = float(t.get("fontSizePx") or 0) * unit_pt * place_scale
        if tpt <= 0:
            continue
        if tpt < float(thr["min_pt"]):
            add("FAIL", "TINY", _tag(t),
                f"折算 {tpt:.1f}pt < 下限 {thr['min_pt']:g}pt（投放宽 {print_w:g}mm）",
                "放大字号或缩小画布；或缩短文字避免缩小整图")
        elif tpt < float(thr["min_pt"]) * 1.15:
            add("WARN", "TINY", _tag(t), f"折算 {tpt:.1f}pt 逼近下限", "留出安全余量")

    # ---- 6. 配色可分性（灰度 + 色盲） -------------------------------------
    # 配色池必须同时收「填充色」和「描边色」——折线/曲线图的系列全部靠 stroke，
    # 只看 fill 会漏掉整类图（实测踩坑：bad 样例 COLLAPSE 漏报）。
    palette: dict[tuple, list] = {}
    for n in nodes:
        if not n["visible"]:
            continue
        rgb = None
        if n["tag"] in ("rect", "circle", "ellipse", "polygon", "image") and n.get("hasFill"):
            rgb = _fill_rgb(n)
        elif n.get("hasStroke"):
            box = n["box"]
            thin = min(box["w"], box["h"]) <= 2.0 or n["tag"] == "line"
            if thin:  # 只把"线状"描边当系列色；粗描边边框不算系列
                rgb = _fg_rgb(n)
        if rgb is None:
            continue
        key = tuple(int(round(v)) for v in rgb)
        palette.setdefault(key, []).append(_tag(n))
    keys = sorted(palette.keys())
    for i in range(len(keys)):
        for j in range(i + 1, len(keys)):
            c1, c2 = keys[i], keys[j]
            if all(v >= 250 for v in c1) and all(v >= 250 for v in c2):
                continue  # 白底/白填充不参与
            # 只跳过"真正的中性深色"（文字/轴线），不能按亮度阈值一刀切——
            # 深蓝/深红等同为暗色但色相不同的系列色必须参与可分性判定。
            if all(v <= 30 for v in c1) and all(v <= 30 for v in c2):
                continue
            if (max(c1) - min(c1) < 8 and max(c1) <= 90
                    and max(c2) - min(c2) < 8 and max(c2) <= 90):
                continue
            d = color_distance(c1, c2)
            pair = f"{_hex(c1)} vs {_hex(c2)}"
            if d < float(thr["min_color_dist"]):
                add("WARN", "MERGE", pair,
                    f"色距 {d:.0f} < {thr['min_color_dist']:g}（两个系列可能被读成同一语义）",
                    "拉开色相差异；确认这是有意的同族编码（alpha 梯度/同色系基线）才可豁免")
            g1, g2 = to_grayscale(c1), to_grayscale(c2)
            if abs(g1[0] - g2[0]) < 8:
                add("FAIL", "COLLAPSE", pair,
                    f"灰度下几乎同亮度（ΔL={abs(g1[0] - g2[0]):.0f}）——黑白打印不可分",
                    "改用 Okabe-Ito 或加线型/marker/hatch 冗余编码")
            for kind in CVD_MATRIX:
                s1, s2 = simulate_cvd(c1, kind), simulate_cvd(c2, kind)
                if color_distance(s1, s2) < float(thr["min_color_dist"]) * 0.6:
                    add("FAIL", "COLLAPSE", pair,
                        f"{kind} 模拟下色距仅 {color_distance(s1, s2):.0f}——色盲读者不可分",
                        "换色盲安全色板（Okabe-Ito / seaborn colorblind）")
                    break

    fails = [c for c in checks if c["level"] == "FAIL"]
    warns = [c for c in checks if c["level"] == "WARN"]
    counts: dict[str, int] = {}
    for c in checks:
        counts[c["id"]] = counts.get(c["id"], 0) + 1

    report = {
        "source": str(src), "renderer": data.get("_renderer", "chrome"),
        "canvas_units": {"w": vb["w"], "h": vb["h"]},
        "rendered_px": {"w": data["docSize"]["w"], "h": data["docSize"]["h"]},
        "print_width_mm": print_w, "pt_per_unit": round(pt_per_u, 4),
        "thresholds": thr,
        "counts": counts,
        "fails": len(fails), "warns": len(warns),
        "checks": checks,
        "palette": [{"color": _hex(k), "used_by": v} for k, v in palette.items()],
        "verdict": "PASS" if not fails else "FAIL",
    }
    if keep_region:
        report["nodes"] = nodes
    return report


def _fill_rgb(n) -> tuple | None:
    c = parse_color(n.get("fill"))
    if c is None:
        return None
    a = c[3] * float(n.get("fillOpacity", 1.0) if n.get("fillOpacity") is not None else 1.0)
    if a <= 0.02:
        return None
    return composite((c[0], c[1], c[2], a), (255, 255, 255))


def _hex(rgb) -> str:
    return "#%02x%02x%02x" % tuple(int(round(v)) for v in rgb[:3])


def _tag(n) -> str:
    who = n.get("id") or n.get("cls") or ""
    lbl = n.get("label") or ""
    if n["tag"] == "text" and lbl:
        return f"text[{lbl[:24]}]"
    return f"{n['tag']}{'#' + who if who else ''}"


def _contains(outer, inner) -> bool:
    a, b = outer["box"], inner["box"]
    return (a["x"] <= b["x"] + 0.5 and a["y"] <= b["y"] + 0.5 and
            a["x"] + a["w"] >= b["x"] + b["w"] - 0.5 and
            a["y"] + a["h"] >= b["y"] + b["h"] - 0.5)


# --------------------------------------------------------------------------
# 报告输出
# --------------------------------------------------------------------------
def print_report(rep: dict, verbose: bool = True) -> None:
    _log("INFO", f"画布 {rep['canvas_units']['w']:g}×{rep['canvas_units']['h']:g}u "
                 f"→ 渲染 {rep['rendered_px']['w']:g}×{rep['rendered_px']['h']:g}px "
                 f"（{rep['pt_per_unit']}pt/u，投放宽 {rep['print_width_mm']:g}mm）")
    order = {"FAIL": 0, "WARN": 1}
    for c in sorted(rep["checks"], key=lambda x: order.get(x["level"], 2)):
        if c["level"] == "WARN" and not verbose:
            continue
        _log(c["level"], f"{c['id']:<9} {c['target']:<34} {c['detail']}")
        if c["level"] == "FAIL" and c.get("fix"):
            print(f"           → {c['fix']}")
    n_pal = len(rep["palette"])
    _log("INFO", f"配色 {n_pal} 种： " + ", ".join(p["color"] for p in rep["palette"][:12]))
    _log("PASS" if rep["verdict"] == "PASS" else "FAIL",
         f"{rep['verdict']}  FAIL={rep['fails']} WARN={rep['warns']} {rep['counts']}")


# --------------------------------------------------------------------------
# 自检：合成正/反样例，验证不误报、不漏报
# --------------------------------------------------------------------------
_CLEAN_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 600 320" width="600" height="320"
  font-family="Helvetica,Arial,sans-serif" data-intended-width-mm="160">
<rect x="0" y="0" width="600" height="320" fill="#ffffff"/>
<g fill="#0072b2"><rect x="90" y="120" width="50" height="130"/><rect x="190" y="120" width="50" height="130"/></g>
<g fill="#d55e00"><rect x="150" y="170" width="50" height="80"/><rect x="250" y="160" width="50" height="90"/></g>
<line x1="70" y1="250" x2="560" y2="250" stroke="#333333" stroke-width="1.5"/>
<text x="115" y="190" font-size="30" fill="#ffffff" text-anchor="middle">30</text>
<text x="175" y="215" font-size="30" fill="#1a1a1a" text-anchor="middle">20</text>
<text x="115" y="278" font-size="22" fill="#222222" text-anchor="middle">Q1</text>
<text x="215" y="278" font-size="22" fill="#222222" text-anchor="middle">Q2</text>
<text x="300" y="50" font-size="24" fill="#222222">Legend: A / B</text>
</svg>"""

# 每个判据至少触发一次：OVERFLOW / COLLIDE / OCCLUDE / MASKED / CONTRAST / TINY / COLLAPSE
_BAD_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 600 320" width="600" height="320"
  font-family="Helvetica,Arial,sans-serif" data-intended-width-mm="160">
<rect x="0" y="0" width="600" height="320" fill="#ffffff"/>
<g fill="#3b6fd4"><rect x="70" y="120" width="120" height="160"/><rect x="250" y="120" width="120" height="160"/></g>
<g fill="#c85028"><rect x="90" y="180" width="120" height="100"/><rect x="270" y="180" width="120" height="100"/></g>
<text x="130" y="260" font-size="30" fill="#c85028">同色柱上不可见</text>
<line x1="90" y1="230" x2="330" y2="230" stroke="#666666" stroke-width="3"/>
<text x="140" y="238" font-size="26" fill="#222222">被线穿过</text>
<text x="130" y="200" font-size="26" fill="#222222">上方行文字</text>
<text x="600" y="40" font-size="12" fill="#333333">跑出画布了</text>
<text x="300" y="40" font-size="7" fill="#999999">对比度不足且字号过小</text>
</svg>"""


# 唯一缺陷是「折线从文字中间穿过」：几何必须自己检出来，不能靠对比度碰巧命中
_LINE_THROUGH_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 600 320" width="600" height="320"
  font-family="Helvetica,Arial,sans-serif" data-intended-width-mm="160">
<rect x="0" y="0" width="600" height="320" fill="#ffffff"/>
<rect x="120" y="120" width="360" height="150" fill="#e8eef7"/>
<text x="300" y="133" font-size="26" fill="#1a1a1a" text-anchor="middle">折线从这行字穿过</text>
<polyline points="60,105 180,95 300,125 420,100 540,115" fill="none" stroke="#0072b2" stroke-width="3"/>
</svg>"""


def _self_test() -> int:
    chrome = find_chrome()
    if not chrome:
        _log("ERROR", "自检需要 Chrome：未找到，可用 CHROME_PATH 指定")
        return 2
    expect_ids = {"OVERFLOW", "COLLIDE", "OCCLUDE", "MASKED", "CONTRAST", "TINY", "COLLAPSE"}
    ok = True
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        for name, svg in (("clean", _CLEAN_SVG), ("bad", _BAD_SVG), ("line", _LINE_THROUGH_SVG)):
            p = td / f"{name}.svg"
            p.write_text(svg, encoding="utf-8")
            print(f"\n=== self-test case: {name} ===")
            try:
                r = render_and_harvest(p, chrome, png=td / f"{name}.png", dpi=150)
                rep = audit(p, r["data"], THRESHOLDS["competition"], 150, keep_region=False)
            except Exception as e:
                _log("ERROR", f"渲染/审计异常: {e}")
                return 2
            print_report(rep)
            if name == "clean" and rep["fails"]:
                _log("ERROR", f"clean 样例出现 {rep['fails']} 个 FAIL（误报）："
                              f"{sorted(c['id'] for c in rep['checks'] if c['level'] == 'FAIL')}")
                ok = False
            if name == "bad":
                got = set(rep["counts"])
                missing = expect_ids - got
                if missing:
                    _log("ERROR", f"bad 样例漏报: {sorted(missing)}")
                    ok = False
                else:
                    _log("INFO", f"bad 样例命中判据: {sorted(got)}")
            if name == "line":
                occ = [c for c in rep["checks"] if c["id"] == "OCCLUDE" and c["level"] == "FAIL"]
                if not occ:
                    _log("ERROR", "line 样例漏报：折线穿过文字未检出 OCCLUDE")
                    ok = False
                elif "线" not in occ[0]["detail"]:
                    _log("ERROR", f"line 样例检出的不是线遮挡：{occ[0]['detail']}")
                    ok = False
                elif any(c["level"] == "FAIL" for c in rep["checks"] if c["id"] != "OCCLUDE"):
                    _log("ERROR", "line 样例出现 OCCLUDE 之外的 FAIL（误报）")
                    ok = False
                else:
                    _log("INFO", "line 样例：仅线穿过文字被检出（几何判定，非对比度巧合）")
            if not (td / f"{name}.png").exists():
                _log("ERROR", "未产出 PNG")
                ok = False
    print()
    _log("PASS" if ok else "FAIL",
         f"svg_audit self-test: {'PASS' if ok else 'FAIL'} (3 cases / {len(expect_ids)} criteria)")
    return 0 if ok else 1


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------
def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--self-test" in argv:
        return _self_test()

    ap = argparse.ArgumentParser(description="SVG/HTML 图件几何 + 配色程序化审计")
    ap.add_argument("src", help="待审计的 .svg 或 .html")
    ap.add_argument("--png", help="同时渲染回看用 PNG（建议：审计与回看同一份渲染）")
    ap.add_argument("--dpi", type=int, default=300, help="写入 PNG 的 DPI 元数据（默认 300）")
    ap.add_argument("--json", help="把完整报告写到该路径（含逐元素几何，供回改定位）")
    ap.add_argument("--thresholds", choices=sorted(THRESHOLDS), default="competition",
                    help="阈值档位（默认 competition；journal/screen 见脚本头部）")
    ap.add_argument("--print-width-mm", type=float, help="图在最终文档中的投放宽度（默认按档位）")
    ap.add_argument("--min-pt", type=float, help="覆盖字号下限（pt）")
    ap.add_argument("--min-contrast", type=float, help="覆盖对比度下限（WCAG 比值）")
    ap.add_argument("--min-color-dist", type=float, help="覆盖最小色距")
    ap.add_argument("--chrome", help="Chrome/Chromium 可执行路径（默认自动探测）")
    ap.add_argument("--quiet", action="store_true", help="只打印 FAIL 和汇总")
    ap.add_argument("--no-line-occlude", action="store_true",
                    help="不把「折线/轴线穿过文字」判为遮挡（图例线样本等已知误检时用）")
    ap.add_argument("--no-geometry", action="store_true",
                    help="跳过 Chrome 几何采集，仅渲染 PNG（Chrome 不可用时的降级）")
    args = ap.parse_args(argv)

    src = Path(args.src)
    if not src.exists():
        _log("ERROR", f"文件不存在: {src}")
        return 2

    thr = dict(THRESHOLDS[args.thresholds])
    if args.print_width_mm is not None:
        thr["print_width_mm"] = args.print_width_mm
        # 标记：只有用户显式声明投放宽，才按投放缩放折算字号（见 audit()）
        thr["_print_width_explicit"] = True
    for k, v in (("min_pt", args.min_pt), ("min_contrast", args.min_contrast),
                 ("min_color_dist", args.min_color_dist)):
        if v is not None:
            thr[k] = v

    chrome = args.chrome or find_chrome()
    png = Path(args.png) if args.png else None
    if png:
        png.parent.mkdir(parents=True, exist_ok=True)

    if not chrome or args.no_geometry:
        # 降级：只出 PNG 供读图，几何无法断言 —— 显式告知，不静默放过
        if not png:
            _log("ERROR", "无 Chrome 时至少要用 --png 渲染回看图，或安装 Chrome/Chromium")
            return 2
        rsp = shutil.which("rsvg-convert")
        if src.suffix.lower() == ".svg" and rsp:
            subprocess.run([rsp, "-d", str(args.dpi), "-p", str(args.dpi), str(src), "-o", str(png)],
                           check=True)
            _log("WARN", "NGEOMETRY 未做几何审计（无 Chrome）：仅产出 PNG，遮挡/裁切/字号未经断言")
            _log("INFO", f"已渲染 {png}")
            return 0
        helper = Path(__file__).with_name("render_svg.py")
        if src.suffix.lower() == ".svg" and helper.exists():
            subprocess.run([sys.executable, str(helper), str(src), str(png), "--dpi", str(args.dpi)],
                           check=True)
            _log("WARN", "NGEOMETRY 未做几何审计（无 Chrome）：仅产出 PNG，遮挡/裁切/字号未经断言")
            return 0
        _log("ERROR", "既无 Chrome 也无 SVG 渲染后端")
        return 2

    try:
        r = render_and_harvest(src, chrome, png=png, dpi=args.dpi)
        r["data"]["_renderer"] = "chrome"
    except Exception as e:
        _log("ERROR", f"渲染/采集失败: {e}")
        _log("INFO", "排查：Chrome 能否手动打开该文件？是否需要 --no-sandbox（容器环境）？")
        return 2

    rep = audit(src, r["data"], thr, args.dpi, line_occlude=not args.no_line_occlude)
    print_report(rep, verbose=not args.quiet)
    if png:
        _log("INFO", f"PNG 已渲染 → {png}")
    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
        _log("INFO", f"报告 → {args.json}")
    return 0 if rep["verdict"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
