#!/usr/bin/env python3
"""F3 Gmsh mesh hierarchy: geometry, hierarchy, qualification, readiness.

No CFD anywhere. The tests that need Gmsh skip cleanly when it is absent; every
test that encodes a FROZEN number runs unconditionally, so the recipe is guarded
even on a machine without a mesher.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from src.families.airfoil import spec as S
from src.families.airfoil.adapter import (
    GATE_ASSETS,
    GATE_MESH_HIERARCHY,
    GATES,
    AirfoilAdapter,
)
from src.pipeline.airfoil import geometry as G
from src.pipeline.airfoil import gmsh_pipeline as GP
from src.pipeline.airfoil import mesh_checks as MC
from src.pipeline.airfoil import mesh_hierarchy as MH
from src.pipeline.airfoil import mesh_levels as ML

#: These tests MESH. They take tens of seconds and are excluded from the quick
#: suite with `-m "not slow"`; everything else in this file is pure arithmetic.
gmsh_required = pytest.mark.skipif(
    not GP.gmsh_status().get("available"), reason="gmsh is not installed"
)
slow = pytest.mark.slow


# -- 1. the corrected TMR analytic section ------------------------------
def test_thickness_polynomial_root_is_solved_not_transcribed():
    """xi_T is the root of the thickness polynomial, to the adjacent double."""
    assert G.XI_T == pytest.approx(G.XI_T_REFERENCE, abs=1e-11)
    assert abs(G.f(G.XI_T)) < 1e-15
    # A transcribed constant would not satisfy the equation this tightly.
    assert G.f(G.XI_T_REFERENCE) == pytest.approx(0.0, abs=1e-11)


def test_leading_and_trailing_edge_are_exact():
    sec = G.section(64)
    assert sec.upper[0] == (0.0, 0.0)
    assert sec.upper[-1] == (1.0, 0.0)
    assert G.ordinate(0.0) == 0.0
    assert abs(G.ordinate(1.0)) < G.BOUNDARY_ERROR_BUDGET


def test_section_is_exactly_symmetric():
    sec = G.section(128)
    for (xu, yu), (xl, yl) in zip(sec.upper, sec.lower):
        assert xu == xl
        assert yl == -yu          # exact negation, not an approximation


def test_closed_loop_has_2n_points_with_one_trailing_edge():
    n = 48
    loop = G.section(n).closed_loop()
    assert len(loop) == 2 * n
    assert loop[0] == (1.0, 0.0)
    assert loop.count((1.0, 0.0)) == 1        # the TE appears ONCE
    assert loop[n] == (0.0, 0.0)              # the LE is reached at index n


def test_surface_stations_follow_the_frozen_cosine_distribution():
    n = 32
    stations = G.cosine_stations(n)
    assert stations[0] == 0.0 and stations[-1] == 1.0
    for j, x in enumerate(stations):
        assert x == pytest.approx(0.5 * (1 - math.cos(math.pi * j / n)), abs=1e-15)
    # clustered at both ends, which is what the distribution is for
    assert stations[1] - stations[0] < stations[n // 2] - stations[n // 2 - 1]


# -- 2. the frozen hierarchy -------------------------------------------
def test_growth_ratio_is_solved_and_stays_below_the_frozen_limit():
    for name in ML.LEVELS:
        lv = ML.level(name)
        stack = ML.layer_stack(lv)
        assert stack.growth_ratio < ML.MAX_GROWTH_RATIO
        # the solved q must reproduce the envelope as an identity
        total = lv.first_layer * (stack.growth_ratio ** lv.nominal_layers - 1) / (
            stack.growth_ratio - 1
        )
        assert total == pytest.approx(ML.BL_ENVELOPE, rel=1e-9)
        assert stack.realized_envelope == pytest.approx(ML.BL_ENVELOPE, rel=1e-9)
        assert stack.realized_layers == lv.nominal_layers


def test_hierarchy_scales_as_declared():
    coarse, medium, fine = (ML.level(n) for n in ML.LEVELS)
    assert (coarse.refinement, medium.refinement, fine.refinement) == (1.0, 1.5, 2.25)
    for lv in (medium, fine):
        assert lv.n_per_side == int(round(coarse.n_per_side * lv.refinement))
        assert lv.first_layer == pytest.approx(
            coarse.first_layer / lv.refinement, rel=1e-6
        )
        assert lv.fan_sectors == int(round(coarse.fan_sectors * lv.refinement))
    # Face counts come from the ACTIVE recipe. Under v1 they were 2N
    # (512 / 768 / 1152); recipe v2 partitions each side at x/c = 0.98 and
    # supersedes those counts with 2 (n_body + n_TE). The v1 numbers are asserted
    # in test_mesh_recipe_v2.py as the counts v2 replaces.
    assert coarse.airfoil_faces == 602
    assert medium.airfoil_faces == 910
    assert fine.airfoil_faces == 1378


def test_farfield_is_identical_on_every_level():
    summary = ML.hierarchy_summary()
    assert summary["farfield"]["x"] == [-500.0, 501.0]
    assert summary["farfield"]["y"] == [-500.0, 500.0]
    assert summary["farfield"]["identical_on_all_levels"] is True
    assert summary["span"] == 0.01


def test_wake_and_background_sizing_equations_are_the_frozen_ones():
    assert ML.wake_half_width(1.0) == pytest.approx(0.05)
    assert ML.wake_half_width(2.0) == pytest.approx(0.25)
    assert ML.background_size(0.0) == pytest.approx(0.002)
    assert ML.background_size(1.0) == pytest.approx(0.122)
    assert ML.background_size(1000.0) == pytest.approx(50.0)     # capped
    # refinement divides the target size
    d = 0.5
    assert ML.target_size(0.0, 5.0, d, 2.25) == pytest.approx(
        ML.target_size(0.0, 5.0, d, 1.0) / 2.25
    )


def test_mesh_generation_configuration_is_deterministic():
    assert ML.GMSH_SEED == 20260927
    assert ML.GMSH_ALGORITHM_2D == 6
    assert ML.GMSH_OPTIMIZE_NETGEN is False
    summary = ML.hierarchy_summary()
    assert summary["gmsh"]["identical_on_all_levels"] is True


def test_te_spacing_mismatch_is_level_invariant_by_construction():
    """The diagnostic that explains a TE-localised failure. Never a criterion."""
    ratios = [ML.te_fan_spacing(ML.level(n))["spacing_ratio"] for n in ML.LEVELS]
    # Invariant to the precision of the FROZEN first-layer heights themselves,
    # which are written as rounded decimals (1.3333333e-6, 8.8888889e-7) rather
    # than as exact thirds and ninths. The residual spread is that rounding, not
    # a dependence on refinement.
    assert ratios[0] == pytest.approx(ratios[1], rel=1e-4)
    assert ratios[1] == pytest.approx(ratios[2], rel=1e-4)
    for name in ML.LEVELS:
        assert ML.te_fan_spacing(ML.level(name))["diagnostic_only"] is True


# -- 3. the qualification thresholds are frozen ------------------------
def test_qualification_thresholds_are_the_frozen_values():
    assert MC.MAX_NON_ORTHOGONALITY_DEG == 65.0
    assert MC.MAX_SKEWNESS == 2.0
    assert MC.MIN_INTERPOLATION_WEIGHT == 0.10
    assert MC.MIN_FACE_VOLUME_RATIO == 0.10
    assert MC.MAX_IN_PLANE_STRETCHING == 10_000.0


def _unit_mesh(*, span: float = 0.01, shear: float = 0.0, squash: float = 1.0):
    """One-hex mesh with every patch declared. Deliberately trivial and valid."""
    base = [(0.0, 0.0), (1.0, 0.0), (1.0 + shear, squash), (shear, squash)]
    plane = {
        "points": base,
        "quads": [(0, 1, 2, 3)],
        "tris": [],
        "airfoil_edges": [(0, 1)],
        "farfield_edges": [(1, 2), (2, 3), (3, 0)],
    }
    return GP.extrude_one_layer(plane, span=span)


def test_a_valid_single_cell_mesh_reports_no_geometric_failure():
    report = MC.qualify_mesh(_unit_mesh(), level_name="coarse")
    for name in ("max_non_orthogonality", "max_skewness",
                 "min_interpolation_weight", "min_face_volume_ratio"):
        failing = [c for c in report.checks if c.name == name and c.passed is False]
        assert not failing, f"{name} failed on a perfect hex: {failing}"


def test_a_crossed_in_plane_cell_is_rejected():
    """A self-intersecting quad must never qualify."""
    plane = {
        "points": [(0.0, 0.0), (1.0, 0.0), (0.0, 1.0), (1.0, 1.0)],   # crossed order
        "quads": [(0, 1, 2, 3)],
        "tris": [],
        "airfoil_edges": [(0, 1)],
        "farfield_edges": [(1, 2), (2, 3), (3, 0)],
    }
    report = MC.qualify_mesh(GP.extrude_one_layer(plane, span=0.01),
                             level_name="coarse")
    assert report.verdict != MC.PASSED


def test_a_genuinely_concave_cell_is_rejected():
    plane = {
        "points": [(0.0, 0.0), (1.0, 0.0), (0.45, 0.45), (0.0, 1.0)],  # reflex vertex
        "quads": [(0, 1, 2, 3)],
        "tris": [],
        "airfoil_edges": [(0, 1)],
        "farfield_edges": [(1, 2), (2, 3), (3, 0)],
    }
    report = MC.qualify_mesh(GP.extrude_one_layer(plane, span=0.01),
                             level_name="coarse")
    assert report.verdict != MC.PASSED
    concavity = [c for c in report.checks if "concav" in c.name]
    assert concavity and any(c.passed is False for c in concavity)


def test_the_raw_check_mesh_report_is_carried_through_unchanged():
    raw = {"status": "whatever OpenFOAM said", "failed_checks": ["nonsense"],
           "mesh_ok": False}
    report = MC.qualify_mesh(_unit_mesh(), level_name="coarse", raw_check_mesh=raw)
    out = report.to_dict()
    assert out["raw_openfoam_check_mesh"] == raw
    assert out["cfd_launched"] is False
    # the deterministic verdict is SEPARATE from the raw report
    assert out["qualification_verdict"] in (MC.PASSED, MC.FAILED, MC.INCONCLUSIVE)


# -- 4. generation, when gmsh is present -------------------------------
@slow
@gmsh_required
def test_generated_coarse_level_matches_the_frozen_recipe(tmp_path):
    mesh = GP.generate("coarse", tmp_path, verbosity=0)
    lv = ML.level("coarse")
    assert mesh.airfoil_faces == lv.airfoil_faces == 602
    # exactly one spanwise cell: both spanwise patches, and nothing else
    assert mesh.frontback_faces == 2 * mesh.cells
    assert mesh.cells == mesh.hexes + mesh.prisms
    assert GP.PATCH_TYPES == {"airfoil": "wall", "farfield": "patch",
                              "frontAndBack": "empty"}
    zs = sorted({round(p[2], 12) for p in mesh.mesh["points"]})
    assert zs == [0.0, ML.SPAN]


@pytest.mark.xfail(strict=True, reason=(
    "known open defect in the ARCHIVED Gmsh generator: node numbering is not "
    "reproducible, so a level cannot carry a registered SHA256. The generator is "
    "archived evidence and is no longer the F3 mesh path, so this is recorded "
    "rather than fixed. Made strict so it flags if it ever starts passing."))
@slow
@gmsh_required
def test_generation_is_deterministic(tmp_path):
    """KNOWN OPEN DEFECT: counts reproduce exactly, the BYTES do not.

    Four independent generations of the coarse level gave 65,270 cells / 25,122
    hexes / 40,148 prisms / 90,986 points every time, and four different file
    digests. The variation is in node numbering, not in the recipe, and it is in
    gmsh's 2-D meshing rather than in this pipeline -- it reproduces across fresh
    processes with Mesh.RandomSeed fixed and NumThreads = 1.

    The test is kept FAILING on purpose. A mesh that cannot be reproduced
    byte-for-byte cannot carry a registered SHA256, so this must be closed (by
    canonicalising the node ordering before the mesh is written) before any level
    is registered as an asset. It is not a reason to relax a mesh threshold.
    """
    a = GP.generate("coarse", tmp_path / "a", verbosity=0)
    b = GP.generate("coarse", tmp_path / "b", verbosity=0)
    assert (a.cells, a.hexes, a.prisms, a.points) == (b.cells, b.hexes,
                                                      b.prisms, b.points)
    assert a.sha256 == b.sha256


# -- 5. readiness ------------------------------------------------------
def _write_report(root: Path, level: str, verdict: str, cells: int = 1234) -> None:
    path = MH.qualification_path(level, root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "level": level, "qualification_verdict": verdict, "failed": [],
        "unresolved": [], "generation": {"cells": cells, "mesh_sha256": "0" * 64},
    }), encoding="utf-8")


def test_gates_include_the_mesh_hierarchy_gate():
    assert GATES == (GATE_ASSETS, GATE_MESH_HIERARCHY, "coarse_pilot_sane",
                     "canonical_validation")


def test_mesh_gate_is_open_while_a_level_is_missing(fake_repo):
    _write_report(fake_repo, "coarse", MC.PASSED)
    _write_report(fake_repo, "medium", MC.PASSED)
    state = MH.hierarchy_state(fake_repo)
    assert state["all_qualified"] is False
    assert state["missing_levels"] == ["fine"]
    assert AirfoilAdapter.readiness(fake_repo)["gates"][GATE_MESH_HIERARCHY] is False


def test_one_failed_level_blocks_cfd_readiness(fake_repo):
    _write_report(fake_repo, "coarse", MC.PASSED)
    _write_report(fake_repo, "medium", MC.PASSED)
    _write_report(fake_repo, "fine", MC.FAILED)
    state = MH.hierarchy_state(fake_repo)
    assert state["all_qualified"] is False
    assert state["not_qualified_levels"] == ["fine"]
    readiness = AirfoilAdapter.readiness(fake_repo)
    assert readiness["gates"][GATE_MESH_HIERARCHY] is False
    assert readiness["ready_for_core"] is False
    assert GATE_MESH_HIERARCHY in readiness["open_gates"]


def test_three_qualified_levels_close_the_mesh_gate(fake_repo):
    for name in ML.LEVELS:
        _write_report(fake_repo, name, MC.PASSED)
    state = MH.hierarchy_state(fake_repo)
    assert state["all_qualified"] is True
    readiness = AirfoilAdapter.readiness(fake_repo)
    assert readiness["gates"][GATE_MESH_HIERARCHY] is True
    # and only the mesh gate closed: the rest of closure is untouched
    assert readiness["ready_for_core"] is False


def test_the_mesh_gate_cannot_be_closed_by_the_readiness_file(fake_repo):
    """The gate is computed from the reports, not from a hand-written record."""
    path = fake_repo / "configs" / "families" / "airfoil" / "readiness.json"
    path.write_text(json.dumps({GATE_MESH_HIERARCHY: True,
                                "mesh_audit": True}), encoding="utf-8")
    assert AirfoilAdapter.readiness(fake_repo)["gates"][GATE_MESH_HIERARCHY] is False


def test_measured_cells_come_from_the_report_never_from_a_declaration(fake_repo):
    _write_report(fake_repo, "fine", MC.PASSED, cells=229_376)
    assert MH.hierarchy_state(fake_repo)["measured_cells"]["fine"] == 229_376
    assert MH.hierarchy_state(fake_repo)["measured_cells"]["coarse"] is None
    # NASA's declared count is never substituted for a missing measurement
    assert S.EXPECTED_CELLS["coarse"] == 14_336


def test_the_archived_grids_do_not_block_readiness_but_the_active_ones_do(fake_repo):
    from src.pipeline.airfoil import assets as A

    assert A.OPTIONAL_SUPPORTING_KEYS == (
        A.MESH_CANONICAL, A.MESH_SENSITIVITY, A.MESH_CGNS_HEX,
        *A.FAMILY2_CROSSCHECK_KEYS,
    )
    for key in A.OPTIONAL_SUPPORTING_KEYS:
        assert A.REGISTER[key].required is False
    audit = A.audit_assets(fake_repo)
    assert audit["all_required_ok"] is False
    missing = set(audit["missing_required"])
    # the ACTIVE Family II levels and the reference data are required
    assert set(A.FAMILY2_KEYS) <= missing
    assert not missing & set(A.OPTIONAL_SUPPORTING_KEYS)


def test_a_scope_request_on_an_unqualified_level_is_refused():
    result = AirfoilAdapter().check_scope(S.AirfoilSpec())
    assert result.approved is False
    assert any("not qualified" in r for r in result.reasons)
