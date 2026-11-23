#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""出版图版面自检：在代码里检测「文字互相遮挡 / 标注压图例 / 文本越出画幅」。

为什么需要它：AI 读图复核能发现遮挡，但每轮都要外部模型调用 + 人工判断；而遮挡、
裁切、图例压数据这些是**几何事实**，matplotlib 渲染后可以直接算出来。所以它属于自检
闭环的「程序自检」步骤（渲染 → layout_qa → figure_qa/字体审计 → 读图复核），让读图
复核专注于语义问题（配色可分性、比例畸形、标注有没有讲对结论）。

用法（出图脚本里，save 之前）：
    from layout_qa import audit_figure
    problems = audit_figure(fig, name="fig4_pareto")   # 打印 [LAYOUT] 行 + 返回清单

判据：
  - OVERLAP : 两个内容文本（ax.text / annotate）包围盒相交 > 6% 较小盒面积
  - DATA    : 内容文本压在数据标记上（散点/带 marker 的线）
  - LEGEND  : 内容文本压住图例框；或图例框盖住可见数据标记
  - CLIP    : 内容文本越出其子图坐标区 / 被画布边缘裁切（>0.02 英寸）
  - TICK    : 同轴刻度标签互相重叠 >35%
"""
from __future__ import annotations

import sys

from matplotlib.text import Annotation, Text

OVERLAP_FRACTION = 0.06
CLIP_TOLERANCE_IN = 0.02
# 引线命中半径（英寸）：约等于 5pt marker 的视觉半径，再小就是擦边
ARROW_HIT_RADIUS_IN = 0.05


def _bbox(actor, renderer):
    try:
        box = actor.get_window_extent(renderer=renderer)
    except Exception:  # noqa: BLE001 - 个别 artist 在无显示环境下没有 extent
        return None
    if box.width <= 0 or box.height <= 0:
        return None
    return box


def _text_bbox(artist, renderer):
    """文字本身的包围盒。Annotation.get_window_extent() 会并上 arrow_patch 的包围盒，
    引线一拉就变成覆盖半个图的大矩形，必须取 Text 的部分，否则引线会被误判成遮挡。"""
    if isinstance(artist, Annotation):
        try:
            artist.update_positions(renderer)
            box = Text.get_window_extent(artist, renderer=renderer)
        except Exception:  # noqa: BLE001
            return _bbox(artist, renderer)
    else:
        box = artist.get_window_extent(renderer=renderer)
    if box.width <= 0 or box.height <= 0:
        return None
    return box


def _intersection_fraction(a, b) -> float:
    ix = max(0.0, min(a.x1, b.x1) - max(a.x0, b.x0))
    iy = max(0.0, min(a.y1, b.y1) - max(a.y0, b.y0))
    if ix <= 0 or iy <= 0:
        return 0.0
    smaller = min(a.width * a.height, b.width * b.height)
    return (ix * iy) / smaller if smaller > 0 else 0.0


def _label(actor) -> str:
    text = " ".join(str(getattr(actor, "get_text", lambda: repr(actor))()).split())
    if not text:
        return "<无文字>"
    return text[:34] + ("…" if len(text) > 34 else "")


def _ax_key(fig, ax) -> str:
    axes = fig.axes
    return "" if len(axes) <= 1 else f"[面板 {axes.index(ax) + 1}]"


def _uses_axes_fraction(artist, ax) -> bool:
    """文本是否按坐标区分数定位（面板标签等），而非数据坐标。"""
    transform = artist.get_transform()
    # 只比身份：transData 组合链里本来就含 transAxes，contains_branch 会把
    # 数据坐标标注误判成分数坐标；== 又是结构比较（xlim=ylim=(0,1) 时相同）。
    return transform is ax.transAxes or transform is ax.get_figure().transFigure


def _axes_box(ax):
    """Axes.get_window_extent 在不同版本签名不一，直接用 ax.bbox（显示坐标）。"""
    box = getattr(ax, "bbox", None)
    if box is None or box.width <= 0 or box.height <= 0:
        return None
    return box


def _content_texts(ax):
    """内容文本 = 手写标注与 ax.text；不含标题/轴标签/刻度（由布局引擎管理）。"""
    return [a for a in ax.texts if str(a.get_text()).strip()]


def _is_nolegend(artist) -> bool:
    """只排除显式 `_nolegend_`；matplotlib 自动命名的 `_line0`/`_child1` 是真实数据线，
    按 startswith("_") 过滤会把无标签数据线全部看成隐藏，遮挡就检不出来了。"""
    return str(artist.get_label() or "") == "_nolegend_"


def _data_points(ax):
    """图上所有可见数据点的显示坐标（散点 + 带 marker 的线），用于引线穿越判定。"""
    pts = []
    for line in ax.get_lines():
        if not line.get_visible() or _is_nolegend(line):
            continue
        if line.get_marker() in (None, "", "None"):
            continue
        data = line.get_xydata()
        if data is None:
            continue
        pts.extend((float(x), float(y)) for (x, y) in line.get_transform().transform(data))
    for collection in list(getattr(ax, "collections", [])):
        try:
            offsets = collection.get_offsets()
        except Exception:  # noqa: BLE001
            continue
        if offsets is None or len(offsets) == 0:
            continue
        transform = (collection.get_offset_transform() if hasattr(collection, "get_offset_transform")
                     else collection.get_transform())
        pts.extend((float(x), float(y)) for (x, y) in transform.transform(offsets))
    return pts


def _leader_path_points(artist):
    """annotate 引线的显示坐标采样点（FancyArrowPatch 的路径本身即显示坐标）。"""
    patch = getattr(artist, "arrow_patch", None)
    if patch is None:
        return []
    try:
        path = patch.get_path()
        if path is None or len(path.vertices) < 2:
            return []
        # Path.interpolated 把折线沿弧长加密，避免长引线只取端点而漏掉中途穿越
        dense = path.interpolated(steps=24).vertices
        return [(float(x), float(y)) for x, y in dense]
    except Exception:  # noqa: BLE001
        return []


def _line_samples(fig):
    """所有坐标区的连续线采样点（twinx 兄弟轴的数据线也要参与遮挡判定）。"""
    samples = []
    for ax in fig.axes:
        for line in ax.get_lines():
            if not line.get_visible() or _is_nolegend(line):
                continue
            if line.get_linestyle() in ("None", "none", "") or line.get_marker() not in (None, "", "None"):
                continue
            data = line.get_xydata()
            if data is None or len(data) == 0:
                continue
            if len(data) <= 2:  # 参考线（axhline/axvline）只有两端点，压住也不是数据
                continue
            samples.extend((float(x), float(y)) for (x, y) in line.get_transform().transform(data))
    return samples


def _line_samples_under(samples, box) -> int:
    return sum(1 for (x, y) in samples if box.x0 <= x <= box.x1 and box.y0 <= y <= box.y1)


def _points_under_box(ax, box):
    """返回 (被遮住的散点/标记数, 被遮住的连续线采样点数)。"""
    n_markers, n_line = 0, 0
    for line in ax.get_lines():
        if not line.get_visible() or _is_nolegend(line):
            continue
        marker = line.get_marker()
        has_marker = marker not in (None, "", "None")
        if line.get_linestyle() in ("None", "none", "") and not has_marker:
            continue
        points = line.get_xydata()
        if points is None or len(points) == 0:
            continue
        for (x, y) in line.get_transform().transform(points):
            if box.x0 <= x <= box.x1 and box.y0 <= y <= box.y1:
                if has_marker:
                    n_markers += 1
                else:
                    n_line += 1
    for collection in list(getattr(ax, "collections", [])):
        try:
            offsets = collection.get_offsets()
        except Exception:  # noqa: BLE001
            continue
        if offsets is None or len(offsets) == 0:
            continue
        # scatter 的 get_transform() 是 IdentityTransform（路径已含标记形状），
        # 数据坐标在 get_offset_transform() 上；旧版本回退到 get_transform()。
        offset_transform = collection.get_offset_transform() if hasattr(
            collection, "get_offset_transform") else collection.get_transform()
        for (x, y) in offset_transform.transform(offsets):
            if box.x0 <= x <= box.x1 and box.y0 <= y <= box.y1:
                n_markers += 1
    return n_markers, n_line


def _markers_under_box(ax, box) -> int:
    """落在图例框内的可见数据点数（纯参考线不计）。"""
    n_markers, n_line = _points_under_box(ax, box)
    return n_markers + n_line


def _figure_box(fig, renderer):
    from matplotlib.transforms import Bbox

    return Bbox.from_extents(0.0, 0.0, float(fig.bbox.width), float(fig.bbox.height))


def audit_figure(fig, name: str = "figure", verbose: bool = True):
    """返回 [(level, check_id, detail)]；空列表 = 版面干净。调用点：save 之前。"""
    problems = []
    if fig.canvas is None or not hasattr(fig.canvas, "get_renderer"):
        problems.append(("WARN", "BACKEND", f"{name}: 无可测量渲染器，跳过版面自检"))
        return problems
    # 必须先 draw()：未绘制时 get_renderer() 返回的是默认画幅（640x480）渲染器，
    # 文本包围盒会算到错误的坐标系里，导致大面积假 CLIP。
    try:
        fig.canvas.draw()
    except Exception as exc:  # noqa: BLE001
        problems.append(("WARN", "BACKEND", f"{name}: 画布无法绘制（{exc}），版面自检结果不可信"))
    renderer = fig.canvas.get_renderer()

    # 跨子图统计采样点：twinx 叠加轴（共享显示坐标的兄弟坐标区）上压住数据，
    # 只看本坐标区的点会漏检。
    all_points = [pt for other in fig.axes for pt in _data_points(other)]
    all_line_samples = _line_samples(fig)

    for ax in fig.axes:
        key = _ax_key(fig, ax)
        texts = _content_texts(ax)
        legend = ax.get_legend()
        legend_box = _bbox(legend, renderer) if legend is not None else None
        ax_box = _axes_box(ax)

        data_points = all_points
        for i, artist in enumerate(texts):
            box = _text_bbox(artist, renderer)
            if box is None:
                continue
            # 3b) 引线穿过数据点：读者会误以为标注指向被穿过的点
            leader = _leader_path_points(artist)
            if leader and isinstance(artist, Annotation):
                # 引线末端本来就落在被指向的点上，那不算穿越
                try:
                    target_x, target_y = artist.get_transform().transform([artist.xy])[0]
                except Exception:  # noqa: BLE001
                    target_x = target_y = None
                radius = ARROW_HIT_RADIUS_IN * max(fig.dpi, 1.0)
                hits = sum(1 for (dx, dy) in data_points
                           if (target_x is None or (dx - target_x) ** 2 + (dy - target_y) ** 2 > radius ** 2)
                           and any(abs(dx - lx) <= radius and abs(dy - ly) <= radius
                                   for (lx, ly) in leader))
                if hits:
                    problems.append(("FAIL", "ARROW",
                                     f"{name}{key} 引线穿过 {hits} 个数据点：「{_label(artist)}」"))
            for other in texts[i + 1:]:
                other_box = _text_bbox(other, renderer)
                frac = _intersection_fraction(box, other_box) if other_box else 0.0
                if frac > OVERLAP_FRACTION:
                    problems.append(("FAIL", "OVERLAP",
                                     f"{name}{key} 文本互相遮挡 {frac * 100:.0f}%：「{_label(artist)}」×「{_label(other)}」"))
            if legend_box is not None:
                frac = _intersection_fraction(box, legend_box)
                if frac > OVERLAP_FRACTION:
                    problems.append(("FAIL", "LEGEND",
                                     f"{name}{key} 标注压住图例 {frac * 100:.0f}%：「{_label(artist)}」"))
            # 子图外标注只有用数据坐标时才是坐标写错；transAxes 定位（面板标签 a/b）
            # 本来就画在坐标区外，不算越界。必须用身份比较：Transform 的 ==
            # 是结构比较，当 xlim/ylim 都是 (0,1) 时 transData 会「等于」transAxes。
            in_axes_coords = not _uses_axes_fraction(artist, ax)
            n_markers, n_line = _points_under_box(ax, box)
            n_line += _line_samples_under(all_line_samples, box)
            if n_markers:
                problems.append(("FAIL", "DATA",
                                 f"{name}{key} 标注盖住 {n_markers} 个数据标记：「{_label(artist)}」"))
            elif n_line > 2:
                problems.append(("WARN", "DATA",
                                 f"{name}{key} 标注压在一条数据线上（{n_line} 个采样点）：「{_label(artist)}」"))
            if ax_box is not None and in_axes_coords:
                overflow = (max(0.0, ax_box.x0 - box.x0, box.x1 - ax_box.x1)
                            + max(0.0, ax_box.y0 - box.y0, box.y1 - ax_box.y1))
                overflow /= max(fig.dpi, 1.0)
                if overflow > CLIP_TOLERANCE_IN:
                    problems.append(("WARN", "CLIP",
                                     f"{name}{key} 标注越出子图 {overflow:.2f} 英寸：「{_label(artist)}」"))

        if legend_box is not None:
            hidden = _markers_under_box(ax, legend_box)
            if hidden:
                problems.append(("WARN", "LEGEND",
                                 f"{name}{key} 图例框盖住 {hidden} 个数据标记（改外置图例或缩小 marker/留白）"))

        for axis, labels in (("x", ax.get_xticklabels()), ("y", ax.get_yticklabels())):
            boxes = [(b, lab) for b, lab in ((_bbox(l, renderer), l) for l in labels) if b is not None]
            for i, (box_i, lab_i) in enumerate(boxes):
                for box_j, lab_j in boxes[i + 1:]:
                    frac = _intersection_fraction(box_i, box_j)
                    if frac > 0.35:
                        problems.append(("WARN", "TICK",
                                         f"{name}{key} {axis} 轴刻度标签重叠 {frac * 100:.0f}%：「{lab_i.get_text()}」×「{lab_j.get_text()}」"))

    fig_box = _figure_box(fig, renderer)
    for ax in fig.axes:
        for artist in _content_texts(ax) + [ax.xaxis.label, ax.yaxis.label, ax.title]:
            box = _text_bbox(artist, renderer)
            if box is None:
                continue
            outside = (max(0.0, -box.x0, box.x1 - fig_box.x1) + max(0.0, -box.y0, box.y1 - fig_box.y1))
            outside /= max(fig.dpi, 1.0)
            if outside > CLIP_TOLERANCE_IN:
                problems.append(("FAIL", "CLIP",
                                 f"{name}{_ax_key(fig, ax)} 文本被画布裁切 {outside:.2f} 英寸：「{_label(artist)}」"))

    if verbose:
        if not problems:
            print(f"[LAYOUT] PASS：{name} 无遮挡 / 裁切 / 图例压数据")
        for level, check_id, detail in problems:
            print(f"[LAYOUT] {level}/{check_id}: {detail}")
    return problems


def _self_test() -> int:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(4, 3))
    ax.plot([1, 2, 3], [1, 2, 3], label="Series A")
    ax.legend(loc="upper left")
    ax.text(1.9, 1.2, "clean note")
    assert not audit_figure(fig, name="clean", verbose=False), "干净图不应报错"

    ax.text(1.92, 1.22, "overlapping note")
    bad = audit_figure(fig, name="crowded", verbose=False)
    assert any(cid == "OVERLAP" for _, cid, _ in bad), bad
    assert any("overlapping note" in d for _, _, d in bad), bad

    fig2, ax2 = plt.subplots(figsize=(4, 3))
    ax2.set_xlim(0, 1)
    ax2.set_ylim(0, 1)
    ax2.text(-0.12, 0.5, "left of the data area")
    clipped = audit_figure(fig2, name="clipped", verbose=False)
    assert any(cid == "CLIP" for _, cid, _ in clipped), clipped

    fig2b, ax2b = plt.subplots(figsize=(4, 3))
    ax2b.set_xlim(0, 1)
    ax2b.set_ylim(0, 1)
    ax2b.text(-0.02, 1.02, "a", transform=ax2b.transAxes, fontweight="bold")
    assert not audit_figure(fig2b, name="panel-label", verbose=False), "面板标签不应报 CLIP"

    fig3, ax3 = plt.subplots(figsize=(4, 3))
    ax3.plot([1, 2, 3], [3, 2, 1], marker="o", ls="-", label="Series B")
    ax3.legend(loc="upper left", framealpha=1.0)
    covered = audit_figure(fig3, name="legend-covers-data", verbose=False)
    assert any(cid == "LEGEND" and "数据标记" in d for _, cid, d in covered), covered

    fig4b, ax4b = plt.subplots(figsize=(4, 3))
    ax4b.scatter([1, 2, 3], [1, 2, 3], s=40)
    ax4b.text(1.4, 1.9, "label on top of a point")
    on_data = audit_figure(fig4b, name="text-on-data", verbose=False)
    assert any(cid == "DATA" for _, cid, _ in on_data), on_data

    # 引线（annotate 的 arrow）穿过数据点不等于文字遮挡：只按文字包围盒判定
    fig5b, ax5b = plt.subplots(figsize=(4, 3))
    ax5b.scatter([1, 2, 3], [1, 2, 3], s=40)
    ax5b.annotate("corner note", xy=(2.6, 2.6), xytext=(0.06, 0.92),
                  textcoords="axes fraction", arrowprops=dict(arrowstyle="->"))
    leader = audit_figure(fig5b, name="leader-line", verbose=False)
    assert not any(cid in ("DATA", "ARROW") for _, cid, _ in leader), leader

    fig6b, ax6b = plt.subplots(figsize=(4, 3))
    ax6b.scatter([1, 2, 3], [1, 2, 3], s=40)
    ax6b.annotate("note", xy=(3.0, 3.0), xytext=(0.05, 0.95),
                  textcoords="axes fraction", arrowprops=dict(arrowstyle="-"))
    crossed = audit_figure(fig6b, name="arrow-crosses-data", verbose=False)
    assert any(cid == "ARROW" for _, cid, _ in crossed), crossed

    fig7b, ax7b = plt.subplots(figsize=(6, 3))
    ax7b.set_xlim(0, 20)
    ax7b.set_ylim(0, 10)
    twin = ax7b.twinx()
    twin.set_ylim(0, 10)
    twin.plot(list(range(20)), [8.5] * 20, lw=1.0)
    ax7b.text(4.0, 8.45, "note over the twin line")
    twin_hit = audit_figure(fig7b, name="text-over-twin-line", verbose=False)
    assert any(cid == "DATA" for _, cid, _ in twin_hit), twin_hit
    plt.close("all")
    print("layout_qa self-test: PASS (8 cases)")
    return 0


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--self-test" in argv:
        return _self_test()
    print(__doc__)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
