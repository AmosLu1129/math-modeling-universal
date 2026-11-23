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

## 获奖论文结构骨架（2025 国赛一等奖范式）

1. **问题分析必配逻辑流程图**：色块+箭头串联各问数据流与依赖关系，让评审 30 秒看懂全局。
2. **符号说明用三列表**：`符号 | 含义 | 单位/取值`，与 `model_doc.md` 及代码严格一致。
3. **每个小问闭环**：问题分析 → 假设 → 模型建立（含最终完整方程）→ 求解（算法步骤/伪代码框）→ 结果（图/表 + 业务解读）→ 验证（参数论证表 + 对照算法 + 误差分析）。
4. **摘要最后写**：背景一句 + 框架一句 + 逐问方法与 **≥3 个可验证量化结果** + 创新点 2–3 条 + 应用落地一句（国赛摘要单独一页；MCM Summary Sheet 1 页）。
5. **AI 使用披露**：国赛附录说明 / MCM Report on Use of AI，模板直接复用 `_shared/templates/ai_disclosure/`（内容取自真实迭代日志，严禁编造）。

## 篇幅预算（开写前先分配，防超页）

- **国赛（CUMCM）**：正文（含摘要）≤20 页（摘要 1–2 页 / 主体 14–16 页 / 参考文献 1–2 页），附录（AI 披露 + 代码/长表）不计正文。
- **美赛（MCM/ICM）**：Summary Sheet + 目录 + 正文 + 参考文献 + 常规附录 **总计 ≤25 页**；文末 **Report on Use of AI 不计入 25 页**。

## 十条硬性规则

1. **数字事实表与单源宏绑定前置**：动笔前必须运行 `fact_sheet.py` 与 `export_paper_macros.py`：
   ```bash
   python _shared/scripts/fact_sheet.py --results work/results.json --out work/fact_sheet.md
   python _shared/scripts/export_paper_macros.py --results work/results.json --out-tex output/paper/results_macros.tex --tables-dir work/tables
   ```
   正文中优先用 `\ResVal{path}` / `\ResPct{path}` / `\ResInt{path}`（或 Typst `--out-typ output/paper/results_data.typ` 的 `#res("path")`）与 `\input{../../work/tables/*.tex}` 直接绑定 `results.json`——禁止手抄数字，缺失键会在编译期直接报错；重跑阶段 5/6 后重跑一次宏导出并重编译即可全自动同步。
2. **最终公式完整独立呈现**：每问结尾对照 `work/final_models.md` 给出完整编号方程 + 参数代入 + 指标。
3. **代码与论文设定逐行一致**：论文声称的效应、特征、约束必须对照 `work/code/` 核实，禁止“论文写 A、代码跑 B”。
4. **多目标小问不得只报单点“最优数”**：必须呈现 Pareto 解集（点数、覆盖区间、前沿图）+ 折中点选取规则 + 范式理由；不可行问题如实交代冲突分析。
5. **每个结果配「业务解读」**：把统计/优化数字翻译成赛题场景决策语言；MCM 题若要求管理备忘录，严格按商务格式（零公式、≤2 页）。
6. **问题重述 ≠ 抄题**；**参数选择必有论证表**（离散化点数、阈值、超参数需配误差或敏感性表）。
7. **图内不写大标题**，结论句交给题注；表格用三线表，长明细进附录。
8. **文献全部可核验**：只引用已通过 `verify_references.py` 的 `work/references.csv` 条目，禁止编造卷期页码。
9. **电子版规范**：国赛电子版不含承诺书/编号页，第一页即为摘要；注意 `../../work/figures/` 与 `../../work/tables/` 相对路径。
10. **初稿完成后**：交 `math-paper-humanize` 润色与核对 AI 披露，经人工确认后再入 `math-paper-review`。
