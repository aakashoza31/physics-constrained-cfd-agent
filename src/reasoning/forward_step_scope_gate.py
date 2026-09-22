#!/usr/bin/env python3
"""Deterministic scope gate for the 2D forward-facing-step family.

PROVENANCE
----------
Same shape as ``src/reasoning/nozzle_scope_gate.py``: the LLM interprets the
request, this gate decides without the LLM whether the resulting specification
lies inside the registered, validated family. A rejection here is final and the
model cannot overrule it.

REGISTERED FAMILY
-----------------
  * 2D forward-facing step, three-block structured mesh, one empty z layer
  * inviscid compressible Euler, normalized ideal gas
  * supersonic inflow
  * OpenFOAM Foundation v14, shockFluid, trusted tutorial recipe

The numeric bounds below are transfer limits around the canonical tutorial
case, not physical laws. They exist so a request far outside what was actually
verified is refused rather than quietly simulated.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from src.pipeline.forward_step_2d.spec import (
    CANONICAL_CELLS,
    MAX_CELLS,
    ForwardStep2DSpec,
)

BOUNDS: Dict[str, tuple] = {
    "mach": (1.2, 6.0),
    "step_height_fraction": (0.05, 0.6),      # step_height / height
    "step_x_fraction": (0.05, 0.8),           # step_x / length
    "aspect_ratio": (1.0, 10.0),              # length / height
    "pressure": (0.1, 10.0),
    "temperature": (0.1, 10.0),
    "end_time": (0.1, 12.0),
    "max_co": (0.05, 0.2),
    "cells": (2000, MAX_CELLS),
    "cell_aspect_ratio": (0.25, 4.0),         # dx / dy
}

# Requests that name physics this family does not implement. The gate refuses
# rather than silently mapping them onto the inviscid recipe.
UNSUPPORTED_TOPICS = {
    "turbulence": ["turbulent", "turbulence", "k-epsilon", "k-omega", "les", "rans", "sst"],
    "viscosity": ["viscous", "viscosity", "reynolds number", "boundary layer", "laminar viscous", "no-slip"],
    "heat_transfer": ["heat transfer", "conjugate", "wall temperature", "heat flux", "thermal wall"],
    "species_or_reaction": ["combustion", "reacting", "species", "mixture fraction"],
    "multiphase": ["multiphase", "two-phase", "cavitation", "free surface", "vof"],
    "three_dimensional": ["3d", "three-dimensional", "spanwise", "extrusion"],
    "arbitrary_cad": ["step file", "stl", "iges", "cad file", "imported geometry"],
    "solver_change": ["rhocentralfoam", "sonicfoam", "simplefoam", "pimplefoam", "change the solver", "different solver"],
    "scheme_change": ["change the scheme", "different flux", "minmod", "upwind scheme", "second order scheme"],
    "subsonic": ["subsonic", "incompressible", "low mach"],
}


@dataclass
class ScopeResult:
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
            "family": "forward_step_2d",
            "reasons": self.reasons,
            "checks": self.checks,
            "measurements": self.measurements,
            "clarification_needed": self.clarification_needed,
            "authority": "deterministic",
        }


def screen_request_text(text: str) -> Dict[str, List[str]]:
    """Flag topics the registered family does not implement."""
    lowered = (text or "").lower()
    hits: Dict[str, List[str]] = {}
    for topic, phrases in UNSUPPORTED_TOPICS.items():
        found = [p for p in phrases if p in lowered]
        if found:
            hits[topic] = found
    return hits


def _bounded(
    checks: Dict[str, bool],
    reasons: List[str],
    name: str,
    value: float,
    label: str,
) -> None:
    low, high = BOUNDS[name]
    ok = low <= float(value) <= high
    checks[f"{name}_in_range"] = ok
    if not ok:
        reasons.append(
            f"{label} = {value:g} is outside the validated transfer envelope "
            f"[{low:g}, {high:g}] for this family."
        )


def evaluate_scope(
    spec: ForwardStep2DSpec, request_text: Optional[str] = None
) -> ScopeResult:
    reasons: List[str] = []
    checks: Dict[str, bool] = {}
    clarification: List[str] = []

    # 1. the specification must be structurally valid at all
    try:
        ForwardStep2DSpec.from_dict(spec.to_dict())
        checks["specification_valid"] = True
    except ValueError as exc:
        checks["specification_valid"] = False
        reasons.append(str(exc))

    # 2. family identity
    checks["registered_family"] = (
        spec.family == "forward_step_2d" and spec.physics == "inviscid_euler"
    )
    if not checks["registered_family"]:
        reasons.append(
            "Only the 2D inviscid-Euler forward-step family is registered."
        )

    # 3. topology
    checks["step_inside_channel"] = (
        0 < spec.step_x < spec.length and 0 < spec.step_height < spec.height
    )
    if not checks["step_inside_channel"]:
        reasons.append("The step must lie strictly inside the channel.")

    # 4. quantitative envelope
    step_h_frac = spec.step_height / spec.height if spec.height else float("inf")
    step_x_frac = spec.step_x / spec.length if spec.length else float("inf")
    aspect = spec.length / spec.height if spec.height else float("inf")
    cell_aspect = spec.dx / spec.dy if spec.dy else float("inf")

    _bounded(checks, reasons, "mach", spec.mach, "inlet Mach number")
    _bounded(checks, reasons, "step_height_fraction", step_h_frac, "step height / channel height")
    _bounded(checks, reasons, "step_x_fraction", step_x_frac, "step position / channel length")
    _bounded(checks, reasons, "aspect_ratio", aspect, "channel length / height")
    _bounded(checks, reasons, "pressure", spec.pressure, "inlet pressure")
    _bounded(checks, reasons, "temperature", spec.temperature, "inlet temperature")
    _bounded(checks, reasons, "end_time", spec.end_time, "integration horizon")
    _bounded(checks, reasons, "max_co", spec.max_co, "maximum Courant number")
    _bounded(checks, reasons, "cells", spec.cells, "fluid cell count")
    _bounded(checks, reasons, "cell_aspect_ratio", cell_aspect, "cell aspect ratio dx/dy")

    # 5. free-text screen for physics this family does not implement
    if request_text:
        hits = screen_request_text(request_text)
        # A 3D or CAD request is a hard rejection; the rest ask for clarification
        # only when they are not already satisfied by the fixed recipe.
        hard = {k: v for k, v in hits.items() if k in {"three_dimensional", "arbitrary_cad", "solver_change", "scheme_change", "subsonic", "multiphase", "species_or_reaction"}}
        soft = {k: v for k, v in hits.items() if k not in hard}
        checks["request_text_in_family"] = not hard
        if hard:
            for topic, phrases in hard.items():
                reasons.append(
                    f"Request mentions {topic.replace('_', ' ')} "
                    f"({', '.join(phrases)}), which this family does not implement."
                )
        for topic, phrases in soft.items():
            clarification.append(
                f"The request mentions {topic.replace('_', ' ')} "
                f"({', '.join(phrases)}). This family solves inviscid Euler with "
                "slip walls; confirm that is acceptable."
            )
    else:
        checks["request_text_in_family"] = True

    measurements = {
        "cells": float(spec.cells),
        "canonical_cells": float(CANONICAL_CELLS),
        "step_height_fraction": step_h_frac,
        "step_x_fraction": step_x_frac,
        "channel_aspect_ratio": aspect,
        "dx": spec.dx,
        "dy": spec.dy,
        "cell_aspect_ratio": cell_aspect,
        "realized_inlet_Mach": spec.realized_mach,
        "inlet_velocity": spec.velocity,
    }

    approved = all(checks.values())
    decision = "IN_SCOPE" if approved else "REJECT_UNSUPPORTED"

    return ScopeResult(
        approved=approved,
        decision=decision,
        reasons=reasons,
        checks=checks,
        measurements=measurements,
        clarification_needed=clarification,
    )
