# Limitations

Read this before believing anything else in the repository.

## What is actually validated

Two families, both inviscid compressible Euler, both 2-D: the converging-diverging
nozzle and the forward-facing step. Everything else in this repository is either
a supplementary development study (the cube and airfoil mesh work) or infrastructure.

Two validated families is **not** a general-purpose CFD agent. The product
contract is implemented end to end, but the set of problems it can carry from
prompt to accepted result is small and closed.

## Physics not covered

No viscous wall-bounded validation, no turbulence-model validation, no reacting
flow, no multiphase, no conjugate heat transfer, no moving geometry, no
compressible turbulence. The exploratory cube run did not reach validation
because its registered stationarity/development criterion was not satisfied.

## Geometry

No STEP/CAD family exists. The interface classifies and refuses CAD parts; see
`docs/cad_and_step_input.md`. Parametric geometry only, and only the shapes the
two validated families generate themselves.

## Statistical and numerical rigour

- No formal grid-convergence index or Richardson extrapolation is reported for
  the accepted families; mesh sensitivity is demonstrated, not quantified into
  an uncertainty.
- No uncertainty quantification, no sensitivity to numerical scheme, no repeated
  runs to separate solver noise from physical variation.
- The cube case ran at one mesh resolution. Its non-certification is a statement
  about that run's development, not about the physical flow.

## The gates themselves

Deterministic authority is only as strong as the registered criteria. The cube
stationarity thresholds (2% drift, 1.25× growth, 5% lateral magnitude) are
registered in `src/families/cube/stationarity.py` with their reasoning. The
exploratory run does not satisfy the growth bound, so it is not used as validated
turbulent-flow evidence; the threshold itself remains open to scientific review.

## LLM involvement

The default interpreter and diagnosis path in this repository are deterministic
keyword and recipe logic, so the pipeline runs without an API key. The archived
campaigns contain real LLM calls (`llm_calls.json`, `llm_interpretation.json`).
No claim is made about which model, at which temperature, would reproduce those
diagnoses — that experiment has not been run.

## Reproducibility boundaries

- Replay is fully reproducible and needs no solver.
- Live execution requires OpenFOAM Foundation v14; results on another
  distribution or version are not claimed to match. The square-duct work in the
  archive is the evidence for that caution: matching turbulence-model *names*
  across CFD versions did not imply equivalent numerical physics.
- Contour rendering requires ParaView; video requires ffmpeg or pillow. Both
  report NOT_AVAILABLE rather than degrading silently.

## What this repository does not claim

1. That an arbitrary engineering prompt can be simulated.
2. That arbitrary CAD geometry can be meshed or solved.
3. That the cube case is a validated simulation of flow over a cube.
4. That the NACA0012 work reproduces NASA CFL3D results — no CFD was run.
5. That LLM diagnosis improves accuracy. The claim is narrower: it does not
   compromise it, because it cannot overrule the gates.
