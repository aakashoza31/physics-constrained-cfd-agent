# Evidence map: paper quantity → source

The `data/` paths are verbatim copies; `data/DATA_MANIFEST.json` gives each copy's original path and SHA-256.
Abbreviations: E2E = `Research/physics-constrained-cfd-agent-e2e/demo/`; AUD = `Codex/.../outputs/family3_cube_reference/audit_t80/`.

## Nozzle, canonical run `20260921T041731Z` (E2E `nozzle_e2e/case_A_reference/validation.json`)
| Quantity | Value | Key |
|---|---|---|
| Status | PASS_SINGLE_MESH, 20/20 checks | `status`, `checks` |
| Time steps / max Co | 30,471 / 0.40004 | `timesteps`, `max_Co` |
| Throat M (slab) | 1.0290 | `final.throat_M` |
| Exit M / p / T / U | 1.51325 / 53,142.7 Pa / 205.763 K / 435.089 m s⁻¹ | `final.outlet_*` |
| Theory exit M / p / T / U / ṁ | 1.50440 / 54,134.1 / 206.520 / 433.361 / 1.55824 | `theory` (the script's own quasi-1-D reproduces M and p to 1e-6) |
| Differences | M +0.588 %, p −1.831 %, T −0.366 %, U +0.399 %, ṁ −1.111 % | `theory_error_pct` |
| ṁ outlet (full nozzle) | 1.5409 kg s⁻¹ | `final.outlet_mdot` |
| Window mass mismatch | 0.05483 % | `final.max_window_mismatch_pct` |
| Max monitor drift | 0.0806 % (inlet ṁ) | `drift_fraction_last_2ms` |
| Max field change | 0.111 % (U) | `field_L2_change_last_2ms` |
| Transient continuity | 6.39e-8 % | `max_transient_continuity_pct` |
| p₀, T₀ inlet error | 2.48e-8, 7.24e-9 | `final.inlet_max_*_relative_error` |
| Min downstream slab M / min outlet normal M | 1.168 / 1.457 | `min_downstream_slab_Mach`, `final.outlet_normal_M_min` |
| Inlet M (slab) | 0.2528; theory 0.2558 (computed from area ratio 2.352) | `axial_profile.csv` row 1 |
| Mesh AR / non-orth / skew | 2.456 / 9.56° / 0.331 | `mesh_evidence.json`, `logs/log.checkMesh` |
| Model calls | 4 × gemini-3.5-flash-lite | `llm_calls.json` |
| Dictionaries | blockMeshDict, fvSchemes, fvSolution, controlDict, physicalProperties match the field-video manifest after CR stripping | `generated_case/` vs `evidence/field_evolution/nozzle/video_manifest.json` |

## Nozzle continuation run `20260921T052758Z` (E2E `nozzle_feedback_v2_hotfix/case_A_reference/iterations/`)
| Quantity | it. 1 (t = 1 ms) | it. 2 (t = 6 ms) |
|---|---|---|
| Status | FAIL: steady_mass_balance, monitors_stationary, fields_stationary | PASS_SINGLE_MESH |
| Window mismatch | 1.3479 % | 0.0588 % |
| Max drift | 2.017 % | 0.0822 % |
| Max field change | 1.165 % | 0.131 % |
| Max theory error | 0.66 % | 1.81 % |
| Gemini diagnosis → action | UNCONVERGED → CONTINUE_RUN (approved) | ACCEPTABLE → ACCEPT (approved) |
Thresholds: `src/pipeline/nozzle/validate.py` lines 449–467.

## Step, Mach 2 `20260922T193651Z` (E2E `forward_step_2d/case_B_mach20/iteration_01/`)
| Quantity | Value | Source |
|---|---|---|
| Status | PASS_2D_FORWARD_STEP, 17 hard + 3 compression checks | `validation.json` |
| Steps / wall | 5,428 / 102.2 s | `diagnostics.json` |
| Realized inlet M | 2.000006 | `diagnostics.realized_inlet_Mach` |
| Co max | 0.20206 | `Co.time_loop_max` |
| Closure residual max / p99 | 5.67e-11 / 2.97e-11 (limit 1e-6) | `mass`; reproduced from `transient_mass.csv` |
| Cumulative defect / wall flux | 8.29e-14 / 1.14e-17 | `mass` |
| Inlet / outlet flux at t = 4 | 0.2800 / 0.2348 (−16.1 %) | `mass` |
| Jumps p, ρ, T | 5.18, 2.87, 1.81 (normal-shock sanity 4.50, 2.67, 1.69) | `shock.jumps` |
| Front x | 0.525 (t = 0.1) → 0.1125 (t = 4) | `shock_front_history.csv` |
| Recipe hashes | fvSchemes, fvSolution, physicalProperties, momentumTransport of `src/pipeline/forward_step/template` match the manifest | field-video manifest |
| Model calls | gemini-3.5-flash-lite (interpretation, diagnosis, summary) + multimodal observer | `provenance.json`, `events.log` |
| Choking estimate | post-shock M 0.5774, A*/A 0.8220 (Mach 2); 0.7192 (Mach 3) | computed (standard relations) |

## Cube `family3_cube_sst_literature_audit_t4_retry2`
| Quantity | Value | Source |
|---|---|---|
| Registered gate | STILL_DEVELOPING; growth ratio 2.0984 (≤1.25); drift fx 0.0753 % (≤2 %); lateral rel. 0.0626 % (≤5 %); window 59.98–79.98, 500 samples | `cases/cube/drifting_wake/expected_result.json`; **reproduced exactly** by running `stationarity.assess` on `reference/force_history.json` |
| Mean C_D | 2 × 0.70621 = 1.412 | same |
| mean\|Fz\| halves | 1.8327e-3 → 3.8456e-3 | same |
| Complete cycles | +208.58 %, +137.17 %, +112.96 %; periods 9.79–10.16 | AUD `cycle_gates.json` |
| Block stats 60–70 vs 70–80 | mean drag Δ 0.0378 %, Fz RMS +109.5 %, max probe mean Δ 0.00175 U_b | AUD `cycle_gates.json` |
| Co max / continuity (last 2 segments) | 0.7911, 0.7915 / 1.52e-12, 2.02e-12 | re-grepped from `CFD_Verification_Package_20260929/03_cube/logs/log.foamRun.t60_to_t70`, `t70_to_t80` |
| Flux imbalance at 80 | 3.23e-11 | AUD `FINAL_ASSESSMENT.md` §3 |
| Mesh | 567,360 cells; AR 18.42; non-orth 0; skew 1.8e-13 | `03_cube/logs/log.checkMesh.retry2` |
| y+ at t* = 80 | median 24.70, range 2.76–96.46, 67.15 % area < 30 | recomputed from AUD `cube_wall_t80.csv` |
| BC types | walls noSlip + kqR/omega/nutUSpalding; inlet mapped from precursor 3000 | `recovery_evidence/sst/cube_pilot/initial_BC_audit.json`, `mapping.json` |
| Model calls | none (the "archived diagnosis" label is not an LLM call) | `evidence/cube/drifting_wake/diagnostics/llm_trace.json` |
| ERCOFTAC RMSE | 0.34–0.68 U_b | AUD `FINAL_ASSESSMENT.md` §10 |

## Step decision points (Table 4)
- Mach 3 iterative run (`case_H_iterative_short_run/events.log`): t = 2 healthy, target 4 → Gemini EXTEND_END_TIME (approved) → t = 4 PASS.
- Mach 3, h = 0.3 (`case_F_step030/events.log`): `compression_front_measurable` failed → Gemini FAIL_SAFELY (approved) → FAIL.

## Nozzle reference campaign (repo `validation/canonical_reference/results/`)
| Mesh | Cells | Throat M | Exit M | Exit p (Pa) | ṁ |
|---|---|---|---|---|---|
| mesh1 | 2,112 | 1.02904 | 1.51325 | 53,142.7 | 1.54092 (bit-identical to the agent's canonical run, 30,471 steps) |
| mesh2 | 4,752 | 1.04319 | 1.51889 | 52,775.0 | 1.53781 |
| mesh3 | 8,448 | 1.05117 | 1.52213 | 52,565.9 | 1.53606 |
| mesh4 | 13,200 | 1.05553 | 1.52439 | 52,425.2 | 1.53491 (theory exit-p error −3.157 %) |
Last-pair changes (`study.json`): throat M 0.4147 %, exit p 0.2677 %, exit M 0.1481 %, ṁ 0.0743 %; controls max 0.0358 % (startup, throat M).

## Step mesh-sensitivity refusal (`case_I_mesh_sensitivity/events.log`)
4,032 cells → Gemini REFINE_MESH (approved, ×2 linear) → 16,128 cells → Gemini ACCEPT → **refused** (SENSITIVITY_CRITERION_NOT_REGISTERED) → case library `STOPPED_ACTION_REFUSED` / REJECT.
