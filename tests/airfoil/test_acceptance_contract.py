#!/usr/bin/env python3
"""The preregistered acceptance contract: thresholds, and that they bite.

Each threshold is asserted twice -- its value, and that a result just outside it
is refused. A tolerance nobody has watched fail is not a gate.
"""
from __future__ import annotations

import copy

import pytest

from src.families.airfoil.recipe import TOLERANCES
from src.families.airfoil.spec import AirfoilSpec
from src.pipeline.airfoil import postprocess as post
from src.pipeline.airfoil import validate as V


# -- registered threshold values ---------------------------------------
def test_symmetry_threshold():
    assert TOLERANCES["symmetry_abs_CL_max"] == 0.005


def test_drag_tolerance_is_ten_percent():
    assert TOLERANCES["drag_relative_tolerance"] == 0.10


def test_cp_rmse_threshold():
    assert TOLERANCES["cp_rmse_max_per_surface"] == 0.05


def test_grid_sensitivity_thresholds():
    assert TOLERANCES["grid_sensitivity_CD_relative_max"] == 0.02
    assert TOLERANCES["grid_sensitivity_cp_rmse_max"] == 0.01


def test_wall_resolution_thresholds():
    assert TOLERANCES["yplus_fraction_below_one_min"] == 0.99
    assert TOLERANCES["yplus_threshold"] == 1.0


def test_numerical_qualification_thresholds():
    assert TOLERANCES["residual_max_U"] == 1e-6
    assert TOLERANCES["residual_max_k"] == 1e-6
    assert TOLERANCES["residual_max_omega"] == 1e-6
    assert TOLERANCES["residual_max_p"] == 1e-5
    assert TOLERANCES["flux_imbalance_normalised_max"] == 1e-5
    assert TOLERANCES["drag_variation_relative_max"] == 0.002
    assert TOLERANCES["lift_range_max"] == 1e-4


# -- the qualified baseline passes -------------------------------------
def test_fully_qualified_evidence_passes(qualified_evidence):
    result = V.validate(qualified_evidence, 0.0)
    assert result["status"] == V.STATUS_PASS, result["failed_checks"]
    assert result["failed_checks"] == []
    assert result["unknown_checks"] == []


# -- each gate bites ---------------------------------------------------
@pytest.mark.parametrize(
    "path,value,expect_failed",
    [
        (("quantitative", "CL"), 0.0051, "zero_incidence_symmetry"),
        (("quantitative", "CD"), 0.0100, "experimental_drag"),
        (("solver", "normalised_flux_imbalance"), 2.0e-5, "numerical_qualification"),
    ],
)
def test_threshold_refuses_a_value_just_outside(qualified_evidence, path, value,
                                                expect_failed):
    evidence = copy.deepcopy(qualified_evidence)
    node = evidence
    for key in path[:-1]:
        node = node[key]
    node[path[-1]] = value
    result = V.validate(evidence, 0.0)
    assert result["status"] == V.STATUS_FAIL
    assert expect_failed in result["failed_checks"]


def test_residual_just_outside_fails(qualified_evidence):
    evidence = copy.deepcopy(qualified_evidence)
    evidence["solver"]["final_window_initial_residuals"]["U"] = 1.1e-6
    result = V.validate(evidence, 0.0)
    assert result["status"] == V.STATUS_FAIL
    assert "residual_U" in result["numerical_qualification"]["failed"]


def test_cp_rmse_just_outside_fails_per_surface(qualified_evidence):
    evidence = copy.deepcopy(qualified_evidence)
    evidence["quantitative"]["cp_rmse"]["lower"]["rmse"] = 0.0501
    result = V.validate(evidence, 0.0)
    assert result["status"] == V.STATUS_FAIL
    assert "surface_pressure" in result["failed_checks"]
    per = result["reference_checks"]["surface_pressure"]["per_surface"]
    assert per["upper"]["within_tolerance"] is True
    assert per["lower"]["within_tolerance"] is False


def test_unused_reference_points_fail_the_pressure_check(qualified_evidence):
    """"Use all supplied reference points" is enforced, not assumed."""
    evidence = copy.deepcopy(qualified_evidence)
    evidence["quantitative"]["cp_rmse"]["upper"]["unmatched_x_over_c"] = [0.95]
    result = V.validate(evidence, 0.0)
    assert result["status"] == V.STATUS_FAIL
    per = result["reference_checks"]["surface_pressure"]["per_surface"]["upper"]
    assert per["all_reference_points_used"] is False


@pytest.mark.parametrize("field,value", [("CD_relative_change", 0.021),
                                         ("cp_rmse_between_grids", 0.0101)])
def test_grid_sensitivity_gates_bite(qualified_evidence, field, value):
    evidence = copy.deepcopy(qualified_evidence)
    evidence["grid_sensitivity"][field] = value
    result = V.validate(evidence, 0.0)
    assert result["status"] == V.STATUS_FAIL
    assert "grid_sensitivity" in result["failed_checks"]


def test_yplus_just_below_the_required_fraction_fails(qualified_evidence):
    evidence = copy.deepcopy(qualified_evidence)
    evidence["quantitative"]["yplus"]["fraction_below_threshold"] = 0.98
    result = V.validate(evidence, 0.0)
    assert result["status"] == V.STATUS_FAIL
    assert "wall_resolution" in result["failed_checks"]
    # max y+ and exceedances are reported regardless of pass or fail.
    assert result["wall_resolution"]["max_yplus"] == 1.4
    assert result["wall_resolution"]["exceedance_regions"]


def test_drag_is_checked_against_every_applicable_dataset(qualified_evidence):
    evidence = copy.deepcopy(qualified_evidence)
    # Within 10% of one dataset, outside it for the other.
    evidence["quantitative"]["CD"] = 0.00819 * 1.02
    evidence["references"]["ladson_drag"][1]["CD_at_zero_incidence"] = 0.0070
    result = V.validate(evidence, 0.0)
    per = result["reference_checks"]["experimental_drag"]["per_dataset"]
    assert len(per) == 2
    assert per[0]["within_tolerance"] is True
    assert per[1]["within_tolerance"] is False
    assert result["status"] == V.STATUS_FAIL


# -- policy: a converged miss is not iterated away ---------------------
def test_a_reference_miss_is_not_sent_back_for_more_iterations(qualified_evidence):
    from src.families.airfoil.adapter import AirfoilAdapter

    evidence = copy.deepcopy(qualified_evidence)
    evidence["quantitative"]["CD"] = 0.0100      # outside the 10% drag gate
    adapter, spec = AirfoilAdapter(), AirfoilSpec()
    result = adapter.validate(evidence, spec)
    assert result["status"] == V.STATUS_FAIL
    assert adapter.maps_to_decision(result) == "REJECT"
    ruling = adapter.execute_action("CONTINUE_RUN", spec, evidence, validation=result)
    assert ruling.approved is False
    assert "must not be used to close a gap" in " ".join(ruling.reasons)


def test_missing_reference_evidence_is_inconclusive_not_a_pass(qualified_evidence):
    evidence = copy.deepcopy(qualified_evidence)
    evidence["references"]["ladson_drag"] = []
    result = V.validate(evidence, 0.0)
    assert result["status"] == V.STATUS_INCONCLUSIVE
    assert "experimental_drag" in result["unknown_checks"]


def test_unqualified_but_healthy_may_continue(qualified_evidence):
    from src.families.airfoil.adapter import AirfoilAdapter

    evidence = copy.deepcopy(qualified_evidence)
    evidence["solver"].pop("normalised_flux_imbalance")
    adapter, spec = AirfoilAdapter(), AirfoilSpec()
    result = adapter.validate(evidence, spec)
    assert result["status"] == V.STATUS_UNQUALIFIED
    assert adapter.maps_to_decision(result) == "CORRECT_AND_RERUN"
    ruling = adapter.execute_action("CONTINUE_RUN", spec, evidence, validation=result)
    assert ruling.approved is True
    assert ruling.corrected_spec is spec


# -- force normalisation ----------------------------------------------
def test_force_normalisation_uses_the_actual_span():
    out = post.normalise_forces((0.01, 0.0, 0.0), alpha_deg=0.0, span_m=0.5)
    assert out["force_reference"] == pytest.approx(0.5 * 1.0 * 1.0 * 1.0 * 0.5)
    assert out["CD"] == pytest.approx(0.01 / 0.25)
    assert out["CL"] == pytest.approx(0.0)


def test_force_normalisation_resolves_along_the_freestream():
    # A force purely along the rotated freestream is all drag, no lift.
    import math

    a = math.radians(10.0)
    force = (math.cos(a) * 0.02, math.sin(a) * 0.02, 0.0)
    out = post.normalise_forces(force, alpha_deg=10.0, span_m=1.0)
    assert out["CL"] == pytest.approx(0.0, abs=1e-15)
    assert out["CD"] == pytest.approx(0.02 / 0.5)


def test_cp_rmse_is_absolute_and_reports_unmatched_points():
    computed = [(0.0, -1.0), (1.0, -1.0)]
    reference = [(0.0, -1.1), (0.5, -1.1), (2.0, -1.0)]
    out = post.cp_rmse(computed, reference)
    assert out["n_matched"] == 2
    assert out["unmatched_x_over_c"] == [2.0]
    assert out["rmse"] == pytest.approx(0.1, rel=1e-9)
    assert "absolute" in out["metric"]


def test_yplus_statistics_are_surface_length_weighted():
    samples = [
        {"yplus": 0.5, "length": 9.0, "x_over_c": 0.5, "surface": "upper"},
        {"yplus": 2.0, "length": 1.0, "x_over_c": 0.01, "surface": "upper"},
    ]
    stats = post.yplus_statistics(samples)
    assert stats["fraction_below_threshold"] == pytest.approx(0.9)
    assert stats["max_yplus"] == 2.0
    assert stats["n_exceedances"] == 1
    assert stats["weighting"] == "surface length"
