#!/usr/bin/env python3
"""Deterministic scientific validator for the 2D forward-step family.

PROVENANCE
----------
Structure follows ``src/pipeline/forward_step/validate.py``: evidence is sorted
into HARD CHECKS, MEASURED DIAGNOSTICS and REFERENCE COMPARISONS, and a check
is only hard when it has a scientifically justified pass condition.

IMPORTANT DIFFERENCE FROM THE NOZZLE FAMILY
-------------------------------------------
The nozzle validator requires stationarity: it integrates to a steady state and
refuses anything still evolving. The canonical forward-step solution is still
evolving at t = 4, so a steady-state criterion would be scientifically wrong
here and is deliberately absent. "Has the transient run far enough" is not
decided by a stationarity threshold; it is decided by whether the requested
horizon was reached, which the spec declares.

No threshold in this file was chosen to make a particular case pass. Quantities
without a defensible pass condition are reported as MEASURED, not graded.
"""
from __future__ import annotations

from typing import Any, Dict, List

from .spec import ForwardStep2DSpec

STATUS_PASS = "PASS_2D_FORWARD_STEP"
STATUS_FAIL = "FAIL"
STATUS_INCOMPLETE = "INCOMPLETE_HORIZON_NOT_REACHED"


def validate(d: Dict[str, Any]) -> Dict[str, Any]:
    spec = ForwardStep2DSpec.from_dict(d["spec"])

    # ---------------- hard checks ------------------------------------
    # Each of these has a justification that does not depend on the answer.
    hard: Dict[str, bool] = {
        # the solver ran to its requested horizon and exited cleanly
        "solver_completed": bool(d["solver_completed"]),
        "no_fatal_error": not bool(d["fatal_error"]),
        # the mesh is valid and genuinely planar
        "mesh_ok": bool(d["mesh_ok"]),
        "two_solution_directions": bool(d["two_solution_directions"]),
        "mesh_stage_clean": d.get("mesh_failed_step") in (None, ""),
        "cell_count_matches_spec": bool(d["cell_count_matches_spec"]),
        "expected_boundaries_present": bool(
            d["boundary"]["expected_patches_present"]
        ),
        "planar_empty_patches": bool(d["boundary"]["empty_patch_present"])
        and d["boundary"]["cyclic_patch_count"] == 0,
        # the trusted numerical recipe was not edited to obtain a result
        "fixed_recipe_unchanged": bool(d["fixed_recipe_unchanged"]),
        # thermodynamic admissibility, at every saved state and every step
        "finite_all_saved": bool(d["finite_all_saved"]),
        "positive_all_saved": bool(d["positive_all_saved"]),
        "positive_every_step": bool(
            all(v > 0 for v in d["minima_every_step"].values())
        ),
        # the time integration behaved
        "courant_finite_positive": bool(d["courant_finite_positive"]),
        # the requested supersonic inflow was actually imposed
        "supersonic_inlet": bool(d["realized_inlet_Mach"] > 1),
        "initial_state_as_specified": max(d["initial_state_errors"].values())
        < 1e-9,
        # solid boundaries are impermeable: a wall that leaks mass is a defect,
        # and the tolerance is a floating-point scale, not a tuned band
        "impermeable_walls": d["mass"]["impermeable_flux_max_abs"]
        < 1e-10 * abs(d["mass"]["final_inlet"] or 1.0),
        # discrete storage balance closes to round-off for an explicit update
        "transient_mass_closure": d["mass"]["relative_residual_max"] < 1e-6,
    }

    # A compression system must exist for supersonic flow over a step. This is
    # a direction-of-change test only: p, rho and T must rise across the
    # detected front. No magnitude is required.
    jumps = d.get("shock", {}).get("jumps", {})
    shock: Dict[str, bool] = {
        f"{k}_rises_across_front": jumps[k] > 1 for k in ("p", "rho", "T") if k in jumps
    }
    if not jumps:
        shock["compression_front_measurable"] = False

    checks = {**hard, **shock}
    failed: List[str] = [k for k, v in checks.items() if not v]

    # ---------------- disposition ------------------------------------
    if not d.get("reached_requested_end_time", False) and not failed:
        status = STATUS_INCOMPLETE
    elif failed:
        status = STATUS_FAIL
    else:
        status = STATUS_PASS

    result: Dict[str, Any] = {
        "status": status,
        "family": spec.family,
        "failed_checks": failed,
        "hard_checks": hard,
        "shock_compression": shock,
        "horizon": {
            "requested_end_time": d["requested_end_time"],
            "final_time": d["final_time"],
            "reached": bool(d.get("reached_requested_end_time", False)),
            "saved_states": d["saved_times"],
            "solver_runs": d.get("solver_runs"),
            "continuation_used": d.get("continuation_used"),
        },
        # ---------------- measured, not graded ------------------------
        "measured": {
            "courant": {
                "status": "MEASURED",
                "data": d["Co"],
                "note": (
                    "maxCo is a controller target, not a strict per-step cap. "
                    "Small overshoots are expected and are not graded."
                ),
            },
            "transient_conservation": {"status": "MEASURED", "data": d["mass"]},
            "transient_evolution": {
                "status": "MEASURED_NOT_REQUIRED_STEADY",
                "data": d.get("transient_evolution", {}),
                "note": (
                    "The canonical forward-step solution is still evolving at "
                    "t = 4. No stationarity criterion is applied to this family."
                ),
            },
            "shock_structure": {"status": "MEASURED", "data": d.get("shock", {})},
            "field_ranges": {"status": "MEASURED", "data": d["final_ranges"]},
            "mesh_quality": {
                "status": "MEASURED",
                "data": {
                    k: d.get(k)
                    for k in (
                        "max_nonorthogonality",
                        "max_skewness",
                        "max_aspect_ratio",
                    )
                },
            },
        },
        # ---------------- reference comparison ------------------------
        "reference_comparison": d.get(
            "reference_comparison", {"status": "PENDING_NO_REFERENCE_PACKAGE"}
        ),
        "canonical_case": spec.is_canonical,
        # ---------------- explicit open items -------------------------
        "unresolved": [
            "Mesh and time-step independence for this family",
            "Exact numerical momentum and energy boundary-flux closure",
            "Independent quantitative benchmark uncertainty",
            "Corner-singularity sensitivity at the step shoulder",
        ],
        "claim_boundary": (
            "Within the registered 2D forward-step Euler family only. This is "
            "not a general CFD validity claim, not a mesh-independence claim, "
            "not a steady-state claim and not experimental validation."
        ),
    }

    if spec.is_canonical and result["reference_comparison"].get("status", "").startswith(
        "PENDING"
    ):
        result["reference_comparison"]["note"] = (
            "This run reproduces the canonical tutorial specification, so it is "
            "the natural anchor for a future reference comparison once the "
            "trusted 2D reference package is available in the repository."
        )

    return result
