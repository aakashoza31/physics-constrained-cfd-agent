# Forward-step requests

These files are the natural-language requests of the archived forward-step
sessions, reproduced verbatim (up to line wrapping) from each session's
`request.txt`. Pass one to the runner with
`python scripts/run_forward_step_2d.py --request-file examples/forward_step_2d/<file>`.

The phrases "validated supersonic channel family" and "validated OpenFOAM
shockFluid numerical recipe" in the requests are historical wording, kept so the
files match what the model received. In the paper and in
this repository the family is *registered*: it has a frozen recipe and
deterministic checks, which is not a claim of validation.

| File | Archived session | Paper ledger | Case directory |
|---|---|---|---|
| `REQUEST_NONCANONICAL.txt` | `live_run_01` | S1 | `cases/forward_step/live_run` |
| `CASE_B_MACH20.txt` | `case_B_mach20` | S2 | `cases/forward_step/mach20_canonical` |
| `CASE_C_MACH35.txt` | `case_C_mach35` | S3 | `cases/forward_step/mach35_variation` |
| `CASE_E_STEP010.txt` | `case_E_step010` | S4 | `cases/forward_step/step_height_010` |
| `CASE_F_STEP030.txt` | `case_F_step030` | S5 | `cases/forward_step/step_height_030_x060` |
| `CASE_G_STEP030_X100.txt` | `case_G_step030_x100` | S6 | `cases/forward_step/step_height_030_x100` |
| `CASE_H_ITERATIVE_SHORT_RUN.txt` | `case_H_iterative_short_run` | S7 | `cases/forward_step/iterative_correction` |
| `REQUEST_MESH_SENSITIVITY.txt` | `case_I_mesh_sensitivity` | S8 | `cases/forward_step/mesh_sensitivity` |

The archived sessions are in the Zenodo archive (https://doi.org/10.5281/zenodo.23148676)
under `demo/forward_step_2d/<session>/`.
