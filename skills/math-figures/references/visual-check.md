# 视觉自检闭环

画完不是结束——**每张图都要过「渲染预览 → 程序自检 → 原生 AI 读图复核 → 回改重渲」**，直到通过再交给论文。

**铁律**：没有渲染出 PNG 并实际看过、且程序审计无 FAIL 的图，不算完成。"写了绘图代码"不等于"出了图"。

```text
绘制 → ① 渲染预览 PNG → ② 程序自检 → ③ 原生视觉读图逐条核对
                                         ↓ 发现问题
       ⑤ 通过 ← ④ 回到源头改图 → 重渲染 → 再读图 ←──┘
```

## 分工

| 层 | 抓什么 | 用什么 |
|---|---|---|
| 程序自检（matplotlib） | 缺字乱码、渲染警告；文件 DPI/格式；遮挡/压数据/压图例/裁切/刻度重叠 | `figure_qa.py` + `layout_qa.py` + `validate_figure_src.py` |
| 程序自检（非 matplotlib） | 越界/文本互叠/线穿文字/同色不可见/对比度/字号折算/灰度与色盲可分 | `svg_audit.py`（自动探测 Chrome/Edge 真实排版，不看屏幕缩放） |
| AI 读图（原生多模态首选） | 语义是否讲对结论、观感是否畸形、比例是否被扭曲、歧义点 | `contact_sheet.py` 总览图或降采样预览 PNG（长边 ~1500–1600 px） |

**两层互补、不可替代**：程序能算的几何与数值约束交脚本；读图只抓**语义、比例与观感**，一言蔽之：**脚本抓"违规"，肉眼抓"丑和怪"。**

## 步骤

### 1. 渲染预览与程序自检
- matplotlib 图：调用 `figure_qa.render_preview(fig, ...)`、`layout_qa.audit_figure(fig)` 与 `figure_qa.audit_figure(fig)`，FAIL 先修；WARN 在读图时重点核对。
- 非 matplotlib 图（手写 SVG / drawio / PPT / AI 基底合成）：
  ```bash
  python ../_shared/scripts/svg_audit.py work/figures/mech_1.svg --png work/figures/mech_1.png --dpi 300 --json work/figures/mech_1.audit.json
  ```
  七条判据（`OVERFLOW/TOUCH`、`COLLIDE`、`OCCLUDE`、`MASKED`、`CONTRAST`、`TINY`、`COLLAPSE/MERGE`），退出码非 0 禁交付。

### 2. 原生多模态读图实操要点

1. **优先批量拼图**：多图用 `contact_sheet.py` 拼成一张总览图，直接用原生看图工具查看；仅对有疑点的图回看单图。
2. **先降采样再读**：600 dpi 大图常达 4000+ px，先等比缩到长边 1500–1600 px 再读；局部拥挤处裁切放大二次查看。
3. **结论落到具体位置**：必须指出“哪张图、哪个面板/区域、什么问题”；视觉怀疑的边缘问题回到源文件/像素数组证实，不把缩放假象当真缺陷。
4. **逐项检查清单**：
   - 乱码/豆腐块（中文 □□□、负号、上下标缺字）；
   - 文字裁切（标题、轴标签、图例、旋转刻度）；
   - 文字遮盖/重叠（图例压数据、标注互叠、字号过大挤占）；
   - 子图编号对齐（a/b/c 风格与位置统一）及间距互侵；
   - 比例畸形（柱状图宽高比约 3–4:1、折线坡度是否被夸张）；
   - 配色与灰度可分性、数据完整性、跨图同变量同色同量纲。

### 3. 回改对应表（改源头代码重渲，严禁 P 图）

| 读图发现 | 回改动作 |
|---|---|
| 中文/符号缺字方框 | 检查 `plot_style.py` 字体探测与 `axes.unicode_minus=False`；「注：」行去掉 mathtext 下标 |
| 文字被裁切 | `bbox_inches="tight"` / `constrained_layout=True`；缩短标签或换行 |
| 图例压数据 | `legend(..., bbox_to_anchor=(1.02, 1), frameon=False)` 移图外，或改曲线末端直标 |
| 标注互相叠 | 调整偏移、引线或删减冗余标注 |
| 比例畸形 | 调 `figsize` 宽高比与 `ax.margins(0.05)` 后重渲 |
| 子图不对齐/互侵 | 统一 axes 比例坐标打标签 + 重建 `GridSpec` |
| 配色难分/灰度糊 | Okabe-Ito 调色板 + 线型/marker/hatch 冗余编码 |
| 文字重叠（字号偏大） | 调小字号（保持投放后 ≥5–6pt）或外移标注 |

## 合规终检清单（导出后）

- [ ] 每个图数据能在 `work/results.json` 溯源，参数记入 `meta.params`
- [ ] 图号与题注和正文一致，图内无大标题
- [ ] 位图 DPI ≥ 300；无 JPEG；数据图矢量优先（SVG/PDF）
- [ ] `figure_qa.py check work/figures/* --min-dpi 300` 无 FAIL
- [ ] 最终投放宽度下 PDF 文字 ≥ 5pt（`audit_pdf_text.py`）
