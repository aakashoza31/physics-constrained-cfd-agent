#!/usr/bin/env python3
"""Declarative family recipe: the frozen scientific definition of a family.

A recipe is data, not code. Every number a family needs in order to say
"this result is acceptable" lives here, and any number not yet justified by an
authoritative reference is declared with ``TODO(...)`` rather than guessed.

The one rule the whole safety argument rests on:

    a recipe with any unresolved constant can never produce ACCEPT.

``FamilyRecipe.unresolved()`` enumerates them and the orchestrator downgrades
the decision to INCONCLUSIVE with reason CRITERION_NOT_REGISTERED.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Tuple

from src.families.base import Unresolved, is_unresolved


@dataclass(frozen=True)
class FamilyRecipe:
    """Frozen declarative definition of one physics family."""

    family: str
    physics: str
    #: Citation of the authoritative benchmark this family reproduces.
    reference: str
    #: Solver / turbulence model / scheme identity, as strings. Declarative.
    numerics: Dict[str, Any] = field(default_factory=dict)
    #: Admissible request envelope: name -> (low, high).
    bounds: Dict[str, Tuple[float, float]] = field(default_factory=dict)
    #: Acceptance tolerances. Values may be TODO(...).
    tolerances: Dict[str, Any] = field(default_factory=dict)
    #: External reference quantities the validator compares against.
    #: Values may be TODO(...).
    reference_values: Dict[str, Any] = field(default_factory=dict)
    #: Bounded corrective actions this family permits.
    allowed_actions: Tuple[str, ...] = ()
    #: Closed vocabulary of region hints the LLM may name for REFINE_REGION.
    region_vocabulary: Tuple[str, ...] = ()
    #: Constants required only by an OPTIONAL capability, keyed by the action
    #: that needs them. An unresolved entry here disables THAT capability; it
    #: does not block acceptance of a result that never used it. Keeping these
    #: separate from `tolerances` is what lets a frozen, already-registered
    #: family still ACCEPT while a newer capability remains unregistered.
    capability_criteria: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    #: Free-form notes carried into the provenance record.
    notes: str = ""

    # ------------------------------------------------------------------
    def unresolved(self) -> List[str]:
        """Acceptance-critical constants still unregistered, sorted.

        Capability-gated constants are deliberately NOT included: they are
        reported by unresolved_capabilities() and they gate their own action
        rather than the family's acceptance.
        """
        out: List[str] = []
        for section in ("numerics", "tolerances", "reference_values"):
            for key, value in getattr(self, section).items():
                if is_unresolved(value):
                    out.append(f"{section}.{key}")
        for key, value in self.bounds.items():
            if is_unresolved(value) or (
                isinstance(value, tuple) and any(is_unresolved(v) for v in value)
            ):
                out.append(f"bounds.{key}")
        return sorted(out)

    def is_registered(self) -> bool:
        """True when every ACCEPTANCE-CRITICAL constant has been registered.

        A family may be registered for acceptance while an optional capability
        is still unavailable.
        """
        return not self.unresolved()

    def unresolved_capabilities(self) -> Dict[str, List[str]]:
        """Optional capabilities blocked by an unregistered constant."""
        out: Dict[str, List[str]] = {}
        for action, constants in self.capability_criteria.items():
            missing = sorted(
                f"capability_criteria.{action}.{k}"
                for k, v in constants.items()
                if is_unresolved(v)
            )
            if missing:
                out[action] = missing
        return out

    def capability_available(self, action: str) -> bool:
        return action not in self.unresolved_capabilities()

    def unresolved_detail(self) -> List[Dict[str, str]]:
        """Unresolved constants with the note explaining what is needed."""
        detail: List[Dict[str, str]] = []
        for path in self.unresolved():
            section, _, key = path.partition(".")
            value = getattr(self, section).get(key)
            if isinstance(value, tuple):
                value = next((v for v in value if is_unresolved(v)), None)
            detail.append(
                {
                    "constant": path,
                    "awaiting": getattr(value, "note", "") if value is not None else "",
                }
            )
        return detail

    def to_dict(self) -> Dict[str, Any]:
        def render(v: Any) -> Any:
            if is_unresolved(v):
                return {"TODO": v.name, "awaiting": v.note}
            if isinstance(v, tuple):
                return [render(x) for x in v]
            if isinstance(v, dict):
                return {k: render(x) for k, x in v.items()}
            return v

        return {
            "family": self.family,
            "physics": self.physics,
            "reference": self.reference,
            "numerics": render(self.numerics),
            "bounds": render(self.bounds),
            "tolerances": render(self.tolerances),
            "reference_values": render(self.reference_values),
            "allowed_actions": list(self.allowed_actions),
            "region_vocabulary": list(self.region_vocabulary),
            "capability_criteria": render(self.capability_criteria),
            "registered": self.is_registered(),
            "unresolved": self.unresolved(),
            "unresolved_capabilities": self.unresolved_capabilities(),
            "notes": self.notes,
        }
