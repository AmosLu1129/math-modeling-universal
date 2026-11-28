---
name: math-paper-review
description: 审查与润色建模论文并准备提交：支持独立红队子代理复核，执行双向数字一致性检查（防幻觉数字）、最终公式完整性核对、版面渲染与原生多模态复核、PDF 字号与 Overfull 检查，生成代码附件 PDF 并打包提交目录。当论文完成润色需要终审质检、生成代码附件或打包提交时使用。
---

# 审查与最终交付

## 输入输出

- 输入：`output/paper/`（tex/typ/pdf）+ `work/` 全部产物
- 输出：终稿 `output/paper/paper.pdf`、`output/code_appendix.pdf`、`output/submission/`、`work/review_report.md`

## 一、机械与双向一致性检查（缺一不可）

1. **摘要 ↔ 正文 ↔ `results.json` 双向核对（防幻觉数字必做，建议优先核查 PDF 提取文本）**：
   若正文大量使用导出宏（`\ResSmart` / `\ResPctSmart`），除传源码目录外，先从终稿 `paper.pdf` 提取纯文本再跑核对，避免未展开宏名漏检：
   ```bash
   python _shared/scripts/consistency_check.py --results work/results.json --paper output/paper/ --percent --check-fabricated
   ```
   - 支持 `.tex`/`.typ`/`.md`/`.txt`（含目录自动合并），自动区分 `CRITICAL_MISSING` 与 `DETAIL_OMITTED`（标准误/Pareto 明细/灵敏度网格等）；可用 `--key-metrics`、`--ignore-patterns`、`--strict-all` 精细控制口径。
   - 正向查 `results.json` 关键数字是否进论文；反向 `--check-fabricated` 抓论文里带小数却无出处的数字。
   - 剩余命中项必须逐条人工判定（四舍五入 / 合法派生 / 真错误），并将判定结论写入 `work/review_report.md`，不得整批放过。
   - **同列正负号、有效数字与表内口径抽检**：核查多组对照表/灵敏度表的同列正负号统一（无漏写 `-`）、展示精度控制在 **2–3 位有效数字**、输入参数清单表与分级假设表完整可核查。
2. **最终公式完整性**：逐条对照定稿 `work/final_models.md`，确认每问均有完整带编号最终方程与参数数值。
3. **约束、文献与防误导复核**：确认 `check_formulation.py --phase all` PASS、`verify_references.py` 无 FAIL、且论文未采信 `problem_integrity_report.md` 隔离的噪声。
4. **AI 使用披露核查**：确认国赛已附「AI 使用情况说明」或 MCM/ICM 已附「Report on Use of AI」，且核查因此顺延的附录编号与目录/交叉引用。

## 二、版面与排版硬规范（渲染 + 原生视觉复核）

1. **渲染全页 + 空白/四边（top/bottom/left/right）触边检测**：
   ```bash
   python _shared/scripts/render_check.py output/paper/paper.pdf --out work/scratch/paper_pages --dpi 90
   ```
2. **原生多模态分批复核**：用当前 Agent 的原生图像读取工具查看关键页与疑点页 PNG（摘要页、目录、主图/主表页、附录代码首页），**每批 ≤3 张**；发现字体方块、文字重叠、链接框或裁切，回改源码重编译再复核。
3. **PDF 插图字号复核**：在最终插图宽度下跑 `python _shared/scripts/audit_pdf_text.py <图.pdf> --min-pt 5`；最小字号 `<5pt` 一律回改，**禁止用缩图压页数绕过**。
4. **一体化排版终审门禁（`paper_qa.py`）**：
   ```bash
   python _shared/scripts/paper_qa.py --paper-dir output/paper --compile --clean --competition auto --out work/paper_qa_report.md
   ```
   单命令串联六项检查并兜底：① `SOURCE-HYGIENE`（拦截 `.tex` 裸 Markdown `**`/`##`/`[url]`/单反引号代码、`\resizebox`/`\scalebox` 括号后误写 `\%`、公式对齐环境内误写 `\&`，或 `.typ` LaTeX 残留与占位符）；② `COMPILE-LOG`（干净双编译、`Overfull \hbox > 10pt`、`^!` 错误与未定义引用）；③ `PAGE-LIMIT`（自动排除 MCM/ICM 文末 Report on Use of AI 后的 25 页上限 / 国赛 20 页上限）；④ `SUMMARY-OVERFLOW`（严查 Summary Sheet 溢出第 1 页）；⑤ `FONT-EMBED`（`pdffonts` 全嵌入与 0 Type 3）；⑥ `FIGURE-AUDIT`（全部 `\includegraphics`/`#image` 存在性与 PDF 插图字号）。
   另留意 `\usepackage[hidelinks]{hyperref}` 去链接框、`thebibliography` 与手动标题不重名、`pdffonts` 无未嵌入 `STFangsong`。

## 三、四向联合独立红队审查（`o_award` / `high_assurance` 必做硬关卡，其余档位强推）

为避免单上下文“自己审自己”的盲区，必须在冻结提交包前派发**全新只读红队子代理**（同时读取终稿 PDF 文本提取件 + 论文源码 `.tex/.typ` + `work/code/*.py` + `work/results.json` + `work/tables/*.csv` + `work/constraint_check.md`），执行四向交叉审验并把逐条核验记录写入 `work/review_report.md`：
1. **向度 1（公式数值反代与源码一致性）**：将正文中给出的参数值代回正文印刷的解析公式，独立验算能否复现文中中间量与最终结果；对照 `work/code/*.py` 逐项抽检超参数、阈值、分段区间、随机种子与样本量 $N$（同表内各试验组口径必须一致，不允许暗降局部实验的 $N$）。
2. **向度 2（数字、断言与定义域一致性）**：核对 Summary、正文、备忘录、图注、图内标注（含 HTML 示意图）与 `results.json` 零矛盾；核查表题/图题里的强定性词（如“单调”“最优”“陡降”）在对应数据行是否每行成立；所有“归一化/概率/占比”指标必须严格在 `[0, 1]`；有效数字与输入估计匹配（2–3 位）。
3. **向度 3（题面映射、输入透明与模型诚实度）**：对照 `brief.md` 动词核对表与期望答案形态检查有无漏问或答非所问；确认正文或附录已列出核心输入参数表与假设三级标源；确认验证章节不仅写了外部「适用边界」，还**单独写了「模型自身弱点（Model Weaknesses）」**且灵敏度回答了结论是否翻转。
4. **向度 4（文献时间线、版面与去工程语体）**：核对文献双向一致（`0` 未引用、`0` 缺失、`0` 超赛题日期文献含赛后 AI 工具、无无实证来源归因）；逐页检查渲染 PNG 确保每图**一图一结论且满足 3 秒可读性**（无过密杂乱轨迹与装饰性 3D）；核查全文零 `snake_case`、零工程质检腔（如 `20/20 PASS`/`Safety Standards`/`Code-to-Academic`）、零配色渲染术语（如 `Morandi`/`terracotta`/`300 DPI HTML`）、零高频 AI 副词与绝对断言。

## 四、外部评审反馈处理闭环

收到指导老师或评审意见时：逐条登记「编号 → 原文要点 → 判定（接受/部分接受/拒绝）→ 理由」；凡修改数字或模型的条目必须重跑代码并更新 `results.json` 后才能改论文；**所有技术与排版修改完成后必须重派一轮独立红队复核通过**，再把可复用教训沉淀进 `ITERATION.md`。

## 五、代码附件与白名单洁净打包

1. **生成代码附件 PDF**：
   ```bash
   python _shared/scripts/code_appendix.py --code work/code/ --out output/code_appendix.pdf
   ```
   支持 `pandoc`、`xelatex`（原生 `listings` + 跨平台 CJK 字体，无 pandoc 时首选）、`typst` 与 `reportlab` 引擎（可用 `--engine` 指定）。确认收录 `work/code/` 全部最终脚本（含共享模块），代码参数与 `final_models.md` 一致且可复现 `results.json`。
2. **白名单洁净重建提交目录 `output/submission/`（严禁增量覆盖旧目录）**：直接使用一键白名单打包脚本清空重建并校验 SHA-256：
   ```bash
   python _shared/scripts/pack_submission.py --project .
   ```
   确保 `paper.pdf`、`code_appendix.pdf`、仅含清洁源码的 `code/`（自动剔除 `__pycache__/`、`*.pyc`、`scratch/`）、`data_clean/`、`README_SUBMISSION.txt` 与 `SHA256SUMS.txt` 逐项对齐。
3. **质量关卡与状态关闭**：critical 问题回退对应环节重跑；通过或经用户确认/WAIVE 后冻结发布包，并运行 `python _shared/scripts/manifest_cli.py mark-current --manifest work/run_manifest.yaml --all` 与 `status --strict` 确认零 stale/drift/missing。
