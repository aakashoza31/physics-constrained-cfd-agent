#!/usr/bin/env python3
"""Recipe v2: the near-trailing-edge surface distribution, and nothing else.

Every number here is recomputed from the recipe and compared with the frozen
value, so a silent change to either fails. No CFD, and no meshing except in the
two tests marked `slow`.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from src.pipeline.airfoil import geometry as G
from src.pipeline.airfoil import gmsh_pipeline as GP
from src.pipeline.airfoil import mesh_checks as MC
from src.pipeline.airfoil import mesh_hierarchy as MH
from src.pipeline.airfoil import mesh_levels as ML

slow = pytest.mark.slow
gmsh_required = pytest.mark.skipif(
    not GP.gmsh_status().get("available"), reason="gmsh is not installed"
)

#: Frozen v2 outcomes, as computed and reported.
FROZEN = {
    "coarse": {"n_body": 233, "n_te": 68, "per_side": 301, "delta": 2.3831e-7},
    "medium": {"n_body": 349, "n_te": 106, "per_side": 455, "delta": 1.0591556e-7},
    "fine": {"n_body": 524, "n_te": 165, "per_side": 689, "delta": 4.7073580e-8},
}
L_T_EXPECTED = 0.020195378182279167


# -- arc length --------------------------------------------------------
def test_surface_arc_length_from_the_partition_to_the_te():
    assert G.arc_length(0.98, 1.0) == pytest.approx(L_T_EXPECTED, rel=1e-13)


def test_arc_length_quadrature_is_converged():
    """Panel count must not move the answer: the integrand is smooth here."""
    reference = G.arc_length(0.98, 1.0, panels=1024)
    for panels in (16, 32, 64, 256):
        assert G.arc_length(0.98, 1.0, panels=panels) == pytest.approx(
            reference, rel=1e-13
        )


def test_arc_length_inversion_is_exact_at_both_ends():
    total = G.arc_length(0.98, 1.0)
    assert G.x_at_arc_from_te(0.0) == 1.0
    assert G.x_at_arc_from_te(total, x_min=0.5) == pytest.approx(0.98, abs=1e-14)


def test_arc_length_is_additive():
    a = G.arc_length(0.98, 0.99)
    b = G.arc_length(0.99, 1.0)
    assert a + b == pytest.approx(G.arc_length(0.98, 1.0), rel=1e-14)


# -- the partition and the body zone -----------------------------------
def test_partition_station_and_angle():
    assert ML.X_PARTITION == 0.98
    assert ML.THETA_T == pytest.approx(math.acos(1.0 - 2.0 * 0.98), rel=0, abs=0)
    assert ML.THETA_T == pytest.approx(2.857798544381465, rel=1e-15)


def test_body_interval_counts_are_the_frozen_rounded_values():
    for name, frozen in FROZEN.items():
        lv = ML.level(name)
        assert ML.body_intervals(lv) == frozen["n_body"]
        assert ML.body_intervals(lv) == round(lv.n_per_side * ML.THETA_T / math.pi)


def test_cosine_parameter_n_is_unchanged_from_v1():
    assert [ML.level(n).n_per_side for n in ML.LEVELS] == [256, 384, 576]


def test_body_stations_follow_the_truncated_cosine_law():
    lv = ML.level("coarse")
    n_body = ML.body_intervals(lv)
    plan = ML.surface_plan(lv)
    stations = G.v2_stations(
        n_body=n_body, n_te=plan["te_intervals"], x_partition=ML.X_PARTITION,
        delta_te=plan["first_interval_prescribed"],
        q_max=plan["growth_ratio_max"],
    )["stations"]
    for j in range(1, n_body):
        expected = 0.5 * (1.0 - math.cos(j * ML.THETA_T / n_body))
        assert stations[j] == pytest.approx(expected, rel=1e-15)
    assert stations[0] == 0.0
    assert stations[n_body] == 0.98
    assert stations[-1] == 1.0


# -- the TE progression ------------------------------------------------
def test_prescribed_first_te_interval_scales_as_r_to_the_minus_two():
    base = ML.DELTA_TE_BASE
    assert base == 2.3831e-7
    for name, frozen in FROZEN.items():
        lv = ML.level(name)
        delta = ML.delta_te(lv)
        assert delta == pytest.approx(base / lv.refinement ** 2, rel=1e-15)
        assert delta == pytest.approx(frozen["delta"], rel=1e-7)


def test_the_scaling_is_not_r_to_the_minus_one():
    """An r^-1 law would give a materially different spacing; guard against it."""
    lv = ML.level("fine")
    assert ML.delta_te(lv) != pytest.approx(ML.DELTA_TE_BASE / lv.refinement,
                                            rel=1e-3)
    assert ML.delta_te(lv) == pytest.approx(
        ML.DELTA_TE_BASE / lv.refinement ** 2, rel=1e-12
    )


def test_growth_limit_is_the_frozen_root():
    for name in ML.LEVELS:
        lv = ML.level(name)
        assert ML.te_growth_limit(lv) == pytest.approx(
            ML.Q_MAX_BASE ** (1.0 / lv.refinement), rel=1e-15
        )
    assert ML.te_growth_limit(ML.level("coarse")) == pytest.approx(1.15, rel=1e-15)


def test_te_interval_count_is_the_ceiling_formula():
    for name, frozen in FROZEN.items():
        lv = ML.level(name)
        first, q_max = ML.delta_te(lv), ML.te_growth_limit(lv)
        arc = G.arc_length(ML.X_PARTITION, 1.0)
        expected = math.ceil(
            math.log(1.0 + (q_max - 1.0) * arc / first) / math.log(q_max)
        )
        assert ML.te_progression(lv)["te_intervals"] == expected == frozen["n_te"]


def test_solved_growth_ratio_is_unique_and_within_the_limit():
    for name in ML.LEVELS:
        lv = ML.level(name)
        prog = ML.te_progression(lv)
        q, n = prog["growth_ratio"], prog["te_intervals"]
        assert 1.0 < q <= prog["growth_ratio_max"]
        series = prog["first_interval_prescribed"] * (q ** n - 1.0) / (q - 1.0)
        assert series == pytest.approx(prog["arc_length_partition_to_te"], rel=1e-12)


def test_the_progression_terminates_exactly_at_the_partition():
    for name in ML.LEVELS:
        prog = ML.te_progression(ML.level(name))
        assert prog["terminates_at_partition"] is True
        assert abs(prog["series_residual"]) <= 1e-12 * prog[
            "arc_length_partition_to_te"
        ]


def test_no_residual_sliver_interval_is_appended():
    """The TE zone holds exactly n_TE intervals, all on the progression."""
    for name, frozen in FROZEN.items():
        lv = ML.level(name)
        plan = ML.surface_plan(lv)
        build = G.v2_stations(
            n_body=plan["body_intervals"], n_te=plan["te_intervals"],
            x_partition=ML.X_PARTITION,
            delta_te=plan["first_interval_prescribed"],
            q_max=plan["growth_ratio_max"],
        )
        stations = build["stations"]
        assert len(stations) - 1 == frozen["per_side"]
        # arc lengths of the TE zone, measured from the trailing edge inward
        te_stations = stations[plan["body_intervals"]:]
        arcs = [G.arc_length(x, 1.0) for x in te_stations]
        intervals = [arcs[k] - arcs[k + 1] for k in range(len(arcs) - 1)]
        intervals.reverse()          # nearest the TE first
        q = build["growth_ratio"]
        first = plan["first_interval_prescribed"]
        for j, length in enumerate(intervals, start=1):
            assert length == pytest.approx(first * q ** (j - 1), rel=1e-7)
        assert len(intervals) == plan["te_intervals"]


def test_total_surface_intervals_supersede_v1():
    for name, frozen in FROZEN.items():
        lv = ML.level(name)
        plan = ML.surface_plan(lv)
        assert plan["intervals_per_side"] == frozen["per_side"]
        assert plan["intervals_per_side"] == frozen["n_body"] + frozen["n_te"]
        assert lv.airfoil_faces == 2 * frozen["per_side"]
        assert lv.airfoil_faces != 2 * lv.n_per_side      # v1 count superseded


def test_prescribed_te_spacing_matches_the_fan_spacing_by_design():
    """This is what v2 exists to do; the ratio must be ~1 at every level."""
    for name in ML.LEVELS:
        lv = ML.level(name)
        fan = ML.te_fan_spacing(lv)["fan_circumferential_spacing"]
        assert ML.delta_te(lv) / fan == pytest.approx(1.0, rel=1e-6)


# -- the geometry is untouched ------------------------------------------
def test_v2_stations_lie_on_the_unchanged_analytic_geometry():
    lv = ML.level("coarse")
    plan = ML.surface_plan(lv)
    sec, _ = G.section_v2(
        n_body=plan["body_intervals"], n_te=plan["te_intervals"],
        x_partition=ML.X_PARTITION,
        delta_te=plan["first_interval_prescribed"],
        q_max=plan["growth_ratio_max"],
    )
    assert sec.leading_edge == (0.0, 0.0)
    assert sec.trailing_edge == (1.0, 0.0)
    for x, y in sec.upper[1:-1]:
        assert y == G.ordinate(x)                  # exact, not approximated
    for (xu, yu), (xl, yl) in zip(sec.upper, sec.lower):
        assert xu == xl and yl == -yu              # exact reflection


def test_v2_stations_are_strictly_increasing():
    for name in ML.LEVELS:
        lv = ML.level(name)
        plan = ML.surface_plan(lv)
        stations = G.v2_stations(
            n_body=plan["body_intervals"], n_te=plan["te_intervals"],
            x_partition=ML.X_PARTITION,
            delta_te=plan["first_interval_prescribed"],
            q_max=plan["growth_ratio_max"],
        )["stations"]
        assert all(b > a for a, b in zip(stations, stations[1:]))
        assert stations.count(ML.X_PARTITION) == 1


# -- everything v2 must NOT change -------------------------------------
def test_fan_sectors_wall_layers_envelope_and_farfield_are_unchanged():
    assert [ML.level(n).fan_sectors for n in ML.LEVELS] == [24, 36, 54]
    assert MC.V2_FROZEN_FAN_SECTORS == {"coarse": 24, "medium": 36, "fine": 54}
    assert [ML.level(n).first_layer for n in ML.LEVELS] == [
        2.0e-6, 1.3333333e-6, 8.8888889e-7
    ]
    assert [ML.level(n).nominal_layers for n in ML.LEVELS] == [48, 72, 108]
    assert ML.BL_ENVELOPE == 0.02
    assert ML.MAX_GROWTH_RATIO == 1.20
    assert (ML.X_MIN, ML.X_MAX, ML.Y_MIN, ML.Y_MAX) == (-500.0, 501.0, -500.0, 500.0)
    assert ML.SPAN == 0.01
    assert (ML.GMSH_SEED, ML.GMSH_ALGORITHM_2D, ML.GMSH_RECOMBINE_ALGORITHM,
            ML.GMSH_SMOOTHING_STEPS, ML.GMSH_OPTIMIZE_NETGEN) == (
        20260927, 6, 1, 5, False)


def test_wall_normal_progression_is_unchanged():
    expected = {"coarse": 1.167234234, "medium": 1.108120656, "fine": 1.070640323}
    for name, q in expected.items():
        stack = ML.layer_stack(ML.level(name))
        assert stack.growth_ratio == pytest.approx(q, rel=1e-8)
        assert stack.realized_envelope == pytest.approx(0.02, rel=1e-9)


def test_wake_sizing_is_unchanged():
    assert ML.wake_half_width(1.0) == pytest.approx(0.05)
    assert ML.wake_half_width(2.0) == pytest.approx(0.25)
    assert ML.background_size(0.0) == pytest.approx(0.002)
    assert ML.background_size(1000.0) == pytest.approx(50.0)


def test_quality_gates_are_unchanged_by_v2():
    assert MC.MAX_NON_ORTHOGONALITY_DEG == 65.0
    assert MC.MAX_SKEWNESS == 2.0
    assert MC.MIN_INTERPOLATION_WEIGHT == 0.10
    assert MC.MIN_FACE_VOLUME_RATIO == 0.10
    assert MC.MAX_IN_PLANE_STRETCHING == 10_000.0


def test_v2_construction_thresholds_are_declared():
    assert MC.V2_FIRST_TE_INTERVAL_TOLERANCE == 0.01
    assert MC.V2_TE_FAN_RATIO_BOUNDS == (0.8, 1.25)
    assert MC.V2_PARTITION_RATIO_MAX == 2.0


@gmsh_required
def test_the_pipeline_refuses_a_surface_count_override():
    with pytest.raises(ValueError, match="not an override under recipe v2"):
        GP.generate("coarse", "/tmp/never-written", section_n=256)


# -- versioned report paths --------------------------------------------
def test_v2_is_now_archived_evidence_not_the_active_path():
    """The Gmsh generator stays in the tree; it no longer gates anything."""
    assert ML.RECIPE_VERSION == "v2"
    assert MH.ACTIVE_RECIPE_VERSION == "nasa_familyII"
    assert MH.REPORT_ROOT.name == "nasa_familyII"
    assert Path("outputs/airfoil_mesh/v1") in MH.ARCHIVED_ROOTS
    assert Path("outputs/airfoil_mesh/v2") in MH.ARCHIVED_ROOTS
    assert MH.REPORT_ROOT not in MH.ARCHIVED_ROOTS


# -- the generated mesh realizes the prescription ----------------------
@slow
@gmsh_required
def test_generated_coarse_v2_mesh_realizes_the_prescribed_surface(tmp_path):
    mesh = GP.generate("coarse", tmp_path, verbosity=0)
    assert mesh.airfoil_faces == 2 * FROZEN["coarse"]["per_side"] == 602
    report = MC.qualify_mesh(mesh.mesh, level_name="coarse")
    v2 = report.metrics["v2_surface_construction"]
    assert v2["resolved"] is True
    assert v2["first_te_interval_relative_error"] <= MC.V2_FIRST_TE_INTERVAL_TOLERANCE
    lo, hi = MC.V2_TE_FAN_RATIO_BOUNDS
    assert lo <= v2["te_surface_to_fan_ratio"] <= hi
    assert v2["partition_adjacent_ratio"] <= MC.V2_PARTITION_RATIO_MAX
    assert v2["missing_prescribed_stations"] == 0
    assert v2["max_ordinate_deviation"] <= v2["ordinate_budget"]
    names = {c.name for c in report.checks}
    for check in ("v2_first_te_interval_as_prescribed",
                  "v2_te_surface_to_fan_spacing_ratio",
                  "v2_partition_adjacent_spacing_ratio",
                  "v2_no_prescribed_te_nodes_removed",
                  "v2_no_layer_collapse",
                  "v2_no_geometry_rounding",
                  "v2_fan_sectors_unchanged"):
        assert check in names
        assert [c for c in report.checks if c.name == check][0].passed is True


@slow
@gmsh_required
def test_v2_does_not_touch_the_wall_layer_or_the_fan(tmp_path):
    """No local first-layer thickening, no TE transition block, no fan reduction."""
    mesh = GP.generate("coarse", tmp_path, verbosity=0)
    provenance = mesh.provenance
    assert provenance["level_parameters"]["te_fan_sectors"] == 24
    assert provenance["layer_stack"]["first_layer_over_chord"] == 2.0e-6
    assert provenance["layer_stack"]["nominal_layers"] == 48
    assert provenance["span"] == 0.01
    assert provenance["recipe_version"] == "v2"
    assert provenance["spanwise_cells"] == 1
