#!/usr/bin/env python3
"""Deterministic region selection for bounded local refinement.

This is the family half of the REFINE_REGION architecture. The LLM may name a
region from CLOSED_VOCABULARY and nothing else; every number below is computed
here from the mesh geometry and from measurements already in the diagnostics
document.

WHAT IS AND IS NOT REGISTERED
-----------------------------
Registered (geometry, not science): where the named regions ARE. The shock
region is a band around the measured compression front; the step-corner region
is a neighbourhood of the step's convex corner, whose coordinates come from the
spec. Locating a region is coordinate arithmetic.

NOT registered: whether a region is UNDER-RESOLVED. Deciding that a shock is
smeared over too many cells requires a criterion tied to the reference -- a
cells-per-gradient-thickness target, or a cross-grid change in a measured shock
quantity that must fall below a stated bound. This family has no such
registered criterion, so ``resolution_verdict`` returns
UNDER_RESOLUTION_NOT_ESTABLISHED and the deterministic gate refuses the action.
That refusal is the correct behaviour, not a gap to be patched with a guess.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from src.families.base import TODO
from src.families.refine_region import (
    NOT_ESTABLISHED,
    RegionSelection,
)
from src.pipeline.forward_step_2d.spec import ForwardStep2DSpec

SHOCK = "shock"
STEP_CORNER = "step_corner"

#: The only region names the LLM may propose for this family.
CLOSED_VOCABULARY = (SHOCK, STEP_CORNER)

#: Half-width of the band placed around the measured compression front,
#: expressed in local cell widths. This is a selection geometry, chosen so the
#: band straddles the front rather than a physical length scale.
SHOCK_BAND_HALF_WIDTH_CELLS = 6

#: Neighbourhood of the step corner, in cell widths.
CORNER_HALF_WIDTH_CELLS = 8

#: THE MISSING SCIENTIFIC CRITERION. Registering this is what would let the
#: deterministic layer say a shock region is under-resolved.
UNDER_RESOLUTION_CRITERION = TODO(
    "forward_step_2d.under_resolution_criterion",
    "awaiting an authoritative criterion for when the compression front is "
    "under-resolved: either a cells-across-front target from the reference, or "
    "a cross-grid tolerance on a measured shock quantity",
)


def _spacing(spec: ForwardStep2DSpec) -> Dict[str, float]:
    """Cell sizes in each of the family's two graded blocks."""
    a, b = spec.splits
    return {
        "dx_upstream": spec.step_x / a,
        "dx_downstream": (spec.length - spec.step_x) / (spec.nx - a),
        "dy_lower": spec.step_height / b,
        "dy_upper": (spec.height - spec.step_height) / (spec.ny - b),
    }


def _count_cells_in_box(spec: ForwardStep2DSpec, x0: float, x1: float,
                        y0: float, y1: float) -> int:
    """Cells whose centres fall inside the box, on this family's block mesh."""
    a, b = spec.splits
    s = _spacing(spec)
    xs = [(i + 0.5) * s["dx_upstream"] for i in range(a)] + [
        spec.step_x + (i + 0.5) * s["dx_downstream"] for i in range(spec.nx - a)
    ]
    ys_lower = [(j + 0.5) * s["dy_lower"] for j in range(b)]
    ys_upper = [spec.step_height + (j + 0.5) * s["dy_upper"]
                for j in range(spec.ny - b)]

    count = 0
    for x in xs:
        if not (x0 <= x <= x1):
            continue
        # Cells below the step exist only upstream of it: the step is solid.
        if x < spec.step_x:
            for y in ys_lower:
                if y0 <= y <= y1:
                    count += 1
        for y in ys_upper:
            if y0 <= y <= y1:
                count += 1
    return count


def total_cells(spec: ForwardStep2DSpec) -> int:
    a, b = spec.splits
    return a * spec.ny + (spec.nx - a) * (spec.ny - b)


def select_region(
    name: str,
    spec: ForwardStep2DSpec,
    diagnostics: Dict[str, Any],
    *,
    levels: int = 1,
) -> Optional[RegionSelection]:
    """Compute the cells a named region covers. Deterministic; no LLM input."""
    if name not in CLOSED_VOCABULARY:
        return None
    s = _spacing(spec)
    total = total_cells(spec)

    if name == SHOCK:
        shock = diagnostics.get("shock") or {}
        if not shock.get("available"):
            return None
        front = shock.get("upper_stem_x")
        if front is None:
            return None
        front = float(front)
        dx = s["dx_upstream"] if front < spec.step_x else s["dx_downstream"]
        half = SHOCK_BAND_HALF_WIDTH_CELLS * dx
        x0, x1 = max(0.0, front - half), min(spec.length, front + half)
        y0, y1 = 0.0, spec.height
        derivation = (
            f"band of +/-{SHOCK_BAND_HALF_WIDTH_CELLS} cell widths "
            f"(dx={dx:.6g}) about the measured upper compression-front "
            f"position x={front:.6g} from diagnostics['shock']['upper_stem_x']"
        )
        measurements = {
            "upper_stem_x": front,
            "regional_angle_deg": shock.get("regional_angle_deg"),
            "dx_at_front": dx,
        }
    else:  # STEP_CORNER
        dx, dy = s["dx_downstream"], s["dy_upper"]
        x0 = max(0.0, spec.step_x - CORNER_HALF_WIDTH_CELLS * s["dx_upstream"])
        x1 = min(spec.length, spec.step_x + CORNER_HALF_WIDTH_CELLS * dx)
        y0 = max(0.0, spec.step_height - CORNER_HALF_WIDTH_CELLS * dy)
        y1 = min(spec.height, spec.step_height + CORNER_HALF_WIDTH_CELLS * dy)
        derivation = (
            f"neighbourhood of +/-{CORNER_HALF_WIDTH_CELLS} cell widths about "
            f"the step corner (step_x={spec.step_x:.6g}, "
            f"step_height={spec.step_height:.6g}) taken from the spec geometry"
        )
        measurements = {"step_x": spec.step_x, "step_height": spec.step_height}

    count = _count_cells_in_box(spec, x0, x1, y0, y1)
    if count <= 0:
        return None

    return RegionSelection(
        name=name,
        box_min=(x0, y0, -spec.span),
        box_max=(x1, y1, spec.span),
        cell_count=count,
        total_cells=total,
        levels=levels,
        derivation=derivation,
        measurements=measurements,
    )


def resolution_verdict(
    name: str, spec: ForwardStep2DSpec, diagnostics: Dict[str, Any]
) -> str:
    """Is the named region under-resolved?

    Always UNDER_RESOLUTION_NOT_ESTABLISHED while
    UNDER_RESOLUTION_CRITERION is unregistered. Do not replace this with a
    heuristic: the deterministic gate is supposed to refuse an action it cannot
    justify from a registered criterion.
    """
    return NOT_ESTABLISHED


def criterion_status() -> Dict[str, Any]:
    return {
        "criterion": UNDER_RESOLUTION_CRITERION.name,
        "registered": False,
        "awaiting": UNDER_RESOLUTION_CRITERION.note,
        "consequence": "REFINE_REGION is refused for this family until registered",
    }
