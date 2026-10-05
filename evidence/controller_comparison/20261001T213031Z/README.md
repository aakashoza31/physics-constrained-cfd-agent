# Controller comparison run 20261001T213031Z

Records of the controller comparison reported in the CFD Forge paper (Sec.
"Controller Comparison", table `tab:controller`). The run was executed on
1 October 2026 (UTC stamp `20261001T213031Z`) by
`paper/cfd_forge/scripts/controller_comparison.py` with `gemini-3.5-flash-lite`
at temperature 0, `--repeats 5 --fault-repeats 3`. No CFD was run: every decision
point is an archived evidence record (or a planted fault applied to one), decided
by four controllers:

| Arm (records) | Controller |
|---|---|
| `A_fixed_rule` | A: the family recipe maps the deterministic validator's outcome to an action; no model call |
| `B_cfd_forge` | B: the archived agent diagnosis call proposes an action on the full evidence packet; the action gate and validator decide |
| `B_gates_off` | B': the same B proposal taken directly as the verdict; derived from the B records (`decision_gates_off`, `gates_off_*`), no extra call |
| `C_llm_only` | C: the model returns a verdict from the evidence packet with the deterministic check outcomes removed (`meta.blind_keys_removed`); no validator |

The files are kept exactly as written by the script; this README is the only
added file.

## Files

### `summary.json`

- `meta`: `model`, `repeats` (5, archived and defect points), `fault_repeats` (3),
  `dry_run` (false), `demo_root` (archive location the points were read from),
  `utc`, `llm_only_system_sha256` (SHA-256 of the stripped arm-C system
  instruction; it matches `LLM_ONLY_SYSTEM` in the current script), and
  `blind_keys_removed` (keys deleted from the arm-C packet).
- `summary.<group>.<arm>` for the groups `archived`, `defect` and `fault`:
  `points`, `n_decisions`, `correct`, `false_accept`, `missed_accept`,
  `unneeded_rerun`; for arm B also `proposals_refused` and
  `points_unanimous_across_repeats` (same diagnosis and action in every repeat),
  for arm C `points_unanimous_across_repeats` (same verdict).
- `summary.errors` (4), `summary.llm_calls_recorded` (284),
  `summary.latency_median_s` (1.269), `summary.tokens_total` (1,099,390),
  `summary.tokens_mean_per_call`.

### `summary.md`

The same counts as Markdown tables, one per group. The paper's table reports
`correct/n_decisions (false_accept)` for arms A, B, B' and C.

### `records.jsonl`

One JSON object per decision (324 lines: 36 arm-A, 144 arm-B and 144 arm-C rows,
of which 4 are errors).

- Common: `point` (decision-point id, see below), `group` (`archived`, `defect`,
  `fault`), `family`, `label`, `source` (archived iteration directory, relative
  to `demo/` in the Zenodo archive; for faults `<source> + <fault name>`),
  `truth` (reference decision: `ACCEPT`, `CORRECT_AND_RERUN`, `REJECT`, or
  `NOT_ACCEPT` when any non-accepting decision is correct), `validator_status`
  (status from the current validator), `arm`, `repeat` (0 for arm A).
- Scoring: `decision`, `match`, `false_accept`, `missed_accept`, `unneeded_rerun`.
- Arm A: `action`.
- Arm B: `diagnosis`, `action`, `confidence`, `approved` (action-gate ruling),
  `refusal` (gate reasons when refused), `reasoning` (first 400 characters of the
  model's summary), and the B' fields `decision_gates_off`, `gates_off_match`,
  `gates_off_false_accept`, `gates_off_missed_accept`, `gates_off_unneeded_rerun`.
- Arm C: `verdict` (`ACCEPT`, `NEEDS_MORE_RUNTIME`, `REJECT`, `INCONCLUSIVE`),
  `reasoning`.
- Failed calls: `error` (exception text, truncated) and, for arm B, `trace`.
  The `CUBE` rows omit `label`, `source` and `validator_status`.

### `calls.jsonl`

One line per successful model call (284): `point`, `arm` (`B` or `C`), `repeat`,
`latency_s`, `model`, `prompt_tokens`, `output_tokens`, `total_tokens`. Failed
calls are not in this file; they appear in `records.jsonl` with an `error` field.

## Failed calls

288 calls were attempted and 284 succeeded. All four failures are recorded in
`records.jsonl` as `429 RESOURCE_EXHAUSTED` quota errors from the provider:

| Point | Arm | Repeat |
|---|---|---|
| S2 | C | 3 |
| S5 | B | 3 |
| F11 | B | 3 |
| F12 | C | 1 |

These decisions are excluded from the counts.

## Prompts

- Arm C: `LLM_ONLY_SYSTEM`, the family notes (`FAMILY_NOTES`) and the blinded keys
  (`BLIND_KEYS`) are in `paper/cfd_forge/scripts/controller_comparison.py`.
- Arm B uses the archived agent prompts: the forward-step diagnosis
  (`SYSTEM_PROMPT` in `src/reasoning/forward_step_diagnosis.py`) and the nozzle
  diagnosis (`src/reasoning/nozzle_diagnosis.py` -> `src/agents/theory_blind_cfd_agent.py`,
  whose system instruction embeds `configs/cfd_reasoning_policy_v2.yaml`). For the
  cube point, arm B uses `SYSTEM` in `paper/cfd_forge/scripts/cube_llm_diagnosis.py`.

## Decision points and the paper's session ledger

The comparison ids are defined in `STEP_POINTS`, `NOZZLE_POINTS`, `load_points`
(faults) and `run_cube` of the script. They are **not** the ledger numbers of the
paper's appendix (S1-S8, N1-N8): for example comparison point `S1` is ledger
session S2, and comparison point `N4` is a state of ledger session N6.

| Point | Group | Archived source (`demo/...`) | Paper ledger session |
|---|---|---|---|
| S1 | archived | `forward_step_2d/case_B_mach20/iteration_01` | S2 (Mach 2, h=0.2) |
| S2 | archived | `forward_step_2d/case_C_mach35/iteration_01` | S3 (Mach 3.5) |
| S3 | archived | `forward_step_2d/case_E_step010/iteration_01` | S4 (Mach 3, h=0.1) |
| S4 | archived | `forward_step_2d/case_F_step030/iteration_01` | S5 (Mach 3, h=0.3, x=0.6) |
| S5 | archived | `forward_step_2d/case_G_step030_x100/iteration_01` | S6 (Mach 3, h=0.3, x=1.0) |
| S6 | archived | `forward_step_2d/case_H_iterative_short_run/iteration_01` | S7, state at t=0.5 |
| S7 | archived | `forward_step_2d/case_H_iterative_short_run/iteration_02` | S7, state at t=1 |
| S8 | archived | `forward_step_2d/case_H_iterative_short_run/iteration_05` | S7, state at t=2 |
| S9 | archived | `forward_step_2d/case_H_iterative_short_run/iteration_07` | S7, final state |
| D1 | defect | `forward_step_2d/live_run_01/iteration_01` | S1 (false-positive fatal-error flag) |
| D2 | defect | `forward_step_2d/case_H_iterative_short_run/iteration_04` | S7, state failed by the pre-fix restart-seam closure |
| N1 | archived | `nozzle_e2e/case_A_reference` | N1 |
| N2 | archived | `nozzle_e2e/case_B_geometry` | N2 |
| N3 | archived | `nozzle_e2e/case_C_conditions` | N3 |
| N4 | archived | `nozzle_feedback_v2_hotfix/case_A_reference/iterations/iteration_01` | N6, state at 1 ms |
| N5 | archived | `nozzle_feedback_v2_hotfix/case_A_reference/iterations/iteration_02` | N6, continued to 6 ms |
| N6 | archived | `nozzle_feedback/case_A_reference/iterations/iteration_02` | N4, early continuation with time-accounting and flux-consistency failures |
| CUBE | archived | cube force history and logs (`paper/cfd_forge/scripts/cube_llm_diagnosis.py`) | cube diagnostic study (run outside the agent loop; not a ledger session) |
| F01-F18 | fault | point S1's evidence with one planted fault (`src/eval/faults.py`; the name is in `label`) | none: planted faults on the ledger S2 state |

The archived sessions are in the Zenodo archive (https://doi.org/10.5281/zenodo.23148676)
under `demo/`.
