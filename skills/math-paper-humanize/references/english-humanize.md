# 英文人工化通道（MCM/ICM）

> 本文件是 `math-paper-humanize` 的**英文**子通道，服务于美赛（MCM/ICM）等英文赛题。
> 中文通道仍以 `../SKILL.md` 主体为准；英文不是把中文规则翻译一遍——
> **有些"AI 味"规则在学术写作里是反的**，见下面「显式保留」一节。

## 0. 目标与边界（与 SKILL.md「边界」一致，不得放宽）

目标是让论文**读起来像一个具体的队伍写的**：主张明确、证据到位、语气一致。
**不是欺骗 AI 检测器**：

- 禁止刻意插入错别字、字符替换、同义改写绕检测；
- 禁止为"显人味"而故意加口语、反问、第一人称滥用、句长人为抖动；
- 禁止**多跳翻译/回译**当最终稿（会把术语改烂）；
- 不承诺任何检测器结果，不报告任何编造的 AI 百分比；
- 模式清单是**顾问**，不是裁判：命中不等于必须改，改与不改都要能说出理由。

**美赛特有约束**：必须提交 **AI Use Report**（不计入 25 页），且 AI 使用是**允许并需如实披露**的
——所以本通道的正当目标是"写得像人写的论文"，而**不是**"掩盖用过 AI"。两者方向不同，
前者提升评审体验，后者与竞赛合规冲突。见 `../_shared/references/competition-rules.md`。

## 1. 显式保留（**覆盖**下列通用规则，禁止误删）

这一节优先级**高于**第 2 节的任何清单。humanizer 的硬规则多是为博客散文写的，
套到科研论文上会造成**过度修正**。

| 项目 | 通用 humanizer 规则 | 学术写作的正确做法 |
|---|---|---|
| **Methods 被动语态** | "No passive constructions." | **Methods 保留被动**（"Samples were collected at..."）是学科惯例，不是 AI 味。Results/Discussion 再按需改主动。 |
| **第一人称** | "No first person." | **`we`/`our` 是学术写作的正确用法**（"we assume", "our model"）。禁止的是滥用，不是使用。 |
| **三项并列（tricolon）** | "Two items beat three." | 科学写作有**固定的三段式**："observation → mechanism → implication"、"input → method → output"、三类误差来源。**确有第三项就必须写三项**——只有为节奏凑数时才砍。 |
| **学科术语** | "avoid jargon" | 术语是**精确**，不是 jargon。`weighted interval score`、`Pareto frontier`、`shadow price` 照用。要砍的是商业套话（`leverage`/`landscape`/`ecosystem`）与 AI 词（`delve`/`tapestry`/`nuanced`）。 |
| **图注 / 表格文字** | 各种句子级规则 | 图注是**电报式**的（"Mean ± SD; n = 36. BH-FDR across 10 contrasts."），不适用句子节奏规则。 |
| **破折号** | "No em dashes." | 学术散文**可以**用，但要少；中文稿的 `——` 同样。这条是风格偏好，不是硬错。 |
| **被动 vs 主动的判据** | 一刀切 | 判据是**「施动者是否重要且已知」**：重要就用主动（"We chose ε = 0.05 because..."），不重要或未知就用被动。 |

> **一句话纪律**：改英文的目标是**更清楚**，不是**更不像 AI**。任何让句子变模糊、变啰嗦、
> 或丢掉学科惯例的改动，即使"更不像 AI"也要拒绝。

## 2. 顾问清单：适用于学术写作的 AI 套话

只收录**在英文科研写作里确实出现且确实有害**的条目。来源见文末致谢。

### 2.1 词与短语（直接替换）

| 命中 | 处理 |
|---|---|
| `delve into` / `delve deeper` | → `examine` / `analyze` / 直接说做了什么 |
| `it is worth noting that` / `it should be noted that` / `it is important to note that` | **删掉整句引导**，直接陈述 |
| `plays a crucial/important role` | → 说**具体作用**（"reduces runtime by 30%"） |
| `is of great significance` / `important implications` | → 说出**是哪个** implication |
| `serves as` / `stands as` | → `is`（除非确实要表达"充当…功能"） |
| `navigate the landscape` / `leverage` / `ecosystem` / `tapestry` / `nuanced` | 商业套话，→ 具体动词或删除 |
| `groundbreaking` / `unprecedented` / `revolutionary` / `cutting-edge` | **促销性夸大**，删或降级为可验证陈述 |
| `highly robust` / `comprehensive solution` | → 给出**具体指标**（"stable across 5 seeds, HV spread 3.6–7.0%"） |
| `researchers have shown` / `experts argue` / `studies suggest` | **虚指归因**：给不出具体来源就是没有来源 → 补引用或删 |

### 2.2 句式结构

| 命中 | 问题 | 处理 |
|---|---|---|
| 负向并列：`Not X. Not Y. Just Z.` | 戏剧化 | 直接陈述 Z |
| 二元对比：`It's not X, it's Y.` | 同上 | 直接说 Y |
| 自问自答：`The result? Devastating.` | 博客体 | 合并成陈述句 |
| 碎片排比：`Speed. That's it. That's the tradeoff.` | 制造强调 | 写成完整句 |
| 虚假范围：`from X to Y`（范围本身无意义） | 空洞 | 给出**真实区间与端点含义** |
| 表层分词分析：`..., highlighting its importance.` | 假分析 | 删，或写成分句说明**为什么**重要 |
| `Despite these challenges...` 公式 | 模板腔 | 删；或指出**具体**是哪个限制、影响哪条结论 |
| 无来源的 `It has long been recognized that...` | 远距离叙述 | 给引用或删 |

### 2.3 段落与全篇

| 命中 | 问题 | 处理 |
|---|---|---|
| 分形摘要：先说"将讨论"，再说一遍，最后总结"刚说的" | 冗余 | 只留中间那次；图内标题交给 caption |
| 单点稀释：一个论点换十种说法重复 | 凑字数 | 压成一段 |
| 比喻堆砌 / 同一个比喻用超过两次 | 假权威 | 删 |
| `In conclusion` / `To sum up` 信号词 | 模板腔 | 直接下结论；LaTeX 里也省一个 `\section` 的套话开头 |
| 列表伪装成散文（"The first wall... The second wall..."） | 结构畸形 | 要么真用 `enumerate`，要么写成连贯段 |
| 加粗开头的项目符号列表 | 强 AI 信号 | 去掉加粗引导词，或改散文 |

### 2.4 与本项目既有审计的重叠

`../_shared/scripts/consistency_check.py --check-fabricated` 已在查**幻觉数字**；
本通道的清单负责**文风**，两者不互相替代。数字类问题一律以那个脚本为准。

## 3. 强制的机器校验（改完必跑）

文风可以商量，**含义不许漂**。改完英文稿必须跑：

```bash
python _shared/scripts/invariance_check.py \
    work/paper_original.tex work/paper_revised.tex \
    --lang en
```

它比对改动前后的：

- **数字与单位**（消失/改变 → **FAIL**）
- **引用键**（`\cite{}` / pandoc `[@key]` 增减 → **FAIL**）
- **公式**（行内 `$...$`、`\[...\]`、`equation/align` 环境变动 → **FAIL**）
- **受保护术语**（方法/模型名如 `NSGA-II`、`XGBoost`、`pymoo`、`Pareto` 被改名 → **FAIL**）
- **LaTeX 安全**（未转义 `%`、裸 `&`、`#`、行内 `$` 不配对 → **FAIL/WARN**）
- **`results.json` 可溯源**（出现的数字在 `results.json` 里找不到 → **FAIL**）
- **否定 / 因果方向 / 情态强度**标记计数变化 → **WARN（须人看）**

> **WARN 的语义**（照搬 PaperSpine 的立场）：标记计数变化是**提示去检查受影响句子**，
> **不是**改错的证据——等价改写本来就会让计数移动。**不得因为计数变了就强行回改。**

**退出码**：`0` 通过 / `1` 有 FAIL / `2` 参数或文件错误。自检：`--self-test`（8 用例）。

### 3.1 这个校验器**抓不住**什么（必读，别把它当免检）

**实测边界（2026-09-17）**：把 `The penalty coefficient barely matters` 改成
`The penalty coefficient matters critically` —— **语义完全反转**，但校验器只报 WARN、
verdict 仍 PASS。原因：改后文本里**根本不存在否定标记**（`barely` 不在词池里，
`critically` 是强化词），标记计数法无从发现。

**一般化结论**：**"移除一个对冲、换成强化"这一类反转，计数法原理上抓不到。**
它只能发现**标记数量变化**，不能判断**语气与结论方向是否被调包**。

因此本通道的防线是**三层，缺一不可**：

| 层 | 抓什么 | 抓不住什么 |
|---|---|---|
| ① `invariance_check.py` | 数字/引文/公式/术语**丢失**、LaTeX 危险、数字不可溯源 | **语义反转**（上述实测）、措辞级语气变化 |
| ② 人读**逐句对照**原稿 | 否定/因果/结论方向被改反、对冲被换成断言 | 看不出没读到的段落 |
| ③ `math-paper-review` 独立复核 | 摘要与正文数字一致、结论与证据相称 | —— |

> **纪律**：脚本报 PASS **不等于**润色安全。交付前必须有人**逐句对照原稿与润色稿**
> 读一遍——尤其盯**否定词、因果词、情态/对冲词**有没有被删除或替换成反义表达。
> 这与本仓库「脚本抓违规、肉眼抓丑和怪」的既有分工是同一条原则。

**当前已知的边界与可能加固**（留给后续优化）：

- 可考虑增加「**对冲词被删除但同句出现强化词**」的启发式（如 `may`/`suggests`/`likely`
  被删且同句新增 `critically`/`significantly`/`proves`），把它标为需人确认；
- 但这类启发式必然带来误报，**只能作为 WARN**，不得据此强行回改。

## 4. 与审查环节的接口

1. 润色前**冻结原文**：`cp output/paper/main.tex work/paper_original.tex`
   （绝不覆盖唯一的原始字节）。
2. 改完跑第 3 节的校验；**FAIL 必须回改**，WARN 逐条判断并在改动摘要里写结论。
3. 改动摘要（改了哪里、为什么）与校验 JSON 一起交 `math-paper-review`。
4. **人工通读仍是 BLOCKING 确认**——脚本只能证明数字没丢，证明不了文章读起来对。

## 致谢与来源

本通道的**顾问清单**（第 2 节）整理自以下 MIT 许可开源项目，并**按学术写作场景做了删减**：

- **skill-deslop** — *De-AI-ify scientific writing*
  作者 Stephen Turner · <https://github.com/stephenturner/skill-deslop> · MIT
  采用：词/短语表、句式结构表、tropes 中的 Word Choice / Sentence Structure /
  Paragraph Structure / Tone / Composition 各组。
  **剔除**：Em-Dash Addiction、Unicode Decoration（博客体，本场景不相关）。
- **stop-slop** — *A skill file for removing AI tells from prose*
  作者 Hardik Pandya · <https://github.com/hardikpandya/stop-slop> · MIT
  采用：Core Rules 中与本场景相符的部分、Quick Checks 的条目。
  **覆盖**：其 "No passive constructions. No first person." 与 "Two items beat three."
  在本场景不适用，见第 1 节「显式保留」。

第 3 节不变量校验的**不变量集合**（数字/单位、引文、公式、否定、因果方向、情态、受保护术语）
参照以下项目设计，实现为自包含脚本（不依赖其安装路径）：

- **PaperSpine**（产品名 PaperSpine5）· 作者 **WUBING2023** · MIT ·
  <https://github.com/WUBING2023/PaperSpine>
  参照文件：`scripts/author_voice_check.py`、`references/humanize.md`
  本仓库新增（该项目没有的）：`results.json` 数字溯源检查、LaTeX 安全门、8 用例自检。
