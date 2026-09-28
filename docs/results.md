# Results

Three headline demonstrations and one supplementary case. Every row is read from
archived evidence in this repository; nothing here is projected or expected.

## Status table

| # | Family | Case | Physics | Outcome | What it demonstrates |
|---|---|---|---|---|---|
| F1 | `nozzle` | `canonical_reference`, `geometry_variation`, `condition_variation` | compressible Euler, 2-D | **ACCEPTED** (3/3) | validated acceptance, continuation and correction behaviour |
| F2 | `forward_step_2d` | 8 cases | compressible Euler, 2-D transient | **ACCEPTED** (5) + **safe stop** (3) | accepted variations, mesh sensitivity, and an inadmissible variation refused |
| F3 | `cube` | `drifting_wake` | incompressible RANS, 3-D transient | **RUNTIME REJECTED** | 3-D execution, LLM diagnosis, deterministic rejection of a still-developing flow |
| S1 | `airfoil` | `mesh_rejection` | incompressible RANS, 2-D | **MESH REJECTED, `CFD_NOT_RUN`** | the mesh contract refusing every candidate mesh; no solver ever launched |

## F1 — compressible nozzle (ACCEPTED)

| Case | Original id | Archived status | Verdict |
|---|---|---|---|
| `canonical_reference` | `case_A_reference` | `PASS_SINGLE_MESH` | ACCEPT |
| `geometry_variation` | `case_B_geometry` | `PASS_SINGLE_MESH` | ACCEPT |
| `condition_variation` | `case_C_conditions` | `PASS_SINGLE_MESH` | ACCEPT |

Correction behaviour is preserved in the feedback campaigns under
`demo/nozzle_feedback*`, and the published campaign under
`demo/published_campaign` carries the closed-loop demonstration.

## F2 — forward-facing step (ACCEPTED, with a refusal)

| Case | Original id | Archived status | Verdict |
|---|---|---|---|
| `mach20_canonical` | `case_B_mach20` | `ACCEPTED` / `PASS_2D_FORWARD_STEP` | ACCEPT |
| `mach35_variation` | `case_C_mach35` | `ACCEPTED` | ACCEPT |
| `step_height_010` | `case_E_step010` | `ACCEPTED` | ACCEPT |
| `step_height_030_extended` | `case_G_step030_x100` | `ACCEPTED` | ACCEPT |
| `iterative_correction` | `case_H_iterative_short_run` | `ACCEPTED` after 7 iterations | ACCEPT |
| `step_height_030_short_horizon` | `case_F_step030` | `STOPPED_FAIL_SAFELY` | REJECT |
| `mesh_sensitivity` | `case_I_mesh_sensitivity` | `STOPPED_ACTION_REFUSED` | REJECT |
| `live_run` | `live_run_01` | `STOPPED_FAIL_SAFELY` | REJECT |

`step_height_030_short_horizon` is the inadmissible variation: the solver
completed and the fields were sane, but the registered compression-front check
was not measurable within the requested horizon, so the run stopped safely
instead of being accepted. `step_height_030_extended` is the same geometry with
the horizon extended, and it is accepted.

## F3 — surface-mounted cube (RUNTIME REJECTED)

The headline refusal. A 3-D turbulent run executed to t = 80 and reported no
numerical failure.

| Quantity | Measured | Registered limit | Result |
|---|---|---|---|
| Streamwise force drift over the final window | 0.08% of mean | ≤ 2% | PASS |
| Vertical force drift | 0.05% of mean | ≤ 2% | PASS |
| Mean lateral force / mean drag | 6.3e-4 | ≤ 0.05 | PASS |
| **Lateral force growth across the window** | **2.10×** | **≤ 1.25×** | **FAIL** |

The lateral force is a periodic mode of period ≈ 10.1 time units whose amplitude
grew from 1.01e-4 to 6.91e-3 — a factor of 68 — at an exponential rate of 0.091
per time unit (e-folding 11.0), and had not saturated when the run ended.

**Every conventional convergence indicator passed.** The drag was settled to
0.08%. A pipeline that watched the drag would have accepted a flow that was still
developing. The deterministic gate refused it on growth, and the refusal is
reproducible: `python scripts/run_demo.py --family cube --case drifting_wake
--mode replay` re-runs the gate over all 2003 archived force samples.

This case is **not** a validated cube simulation and must never be presented as
one. No reference comparison was performed, because a still-developing flow
cannot be compared against one.

## S1 — NACA0012 (supplementary, `CFD_NOT_RUN`)

Three mesh generations were attempted and all were rejected. The record below is
the **corrected** one, from an independent cell-geometry audit; the raw
qualification reports under `outputs/airfoil_mesh/` are superseded historical
evidence and carry a `SUPERSEDED.txt` banner.

### Defects that were ours, not NASA's

The earlier diagnosis blamed the NASA grids for cell orientation, in-plane
validity and skewness. The audit showed all three were artefacts of our own
representation:

* the coordinate transform `(x,y,z)_NASA -> (x,z,y)_OpenFOAM` reverses handedness;
* the corrected local vertex permutation for the archived NASA ordering is
  `P = (3, 7, 6, 2, 0, 4, 5, 1)`;
* the in-plane checker used `cell[:4]`, which selects a **side** face rather than
  the constant-span flow-plane quad;
* the Python skewness metric is **not** Foundation-v14 skewness.

After selecting the real spanwise face and orienting it correctly: **0**
nonpositive in-plane areas, **0** nonpositive bilinear corner Jacobians, and
span-plane coordinates matching exactly, on all three levels.

### Foundation-v14 `checkMesh`, as archived

| Level | non-orthogonality (≤ 65°) | skewness (≤ 2) | min weight (≥ 0.10) | min face-volume ratio (≥ 0.10) |
|---|---|---|---|---|
| coarse | 79.7474 **FAIL** | 0.857067 PASS | 0.123368 PASS | 0.162489 PASS |
| medium | 57.8856 PASS | 0.820430 PASS | 0.157720 PASS | 0.213368 PASS |
| fine | 31.5684 PASS | 0.727893 PASS | 0.213019 PASS | 0.301691 PASS |

Skewness passes everywhere. It is **not** the rejection reason and must never be
quoted as one.

### The decisive genuine failure: in-plane stretching

Longest edge over minimum width of the constant-span flow-plane quad, frozen
limit **10,000**:

| Level | max stretching | cells over the limit | of |
|---|---|---|---|
| coarse | 31,734,384 | 974 | 14,336 |
| medium | 36,320,937 | 3,924 | 57,344 |
| fine | 38,855,541 | 15,678 | 229,376 |

Three to four orders of magnitude over the limit, and worse with refinement.
This is a property of the Family II grids as supplied, measured on the correctly
selected face.

Face-tet warnings remain unresolved at 72 / 214 / 625 faces. They are not needed
to establish the rejection, because stretching already fails decisively.

**Final status: `MESH_REJECTED / CFD_NOT_RUN`.** No flow solver was ever launched
for this family. Its value in the paper is as a negative result — and as an
honest account of a diagnosis that was wrong until it was independently audited.

## Registered-case safety regression (replay consistency)

Replaying all 13 registered cases through the pipeline reproduces every archived
verdict: **false acceptance 0.0, correct rejection 1.0** over 13 runs.

This is a **safety regression / replay-consistency test**, not the paper's
evaluation. It shows that the deterministic gates still reach the same verdicts
on fixed archived evidence. It says nothing about model generalisation, because
no model decides anything in a replay and no new case is attempted.

## Evaluation

The ablation study (full agent vs fixed recipe vs gates-off vs no-diagnosis) is
`NOT_RUN`. See `docs/reproducibility.md` and `evaluation/README.md`.
