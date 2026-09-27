#!/usr/bin/env python3
"""2D turbulent backward-facing step spec.

GEOMETRY AND RUN CONTROL ONLY. Every scientific value this family needs in
order to be ACCEPTED lives in recipe.py as an explicit TODO until the
authoritative reference is registered. Nothing in this file encodes a
Reynolds number, a Mach number, a turbulence boundary condition, a mesh
target or a tolerance.

The fields below are placeholders whose defaults are DELIBERATELY absent:
constructing this spec without values raises, so no run can start from a
guessed condition.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

FAMILY = "backward_step"
PHYSICS = "incompressible_rans"


@dataclass(frozen=True)
class BackwardStepSpec:
    """One scope-checked backward-facing step case."""

    # Geometry ratios are set by the reference, not chosen.
    step_height_m: Optional[float] = None
    inlet_channel_height_ratio: Optional[float] = None
    downstream_length_ratio: Optional[float] = None
    upstream_length_ratio: Optional[float] = None

    # Run control. Registered by the reference, not chosen here.
    end_iterations: Optional[int] = None

    family: str = FAMILY
    physics: str = PHYSICS

    def __post_init__(self) -> None:
        for key in ('step_height_m', 'inlet_channel_height_ratio', 'downstream_length_ratio', 'upstream_length_ratio'):
            value = getattr(self, key)
            if value is None:
                raise ValueError(
                    f"{key} has no registered value for family {FAMILY}; "
                    "the authoritative reference must supply it before a case "
                    "can be constructed"
                )
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"{key} must be a number")
            if not math.isfinite(float(value)):
                raise ValueError(f"{key} must be finite")

    def to_dict(self) -> Dict[str, Any]:
        return {k: getattr(self, k) for k in self.__dataclass_fields__}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "BackwardStepSpec":
        fields_ = set(cls.__dataclass_fields__)
        return cls(**{k: v for k, v in data.items() if k in fields_})
