# Results

The two registered families (nozzle, 2-D forward-facing step), the turbulent-cube
diagnostic study, and the controller comparison, as reported in the CFD Forge
paper. A supplementary airfoil mesh study, which is not part of the paper, is
recorded at the end. Every row is read from archived evidence in this repository
or the session archive (Zenodo, https://doi.org/10.5281/zenodo.23148676); nothing here is
projected or expected. All archived agent sessions are development cases, not a
held-out evaluation.

## Status table

| Family or study | Case(s) | Physics | Outcome | What it demonstrates |
|---|---|---|---|---|
| `nozzle` (registered) | `canonical_reference`, `geometry_variation`, `condition_variation` | inviscid compressible, axisymmetric 5° wedge | **ACCEPT** (3/3 requests) | acceptance, continuation and new cases built from text requests |
| `forward_step_2d` (registered) | 8 cases | inviscid compressible, 2-D transient | 5 **ACCEPT**, 1 **REJECT**, 1 **INCONCLUSIVE**, 1 archived **REJECT** from a false-positive check | new cases, a safe stop, a refused `ACCEPT` |
| `cube` (diagnostic study, not a family) | `drifting_wake` | URANS k-ω SST (`incompressibleFluid`), 3-D | **REJECT** (`STILL_DEVELOPING`, retrospectively registered gate) | solver completion and a settled drag do not establish a developed flow |

## Nozzle

| Case | Original id | Request | Archived status | Decision |
|---|---|---|---|---|
| `canonical_reference` | `case_A_reference` | reference, r_e = 35.4 mm, p0 = 200 kPa | `PASS_SINGLE_MESH` | ACCEPT |
| `geometry_variation` | `case_B_geometry` | exit radius 37.0 mm | `PASS_SINGLE_MESH` | ACCEPT |
| `condition_variation` | `case_C_conditions` | p0 = 220 kPa | `PASS_SINGLE_MESH` | ACCEPT |

These are the canonical runs (N1-N3 in the paper's session ledger). The
requests were repeated while the feedback loop was developed (N4-N8). A separate
continuation run of the reference request (N6, `nozzle_feedback_v2_hotfix`) was
executed first to 1 ms, failed the steady mass-balance and stationarity checks
(`FAIL`), and was accepted after `CONTINUE_RUN`, `CONTINUE_RUN`, `ACCEPT`
(`PASS_SINGLE_MESH` at 6 ms). N4 and N5 ended before an approved action was
carried out and are recorded as not accepted. The session records are in the
Zenodo session archive (`demo/nozzle_e2e/`, `demo/nozzle_feedback*/`).

## Forward-facing step

| Ledger | Case | Original id | Request (M, h, x) | Archived status | Decision |
|---|---|---|---|---|---|
| S2 | `mach20_canonical` | `case_B_mach20` | 2.0, 0.20, 0.6 | `PASS_2D_FORWARD_STEP` | ACCEPT |
| S3 | `mach35_variation` | `case_C_mach35` | 3.5, 0.20, 0.6 | `PASS_2D_FORWARD_STEP` | ACCEPT |
| S4 | `step_height_010` | `case_E_step010` | 3.0, 0.10, 0.6 | `PASS_2D_FORWARD_STEP` | ACCEPT |
| S6 | `step_height_030_x100` | `case_G_step030_x100` | 3.0, 0.30, 1.0 | `PASS_2D_FORWARD_STEP` | ACCEPT |
| S7 | `iterative_correction` | `case_H_iterative_short_run` | 3.0, 0.20, 0.6, staged horizon | `PASS_2D_FORWARD_STEP` after 7 proposals over 4 resumed sessions | ACCEPT after supervised resumption and a restart-seam mass-closure fix (not an unattended result) |
| S5 | `step_height_030_x060` | `case_F_step030` | 3.0, 0.30, 0.6 | `FAIL` (no measurable compression front; `STOPPED_FAIL_SAFELY`) | REJECT |
| S8 | `mesh_sensitivity` | `case_I_mesh_sensitivity` | 3.0, 0.20, 0.6, sensitivity request | `STOPPED_ACTION_REFUSED` | INCONCLUSIVE |
| S1 | `live_run` | `live_run_01` | 2.5, 0.15, 0.6 | `FAIL` from a false-positive fatal-error check (`STOPPED_FAIL_SAFELY`) | archived REJECT; `PASS_2D_FORWARD_STEP` on corrected deterministic reanalysis |

`step_height_030_x060` (S5): the solver completed and the fields were sane, but
the compression front was displaced to x = 0.025 and could not be measured, so
the model proposed `FAIL_SAFELY`, which was approved, and the run was preserved
and rejected rather than tuned. `step_height_030_x100` (S6) moves the same step
(h = 0.3) to x = 1.0; both runs went to t = 4. At x = 1.0 the front had not yet
reached the inlet at t = 4 and the run passed its contract, which for this
transient family includes no stationarity criterion.

`mesh_sensitivity` (S8): the model proposed `REFINE_MESH`, which was approved
(4,032 to 16,128 cells, fresh solve); both grids passed their hard checks, and
the model's subsequent `ACCEPT` was refused by the action validator because no
cross-grid tolerance is registered for the step family. Both solutions were
healthy, but the requested sensitivity assessment could not be certified, so the
decision is INCONCLUSIVE, and the replay of `scripts/run_demo.py` reports it as
INCONCLUSIVE (`cases/forward_step/mesh_sensitivity/expected_result.json`).

`live_run` (S1): the archived validator matched the OpenFOAM start-up line that
enables floating-point trapping as a fatal error. The archived verdict remains
REJECT; a deterministic reanalysis of the unchanged run after the detector was
corrected returns `PASS_2D_FORWARD_STEP` without a new solve.

## Cube diagnostic study

The cube calculation was run outside the agent loop (23-24 September 2026). Its
stationarity gate, `cube-stationarity/1.0.0` (`src/families/cube/stationarity.py`),
was registered retrospectively on 28 September 2026, after the data existed. The
calculation completed its bounded extension to t* = 80 without numerical failure.

| Quantity (window t* = 59.98-79.98) | Measured | Registered limit | Result |
|---|---|---|---|
| Drag drift over the window | 0.075% of mean | ≤ 2% | PASS |
| Mean lateral force / mean drag | 0.063% | ≤ 5% | PASS |
| **Half-window mean \|Fz\| ratio** | **2.10** | **≤ 1.25** | **FAIL** |

The gate returns `STILL_DEVELOPING` and the result is REJECT. The lateral force
oscillates with a period of about 10.1 time units while its envelope grows. A
separate read-only complete-cycle audit, which is not part of the gate, finds
successive complete-cycle amplitude growth of 209%, 137% and 113%: the growth
rate is declining, but the mode has not saturated. Between the t* = 60-70 and
70-80 block averages the mean drag changes by 0.04% while the RMS lateral force
increases by 110%. No reference comparison is claimed. The archived assessment is
reproduced with
`python scripts/run_demo.py --family cube --case drifting_wake --mode replay`.

**LLM diagnosis of the cube evidence.** On 1 October 2026 the agent's diagnosis
stage was applied three times to the archived cube evidence
(`paper/cfd_forge/scripts/cube_llm_diagnosis.py`, `gemini-3.5-flash-lite`,
temperature 0, identical packet without the gate verdict or threshold). Records:
`evidence/cube/drifting_wake/llm_diagnosis/`.

| Call | Diagnosis | Proposed action | Validator |
|---|---|---|---|
| 1 | `STILL_DEVELOPING` | `CONTINUE_RUN` | approved |
| 2 | `NUMERICALLY_UNHEALTHY` | `FAIL_SAFELY` | approved |
| 3 | `STILL_DEVELOPING` | `CONTINUE_RUN` | approved |

No call proposed `ACCEPT`, and no action was executed. Identical inputs at
temperature 0 produced two different diagnoses.

## Controller comparison

Four controllers were compared on archived decision points with
`gemini-3.5-flash-lite` at temperature 0 and the current validators: (A) fixed
rule, (B) CFD Forge, (B') gates off, (C) model only on a filtered packet without
the deterministic check results. Script:
`paper/cfd_forge/scripts/controller_comparison.py`; evidence:
`evidence/controller_comparison/20261001T213031Z/`.

| Controller | Archived (16 points) | Planted faults (18) | Defects (2) |
|---|---|---|---|
| A: fixed rule | 16/16 (0) | 18/18 (0) | 0/2 (0) |
| B: CFD Forge | 79/79 (0) | 53/53 (0) | 0/10 (0) |
| B': gates off | 74/79 (0) | 53/53 (0) | 0/10 (0) |
| C: model only | 72/79 (7) | 3/53 (50) | 5/10 (0) |

Entries are correct decisions / decisions, false accepts in parentheses. 288
model calls were attempted, 284 succeeded and 4 failed (`429 RESOURCE_EXHAUSTED`);
1,099,390 tokens; median latency 1.27 s. Rerunning it requires the Zenodo session
archive (`--demo-root`) and a `GEMINI_API_KEY`; model outputs are not
reproducible exactly. The older harness `scripts/run_evaluation.py` is a
separate legacy replay harness, not this comparison (`evaluation/README.md`).

## NACA0012 airfoil mesh study (not part of the paper, `CFD_NOT_RUN`)

Not part of the CFD Forge paper; a mesh-development record in which no flow solver was run.

Three mesh generations were attempted and all were rejected. The record below is
the **corrected** one, from an independent cell-geometry audit; the raw
qualification reports under `outputs/airfoil_mesh/` (development archive, not in this repository) are superseded historical
evidence and carry a `SUPERSEDED.txt` banner.

### Defects in the earlier diagnosis, not in the NASA grids

The earlier diagnosis blamed the NASA grids for cell orientation, in-plane
validity and skewness. The audit showed all three were artefacts of the
repository's own representation:

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
for this study. It is retained as a negative result and as a record of a
diagnosis that was wrong until it was independently audited.

## Registered-case replay consistency

Replaying the registered cases through `scripts/run_demo.py --mode replay`
reproduces every archived verdict stored in `cases/*/*/expected_result.json`.
This is a replay-consistency check, not an evaluation: no model decides anything
in a replay and no new case is attempted. The replay trace reports three
terminal verdicts (ACCEPT, REJECT, INCONCLUSIVE) and records the S8
refused-action case as INCONCLUSIVE, as in the paper.
