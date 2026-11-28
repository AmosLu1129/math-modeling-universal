---
name: math-paper-writing
description: 撰写数学建模竞赛论文（国赛/MCM/ICM/华为杯等）：写作前按 run_manifest.yaml 确定竞赛模板与排版引擎（LaTeX/Typst/Word，模板库内置 14 中 + 3 英竞赛，跨平台字体就绪），按获奖结构与篇幅配比组织全文，摘要浓缩方法与量化结果，完整呈现迭代后的最终模型公式（对照 final_models.md）。当需要把建模结果写成竞赛论文、组织结构与摘要时使用。
---

# 论文写作

> LaTeX 宏包、三线表转义与页数控制避坑细则见 `references/latex-pitfalls.md`；竞赛规范与 AI 披露模板见 `_shared/references/competition-rules.md` 与 `_shared/templates/ai_disclosure/`。

## 输入输出

- 输入：`work/brief.md`、`work/final_models.md`、`work/validation_report.md`、`work/figures/`、`work/tables/`、`work/results.json`
- 模板库：`_shared/templates/competition/`（14 套中文 + 3 套英文竞赛 × Typst/LaTeX 双版本）
- 输出：`output/paper/main.tex`（或 `main.typ`）→ `output/paper/paper.pdf`

## 步骤 0：确认排版引擎与竞赛模板

正式动笔前检查 `work/run_manifest.yaml`（属于 DEFAULTABLE 决策；仅当会改变合规性时升为 BLOCKING）：

1. **排版引擎**：
   - **LaTeX（`xelatex` 两遍编译）**：竞赛默认主流，需交付 `.tex` 源码或严格匹配官方 LaTeX 模板时首选；所有模板已移除 `fontset=mac` 写死，支持 Windows/macOS/Linux 自动字体适配。
   - **Typst（`typst compile main.typ`）**：若竞赛**仅提交 PDF** 且本机已装 `typst`，推荐优先使用——编译毫秒级、无宏包冲突与转义静默吞格坑，且 17 套竞赛均有对应 Typst 模板。
   - **Word**：无编译环境时兜底。
2. **竞赛模板选择**：将 `_shared/templates/competition/` 下对应目录（如 `zh/cumcm-latex`、`zh/cumcm`、`en/mcm-latex`、`en/mcm`、`zh/huaweibei-latex`、`zh/mathorcup-latex` 等，共 14 中 + 3 英 + `default`）整体复制到 `output/paper/`，按模板既有结构写作，按赛题小问数增减章节。

## 获奖论文结构骨架（含 `o_award` 叙事与四件套展开）

1. **Problem → Solution 唯一主线与奥卡姆推进骨架**：全篇及每节禁止流水账（*"First we did A, then we did B"*），一律围绕 S4 确立的**唯一核心洞察**采用 **`现实矛盾 / 直觉陷阱（Problem）→ 传统简化为何失效（Tension）→ 核心机制洞见（Insight）→ 数学建构与实证定案（Solution）`** 推进；任何脱离主线的冗余模块删去或挪入附录，问题分析必配全局逻辑流程图，让评审 30 秒看懂数据流与机制闭环。
2. **术语降密与「代码 ↔ 学术命名」隔离**：符号说明用三列表 `符号 | 含义 | 单位/取值`；严格对照 `model_doc.md` 的学术展示命名表，**正文段落、三线表与图内严禁出现裸露 `snake_case` 变量名、工程质检词（如 `20/20 PASS` / `Safety Standards` / `Code-to-Academic`）或配色/渲染术语（`Morandi`、`terracotta`、`300 DPI HTML`）**。首次出现的专业术语（无论优化、概率还是机理词汇）必须用一句话大白话解释其直觉含义，能用日常清晰措辞绝不堆砌炫技黑话。
3. **每个小问按“答案形态”闭环展开**（不鼓励为凑量堆公式）：
   - ① **机理直觉导入**（阐明线性或稳态简化为何在边界或耦合下失效）；
   - ② **完整带编号核心公式**（对照 `final_models.md` 与 `results.json` 直接推导至可算形式，只保留服务核心决策的关键编号方程）；
   - ③ **标准化 `algorithm` 伪代码框**（仅核心搜索/反演算法配 1–2 个伪代码框，模板内置 `algorithm` / `algpseudocode`）；
   - ④ **基线对照与受众匹配交付**（必配同口径基线对比或消融结论；若有明确非技术委托方，备忘录/操作检查单须**零公式、纯可执行动作**）。
4. **Summary Sheet“10 分钟评委速读”准则（最后写）**：严格收束在第 1 页并保留充足留白，按四段式推进：**① 一句话大白话界定问题 → ② 一句话讲透核心洞察（首段禁用带下标数学符号与生僻术语，让外行初筛评委 30 秒读懂）→ ③ 每问 1–2 个圆整核心数字（匹配输入精度的 2–3 位有效数字，严禁数字墙，优先 `\ResSmart{path}` / `\ResPctSmart{path}`）→ ④ 一句话可执行建议**。
5. **AI 使用披露**：国赛附录说明 / MCM Report on Use of AI，模板直接复用 `_shared/templates/ai_disclosure/`（内容取自真实迭代日志与人工纠错案例，严禁编造）。

## 篇幅预算（按 `run_manifest.yaml` 运行档位控制）

| 档位 | 国赛（CUMCM） | 美赛（MCM/ICM，不含 AI 披露） | 内容与视觉密度要求 |
|---|---|---|---|
| `competition` | 正文（含摘要）≤20 页（建议 15–19 页） | 总计 ≤25 页（建议 16–20 页） | 稳健保 M/F 紧凑高质量闭环 |
| **`o_award`** | **18–20 页主文 + 9–12 图 + 精炼核心公式** | **21–24 页主文 / 8,500–11,500 英文词 / 9–13 张单结论清晰图 / 1–2 伪代码框** | **靠机制穿透力、核心输入与假设透明表、基线实证对照与「一图一结论」撑起篇幅；严禁为凑页数或指标堆砌冗余子模型** |

> 国赛 AI 披露与代码/长表进附录（不计 20 页上限）；美赛 **Report on Use of AI** 放文末且不计入 25 页上限。

## 硬性规则（O 奖与零硬伤底线）

1. **数字事实表与单源宏绑定前置**：动笔前必须运行 `fact_sheet.py` 与 `export_paper_macros.py`：
   ```bash
   python _shared/scripts/fact_sheet.py --results work/results.json --out work/fact_sheet.md
   python _shared/scripts/export_paper_macros.py --results work/results.json --out-tex output/paper/results_macros.tex --tables-dir work/tables --format-mode smart
   ```
   正文、摘要、表格、备忘录**及 HTML/SVG 示意图**中的所有关键数值优先统一绑定 `results.json` 导出宏（`\ResSmart{path}` / `\ResPctSmart{path}` 或 `#res_smart`）与 `\input{../../work/tables/*.tex}`，**严禁手写硬编码或未经校验的派生数**；重跑后须先刷新宏与表格再重编译。**TeX 宽表与对齐符红线**：宽表一律套用 `\resizebox{\textwidth}{!}{%` 且行尾必须是裸 `%`（严禁 `\%`）；全局 `&`→`\&` 转义严禁作用于 `cases`/`aligned`/`align`/`matrix`/`array` 等数学对齐环境内部。**写后自查**：动笔与终审均须通过 `paper_qa.py --mode o_award`。
2. **有效数字匹配输入精度 + 表内符号守卫**：输出精度必须与输入估计匹配（通用 **2–3 位有效数字**，高不确定性估算给出区间），严禁把 $\pm 20\%$ 估计输入算出 4–5 位虚假精度、将越界归一化指标（如 $> 1$）直接写入正文，或拿 `1e-8` 类程序收敛残差当作模型精度亮点；同时检查每张表的**同列正负号与单位完全一致**（禁止同一变化列前两行带 `-`、第三行漏写 `-`）。
3. **核心输入参数与分级假设全部建表可见**：模型引用的核心参数表、目录/装备表、地形/环境基础参数，以及每条假设的来源分级（`[文献/数据支撑]` / `[合理工程估计]` / `[主观拍定先验]`），必须在正文或附录中明确列成表格供评委核查。
4. **最终公式、指标定义域与代码逐行一致**：每问对照 `work/final_models.md` 给出完整最终方程与参数代入（用文中给出数字能直接复算通过）；所有“归一化/概率/占比”指标必须严格落在 `[0, 1]`；论文声称的效应、特征、阈值与约束必须与 `work/code/` 源码逐行一致。
5. **模型弱点独立披露 + 灵敏度「So-What」**：验证章节必须明确区分「**适用边界（外部极端工况何时失效）**」与「**模型自身弱点（Model Weaknesses：合成数据、未标定参数、简化假设）**」，且灵敏度分析必须明确回答头号敏感因子与核心决策是否翻转；多目标问须呈现解集、归一化边界、[0, 1] 合规评估与折中规则，单目标问只给最优解。
6. **一图一结论 + 3 秒可读性（禁信息过载与图内大标题）**：每张图的题注必须是一句完整结论判断（而非“XX 示意图”），图内不写大标题；通过 **3 秒可读性检查**（轨迹/多曲线过密必须抽稀、分面或改为结构示意图，不画冗余 3D 装饰柱状图与负值无意义坐标轴）；表格使用三线表。
7. **问题重述 ≠ 抄题**；**每个结果配「业务解读」**：把统计/优化数字翻译为面向决策者的直观结论，非技术受众备忘录严格零公式且 ≤2 页。
8. **文献全部可核验且符合时间线**：只引用已通过 `verify_references.py` 的文献且**零遗漏、零未引用、零超赛题日期（含发布于赛后的 AI/软件工具引用）**，禁止无实证来源的数据归因与编造卷期页码。
9. **电子版规范**：国赛电子版不含承诺书/编号页，第一页即为摘要；注意 `../../work/figures/` 与 `../../work/tables/` 相对路径。
10. **初稿完成后**：交 `math-paper-humanize` 润色与核对 AI 披露，经人工确认后再入 `math-paper-review` 四向独立红队终审。
