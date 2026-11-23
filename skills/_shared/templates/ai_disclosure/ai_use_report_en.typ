// Report on Use of AI (COMAP MCM/ICM Typst Template)
// Place at the very end of the paper; excluded from the 25-page limit per COMAP rules.

#pagebreak()
#set page(header: none, footer: none, numbering: none)
#align(center)[#text(size: 16pt, weight: "bold")[Report on Use of AI]]
#v(0.8em)
*Team Control Number:* #team-number #h(1fr) *Problem Chosen:* #problem-chosen

=== 1. AI Tools Used and Division of Labor
Our team used AI tools strictly as productivity aids under COMAP's AI policy. All modeling assumptions, mathematical formulations, and final conclusions were independently verified by team members.

#table(
  columns: (auto, auto, 1fr, 1fr),
  stroke: (top: 0.8pt, bottom: 0.8pt),
  [*Stage*], [*Tool / Model*], [*AI Assistance*], [*Human Verification*],
  [Problem Analysis], [[Model Name]], [Cross-checking problem text and tables], [Page-by-page human visual review],
  [Solver & Figures], [[Model Name]], [Drafting Python solver and plot scripts], [Independent constraint checker & tests],
  [Writing & Editing], [[Model Name]], [Grammar review and Typst formatting], [Line-by-line check vs `results.json`],
)

=== 2. Verification and Anti-Hallucination Protocol
- *Model-First Gate*: Formulations were reviewed and confirmed prior to implementation.
- *Independent Constraint Checking*: Separate script recomputed objectives and constraint violations.
- *Single Source of Truth*: All reported numbers were verified against `results.json`; references verified via Crossref/arXiv.

=== 3. Concrete Examples of Human Corrections
- *Case 1 (Formulation / Constraint Fix)*: [Describe specific correction]
- *Case 2 (Code / Data Fix)*: [Describe specific bug fixed]
- *Case 3 (Text / Consistency Fix)*: [Describe specific numerical/phrasing fix]

=== 4. Statement of Responsibility
We affirm that this report accurately reflects all AI usage in our submission and that our team accepts full responsibility for the entire paper.
