#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""论文图表统一样式（matplotlib）。

用法（在绘图脚本开头，先于任何 pyplot 调用）：
    import sys; sys.path.insert(0, "<本文件所在目录>")
    import plot_style as ps

    fig, ax = plt.subplots()
    ...
    ps.save_fig(fig, "work/figures/fig_1_result.png")

自动完成：
- 中文字体自动探测（PingFang / Hiragino / SimHei / 微软雅黑 / Noto CJK 等）
- 全局 rcParams：300 DPI 导出、统一配色与字号、坐标轴与图例规范
- save_fig() 便捷保存

需要环境：matplotlib（pip install matplotlib）
"""

from __future__ import annotations

import logging
import os
import sys
import warnings

import matplotlib
from matplotlib import font_manager

_CJK_CANDIDATES = [
    "PingFang SC",
    "Hiragino Sans GB",
    "Microsoft YaHei",
    "SimHei",
    "Noto Sans CJK SC",
    "Source Han Sans SC",
    "WenQuanYi Zen Hei",
    "Songti SC",
    "STSong",
]


def detect_cjk_font() -> str | None:
    """探测可用的中文字体名，找不到返回 None。"""
    available = {f.name for f in font_manager.fontManager.ttflist}
    for name in _CJK_CANDIDATES:
        if name in available:
            return name
    for f in font_manager.fontManager.ttflist:
        if any(k in f.name for k in ("CJK", "Hei", "Song", "YaHei", "PingFang", "Noto")):
            return f.name
    return None


PALETTE = [
    "#2F5597",  # 深蓝
    "#C00000",  # 深红
    "#00B050",  # 绿
    "#ED7D31",  # 橙
    "#7030A0",  # 紫
    "#BFBFBF",  # 灰
]


class GlyphFallbackError(RuntimeError):
    """图内出现字体回退（tofu/虚线方块）时的硬失败。"""


def _install_glyph_guard() -> None:
    """把 matplotlib 的「缺字回退」从提示升级为异常。

    两类出口都要堵：Text 走 warnings.warn("Glyph ... missing from font")，
    mathtext 走 logging（"Font 'default' does not have a glyph for ..."），
    后者不会被 warnings 过滤器捕获——它会静默把符号换成 dummy 方块进论文。
    """
    warnings.filterwarnings("error", message="Glyph", category=UserWarning)

    class _Handler(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            msg = record.getMessage()
            if "does not have a glyph" in msg or "substituting with a dummy symbol" in msg:
                raise GlyphFallbackError(f"图内缺字（字体回退）：{msg}")

    # 挂在父 logger 上：matplotlib 内部消息 logger 名字不统一
    # （_mathtext.py 用 "matplotlib.mathtext"，mathtext.py 用 __name__），
    # 子 logger 的记录会向上传播到 "matplotlib"，一处兜住两类。
    for name in ("matplotlib", "matplotlib.mathtext", "matplotlib._mathtext"):
        logger = logging.getLogger(name)
        if any(isinstance(h, _Handler) for h in logger.handlers):
            continue
        logger.setLevel(logging.WARNING)
        logger.addHandler(_Handler())


def apply() -> None:
    """应用统一样式到全局 rcParams。"""
    _install_glyph_guard()
    cjk = detect_cjk_font()
    if cjk is None:
        print(
            "[plot_style] 警告：未找到中文字体，中文可能显示为方框。"
            "请安装 Noto Sans CJK / 微软雅黑 / 思源黑体等字体。",
            file=sys.stderr,
        )

    matplotlib.rcParams.update(
        {
            "font.family": "sans-serif",
            "font.sans-serif": ([cjk] if cjk else []) + ["DejaVu Sans"],
            "axes.unicode_minus": False,  # 负号正常显示
            "figure.dpi": 100,
            "savefig.dpi": 300,
            "savefig.bbox": "tight",
            "font.size": 10.5,
            "axes.titlesize": 12,
            "axes.labelsize": 11,
            "legend.fontsize": 9.5,
            "xtick.labelsize": 9.5,
            "ytick.labelsize": 9.5,
            "axes.linewidth": 0.8,
            "lines.linewidth": 1.8,
            "lines.markersize": 5,
            "axes.prop_cycle": matplotlib.cycler(color=PALETTE),
            "axes.grid": True,
            "grid.alpha": 0.3,
            "grid.linestyle": "--",
            "figure.autolayout": True,
        }
    )


def save_fig(fig, path: str, dpi: int | None = None) -> None:
    """保存并关闭图形，紧凑裁边。

    两档导出（防「画个图好慢」——慢在往返不在渲染）：
    - 迭代轮 `MATHFIG_DRAFT=1` ⇒ 默认 150 DPI 草稿档，只够看版式与遮挡；
    - 定稿不设或 `MATHFIG_DRAFT=0` ⇒ 默认 300 DPI（论文图建议 600，用 `MATHFIG_DPI=600` 覆盖）。
    """
    draft = os.environ.get("MATHFIG_DRAFT") == "1"
    if dpi is None:
        dpi = int(os.environ.get("MATHFIG_DPI", "150" if draft else "300"))
    fig.savefig(path, dpi=dpi, bbox_inches="tight")
    import matplotlib.pyplot as plt

    plt.close(fig)
    print(f"[plot_style] 已保存: {path}（{dpi} dpi{'，草稿档' if draft else ''}）")


apply()
