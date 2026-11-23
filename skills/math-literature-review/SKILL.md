---
name: math-literature-review
description: 在文献库（arXiv、OpenAlex、Semantic Scholar、Crossref、CNKI/百度学术）及网页检索相似数学建模问题的解决范式，输出带 DOI/链接和证据等级的结构化清单；按 citation-ready 或 full-text synthesis 所需程度分析方法、比较优缺点并给出建模方向。当建模前需要调研相似问题解决范式、比较已有方法、寻找可借鉴模型时使用。
---

# 文献调研（按任务触发）

## 输入输出

- 输入：`work/brief.md`；用户提供的全文 PDF 放 `input/refs/`
- 输出：`work/references.csv`、`work/lit_review.md`

## 检索

- **检索方式**：优先用模型联网搜索能力（如 `search_web`）定位高质量中英文综述与竞赛/期刊近作，再用 Python API（`arxiv`、`habanero` Crossref、`requests` 调 OpenAlex / Semantic Scholar / Unpaywall）批量抓回**可核验的真实元数据与 DOI**，避免手抄或记忆编造引文。
- **检索词提炼**：由 `brief.md` 提炼「问题主题 + 核心机制词 + 方法词」（如 `resource allocation optimization`、`epidemic compartmental model`、`排队论 仿真`）。
- **覆盖目标**：每类关键问题尽量覆盖综述/范式文献 1–2 篇、同题近作 2–3 篇、方法实现类 1–2 篇（受时间预算约束时优先确保核心小问的方法依据）。

## 记录（references.csv）

每篇至少包含：`cite_key,title,authors,year,doi,link,core_method,relevance,fulltext_status,sub_question,data_needs,transferable`。写作环节严格按 `cite_key` 引用，防张冠李戴。
- 开放获取查验：可用 Unpaywall API（`https://api.unpaywall.org/v2/<doi>?email=team@example.com`）或 arXiv 下载合法全文到 `input/refs/`；付费文献不可得时保留元数据与摘要级信息，不阻塞后续阶段，除非建模细节强依赖全文公式。

## 证据等级与分析对比（lit_review.md）

按 `_shared/references/workflow-contract.md` §6 标注证据等级：
1. `discovery`：检索与方法映射；
2. `citation-ready`：DOI/arXiv 元数据已核验；
3. `full-text synthesis`：全文已阅读并综合。

`lit_review.md` 需包含：单篇要点（问题、模型、数据需求、局限、可迁移点）、横向对比矩阵，以及「每个小问 → 候选方法 → 选用/弃用理由」映射表，直接喂给 `math-model-design`。**不照搬文献模型**，注明针对本题的改进点。

## 质量关卡

- 交付前必须运行核验脚本，FAIL 项（404 / 虚构 DOI）修正后才允许进入论文参考文献：
  ```bash
  python _shared/scripts/verify_references.py --refs work/references.csv
  ```
- 若用户明确跳过或降级为 `discovery`，在 `run_manifest.yaml` 记为 `WAIVED` 并注明原因与风险。
