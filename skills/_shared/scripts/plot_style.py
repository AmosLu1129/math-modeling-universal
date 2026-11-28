#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""论文图表统一样式（matplotlib，支持 competition 与莫兰迪顶刊主题 morandi_*）。

用法（在绘图脚本开头，先于任何 pyplot 调用）：
    import sys; sys.path.insert(0, "<本文件所在目录>")
    import plot_style as ps
    ps.apply("morandi_journal")  # 或设环境变量 MATHFIG_THEME=morandi_journal

    fig, ax = plt.subplots()
    ...
    ps.save_fig(fig, "work/figures/fig_1_result.png")

特性：
- 4 套主题：competition（v4.1 兼容）、morandi_journal（o_award 主力）、morandi_cool、morandi_pastel
- 3 套定制莫兰迪连续/发散色带：morandi_seq、morandi_div、morandi_warm
- 莫兰迪 6 项顶刊微排版质感规则 + style_3d_axes() / add_line_halo() / darken_hex()
- 中文字体自动探测与缺字硬拦截
"""

from __future__ import annotations

import logging
import os
import sys
import warnings

import matplotlib
from matplotlib import font_manager, patheffects
from matplotlib.colors import LinearSegmentedColormap

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


THEMES: dict[str, list[str]] = {
    "competition": [
        "#2F5597",  # 深蓝
        "#C00000",  # 深红
        "#00B050",  # 绿
        "#ED7D31",  # 橙
        "#7030A0",  # 紫
        "#BFBFBF",  # 灰
    ],
    "morandi_journal": [
        "#4E6E8E",  # 雾霾蓝（本方/核心）
        "#C86D5B",  # 陶土砖红（基线/警示）
        "#6D9A87",  # 鼠尾草绿（正向收益）
        "#D9A462",  # 燕麦琥珀（辅助强调）
        "#8E7A9E",  # 暮烟紫（次级通道）
        "#9BA4AE",  # 暖岩灰（参考对照）
    ],
    "morandi_cool": [
        "#3A5A78",  # 普鲁士灰蓝
        "#5F938F",  # 青瓷绿
        "#D18373",  # 柔珊瑚
        "#9FB8C9",  # 冰雾蓝
        "#C9B79C",  # 暖沙
        "#7F8A96",  # 冷铅灰
    ],
    "morandi_pastel": [
        "#465878",  # 深暮蓝
        "#7589A8",  # 烟灰蓝
        "#B4C2D6",  # 雾蓝浅阶
        "#D48A78",  # 柔陶点缀
        "#8BA59B",  # 浅鼠尾草
        "#C8BEB2",  # 暖米灰
    ],
}

PALETTE: list[str] = list(THEMES["competition"])
CURRENT_THEME: str = "competition"

CMAP_MORANDI_SEQ = LinearSegmentedColormap.from_list(
    "morandi_seq", ["#F5F2EC", "#C5D5D8", "#7599AA", "#3B5875"], N=256
)
CMAP_MORANDI_DIV = LinearSegmentedColormap.from_list(
    "morandi_div", ["#4B6C8C", "#A8BFD0", "#F7F5F0", "#DFAC9D", "#B85D4E"], N=256
)
CMAP_MORANDI_WARM = LinearSegmentedColormap.from_list(
    "morandi_warm", ["#F7F3EC", "#E5C8A6", "#D49B7A", "#B5614E"], N=256
)

MORANDI_CMAPS: dict[str, LinearSegmentedColormap] = {
    "morandi_seq": CMAP_MORANDI_SEQ,
    "morandi_div": CMAP_MORANDI_DIV,
    "morandi_warm": CMAP_MORANDI_WARM,
}

for _cmap_name, _cmap_obj in MORANDI_CMAPS.items():
    try:
        matplotlib.colormaps.register(_cmap_obj, name=_cmap_name, force=True)
    except Exception:
        pass


def get_cmap(name: str = "morandi_seq") -> LinearSegmentedColormap:
    """获取内置莫兰迪色带（morandi_seq / morandi_div / morandi_warm）。"""
    if name not in MORANDI_CMAPS:
        raise KeyError(f"Unknown Morandi cmap {name!r}; expected one of {tuple(MORANDI_CMAPS)}")
    return MORANDI_CMAPS[name]


def darken_hex(hex_color: str, factor: float = 0.75) -> str:
    """将十六进制颜色按比例压暗（用于莫兰迪浅填色配深描边）。"""
    h = hex_color.strip().lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    f = max(0.0, min(1.0, factor))
    return f"#{int(round(r * f)):02x}{int(round(g * f)):02x}{int(round(b * f)):02x}"


def add_line_halo(line, width: float = 3.2, color: str = "white") -> None:
    """为关键折线添加白色外描边光晕，多线交叉时主结论线清晰置顶。"""
    line.set_path_effects([patheffects.withStroke(linewidth=width, foreground=color), patheffects.Normal()])


def bar_style_kwargs(idx: int = 0, theme: str | None = None, alpha: float = 0.82, lw: float = 0.9) -> dict:
    """返回莫兰迪『半透明柔色填充 + 25% 加深同色细描边』样式字典。"""
    pal = THEMES.get(theme or CURRENT_THEME, PALETTE)
    c = pal[idx % len(pal)]
    return {"facecolor": c, "edgecolor": darken_hex(c, 0.75), "linewidth": lw, "alpha": alpha}


def style_3d_axes(ax, pane_rgba=(0.97, 0.98, 0.99, 0.65)) -> None:
    """将 mplot3d 默认灰墙替换为通透雾白底板与极细浅灰网格。"""
    for axis in (ax.xaxis, ax.yaxis, ax.zaxis):
        axis.pane.set_facecolor(pane_rgba)
        axis.pane.set_edgecolor("#DCE2EA")
        if hasattr(axis, "_axinfo") and "grid" in axis._axinfo:
            axis._axinfo["grid"]["color"] = (0.85, 0.87, 0.90, 0.8)
            axis._axinfo["grid"]["linewidth"] = 0.55
    ax.tick_params(colors="#3A3F47")


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


def apply(theme: str | None = None, lang: str = "en") -> list[str]:
    """应用统一样式到全局 rcParams；theme=None 时读取 MATHFIG_THEME（默认 competition）。"""
    global CURRENT_THEME
    _install_glyph_guard()
    eff_theme = (theme or os.environ.get("MATHFIG_THEME", "competition")).strip().lower()
    if eff_theme not in THEMES:
        raise ValueError(f"Unknown plot_style theme {eff_theme!r}; expected one of {tuple(THEMES)}")
    CURRENT_THEME = eff_theme
    selected = THEMES[eff_theme]
    PALETTE[:] = selected

    cjk = detect_cjk_font()
    if cjk is None:
        print(
            "[plot_style] 警告：未找到中文字体，中文可能显示为方框。"
            "请安装 Noto Sans CJK / 微软雅黑 / 思源黑体等字体。",
            file=sys.stderr,
        )

    is_morandi = eff_theme.startswith("morandi")
    if lang.lower().startswith("zh"):
        font_list = ([cjk] if cjk else []) + (["Arial", "Helvetica"] if is_morandi else []) + ["DejaVu Sans"]
    else:
        font_list = (["Arial", "Helvetica"] if is_morandi else []) + ([cjk] if cjk else []) + ["DejaVu Sans"]

    base_rc: dict[str, object] = {
        "font.family": "sans-serif",
        "font.sans-serif": font_list,
        "axes.unicode_minus": False,
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
        "axes.prop_cycle": matplotlib.cycler(color=selected),
        "axes.grid": True,
        "grid.alpha": 0.3,
        "grid.linestyle": "--",
        "figure.autolayout": True,
        "svg.fonttype": "none",
        "pdf.fonttype": 42,
        "ps.fonttype": 42,
    }

    if is_morandi:
        # 莫兰迪顶刊 6 项微排版质感规则
        base_rc.update(
            {
                "axes.spines.top": False,
                "axes.spines.right": False,
                "axes.edgecolor": "#3A3F47",
                "axes.labelcolor": "#2C3137",
                "axes.titlecolor": "#1F242A",
                "xtick.color": "#3A3F47",
                "ytick.color": "#3A3F47",
                "xtick.direction": "out",
                "ytick.direction": "out",
                "grid.color": "#EAECEF",
                "grid.linestyle": "-",
                "grid.linewidth": 0.6,
                "grid.alpha": 1.0,
                "axes.axisbelow": True,
                "mathtext.fontset": "stixsans",
                "legend.frameon": False,
                "patch.linewidth": 0.9,
            }
        )
    else:
        base_rc.update(
            {
                "axes.spines.top": True,
                "axes.spines.right": True,
                "axes.edgecolor": "black",
                "axes.labelcolor": "black",
                "axes.titlecolor": "black",
                "xtick.color": "black",
                "ytick.color": "black",
                "grid.color": "#b0b0b0",
                "legend.frameon": True,
            }
        )

    matplotlib.rcParams.update(base_rc)
    return list(selected)


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


def self_test() -> int:
    import tempfile
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    # 1. Default competition backward compatibility
    pal_def = apply()
    assert pal_def == THEMES["competition"] and matplotlib.rcParams["axes.spines.top"] is True

    # 2. MATHFIG_THEME env override + all morandi themes
    os.environ["MATHFIG_THEME"] = "morandi_journal"
    try:
        pal_env = apply()
        assert CURRENT_THEME == "morandi_journal"
        assert pal_env == THEMES["morandi_journal"] and PALETTE == THEMES["morandi_journal"]
        assert matplotlib.rcParams["axes.spines.top"] is False
        assert matplotlib.rcParams["axes.edgecolor"] == "#3A3F47"
        assert matplotlib.rcParams["grid.color"] == "#EAECEF"
        assert matplotlib.rcParams["legend.frameon"] is False
        assert matplotlib.rcParams["axes.axisbelow"] is True
        assert matplotlib.rcParams["mathtext.fontset"] == "stixsans"
    finally:
        os.environ.pop("MATHFIG_THEME", None)

    for th in ("morandi_cool", "morandi_pastel"):
        assert len(apply(th)) == 6

    # 3. Colormaps, darken_hex, add_line_halo, style_3d_axes & save_fig
    for cm_name in ("morandi_seq", "morandi_div", "morandi_warm"):
        cm = get_cmap(cm_name)
        assert len(cm(0.5)) == 4

    dark = darken_hex("#4E6E8E", 0.75)
    assert dark.startswith("#") and dark != "#4E6E8E", dark

    apply("morandi_journal")
    with tempfile.TemporaryDirectory(prefix="plotstyle_test_") as td:
        fig = plt.figure(figsize=(8, 3.6))
        ax1 = fig.add_subplot(121)
        (ln,) = ax1.plot([0, 1, 2], [1.0, 2.4, 1.9], label="Proposed")
        add_line_halo(ln)
        ax1.bar([0, 1, 2], [0.5, 0.8, 0.7], **bar_style_kwargs(2))
        ax1.legend()

        ax2 = fig.add_subplot(122, projection="3d")
        style_3d_axes(ax2)
        out_p = os.path.join(td, "test.png")
        save_fig(fig, out_p, dpi=300)
        assert os.path.isfile(out_p) and os.path.getsize(out_p) > 0

    apply("competition")
    print("[SELF-TEST] PASS plot_style (4 themes, 3 Morandi cmaps, 6 micro-polish rcParams, 3D helper)")
    return 0


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        sys.exit(self_test())
    print("Themes:", ", ".join(THEMES))
    print("Cmaps:", ", ".join(MORANDI_CMAPS))
