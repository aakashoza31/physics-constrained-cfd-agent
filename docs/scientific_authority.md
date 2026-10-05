# Scientific authority

The system's safety argument is one sentence: **the language model proposes,
deterministic code decides.** This page says exactly where the line falls, and
where that line is enforced in code.

## The two sets

`src/authority/boundary.py` declares both, and they do not overlap.

A language model **may**:

| Activity | Where |
|---|---|
| `interpret_user_intent` | `src/agent/interpret.py` |
| `propose_family_route` | `src/agent/pipeline.py` |
| `diagnose_evidence` | family diagnosis prompts |
| `propose_bounded_action` | family action vocabularies |
| `explain_result` | report narrative |
| `draft_narrative` | report narrative |

Only deterministic code **decides**:

| Question | Decided in |
|---|---|
| `family_compatibility` | `src/geometry/matching.py` |
| `geometry_admissibility` | `src/geometry/matching.py` |
| `mesh_quality` | family mesh checkers (e.g. `src/pipeline/airfoil/mesh_checks.py`) |
| `physical_model` | family recipe (`src/families/recipe.py`) |
| `boundary_condition_consistency` | family builders |
| `numerical_health` | family diagnostics |
| `conservation` | family diagnostics |
| `convergence` | family validators |
| `stationarity` | family validators; for the cube diagnostic study, `src/families/cube/stationarity.py` |
| `validation` | family validators |
| `permitted_actions` | action validators (`src/reasoning/action_validator.py` for the nozzle, `src/reasoning/forward_step_actions.py` for the step) + `FamilyRecipe.allowed_actions` |
| `final_decision` | `src/authority/boundary.py:final_decision` |

## The four decisions

The deterministic layer returns one of four decisions (paper Sec. 2.2). The
model never writes the binding verdict: a model `ACCEPT` is an action proposal,
which the validators may refuse.

| Decision | When |
|---|---|
| `ACCEPT` | every registered check of the family passes, and every criterion the request depends on is registered |
| `CORRECT_AND_RERUN` (not terminal) | the solution is healthy but incomplete (not yet stationary, short of the registered horizon, or insufficiently resolved), and an approved corrective action is executed before reassessment |
| `REJECT` | a registered criterion is violated by a solution that is not merely incomplete (numerical failure, boundary anomaly, request outside the family envelope), or a development test still fails when no permitted correction remains |
| `INCONCLUSIVE` | the assessment cannot be settled: a criterion the request depends on is not registered, a needed action was refused or not executed, or the evidence is insufficient or anomalous |

Insufficient development is not in itself a rejection: while a permitted
continuation exists it leads to `CORRECT_AND_RERUN`. A refused action is also
distinct from a rejected solution: the action validator rules on the model's
proposal, and the scientific validator rules on the result.

The archived campaigns record family-specific status strings, which map to these
decisions: `PASS_SINGLE_MESH` and `PASS_2D_FORWARD_STEP` → `ACCEPT`; `FAIL`
with an approved continuation → `CORRECT_AND_RERUN`; `FAIL` at the end of a run
(for example `STOPPED_FAIL_SAFELY` with no measurable front) → `REJECT`;
`STOPPED_ACTION_REFUSED` → `INCONCLUSIVE`; a session that ended before an
approved action was executed (for example
`UNEXECUTED_ACTION_REQUEST_DIAGNOSTIC`) → not accepted. The session ledger in the
paper's appendix and `paper/cfd_forge/data/session_ledger.json` give the mapping
per session.

## How it is enforced

Two code paths implement the split.

**Orchestrator.** `src/orchestrator/loop.py` (`decide_once`) passes the model's
proposal to the family's deterministic action validator and the evidence to the
family's scientific validator. It returns all four decisions, including the
non-terminal `CORRECT_AND_RERUN`; an `ACCEPT` that depends on an unregistered
criterion becomes `INCONCLUSIVE`, and a `CORRECT_AND_RERUN` whose action was not
approved becomes `INCONCLUSIVE`. The paper's agent runs used the family runners
(`scripts/run_nozzle_e2e.py`, `scripts/run_nozzle_feedback.py`,
`scripts/run_forward_step_2d.py`) with their own action and scientific
validators. The orchestrator applies the family validators to archived
evidence, for example in the controller comparison
(`paper/cfd_forge/scripts/controller_comparison.py`).

**Replay / dry-run trace.** `src/authority/boundary.py` declares the two sets
above and writes the terminal trace used by `scripts/run_demo.py` and
`scripts/run_agent.py` in replay and dry-run mode. `assert_llm_may(activity)`
raises `AuthorityViolation` if a model activity names an authority-owned
question. `AuthorityTrace.gate(...)` refuses a question that is not in
`AUTHORITY_DECIDES`; `AuthorityTrace.proposal(...)` refuses an activity that is
not in `LLM_MAY`, and every proposal it stores carries `binding: false`.

`final_decision(trace)` computes a terminal verdict **from the gates alone**:

```
REJECT        if any gate failed
INCONCLUSIVE  if any gate is unresolved, or no gate was evaluated
ACCEPT        only when every registered gate passed
```

This trace is terminal and has three outcomes; `CORRECT_AND_RERUN` is handled by
the orchestrator, not here. No argument to `final_decision` can raise a verdict,
and a model's diagnosis is not one of its inputs. A run in which no evidence
exists (a dry-run, a refused live run) leaves the evidence gates unresolved and
therefore returns INCONCLUSIVE, never an accidental ACCEPT. Because replay
re-derives the gates from each case's archived record, it leaves the validation
gate unresolved for the refused `ACCEPT` of the step mesh-sensitivity case (S8)
and reports `INCONCLUSIVE`, matching the four decisions above.

## What this buys, concretely

The step mesh-sensitivity request (S8) is the clearest case of the validator
overruling the model: both grids passed their hard checks and the model proposed
`ACCEPT`, which the action validator refused because no cross-grid tolerance is
registered for the step family.

The cube diagnostic study shows the same principle on a different signal. It was
run outside the agent loop, and its stationarity gate (`cube-stationarity/1.0.0`)
was registered retrospectively, after the data existed. The calculation
completed without numerical failure and its mean drag drifted by only 0.075% over
the gate window, yet the half-window mean |Fz| ratio is 2.10 against the
registered limit of 1.25, so the gate returns `STILL_DEVELOPING` and the result
is REJECT. When the agent's diagnosis stage was later applied three times to the
archived evidence, it proposed `CONTINUE_RUN` twice and `FAIL_SAFELY` once and
never `ACCEPT`, so the refusal of an unjustified acceptance was not exercised
there.

## What it does not buy

Deterministic authority is only as good as the registered criteria and the
checks that measure them. A family whose acceptance constants are wrong will
accept wrong results confidently, and a faulty check can stop a healthy run: the
first step session (S1) was rejected by a false-positive fatal-error check and
passes on corrected reanalysis. The
gates are visible, versioned and testable precisely so that the argument is about
the criteria rather than about whether a model felt confident.
