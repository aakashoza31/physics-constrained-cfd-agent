# Paper overview

## One paragraph

We present a physics-constrained autonomous CFD agent in which a language model
interprets engineering requests, routes them to registered problem families,
diagnoses simulation evidence and proposes bounded corrective actions, while
every scientific decision — geometry admissibility, mesh quality, numerical
health, conservation, convergence, stationarity, validation, permitted actions
and the final verdict — is made by deterministic code that the model cannot
override. We demonstrate the system on three headline cases: two validated
compressible families that the agent carries from natural language to an accepted
result, and one three-dimensional turbulent case that the agent executed and the
deterministic authority **rejected** because a lateral flow mode was still
growing, despite every conventional convergence indicator passing. A supplementary
case shows the same authority refusing three successive mesh generations for a
fourth family, so that no CFD was run at all. The contribution is not a faster
solver or a better turbulence model: it is an architecture in which an autonomous
agent cannot produce a false acceptance, demonstrated by the cases where it
refuses.

## The claim, stated narrowly

An LLM-driven CFD agent can be given real autonomy over interpretation, routing,
diagnosis and correction **provided** that a separate deterministic layer owns
every acceptance decision, and that layer is testable, versioned and visible in
the artifacts of every run.

## Evidence for the claim

| Evidence | Where |
|---|---|
| The agent accepts what should be accepted | F1 (3/3), F2 (5/8) |
| The agent refuses what should be refused, at runtime | F3 cube: growth 2.10× vs 1.25× limit, while drag drift was 0.08% |
| The agent refuses before running, on mesh quality | S1 airfoil: three mesh generations, `CFD_NOT_RUN` |
| The agent refuses unsupported input without simulating it | STEP input returns INCONCLUSIVE / UNSUPPORTED |
| A model proposal cannot become a verdict | `src/authority/boundary.py`, enforced by tests |

## What the paper must not claim

That the system generalises to arbitrary CFD; that the cube case is a validated
cube simulation; that the NACA0012 work reproduces NASA results; or that LLM
diagnosis improves accuracy. See `docs/limitations.md`.

## Open work before submission

- the ablation study (`evaluation/`) is `NOT_RUN`;
- no quantified grid-convergence index for the accepted families;
- the S1 CGNS orientation defect is diagnosed but not fixed;
- related work is a placeholder.
