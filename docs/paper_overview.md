# Paper overview

## One paragraph

We present a physics-constrained autonomous CFD agent in which a language model
interprets engineering requests, routes them to registered problem families,
diagnoses simulation evidence and proposes bounded corrective actions, while
scientific acceptance remains under deterministic control. The current validated
scope contains two compressible-flow families: a converging-diverging nozzle and
a two-dimensional forward-facing step. For each family, the system can build and
execute OpenFOAM cases, extract numerical and physical evidence, produce reports
and provenance, and apply bounded correction logic. Supplementary cube and airfoil
studies are retained to document the current operating boundary, but they are not
part of the validated headline claim. The contribution is an auditable agentic
CFD workflow rather than a faster solver or a new turbulence model.

## The claim, stated narrowly

An LLM-driven CFD agent can be given real autonomy over interpretation, routing,
diagnosis and correction **provided** that a separate deterministic layer owns
every acceptance decision, and that layer is testable, versioned and visible in
the artifacts of every run.

## Evidence for the claim

| Evidence | Where |
|---|---|
| The agent accepts what should be accepted | F1 (3/3), F2 (5/8) |
| Scientific certification remains outside the LLM | Deterministic gates own the final decision even when the solver completes cleanly |
| The agent refuses before running, on mesh quality | S1 airfoil: three mesh generations, `CFD_NOT_RUN` |
| The agent refuses unsupported input without simulating it | STEP input returns INCONCLUSIVE / UNSUPPORTED |
| A model proposal cannot become a verdict | `src/authority/boundary.py`, enforced by tests |

## What the paper must not claim

That the system generalises to arbitrary CFD; that the exploratory cube study is a validated
turbulent benchmark; that the NACA0012 work reproduces NASA results; or that LLM
diagnosis improves accuracy. See `docs/limitations.md`.

## Open work before submission

- the ablation study (`evaluation/`) is `NOT_RUN`;
- no quantified grid-convergence index for the accepted families;
- the S1 CGNS orientation defect is diagnosed but not fixed;
- related work is a placeholder.
