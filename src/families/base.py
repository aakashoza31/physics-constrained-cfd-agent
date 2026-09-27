#!/usr/bin/env python3
"""Shared vocabulary every registered physics family speaks.

Nothing in this module knows any CFD. It defines the contract the orchestrator
relies on, the four terminal decisions, and the sentinel that makes an
unregistered scientific constant structurally unable to produce an ACCEPT.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Protocol, Tuple, runtime_checkable

# --------------------------------------------------------------------------
# Terminal decisions. These are the only values the deterministic layer may
# return, and the LLM never writes one.
# --------------------------------------------------------------------------
ACCEPT = "ACCEPT"
CORRECT_AND_RERUN = "CORRECT_AND_RERUN"
INCONCLUSIVE = "INCONCLUSIVE"
REJECT = "REJECT"

DECISIONS = (ACCEPT, CORRECT_AND_RERUN, INCONCLUSIVE, REJECT)
Decision = Literal["ACCEPT", "CORRECT_AND_RERUN", "INCONCLUSIVE", "REJECT"]

#: Reason code used whenever a family's recipe still carries an unresolved
#: scientific constant. It downgrades ACCEPT to INCONCLUSIVE and is the
#: generalisation of forward_step_mesh_study.CRITERION_NOT_REGISTERED.
CRITERION_NOT_REGISTERED = "CRITERION_NOT_REGISTERED"

#: Reason code the router returns when no registered family covers a request.
NO_REGISTERED_FAMILY = "NO_REGISTERED_FAMILY"

# --------------------------------------------------------------------------
# Family lifecycle status. Only CORE families may be routed to.
# --------------------------------------------------------------------------
CORE = "CORE"
CORE_PENDING = "CORE-PENDING"
SUPPORTING = "SUPPORTING"
NONACCEPTED = "NONACCEPTED"

STATUSES = (CORE, CORE_PENDING, SUPPORTING, NONACCEPTED)

#: Only a CORE family may be routed to for execution. CORE-PENDING is visible
#: in the register and inspectable, but not executable: its scientific recipe is
#: unregistered, so nothing it produced could be accepted, and routing a real
#: request there would waste a solve to reach a foregone INCONCLUSIVE.
EXECUTABLE_STATUSES = (CORE,)

#: Retained for callers that want the visible-but-not-executable set.
ROUTABLE_STATUSES = EXECUTABLE_STATUSES


class Unresolved:
    """Sentinel for a scientific constant that has not been registered yet.

    A recipe may be written before the authoritative reference is settled, but
    a recipe holding one of these can never yield ACCEPT. The name is carried
    so the reason string can say which constant is missing.
    """

    __slots__ = ("name", "note")

    def __init__(self, name: str, note: str = "") -> None:
        self.name = name
        self.note = note

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return f"TODO({self.name!r})"

    def __bool__(self) -> bool:
        # Deliberately falsy so an accidental `if tol:` does not read as set.
        return False


def TODO(name: str, note: str = "") -> Unresolved:
    """Declare an unregistered scientific constant."""
    return Unresolved(name, note)


def is_unresolved(value: Any) -> bool:
    return isinstance(value, Unresolved)


# --------------------------------------------------------------------------
# Shared result types
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class ScopeResult:
    """Deterministic admissibility verdict for one spec inside one family."""

    approved: bool
    decision: str
    reasons: List[str] = field(default_factory=list)
    checks: Dict[str, bool] = field(default_factory=dict)
    measurements: Dict[str, float] = field(default_factory=dict)
    clarification_needed: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "approved": self.approved,
            "decision": self.decision,
            "reasons": list(self.reasons),
            "checks": dict(self.checks),
            "measurements": dict(self.measurements),
            "clarification_needed": list(self.clarification_needed),
            "authority": "deterministic",
        }


@dataclass(frozen=True)
class ActionRuling:
    """Deterministic ruling on one LLM-proposed action."""

    approved: bool
    action: str
    reasons: List[str] = field(default_factory=list)
    resulting_changes: Dict[str, Any] = field(default_factory=dict)
    corrected_spec: Optional[Any] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "approved": self.approved,
            "action": self.action,
            "reasons": list(self.reasons),
            "resulting_changes": dict(self.resulting_changes),
            "spec_changed": self.corrected_spec is not None,
            "authority": "deterministic",
        }


@dataclass(frozen=True)
class Proposal:
    """What the LLM returned. Advisory only: nothing here is authoritative."""

    diagnosis: str
    action: str
    reasoning_summary: str = ""
    region_hint: Optional[str] = None
    confidence: str = "unknown"
    raw: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "diagnosis": self.diagnosis,
            "action": self.action,
            "reasoning_summary": self.reasoning_summary,
            "region_hint": self.region_hint,
            "confidence": self.confidence,
            "authority": "advisory_llm",
        }


@dataclass(frozen=True)
class Outcome:
    """One terminal orchestrator result."""

    decision: Decision
    family: str
    reasons: List[str] = field(default_factory=list)
    validation: Dict[str, Any] = field(default_factory=dict)
    iterations: int = 0
    unresolved_criteria: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "decision": self.decision,
            "family": self.family,
            "reasons": list(self.reasons),
            "iterations": self.iterations,
            "unresolved_criteria": list(self.unresolved_criteria),
            "validation_status": self.validation.get("status"),
            "authority": "deterministic",
        }


# --------------------------------------------------------------------------
# Evidence schema. Evidence stays a plain dict -- that is what survived
# contact with reality in forward_step_2d -- but the top level is fixed so the
# orchestrator, the ablations and the fault injector can address it uniformly.
# --------------------------------------------------------------------------
EVIDENCE_SECTIONS = (
    "family",
    "spec",
    "mesh",
    "solver",
    "conservation",
    "stationarity",
    "quantitative",
    "provenance",
)


def empty_evidence(family: str) -> Dict[str, Any]:
    ev: Dict[str, Any] = {k: {} for k in EVIDENCE_SECTIONS}
    ev["family"] = family
    return ev


def validate_evidence_shape(evidence: Dict[str, Any]) -> List[str]:
    """Return the list of missing required sections. Empty list means OK."""
    return [k for k in EVIDENCE_SECTIONS if k not in evidence]


# --------------------------------------------------------------------------
# The family contract
# --------------------------------------------------------------------------
@runtime_checkable
class FamilyAdapter(Protocol):
    """One registered physics family.

    Adapters delegate to existing family code. They must not reimplement CFD.
    """

    name: str
    status: str
    physics: str

    # -- request handling ------------------------------------------------
    def parse_request(self, text: str) -> Tuple[Any, Dict[str, Any]]:
        """Return (spec, llm_call_record). May raise if no LLM is available."""

    def load_spec(self, path: Path) -> Any:
        """Load this family's frozen spec from disk.

        The shared CLI calls only this, so no caller needs to know which spec
        class a family uses.
        """

    def load_evidence(self, path: Path) -> Dict[str, Any]:
        """Rebuild shared-shape evidence from an existing output directory.

        Reads archived documents only. It must never launch a solver, so
        decision-level replay of a completed run costs no CFD.
        """

    def check_scope(self, spec: Any) -> ScopeResult: ...

    # -- case lifecycle --------------------------------------------------
    def build_case(self, spec: Any, destination: Path) -> Path: ...

    def run_case(self, case: Path, *, append: bool = False) -> int: ...

    def collect_evidence(self, case: Path, out: Path) -> Dict[str, Any]: ...

    # -- reasoning -------------------------------------------------------
    def diagnose(
        self, evidence: Dict[str, Any], spec: Any
    ) -> Tuple[Proposal, Dict[str, Any]]:
        """LLM diagnosis. Returns (proposal, llm_call_record)."""

    def deterministic_proposal(
        self, evidence: Dict[str, Any], spec: Any
    ) -> Proposal:
        """Recipe-driven proposal used by the no-diagnosis and baseline modes."""

    def allowed_actions(self, evidence: Dict[str, Any], spec: Any) -> List[str]: ...

    def execute_action(
        self, action: str, spec: Any, evidence: Dict[str, Any], **kw: Any
    ) -> ActionRuling: ...

    # -- authority -------------------------------------------------------
    def validate(self, evidence: Dict[str, Any], spec: Any) -> Dict[str, Any]:
        """Family validation. Must include a 'status' key."""

    def maps_to_decision(self, validation: Dict[str, Any]) -> Decision:
        """Translate the family status vocabulary into a shared Decision."""

    def summarize(
        self, *, spec: Any, evidence: Dict[str, Any], validation: Dict[str, Any], out: Path
    ) -> None: ...
