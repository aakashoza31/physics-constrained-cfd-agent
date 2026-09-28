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
| `stationarity` | family validators; for F3, `src/families/cube/stationarity.py` |
| `validation` | family validators |
| `permitted_actions` | action validators + `FamilyRecipe.allowed_actions` |
| `final_decision` | `src/authority/boundary.py:final_decision` |

## How it is enforced

`assert_llm_may(activity)` raises `AuthorityViolation` if a model activity names
an authority-owned question. `AuthorityTrace.gate(...)` refuses a question that
is not in `AUTHORITY_DECIDES`; `AuthorityTrace.proposal(...)` refuses an activity
that is not in `LLM_MAY`, and every proposal it stores carries `binding: false`.

`final_decision(trace)` computes the verdict **from the gates alone**:

```
REJECT        if any gate failed
INCONCLUSIVE  if any gate is unresolved, or no gate was evaluated
ACCEPT        only when every registered gate passed
```

No argument to that function can raise a verdict, and a model's diagnosis is not
one of its inputs. A run in which no evidence exists — a dry-run, a refused live
run — leaves the evidence gates unresolved and therefore returns INCONCLUSIVE,
never an accidental ACCEPT.

## What this buys, concretely

The F3 cube case is the demonstration. The archived run completed, reported no
numerical failure, and its drag was settled to 0.08% over the assessment window.
An LLM that had been allowed to conclude would have had every reason to accept
it. The deterministic stationarity gate measured the lateral mode instead and
returned REJECT, because a periodic lateral force whose amplitude is still
growing 68× is not a converged flow.

## What it does not buy

Deterministic authority is only as good as the registered criteria. A family
whose acceptance constants are wrong will accept wrong results confidently. The
gates are visible, versioned and testable precisely so that the argument is about
the criteria rather than about whether a model felt confident.
