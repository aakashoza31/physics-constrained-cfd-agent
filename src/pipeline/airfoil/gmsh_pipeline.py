#!/usr/bin/env python3
"""One deterministic Gmsh pipeline for the frozen F3 mesh hierarchy.

Every level runs the SAME code with the SAME algorithm, options and seed; only
the frozen level parameters differ. The 2D mesh is built once and extruded by
exactly one spanwise cell, so quads become hexes and triangles become prisms.

NO CFD. This module calls gmsh only.

TOPOLOGY
  native 2D boundary-layer field with quadrilateral wall layers, an explicit fan
  at the sharp trailing edge, a triangular outer region, no wrapped O-grid, no
  independent upper/lower extrusion, and no global recombination of the outer
  mesh.

SIZING
  The outer size follows the frozen formulae exactly, through a size callback
  rather than an approximate field expression: h_l = min(h_b, h_w) / r with
  h_b = min(50c, 0.002c + 0.12 d_a) and h_w = c(0.006 + 0.015 s) + 0.12 d_W.
"""
from __future__ import annotations

import hashlib
import math
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from src.pipeline.airfoil import geometry as G
from src.pipeline.airfoil import mesh_levels as L

PIPELINE_VERSION = "f3-gmsh-pipeline/2.0.0"

PATCH_AIRFOIL = "airfoil"
PATCH_FARFIELD = "farfield"
PATCH_FRONTBACK = "frontAndBack"
PHYSICAL_VOLUME = "internal"

#: Patch types the OpenFOAM boundary must end up with.
PATCH_TYPES = {
    PATCH_AIRFOIL: "wall",
    PATCH_FARFIELD: "patch",
    PATCH_FRONTBACK: "empty",
}


class GmshUnavailable(RuntimeError):
    """gmsh is not importable. Reported exactly, never worked around."""


REQUIRED_PACKAGE_SPEC = "gmsh>=4.11"
INSTALL_HINT = "pip install 'gmsh>=4.11'   (needs libGLU: apt-get install libglu1-mesa)"


def require_gmsh():
    try:
        import gmsh  # noqa: F401
    except (ImportError, OSError) as exc:
        raise GmshUnavailable(
            f"mesh generation requires {REQUIRED_PACKAGE_SPEC}: {exc}\n"
            f"    install with:  {INSTALL_HINT}"
        ) from exc
    import gmsh

    return gmsh


def gmsh_status() -> Dict[str, Any]:
    try:
        gmsh = require_gmsh()
    except GmshUnavailable as exc:
        return {"available": False, "package": REQUIRED_PACKAGE_SPEC,
                "install": INSTALL_HINT, "reason": str(exc).splitlines()[0]}
    gmsh.initialize()
    version = gmsh.option.getString("General.Version")
    gmsh.finalize()
    return {"available": True, "package": REQUIRED_PACKAGE_SPEC, "version": version}


# ----------------------------------------------------------------------
@dataclass
class GeneratedMesh:
    """A generated level: the file, the counts and the full provenance."""

    level: str
    path: Path
    cells: int
    hexes: int
    prisms: int
    points: int
    airfoil_faces: int
    farfield_faces: int
    frontback_faces: int
    sha256: str
    provenance: Dict[str, Any] = field(default_factory=dict)
    #: The extruded mesh itself, so qualification needs no re-read.
    mesh: Dict[str, Any] = field(default_factory=dict, repr=False)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "level": self.level,
            "mesh_file": str(self.path),
            "mesh_sha256": self.sha256,
            "cells": self.cells,
            "hexahedra": self.hexes,
            "prisms": self.prisms,
            "points": self.points,
            "patch_faces": {
                PATCH_AIRFOIL: self.airfoil_faces,
                PATCH_FARFIELD: self.farfield_faces,
                PATCH_FRONTBACK: self.frontback_faces,
            },
            "provenance": dict(self.provenance),
        }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def generate(
    level_name: str,
    out_dir: Path,
    *,
    section_n: Optional[int] = None,
    write_msh: bool = True,
    verbosity: int = 1,
) -> GeneratedMesh:
    """Generate one frozen level. Deterministic: same inputs, same bytes."""
    gmsh = require_gmsh()
    lv = L.level(level_name)
    stack = L.layer_stack(lv)
    if section_n is not None:
        raise ValueError(
            "section_n is not an override under recipe v2: the surface "
            "distribution is partitioned at x/c = 0.98 and is set by the frozen "
            "hierarchy, not by a caller."
        )
    # RECIPE v2 surface distribution. Same analytic geometry as v1; only the
    # station placement near the trailing edge differs.
    plan = L.surface_plan(lv)
    sec, build = G.section_v2(
        n_body=plan["body_intervals"],
        n_te=plan["te_intervals"],
        x_partition=plan["x_partition"],
        delta_te=plan["first_interval_prescribed"],
        q_max=plan["growth_ratio_max"],
    )
    started = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    gmsh.initialize()
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.option.setNumber("General.Verbosity", verbosity)
        gmsh.option.setNumber("General.NumThreads", 1)      # determinism
        gmsh.option.setNumber("Mesh.Algorithm", L.GMSH_ALGORITHM_2D)
        gmsh.option.setNumber("Mesh.RecombinationAlgorithm",
                              L.GMSH_RECOMBINE_ALGORITHM)
        gmsh.option.setNumber("Mesh.RecombineAll", 0)       # no global recombine
        gmsh.option.setNumber("Mesh.Smoothing", L.GMSH_SMOOTHING_STEPS)
        gmsh.option.setNumber("Mesh.Optimize", 1)
        gmsh.option.setNumber("Mesh.OptimizeNetgen",
                              1 if L.GMSH_OPTIMIZE_NETGEN else 0)
        gmsh.option.setNumber("Mesh.RandomSeed", L.GMSH_SEED)
        gmsh.option.setNumber("Mesh.MeshSizeExtendFromBoundary", 0)
        gmsh.option.setNumber("Mesh.MeshSizeFromPoints", 0)
        gmsh.option.setNumber("Mesh.MeshSizeFromCurvature", 0)
        gmsh.model.add(f"naca0012_{level_name}")

        # -- airfoil: one spline per side, TE shared ---------------------
        loop = sec.closed_loop()                 # 2N distinct points, TE at 0
        n = sec.n_per_side
        te_index = 0
        le_index = n                             # lower-reversed reaches LE at n
        pts = [gmsh.model.geo.addPoint(x, y, 0.0) for x, y in loop]
        te_point, le_point = pts[te_index], pts[le_index]

        # One straight edge per prescribed interval, each carrying exactly one
        # element. A spline would let gmsh re-discretise the surface and replace
        # the frozen cosine spacing with its own, which the recipe forbids: this
        # way the airfoil boundary passes exactly through the analytic ordinates
        # at exactly the frozen stations, and the face count is exactly 2N.
        airfoil_curves = [
            gmsh.model.geo.addLine(pts[i], pts[(i + 1) % len(pts)])
            for i in range(len(pts))
        ]
        airfoil_loop = gmsh.model.geo.addCurveLoop(airfoil_curves)

        # -- farfield rectangle ----------------------------------------
        corners = [
            gmsh.model.geo.addPoint(L.X_MIN, L.Y_MIN, 0.0),
            gmsh.model.geo.addPoint(L.X_MAX, L.Y_MIN, 0.0),
            gmsh.model.geo.addPoint(L.X_MAX, L.Y_MAX, 0.0),
            gmsh.model.geo.addPoint(L.X_MIN, L.Y_MAX, 0.0),
        ]
        far_curves = [
            gmsh.model.geo.addLine(corners[i], corners[(i + 1) % 4])
            for i in range(4)
        ]
        far_loop = gmsh.model.geo.addCurveLoop(far_curves)
        surface = gmsh.model.geo.addPlaneSurface([far_loop, airfoil_loop])
        for curve in airfoil_curves:
            gmsh.model.geo.mesh.setTransfiniteCurve(curve, 2)   # 2 nodes = 1 face
        gmsh.model.geo.synchronize()

        # -- boundary layer field: quad wall layers + explicit TE fan ---
        bl = gmsh.model.mesh.field.add("BoundaryLayer")
        gmsh.model.mesh.field.setNumbers(bl, "CurvesList", airfoil_curves)
        gmsh.model.mesh.field.setNumber(bl, "Size", lv.first_layer)
        gmsh.model.mesh.field.setNumber(bl, "Ratio", stack.growth_ratio)
        gmsh.model.mesh.field.setNumber(bl, "Thickness", lv.envelope)
        gmsh.model.mesh.field.setNumber(bl, "Quads", 1)
        gmsh.model.mesh.field.setNumbers(bl, "FanPointsList", [te_point])
        gmsh.model.mesh.field.setNumbers(
            bl, "FanPointsSizesList", [lv.fan_sectors]
        )
        gmsh.model.mesh.field.setNumber(bl, "SizeFar", lv.envelope)
        gmsh.model.mesh.field.setAsBoundaryLayer(bl)

        # -- outer sizing: the frozen formulae, evaluated exactly -------
        # The distance to the airfoil goes through a KD-tree: the callback is
        # invoked hundreds of thousands of times during meshing, and a linear
        # scan over the 2N surface points made generation superlinear in N.
        query = _section_distance_query(sec)

        def size_callback(dim, tag, x, y, z, lc):
            return L.target_size(x, y, query(x, y), lv.refinement)

        gmsh.model.mesh.setSizeCallback(size_callback)

        gmsh.model.mesh.generate(2)

        # -- extrude exactly one spanwise cell --------------------------
        # The extrusion is done HERE, deterministically, not by gmsh's geometric
        # extrude: with one boundary curve per prescribed surface interval the
        # geometry has 2N+4 boundary curves, and gmsh's extruded-surface
        # bookkeeping becomes the dominant cost. gmsh does the 2D meshing, which
        # is what it is for; the single spanwise layer is mechanical.
        plane = _extract_2d(gmsh, airfoil_curves, far_curves)
        extruded = extrude_one_layer(plane, span=L.SPAN)
        counts = {
            "hexes": len(extruded["hexes"]),
            "prisms": len(extruded["prisms"]),
            "other_3d": 0,
            "quads_2d": len(plane["quads"]),
            "tris_2d": len(plane["tris"]),
            "prescribed_airfoil_faces": sec.faces_total,
            "airfoil_edges_1d": len(plane["airfoil_edges"]),
            "farfield_edges_1d": len(plane["farfield_edges"]),
        }
        patch_counts = {
            PATCH_AIRFOIL: len(extruded["patches"][PATCH_AIRFOIL]),
            PATCH_FARFIELD: len(extruded["patches"][PATCH_FARFIELD]),
            PATCH_FRONTBACK: len(extruded["patches"][PATCH_FRONTBACK]),
        }
        node_count = len(extruded["points"])
        version = gmsh.option.getString("General.Version")
    finally:
        gmsh.finalize()

    path = out_dir / f"naca0012_{level_name}.msh"
    if write_msh:
        write_gmsh_3d(extruded, path)

    digest = _sha256(path) if write_msh and path.exists() else ""
    return GeneratedMesh(
        level=level_name,
        path=path,
        cells=counts["hexes"] + counts["prisms"],
        hexes=counts["hexes"],
        prisms=counts["prisms"],
        points=node_count,
        airfoil_faces=patch_counts[PATCH_AIRFOIL],
        farfield_faces=patch_counts[PATCH_FARFIELD],
        frontback_faces=patch_counts[PATCH_FRONTBACK],
        sha256=digest,
        mesh=extruded,
        provenance={
            "pipeline_version": PIPELINE_VERSION,
            "geometry_version": G.GEOMETRY_VERSION,
            "hierarchy_version": L.HIERARCHY_VERSION,
            "gmsh_version": version,
            "gmsh_seed": L.GMSH_SEED,
            "gmsh_algorithm_2d": L.GMSH_ALGORITHM_2D,
            "gmsh_recombination_algorithm": L.GMSH_RECOMBINE_ALGORITHM,
            "gmsh_smoothing": L.GMSH_SMOOTHING_STEPS,
            "gmsh_optimize_netgen": L.GMSH_OPTIMIZE_NETGEN,
            "global_recombine": False,
            "generated_utc": started,
            "level_parameters": lv.to_dict(),
            "layer_stack": stack.to_dict(),
            "geometry": sec.to_dict(),
            "recipe_version": L.RECIPE_VERSION,
            "surface_plan": plan,
            "surface_construction": build,
            "te_spacing_diagnostic": L.te_fan_spacing(lv),
            "farfield": {"x": [L.X_MIN, L.X_MAX], "y": [L.Y_MIN, L.Y_MAX]},
            "span": L.SPAN,
            "spanwise_cells": 1,
            "patch_types_for_openfoam": dict(PATCH_TYPES),
            "element_counts": counts,
            "cfd_launched": False,
        },
    )


# ----------------------------------------------------------------------
def _section_distance_query(sec: G.Section):
    """A fast, exact-enough distance-to-airfoil query built on the real section.

    Near the section the distance is the nearest-neighbour distance to the
    discrete surface points the mesh is actually built on, so the size field and
    the boundary agree by construction. Far away the point-to-chord distance is
    indistinguishable at the sizing scale and much cheaper.
    """
    points = sec.closed_loop()
    try:
        from scipy.spatial import cKDTree

        tree = cKDTree(points)

        def near(x: float, y: float) -> float:
            return float(tree.query((x, y))[0])
    except ImportError:  # pragma: no cover - scipy is a normal dependency
        def near(x: float, y: float) -> float:
            best = math.inf
            for px, py in points:
                best = min(best, (x - px) ** 2 + (y - py) ** 2)
            return math.sqrt(best)

    def query(x: float, y: float) -> float:
        if -0.2 <= x <= 1.4 and abs(y) <= 0.4:
            return near(x, y)
        cx = min(max(x, 0.0), 1.0)
        return math.hypot(x - cx, y)

    return query




# ----------------------------------------------------------------------
# deterministic one-layer extrusion of the 2D gmsh mesh
# ----------------------------------------------------------------------
_QUAD_TYPE, _TRI_TYPE, _LINE_TYPE = 3, 2, 1


def _extract_2d(gmsh, airfoil_curves: Sequence[int],
                far_curves: Sequence[int]) -> Dict[str, Any]:
    """Pull the 2D mesh and the boundary edges out of gmsh.

    Boundary edges come from the 1D elements ON THE NAMED CURVES, so patch
    membership is exact rather than inferred from coordinates.
    """
    tags, coords, _ = gmsh.model.mesh.getNodes()
    index = {int(t): n for n, t in enumerate(tags)}
    points = [
        (float(coords[3 * n]), float(coords[3 * n + 1])) for n in range(len(tags))
    ]

    quads: List[Tuple[int, int, int, int]] = []
    tris: List[Tuple[int, int, int]] = []
    types, _, conns = gmsh.model.mesh.getElements(2)
    for etype, conn in zip(types, conns):
        if etype == _QUAD_TYPE:
            quads.extend(
                tuple(index[int(v)] for v in conn[i:i + 4])
                for i in range(0, len(conn), 4)
            )
        elif etype == _TRI_TYPE:
            tris.extend(
                tuple(index[int(v)] for v in conn[i:i + 3])
                for i in range(0, len(conn), 3)
            )

    def edges_on(curves: Sequence[int]) -> List[Tuple[int, int]]:
        out: List[Tuple[int, int]] = []
        for curve in curves:
            etypes, _, econns = gmsh.model.mesh.getElements(1, curve)
            for etype, conn in zip(etypes, econns):
                if etype != _LINE_TYPE:
                    continue
                out.extend(
                    (index[int(conn[i])], index[int(conn[i + 1])])
                    for i in range(0, len(conn), 2)
                )
        return out

    return {
        "points": points,
        "quads": quads,
        "tris": tris,
        "airfoil_edges": edges_on(airfoil_curves),
        "farfield_edges": edges_on(far_curves),
    }


def extrude_one_layer(plane: Dict[str, Any], *, span: float) -> Dict[str, Any]:
    """Quads -> hexes, tris -> prisms, exactly one spanwise cell.

    The two spanwise planes sit at z = 0 and z = span, so the span used in force
    normalisation is exactly the frozen value.
    """
    base = plane["points"]
    n = len(base)
    points = [(x, y, 0.0) for x, y in base] + [(x, y, span) for x, y in base]

    def up(i: int) -> int:
        return i + n

    hexes = [tuple(list(q) + [up(v) for v in q]) for q in plane["quads"]]
    prisms = [tuple(list(tr) + [up(v) for v in tr]) for tr in plane["tris"]]

    patches: Dict[str, List[Tuple[int, ...]]] = {
        PATCH_AIRFOIL: [(a, b, up(b), up(a)) for a, b in plane["airfoil_edges"]],
        PATCH_FARFIELD: [(a, b, up(b), up(a)) for a, b in plane["farfield_edges"]],
        PATCH_FRONTBACK: (
            [tuple(reversed(q)) for q in plane["quads"]]
            + [tuple(reversed(tr)) for tr in plane["tris"]]
            + [tuple(up(v) for v in q) for q in plane["quads"]]
            + [tuple(up(v) for v in tr) for tr in plane["tris"]]
        ),
    }
    return {"points": points, "hexes": hexes, "prisms": prisms,
            "patches": patches, "span": span, "base_points": n}


_HEADER = """$MeshFormat
2.2 0 8
$EndMeshFormat
"""


def write_gmsh_3d(mesh: Dict[str, Any], path: Path) -> Path:
    """Write the extruded mesh as Gmsh 2.2 ASCII with named physical surfaces."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    names = [PATCH_AIRFOIL, PATCH_FARFIELD, PATCH_FRONTBACK]
    tags = {name: n + 1 for n, name in enumerate(names)}
    volume_tag = len(names) + 1

    out: List[str] = [_HEADER.rstrip("\n"), "$PhysicalNames", str(len(names) + 1)]
    for name in names:
        out.append(f'2 {tags[name]} "{name}"')
    out.append(f'3 {volume_tag} "{PHYSICAL_VOLUME}"')
    out.append("$EndPhysicalNames")

    out.append("$Nodes")
    out.append(str(len(mesh["points"])))
    for n, (px, py, pz) in enumerate(mesh["points"], start=1):
        out.append(f"{n} {px:.16g} {py:.16g} {pz:.16g}")
    out.append("$EndNodes")

    total = (
        len(mesh["hexes"]) + len(mesh["prisms"])
        + sum(len(v) for v in mesh["patches"].values())
    )
    out.append("$Elements")
    out.append(str(total))
    eid = 0
    for cell in mesh["hexes"]:
        eid += 1
        out.append(f"{eid} 5 2 {volume_tag} {volume_tag} "
                   + " ".join(str(v + 1) for v in cell))
    for cell in mesh["prisms"]:
        eid += 1
        out.append(f"{eid} 6 2 {volume_tag} {volume_tag} "
                   + " ".join(str(v + 1) for v in cell))
    for name in names:
        tag = tags[name]
        for face in mesh["patches"][name]:
            eid += 1
            etype = 3 if len(face) == 4 else 2
            out.append(f"{eid} {etype} 2 {tag} {tag} "
                       + " ".join(str(v + 1) for v in face))
    out.append("$EndElements")
    path.write_text("\n".join(out) + "\n", encoding="ascii")
    return path
