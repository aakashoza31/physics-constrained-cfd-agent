#!/usr/bin/env python3
"""The agent / authority boundary, written down once and enforced in code.

The system's whole safety argument is one sentence:

    the language model proposes, deterministic code decides.

This module makes that checkable rather than aspirational. Every question the
system answers belongs to exactly one of two sets. `LLM_MAY` lists what a model
is allowed to produce; `AUTHORITY_DECIDES` lists what only deterministic code may
answer. A proposal that names an authority-owned question is refused by
`assert_llm_may`, and `final_decision` will not accept a verdict that carries a
model's fingerprints.

Nothing in here is advisory. `AuthorityTrace` is the artefact a reviewer reads to
confirm that each gate was evaluated by code, with its inputs and its threshold.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Tuple

#: Verdicts. The only three outcomes the system may report.
ACCEPT = "ACCEPT"
REJECT = "REJECT"
INCONCLUSIVE = "INCONCLUSIVE"
VERDICTS = (ACCEPT, REJECT, INCONCLUSIVE)

#: What a language model is permitted to do.
LLM_MAY: Tuple[str, ...] = (
    "interpret_user_intent",
    "propose_family_route",
    "diagnose_evidence",
    "propose_bounded_action",
    "explain_result",
    "draft_narrative",
)

#: What only deterministic code may decide. Each entry is a question whose
#: answer changes whether a result may be believed.
AUTHORITY_DECIDES: Tuple[str, ...] = (
    "family_compatibility",
    "geometry_admissibility",
    "mesh_quality",
    "physical_model",
    "boundary_condition_consistency",
    "numerical_health",
    "conservation",
    "convergence",
    "stationarity",
    "validation",
    "permitted_actions",
    "final_decision",
)


class AuthorityViolation(RuntimeError):
    """Raised when a model-produced value is used where code must decide."""


def assert_llm_may(activity: str) -> None:
    if activity in AUTHORITY_DECIDES:
        raise AuthorityViolation(
            f"{activity!r} is owned by deterministic authority and may never be "
            "answered by a language model. The model may propose; only code "
            "decides."
        )
    if activity not in LLM_MAY:
        raise AuthorityViolation(
            f"{activity!r} is not a declared model activity; declared activities "
            f"are {LLM_MAY}"
        )


def assert_authority_owns(question: str) -> None:
    if question not in AUTHORITY_DECIDES:
        raise AuthorityViolation(
            f"{question!r} is not a declared authority question; declared "
            f"questions are {AUTHORITY_DECIDES}"
        )


@dataclass
class Gate:
    """One deterministic check: what was asked, measured, required, decided."""

    question: str
    passed: Optional[bool]
    measured: Any = None
    threshold: Any = None
    detail: str = ""
    source: str = "deterministic"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "question": self.question,
            "passed": self.passed,
            "measured": self.measured,
            "threshold": self.threshold,
            "detail": self.detail,
            "decided_by": self.source,
        }


@dataclass
class AuthorityTrace:
    """The record a reviewer reads to see who decided what.

    Model contributions are recorded as PROPOSALS, in their own list, and can
    never become gates. The verdict is computed from the gates alone.
    """

    family: str = ""
    case: str = ""
    gates: List[Gate] = field(default_factory=list)
    proposals: List[Dict[str, Any]] = field(default_factory=list)
    started_utc: str = field(
        default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    )

    # -- authority side ------------------------------------------------
    def gate(self, question: str, passed: Optional[bool], *, measured: Any = None,
             threshold: Any = None, detail: str = "") -> Gate:
        assert_authority_owns(question)
        entry = Gate(question=question, passed=passed, measured=measured,
                     threshold=threshold, detail=detail)
        self.gates.append(entry)
        return entry

    # -- model side ----------------------------------------------------
    def proposal(self, activity: str, content: Any, *, model: str = "",
                 accepted_by_authority: Optional[bool] = None) -> None:
        assert_llm_may(activity)
        self.proposals.append({
            "activity": activity,
            "content": content,
            "model": model,
            "accepted_by_authority": accepted_by_authority,
            "binding": False,
        })

    # -- verdict -------------------------------------------------------
    @property
    def failed(self) -> List[str]:
        return [g.question for g in self.gates if g.passed is False]

    @property
    def unresolved(self) -> List[str]:
        return [g.question for g in self.gates if g.passed is None]

    def verdict(self) -> str:
        """REJECT beats INCONCLUSIVE beats ACCEPT. Gates only; proposals never."""
        if self.failed:
            return REJECT
        if self.unresolved or not self.gates:
            return INCONCLUSIVE
        return ACCEPT

    def to_dict(self) -> Dict[str, Any]:
        return {
            "family": self.family,
            "case": self.case,
            "started_utc": self.started_utc,
            "authority_questions": list(AUTHORITY_DECIDES),
            "model_activities": list(LLM_MAY),
            "gates": [g.to_dict() for g in self.gates],
            "failed": self.failed,
            "unresolved": self.unresolved,
            "llm_proposals": list(self.proposals),
            "verdict": self.verdict(),
            "rule": ("the verdict is computed from the gates alone; a model "
                     "proposal is recorded but never binding"),
        }


@dataclass
class Decision:
    """The single final answer, with the reason a reviewer needs."""

    verdict: str
    reason: str
    family: str = ""
    case: str = ""
    failed_gates: Tuple[str, ...] = ()
    unresolved_gates: Tuple[str, ...] = ()
    decided_by: str = "deterministic_authority"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "verdict": self.verdict,
            "reason": self.reason,
            "family": self.family,
            "case": self.case,
            "failed_gates": list(self.failed_gates),
            "unresolved_gates": list(self.unresolved_gates),
            "decided_by": self.decided_by,
            "llm_override_possible": False,
        }


def final_decision(trace: AuthorityTrace, *, reason: str = "") -> Decision:
    """Compute the verdict from the trace. No argument can override it."""
    verdict = trace.verdict()
    if not reason:
        if verdict == REJECT:
            reason = f"deterministic gates failed: {trace.failed}"
        elif verdict == INCONCLUSIVE:
            reason = (f"deterministic gates could not be resolved: "
                      f"{trace.unresolved}" if trace.unresolved
                      else "no deterministic gate was evaluated")
        else:
            reason = "every registered deterministic gate passed"
    return Decision(
        verdict=verdict, reason=reason, family=trace.family, case=trace.case,
        failed_gates=tuple(trace.failed), unresolved_gates=tuple(trace.unresolved),
    )
