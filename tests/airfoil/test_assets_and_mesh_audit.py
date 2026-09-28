#!/usr/bin/env python3
"""Registered assets and the mandatory zero-CFD mesh audit.

Nothing here launches OpenFOAM or the flow solver. The mesh exercised is the
synthetic C-grid TOPOLOGY FIXTURE, which is a parabolic lens and explicitly not
a NACA0012 -- see tests/airfoil/synthetic_cgrid.py.
"""
from __future__ import annotations

import gzip
import json

import pytest

from src.families.airfoil.spec import GRID_DIMENSIONS
from src.pipeline.airfoil import assets as A
from src.pipeline.airfoil import mesh_audit, p3d
from src.pipeline.airfoil import references as refs


# -- fail closed on absence -------------------------------------------
def test_no_sha256_is_hard_coded_in_the_source():
    """A digest of a file nobody has seen would be an invented constant."""
    import re
    from pathlib import Path

    text = Path(A.__file__).read_text()
    assert not re.search(r"\b[0-9a-f]{64}\b", text), (
        "a 64-hex digest appears in assets.py; digests belong in the lockfile"
    )


def test_absent_asset_fails_closed(fake_repo):
    audit = A.audit_assets(fake_repo)
    assert audit["all_required_ok"] is False
    # The external validation data are REQUIRED and fail closed when absent.
    assert set(audit["missing_required"]) >= {
        A.REF_LADSON_FORCES, A.REF_CFL3D_FORCES, A.REF_CFL3D_CP,
    }
    # The NASA meshes are an optional supporting branch: absent, they do not
    # block readiness, but they are still never substituted when requested.
    assert not set(audit["missing_required"]) & set(A.OPTIONAL_SUPPORTING_KEYS)
    with pytest.raises(A.AssetError) as exc:
        A.require(A.MESH_CANONICAL, fake_repo)
    assert "never substitutes" in str(exc.value)


def test_present_but_unregistered_digest_fails_closed(fake_repo, install_one):
    install_one(A.MESH_CANONICAL)
    status = A.check_asset(A.MESH_CANONICAL, fake_repo)
    assert status["present"] is True
    assert status["ok"] is False
    assert "SHA256 is not registered" in status["reason"]


def test_hash_mismatch_fails_closed(installed_assets):
    path = A.asset_path(A.MESH_CANONICAL, installed_assets)
    original = path.read_bytes()
    with gzip.open(path, "wb") as fh:
        fh.write(gzip.decompress(original) + b"\n0.0 0.0\n")
    status = A.check_asset(A.MESH_CANONICAL, installed_assets)
    assert status["ok"] is False
    assert "SHA256 mismatch" in status["reason"]
    assert "Refusing" in status["reason"]
    with pytest.raises(A.AssetError):
        A.require(A.MESH_CANONICAL, installed_assets)


def test_registered_assets_pass_once_locked(installed_assets):
    audit = A.audit_assets(installed_assets)
    assert audit["all_required_ok"] is True
    assert audit["mismatched"] == [] and audit["unregistered"] == []


def test_lockfile_records_provenance(installed_assets):
    data = json.loads(A.lockfile_path(installed_assets).read_text())
    assert data["family"] == "airfoil"
    assert data["registered_utc"] and data["toolchain"]
    entry = data["assets"][A.MESH_CANONICAL]
    for field in ("filename", "sha256", "bytes", "source", "role", "expected"):
        assert field in entry
    assert len(entry["sha256"]) == 64


def test_the_registered_assets_are_the_expected_ones():
    names = {a.filename for a in A.REGISTER.values()}
    assert "n0012_897-257.p3dfmt.gz" in names
    assert "n0012_449-129.p3dfmt.gz" in names
    # Plus the CGNS topology authority added for mesh qualification.
    assert "n0012_449-129_hex.cgns.gz" in names
    # 3 active Family II CGNS levels + 3 PLOT3D cross-checks
    # + 2 archived 2DN00 Plot3D grids + 1 archived CGNS authority
    # + 4 reference data files.
    assert len(A.REGISTER) == 13
    assert A.REGISTER[A.REF_CFL3D_CF].required is False, "Cf is supporting only"
    assert "NOT a pressure gate" in A.REGISTER[A.REF_LADSON_FORCES].role


# -- conversion --------------------------------------------------------
def test_conversion_is_deterministic(installed_assets, tmp_path):
    path = A.asset_path(A.MESH_CANONICAL, installed_assets)
    grid = p3d.read_plot3d(path)
    a = p3d.write_gmsh(p3d.convert(grid), tmp_path / "a.msh")
    b = p3d.write_gmsh(p3d.convert(grid), tmp_path / "b.msh")
    assert A.sha256_of(a) == A.sha256_of(b)


def test_wake_interface_is_merged_and_leaves_no_duplicate_faces(installed_assets):
    grid = p3d.read_plot3d(A.asset_path(A.MESH_CANONICAL, installed_assets))
    mesh = p3d.convert(grid)
    assert mesh.topology.wake_pairs > 0
    assert mesh.merged_point_pairs == mesh.topology.wake_pairs
    assert p3d.duplicate_face_count(mesh) == 0


def test_sharp_trailing_edge_keeps_its_wall_faces(installed_assets):
    """The TE joins the coincident run; its faces must stay on the wall patch."""
    grid = p3d.read_plot3d(A.asset_path(A.MESH_CANONICAL, installed_assets))
    mesh = p3d.convert(grid)
    topo = mesh.topology
    assert topo.te_is_coincident is True
    assert topo.trailing_edge_gap == pytest.approx(0.0, abs=1e-12)
    assert topo.pure_wake_pairs == topo.wake_pairs - 1
    assert len(mesh.patches[p3d.PATCH_AIRFOIL]) == (
        topo.surface_i_end - topo.surface_i_start
    )


def test_chord_is_measured_on_the_surface_not_the_wake(installed_assets):
    grid = p3d.read_plot3d(A.asset_path(A.MESH_CANONICAL, installed_assets))
    topo = p3d.convert(grid).topology
    assert topo.chord == pytest.approx(1.0, rel=1e-9)
    assert topo.farfield_extent_chords > 100.0


def test_exactly_one_spanwise_layer(installed_assets):
    grid = p3d.read_plot3d(A.asset_path(A.MESH_CANONICAL, installed_assets))
    mesh = p3d.convert(grid, span=1.0)
    assert mesh.cells == grid.cells_2d
    assert len(mesh.patches[p3d.PATCH_FRONT]) == mesh.cells
    assert len(mesh.patches[p3d.PATCH_BACK]) == mesh.cells
    assert len(mesh.points) % 2 == 0
    zs = {round(p[2], 12) for p in mesh.points}
    assert len(zs) == 2, "one layer means exactly two spanwise point planes"


def test_no_invalid_cell_volumes(installed_assets):
    grid = p3d.read_plot3d(A.asset_path(A.MESH_CANONICAL, installed_assets))
    mesh = p3d.convert(grid)
    assert mesh.negative_or_zero_volume_cells == 0
    assert mesh.min_cell_volume > 0.0


def test_a_grid_without_a_wake_cut_is_refused():
    """A plain Cartesian block has no coincident wake line: refuse, never guess."""
    ni, nj, nk = 2, 5, 3
    x, y, z = [], [], []
    for k in range(nk):
        for j in range(nj):
            for i in range(ni):
                x.append(float(j))
                y.append(float(i))
                z.append(float(k))
    grid = p3d.Plot3DGrid(ni=ni, nj=nj, nk=nk, x=x, y=y, z=z)
    with pytest.raises(p3d.ConversionError) as exc:
        p3d.detect_topology(grid)
    assert "does not look like" in str(exc.value)


def test_a_grid_with_the_wrong_number_of_spanwise_planes_is_refused(tmp_path):
    path = tmp_path / "bad.p3dfmt"
    count = 3 * 5 * 4
    path.write_text("1\n3 5 4\n" + " ".join("0.0" for _ in range(count * 3)) + "\n")
    with pytest.raises(p3d.ConversionError) as exc:
        p3d.read_plot3d(path)
    assert "not 2" in str(exc.value)
    assert "re-extrude" in str(exc.value)


def test_a_header_that_does_not_match_the_coordinate_count_is_refused(tmp_path):
    path = tmp_path / "short.p3dfmt"
    path.write_text("1\n2 5 4\n0.0 1.0 2.0\n")
    with pytest.raises(p3d.ConversionError) as exc:
        p3d.read_plot3d(path)
    assert "Refusing to guess" in str(exc.value)


def test_non_identical_spanwise_planes_fail_closed(tmp_path):
    from tests.airfoil.synthetic_cgrid import write_plot3d

    path = write_plot3d(tmp_path / "skew.p3dfmt.gz", plane_perturbation=1.0e-6)
    grid = p3d.read_plot3d(path)
    check = p3d.check_spanwise_planes(grid)
    assert check.identical_within_tolerance is False
    with pytest.raises(p3d.ConversionError) as exc:
        p3d.convert(grid, span=1.0)
    assert "not identical in the flow plane" in str(exc.value)


def test_wrong_spanwise_separation_fails_closed(tmp_path):
    from tests.airfoil.synthetic_cgrid import write_plot3d

    path = write_plot3d(tmp_path / "wide.p3dfmt.gz", span_override=2.0)
    grid = p3d.read_plot3d(path)
    with pytest.raises(p3d.ConversionError) as exc:
        p3d.convert(grid, span=1.0)
    assert "does not match the registered span" in str(exc.value)
    assert "rescaling" in str(exc.value)


def test_the_supplied_planes_are_used_rather_than_re_extruded(installed_assets):
    grid = p3d.read_plot3d(A.asset_path(A.MESH_CANONICAL, installed_assets))
    mesh = p3d.convert(grid, span=1.0)
    assert mesh.span_coordinates == (
        grid.span_coordinate(0), grid.span_coordinate(1)
    )
    assert mesh.span == pytest.approx(1.0)
    assert mesh.spanwise.identical_within_tolerance is True


def test_axis_mapping_is_recorded():
    assert p3d.AXIS_MAP["openfoam_y"].startswith("nasa_z")
    assert p3d.AXIS_MAP["openfoam_z"].startswith("nasa_y")
    assert p3d.AXIS_MAP["wrap_index"] == "nasa_j"
    assert "no re-extrusion" in p3d.AXIS_MAP["note"]


# -- the audit itself --------------------------------------------------
def test_audit_fails_closed_without_the_asset(fake_repo):
    report = mesh_audit.audit_grid(A.MESH_CANONICAL, repo_root=fake_repo)
    assert report.status == "MESH_AUDIT_FAILED"
    assert "asset_present" in report.failed
    assert "Nothing substituted" in report.provenance["note"]


def test_audit_reports_a_dimension_mismatch_rather_than_accepting(installed_assets):
    """The fixture is deliberately not 897 x 257, so the registry check must fail."""
    report = mesh_audit.audit_grid(A.MESH_CANONICAL, repo_root=installed_assets)
    named = {c.name: c for c in report.checks}
    assert named["dimensions_match_registry"].passed is False
    assert named["asset_sha256_matches"].passed is True
    assert report.status == "MESH_AUDIT_FAILED"


def test_audit_runs_every_required_check(installed_assets, tmp_path):
    report = mesh_audit.audit_grid(
        A.MESH_CANONICAL, repo_root=installed_assets, out_dir=tmp_path
    )
    names = {c.name for c in report.checks}
    required = {
        "asset_present", "asset_sha256_registered", "asset_sha256_matches",
        "plot3d_parses", "dimensions_match_registry", "conversion_succeeds",
        "converted_cell_count", "chord_scaling", "sharp_trailing_edge",
        "farfield_not_truncated", "wake_cut_detected", "wake_interface_merged",
        "no_duplicate_coincident_wake_faces", "exactly_one_spanwise_layer",
        "patch_inventory", "no_invalid_cell_volumes",
        "checkMesh_allTopology_allGeometry", "front_back_are_empty",
    }
    missing = required - names
    assert not missing, f"audit is missing checks: {sorted(missing)}"


def test_geometry_checks_pass_on_the_fixture(installed_assets, tmp_path):
    report = mesh_audit.audit_grid(
        A.MESH_CANONICAL, repo_root=installed_assets, out_dir=tmp_path
    )
    named = {c.name: c for c in report.checks}
    for name in ("chord_scaling", "sharp_trailing_edge", "farfield_not_truncated",
                 "wake_cut_detected", "wake_interface_merged",
                 "no_duplicate_coincident_wake_faces", "exactly_one_spanwise_layer",
                 "patch_inventory", "spanwise_patch_face_count",
                 "airfoil_patch_excludes_wake", "no_invalid_cell_volumes"):
        assert named[name].passed is True, f"{name}: {named[name].detail}"


def test_audit_records_full_conversion_provenance(installed_assets, tmp_path):
    report = mesh_audit.audit_grid(
        A.MESH_CANONICAL, repo_root=installed_assets, out_dir=tmp_path
    )
    p = report.provenance
    for field in ("source_filename", "source_sha256", "source_url",
                  "source_dimensions", "source_cells_2d", "converted_cells",
                  "conversion_utc", "conversion_version", "conversion_toolchain",
                  "converted_mesh_sha256", "spanwise_layers", "topology"):
        assert field in p, f"provenance is missing {field}"
    assert p["geometry_regenerated"] is False
    assert "no polynomial regeneration" in p["geometry_note"]


def test_stage_b_absence_leaves_the_audit_incomplete_not_passed(installed_assets,
                                                               tmp_path, monkeypatch):
    """Without checkMesh the audit can never report PASSED."""
    report = mesh_audit.audit_grid(
        A.MESH_CANONICAL, repo_root=installed_assets, out_dir=tmp_path
    )
    assert report.stage_b["status"] == mesh_audit.NOT_RUN
    assert "checkMesh_allTopology_allGeometry" in report.unknown
    assert report.status != "MESH_AUDIT_PASSED"
    assert report.to_dict()["cfd_launched"] is False


def test_audit_never_launches_a_process(installed_assets, tmp_path, monkeypatch):
    import subprocess

    def boom(*a, **k):  # pragma: no cover - must never run
        raise AssertionError("the mesh audit attempted to launch a process")

    monkeypatch.setattr(subprocess, "run", boom)
    monkeypatch.setattr(subprocess, "Popen", boom)
    monkeypatch.setattr(subprocess, "check_output", boom)
    mesh_audit.audit_all(repo_root=installed_assets, out_dir=tmp_path)


def test_both_registered_grids_are_audited(installed_assets, tmp_path):
    result = mesh_audit.audit_all(repo_root=installed_assets, out_dir=tmp_path)
    assert set(result["grids"]) == set(GRID_DIMENSIONS)
    assert result["cfd_launched"] is False


# -- reference loading -------------------------------------------------
def test_ladson_drag_interpolates_and_preserves_the_offset(installed_assets):
    refs_out = refs.ladson_zero_incidence_drag(installed_assets)
    assert len(refs_out) == 2
    for ref in refs_out:
        assert ref.bracket_alpha[0] <= 0.0 <= ref.bracket_alpha[1]
        assert "offset preserved" in ref.to_dict()["method"]
    # -0.14 -> 0.00819, 1.04 -> 0.00823 at alpha = 0
    first = next(r for r in refs_out if "80" in r.dataset)
    expected = 0.00819 + (0.0 - (-0.14)) / (1.04 - (-0.14)) * (0.00823 - 0.00819)
    assert first.cd == pytest.approx(expected, rel=1e-12)


def test_reference_loading_refuses_to_extrapolate(installed_assets):
    with pytest.raises(refs.ReferenceError) as exc:
        refs.ladson_zero_incidence_drag(installed_assets, target_alpha=20.0)
    assert "Refusing to extrapolate" in str(exc.value)


def test_absent_reference_raises_rather_than_inventing(fake_repo):
    with pytest.raises(refs.ReferenceError):
        refs.ladson_zero_incidence_drag(fake_repo)
    with pytest.raises(refs.ReferenceError):
        refs.cfl3d_cp(fake_repo)


def _relock(root, key, path):
    entries = json.loads(A.lockfile_path(root).read_text())
    entries["assets"][key]["sha256"] = A.sha256_of(path)
    A.lockfile_path(root).write_text(json.dumps(entries))


def test_cp_dat_uses_zone_labels_for_surfaces(installed_assets):
    curves = refs.cfl3d_cp(installed_assets)
    assert curves.surface_labels_present is True
    surfaces = curves.for_surfaces()
    assert set(surfaces) == {"upper", "lower"}
    assert len(surfaces["upper"]) == 11
    assert "surfaces taken from zone/title labels" in \
        " ".join(curves.derivation.transformations)


def test_an_unlabelled_single_curve_is_applied_to_both_and_recorded(installed_assets):
    """Cf fixture is unlabelled: the transformation must be recorded, not silent."""
    curves = refs.cfl3d_cf(installed_assets)
    assert curves.surface_labels_present is False
    surfaces = curves.for_surfaces()
    assert surfaces["upper"] == surfaces["lower"]
    joined = " ".join(curves.derivation.transformations)
    assert "applied to BOTH" in joined
    assert "independently" in joined


def test_an_unlabelled_multi_block_surface_file_is_refused(installed_assets):
    path = A.asset_path(A.REF_CFL3D_CP, installed_assets)
    path.write_text("zone t=\"block one\"\n0.5 -1.0\nzone t=\"block two\"\n"
                    "0.6 -0.9\n", encoding="utf-8")
    _relock(installed_assets, A.REF_CFL3D_CP, path)
    with pytest.raises(refs.ReferenceError) as exc:
        refs.cfl3d_cp(installed_assets)
    assert "without guessing" in str(exc.value)


def test_a_short_surface_row_is_refused(installed_assets):
    path = A.asset_path(A.REF_CFL3D_CP, installed_assets)
    path.write_text("0.5\n", encoding="utf-8")
    _relock(installed_assets, A.REF_CFL3D_CP, path)
    with pytest.raises(refs.ReferenceError) as exc:
        refs.cfl3d_cp(installed_assets)
    assert "column" in str(exc.value)


def test_a_short_force_row_is_refused(installed_assets):
    path = A.asset_path(A.REF_LADSON_FORCES, installed_assets)
    path.write_text("0.0 0.1\n", encoding="utf-8")
    _relock(installed_assets, A.REF_LADSON_FORCES, path)
    with pytest.raises(refs.ReferenceError) as exc:
        refs.ladson_zero_incidence_drag(installed_assets)
    assert "Refusing to guess which column" in str(exc.value)


def test_derived_artifacts_are_traceable_to_the_raw_asset(installed_assets):
    drag = refs.ladson_zero_incidence_drag(installed_assets)[0].to_dict()
    d = drag["derivation"]
    assert d["artifact_class"] == "derived"
    assert d["source_asset_key"] == A.REF_LADSON_FORCES
    assert d["source_filename"] == "CLCD_Ladson_expdata.dat"
    assert len(d["source_sha256"]) == 64
    assert d["source_sha256"] == A.registered_digest(
        A.REF_LADSON_FORCES, installed_assets
    )
    assert d["parser_version"] == refs.PARSER_VERSION
    assert d["transformations"]


def test_the_registered_assets_are_the_raw_authoritative_files():
    names = [a.filename for a in A.REGISTER.values()]
    assert [n for n in names if "familyII" not in n] == [
        "n0012_897-257.p3dfmt.gz",
        "n0012_449-129.p3dfmt.gz",
        "n0012_449-129_hex.cgns.gz",
        "CLCD_Ladson_expdata.dat",
        "n0012clcd_cfl3d_sst.dat",
        "n0012cp_cfl3d_sst.dat",
        "n0012cf_cfl3d_sst.dat",
    ]
    assert not any(n.endswith(".csv") for n in names)
    # The four reference datasets remain the raw TMR .dat files.
    assert sum(1 for n in names if n.endswith(".dat")) == 4


def test_tmr_provenance_uses_the_current_host():
    assert A.TMR_HOST == "https://tmbwg.github.io/turbmodels"
    for asset in A.REGISTER.values():
        assert "turbmodels.larc.nasa.gov" not in asset.source
    assert A.TMR_LEGACY_HOST in A.TMR_HOST_NOTE
