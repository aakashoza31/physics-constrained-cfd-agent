#!/usr/bin/env python3
"""Evidence collection for Family 3, in the shared evidence shape.

Reads artefacts a completed run left on disk and assembles them; it computes
nothing scientific beyond the post-processing in postprocess.py, and it decides
nothing. It never launches a solver, so an archived run can be re-judged for free.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.families.airfoil.spec import AirfoilSpec
from src.pipeline.airfoil import assets as asset_mod
from src.pipeline.airfoil import postprocess as post
from src.pipeline.airfoil import references as refs
from src.pipeline.airfoil.build import FIXED_RECIPE_FILES, recipe_fingerprint


def _read_json(path: Path) -> Optional[Dict[str, Any]]:
    path = Path(path)
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def assemble(
    *,
    spec: AirfoilSpec,
    out_dir: Path,
    case: Optional[Path] = None,
    repo_root: Optional[Path] = None,
) -> Dict[str, Any]:
    """Assemble shared-shape evidence from an output directory. No CFD."""
    out_dir = Path(out_dir)
    raw_forces = _read_json(out_dir / "forces.json") or {}
    surface = _read_json(out_dir / "surface.json") or {}
    solver = _read_json(out_dir / "solver.json") or {}
    audit = _read_json(out_dir / "mesh_audit.json") or {}
    sensitivity = _read_json(out_dir / "grid_sensitivity.json") or {}

    quantitative: Dict[str, Any] = {}
    if raw_forces.get("force_total"):
        quantitative.update(
            post.normalise_forces(
                raw_forces["force_total"],
                alpha_deg=spec.alpha_deg,
                span_m=spec.span_m,
                u_inf=spec.u_inf,
                chord_m=spec.chord_m,
                rho=spec.rho,
            )
        )
    for key, series in (("CD", raw_forces.get("CD_history")),
                        ("CL", raw_forces.get("CL_history"))):
        if series:
            quantitative[f"{key}_series_statistics"] = post.series_statistics(series)
    if "surface_distributions_stable" in raw_forces:
        quantitative["surface_distributions_stable"] = raw_forces[
            "surface_distributions_stable"
        ]

    computed_cp: Dict[str, List[Any]] = {}
    if surface.get("points"):
        computed_cp = post.surface_cp(
            surface["points"], u_inf=spec.u_inf, rho=spec.rho
        )
        quantitative["cp"] = {k: [list(p) for p in v] for k, v in computed_cp.items()}
    if surface.get("yplus_samples"):
        quantitative["yplus"] = post.yplus_statistics(surface["yplus_samples"])

    reference_block: Dict[str, Any] = {"availability": refs.availability(repo_root)}
    derivations: Dict[str, Any] = {}
    try:
        drag = refs.ladson_zero_incidence_drag(repo_root)
        reference_block["ladson_drag"] = [d.to_dict() for d in drag]
        derivations["ladson_drag"] = drag[0].derivation.to_dict()
    except refs.ReferenceError as exc:
        reference_block["ladson_drag"] = []
        reference_block["ladson_drag_error"] = str(exc)
    try:
        cp_curves = refs.cfl3d_cp(repo_root)
        cp_ref = cp_curves.for_surfaces()
        reference_block["cfl3d_cp"] = cp_curves.to_dict()
        derivations["cfl3d_cp"] = cp_curves.derivation.to_dict()
        if computed_cp:
            quantitative["cp_rmse"] = {
                surf: post.cp_rmse(computed_cp.get(surf, []), cp_ref[surf])
                for surf in cp_ref
            }
    except refs.ReferenceError as exc:
        reference_block["cfl3d_cp_error"] = str(exc)
    try:
        forces = refs.cfl3d_forces(repo_root)
        reference_block["cfl3d_forces"] = forces["rows"]
        derivations["cfl3d_forces"] = forces["derivation"]
    except refs.ReferenceError as exc:
        reference_block["cfl3d_forces_error"] = str(exc)
    try:
        cf = refs.cfl3d_cf(repo_root)
        reference_block["cfl3d_cf"] = cf.to_dict()
        derivations["cfl3d_cf"] = cf.derivation.to_dict()
        reference_block["cf_role"] = (
            "supporting CFD evidence only; never an acceptance gate"
        )
    except refs.ReferenceError as exc:
        reference_block["cfl3d_cf_error"] = str(exc)
    reference_block["derived_artifacts"] = derivations

    asset_audit = asset_mod.audit_assets(repo_root)
    fingerprint = recipe_fingerprint(case) if case else {}

    return {
        "family": "airfoil",
        "spec": spec.to_dict(),
        "mesh": {
            "audit_status": audit.get("status"),
            "cells": (audit.get("provenance") or {}).get("converted_cells"),
            "provenance": audit.get("provenance", {}),
            "grid": spec.grid,
        },
        "solver": {
            **solver,
            "qualification_window": spec.qualification_window,
        },
        "conservation": {
            "normalised_flux_imbalance": solver.get("normalised_flux_imbalance"),
        },
        "stationarity": {
            "note": "steady RANS: stationarity is the residual/force plateau",
            "CD_series_statistics": quantitative.get("CD_series_statistics"),
            "CL_series_statistics": quantitative.get("CL_series_statistics"),
        },
        "quantitative": quantitative,
        "references": reference_block,
        "grid_sensitivity": sensitivity,
        "provenance": {
            "assets_ok": bool(asset_audit["all_required_ok"]),
            "asset_audit": asset_audit,
            "recipe_fingerprint": fingerprint,
            "recipe_unchanged": bool(fingerprint) and len(fingerprint) == len(
                FIXED_RECIPE_FILES
            ),
            "second_order_schemes": True,
            "reference_derivations": derivations,
            "nasa_reference_mach": 0.15,
            "our_formulation": "incompressible, isothermal",
            "exact_reproduction_claim": "none",
        },
    }
