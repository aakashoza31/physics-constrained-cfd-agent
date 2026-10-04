#!/usr/bin/env python3
"""Fault injection: seeded defects the deterministic gates must catch.

Each fault is a pure function on an evidence document. Nothing here touches a
case or launches CFD, so the whole suite runs in a test session, and each fault
names the gate it is supposed to trip so a miss is legible rather than just a
number in a table.

Faults are deliberately mechanical corruptions of MEASURED quantities. They do
not encode any scientific threshold: whether a corrupted value should fail is
the registered validator's business, which is the point of the experiment.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional


@dataclass(frozen=True)
class Fault:
    """One seeded defect."""

    name: str
    #: The deterministic check expected to fail. Empty means "any refusal".
    expected_check: str
    #: Expected terminal decision under the full constrained agent.
    expected_decision: str
    description: str
    apply: Callable[[Dict[str, Any]], Dict[str, Any]]
    families: tuple = ("forward_step_2d",)

    def __call__(self, evidence: Dict[str, Any]) -> Dict[str, Any]:
        return self.apply(copy.deepcopy(evidence))


def _raw(ev: Dict[str, Any]) -> Dict[str, Any]:
    return ev["raw_diagnostics"]


# ----------------------------------------------------------------------
# Forward-step faults. Each edits the family's own diagnostics document, which
# is exactly what the registered validator consumes.
# ----------------------------------------------------------------------
def _f_solver_not_completed(ev):
    _raw(ev)["solver_completed"] = False
    ev["solver"]["solver_completed"] = False
    return ev


def _f_fatal_error(ev):
    _raw(ev)["fatal_error"] = True
    ev["solver"]["fatal_error"] = True
    return ev


def _f_mesh_invalid(ev):
    _raw(ev)["mesh_ok"] = False
    ev["mesh"]["mesh_ok"] = False
    return ev


def _f_cell_count_mismatch(ev):
    _raw(ev)["cell_count_matches_spec"] = False
    ev["mesh"]["cell_count_matches_spec"] = False
    return ev


def _f_recipe_edited(ev):
    _raw(ev)["fixed_recipe_unchanged"] = False
    return ev


def _f_negative_pressure(ev):
    _raw(ev)["positive_all_saved"] = False
    return ev


def _f_nonfinite_field(ev):
    _raw(ev)["finite_all_saved"] = False
    return ev


def _f_negative_step_minimum(ev):
    d = _raw(ev)
    minima = dict(d.get("minima_every_step") or {})
    if not minima:
        minima = {"p": 1.0}
    key = sorted(minima)[0]
    minima[key] = -1.0
    d["minima_every_step"] = minima
    return ev


def _f_mass_imbalance(ev):
    d = _raw(ev)
    d.setdefault("mass", {})["relative_residual_max"] = 1.0e-3
    return ev


def _f_leaking_wall(ev):
    d = _raw(ev)
    mass = d.setdefault("mass", {})
    mass["impermeable_flux_max_abs"] = abs(mass.get("final_inlet") or 1.0) * 1.0e-3
    return ev


def _f_restart_seam_discontinuous(ev):
    d = _raw(ev)
    cont = d.setdefault("mass", {}).setdefault("restart_continuity", {})
    cont["all_seams_continuous"] = False
    return ev


def _f_subsonic_inlet(ev):
    _raw(ev)["realized_inlet_Mach"] = 0.8
    return ev


def _f_initial_state_drift(ev):
    d = _raw(ev)
    errors = dict(d.get("initial_state_errors") or {})
    if not errors:
        errors = {"p": 0.0}
    errors[sorted(errors)[0]] = 1.0e-3
    d["initial_state_errors"] = errors
    return ev


def _f_missing_boundary(ev):
    d = _raw(ev)
    b = d.setdefault("boundary", {})
    b["expected_patches_present"] = False
    ev["mesh"]["boundary"] = b
    return ev


def _f_cyclic_patch_present(ev):
    d = _raw(ev)
    b = d.setdefault("boundary", {})
    b["cyclic_patch_count"] = 2
    ev["mesh"]["boundary"] = b
    return ev


def _f_courant_nonfinite(ev):
    _raw(ev)["courant_finite_positive"] = False
    return ev


def _f_three_dimensional(ev):
    _raw(ev)["two_solution_directions"] = False
    ev["mesh"]["two_solution_directions"] = False
    return ev


def _f_mesh_stage_dirty(ev):
    _raw(ev)["mesh_failed_step"] = "checkMesh"
    ev["mesh"]["mesh_failed_step"] = "checkMesh"
    return ev


FORWARD_STEP_FAULTS: List[Fault] = [
    Fault("solver_not_completed", "solver_completed", "REJECT",
          "solver exited before the requested horizon", _f_solver_not_completed),
    Fault("fatal_error_present", "no_fatal_error", "REJECT",
          "a genuine fatal signature in the raw solver log", _f_fatal_error),
    Fault("mesh_invalid", "mesh_ok", "REJECT",
          "checkMesh reported an invalid mesh", _f_mesh_invalid),
    Fault("cell_count_mismatch", "cell_count_matches_spec", "REJECT",
          "the mesh does not have the cells the spec asked for", _f_cell_count_mismatch),
    Fault("fixed_recipe_edited", "fixed_recipe_unchanged", "REJECT",
          "the trusted numerical recipe was modified to obtain a result", _f_recipe_edited),
    Fault("nonpositive_state", "positive_all_saved", "REJECT",
          "a saved field holds a non-positive pressure/temperature/density",
          _f_negative_pressure),
    Fault("nonfinite_state", "finite_all_saved", "REJECT",
          "a saved field holds NaN or Inf", _f_nonfinite_field),
    Fault("negative_step_minimum", "positive_every_step", "REJECT",
          "an intermediate step went non-physical even though saved states look fine",
          _f_negative_step_minimum),
    Fault("mass_imbalance", "transient_mass_closure", "REJECT",
          "discrete storage balance does not close", _f_mass_imbalance),
    Fault("leaking_wall", "impermeable_walls", "REJECT",
          "a solid boundary passes mass", _f_leaking_wall),
    Fault("restart_seam_discontinuous", "transient_mass_closure", "REJECT",
          "a restart did not continue the same state", _f_restart_seam_discontinuous),
    Fault("subsonic_inlet", "supersonic_inlet", "REJECT",
          "the realized inflow is not supersonic, outside the registered family envelope",
          _f_subsonic_inlet),
    Fault("initial_state_drift", "initial_state_as_specified", "REJECT",
          "the imposed initial state is not what the spec requested",
          _f_initial_state_drift),
    Fault("missing_boundary_patch", "expected_boundaries_present", "REJECT",
          "an expected boundary patch is absent", _f_missing_boundary),
    Fault("cyclic_patch_present", "planar_empty_patches", "REJECT",
          "a cyclic patch appeared in a family that must not have one",
          _f_cyclic_patch_present),
    Fault("courant_nonfinite", "courant_finite_positive", "REJECT",
          "the Courant number is not finite and positive", _f_courant_nonfinite),
    Fault("not_two_dimensional", "two_solution_directions", "REJECT",
          "the mesh has three solution directions in a 2D family",
          _f_three_dimensional),
    Fault("mesh_stage_dirty", "mesh_stage_clean", "REJECT",
          "a meshing stage reported a failure", _f_mesh_stage_dirty),
]

REGISTRY: Dict[str, List[Fault]] = {"forward_step_2d": FORWARD_STEP_FAULTS}


def faults_for(family: str) -> List[Fault]:
    return list(REGISTRY.get(family, []))


def by_name(family: str, name: str) -> Optional[Fault]:
    return next((f for f in faults_for(family) if f.name == name), None)
