#!/usr/bin/env python3
"""Mandatory zero-CFD mesh audit for Family 3.

This NEVER launches the flow solver. It runs in two stages:

  Stage A -- pure Python, no OpenFOAM. Asset presence and digest, Plot3D parse,
             dimensions, converted cell count, chord and geometry scaling,
             trailing-edge sharpness, farfield extent, wake-cut detection and
             merge, exactly one spanwise layer, patch inventory, duplicate
             coincident wake faces, invalid cell volumes.

  Stage B -- requires the OpenFOAM runtime: gmshToFoam, the deterministic
             front/back -> empty rewrite, and
             checkMesh -allTopology -allGeometry.

Stage A alone is enough to refuse a mesh. Stage B is reported as NOT_RUN when no
runtime is available, and its absence keeps the audit INCOMPLETE rather than
letting it pass. checkMesh is a mesh utility; running it is not running CFD.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from src.pipeline.airfoil import assets as asset_mod
from src.pipeline.airfoil import p3d
from src.pipeline.airfoil import stage_b as stage_b_mod
from src.families.airfoil.spec import (
    CHORD_M,
    GRID_DIMENSIONS,
    NASA_SPAN_M,
    cells_for,
    flow_plane_dimensions,
)

#: Farfield must stay large. A mesh whose outer boundary is much closer than the
#: registered ~500 chords has been truncated, which this family forbids.
MIN_FARFIELD_CHORDS = 100.0

#: A sharp trailing edge, as a fraction of chord.
SHARP_TE_TOL_CHORD = 1.0e-6

NOT_RUN = "NOT_RUN"


@dataclass
class Check:
    name: str
    passed: Optional[bool]
    detail: str = ""
    measured: Any = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "check": self.name,
            "passed": self.passed,
            "detail": self.detail,
            "measured": self.measured,
        }


@dataclass
class AuditReport:
    grid_key: str
    checks: List[Check] = field(default_factory=list)
    provenance: Dict[str, Any] = field(default_factory=dict)
    stage_b: Dict[str, Any] = field(default_factory=dict)

    def add(self, name: str, passed: Optional[bool], detail: str = "",
            measured: Any = None) -> None:
        self.checks.append(Check(name, passed, detail, measured))

    @property
    def failed(self) -> List[str]:
        return [c.name for c in self.checks if c.passed is False]

    @property
    def unknown(self) -> List[str]:
        return [c.name for c in self.checks if c.passed is None]

    @property
    def status(self) -> str:
        if self.failed:
            return "MESH_AUDIT_FAILED"
        if self.unknown:
            return "MESH_AUDIT_INCOMPLETE"
        return "MESH_AUDIT_PASSED"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "grid": self.grid_key,
            "status": self.status,
            "failed": self.failed,
            "incomplete": self.unknown,
            "checks": [c.to_dict() for c in self.checks],
            "provenance": self.provenance,
            "stage_b_openfoam": self.stage_b,
            "cfd_launched": False,
            "authority": "deterministic",
        }


# ----------------------------------------------------------------------
def audit_grid(
    grid_key: str,
    *,
    repo_root: Optional[Path] = None,
    out_dir: Optional[Path] = None,
    write_mesh: bool = True,
    runtime: Optional[Any] = None,
    runtime_stage_b: Optional[Callable[[Path], Dict[str, Any]]] = None,
) -> AuditReport:
    """Audit one registered grid. No flow solver, ever."""
    report = AuditReport(grid_key=grid_key)
    started = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    if grid_key not in GRID_DIMENSIONS:
        report.add("grid_is_registered", False,
                   f"{grid_key!r} is not a registered grid key")
        return report
    report.add("grid_is_registered", True, measured=grid_key)

    # -- asset presence and digest -------------------------------------
    status = asset_mod.check_asset(grid_key, repo_root)
    report.add("asset_present", bool(status["present"]), status["reason"],
               measured=status["path"])
    report.add(
        "asset_sha256_registered",
        status["registered_sha256"] is not None,
        "SHA256 must be registered in configs/families/airfoil/assets.lock.json",
        measured=status["registered_sha256"],
    )
    report.add("asset_sha256_matches", bool(status["ok"]) if status["present"]
               and status["registered_sha256"] else False, status["reason"],
               measured=status["actual_sha256"])
    if not status["present"]:
        report.provenance = {
            "conversion_utc": started,
            "conversion_version": p3d.CONVERSION_VERSION,
            "conversion_toolchain": p3d.CONVERSION_TOOLCHAIN,
            "asset": asset_mod.REGISTER[grid_key].to_dict(),
            "note": "audit stopped: the registered asset is absent. Nothing substituted.",
        }
        return report

    path = Path(status["path"])
    expected_dims = GRID_DIMENSIONS[grid_key]

    # -- parse ---------------------------------------------------------
    try:
        grid = p3d.read_plot3d(path)
    except p3d.ConversionError as exc:
        report.add("plot3d_parses", False, str(exc))
        return report
    report.add("plot3d_parses", True, measured=list(grid.dimensions))

    report.add(
        "dimensions_match_registry",
        grid.dimensions == expected_dims,
        f"expected the NASA 3-D layout {expected_dims[0]} x {expected_dims[1]} x "
        f"{expected_dims[2]} (spanwise first)",
        measured=list(grid.dimensions),
    )
    report.add(
        "exactly_two_spanwise_planes",
        grid.n_span_planes == 2,
        "the registered grid carries exactly two spanwise planes",
        measured=grid.n_span_planes,
    )
    report.add(
        "source_cell_count",
        grid.cells_3d == cells_for(grid_key),
        f"(ni-1)*(nj-1)*(nk-1) must equal {cells_for(grid_key)}",
        measured={"cells_3d": grid.cells_3d, "cells_2d": grid.cells_2d},
    )

    # -- the two supplied planes, checked before anything is built ------
    try:
        spanwise = p3d.check_spanwise_planes(grid, expected_span=NASA_SPAN_M)
    except p3d.ConversionError as exc:
        report.add("spanwise_planes_consistent", False, str(exc))
        return report
    report.add(
        "spanwise_planes_identical_in_flow_plane",
        spanwise.identical_within_tolerance,
        f"worst flow-plane coordinate difference must be <= {p3d.PLANE_IDENTITY_TOL:.1e}",
        measured=spanwise.max_flow_plane_difference,
    )
    report.add(
        "spanwise_separation_matches_registered_span",
        spanwise.separation_matches_span and spanwise.separation_is_uniform,
        f"uniform separation equal to the registered span b = {NASA_SPAN_M}",
        measured=spanwise.to_dict(),
    )

    # -- convert -------------------------------------------------------
    try:
        mesh = p3d.convert(grid, span=NASA_SPAN_M)
    except p3d.ConversionError as exc:
        report.add("conversion_succeeds", False, str(exc))
        return report
    report.add("conversion_succeeds", True, measured=mesh.cells)

    report.add(
        "converted_cell_count",
        mesh.cells == cells_for(grid_key),
        f"converted cells must equal the registered {cells_for(grid_key)}",
        measured=mesh.cells,
    )
    report.add(
        "no_re_extrusion",
        abs(abs(mesh.span_coordinates[1] - mesh.span_coordinates[0]) - NASA_SPAN_M)
        <= p3d.SPAN_TOL,
        "the converted mesh uses NASA's own spanwise coordinates; nothing is "
        "re-extruded",
        measured={"span_coordinates": list(mesh.span_coordinates),
                  "span": mesh.span},
    )

    topo = mesh.topology
    report.add(
        "chord_scaling",
        abs(topo.chord - CHORD_M) <= 1.0e-6 * CHORD_M,
        f"chord must be {CHORD_M} m",
        measured=topo.chord,
    )
    report.add(
        "sharp_trailing_edge",
        topo.trailing_edge_gap <= SHARP_TE_TOL_CHORD * topo.chord,
        "NASA modified sharp trailing edge must be preserved",
        measured=topo.trailing_edge_gap,
    )
    report.add(
        "leading_edge_at_origin_side",
        topo.leading_edge[0] <= topo.trailing_edge[0],
        "leading edge must lie upstream of the trailing edge",
        measured=list(topo.leading_edge),
    )
    report.add(
        "farfield_not_truncated",
        topo.farfield_extent_chords >= MIN_FARFIELD_CHORDS,
        f"the registered farfield is ~500 chords; refuse below {MIN_FARFIELD_CHORDS}",
        measured=topo.farfield_extent_chords,
    )

    # -- wake cut ------------------------------------------------------
    report.add(
        "wake_cut_detected",
        topo.wake_pairs > 0,
        "coincident wake points must be found from the coordinates",
        measured=topo.wake_pairs,
    )
    report.add(
        "wake_interface_merged",
        mesh.merged_point_pairs == topo.wake_pairs,
        "every detected coincident pair must be merged to one point",
        measured=mesh.merged_point_pairs,
    )
    duplicates = p3d.duplicate_face_count(mesh)
    report.add(
        "no_duplicate_coincident_wake_faces",
        duplicates == 0,
        "a boundary face appearing twice means the C-grid slit is still open",
        measured=duplicates,
    )

    # -- extrusion and patches ----------------------------------------
    # "One layer" is an INTRINSIC property of the converted mesh: exactly two
    # spanwise point planes, and one cell per 2-D quad. Whether the count also
    # matches the registry is a separate check above, so a fixture of the wrong
    # size cannot make this one look like an extrusion fault.
    z_planes = sorted({round(pt[2], 12) for pt in mesh.points})
    report.add(
        "exactly_one_spanwise_layer",
        len(z_planes) == 2 and mesh.cells == grid.cells_2d
        and mesh.cells == grid.cells_3d,
        "one extruded layer: exactly two spanwise point planes and one cell per "
        "2-D quad",
        measured={
            "spanwise_point_planes": len(z_planes),
            "z_values": z_planes,
            "cells": mesh.cells,
            "source_cells_2d": grid.cells_2d,
            "source_cells_3d": grid.cells_3d,
        },
    )
    report.add(
        "patch_inventory",
        set(mesh.patches) == set(p3d.EXPECTED_PATCHES)
        and all(mesh.patches[k] for k in p3d.EXPECTED_PATCHES),
        f"expected patches {p3d.EXPECTED_PATCHES}, each non-empty",
        measured={k: len(v) for k, v in mesh.patches.items()},
    )
    report.add(
        "spanwise_patch_face_count",
        len(mesh.patches[p3d.PATCH_FRONT]) == mesh.cells
        and len(mesh.patches[p3d.PATCH_BACK]) == mesh.cells,
        "front and back must each carry exactly one face per cell",
        measured=[len(mesh.patches[p3d.PATCH_FRONT]),
                  len(mesh.patches[p3d.PATCH_BACK])],
    )
    report.add(
        "airfoil_patch_excludes_wake",
        len(mesh.patches[p3d.PATCH_AIRFOIL])
        == topo.surface_i_end - topo.surface_i_start,
        "the wall patch must cover the airfoil surface only, not the wake cut",
        measured=len(mesh.patches[p3d.PATCH_AIRFOIL]),
    )

    # -- volumes -------------------------------------------------------
    report.add(
        "no_invalid_cell_volumes",
        mesh.negative_or_zero_volume_cells == 0,
        "no zero or negative cell volume",
        measured={
            "bad_cells": mesh.negative_or_zero_volume_cells,
            "min_volume": mesh.min_cell_volume,
            "max_volume": mesh.max_cell_volume,
        },
    )

    # -- provenance ----------------------------------------------------
    report.provenance = {
        "source_filename": asset_mod.REGISTER[grid_key].filename,
        "source_sha256": status["actual_sha256"],
        "source_url": asset_mod.REGISTER[grid_key].source,
        "source_dimensions": list(grid.dimensions),
        "source_dimensions_meaning": "NASA ni x nj x nk, spanwise first",
        "axis_map_nasa_to_openfoam": dict(p3d.AXIS_MAP),
        "spanwise_plane_check": spanwise.to_dict(),
        "spanwise_coordinates": list(mesh.span_coordinates),
        "source_cells_2d": grid.cells_2d,
        "source_cells_3d": grid.cells_3d,
        "converted_cells": mesh.cells,
        "spanwise_layers": 1,
        "span_m": mesh.span,
        "conversion_utc": started,
        "conversion_version": p3d.CONVERSION_VERSION,
        "conversion_toolchain": p3d.CONVERSION_TOOLCHAIN,
        "topology": topo.to_dict(),
        "merged_point_pairs": mesh.merged_point_pairs,
        "geometry_regenerated": False,
        "geometry_note": (
            "geometry taken verbatim from the registered NASA grid; no polynomial "
            "regeneration, no custom C-grid generator, and no re-extrusion: the "
            "two spanwise planes supplied by NASA are used as they are"
        ),
    }

    # -- write the converted mesh -------------------------------------
    mesh_file: Optional[Path] = None
    if write_mesh and out_dir is not None:
        mesh_file = p3d.write_gmsh(mesh, Path(out_dir) / f"{grid_key}.msh")
        report.provenance["converted_mesh_file"] = str(mesh_file)
        report.provenance["converted_mesh_sha256"] = asset_mod.sha256_of(mesh_file)

    # -- stage B -------------------------------------------------------
    if runtime_stage_b is not None and mesh_file is not None:
        report.stage_b = dict(runtime_stage_b(mesh_file))
    elif runtime is not None and mesh_file is not None:
        report.stage_b = stage_b_mod.run_stage_b(
            mesh_file,
            runtime=runtime,
            expected_cells=mesh.cells,
            expected_patch_faces={
                p3d.PATCH_AIRFOIL: len(mesh.patches[p3d.PATCH_AIRFOIL]),
                p3d.PATCH_FARFIELD: len(mesh.patches[p3d.PATCH_FARFIELD]),
                "frontAndBack": 2 * mesh.cells,
            },
        )
        report.provenance["stage_b"] = report.stage_b.get("provenance", {})
    else:
        report.stage_b = {
            "status": NOT_RUN,
            "requires": "OpenFOAM Foundation v14 runtime",
            "steps": [
                "gmshToFoam <converted>.msh",
                "deterministic boundary rewrite: front/back -> empty (frontAndBack)",
                "checkMesh -allTopology -allGeometry",
            ],
            "note": (
                "checkMesh is a mesh utility, not the flow solver. Until stage B "
                "runs the audit is INCOMPLETE, never PASSED. Pass a FoamRuntime "
                "(audit CLI: --with-openfoam) to run it."
            ),
            "solver_invoked": False,
        }
    report.add(
        "checkMesh_allTopology_allGeometry",
        None if report.stage_b.get("status") == NOT_RUN
        else bool(report.stage_b.get("ok")),
        str(report.stage_b.get("note") or report.stage_b.get("status")),
        measured=report.stage_b.get("summary"),
    )
    report.add(
        "front_back_are_empty",
        None if report.stage_b.get("status") == NOT_RUN
        else bool(report.stage_b.get("empty_patches_ok")),
        "front/back must be merged into one 'frontAndBack' patch of type empty",
        measured=report.stage_b.get("patch_types"),
    )
    stage_b_checks = (report.stage_b.get("summary") or {}).get("checks") or {}
    report.add(
        "openfoam_cell_count_and_one_spanwise_cell",
        None if report.stage_b.get("status") == NOT_RUN
        else bool(stage_b_checks.get("cell_count_matches"))
        and bool(stage_b_checks.get("one_spanwise_cell")),
        "checkMesh must report the expected cell count and 2 faces per cell on "
        "frontAndBack (one spanwise cell)",
        measured={k: stage_b_checks.get(k) for k in
                  ("cell_count_matches", "one_spanwise_cell", "all_hexahedra")},
    )
    report.add(
        "openfoam_patch_inventory",
        None if report.stage_b.get("status") == NOT_RUN
        else bool(stage_b_checks.get("patch_types_correct")),
        f"final inventory must be {stage_b_mod.EXPECTED_PATCHES}",
        measured=report.stage_b.get("patch_types"),
    )
    return report


def audit_all(
    *,
    repo_root: Optional[Path] = None,
    out_dir: Optional[Path] = None,
    runtime: Optional[Any] = None,
) -> Dict[str, Any]:
    reports = {
        key: audit_grid(
            key, repo_root=repo_root, out_dir=out_dir, runtime=runtime
        ).to_dict()
        for key in GRID_DIMENSIONS
    }
    return {
        "family": "airfoil",
        "cfd_launched": False,
        "assets": asset_mod.audit_assets(repo_root),
        "grids": reports,
        "all_passed": all(r["status"] == "MESH_AUDIT_PASSED" for r in reports.values()),
    }
