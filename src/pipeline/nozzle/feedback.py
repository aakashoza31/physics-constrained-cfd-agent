"""Deterministic action execution helpers for the nozzle feedback loop.

The LLM selects an action. These helpers define the only permitted mechanical
realizations of those actions inside the registered nozzle domain. The model does
not edit OpenFOAM dictionaries or invent mesh counts directly.
"""
from __future__ import annotations

import json
import re
from dataclasses import replace
from typing import Any, Dict, Tuple

from src.pipeline.nozzle.spec import NozzleCaseSpec


MAX_FEEDBACK_CELLS = 13200  # finest mesh in the frozen reference campaign


def _replace_foam_entry(text: str, name: str, value: str) -> str:
    """Replace one scalar OpenFOAM dictionary entry, including inline entries."""
    pattern = re.compile(rf"\b{re.escape(name)}\s+[^;]+;")
    if not pattern.search(text):
        raise ValueError(f"controlDict entry missing: {name}")
    return pattern.sub(f"{name} {value};", text, count=1)


def configure_continuation_text(
    control_dict: str,
    *,
    current_time: float,
    end_time: float,
) -> str:
    """Configure an OpenFOAM case to continue from its latest saved state."""
    if not end_time > current_time:
        raise ValueError("continuation end_time must be greater than current_time")

    text = _replace_foam_entry(control_dict, "startFrom", "latestTime")
    if re.search(r"\bstartTime\s+[^;]+;", text):
        text = _replace_foam_entry(text, "startTime", f"{current_time:.12g}")
    text = _replace_foam_entry(text, "endTime", f"{end_time:.12g}")
    return text


def manifest_with_end_time(manifest: Dict[str, Any], end_time: float) -> Dict[str, Any]:
    """Return a manifest whose top-level and embedded spec horizons agree."""
    payload = json.loads(json.dumps(manifest))
    payload["end_time"] = float(end_time)
    if "case_spec" not in payload:
        raise ValueError("manifest has no case_spec block")
    payload["case_spec"]["end_time_s"] = float(end_time)
    return payload


def refined_spec(
    spec: NozzleCaseSpec,
    action: str,
    target_region: str | None,
) -> Tuple[NozzleCaseSpec, Dict[str, Any]]:
    """Map an approved LLM refinement action to a bounded structured-mesh edit.

    REFINE_THROAT increases axial resolution in the converging/throat/diverging
    neighborhood while preserving geometry and the radial count. A supported
    REFINE_GRADIENT_REGION targets one named axial segment. The deterministic
    executor never exceeds the cell count of the finest frozen reference mesh.
    """
    base = list(spec.base_axial_cells)
    before = list(spec.axial_cells)
    region = (target_region or "").strip().lower()

    if action == "REFINE_THROAT":
        # Smoothly refine the high-gradient throat neighborhood.  The throat
        # itself doubles; adjacent conical blocks receive a 50% increase so the
        # axial transition is not a single-block resolution jump.
        base[1] = max(base[1] + 1, round(base[1] * 1.5))
        base[2] = max(base[2] + 1, round(base[2] * 2.0))
        base[3] = max(base[3] + 1, round(base[3] * 1.5))
        applied_region = "converging-throat-diverging neighborhood"

    elif action == "REFINE_GRADIENT_REGION":
        if "throat" in region:
            idx = 2
        elif "diverg" in region:
            idx = 3
        elif "converg" in region:
            idx = 1
        elif "outlet" in region:
            idx = 4
        elif "inlet" in region:
            idx = 0
        else:
            raise ValueError(
                "REFINE_GRADIENT_REGION target is not one of the supported "
                "axial nozzle regions"
            )
        base[idx] = max(base[idx] + 1, round(base[idx] * 1.5))
        applied_region = region

    else:
        raise ValueError(f"unsupported refinement action: {action}")

    candidate = replace(spec, base_axial_cells=tuple(base))
    cells = sum(candidate.axial_cells) * candidate.radial_cells
    if cells > MAX_FEEDBACK_CELLS:
        raise ValueError(
            f"refinement would create {cells} cells, above bounded feedback "
            f"limit {MAX_FEEDBACK_CELLS}"
        )

    return candidate, {
        "action": action,
        "requested_target_region": target_region,
        "applied_region": applied_region,
        "axial_cells_before": before,
        "axial_cells_after": candidate.axial_cells,
        "radial_cells": candidate.radial_cells,
        "total_cells_after": cells,
        "authority": "deterministic action executor",
    }
