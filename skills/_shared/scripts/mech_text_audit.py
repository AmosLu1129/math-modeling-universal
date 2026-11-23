#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
机理图文字布局程序化检测（2026-08-15 沉淀，2023 国赛 C 实测教训）。

背景：视觉模型对"文字是否真的重叠/贴边"判断不可靠（实测 vision 多次报 PASS 但
实际存在文字重叠：分式行行距不足、多框 y 范围交叉导致跨框压叠）。本脚本用
matplotlib 的 get_window_extent 做精确 bbox 检测，作为 vision 复核前的确定性闸门。

用法（在绘图脚本末尾调用）：
    import sys; sys.path.insert(0, "<_shared/scripts>")
    from mech_text_audit import audit_mech_text
    audit_mech_text(fig, ax, boxes, tol=2.0)

参数：
    fig    : matplotlib Figure（已 draw 或 savefig 前）
    ax     : 当前 Axes（transData 转换用）
    boxes  : 所属框列表 [(x0, y0, x1, y1), ...]（数据坐标，含 pad 的框范围）
    tol    : 溢出容差（磅，默认 2.0；与坐标轴范围无关）
    boxes  : 允许为 [(x, y, w, h)] 或 [(x0, y0, x1, y1)]（数据坐标）

返回：
    (n_overlap, n_overflow)，均为 0 表示通过；打印问题详情。
"""
from __future__ import annotations

import matplotlib.text


def _display_box(ax, bb):
    inv = ax.transData.inverted()
    p1 = inv.transform((bb.x0, bb.y0))
    p2 = inv.transform((bb.x1, bb.y1))
    return (min(p1[0], p2[0]), min(p1[1], p2[1]), max(p1[0], p2[0]), max(p1[1], p2[1]))


def audit_mech_text(fig, ax, boxes, tol=2.0, th_x=None, th_y=None):
    """检测 1) 文字两两重叠 2) 框内文字溢出自己的框。

    tol 现在是**磅**（原为数据单位）：机理图常用 0~1 分数坐标画布，数据单位的阈值
    （x>0.5、y>0.2）在这种画布上等于半个图，永远检不出重叠。改成显示坐标 + 磅后与
    坐标轴范围无关。boxes 用数据坐标 (x0, y0, x1, y1)；中心落在框外的文字视为「无框
    文字」（层标签、图例、注行等），不参与溢出判定。
    """
    import matplotlib

    fig.canvas.draw()
    points = fig.dpi / 72.0
    pad = tol * points

    items = []
    for t in fig.findobj(matplotlib.text.Text):
        if not t.get_text().strip():
            continue
        try:
            bb = t.get_window_extent()
        except Exception:  # noqa: BLE001
            continue
        if bb.width <= 0 or bb.height <= 0:
            continue
        items.append((" ".join(t.get_text().split())[:22], bb))

    overlaps = []
    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            n1, a = items[i]
            n2, b = items[j]
            ix = max(0.0, min(a.x1, b.x1) - max(a.x0, b.x0))
            iy = max(0.0, min(a.y1, b.y1) - max(a.y0, b.y0))
            if ix <= 0 or iy <= 0:
                continue
            frac = (ix * iy) / max(1e-9, min(a.width * a.height, b.width * b.height))
            if frac > 0.06:
                overlaps.append((n1, n2, round(frac * 100)))

    overflows = []
    framed = 0
    for name, text_bb in items:
        cx, cy = (text_bb.x0 + text_bb.x1) / 2, (text_bb.y0 + text_bb.y1) / 2
        # 取「最小的包含框」：分组底框与气泡框会嵌套，先匹配到的大框会把
        # 气泡内文字的溢出检查整个吞掉（等于不检查）。
        owner = None
        owner_area = float("inf")
        for (x0, y0, x1, y1) in boxes:
            b0 = ax.transData.transform((x0, y0))
            b1 = ax.transData.transform((x1, y1))
            box_bb = (min(b0[0], b1[0]), min(b0[1], b1[1]), max(b0[0], b1[0]), max(b0[1], b1[1]))
            if box_bb[0] <= cx <= box_bb[2] and box_bb[1] <= cy <= box_bb[3]:
                area = (box_bb[2] - box_bb[0]) * (box_bb[3] - box_bb[1])
                if area < owner_area:
                    owner, owner_area = box_bb, area
        if owner is None:
            continue
        framed += 1
        if (text_bb.x0 < owner[0] - pad or text_bb.x1 > owner[2] + pad
                or text_bb.y0 < owner[1] - pad or text_bb.y1 > owner[3] + pad):
            overflows.append((name, f"超出所属框 {(text_bb.x0 - owner[0]) / points:+.1f}/"
                                    f"{(text_bb.x1 - owner[2]) / points:+.1f} pt (x), "
                                    f"{(text_bb.y0 - owner[1]) / points:+.1f}/"
                                    f"{(text_bb.y1 - owner[3]) / points:+.1f} pt (y)"))

    for n1, n2, pct in overlaps:
        print(f"[FAIL] 文字重叠: '{n1}' x '{n2}' (相交 {pct}%)")
    for name, msg in overflows:
        print(f"[FAIL] 文字溢出: '{name}' {msg}")
    if not overlaps and not overflows:
        print(f"[PASS] 机理图文字无重叠；{framed} 个带框文字全部在框内")
    return len(overlaps), len(overflows)


if __name__ == "__main__":
    print("作为模块调用：from mech_text_audit import audit_mech_text")
