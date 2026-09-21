"""Theory-blind CFD diagnosis step with explicit provenance.

Thin wrapper around the repository's existing reasoning stack:

  src/agents/theory_blind_cfd_agent.diagnose_theory_blind
      builds the theory-blind packet from configs/cfd_reasoning_policy_v2.yaml,
      calls Gemini with a structured schema, and runs the deterministic action
      validator on whatever the model proposes.

Nothing about that behaviour is changed here.  This module adds only:

  - a provenance record stating whether the model or the deterministic fallback
    produced the decision,
  - a deterministic fallback decision derived strictly from the deterministic
    evidence, used only when explicitly allowed.

The action validator runs in both paths, so a fallback decision is policed by
exactly the same deterministic rules as a model decision.
"""
from __future__ import annotations

import time
from typing import Any, Dict, List, Optional, Tuple

from src.agents.llm_provenance import (
    FALLBACK,
    GEMINI,
    LLMCallRecord,
    LLMUnavailable,
    gemini_key_present,
    gemini_model_name,
)
from src.contracts.agent_decision import (
    AgentAction,
    AgentDecision,
    CompetingHypothesis,
    Diagnosis,
)
from src.contracts.cfd_evidence import CFDEvidence
from src.contracts.problem_spec import CFDProblemSpec
from src.reasoning.action_validator import (
    ActionValidationResult,
    validate_agent_action,
)


STAGE = "theory_blind_diagnosis"


def _deterministic_decision(evidence: CFDEvidence) -> AgentDecision:
    """A decision derived only from the deterministic evidence."""
    checks: Dict[str, bool] = {}
    measured = evidence.engineering.measured_outputs or {}

    if isinstance(measured.get("deterministic_checks"), dict):
        checks = dict(measured["deterministic_checks"])

    failed = [name for name, ok in checks.items() if not ok]

    solver_bad = (
        not evidence.solver.completed_normally
        or evidence.solver.nan_detected
        or evidence.solver.inf_detected
        or evidence.solver.solver_error_detected
    )

    admissibility_bad = not (
        evidence.admissibility.pressure_positive
        and evidence.admissibility.temperature_positive
        and evidence.admissibility.density_positive
    )

    evidence_used = [
        "deterministic_checks",
        "conservation.mass_imbalance_percent",
        "stationarity.passes_stationarity",
        "boundaries.boundary_anomaly_detected",
    ]

    if solver_bad or admissibility_bad:
        diagnosis = Diagnosis.NUMERICAL_FAILURE
        action = AgentAction.RESTART_CLEAN
        summary = (
            "Deterministic fallback: solver health or physical admissibility "
            "failed, so the state is not a candidate for acceptance."
        )
    elif failed:
        diagnosis = Diagnosis.UNCONVERGED
        action = AgentAction.CONTINUE_RUN
        summary = (
            "Deterministic fallback: the run is physically admissible but "
            f"{len(failed)} deterministic check(s) did not pass "
            f"({', '.join(failed)}); integration should continue rather than "
            "be accepted."
        )
    else:
        diagnosis = Diagnosis.ACCEPTABLE
        action = AgentAction.ACCEPT
        summary = (
            "Deterministic fallback: every deterministic check passed, so the "
            "state is a candidate for acceptance. Final acceptance authority "
            "remains with the deterministic validator."
        )

    decision = AgentDecision(
        diagnosis=diagnosis,
        evidence_used=evidence_used,
        competing_hypotheses=[
            CompetingHypothesis(
                hypothesis=(
                    "The remaining variation is physical unsteadiness rather "
                    "than incomplete convergence."
                ),
                evidence_for=[
                    "monitor drift and field L2 change over the stationarity "
                    "window"
                ],
                evidence_against=[
                    "declared stationarity criteria are evaluated over that "
                    "same window"
                ],
            )
        ],
        reasoning_summary=summary,
        action=action,
        confidence="medium",
    )

    decision.validate()
    return decision


def diagnose(
    problem: CFDProblemSpec,
    evidence: CFDEvidence,
    *,
    history: Optional[List[Dict[str, Any]]] = None,
    allow_fallback: bool = False,
) -> Tuple[AgentDecision, ActionValidationResult, LLMCallRecord]:
    started = time.monotonic()

    if gemini_key_present():
        try:
            from src.agents.theory_blind_cfd_agent import diagnose_theory_blind

            decision, validation = diagnose_theory_blind(
                problem, evidence, history=history
            )

            return (
                decision,
                validation,
                LLMCallRecord(
                    stage=STAGE,
                    source=GEMINI,
                    model=gemini_model_name(),
                    latency_s=round(time.monotonic() - started, 3),
                ),
            )

        except Exception as exc:  # noqa: BLE001
            if not allow_fallback:
                raise LLMUnavailable(
                    f"Gemini theory-blind diagnosis failed: {exc}"
                ) from exc

            decision = _deterministic_decision(evidence)
            validation = validate_agent_action(evidence, decision)

            return (
                decision,
                validation,
                LLMCallRecord(
                    stage=STAGE,
                    source=FALLBACK,
                    ok=True,
                    error=str(exc),
                    latency_s=round(time.monotonic() - started, 3),
                ),
            )

    if not allow_fallback:
        raise LLMUnavailable(
            "GEMINI_API_KEY is not set and the real LLM path was required."
        )

    decision = _deterministic_decision(evidence)
    validation = validate_agent_action(evidence, decision)

    return (
        decision,
        validation,
        LLMCallRecord(
            stage=STAGE,
            source=FALLBACK,
            ok=True,
            error="GEMINI_API_KEY is not set.",
            latency_s=round(time.monotonic() - started, 3),
        ),
    )
