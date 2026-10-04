# Nozzle cases

The nozzle family's demonstrated requests. Each passes through the same
request → mesh → OpenFOAM → evidence → LLM → deterministic-validation pipeline
(`scripts/run_nozzle_e2e.py`, `scripts/run_nozzle_feedback.py`). The registered
cases are in `cases/nozzle/`; the full session records are in the Zenodo session
archive (DOI to be added on release) under `demo/nozzle_e2e/` and
`demo/nozzle_feedback*/`. For the forward-facing-step cases see
`docs/results.md`.

Canonical geometry: inlet radius 50.0 mm, throat radius 32.6 mm, exit radius
35.4 mm; 2,112-cell axisymmetric 5° wedge (1,980 hex + 132 prisms). Operating
conditions: p0 = 200 kPa, T0 = 300 K, nominal ambient 30 kPa.

## Case A: canonical reference run

Session N1 (`demo/nozzle_e2e/case_A_reference`, run `20260921T041731Z`):
`cases/nozzle/canonical_reference`.

- a single execution to t = 6 ms (30,471 adaptive steps, maximum Courant number
  0.400)
- 20/20 deterministic checks pass
- LLM proposal `ACCEPT`, approved by the action validator
- final scientific verdict: `PASS_SINGLE_MESH` → `ACCEPT`

This run is the field-video source and is bit-identical to mesh 1 of the
LLM-free reference campaign (`docs/REFERENCE_VALIDATION.md`).

## Case A, continuation run (feedback demonstration)

Session N6 (`demo/nozzle_feedback_v2_hotfix/case_A_reference`, run
`20260921T052758Z`): a separate run of the same specification, distinct from the
canonical run above. Its first CFD horizon was deliberately limited to 1 ms
(`scripts/run_nozzle_feedback.py --feedback-demo`).

At t = 1 ms:

- solver completes normally; the state is physically admissible
- 17/20 deterministic checks pass; failed: `steady_mass_balance` (1.35% against
  0.1%), `monitors_stationary` (2.0% against 0.2%), `fields_stationary` (1.2%
  against 0.2%)
- LLM diagnosis `UNCONVERGED`, proposal `CONTINUE_RUN`, approved (initial
  end-to-end assessment)
- feedback iteration 1: LLM diagnosis `UNCONVERGED`, proposal `CONTINUE_RUN`,
  approved; the existing
  OpenFOAM state is continued from 1 ms to 6 ms

At t = 6 ms (feedback iteration 2):

- new numerical diagnostics and field images are generated
- 20/20 deterministic checks pass (stationarity ratios 0.59, 0.41, 0.66 of their
  limits)
- LLM diagnosis `ACCEPTABLE`, proposal `ACCEPT`, approved
- final scientific verdict: `PASS_SINGLE_MESH` → `ACCEPT`

Proposal sequence: `CONTINUE_RUN`, `CONTINUE_RUN`, `ACCEPT`. This run
demonstrates the corrective loop (`CORRECT_AND_RERUN` at 1 ms, then `ACCEPT`).
Earlier repeats of the same request (N4, N5) ended before an approved action was
carried out and were not accepted.

## Case B: geometry change

Session N2 (`demo/nozzle_e2e/case_B_geometry`): `cases/nozzle/geometry_variation`.
One engineering variable is changed from Case A: exit radius 35.4 mm → 37.0 mm;
reservoir conditions remain 200 kPa and 300 K.

- mesh generated and checked automatically (2,112-cell wedge)
- OpenFOAM runs to 6 ms in serial
- 20/20 deterministic checks pass; exit Mach number 1.652 (+0.39% from
  quasi-1-D theory)
- LLM proposal `ACCEPT`, approved; verdict `PASS_SINGLE_MESH` → `ACCEPT`

## Case C: operating-condition change

Session N3 (`demo/nozzle_e2e/case_C_conditions`):
`cases/nozzle/condition_variation`. Geometry returns to the canonical dimensions;
reservoir total pressure 200 kPa → 220 kPa.

- mesh generated and checked automatically (2,112-cell wedge)
- OpenFOAM runs to 6 ms in serial
- 20/20 deterministic checks pass; exit Mach number unchanged (1.513), exit
  pressure and mass flow scaled by 1.100
- LLM proposal `ACCEPT`, approved; verdict `PASS_SINGLE_MESH` → `ACCEPT`

Cases B and C were repeated in sessions N7 and N8 with the same outcome.

## What these cases establish

1. A corrective action driven by evidence when the first CFD state is incomplete
   (the continuation run).
2. New cases within the family built from text requests that change the geometry
   (Case B) and the operating conditions (Case C).

They do **not** establish that every geometry or condition inside the scope gate
has been verified. All sessions are development cases, not a held-out
evaluation, and the accepted runs are single-mesh. The scope gate prevents
unsupported requests from silently running; it is not a substitute for a broader
verification campaign.
