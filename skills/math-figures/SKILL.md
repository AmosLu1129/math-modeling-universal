---
name: math-figures
description: 建模论文图表制作：先写一句话结论与 claim boundary，再按证据规划视觉论证，逐组件路由工具（实测值→确定性绘图／标签箭头→可编辑矢量／难画有机形态→先生成无文字基底图再叠矢量标注），生成出版级数据图与机理示意图（matplotlib / SVG 矢量 / 高级图模板），出图后跑「渲染预览 → 程序自检 → 原生读图复核 → 回改」自检闭环，输出 figures/ 与三线表。当需要把结果可视化、绘制模型机理示意图或格式化表格时使用。
---

# 图表制作

> **主 SOP 见 `references/figure-sop.md`**（论证契约与设计先于编码）；历次比赛踩坑与获奖图型标配见 `references/contest-lessons.md`；视觉闭环细则见 `references/visual-check.md`。

## 风格与技术通路（出图前查 `work/run_manifest.yaml`）

读取 `decisions.figure_style`（默认 `competition`）与 `decisions.figure_route`（均属 DEFAULTABLE）：
- **建模竞赛风格（默认）**：`_shared/scripts/plot_style.py`，单栏 ~3.5in / 双栏 ~7.2in，正文 7–9pt，最小 ≥6pt，色距 ≥30，对比度 ≥4.5:1。
- **期刊出版风格（可选）**：按 `references/nature-figure-essence.md`，5pt 渲染字形下限，色距 ≥45，三阶证据结构与家族一致性配色。

| 通路项 | 默认值 | 可覆盖选项 | 说明 |
|---|---|---|---|
| `engine` | `matplotlib`（数据图）/ `svg`（机理图） | `matplotlib` / `svg` / `drawio` / `pptx` / `ai-base+svg` / `vega-lite` | 手算坐标通路必须过 `svg_audit.py` |
| `thresholds` | `competition` | `competition` / `journal` / `screen` | 按最终投放宽度折算字号与对比度 |
| `color_palette` | `plot_style.PALETTE` | 期刊族系色板 | 改色板重跑 `svg_audit` 查灰度与色盲可分 |
| `export` | `("png", "svg", "pdf")` 元组 | — | 禁 JPEG；导出格式**必须写元组** |
| `print_width_mm` | `160` | 按论文实际插图宽度填 | 直接决定 `TINY` 字号折算 |

## 输入输出

- 输入：`work/results.json`、`work/final_models.md`、`work/eda_report.md`、`work/data_dictionary.md`
- 输出：`work/figures/*.png`（关键图另出 `.svg`/`.pdf`）、`work/tables/*.{csv,tex}`、`work/figures/qa_ledger.md`

## 核心工作流

### 1. 先理解与定契约（禁止直接画图）
1. 读 `results.json` 与 `final_models.md`，确认每个数字的含义、单位、样本量；图所用参数并入 `results.json` 的 `meta.params`。
2. **先写一句话结论 + claim boundary**：说不出图要捍卫什么命题就不要画。
3. **先证据后图型**：按「原始数据 / 中间过程 / 最终结果」三类图体系规划，**同题全图覆盖 ≥3 种不同图型**；参考 `references/chart-guide.md` 与 `references/pitfalls.md`，高级图优先复用 `_shared/scripts/advanced_templates/`（11 个模板）。
4. **参考解构（可选）**：有真实参考图做结构映射；无参考时明确声明「本图为原创设计」并继续。

### 2. 数据图与机理图选型纪律
- **数据图**：`plot_style.py` 需内联或可被 `code/` 独立导入，自动探测跨平台中文字体（Windows `Microsoft YaHei`/`SimHei`/`SimSun`，macOS `PingFang SC`/`Songti SC`，Linux `Noto Sans CJK`）；`svg.fonttype='none'`、`pdf.fonttype=42`。
- **样式硬原则**：
  - **图内不写整图大标题**，标题交给论文 `\caption{}` / `#figure(caption: ...)`；
  - **标注精简**：仅标必要类别名与 30 秒读懂结论的关键数值，单位与明细进正文/图注；
  - **语义与色盲安全**：蓝=本方/核心方法，绿=正向，红=基线；禁 `rainbow`/`jet`；加线型/marker/hatch 灰度冗余。
- **机理示意图优先级**：
  1. **首选 `matplotlib` 框图**（`FancyBboxPatch` + `annotate`，公式用 `math_fontfamily="stix"` 课本式排版，`layout_qa.py` 自动防遮挡）；
  2. **次选 手写 SVG**（`viewBox` 等于最终投放尺寸，用 `render_svg.py` 转 PNG，**必须过 `svg_audit.py`**）；
  3. **备选 DrawIO**：探测系统安装（Windows `draw.io.exe` / macOS `draw.io`），导出后过 `svg_audit.py`；
  4. **可选 AI 基底图 + SVG 标注**（仅需生物/物理写实外观时）：若当前 Agent 具备生图能力（工具或子代理），优先生成**纯无文字低饱和基底图**（命令行兜底可用 `ai_figure_gen.py`），再用 SVG 叠中文标注并过 `svg_audit.py`，详见 `references/mechanism-ai-guide.md`。

### 3. 自检闭环与提速纪律（每张图必过）

> **铁律：没有渲染出 PNG、未过程序审计、未用原生视觉复核的图，不算完成。**

1. **一次批量 + 两档提速**：一个 `make_figures.py` 批量出图；迭代轮设 `MATHFIG_DRAFT=1` 写到 `work/scratch/`，定稿再落 `work/figures/`。
2. **静态源码预检**：`python _shared/scripts/validate_figure_src.py <绘图脚本.py>` 无 FAIL（默认 `--mode competition` 要求 300 dpi，期刊投稿追加 `--mode journal` 要求 600 dpi）。
3. **几何与样式程序审计**：
   - matplotlib 图：在 `savefig` 前调用 `layout_qa.audit_figure(fig)`（防 `OVERLAP`/`DATA`/`LEGEND`/`CLIP`/`TICK`）与 `figure_qa.audit_figure(fig)`（缺字守卫）；机理框图追加 `mech_text_audit.py`。
   - 非 matplotlib 图（SVG/DrawIO/PPT/AI 合成）：`python _shared/scripts/svg_audit.py work/figures/mech_1.svg --png work/figures/mech_1.png --dpi 300`。
   - 全量导出检查：`python _shared/scripts/figure_qa.py check "work/figures/*" --min-dpi 300`（已内置通配符与目录展开，兼容 Windows PowerShell）；最终投放尺寸下用 `audit_pdf_text.py <图.pdf> --min-pt 5` 核对字号。
4. **Contact Sheet 一次复核**：用 `python _shared/scripts/contact_sheet.py work/figures --panel-width 1100` 拼总览图，直接用原生多模态视觉（原生看图/文件读取工具）读一次总览图查语义、比例畸形与观感；仅对有疑点的单图回看原图并改源头代码重渲。
5. **登记台账**：将四步结论逐图写入 `work/figures/qa_ledger.md`。

## 速查选图决策

| 想表达 | 首选 | 该避免 |
|---|---|---|
| 组间比较（$n\ge 10$ / $n<10$） | 箱线/小提琴+散点 / stripplot | 裸均值柱、3D 柱 |
| 两变量关系 / 拟合对比 | 散点+回归+CI / 真实-预测散点+$y=x$ | 非有序 x 连折线 |
| 分布 / 占比构成 | 直方图/KDE / 横向排序柱状 | 饼图 |
| 多指标对比 / 灵敏度 | 雷达图（$\le 8$ 维）/ 森林图 / 折线误差带 | 纯表代替对比图 |
| 分类 / 关联 | ROC/PR / 紧凑混淆矩阵 / 相关热力图 | 类别不平衡单看准确率 |
