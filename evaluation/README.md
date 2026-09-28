# Evaluation

**Status: `NOT_RUN`.** The harness, the arms and the metric definitions exist.
No ablation has been executed, so no number is reported. A metric computed over
zero runs returns `NOT_RUN`, never `0.0`.

## Arms

| Arm | Description |
|---|---|
| `full_agent` | interpretation, routing, diagnosis, bounded correction, all gates |
| `fixed_recipe_fixed_rules` | no LLM: the family recipe drives everything |
| `agent_without_deterministic_gates` | the model's diagnosis is allowed to decide |
| `gates_without_diagnosis_or_repair` | gates only; no correction loop |

The third arm is the one that matters: it measures the false-acceptance rate the
architecture exists to prevent. The existing mode plumbing is in
`src/orchestrator/modes.py` (`full_constrained_agent`,
`parameterized_recipe_baseline`, `gates_off`, `no_diagnosis_loop`) and the fault
injection harness is `src/eval/harness.py` and `src/eval/faults.py`.

## Metrics

`valid_completion`, `false_acceptance`, `correct_rejection`,
`first_attempt_success`, `corrected_success`, `actions_per_run`,
`solver_attempts`, `runtime_seconds`, `human_interventions`, `llm_cost`.
Definitions live in `src/evaluation/metrics.py`.

## Ground truth

The registered `expected_result.json` of each case in `cases/` is the ground
truth. For the cube that is `REJECT`; for the airfoil, `REJECT` with
`CFD_NOT_RUN`. An arm that accepts either has produced a false acceptance.

## Running it (when the runs exist)

```bash
python scripts/run_evaluation.py --arm full_agent --mode replay
python scripts/run_evaluation.py --summarise
```

Until those runs are executed, `--summarise` prints `NOT_RUN` for every arm, and
that is the only honest output.
