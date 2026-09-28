# Family register — active

The frozen scope. This page is the single source of truth for what each family
is allowed to do; the machine-readable form is `src/families/capabilities.py`
and the two must agree (a test enforces it).

| Family | Status | Routable | Physics | STEP | Cases | Solver run |
|---|---|---|---|---|---|---|
| `nozzle` | **ACCEPTED** | yes | compressible Euler, 2-D | no | 3 | yes |
| `forward_step_2d` | **ACCEPTED** | yes | compressible Euler, 2-D transient | no | 8 | yes |
| `cube` | **SUPPLEMENTARY** | no | incompressible RANS, 3-D transient | no | 1 | yes |
| `airfoil` | **SUPPLEMENTARY** | no | incompressible RANS, 2-D | no | 1 | **no** |
| `backward_step` | **NOT_IMPLEMENTED** | no | — | no | 0 | no |

## Status semantics

- **ACCEPTED** — validated, routable, may execute and may be accepted.
- **SUPPLEMENTARY** — preserved evidence or development studies. Not routable for acceptance.
- **NOT_IMPLEMENTED** — declared for completeness, deliberately not built.

Only **ACCEPTED** families can reach a solver through the agent. `live.py`
refuses the others before any process starts, and the refusal is tested.

## Experimental 3-D cube study — supplementary

A 3-D turbulent run executed to t = 80 and reported no numerical failure.
The streamwise load settled to 0.08% of its mean over the assessment window
while a periodic lateral mode of period ≈ 10.1 grew 68× in amplitude
(1.01e-4 → 6.91e-3, e-folding 11.0) without saturating. Under the registered
stationarity/development criterion, the case was therefore not certified as a
validated benchmark result.

Evidence: `cases/cube/drifting_wake/` (force history, statistics, lateral-mode
characterisation) and `evidence/cube/drifting_wake/`. Replay:
`python scripts/run_demo.py --family cube --case drifting_wake --mode replay`.

This is retained as an **exploratory development study**, not as a validated
cube benchmark. The archived machine-readable decision remains preserved for
provenance.

## S1 — `airfoil`, SUPPLEMENTARY, `CFD_NOT_RUN`

Three mesh generations, all rejected; no solver was ever launched. The decisive
genuine failure is **in-plane stretching** (3.17e7 / 3.63e7 / 3.89e7 against a
frozen limit of 10,000, on 974 / 3,924 / 15,678 cells).

Foundation-v14 `checkMesh` skewness is 0.857 / 0.820 / 0.728 — passing — and the
orientation and in-plane defects in the first diagnosis were artefacts of our own
converter, not of the NASA grids. The corrected record is
`cases/airfoil/mesh_rejection/reference/corrected_diagnosis.json`; the
development history is archived under `docs/archive/airfoil_mesh_development/`.

## `backward_step`

Declared in the register and deliberately not built. Its adapter and recipe
construct so the register is inspectable, and the recipe carries unresolved
acceptance constants, so nothing it produced could ever be accepted.

## Superseded terminology

The status `CORE-PENDING` no longer appears in the active register. It survives
inside `src/families/` and `src/router/` as the mechanism that makes an
unregistered family non-executable, and in the legacy register preserved at
`docs/archive/airfoil_mesh_development/FAMILY_REGISTER_legacy.md`.
