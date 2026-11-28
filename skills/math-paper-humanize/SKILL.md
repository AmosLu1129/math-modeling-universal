---
name: math-paper-humanize
description: 论文人工化润色。统一全文文风与作者声音，去除模板腔与 AI 常见套话（中英双语通道；英文通道面向 MCM/ICM），补充基于真实迭代日志的建模取舍与适用边界，用不变量校验防止文风改动改漂结果，并按竞赛规则生成 AI 使用披露（国赛附录说明 / MCM Report on Use of AI）。当论文初稿完成需要人工化打磨与准备 AI 合规披露时使用。
---

# 论文人工化润色

本技能位于论文写作之后、审查交付之前：写作 → **人工化润色** → 审查交付。

## 输入输出

- 输入：`output/paper/` 初稿（tex/typ/md/word）+ `work/` 全部产物（`final_models.md`、`results.json`、`iteration_log.md`、`validation_report.md`）
- 输出：润色稿 + 改动摘要 + AI 使用披露章节，交给 `math-paper-review`

## 六项任务

1. **统一文风与克制科研者人格（中英分轨，默认关闭俏皮幽默）**：
   - 全文统一采用 **Problem → Tension → Insight → Solution** 叙事张力，呈现冷静、克制、重证据的科研作者声音，消除“各节像不同模板拼凑”与流水账式汇报；
   - **默认严谨学术语气（中英文一致）**：**默认关闭**所有拟人调侃、俏皮比喻或冷幽默修辞（仅当用户明确要求时，才允许按 `references/english-humanize.md` §2.5 轻点 ≤2–3 处且严禁拟人化表述如 *"No model stays polite..."*）。
2. **去模板腔、AI 副词腔、代码腔与工程质检腔**：
   - 删减空洞中文套话（“综上所述”“值得注意的是”“在很大程度上”）与英文高频 AI 副词/过度断言词（`strictly`、`cleanly`、`crucially`、`fundamentally`、`seamlessly`、`remarkably`、`demonstrably`、`proves`、`exact`、`fatally flawed`），**让数字自己说话**；
   - 将过长复合句拆短（优先短清晰句），并在专业术语首现时补一句大白话解释，控制术语密度；
   - 彻底清理 `snake_case` 代码变量名、虚假 4–5 位小数/尾零，以及内部工程字样（`20/20 PASS`、`Safety Standards`、`Code-to-Academic`、配色词汇如 `Morandi`/`terracotta`、渲染参数字样）。
3. **注入真实作者性（取舍演进 + 不许编造）**：基于 `work/iteration_log.md`、`infeasibility_report.md` 或 `validation_report.md`，主动补充 1–2 处真实建模迭代取舍与自我质疑（*“最初尝试 X → 发现边界局限 Y → 改用 Z”*）以及独立「模型自身弱点」坦诚反思，严禁为了“像人写”新编踩坑故事。
4. **防幻觉核实**：逐条核对文献真实性与数字一致性；润色**不得改变任何结果数字、公式、符号与交叉引用**。
5. **可读性打磨**：长短句交错、段落结构“问题张力 → 机制洞见 → 量化证据 → 结论小结”、图表与正文呼应。
6. **人工通读确认（BLOCKING）**：保留「改动摘要（改了哪里、为什么）」供参赛队员通读确认后，才允许进入审查环节。

## 英文通道（MCM / ICM / APMCM，必读）

赛题为英文时，**必须先读 `references/english-humanize.md`**（含「学术显式保留规则」：保留 Methods 被动语态、`we/our`、学科术语与三段式并列，避免博客式 humanizer 过度改写）。

改写前后必须冻结原文并跑不变量校验：
```bash
# 先将原稿复制一份到 work/paper_original.tex（或 .typ）
python _shared/scripts/invariance_check.py work/paper_original.tex work/paper_revised.tex --lang en
# 数字与 results.json 双向一致性校验由 math-paper-review 的 consistency_check.py 执行（自动剥离 LaTeX 版式尺寸）
```
- `FAIL`（数字/引文/公式/受保护术语丢失、LaTeX 危险构造）必须回改；若对纯文本稿追加 `--against work/results.json`，未溯源数字也须核对；
- `WARN`（否定/因果/情态标记计数变动）须人工逐句核对语义方向，防止把对冲语气反转成绝对断言。

## AI 使用披露（2025–2026 合规，四问式模板）

直接复用 `_shared/templates/ai_disclosure/` 中对应模板（`ai_use_report_zh.{tex,typ}` / `ai_use_report_en.{tex,typ}`）：
1. **工具与分工**：用了哪些工具/模型，分别用于哪些环节；
2. **输出核验**：如何通过机械门禁、独立约束检查器与双向一致性校验核对；
3. **人工纠正实例**：真实纠正过的 AI 错误案例（取自 `iteration_log.md` / 审稿记录，严禁编造）；
4. **责任声明**：参赛队对论文全部内容负最终全责。

- **国赛**：放入附录（如附录 A/B，不计正文篇幅，但不得将正文分析移入附录压页）。
- **MCM/ICM**：作为文末独立 `Report on Use of AI`（按 COMAP 规则不计入 25 页上限）。
- **边界**：目标是写得自然、清晰、诚实披露，**严禁**插入错别字、替换字符或打乱语序去规避 AIGC 检测器。
