#!/usr/bin/env python3
"""Deterministic validation for Family 3 against the PREREGISTERED contract.

Every threshold comes from src/families/airfoil/recipe.py TOLERANCES. None of
them is computed from the result being judged, and none may be widened after a
result is seen.

Two dispositions are kept apart, deliberately:

  hard checks       numerical qualification, wall resolution, mesh audit. A
                    failure here means the run is not a trustworthy candidate.
  reference checks  symmetry, experimental drag, surface pressure, grid
                    sensitivity. These are the validation CLAIM.

A numerically qualified run that misses a reference check is NOT sent back for
more iterations. It fails the claim, or is INCONCLUSIVE when the reference
evidence is unavailable. More iterations cannot fix disagreement with an external
reference, and pretending otherwise is how tuning starts.
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Optional

from src.families.airfoil.recipe import TOLERANCES

STATUS_PASS = "PASS_AIRFOIL_CANONICAL"
STATUS_FAIL = "FAIL"
STATUS_INCONCLUSIVE = "INCONCLUSIVE_REFERENCE_EVIDENCE_UNAVAILABLE"
STATUS_UNQUALIFIED = "NUMERICALLY_UNQUALIFIED"

HARD_PASS = "PASS_HARD_CHECKS"
HARD_FAIL = "FAIL_HARD_CHECKS"


def _finite(value: Any) -> bool:
    return isinstance(value, (int, float)) and math.isfinite(float(value))


# ----------------------------------------------------------------------
def numerical_qualification(evidence: Dict[str, Any]) -> Dict[str, Any]:
    """Criterion 6, over the final `qualification_window` iterations."""
    q = evidence.get("solver", {}) or {}
    residuals = q.get("final_window_initial_residuals") or {}
    checks: Dict[str, Optional[bool]] = {}
    measured: Dict[str, Any] = {"residuals": residuals}

    for field, key in (
        ("U", "residual_max_U"),
        ("k", "residual_max_k"),
        ("omega", "residual_max_omega"),
        ("p", "residual_max_p"),
    ):
        value = residuals.get(field)
        checks[f"residual_{field}"] = (
            bool(_finite(value) and float(value) <= TOLERANCES[key])
            if value is not None else None
        )

    flux = q.get("normalised_flux_imbalance")
    checks["flux_imbalance"] = (
        bool(_finite(flux) and abs(float(flux))
             <= TOLERANCES["flux_imbalance_normalised_max"])
        if flux is not None else None
    )
    measured["normalised_flux_imbalance"] = flux

    checks["no_nan_inf"] = (
        not bool(q.get("nan_detected")) and not bool(q.get("inf_detected"))
        if ("nan_detected" in q or "inf_detected" in q) else None
    )
    checks["physical_turbulence_fields"] = (
        bool(q.get("k_positive")) and bool(q.get("omega_positive"))
        and bool(q.get("nut_finite_nonnegative"))
        if "k_positive" in q else None
    )
    checks["no_persistent_bounding"] = (
        not bool(q.get("persistent_bounding")) if "persistent_bounding" in q else None
    )

    forces = evidence.get("quantitative", {}) or {}
    drag_var = (forces.get("CD_series_statistics") or {}).get("relative_variation")
    checks["drag_variation"] = (
        bool(_finite(drag_var)
             and abs(float(drag_var)) <= TOLERANCES["drag_variation_relative_max"])
        if drag_var is not None else None
    )
    lift_range = (forces.get("CL_series_statistics") or {}).get("range")
    checks["lift_range"] = (
        bool(_finite(lift_range)
             and abs(float(lift_range)) <= TOLERANCES["lift_range_max"])
        if lift_range is not None else None
    )
    checks["surface_distributions_stable"] = (
        bool(forces.get("surface_distributions_stable"))
        if "surface_distributions_stable" in forces else None
    )
    measured["CD_relative_variation"] = drag_var
    measured["CL_range"] = lift_range

    failed = [k for k, v in checks.items() if v is False]
    unknown = [k for k, v in checks.items() if v is None]
    return {
        "checks": checks,
        "failed": failed,
        "unknown": unknown,
        "qualified": not failed and not unknown,
        "measured": measured,
        "window": q.get("qualification_window"),
    }


def wall_resolution(evidence: Dict[str, Any]) -> Dict[str, Any]:
    """Criterion 5. Reports max y+ and every exceedance region regardless."""
    stats = (evidence.get("quantitative", {}) or {}).get("yplus") or {}
    fraction = stats.get("fraction_below_threshold")
    passed = (
        bool(_finite(fraction)
             and float(fraction) >= TOLERANCES["yplus_fraction_below_one_min"])
        if fraction is not None else None
    )
    return {
        "passed": passed,
        "required_fraction": TOLERANCES["yplus_fraction_below_one_min"],
        "threshold": TOLERANCES["yplus_threshold"],
        "fraction_below_threshold": fraction,
        "max_yplus": stats.get("max_yplus"),
        "max_yplus_location": stats.get("max_yplus_location"),
        "exceedance_regions": stats.get("exceedance_regions", []),
        "by_surface": stats.get("by_surface", {}),
    }


def symmetry(evidence: Dict[str, Any], alpha_deg: float) -> Dict[str, Any]:
    """Criterion 1. A NUMERICAL symmetry check, not experimental lift accuracy."""
    if abs(float(alpha_deg)) > 1e-12:
        return {
            "applicable": False,
            "passed": None,
            "note": "the zero-incidence symmetry check applies only at alpha = 0",
        }
    cl = (evidence.get("quantitative", {}) or {}).get("CL")
    limit = TOLERANCES["symmetry_abs_CL_max"]
    return {
        "applicable": True,
        "passed": bool(_finite(cl) and abs(float(cl)) <= limit)
        if cl is not None else None,
        "CL": cl,
        "limit": limit,
        "interpretation": "numerical symmetry, NOT an experimental lift requirement",
    }


def experimental_drag(evidence: Dict[str, Any]) -> Dict[str, Any]:
    """Criterion 2, against EVERY applicable tripped Ladson dataset."""
    quant = evidence.get("quantitative", {}) or {}
    cd = quant.get("CD")
    refs = (evidence.get("references", {}) or {}).get("ladson_drag") or []
    tol = TOLERANCES["drag_relative_tolerance"]
    if not refs:
        return {
            "passed": None,
            "reason": "no registered tripped Ladson drag reference is available",
            "tolerance": tol,
        }
    if not _finite(cd):
        return {"passed": None, "reason": "no computed CD", "tolerance": tol}

    per_dataset = []
    for ref in refs:
        cd_ref = float(ref["CD_at_zero_incidence"])
        error = abs(float(cd) - cd_ref) / abs(cd_ref) if cd_ref else None
        per_dataset.append(
            {
                "dataset": ref["dataset"],
                "CD_reference": cd_ref,
                "CD_computed": float(cd),
                "relative_error": error,
                "within_tolerance": bool(error is not None and error <= tol),
                "interpolation": ref,
            }
        )
    return {
        "passed": all(d["within_tolerance"] for d in per_dataset),
        "tolerance": tol,
        "per_dataset": per_dataset,
        "note": "experimental incidence offset preserved; CFD alpha never tuned",
    }


def surface_pressure(evidence: Dict[str, Any]) -> Dict[str, Any]:
    """Criterion 3. Independent per-surface ABSOLUTE Cp RMSE."""
    rmse = (evidence.get("quantitative", {}) or {}).get("cp_rmse") or {}
    limit = TOLERANCES["cp_rmse_max_per_surface"]
    if not rmse:
        return {
            "passed": None,
            "reason": "no registered NASA CFL3D Cp comparison was computed",
            "limit": limit,
        }
    per_surface = {}
    for surface in ("upper", "lower"):
        entry = rmse.get(surface) or {}
        value = entry.get("rmse")
        unmatched = entry.get("unmatched_x_over_c") or []
        per_surface[surface] = {
            "rmse": value,
            "limit": limit,
            "within_tolerance": bool(_finite(value) and float(value) <= limit),
            "n_reference_points": entry.get("n_reference_points"),
            "n_matched": entry.get("n_matched"),
            "unmatched_x_over_c": unmatched,
            "all_reference_points_used": not unmatched,
        }
    passed = all(
        s["within_tolerance"] and s["all_reference_points_used"]
        for s in per_surface.values()
    )
    return {
        "passed": passed,
        "limit": limit,
        "metric": "absolute RMSE; relative error is never used near Cp = 0",
        "per_surface": per_surface,
    }


def grid_sensitivity(evidence: Dict[str, Any]) -> Dict[str, Any]:
    """Criterion 4. A demonstration, explicitly not a formal asymptotic GCI."""
    data = evidence.get("grid_sensitivity") or {}
    cd_tol = TOLERANCES["grid_sensitivity_CD_relative_max"]
    cp_tol = TOLERANCES["grid_sensitivity_cp_rmse_max"]
    if not data:
        return {
            "passed": None,
            "reason": (
                "the sensitivity grid result is not present; a single grid cannot "
                "demonstrate grid sensitivity"
            ),
            "CD_tolerance": cd_tol,
            "cp_rmse_tolerance": cp_tol,
        }
    cd_change = data.get("CD_relative_change")
    cp_rmse = data.get("cp_rmse_between_grids")
    return {
        "passed": bool(
            _finite(cd_change) and abs(float(cd_change)) <= cd_tol
            and _finite(cp_rmse) and float(cp_rmse) <= cp_tol
        ),
        "CD_relative_change": cd_change,
        "CD_tolerance": cd_tol,
        "cp_rmse_between_grids": cp_rmse,
        "cp_rmse_tolerance": cp_tol,
        "canonical_cells": data.get("canonical_cells"),
        "sensitivity_cells": data.get("sensitivity_cells"),
        "interpretation": "grid-sensitivity demonstration, not formal asymptotic GCI",
    }


# ----------------------------------------------------------------------
def validate(evidence: Dict[str, Any], alpha_deg: float = 0.0) -> Dict[str, Any]:
    """The family's deterministic authority. Returns a status and full evidence."""
    audit = (evidence.get("mesh", {}) or {}).get("audit_status")

    hard: Dict[str, Optional[bool]] = {
        "mesh_audit_passed": (audit == "MESH_AUDIT_PASSED") if audit else None,
        "registered_assets_ok": (
            bool((evidence.get("provenance", {}) or {}).get("assets_ok"))
            if evidence.get("provenance") else None
        ),
        "solver_completed": (
            bool((evidence.get("solver", {}) or {}).get("completed"))
            if "completed" in (evidence.get("solver") or {}) else None
        ),
        "recipe_unchanged": (
            bool((evidence.get("provenance", {}) or {}).get("recipe_unchanged"))
            if evidence.get("provenance") else None
        ),
        "second_order_schemes_used": (
            bool((evidence.get("provenance", {}) or {}).get("second_order_schemes"))
            if evidence.get("provenance") else None
        ),
    }

    qualification = numerical_qualification(evidence)
    wall = wall_resolution(evidence)
    hard["numerical_qualification"] = (
        True if qualification["qualified"]
        else (False if qualification["failed"] else None)
    )
    hard["wall_resolution"] = wall["passed"]

    reference = {
        "zero_incidence_symmetry": symmetry(evidence, alpha_deg),
        "experimental_drag": experimental_drag(evidence),
        "surface_pressure": surface_pressure(evidence),
        "grid_sensitivity": grid_sensitivity(evidence),
    }

    hard_failed = [k for k, v in hard.items() if v is False]
    hard_unknown = [k for k, v in hard.items() if v is None]

    ref_results = {
        name: block.get("passed")
        for name, block in reference.items()
        if block.get("applicable", True)
    }
    ref_failed = [k for k, v in ref_results.items() if v is False]
    ref_unknown = [k for k, v in ref_results.items() if v is None]

    if hard_failed:
        status = STATUS_FAIL
    elif hard_unknown:
        status = STATUS_UNQUALIFIED
    elif ref_failed:
        # The validation CLAIM fails. This is NOT a request for more iterations.
        status = STATUS_FAIL
    elif ref_unknown:
        status = STATUS_INCONCLUSIVE
    else:
        status = STATUS_PASS

    return {
        "family": "airfoil",
        "status": status,
        "alpha_deg": alpha_deg,
        "hard_checks": hard,
        "hard_checks_status": HARD_FAIL if hard_failed else HARD_PASS,
        "failed_checks": hard_failed + ref_failed,
        "unknown_checks": hard_unknown + ref_unknown,
        "numerical_qualification": qualification,
        "wall_resolution": wall,
        "reference_checks": reference,
        "tolerances": dict(TOLERANCES),
        "policy": (
            "a numerically qualified run that misses a registered external-reference "
            "criterion FAILS the claim or is INCONCLUSIVE; it is never sent back for "
            "more iterations to close the gap"
        ),
        "provenance_note": (
            "NASA CFD reference is compressible at M = 0.15; this is an "
            "incompressible Foundation-v14 validation against external evidence, "
            "not an exact NASA-code reproduction"
        ),
        "authority": "deterministic",
    }
