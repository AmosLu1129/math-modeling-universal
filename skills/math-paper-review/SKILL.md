---
name: math-paper-review
description: 审查与润色建模论文并准备提交：支持独立红队子代理复核，执行双向数字一致性检查（防幻觉数字）、最终公式完整性核对、版面渲染与原生多模态复核、PDF 字号与 Overfull 检查，生成代码附件 PDF 并打包提交目录。当论文完成润色需要终审质检、生成代码附件或打包提交时使用。
---

# 审查与最终交付

## 输入输出

- 输入：`output/paper/`（tex/typ/pdf）+ `work/` 全部产物
- 输出：终稿 `output/paper/paper.pdf`、`output/code_appendix.pdf`、`output/submission/`、`work/review_report.md`

## 一、机械与双向一致性检查（缺一不可）

1. **摘要 ↔ 正文 ↔ `results.json` 双向核对（防幻觉数字必做）**：
   传**源码目录**自动合并全部章节：
   ```bash
   python _shared/scripts/consistency_check.py --results work/results.json --paper output/paper/ --percent --check-fabricated
   ```
   - 支持 `.tex`/`.typ`/`.md`/`.txt`（含目录自动合并），自动区分 `CRITICAL_MISSING` 与 `DETAIL_OMITTED`（标准误/Pareto 明细/灵敏度网格等）；可用 `--key-metrics`、`--ignore-patterns`、`--strict-all` 精细控制口径。
   - 正向查 `results.json` 关键数字是否进论文；反向 `--check-fabricated` 抓论文里带小数却无出处的数字。
   - 剩余命中项必须逐条人工判定（四舍五入 / 合法派生 / 真错误），并将判定结论写入 `work/review_report.md`，不得整批放过。
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

## 三、独立红队子代理审查（`high_assurance` 推荐）

为避免单上下文“自己审自己”的盲区，可派发只读子代理（或新开隔离只读会话）在独立上下文中分三线审查并汇总到 `work/review_report.md`：
- **线 1（数值与公式线）**：对照 `results.json`、`final_models.md` 与 `consistency_check.py` 报告逐项验算；
- **线 2（逻辑与防误导线）**：对照 `brief.md`、`problem_integrity_report.md`、`validation_report.md` 核查有无答非所问、物理违背或未交代失效边界；
- **线 3（版面与语言线）**：读渲染 PNG 查排版、图注自足性、中英文语法与 AI 披露合规性。

## 四、外部评审反馈处理闭环

收到指导老师或评审意见时：逐条登记「编号 → 原文要点 → 判定（接受/部分接受/拒绝）→ 理由」；凡修改数字或模型的条目必须重跑代码并更新 `results.json` 后才能改论文，最后把可复用教训沉淀进 `ITERATION.md`。

## 五、代码附件与提交包冻结

1. **生成代码附件 PDF**：
   ```bash
   python _shared/scripts/code_appendix.py --code work/code/ --out output/code_appendix.pdf
   ```
   支持 `pandoc`、`xelatex`（原生 `listings` + 跨平台 CJK 字体，无 pandoc 时首选）、`typst` 与 `reportlab` 引擎（可用 `--engine` 指定）。确认收录 `work/code/` 全部最终脚本（含共享模块），代码参数与 `final_models.md` 一致且可复现 `results.json`。
2. **打包提交目录 `output/submission/`**：放入 `paper.pdf`、`code_appendix.pdf`、仅含清洁源码的 `code/`（打包前先清除 `__pycache__/` 与 `*.pyc`）及规则允许的数据，最后生成校验文件（如 `MD5.txt`）与文件清单。
3. **质量关卡**：critical 问题回退对应环节重跑；通过或经用户确认/WAIVE 后冻结发布包。
