#!/usr/bin/env python3
"""先建模后代码 SOP 机械门禁检查器（见 _shared/references/model-first-sop.md）。

只校验「结构与契约」：形式化要素是否齐全、约束是否编号、多目标范式是否唯一锁定、
权重是否有来源、是否做无量纲化、图抽象四要素、迭代轮次预算、Pareto 解集与独立
约束检查器的覆盖。语义对错仍需人工审定 + 独立复核。

用法：
    python check_formulation.py --work work/ [--phase p1|p3|all] [--min-front 5]
退出码：0=门禁通过（可能有 WARN）；1=存在 FAIL，禁止进入下一环节。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

PARADIGMS = {
    "加权和": (r"加权和|加权求和|weighted[\s-]*sum|加权法",),
    "ε-约束": (r"ε[\s\-]*约?束|epsilon[\s\-]*constraint|ε-constraint",),
    "字典序/分层序列": (r"字典序|分层序列|lexicograph|preemptive",),
    "NSGA-II/帕累托": (r"nsga|moea|spea|进化算法|遗传算法",),
}
PARETO_FALLBACK_PAT = r"pareto|帕累托|非支配"
GRAPH_ALGOS = (r"dijkstra|bellman|floyd|最小费用流|最大流|最小割|min-?cut|生成树|\bmst\b|匈牙利|匹配|\btsp\b|\bvrp\b|网络流|最短路")

HEAD = re.compile(r"^(#{1,5})\s+(.*)$")
QNAME = re.compile(
    r"(?:问题|小问|Question|Problem)\s*[（(]?\s*([0-9０-９一二三四五六七八九十]+(?:\s*[.．]\s*[0-9]+)?)"
    r"|\b[Qq]\s*([1-9](?:\s*[.．]\s*[0-9]+)?)"
)
CID = re.compile(r"\bC\s*(\d{1,2})\b")
CID_ALT = re.compile(r"约束\s*[（(]?\s*(\d{1,2})\b")
# 「继承 C1–C12 / C1-C5 / C1 至 C5」这类区间简写：只写端点会藏住漏写的约束，必须展开
CRANGE = re.compile(r"\bC\s*(\d{1,2})\s*(?:[–—~\-]|至|到)\s*(?:C\s*)?(\d{1,2})\b")
ZID = re.compile(r"\bZ\s*_?\s*(\d)\b")
ROUND = re.compile(r"第\s*(\d+)\s*轮|\b(?:Round|Iteration)\s*(\d+)\b|\bR(\d+)-\d+\b", re.I)


def extract_rounds(text: str) -> list[int]:
    """提取中英文轮次编号（第 N 轮 / Round N / Iteration N / RN-k）。"""
    out: list[int] = []
    for g1, g2, g3 in ROUND.findall(text):
        tok = g1 or g2 or g3
        if tok:
            out.append(int(tok))
    return out

NUM_MAP = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}


def norm_num(s: str) -> int | None:
    s = s.strip()
    if s.isdigit():
        return int(s)
    full = {"０": "0", "１": "1", "２": "2", "３": "3", "４": "4", "５": "5",
            "６": "6", "７": "7", "８": "8", "９": "9"}
    if s and all(ch in full for ch in s):
        return int("".join(full[ch] for ch in s))
    return NUM_MAP.get(s)


class Sec:
    def __init__(self, name: str, level: int, start: int):
        self.name, self.level, self.start, self.lines = name, level, start, []
        self.title = name

    @property
    def text(self) -> str:
        return "\n".join(self.lines)


def split_sections(md: str) -> list[Sec]:
    """按标题切分，保留属于「问题X / Q1 / Problem 2」的小问节（含其所有子标题）。"""
    sections: list[Sec] = []
    cur: Sec | None = None
    for i, line in enumerate(md.split("\n")):
        m = HEAD.match(line)
        if m:
            level, title = len(m.group(1)), m.group(2).strip()
            qm = QNAME.search(title)
            if qm and level <= 4:
                raw = re.sub(r"\s+", "", qm.group(1) or qm.group(2) or "")
                cn = norm_num(raw)
                cur = Sec(f"问题{cn if cn is not None else raw}" if raw else title[:24], level, i)
                cur.title = title
                sections.append(cur)
                continue
            if cur and level <= cur.level:
                cur = None
                continue
        if cur:
            cur.lines.append(line)
    secs = [s for s in sections if s.text.strip()]
    seen: dict[str, int] = {}
    for s in secs:  # 同名标签（多节都写 Q2 等）加标题后缀去重，避免报错串台
        seen[s.name] = seen.get(s.name, 0) + 1
        if seen[s.name] > 1:
            s.name = f"{s.name}（{s.title[:16]}）"
    return secs


def has(pattern: str, text: str) -> bool:
    return re.search(pattern, text, re.I) is not None


def declared_cids(text: str) -> set[str]:
    """model_doc 侧的约束编号收集：显式编号 + 区间展开（C1–C12 ⇒ C1..C12）。

    只用于**声明侧**；`constraint_check.md` 的覆盖核对**不做区间展开**——
    检查器必须逐条列出编号才算真复算，写「C1–C27 全部 PASS」不算证据。
    """
    found = {f"C{n}" for n in CID.findall(text)} | {f"C{n}" for n in CID_ALT.findall(text)}
    for lo_s, hi_s in CRANGE.findall(text):
        lo, hi = int(lo_s), int(hi_s)
        if 1 <= lo <= hi <= 99 and hi - lo <= 40:
            found |= {f"C{k}" for k in range(lo, hi + 1)}
    return found


def find_paradigm_line(text: str) -> str | None:
    pat = r"主范式|求解范式|范式（|范式\(|primary\s+paradigm|locked\s+paradigm|\bparadigm\b"
    lines = text.split("\n")
    heading_idx: int | None = None
    for idx, line in enumerate(lines):
        if has(pat, line):
            if HEAD.match(line):
                if heading_idx is None:
                    heading_idx = idx
            else:
                return line
    if heading_idx is not None:
        # 若只有标题行含 "Primary Paradigm" 等关键字，补充其后紧邻的 1–2 行正文作为声明上下文
        fallback_parts = [lines[heading_idx]]
        for j in range(heading_idx + 1, min(len(lines), heading_idx + 4)):
            nxt = lines[j].strip()
            if HEAD.match(lines[j]):
                break
            if nxt:
                fallback_parts.append(nxt)
                if len(fallback_parts) >= 3:
                    break
        return " ".join(fallback_parts)

    # 宽松兜底：自然英文或无显式「主范式」标签时，识别明确声明求解范式的句子
    fallback_pat = r"epsilon[\s\-]*constraint|ε[\s\-]*约束|weighted[\s\-]+sum|lexicograph|nsga-?ii|closed[\s\-]+loop\s+pareto"
    for line in lines:
        if has(fallback_pat, line) and not HEAD.match(line):
            return line
    return None


def match_paradigms(pline: str) -> list[str]:
    """识别主范式；若已明确匹配 ε-约束/加权和/字典序或显式进化算法，不再把同句 Pareto 说明重复算作第二种范式。"""
    hit = [name for name, pats in PARADIGMS.items() if any(has(p, pline) for p in pats)]
    if not hit and has(PARETO_FALLBACK_PAT, pline):
        hit.append("NSGA-II/帕累托")
    return hit


def extract_brief_tags(brief: str) -> dict[str, str]:
    """从 brief.md 抽取每小问标题与题型标签文本，按规范小问名（如 '问题2'）索引。"""
    tags: dict[str, str] = {}
    for sec in split_sections(brief):
        canon = sec.name.split("（", 1)[0]
        tag_lines = [
            ln for ln in sec.lines
            if has(r"题型标签|Problem\s*Tag|Model\s*Type|类型", ln)
        ]
        payload = (sec.title + "\n" + ("\n".join(tag_lines) if tag_lines else sec.text[:300])).strip()
        tags[canon] = (tags.get(canon, "") + "\n" + payload).strip()
    return tags


def is_non_opt_subproblem(sec: Sec, brief_tag: str, is_mo: bool) -> bool:
    """识别明确属于统计/评价/分类/预测/仿真/对比且非优化/反演/图论的小问。"""
    if is_mo:
        return False
    tag_ctx = f"{sec.title}\n{brief_tag}"
    if has(
        r"优化|规划|调度|选址|路径|图论|网络流|博弈|反演|"
        r"optimiz|linear\s+program|integer\s+program|milp|scheduling|routing|graph|network\s+flow|inverse|mechanism\s+design",
        tag_ctx,
    ):
        return False
    return has(
        r"数据驱动|统计|回归|评价|分类|预测|仿真|模拟|对比|归因|描述|"
        r"statistical|regression|mixed[-\s]*effects|classification|evaluation|comparative|forecast|predict|simulation|attribution|descriptive",
        tag_ctx,
    )


def has_actual_infeasibility(obj) -> bool:
    """递归检查 results.json 是否存在真实不可行（忽略 n_infeasible_weeks: 0 / 'none' / 'non-infeasible'）。"""
    if isinstance(obj, dict):
        for k, v in obj.items():
            ks = str(k)
            if has(r"infeasib|不可行", ks):
                if isinstance(v, bool):
                    if v:
                        return True
                elif isinstance(v, (int, float)):
                    if v > 0:
                        return True
                elif isinstance(v, (list, dict)):
                    if len(v) > 0:
                        return True
                elif isinstance(v, str):
                    if not re.fullmatch(r"\s*(?:none|no|0|zero|pass|feasible|无)\s*", v, re.I):
                        return True
                continue
            if has_actual_infeasibility(v):
                return True
        return False
    if isinstance(obj, (list, tuple)):
        return any(has_actual_infeasibility(item) for item in obj)
    if isinstance(obj, str):
        for m in re.finditer(r"\binfeasib\w*|不可行", obj, re.I):
            prefix = obj[max(0, m.start() - 16) : m.start()]
            if re.search(r"(?:\b0\s+|\bno\s+|\bzero\s+|\bnon[\s\-]?|无|非|未出现)\s*$", prefix, re.I):
                continue
            return True
    return False


def detect_graph(sec_text: str, brief_tags: str) -> bool:
    if has(r"图论|网络流|最短路|选址|路径|调度|巡检", brief_tags):
        return True
    return has(r"节点集合|图抽象|邻接|边集|顶点", sec_text)


def find_fronts(obj, out: list[tuple[str, list]]) -> None:
    """递归寻找形如 Pareto 解集的列表：长度>=2，元素含>=2 个数值目标。"""
    if isinstance(obj, list):
        good = []
        for it in obj:
            vals = None
            if isinstance(it, dict):
                nums = [v for v in it.values() if isinstance(v, (int, float)) and not isinstance(v, bool)]
                if len(nums) >= 2:
                    vals = nums
            elif isinstance(it, (list, tuple)) and len(it) >= 2:
                nums = [v for v in it if isinstance(v, (int, float)) and not isinstance(v, bool)]
                if len(nums) >= 2:
                    vals = nums
            if vals:
                good.append(it)
        if len(good) >= 2 and all(isinstance(x, (dict, list, tuple)) for x in obj):
            out.append((obj_key_hint(obj), good))
        for it in obj:
            find_fronts(it, out)
    elif isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(v, list):
                tmp: list[tuple[str, list]] = []
                find_fronts(v, tmp)
                nums = [x for x in v if isinstance(x, (dict, list, tuple))]
                if len(v) >= 2 and re.search(r"pareto|front|nondom|前沿", str(k), re.I):
                    out.append((str(k), nums))
                else:
                    for name, lst in tmp:
                        out.append((f"{k}.{name}", lst))
            else:
                find_fronts(v, out)


def obj_key_hint(obj: list) -> str:
    return "unnamed_front"


def front_size_declared(obj) -> int:
    """接受"前沿以汇总指标入表 + 原始点集另存文件"的写法：找 front_size 类字段。"""
    best = 0
    stack = [obj]
    while stack:
        cur = stack.pop()
        if isinstance(cur, dict):
            for k, v in cur.items():
                if isinstance(v, int) and not isinstance(v, bool) and re.search(
                        r"front_size|pareto_size|nondom|n_points|front_points|前沿点数", str(k), re.I):
                    best = max(best, v)
                stack.append(v)
        elif isinstance(cur, list):
            stack.extend(cur)
    return best


def front_artifact(work: Path) -> list[str]:
    return sorted(p.name for p in work.rglob("*")
                  if p.is_file() and re.search(r"pareto|front|非支配|前沿", p.name, re.I)
                  and p.suffix.lower() in (".csv", ".json", ".npz", ".npy", ".txt", ".parquet"))


class Gate:
    def __init__(self) -> None:
        self.items: list[tuple[str, str, str]] = []  # (status, target, message)

    def add(self, status: str, target: str, message: str) -> None:
        self.items.append((status, target, message))

    def fail(self, target: str, message: str) -> None:
        self.add("FAIL", target, message)

    def warn(self, target: str, message: str) -> None:
        self.add("WARN", target, message)

    def ok(self, target: str, message: str) -> None:
        self.add("PASS", target, message)

    @property
    def n_fail(self) -> int:
        return sum(1 for s, _, _ in self.items if s == "FAIL")

    @property
    def n_warn(self) -> int:
        return sum(1 for s, _, _ in self.items if s == "WARN")


def read(p: Path) -> str:
    try:
        return p.read_text(encoding="utf8", errors="ignore")
    except OSError:
        return ""


GOOD_DOC = """## 问题1
**决策变量**：x_ij ∈ {0,1}，832 个；s_t ≥ 0（栏）。
**目标函数**：Z1 = max 年化出栏量（只/年）。
**约束**：C1 栏位容量 ≤ 112（题面原文）；C2 公母比 ≥ 1:50（题面原文）；C3 不同阶段不同栏（题面原文）。
**模型假设**：A1 不考虑淘汰更新（题面明示）。
**求解算法与工具**：CP-SAT，<1k 变量，30s–2min。

## 问题2
**决策变量**：同上 + 外租量 r_t ≥ 0（整数）。
**目标函数**（多目标）：Z1 = min 期望空置损失，Z2 = min 期望租用损失。
**主范式（锁定）**：ε-约束法。
**量纲归一化**：以各单目标最优值 18.4 / 96.0 作参考值 min-max 归一化到 [0,1]。
**约束**：C1 C2 C3 同问题1；C4 哺乳期 35–45 天；C5 受孕率 85%。
**折中点选取规则**：膝点法 + 业务门槛。
**模型假设**：A2 场景独立同分布。
**求解算法与工具**：CP-SAT + ε 网格，1k–5k 变量，2–5 min。
"""

BAD_DOC = """## 问题1
用多目标加权求和法求解，目标是最小化损失；不行就换 NSGA-II 试试。约束是栏位不够就外租。
**主范式（锁定）**：加权法与 NSGA-II 交替使用。
"""

GRAPH_DOC = """## 问题1
**决策变量**：y_v ∈ {0,1} 是否封锁节点 v。
**目标函数**：Z1 = min 最大到达时间。
**约束**：C1 每封堵点先于逃犯到达；C2 封锁点数 ≤ 20。
**模型假设**：A1 车速恒定 40 km/h。
**求解算法与工具**：Dijkstra + 节点分裂 max-flow 最小割。
"""

FRONT = ("""{"Q2": {"eps": {"pareto": ["""
           """{"z1":1.0,"z2":9.0,"z1_hat":0.0,"z2_hat":1.0},"""
           """{"z1":2.0,"z2":6.0,"z1_hat":0.167,"z2_hat":0.75},"""
           """{"z1":3.0,"z2":4.4,"z1_hat":0.333,"z2_hat":0.533},"""
           """{"z1":4.1,"z2":3.2,"z1_hat":0.517,"z2_hat":0.375},"""
           """{"z1":5.5,"z2":2.9,"z1_hat":0.75,"z2_hat":0.338},"""
           """{"z1":7.0,"z2":2.5,"z1_hat":1.0,"z2_hat":0.275}],"""
           """ "hypervolume": 0.67, "knee_rule": "knee+门槛"}}, "Q1": {"cp_sat": {"max_out": 1512.4}},"""
           """ "validation": {"v1_cells": 97, "v2_cases": 22, "v3_asserts": "pass"}}""")

CHECKS = """| 编号 | 违约量 | 结论 |
|---|---|---|
| C1 | 0 | PASS |
| C2 | 0 | PASS |
| C3 | 0 | PASS |
| C4 | 0 | PASS |
| C5 | 0 | PASS |
目标值独立复算最大偏差 3e-13。
"""

FRONT_NO_NORM = ("""{"Q2": {"eps": {"pareto": [{"z1":1.0,"z2":9.0},{"z1":2.0,"z2":6.0},"""
                 """{"z1":3.0,"z2":4.4},{"z1":4.1,"z2":3.2},{"z1":5.5,"z2":2.9},{"z1":7.0,"z2":2.5}],"""
                 """ "hypervolume": 0.67}}}""")

# 环节 6 出口（--phase all）所需的合规产物：检验报告三要素 + 定稿无占位
VALIDATION_DOC = """# 模型检验与灵敏度分析报告
## 3. 灵敏度分析：±5/10/20% 二维网格 Tornado 弹性排序（97 格）。
## 4. 随机稳健性：换种子 4 次 + 样本量/评估窗口，噪声地板 ±2%。
## 8. 适用边界与失效条件：循环稳态有效域、业务假设披露。
"""

FINAL_MODELS_OK = "# 最终模型定稿\n\nM1：$Y=3.18777n$，代入 $u=0.2573654$。\n"

CHECKS_REALFAIL = CHECKS.replace("| C5 | 0 | PASS |", "| C5 | 3.2 | FAIL |")

CHECKS_SUMMARY_ONLY = ("| 编号 | 内容 | 违约量 | 结论 |\n|---|---|---|---|\n"
                       + "".join(f"| C{n} | 阶段容量 | 0 | PASS |\n" for n in range(1, 6))
                       + "\n小计：5 条逐编号检查，FAIL 0 条。\n")


def self_test() -> int:
    """回归自检（TESTBED 回归检查清单第 2 条）：合规样例应过、违规样例应挂、图论样例应触发 P2 门禁。"""
    import subprocess
    import tempfile

    root = Path(tempfile.mkdtemp(prefix="gate_selftest_"))

    def build(name: str, files: dict[str, str]) -> Path:
        w = root / name / "work"
        w.mkdir(parents=True)
        for fn, body in files.items():
            w.joinpath(fn).write_text(body, encoding="utf8")
        return w

    good = build("good", {
        "brief.md": "# 问题简报\n### 问题一\n- 题型标签：优化-单目标\n### 问题二\n- 题型标签：优化-多目标\n",
        "model_doc.md": "# 模型设计\n\n" + GOOD_DOC,
        "results.json": FRONT,
        "constraint_check.md": CHECKS,
        "iteration_log.md": "第 1 轮：假设 ε 上界过大导致 C1 冲突，因为需求高估；最小验证：单期手算；结论：命中。\n",
        "validation_report.md": VALIDATION_DOC,
        "final_models.md": FINAL_MODELS_OK,
    })
    bad = build("bad", {
        "brief.md": "# 问题简报\n### 问题一\n- 题型标签：优化-多目标\n",
        "model_doc.md": "# 模型设计\n\n" + BAD_DOC,
        "results.json": '{"Q1": {"best": 42.0, "status": "INFEASIBLE"}}',
        "iteration_log.md": "第 1 轮 换种子\n第 2 轮 改种群\n第 3 轮 改超时\n第 4 轮 再改超时\n第 5 轮 换库\n",
    })
    graph = build("graph", {
        "brief.md": "# 问题简报\n### 问题一\n- 题型标签：图论网络\n",
        "model_doc.md": "# 模型设计\n\n" + GRAPH_DOC,
    })

    def run(work: Path, *extra: str) -> tuple[int, str]:
        r = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--work", str(work), *extra],
                           capture_output=True, text=True)
        return r.returncode, r.stdout + r.stderr

    cases = []
    code, out = run(good)
    cases.append(("合规样例应通过", code == 0, out.strip().splitlines()[-1] if out else ""))
    code, out = run(bad)
    n_fail = out.count("[FAIL]")
    cases.append(("违规样例应拦截且 ≥8 项 FAIL", code == 1 and n_fail >= 8, f"{n_fail} FAIL"))
    for probe in ("范式未锁定", "缺【决策变量】", "Pareto 解集", "infeasibility_report", "4 轮上限", "独立约束检查器"):
        cases.append((f"违规样例应报：{probe}", probe in out, ""))
    code, out = run(graph)
    cases.append(("图论样例应触发 P2 图抽象门禁", code == 1 and "graph_abstraction.md" in out, ""))

    # 区间简写：声明侧展开 C1–C5，检查器侧必须逐条列出（写「C1–C5 全 PASS」不算证据）
    rng = build("range", {
        "brief.md": "# 问题简报\n### 问题一\n- 题型标签：优化-单目标\n",
        "model_doc.md": ("## 问题1\n**决策变量**：x_d ∈ Z≥0，229 个。\n**目标函数**：Z1 = max 年化出栏 Y。\n"
                         "**约束**：继承 C1–C5（阶段容量与栏数上限）。\n**模型假设**：A1 循环稳态。\n"
                         "**求解算法与工具**：CP-SAT，<2k 变量，<10 min。\n"),
        "constraint_check.md": "| 编号 | 违约量 | 结论 |\n|---|---|---|\n| C1 | 0 | PASS |\n| C2 | 0 | PASS |\n"
                               "| C3 | 0 | PASS |\n| C5 | 0 | PASS |\n",
    })
    code, out = run(rng)
    cases.append(("区间简写应展开且检查器缺 C4 时拦截", code == 1 and "C4" in out, ""))
    rng.joinpath("constraint_check.md").write_text(
        "| 编号 | 违约量 | 结论 |\n|---|---|---|\nC1–C5 全部 PASS\n", encoding="utf8")
    code, out = run(rng)
    cases.append(("检查器写区间汇总（不展开）应拦截", code == 1 and "C4" in out, ""))
    rng.joinpath("constraint_check.md").write_text(
        "| 编号 | 违约量 | 结论 |\n|---|---|---|\n| C1 | 0 | PASS |\n| C2 | 0 | PASS |\n| C3 | 0 | PASS |\n"
        "| C4 | 0 | PASS |\n| C5 | 0 | PASS |\n", encoding="utf8")
    rng.joinpath("validation_report.md").write_text(VALIDATION_DOC, encoding="utf8")
    rng.joinpath("final_models.md").write_text(FINAL_MODELS_OK, encoding="utf8")
    code, _ = run(rng)
    cases.append(("检查器逐条补齐 C1..C5 后应通过（含环节 6 产物）", code == 0, ""))
    code, out = run(rng, "--phase", "p3")
    cases.append(("环节 5 出口缺 results.json 应硬拦（不再只 WARN）",
                  code == 1 and "results.json" in out, ""))
    nonorm = build("nonorm", {
        "brief.md": "# 问题简报\n### 问题二\n- 题型标签：优化-多目标\n",
        "model_doc.md": "# 模型设计\n\n" + GOOD_DOC,
        "results.json": FRONT_NO_NORM,
        "constraint_check.md": CHECKS_SUMMARY_ONLY,
        "iteration_log.md": "第 1 轮：假设 ε 步长过大；最小验证：单点复算；结论：命中。\n",
    })
    (nonorm / "results").mkdir()
    (nonorm / "results/pareto_points.csv").write_text("z1,z2\n1,9\n2,6\n", encoding="utf8")
    code, out = run(nonorm)
    cases.append(("前沿缺逐点归一化字段应拦截", code == 1 and "归一化字段" in out, out.strip()[-160:]))
    realfail = build("realfail", {
        "brief.md": "# 问题简报\n### 问题二\n- 题型标签：优化-多目标\n",
        "model_doc.md": "# 模型设计\n\n" + GOOD_DOC,
        "results.json": FRONT,
        "constraint_check.md": CHECKS_REALFAIL,
        "iteration_log.md": "第 1 轮：假设 ε 步长过大；最小验证：单点复算；结论：命中。\n",
    })
    code, out = run(realfail)
    cases.append(("判定列真 FAIL 且无根因分析应拦截", code == 1 and "根因" in out, out.strip()[-160:]))
    summary_only = build("summaryonly", {
        "brief.md": "# 问题简报\n### 问题二\n- 题型标签：优化-多目标\n",
        "model_doc.md": "# 模型设计\n\n" + GOOD_DOC,
        "results.json": FRONT,
        "constraint_check.md": CHECKS_SUMMARY_ONLY,
        "iteration_log.md": "第 1 轮：假设 ε 步长过大；最小验证：单点复算；结论：命中。\n",
    })
    (summary_only / "results").mkdir()
    (summary_only / "results/pareto_points.csv").write_text("z1,z2\n1,9\n2,6\n", encoding="utf8")
    summary_only.joinpath("validation_report.md").write_text(VALIDATION_DOC, encoding="utf8")
    summary_only.joinpath("final_models.md").write_text(FINAL_MODELS_OK, encoding="utf8")
    code, out = run(summary_only)
    cases.append(("报告写「FAIL 0 条」汇总文字不应误判为违约", code == 0, out.strip()[-160:]))
    # 环节 6 出口新门禁：缺检验报告 / 报告缺三要素 / 定稿留占位 ⇒ 一律硬拦
    no_val = build("noval", {
        "brief.md": (good / "brief.md").read_text(encoding="utf8"),
        "model_doc.md": (good / "model_doc.md").read_text(encoding="utf8"),
        "results.json": FRONT,
        "constraint_check.md": CHECKS,
        "iteration_log.md": "第 1 轮：假设 ε 上界过大；最小验证：单期手算；结论：命中。\n",
        "final_models.md": FINAL_MODELS_OK,
    })
    code, out = run(no_val)
    cases.append(("环节 6 缺 validation_report.md 应拦截",
                  code == 1 and "validation_report.md" in out, out.strip()[-160:]))
    no_val.joinpath("validation_report.md").write_text(
        "# 检验\n## 结果很好，模型稳定，收敛正常。\n", encoding="utf8")
    no_val.joinpath("results.json").write_text(
        FRONT.replace('"validation": {"v1_cells": 97, "v2_cases": 22, "v3_asserts": "pass"}',
                      '"note": "环节 6 数字未并入"'), encoding="utf8")
    code, out = run(no_val)
    cases.append(("检验报告缺三要素且 validation 块未并入应拦截",
                  code == 1 and "灵敏度" in out and "validation 块" in out, out.strip()[-160:]))
    no_val.joinpath("validation_report.md").write_text(VALIDATION_DOC, encoding="utf8")
    no_val.joinpath("results.json").write_text(FRONT, encoding="utf8")
    no_val.joinpath("final_models.md").write_text(
        FINAL_MODELS_OK + "\n## 待环节 6 定稿项\n1. 灵敏度补做。\n", encoding="utf8")
    code, out = run(no_val)
    cases.append(("final_models.md 留「待环节 6」占位应拦截",
                  code == 1 and "final_models.md" in out, out.strip()[-160:]))
    no_val.joinpath("final_models.md").write_text(FINAL_MODELS_OK, encoding="utf8")
    code, out = run(no_val)
    cases.append(("环节 6 产物齐备后应放行", code == 0, out.strip()[-160:]))

    graph.joinpath("graph_abstraction.md").write_text(
        "# 图抽象\n## 节点：1–26 对应附件位号 XJ-0001…；虚拟源 0=调度中心\n"
        "## 边：无向 31 条，权重=行走分钟；无向存两条同权反向弧\n"
        "## 特例：无孤立节点、无自环、不可达需折返、无重边\n"
        "## 算法-题型对齐：多次 Dijkstra（非负权 26 节点），封锁判定用 max-flow 最小割\n", encoding="utf8")
    code, _ = run(graph, "--phase", "p1")
    cases.append(("补齐图抽象后 P1 门禁应通过", code == 0, ""))
    code, _ = run(bad, "--phase", "p1")
    cases.append(("p1 模式只查形式化（应仍拦范式）", code == 1, ""))

    # 英文合规项目：含统计对比非优化小问 Q2、heading ### Primary Paradigm + epsilon-constraint (Pareto front)、
    # Round 1 / R1-01、n_infeasible_weeks=0 -> 0 FAIL & 0 WARN
    en_doc = (
        "## Problem 1\n"
        "- **Decision Variables**: x_i >= 0.\n"
        "- **Objective Function**: min Z1 = sum x_i^2.\n"
        "- **Constraints**: C1 sum x_i = 1; C2 x_i >= 1e-4.\n"
        "- **Assumptions**: A1 simplex identifiability.\n"
        "- **Solver & Algorithm**: SLSQP convex optimization, runtime < 2s.\n\n"
        "## Problem 2\n"
        "- **Estimands & Regression**: beta_1, beta_2, random intercept u_p.\n"
        "- **Model Equation & Metric**: REML mixed-effects likelihood & divergence rate.\n"
        "- **Constraints**: C3 baseline reference coding.\n"
        "- **Assumptions**: A2 Gaussian random intercepts.\n"
        "- **Estimation Method**: REML + 500 bootstrap samples, runtime < 3s.\n\n"
        "## Problem 3\n"
        "- **Decision Variables**: alpha in [0.25, 0.75], kappa in {0, 1}.\n"
        "- **Objective Function** (Multi-Objective): Z1 = max Meritocracy, Z2 = max Suspense.\n"
        "- **Normalization**: min-max normalized to dimensionless [0, 1] using single-objective anchors.\n"
        "### Primary Paradigm\n"
        "- epsilon-constraint (generates full Pareto front).\n"
        "- **Selection Rule**: Knee point with maximum perpendicular distance in normalized space.\n"
        "- **Constraints**: C4 alpha in [0.25, 0.75]; C5 FAR >= 0.25.\n"
        "- **Assumptions**: A3 stationarity.\n"
        "- **Solver & Algorithm**: vectorized grid search + epsilon grid, runtime < 5s.\n"
    )
    en_brief = (
        "# Brief\n"
        "### Problem 1\n- **Problem Tag**: Optimization-Single\n"
        "### Problem 2\n- **Problem Tag**: statistical / comparative evaluation\n"
        "### Problem 3\n- **Problem Tag**: Multi-Objective Optimization (MO)\n"
    )
    en_results = json.loads(FRONT)
    en_results["Q1"] = {"n_infeasible_weeks": 0, "ecr": 1.0}
    en_results["Q3"] = en_results.pop("Q2")
    en_ok = build("en_ok", {
        "brief.md": en_brief,
        "model_doc.md": en_doc,
        "results.json": json.dumps(en_results, ensure_ascii=False),
        "constraint_check.md": "| ID | Violation | Verdict |\n|---|---|---|\n" + "".join(
            f"| C{k} | 0 | PASS |\n" for k in range(1, 6)
        ),
        "iteration_log.md": "- **R1-01**: Hypothesis: fallback rank ordering inverted; Minimal Verification: unit test; Confirmed.\n",
        "validation_report.md": (
            "# Validation Report\n"
            "## Sensitivity Analysis\nPerturbed parameters +/-5%, +/-10%, +/-20% in Tornado table.\n"
            "## Stochastic Robustness & Noise Floor\n20 Monte Carlo posterior draws establish noise floor +/-1.5%.\n"
            "## Validity Domain & Failure Conditions\nValid only when voting behavior is stationary.\n"
        ),
        "final_models.md": "# Final Models\nAll equations finalized with numeric coefficients.\n",
    })
    code, out = run(en_ok)
    cases.append(("纯英文合规项目（含统计小问+0不可行+epsilon-Pareto）应 0 FAIL 0 WARN",
                  code == 0 and "0 WARN / 0 FAIL" in out, out.strip()[-160:]))

    en_results_bad = json.loads(json.dumps(en_results))
    en_results_bad["Q1"]["n_infeasible_weeks"] = 2
    en_ok.joinpath("results.json").write_text(json.dumps(en_results_bad), encoding="utf8")
    code, out = run(en_ok)
    cases.append(("n_infeasible_weeks=2 且缺 infeasibility_report.md 应拦截",
                  code == 1 and "infeasibility_report.md" in out, out.strip()[-160:]))

    # 同行同时写 ε-约束与加权和交替使用仍应被拦截为「范式未锁定」
    en_ok.joinpath("results.json").write_text(json.dumps(en_results), encoding="utf8")
    en_ok.joinpath("model_doc.md").write_text(
        en_doc.replace("epsilon-constraint (generates full Pareto front).", "epsilon-constraint mixed with weighted-sum"),
        encoding="utf8",
    )
    code, out = run(en_ok, "--phase", "p1")
    cases.append(("真多范式混用（epsilon-constraint + weighted-sum）应仍拦截",
                  code == 1 and "范式未锁定" in out, out.strip()[-160:]))

    # 自然英文自由表述（不依赖固定加粗标题词）亦应放行 0 FAIL 0 WARN
    en_natural = build("en_natural", {
        "brief.md": "# Brief\n### Problem 1\n- Problem Tag: Multi-Objective Optimization (MO)\n",
        "model_doc.md": (
            "## Problem 1\n"
            "We select portfolio vector \\mathbf{x} and state variable z.\n"
            "Minimize Z1 = cost and Z2 = latency via the epsilon-constraint method.\n"
            "Objectives are scaled by utopia distance and normalized across the Pareto front; knee rule picks the balanced portfolio.\n"
            "Subject to C1 deck bound and C2 rating floor.\n"
            "Under prior empirical hypotheses solved via vectorized search.\n"
        ),
        "results.json": json.dumps({"Q1": en_results["Q3"], "validation": {"v1": 1}}, ensure_ascii=False),
        "constraint_check.md": "| ID | Violation | Verdict |\n|---|---|---|\n| C1 | 0 | PASS |\n| C2 | 0 | PASS |\n",
        "iteration_log.md": "- R1-01: Hypothesis: baseline too coarse; minimal verification: passed.\n",
        "validation_report.md": "# Validation\nSensitivity perturbation +/-20% checked.\nMonte Carlo robustness checked.\nModel Weaknesses and Operating Limits: synthetic priors.\n",
        "final_models.md": "# Final Models\nAll finalized.\n",
    })
    code, out = run(en_natural)
    cases.append(("自然英文无八股标题项目应 0 FAIL 0 WARN",
                  code == 0 and "0 WARN / 0 FAIL" in out, out.strip()[-160:]))

    print(f"self-test fixtures: {root}")
    bad_n = 0
    for name, ok, detail in cases:
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail and not ok else ""))
        bad_n += 0 if ok else 1
    print(f"合计 {len(cases) - bad_n}/{len(cases)} 通过")
    return 1 if bad_n else 0


def main() -> int:
    if "--self-test" in sys.argv:
        return self_test()
    ap = argparse.ArgumentParser(description="先建模后代码 SOP 机械门禁")
    ap.add_argument("--work", default="work/", help="项目 work/ 目录")
    ap.add_argument("--phase", default="all", choices=["p1", "p3", "all"])
    ap.add_argument("--min-front", type=int, default=5, help="Pareto 前沿最少点数")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    work = Path(args.work)
    doc_path = work / "model_doc.md"
    if not doc_path.exists():
        print(f"[FAIL] 缺 {doc_path}：未做数学形式化，禁止写求解代码（SOP §1 P1）")
        return 1

    doc = read(doc_path)
    brief = read(work / "brief.md")
    results = {}
    rj = work / "results.json"
    if rj.exists():
        try:
            results = json.loads(rj.read_text(encoding="utf8"))
        except Exception as e:  # noqa: BLE001
            print(f"[WARN] results.json 解析失败：{e}")
    checker_md = read(work / "constraint_check.md")
    g = Gate()

    secs = split_sections(doc)
    if not secs:
        # 不放过任何一份文档：识别不到小问分节时，按全文整体检查（防止"格式不合"绕过门禁）
        g.warn("model_doc.md", "未按「问题N」分节，改按全文整体检查（建议每小问独立成节，含各自变量/目标/约束/假设）")
        whole = Sec("全文", 9, 0)
        whole.lines = doc.split("\n")
        secs = [whole]
    else:
        g.ok("model_doc.md", f"识别 {len(secs)} 个小问节")

    # 未被小问节覆盖的部分（公共符号/全局假设/求解器约定等）作为全文级证据，
    # 避免"要素写在公共节里"造成误判；但本节应显式引用编号，故降级为 WARN。
    covered = set()
    for s in secs:
        covered.update(range(s.start, s.start + len(s.lines) + 1))
    global_text = "\n".join(l for i, l in enumerate(doc.split("\n")) if i not in covered)

    brief_tags = extract_brief_tags(brief)
    cids_global: set[str] = set()
    mo_questions: list[Sec] = []
    for sec in secs:
        tag = sec.name
        canon = tag.split("（", 1)[0]
        brief_tag = brief_tags.get(canon, "")
        text = sec.text
        cids = declared_cids(text)
        cids_global |= cids
        zids = {f"Z{n}" for n in ZID.findall(text)}
        multi_decl = (
            has(r"多目标|multi[-\s]*objective|pareto\s+trade[-\s]*off", text)
            or has(r"多目标|multi[-\s]*objective|\(MO\)", brief_tag)
            or has(rf"{re.escape(tag)}.*多目标|{re.escape(tag)}.*\(MO\)", brief)
        )
        is_mo = multi_decl or len(zids) >= 2
        non_opt = is_non_opt_subproblem(sec, brief_tag, is_mo)

        # ---- P1 形式化六要素 ----
        def elem(pattern: str, label: str, clause: str) -> None:
            if has(pattern, text):
                return
            if has(pattern, global_text):
                g.warn(tag, f"【{label}】只出现在公共/全局节，本小问节未显式列出（SOP {clause}）")
            else:
                g.fail(tag, f"缺【{label}】清单/表达式，全文亦未找到（SOP {clause}）")

        var_pat = (
            r"决策变量|变量定义|变量说明|待估参数|未知量|decision\s+variable|state\s+variable|\bvariables?\b|\bvector\s+\\mathbf\{|\bportfolio\b|\btrajectory\b|unknowns?|parameters?\s+to\s+estimate|estimand|latent\s+variable"
            + (r"|核心统计量|回归|模型方程|指标|statistic|covariate|predictor|feature" if non_opt else "")
        )
        obj_pat = (
            r"目标函数|优化目标|objective\s+function|objective|loss\s+function|likelihood|\breml\b|\bmin\b|\bmax\b|\bminimi[sz]e\b|\bmaximi[sz]e\b|s\.t\.|subject\s+to"
            + (r"|评估指标|指标体系|准则|metric|criterion|estimator|model\s+equation|specification" if non_opt else "")
        )
        elem(var_pat, "决策变量", "§2.1")
        elem(obj_pat, "目标函数", "§2.2")
        if non_opt:
            if not cids:
                g.ok(tag, "统计/评价/比较类小问无需强制编号约束")
        else:
            if not cids:
                if cids_global:
                    g.warn(tag, "本小问节内约束未编号（C1/C2…），仅在全文章节出现，建议本节显式引用（SOP §2.3）")
                else:
                    g.fail(tag, "约束未编号（需 C1/C2/…，SOP §2.3）；散述约束无法逐条复核")
            elif len(cids) < 2:
                g.warn(tag, f"仅识别到 {sorted(cids)}：约束条数偏少，确认是否省略了边界/逻辑约束")
        elem(r"模型假设|假设|assumption|premise|hypothes[ie]s|simplif|boundary\s+condition|\bprior\b", "假设", "§2.4")
        solver_pat = r"求解算法|求解思路|求解器|算法与工具|solver|algorithm|estimation\s+method|runtime|时间预算|耗时|solved\s+via|vectorized"
        if not has(solver_pat, text):
            if has(solver_pat, global_text):
                g.warn(tag, "【求解思路与规模判断】只写在公共节（SOP §2.6）")
            else:
                g.warn(tag, "缺【求解思路与规模判断】（SOP §2.6）")

        if is_mo:
            mo_questions.append(sec)
            if not has(r"归一化|无量纲|标准化|normali[sz]|standardi[sz]|dimensionless|min[-\s]?max|utopia|hypervolume|pareto\s+front|scaled|non-?dominat|理想点|ideal\s+point|参考值|reference\s+point", text):
                g.fail(tag, "多目标小问缺【量纲归一化】说明（SOP §2.5/§3.4）")
            pline = find_paradigm_line(text)
            if pline is None:
                g.fail(tag, "多目标小问未声明「主范式（锁定）」（SOP §3.2）")
            else:
                hit = match_paradigms(pline)
                if len(hit) == 0:
                    g.fail(tag, f"主范式声明无法识别四类之一：{pline.strip()[:60]}")
                elif len(hit) > 1:
                    g.fail(tag, f"范式未锁定，一行内出现多种：{hit}（SOP §3.2 禁止来回切换）")
                else:
                    g.ok(tag, f"主范式锁定：{hit[0]}")
                    if hit[0] == "加权和" and not has(
                        r"权重来源|权重依据|权重标定|weight\s+source|weight\s+justification|calibrat|AHP|熵权|entropy\s+weight|影子价格|shadow\s+price|标定",
                        text,
                    ):
                        g.fail(tag, "加权和范式未给出【权重来源】（SOP §3.1）")
            if not has(r"折中|膝点|knee|TOPSIS|选取规则|择优规则|满意度|compromise|selection\s+rule|decision\s+rule", text):
                g.warn(tag, "未写折中点选取规则（SOP §3.5：前沿 + 选取规则）")
        # ---- 图抽象门禁 ----
        if detect_graph(text, brief_tag):
            ga = read(work / "graph_abstraction.md")
            if not ga.strip():
                g.fail(tag, "图论/网络类小问缺 work/graph_abstraction.md（SOP §1 P2 暂停门禁）")
            else:
                for need, pat, why in [
                    ("节点", r"节点|顶点|node", "节点集合与索引含义"),
                    ("边", r"边|弧|edge|arc|权重|方向", "边方向/权重/双向说明"),
                    ("特例", r"孤立|自环|不连通|不可达|重边|虚拟", "孤立点/自环/不可达处理"),
                    ("算法对齐", GRAPH_ALGOS, "算法-题型对齐"),
                ]:
                    if not has(pat, ga):
                        g.fail(f"{tag}/图抽象", f"缺【{need}】：{why}（SOP §4）")

    # ---- P3/P4：结果契约 ----
    if args.phase in ("p3", "all"):
        def check_coverage() -> None:
            """检查器报告逐条覆盖声明过的约束编号（区间简写在检查器侧**不**展开）。"""
            missing = sorted(cids_global - {f"C{n}" for n in CID.findall(checker_md)},
                             key=lambda s: int(s[1:]))
            if missing:
                g.fail("constraint_check.md", f"未覆盖约束编号：{missing}"
                                             f"（需逐条 PASS/FAIL；写「C1–C5 全部 PASS」不算证据）")
            else:
                g.ok("constraint_check.md", f"覆盖全部 {len(cids_global)} 个约束编号")
            # 只数「判定列真的是 FAIL」的行——报告里写「FAIL 0 条」这类汇总文字不得触发误判
            n_real = len(re.findall(r"\|\s*(?:\*\*)?FAIL(?:\*\*)?\s*\|", checker_md))
            if n_real and not has(r"根因|原因|分析|infeasib|不可行|root\s*cause|diagnos|explanation|reason", checker_md):
                g.fail("constraint_check.md", f"存在 {n_real} 条 FAIL 判定但无根因分析（SOP §5 优先级 1）")

        if rj.exists():
            if not checker_md.strip():
                g.fail("constraint_check.md", "缺独立约束检查器报告（SOP §6.1：能跑 ≠ 对）")
            else:
                check_coverage()
            for sec in mo_questions:
                canon = sec.name.split("（", 1)[0]
                qnum = norm_num(canon.replace("问题", ""))
                key = f"Q{qnum}" if qnum is not None else None
                blob = json.dumps(results, ensure_ascii=False)
                fronts: list[tuple[str, list]] = []
                sub = results
                for k in (key or "", canon, sec.name, "pareto"):
                    if isinstance(results, dict) and k and k in results:
                        sub = results[k]
                        break
                find_fronts(sub, fronts)
                sizes = [len(v) for _, v in fronts]
                declared = front_size_declared(sub)
                art = front_artifact(work)
                n_pts = max([max(sizes, default=0), declared])
                if n_pts < args.min_front:
                    g.fail(sec.name, f"多目标小问未交出 Pareto 解集（前沿点数 {n_pts} < {args.min_front}）"
                                     f"——禁止只报单个「最优数」（SOP §3.5）")
                elif not fronts and not art:
                    g.fail(sec.name, f"前沿点数 {n_pts} 有声明，但既无内联解集也无点集文件（SOP §3.5 需可复核的前沿）")
                else:
                    src = fronts[0][0] if fronts else (art[0] if art else "declared")
                    g.ok(sec.name, f"Pareto 解集 {n_pts} 点（来源 {src}）")
                # 逐点归一化：多目标必须证明做过无量纲化（SOP §3.4），只有原始目标值不算
                if fronts:
                    pts = [p for _, lst in fronts for p in lst if isinstance(p, dict)]
                    if pts and not any(
                            re.search(r"_hat$|_norm$|normalized|归一", str(k)) for p in pts for k in p):
                        g.fail(sec.name, "Pareto 点只给了原始目标值，缺逐点归一化字段"
                                         "（z1_hat/z2_hat 等，SOP §3.4 无量纲化不可省略）")
                elif declared and not fronts:
                    g.warn(sec.name, "前沿只存文件（未内联点集）⇒ 无法机械核对逐点归一化字段")
                blob_l = blob.lower()
                if not re.search(r"hypervolume|超体积|非支配|nondom|spacing|间距", blob_l):
                    g.warn(sec.name, "缺前沿质量自检（超体积/非支配性/间距，SOP §3.7）")
            if has_actual_infeasibility(results):
                if not (work / "infeasibility_report.md").exists():
                    g.fail("infeasibility", "结果含不可行信息但缺 work/infeasibility_report.md（SOP §3.6：报告冲突分析，不调参逼解）")
        else:
            # results.json 未产出：环节 5 出口（--phase p3）视为该环节未完成，硬拦；
            # 整体预检（--phase all）只提示，避免环节 4 就报「缺结果」。
            if args.phase == "p3":
                g.fail("results.json", "未产出 results.json：环节 5 未完成（SOP §1 P4 产物缺失视为未完成）")
            else:
                g.warn("results.json", "尚未产出 results.json（环节 5 结束前必须补齐）")
            if checker_md.strip():
                check_coverage()  # 检查器先写好、结果后补：同样逐条校验，区间汇总蒙不过

        # ---- 环节 6（模型检验与灵敏度）产物：只有整体出口 --phase all 才强制 ----
        if args.phase == "all":
            vr = read(work / "validation_report.md")
            if not vr.strip():
                g.fail("validation_report.md",
                       "环节 6 未产出检验报告：灵敏度/稳健性/备选对比缺失（SOP §7、math-model-validation 硬门禁）")
            else:
                if not has(r"灵敏度|弹性|Tornado|sensitivit|elasticit|perturbation|±\s*\d+\s*%", vr):
                    g.fail("validation_report.md", "检验报告缺参数灵敏度（±5/10/20% 或弹性/Tornado）证据")
                if not has(r"稳健|鲁棒|噪声地板|robust|noise\s+floor|monte\s+carlo|bootstrap|cross[-\s]*validation|\bseed|posterior\s+draw", vr):
                    g.fail("validation_report.md", "检验报告缺稳健性证据（重复模拟/换种子/样本量/窗口）")
                if not has(r"适用边界|失效条件|有效域|模型弱点|模型局限|validity\s+(?:domain|boundar)|failure\s+(?:condition|mode)|limitation|scope\s+of\s+validity|applicable\s+range|model\s+weakness|weaknesses|operating\s+limit", vr):
                    g.fail("validation_report.md",
                           "检验报告缺「适用边界与失效条件」——只摆灵敏度数字、不给结论与失效边界不合格（SOP §6.6）")
                if rj.exists() and results.get("validation") is None:
                    g.fail("results.json",
                           "缺 validation 块：环节 6 的检验数字未并入唯一数字出处 ⇒ 写作环节无从引用（SOP §6）")
                else:
                    g.ok("validation_report.md", "环节 6 检验报告 + results.json validation 块就位")
            fm = read(work / "final_models.md")
            if fm.strip() and re.search(r"待环节\s*6|待补充|\bTODO\b|\bTBD\b|占位|placeholder", fm, re.I):
                g.fail("final_models.md",
                       "仍含「待环节 6 定稿/待补充」占位：公式权威来源未定稿，不得进入写作环节")
            n_fail6 = len(re.findall(r"\|\s*(?:\*\*)?FAIL(?:\*\*)?\s*\|", checker_md))
            if n_fail6:
                g.fail("constraint_check.md",
                       f"环节 6 出口时仍有 {n_fail6} 条 FAIL 判定：检验不得覆盖未修复的违约（SOP §5）")

        ilog = read(work / "iteration_log.md")
        if ilog.strip():
            rounds = extract_rounds(ilog)
            if rounds and max(rounds) > 4:
                g.fail("iteration_log.md", f"第 {max(rounds)} 轮 > 4 轮上限：须停止修改并输出模型缺陷分析（SOP §5）")
            else:
                g.ok("iteration_log.md", f"最大轮次 {max(rounds) if rounds else 0} ≤ 4")
            if not has(r"假设|因为|根因|hypothes|root\s*cause|because|diagnos|minimal\s+verif", ilog):
                g.warn("iteration_log.md", "缺少「假设→最小验证→结论」记录（SOP §5）")
        else:
            g.warn("iteration_log.md", "缺迭代记账文件（有报错/异常输出时必须记账）")

    # ---- 输出 ----
    if not args.quiet:
        for status, target, message in g.items:
            if status == "PASS":
                continue
            print(f"[{status}] {target}: {message}")
        passed = [x for x in g.items if x[0] == "PASS"]
        print(f"\n汇总：{len(passed)} PASS / {g.n_warn} WARN / {g.n_fail} FAIL")
    if g.n_fail:
        print("门禁不过：禁止进入下一环节（见 _shared/references/model-first-sop.md）")
        return 1
    print("门禁通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
