#!/usr/bin/env python3
"""NASA TMR NACA0012 Numerical Analysis FAMILY II -- the ACTIVE airfoil mesh path.

The mesh is NASA's. This module reads it, changes exactly one thing, and proves
that it changed nothing else.

  * IN-PLANE coordinates and connectivity are preserved EXACTLY, bit for bit.
    Nothing here regenerates, smooths, projects, optimises or remeshes.
  * The ONLY modification is the spanwise separation, rescaled from NASA's own
    span to our required b = 0.01 c, keeping exactly one spanwise cell.
  * Patches are assigned from the mesh's own topology: airfoil -> wall,
    farfield -> patch, frontAndBack -> empty. The joined C-grid wake stays
    INTERNAL connectivity and is never turned into a boundary.

The CGNS reading, the geometric diagnosis and the frozen quality gates are the
existing implementations (cgns.py, mesh_qualification.py, mesh_checks.py); this
module is the Family II entry point onto them, not a second pipeline.

NASA provenance does not override a failure. If the native grid violates the
frozen contract, that is reported as a failure of the grid -- it is never
patched, smoothed or waived here.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from src.pipeline.airfoil import cgns
from src.pipeline.airfoil import geometry as G
from src.pipeline.airfoil.gmsh_pipeline import (
    PATCH_AIRFOIL,
    PATCH_FARFIELD,
    PATCH_FRONTBACK,
    PATCH_TYPES,
)

FAMILY2_VERSION = "nasa-familyII-cgns/1.0.0"

COARSE, MEDIUM, FINE = "coarse", "medium", "fine"
LEVELS = (COARSE, MEDIUM, FINE)

#: NASA Family II structured dimensions each level corresponds to, and the cell
#: and airfoil-point counts they imply. NASA-declared, and re-derived below as
#: identities so a transcription error cannot survive.
DIMENSIONS: Dict[str, Tuple[int, int]] = {
    COARSE: (225, 65), MEDIUM: (449, 129), FINE: (897, 257),
}
AIRFOIL_SURFACE_POINTS: Dict[str, int] = {COARSE: 129, MEDIUM: 257, FINE: 513}


def cells_for(level: str) -> int:
    """(ni-1)(nj-1) -- the identity, not a transcribed integer."""
    ni, nj = DIMENSIONS[level]
    return (ni - 1) * (nj - 1)


CELLS: Dict[str, int] = {name: cells_for(name) for name in LEVELS}

#: Our required span. The ONE thing this module changes.
REQUIRED_SPAN = 0.01

#: Tolerances for the geometric cross-checks against the frozen TMR formula.
#: These bound OUR agreement with the analytic curve; they never modify the grid.
CHORD_TOLERANCE = 1.0e-9
TE_CLOSURE_TOLERANCE = 1.0e-9
#: NASA's grids are written in double precision from their own surface
#: definition, so agreement with our polynomial is expected at round-off, not at
#: zero. A discrepancy larger than this is REPORTED, never absorbed.
ORDINATE_DISCREPANCY_BUDGET = 1.0e-7
REFLECTION_BUDGET = 1.0e-12
FARFIELD_MIN_CHORDS = 100.0

#: Hex face vertex orderings, matching mesh_checks.HEX_FACES.
HEX_FACES = ((0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4),
             (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7))


class Family2Error(RuntimeError):
    """The Family II grid could not be used as supplied."""


@dataclass
class Converted:
    """One converted Family II level, plus the evidence that it is unchanged."""

    level: str
    mesh: Dict[str, Any]
    source: Dict[str, Any] = field(default_factory=dict)
    geometry_check: Dict[str, Any] = field(default_factory=dict)
    conversion_check: Dict[str, Any] = field(default_factory=dict)
    provenance: Dict[str, Any] = field(default_factory=dict)

    @property
    def cells(self) -> int:
        return len(self.mesh["hexes"])

    def to_dict(self) -> Dict[str, Any]:
        return {
            "level": self.level,
            "cells": self.cells,
            "points": len(self.mesh["points"]),
            "patch_faces": {k: len(v) for k, v in self.mesh["patches"].items()},
            "source": dict(self.source),
            "geometry_cross_check": dict(self.geometry_check),
            "conversion_cross_check": dict(self.conversion_check),
            "provenance": dict(self.provenance),
        }


# ----------------------------------------------------------------------
def _spanwise_planes(points: Sequence[Tuple[float, float, float]]) -> List[float]:
    return sorted({p[2] for p in points})


def read_source(level: str, path: Path) -> cgns.UnstructuredHexMesh:
    """Read one Family II CGNS level through the existing reader. Fails closed."""
    if level not in LEVELS:
        raise Family2Error(f"{level!r} is not a Family II level; expected {LEVELS}")
    return cgns.read_cgns_hex(Path(path), expected_cells=CELLS[level])


def rescale_span(points: Sequence[Tuple[float, float, float]], *,
                 span: float = REQUIRED_SPAN) -> Tuple[List[Tuple[float, float, float]],
                                                       Dict[str, Any]]:
    """Map the two spanwise planes onto 0 and `span`. In-plane values untouched.

    This is the ONLY modification made to NASA's coordinates. The in-plane pair
    is copied through by value, so a conversion cannot perturb it even by a
    round-trip through arithmetic.
    """
    planes = _spanwise_planes(points)
    if len(planes) != 2:
        raise Family2Error(
            f"the source carries {len(planes)} spanwise plane(s); Family II hex "
            "grids carry exactly two, which is one spanwise cell. Refusing to "
            "collapse or re-extrude."
        )
    low, high = planes
    out = [(p[0], p[1], 0.0 if p[2] == low else span) for p in points]
    return out, {
        "source_planes": [low, high],
        "source_span": high - low,
        "target_planes": [0.0, span],
        "required_span": span,
        "in_plane_modified": False,
        "note": ("only the spanwise coordinate is reassigned; x and y are copied "
                 "through unchanged"),
    }


def _boundary_faces(hexes: Sequence[Sequence[int]]) -> Dict[Tuple[int, ...], Tuple[int, Tuple[int, ...]]]:
    """Faces owned by exactly one cell, keyed by their sorted vertex set.

    A joined C-grid wake has two cells on every wake face, so those faces are
    absent here: the wake is internal by construction, not by assertion.
    """
    seen: Dict[Tuple[int, ...], List[Tuple[int, Tuple[int, ...]]]] = {}
    for ci, cell in enumerate(hexes):
        for local in HEX_FACES:
            face = tuple(cell[i] for i in local)
            seen.setdefault(tuple(sorted(face)), []).append((ci, face))
    return {k: v[0] for k, v in seen.items() if len(v) == 1}


def classify_patches(points: Sequence[Tuple[float, float, float]],
                     hexes: Sequence[Sequence[int]], *,
                     span: float = REQUIRED_SPAN) -> Tuple[Dict[str, List[Tuple[int, ...]]],
                                                           Dict[str, Any]]:
    """Assign every boundary face to exactly one patch, from the topology.

    * a face whose four vertices share one spanwise plane is frontAndBack;
    * of the remaining faces, those on the airfoil surface are the wall;
    * everything else is the farfield.

    The airfoil is identified by position on the analytic section rather than by
    a node list, so a misassignment would have to be a geometric coincidence.
    """
    boundary = _boundary_faces(hexes)
    patches: Dict[str, List[Tuple[int, ...]]] = {
        PATCH_AIRFOIL: [], PATCH_FARFIELD: [], PATCH_FRONTBACK: [],
    }
    unclassified: List[Tuple[int, ...]] = []
    worst_airfoil_error = 0.0

    for key, (_, face) in sorted(boundary.items()):
        zs = {points[v][2] for v in face}
        if len(zs) == 1:
            patches[PATCH_FRONTBACK].append(face)
            continue
        xs = [points[v][0] for v in face]
        ys = [points[v][1] for v in face]
        radius = max(math.hypot(x - 0.5, y) for x, y in zip(xs, ys))
        on_section = all(
            -1.0e-9 <= x <= 1.0 + 1.0e-9
            and abs(abs(y) - G.ordinate(min(max(x, 0.0), 1.0)))
            <= ORDINATE_DISCREPANCY_BUDGET
            for x, y in zip(xs, ys)
        )
        if on_section:
            patches[PATCH_AIRFOIL].append(face)
            worst_airfoil_error = max(
                worst_airfoil_error,
                max(abs(abs(y) - G.ordinate(min(max(x, 0.0), 1.0)))
                    for x, y in zip(xs, ys)),
            )
        elif radius >= FARFIELD_MIN_CHORDS:
            patches[PATCH_FARFIELD].append(face)
        else:
            unclassified.append(face)

    report = {
        "boundary_faces": len(boundary),
        "patch_faces": {k: len(v) for k, v in patches.items()},
        "unclassified_boundary_faces": len(unclassified),
        "worst_airfoil_ordinate_error": worst_airfoil_error,
        "patch_types": dict(PATCH_TYPES),
        "wake_is_internal": True,
        "wake_note": ("wake faces are shared by two cells and therefore never "
                      "appear as boundary faces; the wake is internal by "
                      "construction, not by assertion"),
    }
    if unclassified:
        sample = unclassified[0]
        report["wake_is_internal"] = False
        report["unclassified_sample"] = [list(points[v]) for v in sample]
    return patches, report


# ----------------------------------------------------------------------
def cross_check_geometry(points: Sequence[Tuple[float, float, float]],
                         patches: Dict[str, List[Tuple[int, ...]]]) -> Dict[str, Any]:
    """Verify NASA's surface against the FROZEN corrected TMR sharp-TE formula.

    Reported as measurements plus pass/fail flags. Nothing is adjusted to agree.
    """
    surface = sorted({v for face in patches[PATCH_AIRFOIL] for v in face})
    if not surface:
        return {"resolved": False,
                "reason": "no airfoil patch faces were classified"}
    xs = [points[v][0] for v in surface]
    ys = [points[v][1] for v in surface]
    chord = max(xs) - min(xs)

    worst_ordinate = 0.0
    worst_at = None
    for x, y in zip(xs, ys):
        clamped = min(max(x, 0.0), 1.0)
        error = abs(abs(y) - G.ordinate(clamped))
        if error > worst_ordinate:
            worst_ordinate, worst_at = error, (x, y)

    # Sharp trailing edge: the surface must close at x = 1 with y = 0.
    te_nodes = [(x, y) for x, y in zip(xs, ys) if abs(x - max(xs)) <= 1.0e-9]
    te_closure = max((abs(y) for _, y in te_nodes), default=float("inf"))

    # Upper / lower reflection, by pairing on x within the coordinate tolerance.
    upper = sorted((x, y) for x, y in zip(xs, ys) if y > 0.0)
    lower = sorted((x, -y) for x, y in zip(xs, ys) if y < 0.0)
    reflection = 0.0
    paired = 0
    lookup: Dict[float, List[float]] = {}
    for x, y in lower:
        lookup.setdefault(round(x, 12), []).append(y)
    for x, y in upper:
        candidates = lookup.get(round(x, 12))
        if candidates:
            reflection = max(reflection, min(abs(y - c) for c in candidates))
            paired += 1

    far_nodes = [math.hypot(p[0] - 0.5, p[1]) for p in points]
    return {
        "resolved": True,
        "airfoil_surface_points": len(surface),
        "chord": chord,
        "chord_ok": abs(chord - 1.0) <= CHORD_TOLERANCE,
        "trailing_edge_closure": te_closure,
        "trailing_edge_sharp": te_closure <= TE_CLOSURE_TOLERANCE,
        "max_ordinate_discrepancy": worst_ordinate,
        "max_ordinate_discrepancy_at": list(worst_at) if worst_at else None,
        "ordinate_budget": ORDINATE_DISCREPANCY_BUDGET,
        "ordinate_within_budget": worst_ordinate <= ORDINATE_DISCREPANCY_BUDGET,
        "reflection_max_error": reflection,
        "reflection_pairs": paired,
        "reflection_budget": REFLECTION_BUDGET,
        "reflection_ok": reflection <= REFLECTION_BUDGET,
        "farfield_max_radius_chords": max(far_nodes),
        "farfield_ok": max(far_nodes) >= FARFIELD_MIN_CHORDS,
        "formula": "corrected TMR sharp TE: x = xi/xi_T, y = +-0.6 f(xi)/xi_T",
        "xi_t": G.XI_T,
    }


def cross_check_conversion(level: str, source: cgns.UnstructuredHexMesh,
                           mesh: Dict[str, Any], span_report: Dict[str, Any],
                           patch_report: Dict[str, Any]) -> Dict[str, Any]:
    """Prove the conversion changed only the spanwise coordinate."""
    src_points = source.points
    out_points = mesh["points"]
    in_plane_error = max(
        (max(abs(a[0] - b[0]), abs(a[1] - b[1]))
         for a, b in zip(src_points, out_points)),
        default=0.0,
    )
    connectivity_identical = list(map(tuple, source.hexes)) == list(
        map(tuple, mesh["hexes"])
    )
    unique_points = len({(round(p[0], 12), round(p[1], 12), round(p[2], 12))
                         for p in out_points})
    duplicates = len(out_points) - unique_points

    # Orientation: signed volume of every hex, via its own face decomposition.
    negative = 0
    for cell in mesh["hexes"]:
        pts = [out_points[i] for i in cell]
        centre = (sum(p[0] for p in pts) / 8.0, sum(p[1] for p in pts) / 8.0,
                  sum(p[2] for p in pts) / 8.0)
        volume = 0.0
        for local in HEX_FACES:
            fp = [pts[i] for i in local]
            fc = (sum(q[0] for q in fp) / 4.0, sum(q[1] for q in fp) / 4.0,
                  sum(q[2] for q in fp) / 4.0)
            nx = ny = nz = 0.0
            for k in range(4):
                a, b = fp[k], fp[(k + 1) % 4]
                ax, ay, az = a[0] - fc[0], a[1] - fc[1], a[2] - fc[2]
                bx, by, bz = b[0] - fc[0], b[1] - fc[1], b[2] - fc[2]
                nx += ay * bz - az * by
                ny += az * bx - ax * bz
                nz += ax * by - ay * bx
            volume += 0.5 * ((fc[0] - centre[0]) * nx + (fc[1] - centre[1]) * ny
                             + (fc[2] - centre[2]) * nz) / 3.0
        if volume <= 0.0:
            negative += 1

    expected_cells = CELLS[level]
    ni, nj = DIMENSIONS[level]
    patch_faces = patch_report["patch_faces"]
    return {
        "expected_cells": expected_cells,
        "cells": len(mesh["hexes"]),
        "cells_match": len(mesh["hexes"]) == expected_cells,
        "cells_identity": f"({ni}-1)*({nj}-1) = {expected_cells}",
        "source_points": len(src_points),
        "points": len(out_points),
        "point_count_preserved": len(src_points) == len(out_points),
        "in_plane_coordinate_error": in_plane_error,
        "in_plane_preserved_exactly": in_plane_error == 0.0,
        "connectivity_identical": connectivity_identical,
        "duplicate_points": duplicates,
        "no_duplicate_or_merged_points": duplicates == 0,
        "cells_with_non_positive_volume": negative,
        "orientation_positive": negative == 0,
        "patch_faces": dict(patch_faces),
        "frontandback_equals_two_cells": (
            patch_faces.get("frontAndBack") == 2 * len(mesh["hexes"])
        ),
        "airfoil_faces_expected": AIRFOIL_SURFACE_POINTS[level] - 1,
        "airfoil_faces": patch_faces.get("airfoil"),
        "unclassified_boundary_faces": patch_report["unclassified_boundary_faces"],
        "wake_internal": patch_report["wake_is_internal"],
        "span": span_report,
    }


# ----------------------------------------------------------------------
def convert(level: str, path: Path, *, span: float = REQUIRED_SPAN) -> Converted:
    """Read one Family II level and produce the OpenFOAM-ready mesh."""
    source = read_source(level, path)
    points, span_report = rescale_span(source.points, span=span)
    hexes = [tuple(c) for c in source.hexes]
    patches, patch_report = classify_patches(points, hexes, span=span)
    mesh = {
        "points": points,
        "hexes": hexes,
        "prisms": [],
        "patches": patches,
        "base_points": None,
        "span": span,
    }
    geometry_check = cross_check_geometry(points, patches)
    conversion_check = cross_check_conversion(level, source, mesh, span_report,
                                              patch_report)
    return Converted(
        level=level,
        mesh=mesh,
        source=source.provenance,
        geometry_check=geometry_check,
        conversion_check=conversion_check,
        provenance={
            "family2_version": FAMILY2_VERSION,
            "geometry_version": G.GEOMETRY_VERSION,
            "authority": (
                "NASA TMR NACA0012 Numerical Analysis Family II, unstructured "
                "hexahedral CGNS; authoritative for in-plane coordinates and "
                "connectivity"
            ),
            "source_file": str(Path(path).name),
            "structured_dimensions": list(DIMENSIONS[level]),
            "modification": "spanwise separation only, set to b = 0.01 c",
            "not_done": ["regenerate", "smooth", "project", "optimise", "remesh"],
            "patch_types": dict(PATCH_TYPES),
            "cfd_launched": False,
        },
    )
