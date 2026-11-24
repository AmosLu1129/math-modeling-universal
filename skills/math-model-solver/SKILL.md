---
name: math-model-solver
description: 把模型文档实现为可复现代码（Python 优先，支持 MATLAB），计算数值结果并结构化存入 results.json，组织最终代码目录并产出初版 final_models.md。当模型定义好了需要编程求解、跑实验、拿到论文所需的全部数字时使用。
---

# 模型求解

## 输入输出

- 输入：`work/model_doc.md`、`work/data_clean/`
- 输出：`work/code/`（最终代码）、`work/results.json`、`work/final_models.md`（初版）
- 强制产物（优化/多目标/图论/调度类小问）：`work/constraint_check.md`（独立约束复核）、`work/iteration_log.md`（迭代记账）；不可行时另出 `work/infeasibility_report.md`

## 本环节硬门禁：门禁不过不写代码（不可跳过）

> 全文规则见 `_shared/references/model-first-sop.md`（§3 多目标、§5 迭代预算、§6 能跑≠对、§7 反 slop）；历次踩坑经验见 `references/solver-lessons.md`。

1. **入口先验门禁**：`python _shared/scripts/check_formulation.py --work work/ --phase p1` 必须 PASS；`work/run_manifest.yaml` 中 P1（及图论题 P2）已记录 `confirmed` 或 `waived` → 否则**禁止开始写求解代码**，退回 `math-model-design`。
2. **禁止在代码里改模型**：实现期间发现模型需修改，必须回到 P1 更新 `model_doc.md` 并重过门禁；不允许“代码先改了再补文档”。
3. **多目标交付物是 Pareto 解集**：输出非支配解集（内联点数 `>=5`、含 `z*_hat` 归一化字段、前沿图、`plan_ref`）+ 折中点选取规则；**禁止只报单个“最优数”**。前沿退化为单点必须给证据。范式沿用 `model_doc.md` 锁定值，不得中途切换。
4. **不可行不硬凑**：求解器无可行解 → 禁止不断调参、放宽超时或偷偷删约束逼出解。必须按 IIS 思路定位冲突约束子集、核对题面与单位口径，产出 `work/infeasibility_report.md` 并回写 `model_doc.md`。
5. **能跑 ≠ 对（独立复核）**：
   - 先手算解析上下界/锚点并与求解器输出对账；
   - 另起**独立约束检查器**（不复用求解器内部逻辑），按 `model_doc.md` 的 C 编号逐条复算违约量、独立重算目标值并写入 `work/constraint_check.md`（禁止写“C1–C20 全部 PASS”这类区间汇总）；
   - 做单位/缩放链回代与 3–5 个解的抽样人工读解；
   - **反演/可行域题必须区分样本内可行性与样本外（OOS）预测力**：补充闭式充要条件解析交叉核验 + ≥1 个无当期结局泄露的非构造性 OOS 基线（Naive / 时序顺延 / 留一季特征），禁止把约束构造出的 100% 当预测准确率。
6. **出口自检**：`python _shared/scripts/check_formulation.py --work work/ --phase p3` 退出码为 0 才能进阶段 6。（注意：本阶段不得用裸 `--phase all`，`all` 会检查阶段 6 的 `validation_report.md`。）

## 实现与产物规范

- **语言与工具**：Python 优先（优化 `scipy.optimize`/PuLP/OR-Tools CP-SAT；多目标 `pymoo` 或 ε-约束 + MILP；统计 `statsmodels`；ML `scikit-learn`/LightGBM；ODE `solve_ivp`；图论 `networkx`）。运筹优化题先读 `_shared/references/optimization-playbook.md`。
- **代码组织**：`work/code/` 只保留最终版代码（探索/调试脚本放 `work/scratch/`），每文件头部注明【题号 / 模型 / 功能 / 依赖 / 入口】；这是 `code_appendix.pdf` 的唯一数据源。
- **`results.json` 唯一出处**：由脚本（如 `make_results.py`）从求解产物汇编并自带 `verify()` 断言，禁止手抄；强制在顶层生成 **`key_metrics`** 路径清单（配合 `consistency_check.py --key-metrics` 聚焦核心指标），下游反事实与策略评估必须复用**同一套后验抽样集合**；多目标前沿若在评估后按可行门槛剪枝，必须重算 `front_size` 与双实现 `hypervolume`。多目标/随机策略按 `eps_main`（含 `hypervolume`、`hypervolume_ref`、`hypervolume_crosscheck`、`pareto[].z*_hat`、`pareto[].plan_ref`、`front_implementable`）、`policy`、`rollout`（含 `out_of_sample`）结构存放。
- **官方结果模板回填**：使用 `_shared/scripts/fill_result_template.py`，回填后自动回读校验。
- **`final_models.md`（初版）**：汇总每个模型的最终方程、代入参数与初步指标，交阶段 6 定稿。

## 系统化调试与两级预算（结果不对时）

1. **修复优先级严格按序**：① 数学模型/图抽象是否违反题面 → ② 变量量纲、0/1-based 索引、单位换算 → ③ 代码级小补丁。禁止跳过 ①② 直接调参打补丁。
2. **两级预算**：同一症状代码补丁 **≤ 3 次**；同一小问「建模↔求解↔复核」整轮 **≤ 4 轮**，到限立即停止并输出模型缺陷分析交用户裁决。
3. **记账与无效迭代**：每次尝试记入 `work/iteration_log.md`（假设 → 最小验证 → 结论）；只改超时/种子/字号而不改结论的记为「无效迭代」，连续 2 次无效迭代必须回滚重审题意与假设。
