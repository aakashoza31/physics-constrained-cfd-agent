#!/usr/bin/env python3
"""Family router: LLM proposes, the register verifies, the family vetoes.

Three authorities in series, and only the first is the LLM:

    1. an LLM reads the request and NAMES a family (advisory);
    2. the register confirms that name exists and is routable (deterministic);
    3. the family's own scope gate decides whether the parsed spec is
       admissible, and may veto (deterministic).

A request no registered family covers returns REJECT / NO_REGISTERED_FAMILY.
The LLM cannot invent a family, cannot route to a non-routable one, and cannot
overturn a scope-gate refusal.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from src.families import registry
from src.families.base import NO_REGISTERED_FAMILY, REJECT
from src.orchestrator.ledger import Ledger


@dataclass(frozen=True)
class RoutingResult:
    approved: bool
    family: Optional[str]
    decision: str
    reasons: List[str] = field(default_factory=list)
    proposed_family: Optional[str] = None
    candidates: List[str] = field(default_factory=list)
    keyword_support: Dict[str, List[str]] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "approved": self.approved,
            "family": self.family,
            "decision": self.decision,
            "reasons": list(self.reasons),
            "proposed_family": self.proposed_family,
            "candidates": list(self.candidates),
            "keyword_support": {k: list(v) for k, v in self.keyword_support.items()},
            "authority": "deterministic_confirmation_of_llm_proposal",
        }


def keyword_support(text: str) -> Dict[str, List[str]]:
    """Which registered families the request text positively mentions.

    Scans the WHOLE register, not only the executable families, so that a
    request straddling an executable and a pending family is recognised as
    ambiguous instead of silently collapsing onto whichever one happens to be
    executable today.

    Declarative evidence only. It never overrides the LLM's choice; it is
    recorded so a routing decision can be audited, and it is what the router
    falls back to when no LLM is available.
    """
    low = (text or "").lower()
    hits: Dict[str, List[str]] = {}
    for record in registry.all_families():
        matched = [k for k in record.keywords if k in low]
        if matched:
            hits[record.name] = matched
    return hits


def describe_families() -> List[Dict[str, str]]:
    """The EXECUTABLE family menu handed to the LLM. Declarative.

    CORE-PENDING families are omitted: they are visible in the register but
    cannot be routed to, so offering them would invite a proposal that is
    refused a moment later.
    """
    return [
        {"name": r.name, "physics": r.physics, "description": r.description}
        for r in registry.routable_families()
    ]


def route(
    text: str,
    *,
    propose: Optional[Callable[[str, List[Dict[str, str]]], Optional[str]]] = None,
    ledger: Optional[Ledger] = None,
) -> RoutingResult:
    """Route a natural-language request to a registered family.

    ``propose(text, menu) -> family_name | None`` is the LLM seam. When it is
    None the router uses keyword support alone, which is the offline path used
    by the negative-routing tests.
    """
    ledger = ledger or Ledger()
    registry.install_standing_register()
    menu = describe_families()
    names = [m["name"] for m in menu]
    support = keyword_support(text)

    proposed: Optional[str] = None
    if propose is not None:
        proposed = propose(text, menu)
    elif len(support) == 1:
        # Keyword fallback only fires on a single unambiguous match, and only
        # when that match is executable. Support for a pending or retained
        # family is ambiguity, not a route.
        only = next(iter(support))
        record = registry.get(only)
        if record is not None and record.routable:
            proposed = only

    reasons: List[str] = []

    if proposed is None:
        detail = ""
        if len(support) > 1:
            detail = (
                f"; {len(support)} families share keyword support "
                f"({', '.join(sorted(support))}) and the request must say which"
            )
        elif len(support) == 1:
            only = next(iter(support))
            record = registry.get(only)
            status = record.status if record else "unknown"
            detail = (
                f"; the only family the request mentions is {only!r}, which is "
                f"status {status} and not executable"
            )
        result = RoutingResult(
            False, None, f"{REJECT} / {NO_REGISTERED_FAMILY}",
            ["no executable family was identified for this request" + detail],
            None, names, support,
        )
        ledger.record("routing", result)
        return result

    record = registry.get(proposed)
    if record is None:
        result = RoutingResult(
            False, None, f"{REJECT} / {NO_REGISTERED_FAMILY}",
            [f"{proposed!r} is not a registered family; registered: {names}"],
            proposed, names, support,
        )
        ledger.record("routing", result)
        return result

    if not record.routable:
        why = f"status {record.status}"
        if record.status == "CORE-PENDING":
            why += (
                "; its scientific recipe is unregistered, so no result could be "
                "accepted"
            )
        elif record.retained_as:
            why += f"; retained as {record.retained_as}"
        result = RoutingResult(
            False, None, f"{REJECT} / {NO_REGISTERED_FAMILY}",
            [f"family {proposed!r} is registered but not executable ({why})"],
            proposed, names, support,
        )
        ledger.record("routing", result)
        return result

    if proposed not in support:
        reasons.append(
            f"note: request text contains no declared keyword for {proposed!r}; "
            "routing rests on the model's reading and the family scope gate retains veto"
        )

    result = RoutingResult(
        True, proposed, "ROUTED", reasons, proposed, names, support
    )
    ledger.record("routing", result)
    return result
