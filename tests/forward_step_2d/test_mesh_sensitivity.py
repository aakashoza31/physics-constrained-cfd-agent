#!/usr/bin/env python3
"""Regression tests for autonomous mesh refinement / numerical sensitivity.

WHAT IS BEING PINNED
--------------------
A solution that passes every hard check has been shown healthy ON THE GRID IT
WAS COMPUTED ON. That is a different claim from "the answer no longer depends
on the grid", and a request that asks the second question cannot be answered
by the first. These tests pin that separation, the bounded refinement policy
the model cannot reach around, and the fact that a new mesh is a new solve.

THE ACCEPTANCE CRITERION IS DELIBERATELY ABSENT
-----------------------------------------------
No cross-grid tolerance exists in this repository, so none is used as a
default. Tests that need a verdict supply one explicitly and say so; the
default path asserts that the verdict is withheld rather than guessed.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from src.agents.forward_step_spec_agent import ForwardStepRequest, to_spec
from src.pipeline.forward_step_2d.spec import ForwardStep2DSpec
from src.reasoning.forward_step_actions import validate_action
from src.reasoning.forward_step_mesh_study import (
    ABOVE_TOLERANCE,
    CRITERION_NOT_REGISTERED,
    MAX_REFINEMENT_LEVELS,
    MAX_STUDY_CELLS,
    MESH_REFINEMENT_FACTOR,
    NOT_ESTABLISHED,
    SENSITIVITY_QOIS,
    SENSITIVITY_TOLERANCE,
    WITHIN_TOLERANCE,
    assess_sensitivity,
    can_refine,
    compare_grids,
    grid_record,
    refine,
    uniform_spacing,
)

_REPO = Path(__file__).resolve().parents[2]

# A deliberately coarse but entirely valid starting grid.
COARSE = ForwardStep2DSpec(nx=60, ny=20, sensitivity_assessment_requested=True)

HEALTHY_VALIDATION = {
    "status": "PASS_2D_FORWARD_STEP",
    "hard_checks_status": "PASS_HARD_CHECKS",
    "failed_checks": [],
}


def _diagnostics(front=0.35, stem=0.74, angle=61.3, p=7.49, rho=3.44, T=2.18):
    return {
        "fatal_error": False,
        "finite_all_saved": True,
        "positive_all_saved": True,
        "minima_every_step": {"rho": 0.1, "p": 0.1, "T": 0.5},
        "courant_finite_positive": True,
        "solver_completed": True,
        "final_time": 4.0,
        "reached_requested_end_time": True,
        "mass": {"relative_residual_max": 3.1e-11},
        "shock": {
            "lower_front_x": front,
            "upper_stem_x": stem,
            "regional_angle_deg": angle,
            "jumps": {"p": p, "rho": rho, "T": T},
        },
    }


def _levels(*specs_and_diagnostics):
    return [
        grid_record(spec, diagnostics, HEALTHY_VALIDATION)
        for spec, diagnostics in specs_and_diagnostics
    ]


def _gate(action, spec, diagnostics=None, validation=None, sensitivity=None, **kw):
    kw.setdefault("max_end_time", 12.0)
    kw.setdefault("iterations_used", 1)
    kw.setdefault("max_iterations", 6)
    return validate_action(
        action,
        spec,
        diagnostics if diagnostics is not None else _diagnostics(),
        validation or HEALTHY_VALIDATION,
        sensitivity=sensitivity,
        **kw,
    )


# ----------------------------------------------------------------------
# 1. a healthy single grid cannot answer a resolution question
# ----------------------------------------------------------------------


def test_1_single_healthy_grid_cannot_be_accepted_when_sensitivity_requested():
    levels = _levels((COARSE, _diagnostics()))
    sensitivity = assess_sensitivity(levels, tolerance=0.05, requested=True)

    assert sensitivity["status"] == NOT_ESTABLISHED
    assert sensitivity["satisfied"] is False

    refused = _gate("ACCEPT", COARSE, sensitivity=sensitivity)
    assert not refused.approved
    reason = " ".join(refused.reasons)
    assert "numerical-sensitivity assessment" in reason
    assert NOT_ESTABLISHED in reason


def test_1b_the_single_grid_is_still_healthy_in_its_own_right():
    """The distinction, not a downgrade: the grid itself is fine."""
    levels = _levels((COARSE, _diagnostics()))
    assert levels[0]["grid_health"]["hard_checks_status"] == "PASS_HARD_CHECKS"
    assert levels[0]["grid_health"]["failed_checks"] == []
    assert levels[0]["cells"] == 1008


def test_10_ordinary_requests_are_unaffected():
    """A request that asked no resolution question still accepts normally."""
    ordinary = ForwardStep2DSpec()
    assert ordinary.sensitivity_assessment_requested is False
    assert ordinary.refinement_level == 0

    sensitivity = assess_sensitivity(
        _levels((ordinary, _diagnostics())), tolerance=None, requested=False
    )
    approved = _gate("ACCEPT", ordinary, sensitivity=sensitivity)
    assert approved.approved


def test_10b_the_interpreter_does_not_set_the_flag_for_an_ordinary_request():
    plain = ForwardStepRequest(case_name="c", summary="x", mach=3.0)
    spec, _ = to_spec(plain)
    assert spec.sensitivity_assessment_requested is False
    assert spec.cells == 16128  # the registered canonical mesh

    asked = ForwardStepRequest(
        case_name="c",
        summary="x",
        mach=3.0,
        nx=60,
        ny=20,
        requests_mesh_sensitivity_assessment=True,
    )
    spec, provenance = to_spec(asked)
    assert spec.sensitivity_assessment_requested is True
    assert spec.cells == 1008
    assert "sensitivity_assessment_requested" in provenance["stated_by_user"]


def test_10c_the_interpreter_records_a_question_not_an_action():
    """The parser must not hard-code REFINE_MESH."""
    from src.agents.forward_step_spec_agent import SYSTEM_PROMPT

    assert "requests_mesh_sensitivity_assessment" in SYSTEM_PROMPT
    assert "Do NOT conclude that refinement is needed" in SYSTEM_PROMPT
    field = ForwardStepRequest.model_fields["requests_mesh_sensitivity_assessment"]
    assert "do not name an action" in field.description.lower()


# ----------------------------------------------------------------------
# 2, 3. a justified refinement is approved and bounded
# ----------------------------------------------------------------------


def test_2_justified_refinement_is_approved():
    levels = _levels((COARSE, _diagnostics()))
    sensitivity = assess_sensitivity(levels, tolerance=0.05, requested=True)

    approved = _gate("REFINE_MESH", COARSE, sensitivity=sensitivity)
    assert approved.approved
    assert approved.resulting_changes["next_level"] == 1
    assert approved.resulting_changes["cells"] == 4032


def test_3_refinement_maps_to_one_registered_deterministic_operation():
    refined = refine(COARSE)
    assert refined.nx == COARSE.nx * MESH_REFINEMENT_FACTOR
    assert refined.ny == COARSE.ny * MESH_REFINEMENT_FACTOR
    assert refined.refinement_level == 1
    # Geometry, physics and the numerical recipe are untouched.
    for field in ("length", "height", "step_x", "step_height", "span",
                  "mach", "pressure", "temperature", "max_co", "physics"):
        assert getattr(refined, field) == getattr(COARSE, field)


def test_3b_the_refined_grid_stays_uniform():
    """Factor 2 preserves the block split ratios; 1.5 does not."""
    assert uniform_spacing(COARSE)["uniform"] is True
    assert uniform_spacing(refine(COARSE))["uniform"] is True

    # The reason the generic 1.5 factor was not reused.
    awkward = ForwardStep2DSpec(nx=45, ny=15)
    assert uniform_spacing(awkward)["uniform"] is True
    by_one_and_a_half = ForwardStep2DSpec(
        nx=int(round(45 * 1.5)), ny=int(round(15 * 1.5))
    )
    assert uniform_spacing(by_one_and_a_half)["uniform"] is False


def test_3c_the_ladder_terminates_on_the_registered_canonical_mesh():
    """60x20 -> 120x40 -> 240x80, which is the canonical 16,128-cell grid."""
    grid = COARSE
    ladder = [grid.cells]
    for _ in range(MAX_REFINEMENT_LEVELS):
        grid = refine(grid)
        ladder.append(grid.cells)
    assert ladder == [1008, 4032, 16128]
    assert (grid.nx, grid.ny) == (240, 80)


def test_3d_the_model_cannot_choose_the_mesh():
    """REFINE_MESH carries no model-supplied geometry or resolution."""
    from src.reasoning.forward_step_diagnosis import ForwardStepDecision

    fields = set(ForwardStepDecision.model_fields)
    for forbidden in ("nx", "ny", "refinement_factor", "cells", "blockMeshDict"):
        assert forbidden not in fields


# ----------------------------------------------------------------------
# 4. a refined mesh is a fresh solve
# ----------------------------------------------------------------------


def test_4_a_new_mesh_is_never_a_latesttime_continuation():
    source = (_REPO / "scripts" / "run_forward_step_2d.py").read_text()
    # Continuation is keyed on the case, so a newly built grid cannot inherit
    # the append flag from the iteration counter.
    assert "append = last_executed_case == case" in source
    assert "last_executed_case = case" in source
    assert "fresh solve from the physical initial condition" in source


def test_4b_each_grid_gets_its_own_case_directory():
    """Previous grid evidence is never overwritten."""
    source = (_REPO / "scripts" / "run_forward_step_2d.py").read_text()
    assert 'f"case_L{level}" if level else "case"' in source
    assert "previous grid's case and evidence are left untouched" in source.replace(
        "\n", " "
    ).replace("  ", " ")


def test_4c_a_refined_grid_passes_the_same_mesh_gate():
    source = (_REPO / "scripts" / "run_forward_step_2d.py").read_text()
    assert "refined_case = self.build_and_mesh(runtime, root, code, current)" in source
    # A grid that failed its own mesh gate is not a refinement result.
    assert "if refined_case is None:" in source


# ----------------------------------------------------------------------
# 5. the cross-grid comparison
# ----------------------------------------------------------------------


def test_5_comparison_names_the_pair_and_uses_registered_quantities():
    levels = _levels(
        (COARSE, _diagnostics()),
        (refine(COARSE), _diagnostics(front=0.352, stem=0.745)),
    )
    comparison = compare_grids(levels[0], levels[1])

    assert comparison["coarse_level"] == 0 and comparison["fine_level"] == 1
    assert comparison["coarse_cells"] == 1008 and comparison["fine_cells"] == 4032
    assert comparison["refinement_ratio"] == 2
    assert "level 0 (1008 cells) -> level 1 (4032 cells)" == comparison["pair"]

    assert set(comparison["quantities"]) == {name for name, _, _ in SENSITIVITY_QOIS}
    front = comparison["quantities"]["lower_front_x"]
    assert front["coarse"] == 0.35 and front["fine"] == 0.352
    assert front["relative_change"] == pytest.approx(0.002 / 0.35)
    assert comparison["max_abs_relative_change"] == pytest.approx(
        max(0.002 / 0.35, 0.005 / 0.74)
    )


def test_5b_an_unmeasurable_quantity_is_reported_not_silently_dropped():
    coarse = grid_record(COARSE, _diagnostics(), HEALTHY_VALIDATION)
    blind = _diagnostics()
    blind["shock"] = {"available": False}
    fine = grid_record(refine(COARSE), blind, HEALTHY_VALIDATION)

    comparison = compare_grids(coarse, fine)
    assert comparison["quantities_compared"] == 0
    assert comparison["quantities_unavailable"] == len(SENSITIVITY_QOIS)
    for entry in comparison["quantities"].values():
        assert entry["status"] == "UNAVAILABLE_ON_AT_LEAST_ONE_GRID"

    verdict = assess_sensitivity([coarse, fine], tolerance=0.05)
    assert verdict["status"] == NOT_ESTABLISHED


def test_5c_no_fragile_image_derived_metrics_were_added():
    """Every compared quantity is one diagnostics already measures."""
    from src.pipeline.forward_step_2d import diagnostics as diag

    source = Path(diag.__file__).read_text()
    for _, _, path in SENSITIVITY_QOIS:
        assert f'"{path[-1]}"' in source or f"'{path[-1]}'" in source


# ----------------------------------------------------------------------
# 6, 7. the verdict, once a criterion is supplied
# ----------------------------------------------------------------------


def test_6_a_stable_comparison_can_satisfy_a_supplied_criterion():
    levels = _levels(
        (COARSE, _diagnostics()),
        (refine(COARSE), _diagnostics(front=0.3505, stem=0.7405)),
    )
    verdict = assess_sensitivity(levels, tolerance=0.05, requested=True)
    assert verdict["status"] == WITHIN_TOLERANCE
    assert verdict["satisfied"] is True

    approved = _gate("ACCEPT", refine(COARSE), sensitivity=verdict)
    assert approved.approved


def test_7_a_sensitive_comparison_permits_one_further_refinement():
    levels = _levels(
        (COARSE, _diagnostics()),
        (refine(COARSE), _diagnostics(front=0.30, stem=0.68, p=6.9)),
    )
    verdict = assess_sensitivity(levels, tolerance=0.02, requested=True)
    assert verdict["status"] == ABOVE_TOLERANCE
    assert verdict["satisfied"] is False

    medium = refine(COARSE)
    approved = _gate("REFINE_MESH", medium, sensitivity=verdict)
    assert approved.approved
    assert approved.resulting_changes["cells"] == 16128

    refused = _gate("ACCEPT", medium, sensitivity=verdict)
    assert not refused.approved


def test_7b_a_satisfied_criterion_stops_further_refinement():
    levels = _levels(
        (COARSE, _diagnostics()),
        (refine(COARSE), _diagnostics(front=0.3505)),
    )
    verdict = assess_sensitivity(levels, tolerance=0.05, requested=True)
    refused = _gate("REFINE_MESH", refine(COARSE), sensitivity=verdict)
    assert not refused.approved
    assert "already satisfied" in " ".join(refused.reasons)


# ----------------------------------------------------------------------
# the criterion is missing, and that is reported rather than guessed
# ----------------------------------------------------------------------


def test_no_cross_grid_tolerance_is_invented():
    assert SENSITIVITY_TOLERANCE is None

    levels = _levels(
        (COARSE, _diagnostics()),
        (refine(COARSE), _diagnostics(front=0.3505)),
    )
    verdict = assess_sensitivity(levels, requested=True)

    assert verdict["status"] == CRITERION_NOT_REGISTERED
    assert verdict["satisfied"] is False
    assert verdict["tolerance"] is None
    assert "NOT REGISTERED" in verdict["criterion_source"]
    # The comparison is still measured and reported in full.
    assert verdict["latest_comparison"]["max_abs_relative_change"] is not None


def test_an_unregistered_criterion_blocks_accept_rather_than_defaulting():
    levels = _levels(
        (COARSE, _diagnostics()),
        (refine(COARSE), _diagnostics(front=0.3505)),
    )
    verdict = assess_sensitivity(levels, requested=True)
    refused = _gate("ACCEPT", refine(COARSE), sensitivity=verdict)
    assert not refused.approved
    assert CRITERION_NOT_REGISTERED in " ".join(refused.reasons)


def test_the_study_does_not_claim_grid_convergence_or_gci():
    from src.reasoning import forward_step_mesh_study as study

    text = Path(study.__file__).read_text()
    assert "not a GCI" in text or "not a Grid Convergence Index" in text
    verdict = assess_sensitivity(_levels((COARSE, _diagnostics())))
    assert "sensitivity assessment, not grid convergence" in verdict["qualification"]


# ----------------------------------------------------------------------
# 8. bounds the model cannot pass
# ----------------------------------------------------------------------


def test_8_the_refinement_level_cap_is_enforced():
    grid = COARSE
    for _ in range(MAX_REFINEMENT_LEVELS):
        grid = refine(grid)
    assert grid.refinement_level == MAX_REFINEMENT_LEVELS

    with pytest.raises(ValueError, match="registered maximum"):
        refine(grid)

    verdict = assess_sensitivity(
        _levels((COARSE, _diagnostics()), (grid, _diagnostics(front=0.30))),
        tolerance=0.001,
        requested=True,
    )
    refused = _gate("REFINE_MESH", grid, sensitivity=verdict)
    assert not refused.approved
    assert "registered maximum" in " ".join(refused.reasons)


def test_8b_the_cell_budget_is_enforced():
    big = ForwardStep2DSpec(nx=300, ny=100)
    assert refine(big).cells <= MAX_STUDY_CELLS  # 100,800: still inside
    # 440x150 is 55,440 cells and valid; doubling it would be 221,760.
    bigger = ForwardStep2DSpec(nx=440, ny=150)
    assert bigger.cells == 55440
    with pytest.raises(ValueError, match="budget|bound"):
        refine(bigger)
    assert can_refine(bigger)["permitted"] is False


def test_8c_the_iteration_budget_also_stops_refinement():
    refused = _gate(
        "REFINE_MESH", COARSE, iterations_used=6, max_iterations=6
    )
    assert not refused.approved
    assert "budget" in " ".join(refused.reasons)


# ----------------------------------------------------------------------
# 9. refinement is not a universal repair
# ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "failure",
    ["mesh_ok", "two_solution_directions", "fixed_recipe_unchanged",
     "supersonic_inlet", "no_fatal_error"],
)
def test_9_an_invalid_mesh_is_not_refinement_recovery(failure):
    """A finer grid does not fix a broken one, a wrong inlet or an edited recipe."""
    broken = {
        "status": "FAIL",
        "hard_checks_status": "FAIL_HARD_CHECKS",
        "failed_checks": [failure],
    }
    refused = _gate("REFINE_MESH", COARSE, validation=broken)
    assert not refused.approved
    assert "not spatial-resolution problems" in " ".join(refused.reasons)


def test_9b_an_unhealthy_solution_cannot_justify_refinement():
    sick = _diagnostics()
    sick["positive_all_saved"] = False
    refused = _gate("REFINE_MESH", COARSE, diagnostics=sick)
    assert not refused.approved
    assert "not numerically healthy" in " ".join(refused.reasons)


def test_9c_refinement_needs_cfd_evidence_to_respond_to():
    nothing = _diagnostics()
    nothing["final_time"] = None
    refused = _gate("REFINE_MESH", COARSE, diagnostics=nothing)
    assert not refused.approved
    assert "no CFD evidence" in " ".join(refused.reasons)


def test_9d_a_failed_mesh_gate_on_a_refined_grid_is_a_mesh_rejection():
    source = (_REPO / "scripts" / "run_forward_step_2d.py").read_text()
    assert 'self.finish("MESH_REJECTED", f"level {level} failed at {failed}")' in source
