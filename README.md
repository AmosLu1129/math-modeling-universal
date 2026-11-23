# Math Modeling Universal Skills (`v4.0`)

跨 Agent、遵循 [Agent Skills 开放标准](https://agentskills.io) 的数学建模竞赛全流程技能包（11 个模块化 Skill + 共享工具链 `_shared/`）。一次安装，在 **Claude Code、OpenAI Codex、OpenCode、DeepSeek Harness (`dsh`)、Qoder / Qoder CN、Trae CN、Cursor、Windsurf、Gemini CLI 与 Antigravity** 中全局直接调用。

---

## 一、包含的 11 个核心技能

| 技能目录 (`name`) | 阶段 | 核心能力与内置门禁 |
|---|---|---|
| `math-modeling-workflow` | 全流程编排 | 按题型裁剪阶段、DAG 状态追踪 (`manifest_cli.py`)、P1/P2 人工确认门禁 |
| `math-problem-analysis` | S1 审题拆题 | 隐藏文本/零宽字符/白底小字防 AI 误导审计 (`problem_integrity_check.py`)、双通道视觉对照 |
| `math-data-prep` | S2 数据清洗 | `.mat` / `.xlsx` / `.csv` 清洗、无附件参数字典与量级预检 |
| `math-literature-review` | S3 文献综述 | Crossref / OpenAlex / arXiv / CNKI 调研与 DOI 真实性活体校验 (`verify_references.py`) |
| `math-model-design` | S4 模型设计 | 奥卡姆剃刀基线升级、P1 六要素形式化与 Pareto 范式锁定 (`check_formulation.py --phase p1`) |
| `math-model-solver` | S5 编程求解 | 求解器实现、`C1`–`C...` 独立约束检查、迭代日志 (`<=4` 轮)、`results.json` (`--phase p3`) |
| `math-model-validation` | S6 验证定稿 | 极限退化、求解器交叉检验、灵敏度/噪声地板、`validation_report.md`、`fact_sheet.md` (`--phase all`) |
| `math-figures` | S7 出版图表 | 11 套高级模板、静态预检 (`validate_figure_src.py`)、`layout_qa`、`figure_qa`、`audit_pdf_text`、拼图复核 |
| `math-paper-writing` | S8 论文写作 | 14 中 + 3 英竞赛模板、`export_paper_macros.py` 单源绑定（`\ResVal`/`\ResPct` + Booktabs 表格） |
| `math-paper-humanize` | S9 人工化润色 | 中英双通道去套话、改写不变量校验 (`invariance_check.py`)、竞赛级 AI 使用披露 |
| `math-paper-review` | S10 终审打包 | 红队审查、`paper_qa.py`（页数/Overfull/字体嵌入）、`consistency_check.py`（防幻觉数字）、代码附件与提交包 |

---

## 二、一键全局安装（零重复冗余）

### 从 GitHub 克隆仓库
Git 仓库中仅追踪唯一真源 `skills/_shared/`；在本地运行 `install.py` / `install.ps1` / `install.sh` 后，会自动在每个 `skills/math-*/` 下挂载或复制 `_shared` 并注册到本机各个 Agent：

```bash
git clone https://github.com/AmosLu1129/math-modeling-universal.git
cd math-modeling-universal
```

### Windows PowerShell
```powershell
cd path\to\math-modeling-universal

# 1. 查看本机已探测到的所有 Agent 技能目录
python install.py --list-targets

# 2. 为本机已检测到的所有 Agent 全局挂载（默认使用 NTFS Junction，不占用额外磁盘）
python install.py --agents auto --mode link
# 或使用 PowerShell 包装脚本：
.\install.ps1 -Agents auto -Mode link

# 3. 校验全部挂载目录、YAML Frontmatter 与核心脚本自检
python verify_install.py
```

### macOS / Linux
```bash
cd /path/to/math-modeling-universal
./install.sh --agents auto --mode link
python3 verify_install.py
```

### 安装选项说明
- `--agents auto`（默认）：自动扫描本机已安装的 Agent 配置根目录；若 Antigravity 原生插件 `~/.gemini/config/plugins/math-modeling` 已存在，自动跳过 `~/.gemini/antigravity/skills` 避免同一宿主重复注册。
- `--agents all`：挂载到全部 12 类已知 Agent 全局路径。
- `--agents minimal`：仅保留 `~/.agents/skills` + `~/.claude/skills` + `~/.qoder/skills` + `~/.qoder-cn/skills` 去重精简集合。
- `--agents claude,codex,opencode,dsh,qoder-cn`：按逗号列表精确指定目标。
- `--mode link|copy`：`link` 为目录链接/Junction（更新源仓库一次即全端同步）；跨盘/离线分发给别人或单项目打包可用 `--mode copy`。
- `--project <目录>`：安装到指定竞赛项目 `<dir>/.agents/skills/` 与 `<dir>/.claude/skills/`，彻底自包含随项目迁移。

---

## 三、支持 Agent 与全局路径清单

| Agent 宿主 | 全局路径 | 说明 / 触发方式 |
|---|---|---|
| **Open Standard** (Codex / Cursor / OpenCode / `dsh`) | `~/.agents/skills/` | 遵循 `agentskills.io` 开放规范；同时可通过 `npx skills add <path-or-repo>` 分发 |
| **Claude Code** | `~/.claude/skills/` | 原生斜杠命令 `/math-modeling-workflow` 或按描述自动触发；也可作为插件挂载 `.claude-plugin/plugin.json` |
| **OpenAI Codex** | `~/.codex/skills/` + `~/.agents/skills/` | 使用 `$math-modeling-workflow` 或自然语言提及赛题自动加载 |
| **OpenCode** | `~/.config/opencode/skills/` | 通过内置 `skill` 工具按需加载 |
| **DeepSeek Harness (`dsh`)** | `~/.dsh/skills/` + `~/.agents/skills/` | 支持 `.dsh/skills/` 与 `.agents/skills/` 自动发现 |
| **Qoder / Qoder CN** | `~/.qoder/skills/` / `~/.qoder-cn/skills/` | 新增/重载后可执行 `/skills reload` 或重启 IDE/CLI 生效 |
| **Trae CN** | `~/.trae-cn/skills/` | 与现有技能共存，不覆盖用户自定义技能 |
| **Cursor / Windsurf / Gemini CLI** | `~/.cursor/skills/` / `~/.codeium/windsurf/skills/` / `~/.gemini/skills/` | 按 `SKILL.md` frontmatter 自动发现 |
| **Antigravity** | `~/.gemini/config/plugins/math-modeling` 或 `~/.gemini/antigravity/skills/` | 原生插件已安装时优先沿用插件通道，避免双份注册冲突 |

---

## 四、`SKILL.md` 如何零改造跨 Agent 运行 `_shared/`

为避免在各个 Agent 顶级 `skills/` 目录下产生不被识别的杂散 `_shared` 目录：
1. 所有公共脚本（`scripts/`）、参考规范（`references/`）与竞赛模板（`templates/`）均保存在唯一的真源目录 `skills/_shared/` 中。
2. 每个 `skills/math-*/` 内部直接挂载 `_shared` 链接（拷贝模式下为独立副本），且每个技能内自带轻量跨平台启动器 `scripts/mm_run.py`。
3. 所有 `SKILL.md` 均统一使用相对于自身技能目录的 `_shared/...` 路径，并已移除特定宿主的专有工具名绑定与 `python3` 硬编码，实现零魔改通用执行。

---

## 五、安全卸载 / 去重

卸载脚本**仅删除**由本仓库挂载的 11 个 `math-*` 目录（含 `.math-modeling-managed.json` 标记），绝不触碰你原有的其他技能或工作区数据：

```powershell
# 预览将要清理的目标（不删文件）
python uninstall.py --agents all --dry-run

# 如果某些共用 .agents/skills 的工具想精简重复项，可按需卸载指定端（例如仅保留 agents + claude + qoder-cn）：
python uninstall.py --agents codex,opencode,dsh,trae-cn
```

---

## 六、引用与致谢（Credits & Acknowledgments）

本项目的架构设计、作图规范、静态审计规则与去套话机制移植、改写并感谢以下开源项目、研究规范与社区成果：

### 1. PaperSpine（产品名 PaperSpine5）
- **作者 / 仓库**：**WUBING2023** · <https://github.com/WUBING2023/PaperSpine>
- **许可**：MIT（移植依据版本 `v0.4.0-alpha.1-dev`）
- **采用了什么**：
  - `skills/math-figures/references/figure-sop.md` 的作图主 SOP 移植并改写自上游 `references/scientific-figure-workflow.md`、`references/figure-story.md` 与 `references/figure-reference-mapping.md`（先写一句话结论、按证据而非图型规划视觉论证、整图/面板两级论证契约与 claim boundary、参考图结构迁移映射、按组件路由工具）。
  - `skills/_shared/scripts/invariance_check.py` 与 `skills/math-paper-humanize/references/english-humanize.md` 的文本改写不变量集合（数值/单位、引用、公式、否定词、因果方向、情态强度、受保护术语）与 FAIL/WARN 严格度立场借鉴自上游 `author_voice_check.py`，并采用双文件对比的自包含实现。
- **有意改写的部分**：上游面向期刊投稿、将「参考图解构」与「逐图网页确认」设为强制环节；本项目面向数学建模竞赛场景，将参考解构降级为可选（拿不到可查看的合法参考时，明确声明「本图为原创设计」并继续，不阻塞流程），并用 `work/run_manifest.yaml` 决策边界替代逐图网页确认，同时保留与扩展自有的几何/排版自检脚本栈（`layout_qa.py` / `svg_audit.py` / `validate_figure_src.py` / `figure_qa.py` / `audit_pdf_text.py`）。

### 2. nature-skills（`nature-figure`）
- **仓库**：<https://github.com/Yuan1z0825/nature-skills>
- **采用了什么**：通读其 `nature-figure` 技能契约、QA、设计理论、图例规范与页面原型后，将适用于数学建模论文的部分提炼整合至 [`skills/math-figures/references/nature-figure-essence.md`](skills/math-figures/references/nature-figure-essence.md)，作为可选「期刊出版风格」（证据链唯一性、面板审计表、配对效应检查、三阶推进信息架构、语义固定色板与 Nature 等期刊栏宽/字号规格）。

### 3. academic-figure-skill
- **许可**：Apache-2.0
- **采用了什么**：[`skills/_shared/scripts/validate_figure_src.py`](skills/_shared/scripts/validate_figure_src.py) 的静态出图前代码预检规则结构借鉴并重构自其 Apache-2.0 QA 工作流（未保留其路径绑定执行器，内部保留对应版权/启发说明注释）。

### 4. skill-deslop & stop-slop（英文学术写作去 AI 套话）
- **skill-deslop**：作者 **Stephen Turner** · <https://github.com/stephenturner/skill-deslop> · MIT
- **stop-slop**：作者 **Hardik Pandya** · <https://github.com/hardikpandya/stop-slop> · MIT
- **采用了什么**：在 [`skills/math-paper-humanize/references/english-humanize.md`](skills/math-paper-humanize/references/english-humanize.md) 的英文科研写作润色顾问清单中，整理、整合上述两个 MIT 项目规则，并结合理工科/数模竞赛写作要求做了针对性裁剪（例如保留科研因果链与三段式表达中确有实质内容的三项并列）。

### 5. 数学建模社区工作流与绘图参考
- 在多轮迭代调研中参考并吸收了开源数学建模 Agent / Skill 社区项目（**MathModelAgent**、**cumcm-modeling-skill**、**math-modeling-skill**、**MathModel-Skill**）的互补实践与共识：图内不写大标题（标题统一交由 LaTeX / Typst `\caption{}`）、三类图体系（原始数据 / 中间过程 / 最终结果）、图型多样性硬规则、按题型出图速查与常见高级绘图模板组织方式。

### 6. 开放标准与底层排版工具
- **[Agent Skills 开放标准](https://agentskills.io)**：跨 Agent 的 `SKILL.md` 发现规范、目录结构与 `.agents/skills` 分发约定。
- **[Typst](https://github.com/typst/typst)** 与 **[Tectonic](https://github.com/tectonic-typesetting/tectonic)**：作为竞赛论文自动化渲染与校验管线的默认跨平台排版引擎。

---

## 七、开源许可（License）

本仓库整体以 **MIT License** 发布，详见 [`LICENSE`](LICENSE)。

部分参考或重构自第三方开源项目的脚本与规范文件（如源自 `PaperSpine`、`skill-deslop`、`stop-slop` 的 MIT 方法论与清单，以及 `validate_figure_src.py` 中重构自 Apache-2.0 `academic-figure-skill` 规则结构的静态检查规则）已在对应文件头部或致谢章节中保留各自原始归属与许可说明。

