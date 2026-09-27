#!/usr/bin/env python3
"""2D turbulent NACA0012 airfoil spec.

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

FAMILY = "airfoil"
PHYSICS = "incompressible_or_low_mach_rans"


@dataclass(frozen=True)
class AirfoilSpec:
    """One scope-checked NACA0012 airfoil case."""

    # Geometry is fixed by the section designation; chord is a scale.
    chord_m: Optional[float] = None
    angle_of_attack_deg: Optional[float] = None

    # Domain extent in chords. Registered by the reference.
    farfield_radius_chords: Optional[float] = None

    # Run control. Registered by the reference, not chosen here.
    end_iterations: Optional[int] = None

    family: str = FAMILY
    physics: str = PHYSICS

    def __post_init__(self) -> None:
        for key in ('chord_m', 'angle_of_attack_deg', 'farfield_radius_chords'):
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
    def from_dict(cls, data: Dict[str, Any]) -> "AirfoilSpec":
        fields_ = set(cls.__dataclass_fields__)
        return cls(**{k: v for k, v in data.items() if k in fields_})
