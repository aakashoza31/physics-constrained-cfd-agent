# Family register

The frozen scope. This page summarises what each family is allowed to do; the
machine-readable form is `src/families/capabilities.py`, and the two must agree.

| Family | Register status | Routable | Physics | STEP | Cases | Solver run | In the paper |
|---|---|---|---|---|---|---|---|
| `nozzle` | `ACCEPTED` (registered) | yes | inviscid compressible (`shockFluid`), axisymmetric 5° wedge | no | 3 | yes | registered family |
| `forward_step_2d` | `ACCEPTED` (registered) | yes | inviscid compressible (`shockFluid`), 2-D planar, transient | no | 8 | yes | registered family |
| `cube` | `SUPPLEMENTARY` | no | URANS k-ω SST (`incompressibleFluid`), 3-D transient | no | 1 | yes, outside the agent loop | diagnostic study, not a family |
| `airfoil` | `SUPPLEMENTARY` | no | incompressible RANS, 2-D | no | 1 | **no** | not part of the paper |
| `backward_step` | `NOT_IMPLEMENTED` | no | — | no | 0 | no | not part of the paper |

## Status semantics

- **`ACCEPTED`** (code identifier) — a registered, routable family: it may
  execute, and its runs may be accepted when they pass the family's registered
  checks. Registration is not physical validation.
- **`SUPPLEMENTARY`** — preserved evidence or a development study. Not routable
  for acceptance.
- **`NOT_IMPLEMENTED`** — declared for completeness, deliberately not built.

Only registered (`ACCEPTED`) families can reach a solver through the agent.
`src/orchestration/live.py` refuses the others before any process starts, and the
refusal is tested.

## Cube diagnostic study

The cube calculation was run outside the agent loop (23-24 September 2026) and
completed its bounded extension to t* = 80 without numerical failure. Its
stationarity gate, `cube-stationarity/1.0.0` (`src/families/cube/stationarity.py`),
was registered retrospectively on 28 September 2026, after the data existed.
Over the gate window t* = 59.98-79.98 the drag drift is 0.075% of the mean
(limit 2%) and the mean lateral force is 0.063% of the drag (limit 5%), but the
half-window mean |Fz| ratio is 2.10 against the limit of 1.25. The gate returns
`STILL_DEVELOPING` and the result is REJECT. A separate complete-cycle audit
(not part of the gate) finds successive amplitude growth of 209%, 137% and 113%:
the growth rate is declining, but the lateral mode has not saturated.

Evidence: `cases/cube/drifting_wake/` (force history, statistics, lateral-mode
characterisation), `evidence/cube/drifting_wake/`, and the three LLM diagnosis
calls of 1 October 2026 in `evidence/cube/drifting_wake/llm_diagnosis/`. Replay:
`python scripts/run_demo.py --family cube --case drifting_wake --mode replay`.

The cube is a diagnostic study, not a validated benchmark and not a routable
family. The archived machine-readable decision is preserved for provenance.

## `airfoil` (not part of the paper, `CFD_NOT_RUN`)

Not part of the CFD Forge paper. Three mesh generations, all rejected; no solver
was ever launched. The decisive genuine failure is **in-plane stretching**
(3.17e7 / 3.63e7 / 3.89e7 against a frozen limit of 10,000, on 974 / 3,924 /
15,678 cells).

Foundation-v14 `checkMesh` skewness is 0.857 / 0.820 / 0.728 — passing — and the
orientation and in-plane defects in the first diagnosis were artefacts of the
repository's own converter, not of the NASA grids. The corrected record is
`cases/airfoil/mesh_rejection/reference/corrected_diagnosis.json`; see also
`docs/results.md`.

## `backward_step` (not part of the paper)

Not part of the CFD Forge paper. Declared in the register and deliberately not
built. Its adapter and recipe construct so the register is inspectable, and the
recipe carries unresolved acceptance constants, so nothing it produced could be
accepted.

## Superseded terminology

The status `CORE-PENDING` no longer appears in the active register. It survives
inside `src/families/` and `src/router/` as the mechanism that makes an
unregistered family non-executable.
