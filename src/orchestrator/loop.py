#!/usr/bin/env python3
"""The shared orchestrator: the decision core every registered family uses.

The paper's controller comparison calls decide_once for arms A, B and B'
(paper/cfd_forge/scripts/controller_comparison.py); its arm C is implemented
in that script. The agent sessions reported in the paper ran through the
family runners (scripts/run_nozzle_feedback.py, scripts/run_nozzle_e2e.py,
scripts/run_forward_step_2d.py), not through run_loop.

Two entry points, deliberately separated:

    decide_once(...)   The pure decision core. Takes evidence that already
                       exists and returns the deterministic ruling and
                       decision. Touches no filesystem and runs no CFD, so
                       parity tests, the gates-off ablation, the no-diagnosis
                       ablation and fault injection all exercise exactly the
                       code the real system uses, for free.

    run_loop(...)      Wraps decide_once with build / run / collect. This is
                       the only place CFD is launched.

The authority split is enforced structurally: the LLM's Proposal is advisory
and is passed to the family's deterministic validator, which returns the
ActionRuling. In GATES_OFF mode the ruling is still computed and recorded --
so the ablation measures what the gates WOULD have caught -- but the decision
is taken from the LLM instead.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.families.base import (
    ACCEPT,
    CORRECT_AND_RERUN,
    CRITERION_NOT_REGISTERED,
    INCONCLUSIVE,
    REJECT,
    ActionRuling,
    Decision,
    Outcome,
    Proposal,
    validate_evidence_shape,
)
from src.orchestrator import modes as modes_mod
from src.orchestrator.ledger import Ledger


@dataclass(frozen=True)
class StepResult:
    """One diagnose -> propose -> rule -> validate cycle."""

    decision: Decision
    proposal: Proposal
    ruling: ActionRuling
    validation: Dict[str, Any]
    reasons: List[str]
    unresolved_criteria: List[str]
    next_spec: Optional[Any] = None

    @property
    def terminal(self) -> bool:
        return self.decision != CORRECT_AND_RERUN


def _recipe_of(adapter: Any) -> Any:
    return getattr(adapter, "recipe", None)


def _unresolved_of(adapter: Any) -> List[str]:
    recipe = _recipe_of(adapter)
    if recipe is None:
        return []
    return list(recipe.unresolved())


# ----------------------------------------------------------------------
def decide_once(
    adapter: Any,
    spec: Any,
    evidence: Dict[str, Any],
    *,
    mode: Any = modes_mod.FULL,
    ledger: Optional[Ledger] = None,
    iterations_used: int = 0,
    **ruling_kw: Any,
) -> StepResult:
    """Run one decision cycle on evidence that already exists. No CFD."""
    if isinstance(mode, str):
        mode = modes_mod.resolve(mode)
    ledger = ledger or Ledger()

    missing = validate_evidence_shape(evidence)
    if missing:
        ledger.record("evidence", {"missing_sections": missing}, ok=False)
    else:
        ledger.record("evidence", {"sections": sorted(evidence)}, ok=True)

    # --- 1. proposal (advisory) ----------------------------------------
    if mode.use_llm_diagnosis:
        proposal, llm_record = adapter.diagnose(evidence, spec)
        ledger.record("llm_call", llm_record)
        ledger.record("diagnosis", proposal, source="llm")
    else:
        proposal = adapter.deterministic_proposal(evidence, spec)
        ledger.record("diagnosis", proposal, source="recipe")
    ledger.record("proposed_action", {"action": proposal.action,
                                      "region_hint": proposal.region_hint})

    # --- 2. deterministic validation of the result ---------------------
    validation = adapter.validate(evidence, spec)
    ledger.record("validation", validation)

    # --- 3. deterministic ruling on the proposed action ---------------
    # Computed in EVERY mode, including gates_off, so the ablation can report
    # what the gates would have refused.
    if mode.allow_corrective_actions:
        ruling = adapter.execute_action(
            proposal.action,
            spec,
            evidence,
            validation=validation,
            proposal=proposal,
            iterations_used=iterations_used,
            max_iterations=mode.max_iterations,
            **ruling_kw,
        )
    else:
        ruling = ActionRuling(
            False,
            proposal.action,
            ["corrective actions are disabled in this mode"],
        )
    ledger.record("deterministic_ruling", ruling,
                  authoritative=mode.gates_authoritative)

    # --- 4. decision --------------------------------------------------
    unresolved = _unresolved_of(adapter)
    recipe = _recipe_of(adapter)
    if recipe is not None and recipe.unresolved_capabilities():
        ledger.record(
            "deterministic_ruling",
            {"blocked_capabilities": recipe.unresolved_capabilities()},
            authoritative=True,
        )
    reasons: List[str] = []

    if not mode.gates_authoritative:
        # GATES_OFF: take the LLM at its word. This is the ablation.
        decision = _llm_decision(proposal)
        reasons.append(
            "gates_off: decision taken from the LLM proposal; the deterministic "
            "ruling was computed and recorded but not applied"
        )
    else:
        decision = adapter.maps_to_decision(validation)
        reasons.extend(validation.get("failed_checks", []) or [])

        if decision == ACCEPT and unresolved:
            decision = INCONCLUSIVE
            reasons.insert(
                0,
                f"{CRITERION_NOT_REGISTERED}: "
                + ", ".join(unresolved),
            )
        if decision == CORRECT_AND_RERUN and not (
            mode.allow_corrective_actions and ruling.approved
        ):
            decision = INCONCLUSIVE
            reasons.append(
                "a corrective action was indicated but not approved: "
                + "; ".join(ruling.reasons)
            )

    next_spec = ruling.corrected_spec if (
        mode.gates_authoritative and ruling.approved and decision == CORRECT_AND_RERUN
    ) else None

    ledger.record(
        "final_decision" if decision != CORRECT_AND_RERUN else "case_change",
        {"decision": decision, "reasons": reasons[:8]},
    )

    return StepResult(
        decision=decision,
        proposal=proposal,
        ruling=ruling,
        validation=validation,
        reasons=reasons,
        unresolved_criteria=unresolved,
        next_spec=next_spec,
    )


def _llm_decision(proposal: Proposal) -> Decision:
    """How the gates-off ablation reads an LLM proposal as a verdict."""
    action = (proposal.action or "").upper()
    if action == "ACCEPT":
        return ACCEPT
    if action in {"REJECT", "REJECT_UNSUPPORTED"}:
        return REJECT
    if action in {"REQUEST_CLARIFICATION", "FAIL_SAFELY", "INCONCLUSIVE"}:
        return INCONCLUSIVE
    return CORRECT_AND_RERUN


# ----------------------------------------------------------------------
def run_loop(
    adapter: Any,
    spec: Any,
    workdir: Path,
    *,
    mode: Any = modes_mod.FULL,
    ledger: Optional[Ledger] = None,
    max_iterations: Optional[int] = None,
    evidence_hook: Optional[Any] = None,
) -> Outcome:
    """Build, run, collect and decide, iterating while corrections are approved.

    ``evidence_hook(evidence, iteration) -> evidence`` is the fault-injection
    seam: src/eval/faults.py uses it to corrupt evidence between collection and
    diagnosis without touching this loop.
    """
    if isinstance(mode, str):
        mode = modes_mod.resolve(mode)
    ledger = ledger or Ledger(mode=mode.name)
    workdir = Path(workdir)
    cap = max_iterations or mode.max_iterations

    ledger.record("run_start", {"family": adapter.name, "mode": mode.name,
                                "max_iterations": cap})

    scope = adapter.check_scope(spec)
    ledger.record("scope_gate", scope)
    if not scope.approved:
        outcome = Outcome(REJECT, adapter.name, list(scope.reasons))
        ledger.record("run_end", outcome)
        return outcome

    iteration = 0
    step: Optional[StepResult] = None
    while iteration < cap:
        iteration += 1
        case_out = workdir / f"iteration_{iteration:02d}"
        case_out.mkdir(parents=True, exist_ok=True)

        case = adapter.build_case(spec, case_out / "case")
        ledger.record("case_build", {"iteration": iteration, "case": str(case)})

        rc = adapter.run_case(case, append=iteration > 1)
        ledger.record("solver_execution", {"iteration": iteration, "returncode": rc})

        evidence = adapter.collect_evidence(case, case_out)
        if evidence_hook is not None:
            evidence = evidence_hook(evidence, iteration)
            ledger.record("fault_injection", {"iteration": iteration, "applied": True})

        step = decide_once(
            adapter, spec, evidence, mode=mode, ledger=ledger,
            iterations_used=iteration,
        )
        adapter.summarize(spec=spec, evidence=evidence,
                          validation=step.validation, out=case_out)

        if step.terminal:
            break
        if step.next_spec is None:
            break
        spec = step.next_spec

    if step is None:  # pragma: no cover - cap<1 is a caller error
        outcome = Outcome(INCONCLUSIVE, adapter.name, ["no iteration ran"])
    else:
        outcome = Outcome(
            step.decision, adapter.name, step.reasons, step.validation,
            iteration, step.unresolved_criteria,
        )
    ledger.record("run_end", outcome)
    return outcome
