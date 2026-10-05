# Evidence map: paper quantity → source

The `data/` paths are verbatim copies; `data/DATA_MANIFEST.json` gives each copy's source and SHA-256.
Source labels:
- repo: this repository.
- archive (Zenodo): the session archive deposited on Zenodo (DOI to be added on release); `demo/` holds the archived agent sessions.
- verification package (Zenodo): `CFD_Verification_Package_20260929/` inside the same Zenodo archive.
- AUD: read-only cube audit output (`audit_t80/`, workstation output, not released); copies of `cycle_gates.json`, `forces_merged.csv` and `cube_wall_t80.csv` are in `data/cube/`.

Abbreviation: E2E = archive (Zenodo): `demo/`.

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
Thresholds: repo `src/pipeline/nozzle/validate.py`, the `checks` dictionary of the validator.

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
| Registered gate | STILL_DEVELOPING; growth ratio 2.0984 (≤1.25); drift fx 0.0753 % (≤2 %); lateral rel. 0.0626 % (≤5 %); window 59.98–79.98, 500 samples | repo `cases/cube/drifting_wake/expected_result.json` (copy: `data/cube/registered_stationarity.json`); **reproduced exactly** by running `stationarity.assess` on `reference/force_history.json` |
| Mean C_D | 2 × 0.70621 = 1.412 | same |
| mean\|Fz\| halves | 1.8327e-3 → 3.8456e-3 | same |
| Complete cycles | +208.58 %, +137.17 %, +112.96 %; periods 9.79–10.16 | AUD `cycle_gates.json` |
| Block stats 60–70 vs 70–80 | mean drag Δ 0.0378 %, Fz RMS +109.5 %, max probe mean Δ 0.00175 U_b | AUD `cycle_gates.json` |
| Co max / continuity (last 2 segments) | 0.7911, 0.7915 / 1.52e-12, 2.02e-12 | re-grepped from verification package (Zenodo): `03_cube/logs/log.foamRun.t60_to_t70`, `t70_to_t80` |
| Flux imbalance at 80 | 3.23e-11 | AUD `FINAL_ASSESSMENT.md` §3 |
| Mesh | 567,360 cells; AR 18.42; non-orth 0; skew 1.8e-13 | verification package (Zenodo): `03_cube/logs/log.checkMesh.retry2` (copy: `data/cube/log.checkMesh`) |
| y+ at t* = 80 | median 24.70, range 2.76–96.46, 67.15 % area < 30 | recomputed from AUD `cube_wall_t80.csv` |
| BC types | walls noSlip + kqR/omega/nutUSpalding; inlet mapped from precursor 3000 | `data/cube/initial_BC_audit.json`, `data/cube/mapping.json` (cube pilot recovery evidence, workstation output) |
| Model calls | 3 × gemini-3.5-flash-lite, 1 Oct 2026, outside the agent loop: STILL_DEVELOPING → CONTINUE_RUN, NUMERICALLY_UNHEALTHY → FAIL_SAFELY, STILL_DEVELOPING → CONTINUE_RUN; all three approved by the action validator, none executed, never ACCEPT; latency 2.5 / 2.2 / 1.7 s; tokens 4,805 / 4,709 / 4,764 | repo `evidence/cube/drifting_wake/llm_diagnosis/20261001T154401Z_run01.json`–`run03.json` (`decision`, `action_validation`, `latency_s`, `usage.total_token_count`), `20261001T154401Z_summary.json`, packet `20261001T154401Z_packet.json`; script `scripts/cube_llm_diagnosis.py`. (`evidence/cube/drifting_wake/diagnostics/llm_trace.json`, regenerated by replay, lists the deterministic request interpreter and these three archived model calls.) |
| ERCOFTAC RMSE | 0.34–0.68 U_b | AUD `FINAL_ASSESSMENT.md` §10 |

## Step decision points (representative decision points, `tab:actions`)
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
4,032 cells → Gemini REFINE_MESH (approved, ×2 linear) → 16,128 cells → Gemini ACCEPT → **refused** (SENSITIVITY_CRITERION_NOT_REGISTERED) → session status `STOPPED_ACTION_REFUSED` → decision **INCONCLUSIVE** (ledger S8; E2E `forward_step_2d/case_I_mesh_sensitivity/agent_result.json`, `MESH_SENSITIVITY.json`). Both iterations passed the deterministic step checks; acceptance was withheld because no cross-grid tolerance is registered.

## Agent call statistics (Sec. "Agent results", Fig. `fig:agent_stats`, Fig. `fig_agent_loop`)
Counted by `scripts/recount_agent_calls.py --demo <E2E>` from every call record of the nozzle and 2-D step sessions, deduplicated per run by (stage, latency); stored in `data/agent_stats.json`.
| Quantity | Value | Key |
|---|---|---|
| Sessions / runs / distinct requests | 19 (8 nozzle, 11 step) / 16 / 11 | `n_sessions`, `sessions`, `n_runs`, `n_distinct_requests` |
| Model calls by stage | 16 interpretation, 8 mesh review, 28 diagnosis, 23 field observation (5 failed, HTTP 503 UNAVAILABLE), 22 summary; 97 in total | `model_calls_by_stage`, `field_observation_failures` |
| Text calls | 74, all succeeded on the first attempt | `text_calls_first_attempt_success` |
| Median latency | interpretation 4.92 s, diagnosis 2.90 s, summary 2.81 s, mesh review 1.94 s | `latency_median_s_by_stage` |
| Proposals | 28: 14 ACCEPT, 5 CONTINUE_RUN, 4 EXTEND_END_TIME, 3 FAIL_SAFELY, 1 REFINE_MESH, 1 REQUEST_DIAGNOSTIC | `proposals_by_action` |
| Rulings | 25 approved, 3 refused (ACCEPT in S8, CONTINUE_RUN and EXTEND_END_TIME in S7) | `rulings` |
| Unrecorded repair call | N4, iteration 2: one refused proposal and its repair call were not recorded and are not counted | disclosed in the paper; not in the call records |
| Per-session counts (additive, 74 text calls) | see `data/session_ledger.json` (`n_json_calls`, `by_stage`; raw per-folder counts in `*_all_records`) | made additive by repo `scripts/reconcile_session_ledger.py` |
The older event-stream count (`scripts/scan_agent_sessions.py`, 82 calls / 23 proposals) is superseded.

## Session ledger (Appendix, Table `tab:ledger`)
`data/session_ledger.json`, one entry per session folder of E2E. `status`, `validation_status`, `status_source`, the chronological `proposals`, `ledger_id` and `paper_decision` are recomputed from the archive by `scripts/ledger_statuses.py --demo <E2E>`:
| Ledger | Session | Status (source) | Validator | Decision |
|---|---|---|---|---|
| N1–N3 | `nozzle_e2e/case_{A,B,C}_*` | ACCEPTED (`case_result.json`) | PASS_SINGLE_MESH | ACCEPT |
| N4 | `nozzle_feedback/case_A_reference` | UNEXECUTED_ACTION_REQUEST_DIAGNOSTIC (`feedback_summary.json`) | FAIL | not accepted |
| N5 | `nozzle_feedback_v2/case_A_reference` | ERROR, session ended before the continuation (`nozzle_feedback_v2/FEEDBACK_CAMPAIGN_SUMMARY.json`) | FAIL (1 ms) | not accepted |
| N6 | `nozzle_feedback_v2_hotfix/case_A_reference` | ACCEPTED (`feedback_summary.json`); proposals CONTINUE_RUN, CONTINUE_RUN, ACCEPT | PASS_SINGLE_MESH | ACCEPT |
| N7, N8 | `nozzle_feedback_final/case_{B,C}_*` | ACCEPTED (`feedback_summary.json`) | PASS_SINGLE_MESH | ACCEPT |
| S1 | `forward_step_2d/live_run_01` | STOPPED_FAIL_SAFELY (`agent_result.json`) | FAIL (false-positive fatal-error check; `REANALYSIS.json`: PASS_2D_FORWARD_STEP) | REJECT |
| S2–S4, S6 | `case_B_mach20`, `case_C_mach35`, `case_E_step010`, `case_G_step030_x100` | ACCEPTED | PASS_2D_FORWARD_STEP | ACCEPT |
| S5 | `case_F_step030` | STOPPED_FAIL_SAFELY | FAIL | REJECT |
| S7 | `case_H_iterative_short_run` (+ 3 earlier sessions under `history/`) | ACCEPTED; 7 proposals in iteration order | PASS_2D_FORWARD_STEP | ACCEPT (after supervised resumption) |
| S8 | `case_I_mesh_sensitivity` | STOPPED_ACTION_REFUSED | PASS_2D_FORWARD_STEP | INCONCLUSIVE |
In the nozzle feedback campaigns `case_result.json` records only the initial 1 ms stage (REJECTED_BY_VALIDATOR) and is not the final session status.

## Controller comparison (Sec. `sec:controller`, Table `tab:controller`)
Run `20261001T213031Z`, repo `evidence/controller_comparison/20261001T213031Z/` (`summary.json`, per-call `calls.jsonl`, per-decision `records.jsonl`); script `scripts/controller_comparison.py`.
| Quantity | Value | Key in `summary.json` |
|---|---|---|
| Model / repeats | gemini-3.5-flash-lite; 5 per archived and defect point, 3 per fault | `meta.model`, `meta.repeats`, `meta.fault_repeats` |
| Calls | 288 attempted, 284 succeeded, 4 failed (429 RESOURCE_EXHAUSTED) | `summary.llm_calls_recorded`, `summary.errors` |
| Tokens / median latency | 1,099,390 / 1.269 s | `summary.tokens_total`, `summary.latency_median_s` |
| Archived (16 points) | A 16/16 (0), B 79/79 (0), B′ 74/79 (0), C 72/79 (7) | `summary.archived.<arm>.correct`, `n_decisions`, `false_accept` |
| Planted faults (18) | A 18/18 (0), B 53/53 (0), B′ 53/53 (0), C 3/53 (50) | `summary.fault.<arm>` |
| Defects (2) | A 0/2 (0), B 0/10 (0), B′ 0/10 (0), C 5/10 (0) | `summary.defect.<arm>` |
| Repeat consistency (B) | 16/16 archived points, 13/18 faults unanimous; 2 proposals refused by the action gate (faults) | `points_unanimous_across_repeats`, `proposals_refused` |
| Blinded keys (arm C) | 20 keys removed from the packet | `meta.blind_keys_removed` |
Arms: A = `A_fixed_rule`, B = `B_cfd_forge`, B′ = `B_gates_off`, C = `C_llm_only`.

## New cases within the registered families (Sec. `sec:variants`, Table `tab:variants`)
Nozzle rows (t = 6 ms), from E2E `nozzle_e2e/case_A_reference`, `case_B_geometry`, `case_C_conditions` `/validation.json` (keys `final.outlet_M`, `final.outlet_p`, `final.outlet_mdot`, `theory_error_pct`, `status`, `checks`); the repeat sessions `nozzle_feedback_final/case_B_geometry`, `case_C_conditions` give identical values.
| Request | Exit M | Exit p (Pa) | ṁ (kg s⁻¹) | Theory error M / p / ṁ | Status |
|---|---|---|---|---|---|
| Reference (r_e = 35.4 mm, p₀ = 200 kPa) | 1.5133 | 53,142.7 | 1.54092 | +0.588 / −1.831 / −1.111 % | PASS_SINGLE_MESH, 20/20 |
| r_e = 37.0 mm | 1.6517 | 43,294.9 | 1.54106 | +0.385 / −1.569 / −1.102 % | PASS_SINGLE_MESH, 20/20 |
| p₀ = 220 kPa | 1.5131 | 58,459.5 | 1.69495 | +0.578 / −1.827 / −1.115 % | PASS_SINGLE_MESH, 20/20 |

Step rows (t = 4), from E2E `forward_step_2d/<case>/iteration_NN/` of the last iteration: front x = last row of `shock_front_history.csv` (`lower_front_x`), p rise = `validation.json` `shock.jumps.p`, mass closure = `diagnostics.json` `mass.relative_residual_max`; normal-shock ratio and post-shock A*/A from the standard relations (γ = 1.4).
| (M, h, x_s) | Case | Front x | p rise | Closure max | Status |
|---|---|---|---|---|---|
| 2.0, 0.20, 0.6 | `case_B_mach20/iteration_01` | 0.1125 | 5.184 | 5.67e-11 | PASS_2D_FORWARD_STEP |
| 2.5, 0.15, 0.6 | `live_run_01/iteration_01` | 0.3406 | 7.492 | 3.86e-11 | FAIL (no_fatal_error false positive); `live_run_01/REANALYSIS.json`: PASS_2D_FORWARD_STEP |
| 3.0, 0.10, 0.6 | `case_E_step010/iteration_01` | 0.4500 | 11.109 | 3.36e-11 | PASS_2D_FORWARD_STEP |
| 3.0, 0.20, 0.6 | `case_H_iterative_short_run/iteration_07` | 0.3125 | 10.820 | 4.27e-11 | PASS_2D_FORWARD_STEP |
| 3.0, 0.30, 0.6 | `case_F_step030/iteration_01` | 0.0250 | not measurable | 5.02e-11 | FAIL (compression_front_measurable) |
| 3.0, 0.30, 1.0 | `case_G_step030_x100/iteration_01` | 0.4250 | 11.001 | 5.40e-11 | PASS_2D_FORWARD_STEP |
| 3.5, 0.20, 0.6 | `case_C_mach35/iteration_01` | 0.3375 | 14.757 | 3.69e-11 | PASS_2D_FORWARD_STEP |
The 3-case nozzle campaign summary is also in E2E `published_campaign/`.
