#!/usr/bin/env python3
"""Deterministic mesh-refinement / numerical-sensitivity study.

WHAT THIS IS, AND WHAT IT IS NOT
--------------------------------
This measures how the registered forward-step quantities of interest move when
the grid is refined, under a bounded refinement policy the model cannot alter.
It is a numerical-sensitivity assessment.

It is NOT formal grid convergence and it is NOT a Grid Convergence Index. Those
require a demonstrated asymptotic range, an observed order of accuracy and a
safety-factored uncertainty band. None of that is established for this family,
the underlying shock measurements are gradient-based regional estimates on a
moving curved system that the diagnostics themselves qualify as "not a
grid-converged measurement", and claiming otherwise from three grids would be
dressing up a sensitivity check as an uncertainty quantification. The language
used throughout is "sensitivity", deliberately.

THE ACCEPTANCE CRITERION IS NOT SET HERE
----------------------------------------
A cross-grid tolerance is a scientific decision about how much a quantity may
move between grids before the result counts as adequately resolved. The
repository does not contain one:

  - validate.py lists "Mesh and time-step independence for this family" under
    ``unresolved`` and states the claim boundary is "not a mesh-independence
    claim";
  - no reference package for this family is present (reference_comparison is
    PENDING_NO_REFERENCE_PACKAGE), so no published band can be adopted;
  - the nozzle family has no cross-grid tolerance either.

So ``SENSITIVITY_TOLERANCE`` is None. The comparison is computed and reported
in full; the verdict is withheld as SENSITIVITY_CRITERION_NOT_REGISTERED until
a criterion is supplied explicitly. Inventing a number here would manufacture
the appearance of a scientific decision that has not been made, and the first
run of this study is precisely the evidence needed to make it.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from src.pipeline.forward_step_2d.spec import MAX_CELLS, ForwardStep2DSpec

# ----------------------------------------------------------------------
# bounded refinement policy
# ----------------------------------------------------------------------

#: Uniform linear refinement factor. Two, not the 1.5 the generic bounded
#: action used, because this family's block structure only stays uniform when
#: the split ratios survive the refinement exactly. The upstream block holds
#: round(nx * step_x / length) cells; doubling preserves that ratio for any
#: grid that already had it, while 1.5 does not: refining 45 x 15 by 1.5 gives
#: 68 x 22, where dx is 0.042857 upstream of the step and 0.044444 downstream
#: and dy is 0.05 below the step and 0.044444 above. That is a different mesh
#: topology quality, not a finer version of the same mesh, and comparing
#: quantities across it would confound refinement with grading.
MESH_REFINEMENT_FACTOR = 2

#: At most this many refinements, so three grids in total. The bound exists so
#: an approved action can never open an unbounded compute loop; each level
#: multiplies the cell count by four and the timestep count by two.
MAX_REFINEMENT_LEVELS = 2

#: Cell budget, shared with the specification's own bound.
MAX_STUDY_CELLS = MAX_CELLS

# ----------------------------------------------------------------------
# quantities compared across grids
# ----------------------------------------------------------------------

#: Registered cross-grid quantities. Every one is already measured by
#: diagnostics.shock_metrics on a real run; nothing new and nothing
#: image-derived is introduced. ``kind`` records what a change in it means:
#: a position moves in domain units, an angle in degrees, a jump is a ratio.
SENSITIVITY_QOIS = (
    ("lower_front_x", "position", ("shock", "lower_front_x")),
    ("upper_stem_x", "position", ("shock", "upper_stem_x")),
    ("regional_angle_deg", "angle", ("shock", "regional_angle_deg")),
    ("pressure_jump", "ratio", ("shock", "jumps", "p")),
    ("density_jump", "ratio", ("shock", "jumps", "rho")),
    ("temperature_jump", "ratio", ("shock", "jumps", "T")),
)

#: No defensible cross-grid tolerance exists in this repository. See the module
#: docstring. A criterion must be supplied explicitly before the sensitivity
#: gate can return a verdict.
SENSITIVITY_TOLERANCE: Optional[float] = None

SENSITIVITY_CRITERION_SOURCE = (
    "NOT REGISTERED. No cross-grid tolerance exists in this repository: "
    "validate.py lists mesh independence under 'unresolved' and disclaims a "
    "mesh-independence claim, and no reference package for this family is "
    "present from which a published band could be adopted. The comparison is "
    "measured and reported; the verdict is withheld until a criterion is "
    "supplied. No tolerance is invented here."
)

# sensitivity statuses
CRITERION_NOT_REGISTERED = "SENSITIVITY_CRITERION_NOT_REGISTERED"
NOT_ESTABLISHED = "NUMERICAL_SENSITIVITY_NOT_ESTABLISHED"
WITHIN_TOLERANCE = "SENSITIVITY_WITHIN_TOLERANCE"
ABOVE_TOLERANCE = "SENSITIVITY_ABOVE_TOLERANCE"

QUALIFICATION = (
    "Gradient-based regional measurements on a moving, curved shock system, "
    "compared between grids. A sensitivity assessment, not grid convergence, "
    "not an observed order of accuracy and not a GCI."
)


# ----------------------------------------------------------------------
# refinement
# ----------------------------------------------------------------------


def uniform_spacing(spec: ForwardStep2DSpec) -> Dict[str, Any]:
    """Whether the three blocks share one cell size in each direction.

    The generated mesh is three blocks meeting at the step. Uniformity is a
    property of how the cell counts divide, not something blockMesh enforces,
    and a grid that loses it is not a refined version of the same mesh.
    """
    a, b = spec.splits
    dx_upstream = spec.step_x / a
    dx_downstream = (spec.length - spec.step_x) / (spec.nx - a)
    dy_lower = spec.step_height / b
    dy_upper = (spec.height - spec.step_height) / (spec.ny - b)
    return {
        "dx_upstream": dx_upstream,
        "dx_downstream": dx_downstream,
        "dy_below_step": dy_lower,
        "dy_above_step": dy_upper,
        "uniform": bool(
            abs(dx_upstream - dx_downstream) <= 1e-12 * max(1.0, dx_upstream)
            and abs(dy_lower - dy_upper) <= 1e-12 * max(1.0, dy_lower)
        ),
    }


def refine(spec: ForwardStep2DSpec) -> ForwardStep2DSpec:
    """The registered refinement operation. Raises if it is not permitted.

    This is the ONLY mapping from REFINE_MESH to a mesh change. The model
    proposes the action; it never chooses nx, ny, a factor or any geometry.
    """
    if spec.refinement_level >= MAX_REFINEMENT_LEVELS:
        raise ValueError(
            f"Refinement level {spec.refinement_level} is already at the "
            f"registered maximum of {MAX_REFINEMENT_LEVELS}."
        )

    refined = spec.with_changes(
        nx=spec.nx * MESH_REFINEMENT_FACTOR,
        ny=spec.ny * MESH_REFINEMENT_FACTOR,
        refinement_level=spec.refinement_level + 1,
    )
    if refined.cells > MAX_STUDY_CELLS:
        raise ValueError(
            f"Refinement would produce {refined.cells} cells, beyond the "
            f"{MAX_STUDY_CELLS} budget for this family."
        )
    spacing = uniform_spacing(refined)
    if not spacing["uniform"]:
        raise ValueError(
            "Refinement would leave the registered family: the refined grid "
            "does not share one cell size across the three blocks "
            f"(dx {spacing['dx_upstream']:.6g} vs {spacing['dx_downstream']:.6g}, "
            f"dy {spacing['dy_below_step']:.6g} vs {spacing['dy_above_step']:.6g})."
        )
    return refined


def can_refine(spec: ForwardStep2DSpec) -> Dict[str, Any]:
    """Non-raising form, for the action validator's reasons."""
    try:
        refined = refine(spec)
    except ValueError as exc:
        return {"permitted": False, "reason": str(exc)}
    return {
        "permitted": True,
        "next_level": refined.refinement_level,
        "nx": refined.nx,
        "ny": refined.ny,
        "cells": refined.cells,
        "dx": refined.dx,
        "dy": refined.dy,
        "refinement_ratio": float(MESH_REFINEMENT_FACTOR),
    }


# ----------------------------------------------------------------------
# grid records and comparison
# ----------------------------------------------------------------------


def _dig(source: Dict[str, Any], path) -> Optional[float]:
    value: Any = source
    for key in path:
        if not isinstance(value, dict) or key not in value:
            return None
        value = value[key]
    return float(value) if isinstance(value, (int, float)) else None


def grid_record(
    spec: ForwardStep2DSpec,
    diagnostics: Dict[str, Any],
    validation: Dict[str, Any],
) -> Dict[str, Any]:
    """One grid level's entry in the study. Measurement only."""
    return {
        "refinement_level": spec.refinement_level,
        "nx": spec.nx,
        "ny": spec.ny,
        "cells": spec.cells,
        "dx": spec.dx,
        "dy": spec.dy,
        "spacing": uniform_spacing(spec),
        "final_time": diagnostics.get("final_time"),
        "grid_health": {
            "hard_checks_status": validation.get("hard_checks_status"),
            "failed_checks": validation.get("failed_checks", []),
            "solver_completed": diagnostics.get("solver_completed"),
            "finite_all_saved": diagnostics.get("finite_all_saved"),
            "positive_all_saved": diagnostics.get("positive_all_saved"),
            "courant_finite_positive": diagnostics.get("courant_finite_positive"),
            "transient_mass_closure_residual": (
                diagnostics.get("mass", {}).get("relative_residual_max")
            ),
        },
        "qois": {
            name: _dig(diagnostics, path) for name, _, path in SENSITIVITY_QOIS
        },
        "qoi_kinds": {name: kind for name, kind, _ in SENSITIVITY_QOIS},
    }


def compare_grids(coarse: Dict[str, Any], fine: Dict[str, Any]) -> Dict[str, Any]:
    """Relative movement of each registered quantity between two grids."""
    quantities: Dict[str, Any] = {}
    changes: List[float] = []

    for name, kind, _ in SENSITIVITY_QOIS:
        a, b = coarse["qois"].get(name), fine["qois"].get(name)
        if a is None or b is None:
            quantities[name] = {
                "kind": kind,
                "coarse": a,
                "fine": b,
                "status": "UNAVAILABLE_ON_AT_LEAST_ONE_GRID",
            }
            continue
        absolute = b - a
        relative = absolute / a if a != 0 else float("inf")
        quantities[name] = {
            "kind": kind,
            "coarse": a,
            "fine": b,
            "absolute_change": absolute,
            "relative_change": relative,
        }
        changes.append(abs(relative))

    return {
        # The pair is named explicitly: a comparison that does not say which
        # grids it is between is not evidence.
        "pair": (
            f"level {coarse['refinement_level']} ({coarse['cells']} cells) -> "
            f"level {fine['refinement_level']} ({fine['cells']} cells)"
        ),
        "coarse_level": coarse["refinement_level"],
        "fine_level": fine["refinement_level"],
        "coarse_cells": coarse["cells"],
        "fine_cells": fine["cells"],
        "refinement_ratio": (
            fine["nx"] / coarse["nx"] if coarse["nx"] else None
        ),
        "quantities": quantities,
        "max_abs_relative_change": max(changes) if changes else None,
        "quantities_compared": len(changes),
        "quantities_unavailable": len(SENSITIVITY_QOIS) - len(changes),
        "qualification": QUALIFICATION,
    }


def assess_sensitivity(
    levels: List[Dict[str, Any]],
    tolerance: Optional[float] = SENSITIVITY_TOLERANCE,
    *,
    requested: bool = True,
) -> Dict[str, Any]:
    """Deterministic verdict on the cross-grid evidence. Withholds, never guesses.

    Returns a status and, when a criterion was supplied, whether the evidence
    satisfies it. With fewer than two grids there is nothing to compare. With
    no criterion registered the comparison is reported and the verdict is
    explicitly withheld rather than defaulted either way.
    """
    comparisons = [
        compare_grids(levels[i - 1], levels[i]) for i in range(1, len(levels))
    ]
    latest = comparisons[-1] if comparisons else None

    if len(levels) < 2:
        status = NOT_ESTABLISHED
        reason = (
            "A single grid cannot show how the solution depends on the grid. "
            "One healthy solution is not a resolution assessment."
        )
    elif tolerance is None:
        status = CRITERION_NOT_REGISTERED
        reason = SENSITIVITY_CRITERION_SOURCE
    elif latest["max_abs_relative_change"] is None:
        status = NOT_ESTABLISHED
        reason = "No registered quantity was measurable on both grids."
    elif latest["max_abs_relative_change"] <= tolerance:
        status = WITHIN_TOLERANCE
        reason = (
            f"Largest relative change {latest['max_abs_relative_change']:.4g} "
            f"across {latest['quantities_compared']} registered quantities is "
            f"within the supplied criterion {tolerance:g} for {latest['pair']}."
        )
    else:
        status = ABOVE_TOLERANCE
        reason = (
            f"Largest relative change {latest['max_abs_relative_change']:.4g} "
            f"exceeds the supplied criterion {tolerance:g} for {latest['pair']}."
        )

    return {
        "status": status,
        "satisfied": status == WITHIN_TOLERANCE,
        "assessment_requested": bool(requested),
        "grids": len(levels),
        "tolerance": tolerance,
        "criterion_source": SENSITIVITY_CRITERION_SOURCE
        if tolerance is None
        else "Supplied explicitly for this study.",
        "reason": reason,
        "comparisons": comparisons,
        "latest_comparison": latest,
        "levels": levels,
        "policy": {
            "refinement_factor": MESH_REFINEMENT_FACTOR,
            "max_refinement_levels": MAX_REFINEMENT_LEVELS,
            "max_cells": MAX_STUDY_CELLS,
        },
        "qualification": QUALIFICATION,
    }
