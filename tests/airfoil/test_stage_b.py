#!/usr/bin/env python3
"""Stage B: OpenFOAM MESH UTILITIES only. No flow solver, ever.

Every test here drives Stage B through a RECORDING runtime that captures each
script instead of executing it, so the full command sequence is asserted without
OpenFOAM and without any process at all.
"""
from __future__ import annotations

import re

import pytest

from src.families.airfoil.adapter import AirfoilAdapter
from src.pipeline.airfoil import assets as A
from src.pipeline.airfoil import mesh_audit, p3d
from src.pipeline.airfoil import stage_b as SB


class Result:
    def __init__(self, stdout: str = "", returncode: int = 0, stderr: str = ""):
        self.stdout, self.returncode, self.stderr = stdout, returncode, stderr

    @property
    def ok(self) -> bool:
        return self.returncode == 0


CHECKMESH_OK = """
Create polyMesh for time = 0

Mesh stats
    points:           2048
    faces:            5000
    internal faces:   2500
    cells:            1024
    faces per cell:   6
    boundary patches: 3
    point zones:      0

Overall number of cells of each type:
    hexahedra:     1024
    prisms:        0
    tetrahedra:    0

Checking topology...
    Boundary definition OK.
    Cell to face addressing OK.
    Point usage OK.
    Upper triangular ordering OK.
    Face vertices OK.
    Number of regions: 1 (OK).

Checking patch topology for multiply connected surfaces...
    Patch               Faces    Points
    airfoil                40        82
    farfield               96       196
    frontAndBack         2048      2048

Checking geometry...
    Overall domain bounding box (-500 -500 0) (501 500 1)
    Mesh has 2 geometric (non-empty/wedge/symmetry/empty) directions
    Boundary openness OK.
    Minimum face area = 1e-09. Maximum face area = 10.
    Mesh OK.

End
"""

BOUNDARY_AFTER = """
FoamFile
{
    version     2.0;
    format      ascii;
    class       polyBoundaryMesh;
    object      boundary;
}

3
(
    airfoil
    {
        type            wall;
        nFaces          40;
        startFace       2500;
    }
    farfield
    {
        type            patch;
        nFaces          96;
        startFace       2540;
    }
    frontAndBack
    {
        type            empty;
        nFaces          2048;
        startFace       2636;
    }
)
"""


class RecordingRuntime:
    """Captures scripts instead of running them. Mode mirrors FoamRuntime."""

    mode = "linux"
    bashrc = "/opt/openfoam14/etc/bashrc"

    def __init__(self, *, checkmesh: str = CHECKMESH_OK,
                 boundary: str = BOUNDARY_AFTER, fail_at: str = ""):
        self.scripts: list = []
        self.checkmesh, self.boundary, self.fail_at = checkmesh, boundary, fail_at

    def to_runtime_path(self, local) -> str:
        return str(local)

    def bash(self, script: str, *, foam: bool = True, timeout=None) -> Result:
        self.scripts.append(script)
        if self.fail_at and self.fail_at in script:
            return Result("", 1, f"simulated failure in {self.fail_at}")
        if "AIRFOIL_STAGEB_CASE" in script:
            return Result("AIRFOIL_STAGEB_CASE=/home/u/.cache/cfd-agent/x\n")
        if "gmshToFoam" in script:
            return Result("End\n")
        if "__PYEOF__" in script:
            return Result("AIRFOIL_STAGEB_BOUNDARY_REWRITTEN=3\n")
        if "polyMesh/boundary" in script:
            return Result(self.boundary)
        if "checkMesh" in script:
            return Result(self.checkmesh)
        return Result("")


@pytest.fixture
def converted(installed_assets, tmp_path):
    grid = p3d.read_plot3d(A.asset_path(A.MESH_CANONICAL, installed_assets))
    mesh = p3d.convert(grid, span=1.0)
    return mesh, p3d.write_gmsh(mesh, tmp_path / "mesh_canonical.msh")


# -- the allow-list -----------------------------------------------------
@pytest.mark.parametrize(
    "tool",
    ["foamRun", "simpleFoam", "pimpleFoam", "incompressibleFluid", "shockFluid",
     "rhoCentralFoam", "interFoam", "mpirun"],
)
def test_any_solver_command_is_refused_before_it_runs(tool):
    with pytest.raises(SB.StageBRefused) as exc:
        SB.assert_mesh_only(f"cd /case && {tool} -case .")
    assert "mesh utilities only" in str(exc.value)


def test_the_allow_list_is_mesh_utilities_only():
    assert SB.ALLOWED_TOOLS == ("gmshToFoam", "checkMesh", "foamDictionary")
    for forbidden in ("foamRun", "simpleFoam", "incompressibleFluid"):
        assert forbidden in SB.FORBIDDEN_TOOLS


def test_mesh_utility_commands_are_permitted():
    for script in ("cd /c && gmshToFoam mesh.msh",
                   "cd /c && checkMesh -allTopology -allGeometry"):
        SB.assert_mesh_only(script)


# -- THE regression test the correction asks for ------------------------
def test_stage_b_never_calls_the_cfd_solver(converted):
    """Every script Stage B issues, inspected for any solver name."""
    mesh, mesh_file = converted
    runtime = RecordingRuntime()
    SB.run_stage_b(mesh_file, runtime=runtime, expected_cells=mesh.cells)

    assert runtime.scripts, "Stage B issued no commands"
    for script in runtime.scripts:
        for tool in SB.FORBIDDEN_TOOLS:
            assert not re.search(rf"\b{re.escape(tool)}\b", script), (
                f"Stage B script named the solver {tool!r}: {script[:120]}"
            )
    joined = " ".join(runtime.scripts)
    assert "gmshToFoam" in joined
    assert "checkMesh -allTopology -allGeometry" in joined


def test_stage_b_spawns_no_process_of_its_own(converted, monkeypatch):
    """It must use the FoamRuntime bridge, not a second subprocess system."""
    import subprocess

    def boom(*a, **k):  # pragma: no cover
        raise AssertionError("Stage B spawned its own process")

    monkeypatch.setattr(subprocess, "run", boom)
    monkeypatch.setattr(subprocess, "Popen", boom)
    mesh, mesh_file = converted
    SB.run_stage_b(mesh_file, runtime=RecordingRuntime(), expected_cells=mesh.cells)


# -- the command sequence ----------------------------------------------
def test_stage_b_runs_the_four_steps_in_order(converted):
    mesh, mesh_file = converted
    runtime = RecordingRuntime()
    out = SB.run_stage_b(mesh_file, runtime=runtime, expected_cells=mesh.cells)
    labels = [c["label"] for c in out["commands"]]
    assert labels == ["stage_setup", "gmshToFoam", "boundary_rewrite",
                      "read_boundary", "checkMesh"]
    assert out["solver_invoked"] is False


def test_stage_b_passes_on_a_clean_report(converted):
    mesh, mesh_file = converted
    out = SB.run_stage_b(
        mesh_file, runtime=RecordingRuntime(), expected_cells=mesh.cells,
        expected_patch_faces={"airfoil": 40, "farfield": 96,
                              "frontAndBack": 2 * mesh.cells},
    )
    assert out["status"] == "STAGE_B_PASSED"
    assert out["ok"] is True
    assert out["empty_patches_ok"] is True
    assert out["patch_types"] == {"airfoil": "wall", "farfield": "patch",
                                  "frontAndBack": "empty"}
    checks = out["summary"]["checks"]
    assert checks["mesh_ok_reported"] is True
    assert checks["cell_count_matches"] is True
    assert checks["one_spanwise_cell"] is True
    assert checks["patch_types_correct"] is True


def test_stage_b_provenance_is_complete(converted):
    mesh, mesh_file = converted
    out = SB.run_stage_b(mesh_file, runtime=RecordingRuntime(),
                         expected_cells=mesh.cells)
    p = out["provenance"]
    for field in ("stage_b_version", "started_utc", "finished_utc", "runtime_mode",
                  "case_directory", "converted_mesh", "commands_run",
                  "tools_allowed", "expected_cells", "checkMesh_report",
                  "final_patch_types"):
        assert field in p, f"provenance missing {field}"
    assert p["solver_invoked"] is False


# -- parsing, not trusting the return code -----------------------------
def test_checkmesh_report_is_parsed():
    report = SB.parse_check_mesh(CHECKMESH_OK)
    assert report["mesh_ok"] is True
    assert report["cells"] == 1024
    assert report["hexahedra"] == 1024
    assert report["failed_checks"] == []
    assert report["patch_face_counts"]["frontAndBack"]["nFaces"] == 2048


def test_a_zero_exit_with_a_failed_check_does_not_pass(converted):
    """checkMesh can exit 0 while reporting ***Failed. The report is the evidence."""
    bad = CHECKMESH_OK.replace(
        "    Mesh OK.", " ***Number of severely non-orthogonal faces: 12."
    )
    mesh, mesh_file = converted
    out = SB.run_stage_b(mesh_file, runtime=RecordingRuntime(checkmesh=bad),
                         expected_cells=mesh.cells)
    assert out["status"] == "STAGE_B_FAILED"
    assert out["ok"] is False
    assert out["summary"]["failed_checks"]
    assert out["summary"]["checks"]["mesh_ok_reported"] is False


def test_a_cell_count_mismatch_fails(converted):
    mesh, mesh_file = converted
    out = SB.run_stage_b(mesh_file, runtime=RecordingRuntime(),
                         expected_cells=mesh.cells + 1)
    assert out["ok"] is False
    assert out["summary"]["checks"]["cell_count_matches"] is False


def test_a_wrong_patch_inventory_fails(converted):
    boundary = BOUNDARY_AFTER.replace("type            empty;",
                                      "type            patch;")
    mesh, mesh_file = converted
    out = SB.run_stage_b(mesh_file, runtime=RecordingRuntime(boundary=boundary),
                         expected_cells=mesh.cells)
    assert out["status"] == "PATCH_INVENTORY_WRONG"
    assert out["empty_patches_ok"] is False


def test_gmshtofoam_failure_stops_stage_b(converted):
    mesh, mesh_file = converted
    out = SB.run_stage_b(mesh_file,
                         runtime=RecordingRuntime(fail_at="gmshToFoam"),
                         expected_cells=mesh.cells)
    assert out["status"] == "GMSHTOFOAM_FAILED"
    assert out["ok"] is False


# -- the audit reaches PASSED only with both stages ---------------------
def test_audit_is_incomplete_without_a_runtime(installed_assets, tmp_path):
    report = mesh_audit.audit_grid(A.MESH_CANONICAL, repo_root=installed_assets,
                                   out_dir=tmp_path)
    assert report.stage_b["status"] == mesh_audit.NOT_RUN
    assert report.stage_b["solver_invoked"] is False
    assert report.status != "MESH_AUDIT_PASSED"
    assert "--with-openfoam" in report.stage_b["note"]


def test_audit_reaches_passed_with_stage_b(installed_assets, tmp_path, monkeypatch):
    """Stage A on the fixture + a clean Stage B == MESH_AUDIT_PASSED.

    The fixture is not 897 x 257, so the registry dimension check is pointed at
    the fixture's own shape for this test only: the purpose here is to prove the
    audit CAN reach PASSED once both stages pass, which is what the correction
    asked for.
    """
    from src.families.airfoil import spec as S

    grid = p3d.read_plot3d(A.asset_path(A.MESH_CANONICAL, installed_assets))
    monkeypatch.setitem(S.GRID_DIMENSIONS, A.MESH_CANONICAL, grid.dimensions)
    monkeypatch.setattr(mesh_audit, "GRID_DIMENSIONS", S.GRID_DIMENSIONS)

    report = mesh_audit.audit_grid(
        A.MESH_CANONICAL, repo_root=installed_assets, out_dir=tmp_path,
        runtime=RecordingRuntime(),
    )
    assert not report.failed, f"failed: {report.failed}"
    assert not report.unknown, f"indeterminate: {report.unknown}"
    assert report.status == "MESH_AUDIT_PASSED"
    assert report.to_dict()["cfd_launched"] is False
    assert report.provenance["stage_b"]["solver_invoked"] is False


def test_adapter_exposes_the_runtime_hook(installed_assets, tmp_path):
    out = AirfoilAdapter().audit_mesh(
        A.MESH_CANONICAL, repo_root=installed_assets, out_dir=tmp_path,
        runtime=RecordingRuntime(),
    )
    assert out["stage_b_openfoam"]["status"] in ("STAGE_B_PASSED", "STAGE_B_FAILED")
    assert out["cfd_launched"] is False
