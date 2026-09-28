#!/usr/bin/env python3
"""Family matching and admissibility. Deterministic, and it owns the answer.

The language model may PROPOSE a family. This module decides whether that family
can actually accept the geometry in front of it, by three tests in order:

  1. the family is registered and routable;
  2. the family accepts this geometry SOURCE (parametric / STEP);
  3. the geometry, normalised by the family's characteristic dimension, lies in
     the family's registered envelope.

A failure at any step returns a refusal with the reason, and no mesh or solver is
touched. There is no path from an unsupported geometry to a CFD run.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from src.families import capabilities as caps
from src.geometry.features import GeometryFeatures, PARAMETRIC, STEP

MATCHER_VERSION = "family-matching/1.0.0"

ADMISSIBLE = "ADMISSIBLE"
UNSUPPORTED_GEOMETRY = "UNSUPPORTED_GEOMETRY"
UNSUPPORTED_SOURCE = "UNSUPPORTED_GEOMETRY_SOURCE"
NOT_ROUTABLE = "FAMILY_NOT_ROUTABLE"
NO_FAMILY = "NO_REGISTERED_FAMILY"


@dataclass
class Admissibility:
    """Whether one family may accept one geometry, and why."""

    family: str
    status: str
    reasons: List[str] = field(default_factory=list)
    checks: Dict[str, bool] = field(default_factory=dict)
    normalised: Dict[str, float] = field(default_factory=dict)

    @property
    def admissible(self) -> bool:
        return self.status == ADMISSIBLE

    def to_dict(self) -> Dict[str, Any]:
        return {
            "matcher_version": MATCHER_VERSION,
            "family": self.family,
            "status": self.status,
            "admissible": self.admissible,
            "checks": dict(self.checks),
            "normalised_geometry": dict(self.normalised),
            "reasons": list(self.reasons),
        }


def normalise(features: GeometryFeatures,
              capability: caps.FamilyCapabilities) -> Dict[str, float]:
    """Divide every dimension by the family's characteristic dimension.

    Returns {} when the characteristic dimension is unknown -- an unnormalised
    geometry is reported as unknown rather than passed through as if it were 1.
    """
    name = capability.characteristic_dimension
    value = features.dimensions.get(name, features.characteristic_dimension)
    if not value:
        return {}
    return {f"{k}_over_{name}": v / value for k, v in features.dimensions.items()}


def admissible(family: str, features: GeometryFeatures) -> Admissibility:
    """The deterministic admissibility decision for one family."""
    canonical = caps.resolve(family)
    if canonical not in caps.TABLE:
        return Admissibility(family=family, status=NO_FAMILY,
                             reasons=[f"{family!r} is not a registered family"])
    family = canonical
    capability = caps.capabilities(family)
    checks: Dict[str, bool] = {}
    reasons: List[str] = []

    checks["family_is_routable"] = capability.routable
    if not capability.routable:
        reasons.append(
            f"{family} has status {capability.status} and is not routable for "
            "execution; its evidence is preserved and replayable, but a new run "
            "may not be accepted through it"
        )

    if features.source == STEP:
        checks["family_accepts_step"] = capability.accepts_step()
        if not capability.accepts_step():
            reasons.append(
                f"{family} does not accept STEP input: {capability.geometry_inputs.step_note}"
            )
    else:
        checks["family_accepts_parametric"] = capability.geometry_inputs.parametric
        if not capability.geometry_inputs.parametric:
            reasons.append(f"{family} does not accept parametric geometry")

    checks["geometry_is_characterised"] = features.usable
    if not features.usable:
        reasons.append(features.reason or "the geometry could not be characterised")

    normalised = normalise(features, capability) if features.usable else {}
    checks["characteristic_dimension_known"] = bool(normalised) or not features.dimensions
    if features.usable and features.dimensions and not normalised:
        reasons.append(
            f"the characteristic dimension {capability.characteristic_dimension!r} "
            "was not supplied, so the geometry cannot be normalised against the "
            "registered envelope"
        )

    if all(checks.values()):
        status = ADMISSIBLE
    elif not capability.routable:
        status = NOT_ROUTABLE
    elif features.source == STEP and not capability.accepts_step():
        status = UNSUPPORTED_SOURCE
    else:
        status = UNSUPPORTED_GEOMETRY
    return Admissibility(family=family, status=status, reasons=reasons,
                         checks=checks, normalised=normalised)


def match(features: GeometryFeatures, *,
          proposed: Optional[str] = None) -> Dict[str, Any]:
    """Evaluate every family, and report which (if any) can take this geometry.

    A model's proposal is recorded and then CHECKED; it is never trusted.
    """
    evaluations = {name: admissible(name, features).to_dict() for name in caps.TABLE}
    admissible_families = [n for n, e in evaluations.items() if e["admissible"]]
    selected: Optional[str] = None
    if proposed and proposed in admissible_families:
        selected = proposed
    elif len(admissible_families) == 1:
        selected = admissible_families[0]
    return {
        "matcher_version": MATCHER_VERSION,
        "geometry": features.to_dict(),
        "llm_proposed_family": proposed,
        "llm_proposal_was_accepted": bool(selected) and selected == proposed,
        "admissible_families": admissible_families,
        "selected_family": selected,
        "evaluations": evaluations,
        "rule": ("a model may propose a family; this matcher decides whether the "
                 "geometry is admissible for it"),
    }
