#!/usr/bin/env python3
"""NASA TMR Family II: the ACTIVE F3 mesh path. No CFD, no network.

The real assets are hundreds of megabytes and are not in the tree, so the
conversion and the frozen gates are exercised against a Family-II-SHAPED
synthetic grid built from the same frozen analytic geometry, plus corrupted
variants that prove each specific failure is caught.
"""
from __future__ import annotations

import math
from pathlib import Path

import pytest

from src.pipeline.airfoil import assets as A
from src.pipeline.airfoil import cgns
from src.pipeline.airfoil import family2 as F2
from src.pipeline.airfoil import geometry as G
from src.pipeline.airfoil import mesh_checks as MC
from src.pipeline.airfoil import mesh_hierarchy as MH
from tests.airfoil import synthetic_family2 as SF

h5py_required = pytest.mark.skipif(
    not cgns.dependency_status().get("available"), reason="h5py is not installed"
)


# -- the registered hierarchy ------------------------------------------
def test_the_three_family2_levels_are_registered_as_required():
    assert A.FAMILY2_KEYS == ("familyII_coarse_hex_cgns", "familyII_medium_hex_cgns",
                              "familyII_fine_hex_cgns")
    filenames = [A.REGISTER[k].filename for k in A.FAMILY2_KEYS]
    assert filenames == ["n0012familyII.6.hex.cgns.gz",
                         "n0012familyII.5.hex.cgns.gz",
                         "n0012familyII.4.hex.cgns.gz"]
    for key in A.FAMILY2_KEYS:
        assert A.REGISTER[key].required is True


def test_level_dimensions_and_cell_counts_are_the_identity():
    assert F2.DIMENSIONS == {"coarse": (225, 65), "medium": (449, 129),
                             "fine": (897, 257)}
    assert F2.CELLS == {"coarse": 14336, "medium": 57344, "fine": 229376}
    for level, (ni, nj) in F2.DIMENSIONS.items():
        assert F2.cells_for(level) == (ni - 1) * (nj - 1) == F2.CELLS[level]
    assert F2.AIRFOIL_SURFACE_POINTS == {"coarse": 129, "medium": 257, "fine": 513}


def test_registered_expectations_match_the_module():
    for level, key in A.FAMILY2_LEVEL_KEYS.items():
        expected = A.REGISTER[key].expected
        assert expected["cells"] == F2.CELLS[level]
        assert expected["structured_dimensions_ni_nj"] == list(F2.DIMENSIONS[level])
        assert expected["airfoil_surface_points"] == F2.AIRFOIL_SURFACE_POINTS[level]
        assert expected["spanwise_cells"] == 1
        assert expected["farfield_chords_approx"] == 500


def test_plot3d_counterparts_are_crosscheck_only():
    for key in A.FAMILY2_CROSSCHECK_KEYS:
        asset = A.REGISTER[key]
        assert asset.required is False
        assert "cross-check" in asset.role
        assert key in A.OPTIONAL_SUPPORTING_KEYS


def test_retrieval_provenance_records_the_archive_not_an_invented_url():
    source = A.REGISTER[A.FAMILY2_COARSE].source
    assert A.FAMILY2_ARCHIVE in source
    assert "naca0012numerics_grids.html" in source
    # No per-file URL is fabricated: the page carries no per-file anchor.
    assert ".hex.cgns.gz" not in source


def test_required_assets_fail_closed_when_absent(fake_repo):
    audit = A.audit_assets(fake_repo)
    assert audit["all_required_ok"] is False
    assert set(A.FAMILY2_KEYS) <= set(audit["missing_required"])
    for key in A.FAMILY2_KEYS:
        with pytest.raises(A.AssetError, match="never substitutes"):
            A.require(key, fake_repo)


def test_the_active_report_path_is_the_family2_path():
    assert MH.ACTIVE_RECIPE_VERSION == "nasa_familyII"
    assert MH.REPORT_ROOT.name == "nasa_familyII"
    archived = {r.name for r in MH.ARCHIVED_ROOTS}
    assert archived == {"v1", "v2"}


def test_the_required_span_is_ours_not_nasas():
    from src.families.airfoil import spec as S
    assert F2.REQUIRED_SPAN == 0.01 == S.SPAN_M
    assert SF.SOURCE_SPAN == 1.0


# -- conversion --------------------------------------------------------
@pytest.fixture
def fixture_level(tmp_path, monkeypatch):
    """A Family-II-shaped grid, with the level registry pointed at its shape."""
    path, counts = SF.write(tmp_path / "familyII.synthetic.cgns.gz",
                            n_per_side=32, n_radial=12)
    ni = counts["ni"] + 1
    monkeypatch.setitem(F2.DIMENSIONS, "coarse", (ni, counts["n_radial"]))
    monkeypatch.setitem(F2.CELLS, "coarse", counts["cells"])
    monkeypatch.setitem(F2.AIRFOIL_SURFACE_POINTS, "coarse", counts["ni"] + 1)
    return path, counts


@h5py_required
def test_conversion_preserves_the_source_exactly(fixture_level):
    path, counts = fixture_level
    converted = F2.convert("coarse", path)
    check = converted.conversion_check
    assert check["in_plane_preserved_exactly"] is True
    assert check["in_plane_coordinate_error"] == 0.0
    assert check["connectivity_identical"] is True
    assert check["point_count_preserved"] is True
    assert check["no_duplicate_or_merged_points"] is True
    assert check["orientation_positive"] is True
    assert check["cells"] == counts["cells"]


@h5py_required
def test_only_the_spanwise_separation_changes(fixture_level):
    path, _ = fixture_level
    source = cgns.read_cgns_hex(path)
    converted = F2.convert("coarse", path)
    zs = sorted({p[2] for p in converted.mesh["points"]})
    assert zs == [0.0, F2.REQUIRED_SPAN]
    assert converted.conversion_check["span"]["source_span"] == SF.SOURCE_SPAN
    # x and y are the source's, value for value.
    for a, b in zip(source.points, converted.mesh["points"]):
        assert (a[0], a[1]) == (b[0], b[1])


@h5py_required
def test_exactly_one_spanwise_cell_survives(fixture_level):
    path, counts = fixture_level
    converted = F2.convert("coarse", path)
    patches = converted.mesh["patches"]
    assert len(patches["frontAndBack"]) == 2 * converted.cells
    assert converted.cells == counts["cells"]


@h5py_required
def test_patch_assignment_and_types(fixture_level):
    path, counts = fixture_level
    converted = F2.convert("coarse", path)
    patches = converted.mesh["patches"]
    assert len(patches["airfoil"]) == counts["ni"]
    assert len(patches["farfield"]) == counts["ni"]
    assert F2.PATCH_TYPES == {"airfoil": "wall", "farfield": "patch",
                              "frontAndBack": "empty"}
    assert converted.conversion_check["unclassified_boundary_faces"] == 0


@h5py_required
def test_the_joined_seam_is_internal_not_a_boundary(fixture_level):
    """The wrap/wake seam must be shared by two cells, never a patch."""
    path, _ = fixture_level
    converted = F2.convert("coarse", path)
    assert converted.conversion_check["wake_internal"] is True
    names = set(converted.mesh["patches"])
    assert names == {"airfoil", "farfield", "frontAndBack"}


@h5py_required
def test_geometry_is_verified_against_the_frozen_tmr_formula(fixture_level):
    path, _ = fixture_level
    check = F2.convert("coarse", path).geometry_check
    assert check["chord_ok"] is True
    assert check["chord"] == pytest.approx(1.0, abs=F2.CHORD_TOLERANCE)
    assert check["trailing_edge_sharp"] is True
    assert check["ordinate_within_budget"] is True
    assert check["reflection_ok"] is True
    assert check["farfield_ok"] is True
    assert check["farfield_max_radius_chords"] >= 100.0
    assert check["xi_t"] == G.XI_T


# -- corrupted variants: each failure must be caught -------------------
@h5py_required
def test_a_wrong_cell_count_is_refused(fixture_level):
    path, counts = fixture_level
    with pytest.raises(cgns.CgnsError, match="expected"):
        cgns.read_cgns_hex(path, expected_cells=counts["cells"] + 1)


@h5py_required
def test_three_spanwise_planes_are_refused(tmp_path):
    from tests.airfoil.synthetic_cgns import write_cgns_hex
    points = [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (1.0, 1.0, 0.0), (0.0, 1.0, 0.0),
              (0.0, 0.0, 1.0), (1.0, 0.0, 1.0), (1.0, 1.0, 1.0), (0.0, 1.0, 1.0),
              (0.0, 0.0, 2.0), (1.0, 0.0, 2.0), (1.0, 1.0, 2.0), (0.0, 1.0, 2.0)]
    hexes = [(0, 1, 2, 3, 4, 5, 6, 7), (4, 5, 6, 7, 8, 9, 10, 11)]
    path = write_cgns_hex(tmp_path / "three.cgns.gz", points, hexes)
    source = cgns.read_cgns_hex(path)
    with pytest.raises(F2.Family2Error, match="spanwise plane"):
        F2.rescale_span(source.points)


@h5py_required
def test_an_open_seam_is_reported_not_silently_merged(tmp_path, monkeypatch):
    """Duplicated seam nodes leave boundary faces that belong to no patch."""
    points, hexes, counts = SF.build(n_per_side=16, n_radial=6)
    ni = counts["ni"]
    n_plane = len(points) // 2
    # Duplicate the seam column so the wrap is no longer shared.
    extra = {}
    for j in range(counts["n_radial"]):
        for k in (0, 1):
            original = k * n_plane + j * ni
            extra[original] = len(points)
            points.append(points[original])
    patched = []
    for cell in hexes:
        patched.append(tuple(
            extra[v] if (v in extra and cell.index(v) in (1, 2, 5, 6)) else v
            for v in cell
        ))
    from tests.airfoil.synthetic_cgns import write_cgns_hex
    path = write_cgns_hex(tmp_path / "open.cgns.gz", points, patched)
    monkeypatch.setitem(F2.DIMENSIONS, "coarse", (ni + 1, counts["n_radial"]))
    monkeypatch.setitem(F2.CELLS, "coarse", counts["cells"])
    monkeypatch.setitem(F2.AIRFOIL_SURFACE_POINTS, "coarse", ni + 1)
    converted = F2.convert("coarse", path)
    assert converted.conversion_check["no_duplicate_or_merged_points"] is False
    report = MC.qualify_family2(
        converted.mesh, level_name="coarse",
        geometry_check=converted.geometry_check,
        conversion_check=converted.conversion_check, span=F2.REQUIRED_SPAN,
    )
    assert report.verdict != MC.PASSED
    assert "no_duplicate_or_merged_points" in report.failed


# -- qualification -----------------------------------------------------
@h5py_required
def test_the_frozen_gates_are_applied_to_the_nasa_path(fixture_level):
    path, _ = fixture_level
    converted = F2.convert("coarse", path)
    report = MC.qualify_family2(
        converted.mesh, level_name="coarse",
        geometry_check=converted.geometry_check,
        conversion_check=converted.conversion_check, span=F2.REQUIRED_SPAN,
    )
    names = {c.name for c in report.checks}
    for gate in ("max_non_orthogonality", "max_skewness",
                 "min_interpolation_weight", "min_face_volume_ratio",
                 "max_in_plane_stretching", "positive_cell_volumes",
                 "positive_face_areas", "face_pyramid_checks", "face_tet_checks",
                 "no_genuine_concavity", "quads_strictly_convex",
                 "positive_bilinear_jacobian", "one_connected_fluid_region",
                 "correct_patch_membership", "exactly_one_spanwise_layer",
                 "nasa_in_plane_coordinates_preserved_exactly",
                 "nasa_connectivity_identical", "nasa_cell_count",
                 "nasa_chord_is_unit", "nasa_trailing_edge_is_sharp",
                 "nasa_surface_matches_tmr_formula", "nasa_farfield_extent"):
        assert gate in names, gate
    assert report.to_dict()["cfd_launched"] is False
    assert report.verdict in (MC.PASSED, MC.FAILED, MC.INCONCLUSIVE)


@h5py_required
def test_one_connected_region_and_span_are_checked(fixture_level):
    path, _ = fixture_level
    converted = F2.convert("coarse", path)
    report = MC.qualify_family2(
        converted.mesh, level_name="coarse",
        geometry_check=converted.geometry_check,
        conversion_check=converted.conversion_check, span=F2.REQUIRED_SPAN,
    )
    by_name = {c.name: c for c in report.checks}
    assert by_name["one_connected_fluid_region"].passed is True
    assert by_name["exactly_one_spanwise_layer"].passed is True
    assert by_name["nasa_in_plane_coordinates_preserved_exactly"].passed is True


def test_nasa_provenance_does_not_relax_a_threshold():
    """The Family II path reads the same module constants, with no override."""
    import inspect
    source = inspect.getsource(MC.qualify_family2)
    for constant in ("MAX_NON_ORTHOGONALITY_DEG", "MAX_SKEWNESS",
                     "MIN_INTERPOLATION_WEIGHT", "MIN_FACE_VOLUME_RATIO"):
        assert constant not in source          # thresholds live in the shared gate
    assert "apply_frozen_gates" in source
    assert MC.MAX_NON_ORTHOGONALITY_DEG == 65.0
    assert MC.MAX_SKEWNESS == 2.0
    assert MC.MIN_INTERPOLATION_WEIGHT == 0.10
    assert MC.MIN_FACE_VOLUME_RATIO == 0.10
    assert MC.MAX_IN_PLANE_STRETCHING == 10_000.0


@h5py_required
def test_a_raw_checkmesh_report_is_carried_through_unchanged(fixture_level):
    path, _ = fixture_level
    converted = F2.convert("coarse", path)
    raw = {"status": "STAGE_B_PASSED", "summary": {"mesh_ok": True},
           "failed_checks": []}
    report = MC.qualify_family2(
        converted.mesh, level_name="coarse",
        geometry_check=converted.geometry_check,
        conversion_check=converted.conversion_check, span=F2.REQUIRED_SPAN,
        raw_check_mesh=raw,
    )
    assert report.to_dict()["raw_openfoam_check_mesh"] == raw


def test_the_gmsh_generator_is_untouched_and_archived():
    """v1/v2 remain in the tree as evidence and are not the active path."""
    from src.pipeline.airfoil import gmsh_pipeline, mesh_levels
    assert mesh_levels.RECIPE_VERSION == "v2"
    assert gmsh_pipeline.PIPELINE_VERSION == "f3-gmsh-pipeline/2.0.0"
    assert MH.ACTIVE_RECIPE_VERSION != "v2"
    for archived in MH.ARCHIVED_ROOTS:
        assert archived != MH.REPORT_ROOT
