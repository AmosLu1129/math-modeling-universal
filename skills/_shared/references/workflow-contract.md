# Workflow Contract

This document is the single source for orchestration semantics. The workflow skill
routes work; stage skills own domain procedures and detailed checks.

## 1. Project manifest

Create `work/run_manifest.yaml` at project start. It is the authoritative record
for project decisions, stage status, user approvals, and invalidated artifacts.
Keep `work/run_choices.md` for backward compatibility, but do not use it as the
source of truth when the manifest exists.

Minimum fields:

```yaml
schema: 1
project:
  competition: null
  language: zh
  time_budget_hours: null
  mode: competition        # competition | o_award | high_assurance | testbed
decisions:
  template: {value: null, status: pending, source: user}
  engine: {value: latex, status: defaulted, source: workflow}
  figure_style: {value: competition, status: defaulted, source: workflow}
  mechanism_route: {value: svg, status: defaulted, source: workflow}
stages: {}
artifacts: {}
approvals: []
human_requests: []
```

Run mode summary:
- `competition`: compact high-rigor closed loop (default `figure_style: competition`).
- **`o_award`**: full depth, Morandi visual polish (`figure_style: morandi_journal` defaulted), real-world empirical anchor (when data-less), 10–14 figures, 21–24 main pages (MCM/ICM), strict `CODE-LEAK` and `DEPTH-CHECK` QA gates.
- `testbed`: repository regression & archival run (`ITERATION.md` / `TESTBED.md`).

Each stage entry records `status`, `started_at`, `finished_at`, `inputs`,
`outputs`, `gate`, and `return_to` when applicable. Each artifact entry records
`kind` (`source`, `derived`, or `audit`), `producer`, `depends_on`, and
`status` (`current` or `stale`).

## 2. Stage and gate states

阶段/门禁状态与决策状态是两套不同枚举：本节的全大写状态只用于
`stages.*.status`、门禁结果和产物审计；`decisions.*.status` 使用
`pending / defaulted / confirmed / waived`，并在 manifest 中记录来源。

Use only these states:

| State | Meaning | Next action |
|---|---|---|
| `PENDING` | Not started because prerequisites are absent | Resolve prerequisites |
| `READY` | Prerequisites and capability checks pass | Run the stage |
| `BLOCKED` | A blocking decision, capability, or dependency is unresolved | Ask, resolve, or explicitly waive |
| `WAITING_HUMAN` | Paused on a standardized `work/human_requests/req_XX.md` ticket | Wait for user artifact/choice or invoke ticket Fallback |
| `RUNNING` | Work is in progress | Continue and record evidence |
| `PASS` | Output contract and gate pass | Enable dependents |
| `FAIL` | Evidence or output contract failed | Follow `return_to` |
| `N/A` | Stage is not applicable to this problem | Record the reason; do not fake output |
| `WAIVED` | User explicitly accepts a documented exception | Record scope, reason, and risk |

Every gate has exactly four fields: `applies_when`, `evidence`, `check`, and
`failure_route`. A prose rule without those fields is guidance, not a gate.

## 3. User decision classes

Classify a decision before asking the user:

- **BLOCKING**: changes problem meaning or the claimed result. Examples:
  objective interpretation, core assumptions, information structure, model
  paradigm, graph abstraction, competition rule ambiguity, and final acceptance.
  Pause until the user confirms or explicitly waives it.
- **DEFAULTABLE**: affects presentation or a reversible implementation choice.
  Announce the default, record it as `defaulted`, and continue. The user may
  override it before the dependent stage starts. Examples: ordinary template or
  engine choice when the competition is known, figure style, and mechanism
  drawing route.
- **INTERNAL**: does not change the claim and is reversible. Decide internally
  and record only when it affects reproducibility. Examples: command spelling,
  renderer fallback, batching, and temporary diagnostics.

Do not describe a decision as both “must confirm” and “default automatically”.
If a default would violate a competition rule or change the scientific claim,
upgrade it to `BLOCKING`.

## 4. Dependency and invalidation rules

The canonical dependency graph is:

```text
input -> problem_spec -> {clean_data, evidence} -> model_spec -> solved_results
       -> validated_results -> {figures, tables, fact_sheet} -> draft_paper
       -> humanized_paper -> reviewed_package
```

Data cleaning and literature work may run in parallel after `problem_spec`.
Figure preparation and writing preparation may overlap only after validated
results and the relevant decisions are current.

When a source artifact changes, mark all downstream derived and audit artifacts
stale until regenerated. At minimum:

| Changed artifact | Invalidate |
|---|---|
| `input/` or `brief.md` | data, literature, model, results, validation, figures, paper |
| `data_clean/` or dictionary | model, results, validation, figures, paper |
| `model_doc.md` or graph abstraction | code, results, validation, figures, paper |
| `results.json` or final model | validation, figures, fact sheet, paper, package |
| figures/tables | paper, package |
| paper source | paper PDF, humanized copy, review report, package |

Do not delete stale files automatically. Mark them stale in the manifest and
regenerate or explicitly waive the affected outputs.

## 5. Capability checks

Environment checks describe capabilities, not a universal stop sign:

- `analysis`: text extraction, data inspection, and model documentation;
- `compute`: required Python packages and solvers;
- `render`: PDF, SVG, and font rendering;
- `visual_qa`: image input or the configured vision fallback;
- `publish`: compiler, code appendix, and archive tooling.

Block only the first stage that needs a missing capability. Continue independent
work and record the risk in the manifest. Installation and platform-specific
commands belong to the environment or figure references, not this contract.

## 6. Evidence levels for literature

Use the least blocking level that answers the task:

1. **Discovery**: search and method mapping; no citation claim yet.
2. **Citation-ready**: verified metadata/DOI and a stable link.
3. **Full-text synthesis**: PDF or full text available and actually read.

Full text is required only when the requested claim or model choice depends on
details unavailable from the citation record. Otherwise, missing PDFs are a
documented limitation, not an automatic workflow stop.

## 7. Rule promotion and maintenance

An incident first goes into `ITERATION.md` as a candidate lesson. Promote it to
a global hard rule only when it is reproducible across at least two problem
types, prevents a material failure, or can be checked automatically. Otherwise
keep it in the owning stage reference. Retire or downgrade rules that become
obsolete. After a promoted rule changes, run the affected regression checks from
`TESTBED.md` before release.

## 8. Human-in-the-Loop Escalation Protocol (v4.2)

High-leverage pause/handoff is reserved ONLY for work the local Python/LaTeX sandbox genuinely cannot replace:
1. **Valid triggers**:
   - `visual_asset`: manual Nano Banana generation of 1–2 complex hero 3D visual components (with copy-paste Morandi pure-white-bg zero-text prompt + target save path `work/figures/assets/comp_XX.png`);
   - `external_sim`: heavy multi-physics FEM/CFD (ANSYS/COMSOL), proprietary MATLAB/Simulink blocks, or massive GPU sweeps exceeding practical local runtime;
   - `manual_data`: physical measurement / field sampling / gated external lookup requested by user;
   - `decision`: core P1/P2 paradigm or assumption trade-offs.
2. **Hard non-offloading rule**: Standard vectorized Python, LP/MILP/NLP, ODE/PDE integration, and seconds-scale Monte Carlo/Bootstrap **MUST** be executed autonomously by the agent—never outsourced to the user.
3. **Standardized ticket (`work/human_requests/req_XX.md`)**: Never ask vaguely. Always register via `manifest_cli.py request` (sets stage to `WAITING_HUMAN`) and include: goal/context, ready-to-run prompt or self-contained parameter script, strict CSV/JSON schema & save path, and a mandatory **Fallback** route (pure SVG/HTML vector diagram or reduced-order Python solver) so declining/skipping never stalls delivery.
