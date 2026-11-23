#!/usr/bin/env python3
"""Humanize invariant checker for math-modeling papers.

Guards a humanization/edit pass against silently corrupting meaning. Compares a
FROZEN original against the revised text and reports:

  * numbers & units that appeared / disappeared / changed;
  * citation keys added or dropped;
  * inline/display math changed;
  * negation, causal-direction and modality/uncertainty marker counts that moved;
  * protected terms (model names, symbols) renamed;
  * LaTeX-unsafe constructs introduced (double-escaped %, raw &, # in captions);
  * numbers that cannot be traced back to work/results.json.

Design credit: the invariant SET (numbers/units, citations, formulas, negation,
causal direction, modality, protected terms) follows PaperSpine's
`author_voice_check.py` (project PaperSpine, author WUBING2023, MIT,
https://github.com/WUBING2023/PaperSpine). This implementation is self-contained:
it takes two text files instead of PaperSpine's contract JSON, and adds a
results.json traceability check and LaTeX-safety gate that this project needs.

Severity policy (deliberate, mirrors PaperSpine's stance):
  * A marker-count change is a SIGNAL TO INSPECT, never proof of an error.
    Equivalent rewording legitimately moves these counts, so they are WARN.
  * Numbers/units/citations/formulas that vanish or change are FAIL — humanizing
    must never silently drop a result.
  * `--against results.json` turns untraceable numbers into FAIL, because every
    number in this project must have a single traceable source.

Usage:
    python3 invariance_check.py ORIGINAL REVISED [--lang en|zh]
                               [--against work/results.json] [--json PATH]
    python3 invariance_check.py --self-test
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path

# ----------------------------------------------------------------------------- markers
NEGATION_EN = (
    "not", "no", "never", "none", "neither", "nor", "without", "cannot", "can't",
    "does not", "do not", "did not", "is not", "are not", "was not", "were not",
    "unable", "fail", "fails", "failed", "excludes", "absence", "lack",
)
NEGATION_ZH = (
    "不", "未", "无", "没有", "非", "无法", "不能", "并非", "缺乏", "排除", "否",
)
CAUSAL_EN = (
    "because", "since", "therefore", "thus", "hence", "consequently", "leads to",
    "results in", "causes", "due to", "owing to", "attributable", "driven by",
    "as a result", "thereby",
)
CAUSAL_ZH = (
    "因为", "由于", "因此", "所以", "导致", "引起", "使得", "从而", "归因于", "造成",
)
MODAL_EN = (
    "may", "might", "could", "would", "should", "possibly", "probably", "likely",
    "unlikely", "suggest", "suggests", "suggested", "indicate", "indicates",
    "appear", "appears", "seem", "seems", "approximately", "roughly", "about",
    "consistent with", "associated with", "correlat", "tends to", "presumably",
    "we believe", "in our view",
)
MODAL_ZH = (
    "可能", "或许", "可以", "提示", "表明", "似乎", "大约", "约", "不确定",
    "潜在", "倾向", "证明", "证实", "显示", "相关", "倾向于",
)

NUMBER_UNIT_RE = re.compile(
    r"(?<![\w.])[+\-−]?\d+(?:[.,]\d+)?(?:[eE][+\-]?\d+)?"
    r"(?:\s*(?:%|‰|pp|bp|bps|fold|x|×|mg|g|kg|μg|ug|ng|pg|mL|ml|L|l|"
    r"μL|uL|nm|μm|um|mm|cm|m|km|s|ms|min|h|Hz|kHz|MHz|°C|K|Pa|kPa|"
    r"mol|mmol|μmol|umol|nM|μM|uM|mM|M|USD|CNY|yuan|day|days|week|weeks|"
    r"month|months|year|years|pts|points|km/h|m/s))?",
    re.IGNORECASE,
)
CITE_RE = re.compile(r"\\cite[a-zA-Z*]*\s*(?:\[[^\]]*\]\s*)*\{([^{}]+)\}")
PANDOC_CITE_RE = re.compile(r"\[@([\w:./\-]+)")
INLINE_MATH_RE = re.compile(r"(?<!\\)\$(?!\$)(.+?)(?<!\\)\$", re.DOTALL)
DISPLAY_MATH_RE = re.compile(r"\\\[(.+?)\\\]", re.DOTALL)
ENV_MATH_RE = re.compile(
    r"\\begin\{(equation\*?|align\*?|gather\*?|multline\*?)\}(.+?)"
    r"\\end\{\1\}", re.DOTALL,
)

# LaTeX-unsafe constructs that silently corrupt a compiled paper.
LATEX_HAZARDS: tuple[tuple[str, str, str], ...] = (
    (r"(?<!\\)%", "FAIL", "unescaped % starts a LaTeX comment and swallows the rest of the line"),
    (r"(?<!\\)&(?![^&\n]*\\)", "WARN", "raw & outside a tabular row can break alignment"),
    (r"(?<!\\)#(?!\d)", "WARN", "raw # in text/caption (use \\#)"),
    (r"(?<!\\)\$(?!\$)[^$\n]*$", "FAIL", "unbalanced inline math $ on a line"),
    (r"\\textbf\{\s*\}", "WARN", "empty \\textbf{}"),
    (r"(?<!\\)_(?![{A-Za-z0-9])", "WARN", "bare underscore outside math (use \\_)"),
)

DIAGNOSTIC_PATTERNS: dict[str, tuple[str, ...]] = {
    "empty_framing": (
        "it is worth noting that", "it should be noted that", "it is important to note that",
        "it is worth mentioning", "needless to say",
        "值得注意的是", "需要指出的是", "不容忽视的是",
    ),
    "generic_importance": (
        "plays an important role", "plays a crucial role", "is of great significance",
        "important implications", "far-reaching implications", "has important implications",
        "具有重要意义", "具有重要作用", "具有广阔前景", "产生深远影响",
    ),
    "mechanical_enumeration": (
        "firstly", "secondly", "thirdly", "lastly", "in conclusion", "to sum up",
        "in summary", "all in all",
        "首先", "其次", "再次", "综上所述", "总而言之",
    ),
    "writing_process_leak": (
        "this section discusses", "the following paragraph", "we have reorganized",
        "this manuscript has been revised", "as mentioned earlier", "the rest of this paper",
        "本节将讨论", "下文将", "本文重新组织",
    ),
    "promotional_precision_gap": (
        "groundbreaking", "unprecedented", "comprehensive solution", "highly robust",
        "cutting-edge", "state-of-the-art solution", "revolutionary",
        "突破性的", "前所未有", "全面解决", "高度稳健",
    ),
    "stakes_inflation": (
        "despite these challenges", "in today's world", "in an era of",
        "as the world becomes", "now more than ever",
    ),
    "superficial_participle": (
        "highlighting its importance", "underscoring the need", "reflecting the",
        "emphasizing the importance", "showcasing the",
    ),
}

# Terms that MUST survive a humanization pass because they carry identity.
DEFAULT_PROTECTED = (
    "NSGA-II", "NSGA-2", "CP-SAT", "pymoo", "Pyomo", "Gurobi", "COPT", "Gurobi",
    "XGBoost", "LightGBM", "SHAP", "ARIMA", "LSTM", "MCMC", "Bootstrap",
    "Pareto", "Monte Carlo", "AHP", "TOPSIS", "Entropy Weight", "SEIR", "SIR",
    "CUMCM", "MCM", "ICM", "APMCM",
)


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def _diff(a: Counter, b: Counter) -> dict[str, dict[str, int]]:
    return {k: {"original": a[k], "revised": b[k]}
            for k in sorted(set(a) | set(b)) if a[k] != b[k]}


def numbers_units(text: str) -> Counter:
    return Counter(_norm(m.group(0)).lower().replace("−", "-")
                   for m in NUMBER_UNIT_RE.finditer(text))


def citations(text: str) -> Counter:
    keys: list[str] = []
    for m in CITE_RE.finditer(text):
        keys.extend(k.strip() for k in m.group(1).split(",") if k.strip())
    keys.extend(m.group(1).strip() for m in PANDOC_CITE_RE.finditer(text))
    return Counter(keys)


def formulas(text: str) -> Counter:
    out = [_norm(m.group(1)) for m in INLINE_MATH_RE.finditer(text)]
    out += [_norm(m.group(1)) for m in DISPLAY_MATH_RE.finditer(text)]
    out += [_norm(m.group(2)) for m in ENV_MATH_RE.finditer(text)]
    return Counter(f for f in out if f)


def marker_counter(text: str, language: str, kind: str) -> Counter:
    pools = {
        ("en", "negation"): NEGATION_EN, ("zh", "negation"): NEGATION_ZH,
        ("en", "causal"): CAUSAL_EN, ("zh", "causal"): CAUSAL_ZH,
        ("en", "modality"): MODAL_EN, ("zh", "modality"): MODAL_ZH,
    }
    pool = pools[(language, kind)]
    low = text.casefold()
    counts = Counter()
    for marker in pool:
        needle = marker.casefold()
        n = low.count(needle) if language == "zh" else len(re.findall(rf"\b{re.escape(needle)}\w*", low))
        if n:
            counts[marker] = n
    return counts


def protected_counter(text: str, terms) -> Counter:
    low = text.casefold()
    return Counter({t: low.count(t.casefold()) for t in terms if t.strip()})


def _float_keys(counter: Counter) -> set[float]:
    out = set()
    for key in counter:
        m = re.match(r"[+\-−]?(\d+(?:[.,]\d+)?(?:[eE][+\-]?\d+)?)", key)
        if m:
            try:
                out.add(float(m.group(1).replace(",", "")))
            except ValueError:
                pass
    return out


def results_numbers(path: Path) -> set[float]:
    """Collect every number appearing anywhere in results.json."""
    found: set[float] = set()

    def walk(node):
        if isinstance(node, dict):
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)
        elif isinstance(node, (int, float)) and not isinstance(node, bool):
            found.add(float(node))
        elif isinstance(node, str):
            for m in re.finditer(r"[+\-−]?\d+(?:\.\d+)?(?:[eE][+\-]?\d+)?", node):
                try:
                    found.add(float(m.group(0).replace("−", "-")))
                except ValueError:
                    pass

    walk(json.loads(path.read_text(encoding="utf-8-sig")))
    return found


@dataclass
class Finding:
    code: str
    severity: str
    message: str
    details: dict = field(default_factory=dict)


@dataclass
class Result:
    original: str = ""
    revised: str = ""
    language: str = ""
    hard: list = field(default_factory=list)
    advisory: list = field(default_factory=list)
    invariants: dict = field(default_factory=dict)
    diagnostics: dict = field(default_factory=dict)
    traceability: dict = field(default_factory=dict)

    @property
    def failed(self) -> bool:
        return any(f.severity == "FAIL" for f in self.hard)


def check(original_text: str, revised_text: str, language: str = "en",
          against: Path | None = None, protected=DEFAULT_PROTECTED) -> Result:
    r = Result(original="", revised="", language=language)
    if language not in {"en", "zh"}:
        r.hard.append(Finding("unsupported_language", "FAIL",
                              f"language must be en or zh, got {language!r}"))
        return r

    for label, counter_fn in (("numbers_units", numbers_units),
                              ("citations", citations),
                              ("formulas", formulas)):
        a, b = counter_fn(original_text), counter_fn(revised_text)
        changes = _diff(a, b)
        r.invariants[label] = {"changes": changes,
                               "original_total": sum(a.values()),
                               "revised_total": sum(b.values())}
        dropped = {k: v for k, v in changes.items() if v["revised"] < v["original"]}
        if dropped:
            r.hard.append(Finding(f"{label}_changed", "FAIL",
                                  f"{len(dropped)} {label} entr(ies) disappeared or decreased",
                                  {"dropped": dict(list(dropped.items())[:12])}))

    for kind in ("negation", "causal", "modality"):
        a, b = marker_counter(original_text, language, kind), marker_counter(revised_text, language, kind)
        changes = _diff(a, b)
        r.invariants[kind] = {"changes": changes,
                              "original_total": sum(a.values()),
                              "revised_total": sum(b.values())}
        if changes:
            r.advisory.append(Finding(f"{kind}_counts_moved", "WARN",
                                      f"{kind} marker counts changed; inspect the affected "
                                      f"sentences for meaning drift (equivalent rewording "
                                      f"legitimately moves these)",
                                      {"changes": dict(list(changes.items())[:12])}))

    a, b = protected_counter(original_text, protected), protected_counter(revised_text, protected)
    changes = _diff(a, b)
    r.invariants["protected_terms"] = {"changes": changes}
    if changes:
        r.hard.append(Finding("protected_term_changed", "FAIL",
                              "a protected term (method/model name) was added, removed or renamed",
                              {"changes": changes}))

    # LaTeX safety
    hazards = []
    for pattern, severity, why in LATEX_HAZARDS:
        n_new = len(re.findall(pattern, revised_text, re.MULTILINE))
        n_old = len(re.findall(pattern, original_text, re.MULTILINE))
        if n_new > n_old:
            hazards.append({"pattern": pattern, "why": why,
                            "original": n_old, "revised": n_new})
            (r.hard if severity == "FAIL" else r.advisory).append(
                Finding("latex_hazard", severity,
                        f"LaTeX hazard introduced ({n_old}->{n_new}): {why}",
                        {"pattern": pattern}))
    r.invariants["latex_hazards_introduced"] = hazards

    # Advisory pattern scan (never forces a rewrite by itself)
    low = revised_text.casefold()
    diag = {}
    for group, phrases in DIAGNOSTIC_PATTERNS.items():
        hits = [p for p in phrases if p.casefold() in low]
        if hits:
            diag[group] = hits
    r.diagnostics = diag
    if diag:
        r.advisory.append(Finding("ai_patterns_present", "WARN",
                                  "AI-tell patterns still present (advisory; remove only if "
                                  "the claim survives without them)",
                                  diag))

    # Traceability against results.json
    if against is not None:
        if not against.is_file():
            r.hard.append(Finding("results_missing", "FAIL", f"results.json not found: {against}"))
        else:
            allowed = results_numbers(against)
            ctr = numbers_units(revised_text)
            untraceable = []
            for key in ctr:
                vals = _float_keys(Counter({key: 1}))
                if not vals:
                    continue
                v = next(iter(vals))
                # integer-ish small numbers (counts, n, indices) and 0/1 are exempt
                if v in (0.0, 1.0) or float(v).is_integer() and abs(v) <= 20:
                    continue
                if not any(abs(v - a) <= max(1e-9, abs(a) * 1e-6) for a in allowed):
                    untraceable.append(key)
            r.traceability = {"checked_against": str(against),
                              "results_number_count": len(allowed),
                              "untraceable": untraceable[:40],
                              "untraceable_count": len(untraceable)}
            if untraceable:
                r.hard.append(Finding("untraceable_numbers", "FAIL",
                                      f"{len(untraceable)} number(s) in the revised text are not "
                                      f"traceable to results.json",
                                      {"examples": untraceable[:12]}))
    return r


def render(r: Result) -> str:
    lines = ["Humanize invariance check", f"language: {r.language}"]
    lines.append(f"numbers/units: {r.invariants.get('numbers_units', {}).get('original_total', 0)}"
                 f" -> {r.invariants.get('numbers_units', {}).get('revised_total', 0)}")
    lines.append(f"citations:     {r.invariants.get('citations', {}).get('original_total', 0)}"
                 f" -> {r.invariants.get('citations', {}).get('revised_total', 0)}")
    lines.append(f"formulas:      {r.invariants.get('formulas', {}).get('original_total', 0)}"
                 f" -> {r.invariants.get('formulas', {}).get('revised_total', 0)}")
    for kind in ("negation", "causal", "modality"):
        d = r.invariants.get(kind, {})
        lines.append(f"{kind:<14} {d.get('original_total', 0)} -> {d.get('revised_total', 0)}")
    if r.traceability:
        lines.append(f"traceable to results.json: "
                     f"{r.traceability['untraceable_count']} untraceable "
                     f"(of {r.traceability.get('results_number_count', 0)} known numbers)")
    for f in r.hard:
        lines.append(f"[{f.severity}] {f.code}: {f.message}")
        if f.details:
            lines.append(f"        {json.dumps(f.details, ensure_ascii=False)[:400]}")
    for f in r.advisory:
        lines.append(f"[{f.severity}] {f.code}: {f.message}")
        if f.details:
            lines.append(f"        {json.dumps(f.details, ensure_ascii=False)[:400]}")
    lines.append("verdict: " + ("FAIL" if r.failed else "PASS"))
    lines.append("note: marker-count movement is a signal to inspect, not proof of error")
    return "\n".join(lines)


def _self_test() -> int:
    ok = True
    # NOTE: these fixtures use properly escaped \\% — an unescaped % is itself a
    # LaTeX hazard this checker flags, so a fixture written with a raw % would
    # (correctly) trip that gate and confuse the other assertions.
    orig = (r"We collected 120 samples and measured 45.2 \% yield. The model was not "
            r"significant (p = 0.31). We used NSGA-II \cite{deb2002} with $x^2 + y$ "
            r"because cost fell by 12.5 \%.")

    identical = check(orig, orig, "en")
    if identical.failed:
        print(f"FAIL: identical text should pass: {[f.code for f in identical.hard]}")
        ok = False
    if any(f.code.endswith("counts_moved") for f in identical.advisory):
        print("FAIL: identical text moved marker counts"); ok = False

    dropped = check(orig, orig.replace(r"45.2 \%", r"45 \%"), "en")
    if not dropped.failed:
        print("FAIL: changed number not caught"); ok = False

    vanished = check(orig, orig.replace(r" \cite{deb2002}", ""), "en")
    if not vanished.failed:
        print("FAIL: dropped citation not caught"); ok = False

    negated = check(orig, orig.replace("was not", "was"), "en")
    if not any(f.code == "negation_counts_moved" for f in negated.advisory):
        print("FAIL: negation flip not signalled"); ok = False

    renamed = check(orig, orig.replace("NSGA-II", "the genetic algorithm"), "en")
    if not renamed.failed:
        print("FAIL: protected term rename not caught"); ok = False

    hazard = check(r"a 50\% drop", "a 50% drop", "en")
    if not hazard.failed:
        print("FAIL: unescaped %% not caught"); ok = False

    zh = "我们收集了 120 个样本，模型并不显著，因为成本下降了 12.5 %。"
    zh_ok = check(zh, zh, "zh")
    if zh_ok.failed:
        print(f"FAIL: zh identical should pass: {[f.code for f in zh_ok.hard]}")
        ok = False
    zh_bad = check(zh, zh.replace("并不显著", "显著"), "zh")
    if not any(f.code == "negation_counts_moved" for f in zh_bad.advisory):
        print("FAIL: zh negation flip not signalled"); ok = False

    # traceability
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        rp = Path(td) / "results.json"
        rp.write_text(json.dumps({"yield_pct": 45.2, "n": 120}), encoding="utf-8")
        good = check(r"text", r"We collected 120 samples and measured 45.2 \% yield.",
                     "en", against=rp)
        if good.failed:
            print(f"FAIL: traceable numbers flagged: {[f.code for f in good.hard]}")
            ok = False
        bad = check(r"text", r"We collected 120 samples and measured 99.9 \% yield.",
                    "en", against=rp)
        if not bad.failed:
            print("FAIL: untraceable 99.9 not caught"); ok = False

    print("invariance_check self-test: " + ("PASS" if ok else "FAIL")
          + " (8 cases: identical/zh-identical/number-changed/citation-dropped/"
            "negation-flip/protected-term/latex-hazard/traceability)")
    return 0 if ok else 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("original", nargs="?", type=Path)
    ap.add_argument("revised", nargs="?", type=Path)
    ap.add_argument("--lang", choices=("en", "zh"), default="en")
    ap.add_argument("--against", type=Path,
                    help="work/results.json for number traceability")
    ap.add_argument("--json", type=Path)
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args(argv)

    if args.self_test:
        return _self_test()
    if not args.original or not args.revised:
        ap.error("ORIGINAL and REVISED are required unless --self-test is used")
    for p in (args.original, args.revised):
        if not p.is_file():
            print(f"error: not a file: {p}", file=sys.stderr)
            return 2
    r = check(args.original.read_text(encoding="utf-8-sig", errors="replace"),
              args.revised.read_text(encoding="utf-8-sig", errors="replace"),
              args.lang, against=args.against)
    print(render(r))
    if args.json:
        args.json.write_text(json.dumps(asdict(r), indent=2, ensure_ascii=False), encoding="utf-8")
    return 1 if r.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
