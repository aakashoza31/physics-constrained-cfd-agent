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

Three mesh generations were attempted and all were rejected:

| Attempt | Meshes | Outcome |
|---|---|---|
| Gmsh v1 (uniform cosine surface) | coarse/medium/fine | all `F3_MESH_NOT_QUALIFIED`: skewness 2.86→8.65, weight 4.3e-3, volume ratio 3.3e-3 |
| Gmsh v2 (partitioned TE distribution) | coarse/medium/fine | all `F3_MESH_NOT_QUALIFIED`: the mismatch relocated to the BL outer front; skewness 275→792 |
| NASA TMR Family II CGNS | 14,336 / 57,344 / 229,376 cells | all `F3_MESH_NOT_QUALIFIED`: skewness 5.06 / 4.20 / 2.41 against a limit of 2 |

The Family II run also flagged `positive_cell_orientation` and
`all_in_plane_elements_valid` on all three levels with
`in_plane_sign_resolution` unresolved and in-plane stretching reported as 0.0 —
a signature of a **conversion/orientation defect on our side**, not of NASA's
grid. The genuine contract failure is the skewness one, which persists at the
fine level (2.41 > 2.0) after improving monotonically with refinement.

**No flow solver was ever launched for this family.** Its value in the paper is
as a negative result: a frozen mesh-quality contract that refuses, three times,
rather than proceeding to a CFD run whose accuracy could not be defended.

## Evaluation

The ablation study (full agent vs fixed recipe vs gates-off vs no-diagnosis) is
`NOT_RUN`. See `docs/reproducibility.md` and `evaluation/README.md`.
