# Manuscript outline

**Status: outline only. No experimental result in this file is invented; every
number cited below is a pointer to archived evidence in this repository, and
anything not yet run is marked `NOT_RUN`.**

## Abstract

See `docs/paper_overview.md`. One paragraph: agent proposes, authority decides;
demonstrated by two validated CFD families, with supplementary studies used to
document current operating boundaries.

## 1. Introduction

- Autonomous agents are being applied to simulation; the failure mode that
  matters is not a wrong number but a *confident* wrong number.
- Position: separate interpretation from acceptance. Give the model real
  autonomy over the first, none over the second.
- Contributions: (i) the agent/authority boundary, enforced in code; (ii) a
  family registration protocol that makes a new physics domain a declaration
  rather than a branch; (iii) three headline demonstrations including two
  refusals; (iv) a reproducible artifact.

## 2. Related work

`PLACEHOLDER`. To cover: LLM agents for scientific computing; autonomous
simulation pipelines; verification and validation practice (ASME V&V 20, Roache);
automated mesh generation and quality metrics; guardrail/critic architectures.

## 3. Method

3.1 Product contract and pipeline stages (`docs/architecture.md`)
3.2 Request interpretation and geometry characterization
3.3 Family routing and admissibility
3.4 Case and mesh generation
3.5 Execution and evidence extraction
3.6 Diagnosis and bounded correction

## 4. Scientific authority

4.1 The two sets: what a model may do, what only code decides
4.2 Gates, proposals and the authority trace
4.3 Verdict computation: REJECT > INCONCLUSIVE > ACCEPT
4.4 Why an unresolved gate is not a pass
4.5 Enforcement and tests (`docs/scientific_authority.md`)

## 5. Family registration protocol

5.1 Capability declarations
5.2 Recipes and unresolved constants (`TODO` cannot produce ACCEPT)
5.3 Adapters and gates
5.4 Case registration and replay (`docs/family_protocol.md`)

## 6. Experiments

6.1 F1 compressible nozzle — canonical, geometry variation, condition variation
6.2 F2 forward-facing step — accepted variations, mesh sensitivity, the
    inadmissible variation and its extended-horizon counterpart
6.3 Supplementary 3-D cube stationarity/development study (not a validated benchmark claim)
6.4 S1 NACA0012 — mesh-development study; CFD not run because qualification did not pass,
    `CFD_NOT_RUN`

## 7. Evaluation

Ablations: full agent; fixed recipe + fixed rules; agent without deterministic
gates; gates without diagnosis/repair. Metrics: valid completion, **false
acceptance**, correct rejection, first-attempt success, corrected success,
actions per run, solver attempts, runtime, human interventions, LLM/tool cost.

**Status: `NOT_RUN`.** The harness and the metric definitions exist in
`evaluation/`; no ablation has been executed, and no number may be reported until
it has.

## 8. Results

Populate from `docs/results.md`. Headline figures: the cube force history (drag
settled, lateral mode growing) and the gate table.

## 9. Failure and rejection analysis

9.1 Exploratory cube study: drag settled while a lateral mode continued to
    refused; the lateral mode (period ≈ 10.1, amplitude ×68, e-folding 11.0)
9.2 The airfoil: a frozen mesh contract refusing three successive generations;
    the v1 TE spacing mismatch, the v2 relocation of that mismatch, and the
    Family II **in-plane stretching** failure (3.2e7 / 3.6e7 / 3.9e7 against a
    limit of 10,000, on 974 / 3,924 / 15,678 cells)
9.3 Honest accounting of our own defects: the first Family II diagnosis blamed
    the NASA grid for orientation, in-plane validity and skewness. An
    independent cell-geometry audit showed all three were artefacts of our
    converter -- a handedness-reversing axis transform, a wrong vertex
    permutation (corrected: P = (3,7,6,2,0,4,5,1)), an in-plane checker reading
    `cell[:4]` (a side face) instead of the constant-span flow-plane quad, and a
    Python skewness proxy that is not Foundation-v14 skewness. Foundation-v14
    reports skewness 0.857 / 0.820 / 0.728, all passing. Also: the
    non-reproducible node numbering in the archived Gmsh generator.
9.4 What this says about autonomous diagnosis: the rejection verdict survived
    the audit unchanged, but its stated REASON did not. A pipeline that reports
    which gate failed, with its measured value, is auditable; one that reports
    only ACCEPT/REJECT is not.

## 10. Limitations

From `docs/limitations.md`: two validated families, both inviscid and 2-D; no
turbulent validation; no STEP support; no quantified grid-convergence index; no
UQ; ablations not run.

## 11. Discussion

- Refusal as a first-class result
- Where autonomy is safe and where it is not
- What it would take to add a turbulent family credibly

## 12. Conclusion

An agent that cannot overrule its own gates can be trusted with autonomy over
everything else. The evidence is the cases where it says no.

## Figures

| # | Figure | Source | Status |
|---|---|---|---|
| 1 | Architecture / authority boundary | `docs/architecture.md` Mermaid | ready |
| 2 | Cube force history with assessment window | `evidence/cube/drifting_wake/plots/force_history.png` | ready |
| 3 | Lateral amplitude growth (log) | `evidence/cube/drifting_wake/plots/lateral_force_growth.png` | ready |
| 4 | Gate outcome table per case | `evidence/*/*/plots/convergence.png` | ready |
| 5 | Mesh-quality failure across three generations | `docs/results.md` S1 tables | table only |
| 5b | Corrected vs pre-audit S1 diagnosis | `cases/airfoil/mesh_rejection/reference/corrected_diagnosis.json` | table only |
| 6 | Ablation results | `evaluation/` | `NOT_RUN` |
