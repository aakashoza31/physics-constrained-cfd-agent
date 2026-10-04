# Evaluation

## The paper's controller comparison

The controller comparison reported in the CFD Forge paper (Sec. "Controller
Comparison") is produced by
[`paper/cfd_forge/scripts/controller_comparison.py`](../paper/cfd_forge/scripts/controller_comparison.py),
and its archived run is
[`evidence/controller_comparison/20261001T213031Z/`](../evidence/controller_comparison/20261001T213031Z/)
(`summary.md`, `summary.json`, per-decision `records.jsonl`, per-call
`calls.jsonl`). It compares four controllers on archived, planted-fault and
defect decision points: (A) fixed rule, (B) CFD Forge, (B') gates off and
(C) model only on a filtered packet. See the top-level
[`README.md`](../README.md#controller-comparison) and
[`docs/results.md`](../docs/results.md) for the headline numbers and how to
rerun it.

## Legacy replay harness (`scripts/run_evaluation.py`)

`scripts/run_evaluation.py` is a separate, older replay harness over the
registered cases in `cases/`. It is **not** the paper's controller comparison
and none of the paper's numbers come from it. Its four arms are defined in
`src/evaluation/metrics.py`:

| Arm | Description |
|---|---|
| `full_agent` | interpretation, routing, diagnosis, bounded correction, all gates |
| `fixed_recipe_fixed_rules` | no LLM: the family recipe drives everything |
| `agent_without_deterministic_gates` | the model's diagnosis is allowed to decide |
| `gates_without_diagnosis_or_repair` | gates only; no correction loop |

The orchestrator modes it relies on are in `src/orchestrator/modes.py`
(`full_constrained_agent`, `parameterized_recipe_baseline`, `gates_off`,
`no_diagnosis_loop`), and the fault-injection helpers are in
`src/eval/harness.py` and `src/eval/faults.py`.

Metrics: `valid_completion`, `false_acceptance`, `correct_rejection`,
`first_attempt_success`, `corrected_success`, `actions_per_run`,
`solver_attempts`, `runtime_seconds`, `human_interventions`, `llm_cost`
(definitions in `src/evaluation/metrics.py`). Ground truth is the registered
`expected_result.json` of each case in `cases/`.

```bash
python scripts/run_evaluation.py --arm full_agent --mode replay
python scripts/run_evaluation.py --summarise
```

Records are written to `evaluation/records/<arm>.jsonl` (git-ignored). For an
arm with no records, `--summarise` prints `NOT_RUN` for every metric rather
than a fabricated zero. No results from this harness are reported in the
repository or the paper.
