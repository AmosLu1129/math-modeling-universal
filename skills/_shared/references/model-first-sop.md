# 先建模后代码 · 防死循环 SOP（建模类环节硬门禁）

> 版本 v3.0（2026-09-03）· 来源：用户提供的英文约束提示词，经逐条分析后并入本工作流
> 适用范围：环节 1/4/5/6 中涉及**优化、多目标、图论/网络、调度、机理方程求解**的小问。纯数据驱动/统计预测类小问至少套用 §6（能跑≠对）与 §7（反 slop）。
> 强制方式：各环节 SKILL.md 顶部「本环节硬门禁」引用本文件；机械门禁 `python _shared/scripts/check_formulation.py --work work/` 退出码非 0 时**禁止跨门禁**。
> 铁律：**不跳步、不省门禁、不为了跑出结果改题面**。

## 0. 一句话总则

先交出**可以被人工审定的数学形式化**，人审通过才允许写代码；输出不合理时**优先怀疑模型与抽象**，而不是反复改代码凑输出。

## 1. 四阶段与暂停门禁（Phase gates）

| 阶段 | 产出文件 | 必备内容 | 暂停等人工确认 |
|---|---|---|---|
| P1 数学形式化 | `work/model_doc.md` | 决策变量、完整目标函数、全部约束/边界/逻辑假设、多目标量纲归一化 | **必须**（确认后才进 P3） |
| P2 图抽象文档 | `work/graph_abstraction.md` | 仅图论/网络类小问：节点定义与索引语义、边方向/权重/双向说明、孤立点·自环·不可达特例、算法-题型对齐 | **必须**（图论题） |
| P3 代码实现 | `work/code/` | 严格按已确认的 P1/P2 实现，不夹带"顺手改模型" | 否 |
| P4 结果复核 | `work/constraint_check.md`、`work/results.json` | 约束逐条满足性复核、结果解释、不可行/失败根因分析 | 否，但**产物缺失视为该环节未完成** |

- P1（图论题含 P2）未经用户确认，**不得写任何求解代码**。
- P3 期间发现模型必须修改 → 回到 P1 重走门禁并更新 model_doc，**禁止"代码先改了再补文档"**。
- 新项目的确认结论写入 `work/run_manifest.yaml`：P1/P2 人工确认记 `confirmed`，明确豁免记 `waived`，并注明谁确认、何时、改了什么；同时保留 `work/model_doc.md` 的「门禁记录」小节。仅旧项目在无 manifest 时回退到 `work/run_choices.md` 或 model_doc 记录。

## 2. P1 形式化最低要求（缺一即门禁不过）

每个小问独立成节，且**要素可编号引用**：

1. **决策变量**：符号、类型（连续/整数/0-1）、取值域、单位、变量规模。
2. **目标函数**：完整表达式（含下标与求和范围）+ 优化方向；多目标逐条编号 Z1, Z2, …（≥2 条即判为多目标小问）。
3. **约束**：编号 C1, C2, …，含边界条件、逻辑/条件约束、整数性、时间/空间耦合；每条注明**题面原文出处（保留原数字与单位）**。
4. **假设**：编号 A1, A2, …，写明"为什么可以这样简化"与失效条件。
5. **量纲归一化**（多目标必做）：各目标用什么归一化（min-max / 参考值 / 理想点 / 单目标最优选作尺度），归一化后取值范围。
6. **求解思路与规模判断**：算法 + 复杂度 + 变量/约束规模 + 预计耗时（对齐 `optimization-playbook.md` 时间预算表）。

**禁止**：只写"用线性规划求解"而无变量/目标/约束清单；把约束散落在正文叙述里不编号；用"等等/类似条件"省略约束。

**编号继承必须展开（2026-09-03，2023 D 压测发现）**：写"继承 C1–C12"这类区间简写时，门禁按区间**展开**成 C1…C12 计入本问约束集合（`check_formulation.declared_cids`）。因此**不能靠只写端点来藏漏写的约束**——展开后缺失的编号会在 `constraint_check.md` 覆盖核对时暴露。反过来，**检查器报告侧不接受区间汇总**：写"C1–C27 全部 PASS"不算证据，必须逐条列出编号 + 违约量，否则门禁 FAIL。

**题面自带的算例/等式是免费的正确性锚点**（§6 复核的第一批测试）：本题题面原文给出"用 3 个羊栏给 42 只母羊配种→孕期 6 栏、哺乳 7 栏、育肥+休整 9 栏"，据此才能锁定"栏数 = ⌈只数/容量⌉ 且同阶段跨批次合并装箱、哺乳期羔羊不单独计栏"的口径。凡题面含自算例、自等式（如"每 2 年 3 胎"）→ 必须先写成回归断言再写求解器。

## 3. 多目标专项（防"假最优"与范式漂移）

1. **禁止无依据加权合并**：不得把冲突目标随手加权求和降为单目标。用加权和必须写**权重来源**（专家打分 / AHP / 熵权 / 约束影子价格 / 预算或业务门槛 / 灵敏度标定），并配套权重灵敏度分析。
2. **范式锁定（只选一种）**：加权（带依据）/ ε-约束 / NSGA-II 类 Pareto 启发式 / 字典序（分层序列法）。**禁止迭代中来回切换范式**；主范式写进 model_doc 的「主范式（锁定）」一行。确需换范式 = 回到 P1 重新与用户确认，并在复盘中记录理由。
3. **对照 ≠ 摇摆**：model_doc 的「备选/对照模型」只做**一次性对照实验**（同数据、同口径、给结论差异），不得拿对照结果回头改主模型的输出；主模型与对照的选用与切换条件在求解前写死。
4. **必须先无量纲化**：量级/量纲不同的目标（如 万元 vs 栏·天 vs 只）先归一化再比较；禁止把不同量纲直接相加。
5. **交付物是 Pareto 解集，不是单个"最优数"**：输出非支配解集（前沿点数、覆盖的目标区间、前沿图）+ **折中点选取规则**（膝点 / TOPSIS / 业务门槛）；论文摘要与正文都不得只报一个"最优值"而不交代前沿与选取规则。若前沿退化为单点（目标实质不冲突/可分解），必须显式说明并给证据（两目标单最优解重合等）。
6. **不可行不硬凑**：求解器返回无可行解时，**禁止**不断调参、放宽超时、重写代码"逼出"可行解。必须产出不可行性分析（`work/infeasibility_report.md`）：逐条约束松弛定位冲突子集（IIS 思路）、题面理解/单位口径是否出错、边界与规模是否设置矛盾、需要业务侧裁决的点；论文如实报告不可行及原因。
7. **前沿质量自检**：解集内两两非支配自检通过；固定随机种子 + 多次独立运行（≥5）报告均值±标准差；记录种群/代数/耗时/评估次数；目标数 >3 时说明 NSGA-II 退化风险与对策。
8. **前沿质量指标必须可交叉验证**：归一化超体积（HV）要有**双实现**（手写扫描 + `pymoo.indicators.hv.HV`）并断言一致（2023D 实测两实现一致到 1e-16）；HV 必须写**参考点**（如归一化空间 (1,1)）；前沿含重复点/退化单点属异常，脚本应直接报错而不是凑点数。
9. **业务门槛无解 ⇒ 定量探针，不是硬凑**：若"零外租/预算上限/峰值不超限"这类门槛在预案族内无解，按 §3.6 出不可行性分析，并追加**规模缩放探针**（对基准方案整体乘 f、逐 f 重放）给出"做到零违约要付多少代价"。2023D 实测：零租用需缩容 7%，出栏 −7.3% 而期望损失反而 ×5.2（题面租用单价 3 > 空置单价 1）⇒ 结论从"不可行"升级为"该门槛在经济上不划算，应作为不推荐项呈现"。
10. **随机/序贯类：参数化方式本身就是模型假设**。逐桶/逐状态独立设决策变量（here-based）在样本外会塌缩——2023D 实测在样 Z2=1346 → 样本外 507（−38%），因为桶是**状态**而存量是**物理资源**，逐桶各配一份排产表等于重复使用同一批资源。默认交付「**路径无关基准方案 + 观测桶→选哪个方案的选择规则**」，并把在样/样本外两个值同时报告。
11. **任何对前沿的子集筛选都必须重算派生量**：一旦因可实现性或业务规则剔除前沿点（2023D：剔除「名义 m≥18 合规、实现被随机孕程挤到 17 天」的 11 个点），**归一化锚点、ẑ、超体积、膝点、间距全部作废重算**——非支配性会遗传到子集，但「膝点」不会（实测子集 HV 0.5026→0.4301、膝点 #62→#73，折中点因此改由业务门槛与单价比确定）。筛选规则写进 `results.json`（如 `front_implementable.rule`），主前沿与子前沿同时保留。
12. **灵敏度结论必须先减掉「蒙特卡洛噪声地板」**：随机/仿真评估下，先跑一组**同参数换种子**的重复（≥4 个种子），把它的散布当作噪声地板；小于地板的 ΔZ 不得称为"敏感"，必须写"在抽样噪声内"。2023D 实测：5 个种子的 Z1 散布仅 ±2%（秩相关 ρs≈1.0），而均值型扰动（产羔均值 ±10%、受孕率 ±10%）使 Z1 变化 260%–900% ⇒ 二者数量级差 100 倍，才能声称"水平移位敏感、形状扰动不敏感"。
13. **任何稳态/周期/线性化表示都要写明有效域，并给不变式自检**：矩阵化占用掩码的不变式是「列和 = 该阶段天数」（Σ_τ A_s[τ,d] = 天数）；一旦阶段天数超过周期（2023D：羔羊育肥 F=210 可长于周期 C=199），mod-C 的 0/1 掩码会把多世代覆盖**截成 1** ⇒ 低估占用、上界虚高。要么把掩码改成覆盖计数（F ≤ C 时与旧掩码逐元素相等 ⇒ 主输出零影响），要么把该格标为「超出模型有效域」而不作为结论汇报。Tornado 的越界格子会自动替你发现它。
14. **非冗余参数、严格内点与非循环留出验证（2026-11-25，2026 MCM C 压测沉淀）**：
   - **尺度/平移不变参数消元审查**：凡后续送入标准化（$z$-score）、归一化或排序（rank）的模块，超参数严禁与线性乘子同构（例如 $z(\gamma \ln v) \equiv z(\ln v)$ 会让 $\gamma$ 在灵敏度中数学恒等于零却假装独立生效）；必须改用改变函数曲率/凹凸性的参数（如 Box-Cox 指数 $\lambda$）并做消融实证目标确实单调挪动。
   - **禁止循环约束（同义反复）**：设计新机制或决策规则时，禁止将“必须拦截/满足某个已知争议测试样本”写进硬约束 C_k，再将「100% 拦截」当作建模成果汇报。必须明确划分**训练集**与**完全留出测试集（Holdout）**，仅在训练集调参求前沿，在留出集报告零泄露的样本外指标。
   - **膝点/最优超参贴边界红旗**：当 Pareto 膝点或最优权重直接落在搜索区间边界（如允许 $[0.25, 0.75]$ 而膝点卡在 $0.75$），属于高危告警；必须先拓宽区间（如扩至 $[0.05, 0.95]$）验证是否收敛于真正内点，或给出来自物理/规则的结构性边角解证明。

## 4. 图论/网络专项（防算法与题型错配）

P2 图抽象文档必须先于代码，四项齐备：

1. **节点**：节点集合定义 + **每个节点索引的含义**（例："1–26 对应附件位号 XJ-0001…"），虚拟源/汇、分裂节点（入/出）说明。
2. **边**：有向/无向、权重语义与单位、双向边如何表示（无向 → 两条同容量反向弧）、稀疏/稠密与数据源文件。
3. **特例处理**：孤立节点、自环、重边、不连通/不可达路径 → 如何处理或为何不存在（必须逐项交代，不允许"默认图是连通的"）。
4. **算法-题型对齐**：最短路（Dijkstra / Bellman-Ford / Floyd）≠ 最小费用流 ≠ 最大流/最小割 ≠ MST ≠ 连通性/匹配 ≠ TSP/VRP；算法复杂度必须匹配规模（>1000 节点禁 Floyd；TSP >20 节点不追求精确解；负权禁 Dijkstra）。
5. **口径确认**：坐标/距离/时间的单位与换算（2011B 教训：题面未写坐标单位，实为百米，差 10 倍）。

## 5. 迭代预算与终止（防死循环）

两级预算，均在 `work/iteration_log.md` 记账：

- **补丁级**：同一症状最多 **3 次**代码级修补（沿用既有"三次失败叫停"）。
- **轮次级**：同一小问「建模 ↔ 求解 ↔ 复核」整轮最多 **4 轮**。到上限立即**停止修改**，输出**当前模型缺陷分析**（defect report：未闭合的约束/目标、假设相互冲突处、规模与算法不匹配处、需用户裁决的点），交用户决定，不得继续无限试错。
- **每次尝试必须先写**：假设（"我认为根因是 X，因为 Y"）→ 最小验证 → 结论（命中/否定）。禁止无假设试错、禁止一次改多处。
- **修复优先级（严格按序）**：
  1. 数学模型 / 图抽象是否违反题面原文；
  2. 变量量纲、索引偏移（0-/1-based）、边界值与单位换算；
  3. 代码级小补丁。
  **禁止只做第 3 级而跳过前两级。**
- **题面条件不可篡改**：迭代中不得隐式新增、删除或放宽原题约束。确需软约束化/松弛，必须①引用题面原文依据（如 2018D"间隔 5~9 辆可接受但代价很高"属软目标）、②写进 model_doc、③量化代价并在灵敏度中报告。
- **补守恒式而非加惩罚项**：出现"OPTIMAL 但结果荒谬"（零损失、变量顶到上界）时，第一反应是找**没有成本约束的自由变量**并补回物理守恒/闭式定义，禁止用目标惩罚项、调界或改权重把结果"压"到看起来合理（2023D 两例：存量 n̄ 自由 ⇒ 养空母羊填栏把空置损失消成 0；公羊数 r 自由 ⇒ 顶到 500）。凡"占用资源但不计费"的变量一律审计一遍。
- **辅助变量的不等式方向 = 物理含义（方向审计）**：凡"资源需求量"型变量（闲置栏数、空置 U、外租 V、缺口、欠载量）必须写成 **≥ 需求量**（或直接闭式等式）；写成 ≤ 等于把"少开一栏"的自由留给求解器，目标会**系统性乐观**。审计法：对每个辅助变量问"它取 0 时物理上讲得通吗？"——只要取 0 能降低目标而违反现实，方向就反了。检查器要用**独立闭式**算一遍该变量的应有值并与解中的值对差。
  （2026-09-04 实测：2023D 设计层把 C9「闲置公羊栏」写成 `PR ≤ (r−P_mating)/4`，而同题 Q1 的 LP/CP-SAT 与 model_doc 都是正确的需求方向 ⇒ 文档对、代码反。退化角一眼看穿：设计层 n̄ 比解析锚点**高** 0.55%（上界不可能被超过），且 ε=1500 的外租成本 8194.8 < 可证下界 365·3·(Φ*−112) = 9967.5。）
- **单边界不够：由定义确定的量必须双向钉死（等式）**。上一条只给 `≥` 的修正立刻暴露第二种漂移——求解器**凭空多开**闲置公羊栏把空置洗成 0（同一 flock 下 min-Z1 端 Z1≡0）。凡「由其它变量闭式决定」的辅助量（这里 PR=(r−P_mating)/4、以及存量守恒、r=⌈n̄/50⌉）必须写成**等式**（两式或等式行），只给单方面边界一定会被利用；判别口诀：**这个变量在目标里有没有成本？没有 ⇒ 它必须被等式钉死**。修正后退化角实测：Z1(ε=1500) 反解外租 9.10274 栏 = Q1 缺口 Φ*−112 **逐位相等**，自由端 Z1 只余 0.71%（=周粒度税）。
- **修复后必须跑锚点回归**：每次改动后用**上一环节已验证的解**做回归（2023D：Q3 重放层应回落到 Q2 的 Y=1358、rams=9；差 2 栏可解释为周分桶惩罚）。没有回归锚点的修复等于没验证。
- **求解慢/无 incumbent ≠ bug**：先给"有效界 + 可行下界 + 对称破缺 + AddHint"，再给时间预算；到预算内产出 `FEASIBLE` 且 gap ≤ 预设阈值（如 5%）即**接受并继续**，不换范式、不加时（2023D：CP-SAT 加 `x[0] ≥ x[d]` 循环相位对称破缺后 300 s 内 FEASIBLE，gap 1.9%）。
- **松弛变量「顶格率」= 100% 是业务假设红旗**（免费午餐规则的对偶情形）：无成本、只有上界的变量会被顶到**上界**
  而不是取 0，于是整条前沿被一个从未记载的常数塑形（2023D 的 δ「超栏外溢」δ_max=16 ⇒ 90/90 预案全部顶格）。
  处置三步且不可省：① 在 model_doc 补编号并**标注「非题面约束/业务假设」**；② 检查器加逐条复算行，报「多少 % 解顶格」
  与「收紧为 0 的代价扫描」；③ 论文按假设口径写，并披露其对结论的影响（δ_max=0 时设计层前沿退化、出栏上限 −9.9%）。

## 6. 区分"能跑"与"结果正确"（强制复核）

代码无报错不代表模型正确。P3 之后必须完成：

1. **独立约束检查器**：另起脚本（不复用求解器内部逻辑）按 P1 的 C 编号逐条复算，输出 `work/constraint_check.md`：约束编号 → 违约量/最大相对偏差 → PASS/FAIL；目标值独立重算并与求解器报值比对（应达机器精度级一致）。
2. **上下界与交叉验证**：与手工小算例、解析上下界、LP 松弛、经典算法或独立第二算法、优秀论文结论对照（不一致要能解释）。
3. **单位/缩放链回代**：整数放大求解 → 还原 → 单位换算，每一环在检查器中复算（2011B：×100 → 百米 → ÷10 得分钟）。
4. **抽样读解**：随机 + 边界共取 3–5 个解，逐时刻/逐点人工核对语义是否真的符合题面（2011B 封堵截止、2018D 颜色×四驱联合可行都是这样暴露的）。
5. **解析锚点必须先于求解器结果被校验**：动手写求解器前先手算一个**闭式上界/下界/平均占用系数**，求解器一有输出就与锚点对账。上界**高于**解析上界 ⇒ 必然是实现错误（约束写反、变量可取负、漏约束），不是"更紧的界"。2023D 实测：LP 给出 n=443.8 > 解析 435.179，一眼暴露 C7/C8 符号反了 + 闲置公羊栏可取负；修正后 Δ=9.7e-13。
6. **检查器要走第二条实现路径**：独立复核不能复用求解器的同一套代码路径。矩阵/解析口径 ↔ 事件仿真/逐步重放口径互检，偏差应在机器精度（2023D 靠这条抓出"事件区间漏平移 t0"造成 696 只偏差）。
7. **评估窗口必须长于生产/物理管道长度**：稳态统计窗口若短于最长在制链条（2023D 首次出栏第 419 天 > 周期 229 天），结果会系统性偏低甚至全 0。设 burn-in（跳过前若干循环）并在检查器里复算窗口首尾语义。
8. **检查器自身的度量也要复核**：判定口径写错会同时造成假 PASS 与假 FAIL。2023D 两例：①把 `⌈⌉` 的小数部分当违约量（真实判据应为"不超容量 **且** 取整最小"）；②门禁把报告里的"FAIL 0 条"汇总文字当成违约行。判据改动一律配 self-test 用例。

9. **退化一致性角（degenerate-corner regression）——多问共模项目的最强自检**：若下游问题（随机/多目标/更细粒度）是上游问题的推广，必须构造一个**退化配置**把下游模型压回上游口径（等价类数 K=1、随机系数取题面确定值、取整溢价 π=0、人为上限放到不截断），要求解与目标值**逐项回落到上游的解析/LP 数字**（最好到常数级）。它一次同时检验模型结构、单位口径与不等式方向，成本只有 1–2 次求解。落不到同一数字时按三分法诊：①方向反/漏约束 ⇒ 真 bug，回 P1 改模型；②可解释的离散化税 ⇒ 写进有效域与误差预算（正好变成"近似假设代价"的量化数字）；③上游数字本身错 ⇒ 退回上一环节。（2026-09-04 实测：修完 C9 方向后退化角给出 Z1=0、n̄=432.01 vs 解析锚点 435.179，差 0.73% = 周决策粒度税 ⇒ 直接成为 A16 的量化证据；ε=1500 时 Z1=9967.500 与 365·3·9.1027 **逐项相等**。）
10. **可证下界/上界要写成断言跑在结果之前**：凡是能手算出目标值边界的情形（单价 × 缺口 × 时间因子、单批算例、全空置代价），就在检验脚本里 `assert` 之。"结果比理论上界还好"是最高性价比的缺陷探测器（本次第 9 条的 bug 就是被一条 3 行的下界断言抓到的）。
11. **口径变更的连带影响审计（筛选域/单位/角色定义一改，必须 grep 全部消费方）**：任何「可行域 / 可交付域 /
  归一化口径 / 角色定义」的变更，若只改了推荐点与检查器，而没改**生成结论的规则本身**（如「观测桶→选预案」的候选集），
  就会留下「结论合规、交付物违规」的隐性矛盾，而且**不报错、照常出数**（2023D R1-19：交付域 m≥19 引入后
  `q3_rollout` 仍指向被剔除的 m=18 点；修正后代价 Z1 +6.0% / Z2 +1.05%，互不支配 ⇒ 两个数一起报）。
  同一变更还会让**派生度量语义死亡**：`v2.minZ1_kept` 在全前沿比较 ⇒ 交付口径下恒 0，数字「看起来正常」但已无意义。
  ⇒ 改口径后逐个重问：这个度量现在还在比什么？并在聚合层按新域重算 + 显式标注旧字段不再引用。
12. **样本内可行性 ≠ 样本外预测力、无反演对照与统一后验口径（2026-11-25，2026 MCM C 压测沉淀）**：
   - **区分构造性可行与非构造性 OOS**：可行域反演/约束拟合类模型，样本内满足约束必然给出 100% 一致，绝不能将其充作预测准确率；必须附**闭式充要条件解析交叉核验**，并跑至少一个无当期结果泄露的**非构造性样本外（OOS）基线**（如朴素物理基线 / 时序顺延 / 留一季特征预测）来诚实界定“部分识别”边界。
   - **无反演直接对照通道防机械相关**：当归因回归使用上游由生存结局倒推的隐变量时，必须同口径补一条不经过反演的**直接观测因果通道**（如直接生存 Logit / 残差回归），全特征报告 BH-FDR $q$ 值，并对 $n<10$ 稀少样本标为低功效、严禁进摘要当主发现。
   - **统一后验样本集合 + 2D 离散度相变扫描**：下游反事实重放、新机制评估与灵敏度表格必须强制共用**完全同一套后验抽样集合**，禁止前节用抽样/后节用 MAP 或两节数字对不上；当 MaxEnt/正则化点估计会压平变异性时，必须在「离散度比 × 相关性」平面做 2D 相变扫描并给出结论翻转边界 $R^*(\rho)$。

## 7. 反 slop（禁止表面功夫）

- **无效迭代定义**：只改图例、字号、措辞、随机种子、超时上限等，而不改变模型/算法结论的操作。无效迭代照实计入 §5 预算，且必须在 log 标注"无效迭代"。
- 连续 2 次无效迭代 → 强制回到 §5 优先级 1：重读题面、质疑假设与建模逻辑，必要时向用户提问，而不是继续微调。
- 禁止为"结果好看"改数据、删异常样本、只报有利情景；异常、不确定性与失败路径如实报告（沿用既有"不掩盖、不凑数"）。
- 探索/调试脚本不得进 `work/code/`（`code_appendix.pdf` 唯一数据源纪律不变）。
- **诊断实验与主输出物理隔离**：规模缩放探针、等间隔族、NSGA-II/机会约束对照一律写进 `control`/`infeasibility_report.md`/独立的 `*_probe.*`，不并入 Pareto 点集与推荐点，避免"为了好看的结果改口径"。
- **未计算的量不得冒充实测**：`results.json` 里算不了的字段写 `null` + 一行理由与后续计划（2023D 的 `EVPI`），禁止用文献数字、估计值或旧口径填坑。
- **数字只有一个出处**：`results.json` 由脚本（如 `make_results.py`）从求解产物汇编并自带 `verify()` 出口自检（点数/归一化/plan_ref 文件存在/与产物逐项相等），写作环节只引用它。
- **带 `--only/--subset/--limit` 的诊断脚本必须回显「实际执行了什么」**：CLI 手解参数 `argv[i+1][0]` 会把
  `--only A,B` 截成 `{A}` ⇒ 三块诊断「成功退出」却**从未真跑**。现已统一打印
  `[argv] only=[...] -> 实际执行块 [...]`。凡"静默截断即静默漏跑"的参数入口都要自证执行范围。

## 8. 与阶段图映射

| 环节 | 适用条款 | 门禁动作 |
|---|---|---|
| 1 读题 | §4.5 单位口径、§2.3 约束原文出处 | brief.md **必须给每小问打题型标签**（优化-单目标 / 优化-多目标 / 图论网络 / 机理 / 数据驱动 / 评价 / 预测）并标注适用门禁 |
| 2 数据 | §6.3 | 数据口径与单位入 data_dictionary |
| 4 模型设计 | §1 P1、§2、§3.1–3.4、§4（P2） | **人工确认暂停**；`check_formulation.py --phase p1` 必须 PASS |
| 5 求解 | §3.5–3.7、§5、§6.1 | `--phase p3`；不可行必出 `infeasibility_report.md`；iteration_log 记账 |
| 6 检验 | §6.2–6.4、§3.7、§5 缺陷分析 | validation_report 必须引用 constraint_check 结论与前沿质量 |
| 7 图表 | §7 数字唯一出处（含 `meta.params`） | savefig 前 `layout_qa.audit_figure`；批后 `validate_figure_src` + `mech_text_audit`；读图复核用 `contact_sheet.py` 一次看全；图内文字最终 PDF ≥5 pt |
| 8 写作 | §3.5 前沿呈现、§6.3 单位 | 摘要/正文数字全来自 results.json，禁止单点"假最优" |
| 9 人工化 | §7 反 slop（禁编造踩坑故事） | 作者性素材取自 `iteration_log.md` 的 `R1-xx`；AI 使用记录四问式入附录 |
| 10 审查润色 | §7 数字唯一出处 | `consistency_check.py --check-fabricated` **反向核对必做**（论文→results.json，抓幻觉数字）；`audit_pdf_text.py` 在最终插图宽度下重跑；页数超预算不得靠缩图解决 |

## 9. 机械门禁脚本

```bash
python _shared/scripts/check_formulation.py --work work/              # 全流程门禁（p1+p3）
python _shared/scripts/check_formulation.py --work work/ --phase p1   # 只查形式化（环节 4 出口）
python _shared/scripts/check_formulation.py --work work/ --min-front 8
```

脚本只校验**结构与契约**（要素齐全、约束有编号、范式唯一锁定、权重有来源、归一化存在、图抽象四要素、迭代轮次 ≤4、前沿解集与检查器覆盖全部 C 编号）；**语义对错仍靠人工审 + §6 复核**。退出码非 0 = 门禁不过，禁止进入下一环节。

**v3.2 再加固三处（同一轮压测的环节 5–6 现场发现，self-test 现 18/18）**：

4. **Pareto 点缺逐点归一化字段 ⇒ FAIL**：旧版只看点数与文件存在性，"6 个点但只有原始目标值（没做无量纲化）"能蒙过门禁（§3.4 失效无人发现）。内联点集必须有 `z*_hat`/`*_norm` 字段；只存文件的点集降级为 WARN 并提示人工核对。
5. **`constraint_check.md` 的 FAIL 检测改为只数判定列**：旧版用 `has("FAIL", md)`，报告里写"小计：67 条检查，FAIL 0 条"这种**合规**文字会被当成违约，逼着模型去改措辞（典型的指标自身缺陷）。现在匹配 `| FAIL |` / `| **FAIL** |` 单元格。
6. **合规样例 fixture 同步升级**：`FRONT` fixture 原先也没有归一化字段——门禁变严后先跑 self-test，把"合规样例"补齐，再新增"缺归一化应拦""真 FAIL 无根因应拦""FAIL 0 条汇总不应误判"三个用例。**门禁脚本自己也要过 §6.8 的度量复核。**

**v3.1 加固的三处（2023 D 压测现场发现，均有 self-test 回归用例）**：

1. 声明侧的约束区间简写（C1–C12）自动展开计数，防"只写端点"蒙过覆盖核对；
2. `constraint_check.md` 只要存在就逐条核对覆盖（旧版把整段 P3/P4 检查挂在 `results.json` 存在之下——检查器先写好、结果尚未落盘时完全不校验；写"C1–C5 全 PASS"这类汇总现在直接 FAIL）；
3. `--phase p3`（环节 5 出口）缺 `results.json` 由 WARN 改为 **FAIL**——旧版缺文件时只在错误分支里 WARN，等于"什么都没产出也能过关"。

## 10. 分析：这份提示词补了什么、与既有规范的两处冲突及处置

**补上的缺口**（v2.9 之前工作流里没有明文）：

1. 范式锁定与"禁止迭代中来回切换"——旧规范只写"多目标可用加权/ε-约束/帕累托"，没有唯一性与防漂移约束。
2. 轮次级迭代预算（≤4）与**到限即输出缺陷分析**——旧规范只有"同一处改 3 次叫停"（补丁级）。
3. 不可行的正确处置是**报告冲突分析**而非调参逼解——旧规范只说"记录诊断信息回写 model_doc"。
4. 独立约束检查器 + 目标值独立复算（把 2020C 临场写的 `check_solution_credit.py` 提升为硬要求）。
5. 图抽象文档作为**独立暂停门禁**（2011B 是在 model_doc 里附带写的，没有单文件与门禁）。
6. "无效迭代"定义与反 slop 回滚规则（旧规范有"不调参凑数"，但无可判定定义）。
7. Pareto 交付物纪律：禁止单点"假最优"，前沿退化也要证据。

**与既有规范的冲突及处置**：

- 冲突①：原提示词"Choose ONE paradigm only" vs 本工作流"主模型 + 1 个对照/备选模型"（环节 4 既有要求）。处置：**主范式唯一锁定**，对照/备选只做一次性对照实验、不参与回头改主模型输出（§3.2–3.3 已明确区分"对照"与"摇摆"）。
- 冲突②：原提示词"最多 4 轮" vs 既有"同一处改 3 次仍失败"。处置：**两级预算并存**（补丁级 3 次、轮次级 4 轮），都在 iteration_log 记账，避免把两个数字混为一谈。
- 需要保留的本地优势（未被原提示词覆盖，继续生效）：数字事实表防幻觉、文献逐条核验、渲染/版面/视觉复核、代码附件与提交包纪律、题面单位靠优秀论文交叉证实。

## 11. 原始提示词（可追溯）

> 用户 2026-09-03 提供，逐条对应 §1–§7。

```text
You are a rigorous mathematical modeling assistant for mathematical-modeling contests.
Strictly follow this workflow and rules, DO NOT skip any step.

## Core Ground Rules to avoid infinite loop & patch-loop debugging
1. Model-first, code-second. Never jump directly to writing code. Before generating any code, you must
explicitly output: clear definition of all decision variables; full objective function(s); complete list of
constraints, boundary conditions, logical assumptions; unit normalization description for multi-objective
terms. Human must verify this mathematical formulation is correct before you proceed to implement code.
You are forbidden to tweak code blindly to fix bad outputs without reviewing the top-level mathematical model.
2. For multi-objective optimization problems: do NOT arbitrarily merge multiple conflicting objectives into
one weighted-sum without justifying weight sources. Choose ONE paradigm only: weighted-sum with
justification / ε-constraint / NSGA-II-style Pareto heuristic. Do NOT switch paradigms back and forth in
iterations. Explicitly perform dimension normalization for objectives of different magnitudes. Your expected
output is Pareto-optimal solution set, not a single fake "best number". If solver returns no feasible solution,
analyze whether constraints are conflicting. Do NOT endlessly tune parameters or rewrite code to force a
feasible result. Report infeasibility analysis instead.
3. For graph-theoretic tasks (shortest path, network flow, spanning tree, topology etc.): before writing code,
document graph abstraction explicitly: definition of nodes, meaning of each node index; definition of edges,
direction, weight, bidirectional-edge note; special-case handling note: isolated nodes, self-loops, unreachable
paths. Only after this abstraction is confirmed reasonable can you generate implementation code. Distinguish
problem types clearly: do not confuse min-cost-flow, Dijkstra, connectivity and MST. Match algorithm
complexity to problem scale.
4. Iteration & termination rules to prevent infinite loop: maximum iteration rounds for debugging: 4 rounds.
After reaching the limit, stop iteration and output defect analysis of current model rather than keep modifying
code. When you get unreasonable outputs / runtime errors: Priority 1 check whether the mathematical model or
graph abstraction violates the original problem statement; Priority 2 check variable dimension, index offset,
boundary value; Priority 3 minor code-level patching. Never only patch code syntax while ignoring top-level
logic flaws. You must strictly preserve original problem conditions. Do NOT invent or alter problem
constraints implicitly during repeated revisions.
5. Distinguish "runnable code" and "mathematically correct result": code executing without errors does NOT
mean the model is correct. After code runs, cross-validate whether outputs satisfy all constraints of the
original problem.
6. Anti-slop requirement: avoid superficial cosmetic tweaks. If multiple attempts produce bad results, roll back
to re-examine assumptions and modeling logic, instead of making trivial parameter adjustments.

## Output format discipline
Phase 1: Mathematical formulation (variables, objectives, constraints, assumptions, normalization). Pause for
validation. Phase 2: Graph abstraction document (only for graph problems). Pause for validation.
Phase 3: Python implementation code. Phase 4: Result interpretation, constraint-satisfaction check, failure
analysis if applicable.
```
