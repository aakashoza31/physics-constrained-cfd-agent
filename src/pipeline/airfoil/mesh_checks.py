#!/usr/bin/env python3
"""Deterministic F3 mesh qualification. Pure geometry; no OpenFOAM, no CFD.

Every threshold below is the FROZEN value from the approved recipe. None is
computed from the mesh being judged and none may be widened. A sign that cannot
be resolved at floating-point precision yields INCONCLUSIVE, never PASS.

The raw ``checkMesh`` report, when supplied, is carried through unchanged and
sits beside this verdict rather than replacing it.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

from src.pipeline.airfoil import geometry as G
from src.pipeline.airfoil import mesh_levels as L
from src.pipeline.airfoil.gmsh_pipeline import (
    PATCH_AIRFOIL,
    PATCH_FARFIELD,
    PATCH_FRONTBACK,
    PATCH_TYPES,
)
from src.pipeline.airfoil.mesh_qualification import (
    SIGN_GUARD_RELATIVE,
    diagnose_cell_concavity,
    quad_diagnostics,
)

CHECKER_VERSION = "f3-mesh-checks/2.0.0"

PASSED = "F3_MESH_QUALIFIED"
FAILED = "F3_MESH_NOT_QUALIFIED"
INCONCLUSIVE = "F3_MESH_QUALIFICATION_INCONCLUSIVE"

# ---- FROZEN thresholds ------------------------------------------------
MAX_NON_ORTHOGONALITY_DEG = 65.0
MAX_SKEWNESS = 2.0
MIN_INTERPOLATION_WEIGHT = 0.10
MIN_FACE_VOLUME_RATIO = 0.10
MAX_IN_PLANE_STRETCHING = 10_000.0
ENVELOPE_RELATIVE_TOLERANCE = 0.02      # "realized envelope ~= 0.02c"
MAX_LAYER_DEVIATION = 1                 # at most one layer from nominal

# -- RECIPE v2 CONSTRUCTION CHECKS -------------------------------------
# These are ADDITIONAL to every threshold above, which is unchanged. They verify
# that the prescribed v2 surface distribution was actually realized in the mesh,
# measured FROM the mesh rather than assumed from the recipe.
V2_FIRST_TE_INTERVAL_TOLERANCE = 0.01       # realized within 1% of prescribed
V2_TE_FAN_RATIO_BOUNDS = (0.8, 1.25)        # surface interval / fan interval
V2_PARTITION_RATIO_MAX = 2.0                # adjacent ratio across x/c = 0.98
#: Frozen fan sector counts. v2 may not reduce them.
V2_FROZEN_FAN_SECTORS = {"coarse": 24, "medium": 36, "fine": 54}

#: Hex and prism face definitions, as local vertex indices.
HEX_FACES = ((0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4),
             (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7))
PRISM_FACES = ((0, 2, 1), (3, 4, 5), (0, 1, 4, 3), (1, 2, 5, 4), (2, 0, 3, 5))


def _centroid(pts: Sequence[Sequence[float]]) -> Tuple[float, float, float]:
    n = len(pts)
    return (sum(p[0] for p in pts) / n, sum(p[1] for p in pts) / n,
            sum(p[2] for p in pts) / n)


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1],
            a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0])


def _face_centre_normal(pts):
    """Face centre and area vector, as OpenFOAM computes them.

    This reproduces primitiveMeshFaceCentresAndAreas: a triangle uses the vertex
    mean, and any other face is decomposed about its vertex mean into triangles
    whose AREA-WEIGHTED centroid is the face centre. The vertex mean alone is not
    the face centre of a non-triangular face, and using it biases skewness and
    the interpolation weight on exactly the stretched cells whose thresholds
    matter -- so the metric must be computed the way the thresholds were defined.
    """
    n = len(pts)
    if n == 3:
        return _centroid(pts), tuple(
            0.5 * v for v in _cross(_sub(pts[1], pts[0]), _sub(pts[2], pts[0]))
        )
    est = _centroid(pts)
    sum_n = [0.0, 0.0, 0.0]
    sum_a = 0.0
    sum_ac = [0.0, 0.0, 0.0]
    for i in range(n):
        a, b = pts[i], pts[(i + 1) % n]
        centroid3 = (a[0] + b[0] + est[0], a[1] + b[1] + est[1], a[2] + b[2] + est[2])
        normal = _cross(_sub(b, a), _sub(est, a))
        area = _mag(normal)
        for k in range(3):
            sum_n[k] += normal[k]
            sum_ac[k] += area * centroid3[k]
        sum_a += area
    if sum_a < 1.0e-300:
        return est, tuple(0.5 * v for v in sum_n)
    return (tuple(v / (3.0 * sum_a) for v in sum_ac),
            tuple(0.5 * v for v in sum_n))


def _cell_centre_volume(faces):
    """Cell centre and volume, as OpenFOAM computes them.

    primitiveMeshCellCentresAndVols: a pyramid decomposition about the mean of
    the face centres, with the cell centre the VOLUME-weighted centroid of those
    pyramids. The vertex mean of a highly stretched cell is not its centroid, and
    the owner/neighbour vector that skewness and the interpolation weight are
    built on is measured between cell centres.

    ``faces`` is a sequence of (face_centre, area_vector). Orientation is taken
    outward with respect to the provisional centre, which is exact for the convex
    cells the concavity scan independently verifies.
    """
    est = _centroid([fc for fc, _ in faces])
    sum_v = 0.0
    sum_vc = [0.0, 0.0, 0.0]
    for fc, sf in faces:
        pyr3 = abs(_dot(sf, _sub(fc, est)))
        for k in range(3):
            sum_vc[k] += pyr3 * (0.75 * fc[k] + 0.25 * est[k])
        sum_v += pyr3
    if sum_v <= 0.0:
        return est, 0.0
    return tuple(v / sum_v for v in sum_vc), sum_v / 3.0


def _dot(a, b) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _mag(a) -> float:
    return math.sqrt(_dot(a, a))


@dataclass
class Check:
    name: str
    passed: Optional[bool]
    detail: str = ""
    measured: Any = None

    def to_dict(self) -> Dict[str, Any]:
        return {"check": self.name, "passed": self.passed, "detail": self.detail,
                "measured": self.measured}


@dataclass
class Report:
    level: str
    checks: List[Check] = field(default_factory=list)
    raw_check_mesh: Dict[str, Any] = field(default_factory=dict)
    metrics: Dict[str, Any] = field(default_factory=dict)
    provenance: Dict[str, Any] = field(default_factory=dict)

    def add(self, name, passed, detail="", measured=None) -> None:
        self.checks.append(Check(name, passed, detail, measured))

    @property
    def failed(self) -> List[str]:
        return [c.name for c in self.checks if c.passed is False]

    @property
    def unresolved(self) -> List[str]:
        return [c.name for c in self.checks if c.passed is None]

    @property
    def verdict(self) -> str:
        if self.failed:
            return FAILED
        if self.unresolved:
            return INCONCLUSIVE
        return PASSED

    def to_dict(self) -> Dict[str, Any]:
        return {
            "level": self.level,
            "qualification_verdict": self.verdict,
            "failed": self.failed,
            "unresolved": self.unresolved,
            "checks": [c.to_dict() for c in self.checks],
            "raw_openfoam_check_mesh": dict(self.raw_check_mesh),
            "metrics": dict(self.metrics),
            "provenance": dict(self.provenance),
            "thresholds": {
                "max_non_orthogonality_deg": MAX_NON_ORTHOGONALITY_DEG,
                "max_skewness": MAX_SKEWNESS,
                "min_interpolation_weight": MIN_INTERPOLATION_WEIGHT,
                "min_face_volume_ratio": MIN_FACE_VOLUME_RATIO,
                "max_in_plane_stretching": MAX_IN_PLANE_STRETCHING,
            },
            "cfd_launched": False,
            "authority": "deterministic",
            "note": ("this verdict is separate from the raw checkMesh report above "
                     "and does not modify it"),
        }


# ----------------------------------------------------------------------
def _surface_polyline(points, mesh) -> List[int]:
    """The airfoil surface as an ordered ring of base-plane node indices.

    Recovered from the airfoil patch faces themselves, so it reflects the MESH
    and not the recipe: each patch face is a spanwise quad whose two base-plane
    nodes are one surface interval.
    """
    edges: List[Tuple[int, int]] = []
    for face in mesh["patches"][PATCH_AIRFOIL]:
        base_nodes = [v for v in face if points[v][2] == 0.0]
        if len(base_nodes) != 2:
            return []
        edges.append((base_nodes[0], base_nodes[1]))
    adjacency: Dict[int, List[int]] = {}
    for a, b in edges:
        adjacency.setdefault(a, []).append(b)
        adjacency.setdefault(b, []).append(a)
    if any(len(v) != 2 for v in adjacency.values()):
        return []
    start = min(adjacency)
    ring = [start]
    previous = None
    current = start
    for _ in range(len(adjacency)):
        nxt = [v for v in adjacency[current] if v != previous]
        if not nxt:
            break
        previous, current = current, nxt[0]
        if current == start:
            break
        ring.append(current)
    return ring if len(ring) == len(adjacency) else []


def _v2_surface_checks(points, mesh, lv) -> Dict[str, Any]:
    """Measure the realized v2 surface distribution. Nothing is assumed."""
    plan = L.surface_plan(lv)
    out: Dict[str, Any] = {"plan": plan, "resolved": False}
    ring = _surface_polyline(points, mesh)
    if not ring:
        out["reason"] = ("the airfoil surface could not be recovered as a single "
                         "ring from the patch faces")
        return out

    def xy(i):
        return (points[i][0], points[i][1])

    def dist(i, j):
        a, b = xy(i), xy(j)
        return math.hypot(b[0] - a[0], b[1] - a[1])

    te_index = min(range(len(ring)),
                   key=lambda k: abs(xy(ring[k])[0] - 1.0) + abs(xy(ring[k])[1]))
    n = len(ring)
    # The two intervals incident to the trailing edge, one per surface.
    first_intervals = (dist(ring[te_index], ring[(te_index + 1) % n]),
                       dist(ring[te_index], ring[(te_index - 1) % n]))
    out["first_te_intervals_realized"] = list(first_intervals)
    out["first_te_interval_realized"] = min(first_intervals)
    out["first_te_interval_prescribed"] = plan["first_interval_prescribed"]
    out["first_te_interval_relative_error"] = max(
        abs(v - plan["first_interval_prescribed"]) / plan["first_interval_prescribed"]
        for v in first_intervals
    )

    # Realized fan circumferential spacing, measured from the nodes that sit on
    # the first-layer circle about the trailing edge.
    te_xy = xy(ring[te_index])
    h1 = lv.first_layer
    on_circle = []
    for i, p in enumerate(points):
        if p[2] != 0.0:
            continue
        r = math.hypot(p[0] - te_xy[0], p[1] - te_xy[1])
        if 0.5 * h1 <= r <= 1.5 * h1:
            on_circle.append((math.atan2(p[1] - te_xy[1], p[0] - te_xy[0]), i))
    out["fan_nodes_on_first_layer_circle"] = len(on_circle)
    if len(on_circle) >= 3:
        on_circle.sort()
        gaps = [dist(on_circle[k][1], on_circle[k + 1][1])
                for k in range(len(on_circle) - 1)]
        gaps.sort()
        median = gaps[len(gaps) // 2]
        out["fan_interval_realized"] = median
        out["fan_interval_range"] = [gaps[0], gaps[-1]]
        out["te_surface_to_fan_ratio"] = out["first_te_interval_realized"] / median
    else:
        out["fan_interval_realized"] = None
        out["te_surface_to_fan_ratio"] = None

    # Adjacent interval ratio across the partition, on each surface.
    x_t = plan["x_partition"]
    ratios = []
    partition_nodes = []
    for k in range(n):
        if abs(xy(ring[k])[0] - x_t) <= 1.0e-9:
            partition_nodes.append(k)
            a = dist(ring[(k - 1) % n], ring[k])
            b = dist(ring[k], ring[(k + 1) % n])
            if a > 0.0 and b > 0.0:
                ratios.append(max(a / b, b / a))
    out["partition_nodes_found"] = len(partition_nodes)
    out["partition_adjacent_ratio"] = max(ratios) if ratios else None

    # Every prescribed station must still be in the mesh.
    station_xs = sorted(set(round(x, 12) for x in plan_stations(lv)))
    mesh_xs = sorted(set(round(points[i][0], 12) for i in ring))
    missing = [x for x in station_xs if x not in mesh_xs]
    out["prescribed_stations"] = len(station_xs)
    out["missing_prescribed_stations"] = len(missing)
    out["airfoil_faces_realized"] = len(mesh["patches"][PATCH_AIRFOIL])
    out["airfoil_faces_prescribed"] = plan["airfoil_faces"]

    # No geometry rounding: every surface node lies on the analytic section.
    worst = 0.0
    for i in ring:
        x, y = xy(i)
        if 0.0 < x < 1.0:
            worst = max(worst, abs(abs(y) - abs(G.ordinate(x))))
    out["max_ordinate_deviation"] = worst
    out["ordinate_budget"] = G.BOUNDARY_ERROR_BUDGET
    out["resolved"] = True
    return out


def plan_stations(lv) -> List[float]:
    """The prescribed v2 stations for one level, from the recipe alone."""
    plan = L.surface_plan(lv)
    return G.v2_stations(
        n_body=plan["body_intervals"], n_te=plan["te_intervals"],
        x_partition=plan["x_partition"],
        delta_te=plan["first_interval_prescribed"],
        q_max=plan["growth_ratio_max"],
    )["stations"]


# ----------------------------------------------------------------------
def apply_frozen_gates(report: "Report", points, cells, mesh, internal, *,
                       concavity_sample: Optional[int] = None) -> Dict[str, Any]:
    """Every FROZEN quality gate, applied identically to any mesh we qualify.

    One function so that the Gmsh hierarchy (archived) and the NASA Family II
    hierarchy (active) are judged by the same code against the same thresholds.
    No caller may pass a threshold in: they are module constants, and a mesh's
    provenance never changes them.

    Returns the measured geometry, in-plane and concavity dictionaries so a
    caller can add provenance-specific checks on top.
    """
    #: Index offset between the two spanwise point planes of a one-cell mesh.
    base = mesh.get("base_points", len(points) // 2)

    # -- volumes, areas, pyramids, tets, flatness ----------------------
    geometry = _cell_geometry(points, cells, internal,
                              n_hexes=len(mesh["hexes"]))
    report.metrics.update(geometry["metrics"])
    report.add("positive_cell_volumes", geometry["min_volume"] > 0.0,
               "every cell volume must be positive", geometry["min_volume"])
    report.add("positive_face_areas", geometry["min_area"] > 0.0,
               "every face area must be positive", geometry["min_area"])
    report.add("face_pyramid_checks", geometry["pyramids_ok"],
               "every face pyramid about its cell centre must have positive volume",
               geometry["min_pyramid"])
    report.add("face_tet_checks", geometry["tets_ok"],
               "every face decomposition tet must have positive volume",
               geometry["min_tet"])
    report.add("face_flatness_and_closure", geometry["flatness_ok"],
               "face closure error must vanish and faces must be flat to tolerance",
               {"max_closure": geometry["max_closure"],
                "min_flatness": geometry["min_flatness"]})

    # -- OpenFOAM-metric thresholds ------------------------------------
    report.add("max_non_orthogonality",
               geometry["max_non_orthogonality"] <= MAX_NON_ORTHOGONALITY_DEG,
               f"<= {MAX_NON_ORTHOGONALITY_DEG} deg",
               geometry["max_non_orthogonality"])
    report.add("max_skewness", geometry["max_skewness"] <= MAX_SKEWNESS,
               f"<= {MAX_SKEWNESS}", geometry["max_skewness"])
    report.add("min_interpolation_weight",
               geometry["min_weight"] >= MIN_INTERPOLATION_WEIGHT,
               f">= {MIN_INTERPOLATION_WEIGHT}", geometry["min_weight"])
    report.add("min_face_volume_ratio",
               geometry["min_volume_ratio"] >= MIN_FACE_VOLUME_RATIO,
               f">= {MIN_FACE_VOLUME_RATIO}", geometry["min_volume_ratio"])

    # -- in-plane element validity -------------------------------------
    plane = _in_plane_checks(points, mesh, base)
    report.metrics.update(plane["metrics"])
    report.add("no_self_intersecting_polygons", plane["no_crossed"],
               "no in-plane element may have crossed edges", plane["n_crossed"])
    report.add("all_in_plane_elements_valid", plane["all_valid"],
               "every triangle and quadrilateral must have positive area",
               plane["n_invalid"])
    report.add("quads_strictly_convex", plane["quads_convex"],
               "every quadrilateral must be strictly convex", plane["n_non_convex"])
    report.add("positive_bilinear_jacobian", plane["jacobians_positive"],
               "the bilinear Jacobian must be positive at all four corners",
               plane["n_bad_jacobian"])
    report.add("no_collapsed_edges", plane["no_collapsed"],
               "no in-plane edge may have zero length", plane["min_edge"])
    report.add("max_in_plane_stretching",
               plane["max_stretching"] <= MAX_IN_PLANE_STRETCHING,
               f"longest edge / minimum altitude <= {MAX_IN_PLANE_STRETCHING}",
               plane["max_stretching"])
    if plane["unresolved"]:
        report.add("in_plane_sign_resolution", None,
                   "some in-plane geometric sign could not be resolved",
                   plane["unresolved"])

    # -- genuine concavity ---------------------------------------------
    concavity = _concavity_scan(points, mesh["hexes"], sample=concavity_sample)
    report.metrics["concavity"] = concavity
    report.add("no_genuine_concavity",
               None if concavity["unresolved"] else concavity["genuine"] == 0,
               "a genuinely concave cell disqualifies the mesh; a near-planarity "
               "flag qualifies only if independent geometry proves convexity",
               {k: concavity[k] for k in ("scanned", "genuine", "unresolved")})

    return {"geometry": geometry, "plane": plane, "concavity": concavity}


# ----------------------------------------------------------------------
def qualify_mesh(
    mesh: Dict[str, Any],
    *,
    level_name: str,
    raw_check_mesh: Optional[Dict[str, Any]] = None,
    concavity_sample: Optional[int] = None,
) -> Report:
    """Qualify one extruded mesh dict from gmsh_pipeline.extrude_one_layer."""
    report = Report(level=level_name)
    report.raw_check_mesh = dict(raw_check_mesh or {})
    lv = L.level(level_name)
    stack = L.layer_stack(lv)

    points = mesh["points"]
    cells: List[Tuple[Tuple[int, ...], Tuple[Tuple[int, ...], ...]]] = (
        [(c, HEX_FACES) for c in mesh["hexes"]]
        + [(c, PRISM_FACES) for c in mesh["prisms"]]
    )
    n_cells = len(cells)

    # -- face map: owner/neighbour, duplicates, non-manifold -----------
    faces: Dict[Tuple[int, ...], List[int]] = {}
    for ci, (cell, local_faces) in enumerate(cells):
        for local in local_faces:
            key = tuple(sorted(cell[i] for i in local))
            faces.setdefault(key, []).append(ci)
    internal = {k: v for k, v in faces.items() if len(v) == 2}
    boundary = {k: v for k, v in faces.items() if len(v) == 1}
    overfull = {k: v for k, v in faces.items() if len(v) > 2}

    report.add("no_non_manifold_connectivity", len(overfull) == 0,
               "no face may be shared by more than two cells", len(overfull))
    report.add("no_duplicate_faces", len(overfull) == 0,
               "a repeated face would appear as an over-shared face", len(overfull))

    # -- patch membership ----------------------------------------------
    declared: Dict[Tuple[int, ...], str] = {}
    overlap = 0
    for name, patch_faces in mesh["patches"].items():
        for face in patch_faces:
            key = tuple(sorted(face))
            if key in declared:
                overlap += 1
            declared[key] = name
    missing = [k for k in boundary if k not in declared]
    extra = [k for k in declared if k not in boundary]
    report.add("correct_patch_membership",
               not missing and not extra and overlap == 0,
               "every boundary face belongs to exactly one declared patch",
               {"boundary_faces": len(boundary), "declared": len(declared),
                "undeclared_boundary_faces": len(missing),
                "declared_but_internal": len(extra), "overlapping": overlap})
    report.add("no_unintended_internal_boundaries", len(extra) == 0,
               "no declared patch face may lie between two cells", len(extra))
    report.add("patch_types_registered",
               set(mesh["patches"]) == set(PATCH_TYPES),
               f"patches must be exactly {tuple(PATCH_TYPES)}",
               {k: PATCH_TYPES[k] for k in PATCH_TYPES})

    # -- one connected region ------------------------------------------
    adjacency: Dict[int, List[int]] = {i: [] for i in range(n_cells)}
    for a, b in internal.values():
        adjacency[a].append(b)
        adjacency[b].append(a)
    seen = [False] * n_cells
    stack_ = [0] if n_cells else []
    seen[0] = True if n_cells else False
    visited = 0
    while stack_:
        c = stack_.pop()
        visited += 1
        for nb in adjacency[c]:
            if not seen[nb]:
                seen[nb] = True
                stack_.append(nb)
    report.add("one_connected_fluid_region", visited == n_cells,
               "the cell adjacency graph must be a single component",
               {"cells": n_cells, "reached": visited})

    # -- one spanwise layer, two directions, matching planes -----------
    zs = sorted({round(p[2], 12) for p in points})
    report.add("exactly_one_spanwise_layer",
               len(zs) == 2 and abs((zs[1] - zs[0]) - L.SPAN) <= 1e-12,
               f"two spanwise point planes, {L.SPAN} apart",
               {"z_planes": zs, "span": (zs[1] - zs[0]) if len(zs) == 2 else None})
    base = mesh.get("base_points", len(points) // 2)
    mismatch = max(
        (max(abs(points[i][0] - points[i + base][0]),
             abs(points[i][1] - points[i + base][1])) for i in range(base)),
        default=0.0,
    )
    report.add("front_back_flow_plane_coordinates_match", mismatch == 0.0,
               "the two spanwise planes must share x and y exactly", mismatch)
    report.add("two_geometric_directions", len(zs) == 2,
               "a one-cell extrusion leaves two solution directions", len(zs))

    # -- every frozen gate, shared with the NASA Family II path ---------
    gates = apply_frozen_gates(report, points, cells, mesh, internal,
                               concavity_sample=concavity_sample)
    geometry, plane = gates["geometry"], gates["plane"]
    # Reported diagnostic, not a criterion: it explains a trailing-edge failure.
    report.metrics["te_spacing_diagnostic"] = L.te_fan_spacing(lv)

    # -- prescribed boundary layer -------------------------------------
    report.add("bl_growth_ratio_within_limit",
               stack.growth_ratio < L.MAX_GROWTH_RATIO,
               f"q < {L.MAX_GROWTH_RATIO}", stack.growth_ratio)
    report.add("bl_envelope_realized",
               abs(stack.realized_envelope - lv.envelope) / lv.envelope
               <= ENVELOPE_RELATIVE_TOLERANCE,
               f"realized envelope within {ENVELOPE_RELATIVE_TOLERANCE:.0%} of "
               f"{lv.envelope}", stack.realized_envelope)
    report.add("bl_layer_count_within_one_of_nominal",
               abs(stack.realized_layers - lv.nominal_layers) <= MAX_LAYER_DEVIATION,
               f"at most {MAX_LAYER_DEVIATION} layer from nominal "
               f"{lv.nominal_layers}", stack.realized_layers)
    report.add("bl_first_layer_as_prescribed",
               stack.first_layer == lv.first_layer,
               f"h1/c must be exactly {lv.first_layer}", stack.first_layer)
    report.add("airfoil_faces_as_prescribed",
               len(mesh["patches"][PATCH_AIRFOIL]) == lv.airfoil_faces,
               f"exactly {lv.airfoil_faces} airfoil faces",
               len(mesh["patches"][PATCH_AIRFOIL]))

    # -- RECIPE v2 construction checks, additional to everything above --
    v2 = _v2_surface_checks(points, mesh, lv)
    report.metrics["v2_surface_construction"] = v2
    lo, hi = V2_TE_FAN_RATIO_BOUNDS
    if not v2["resolved"]:
        for name in ("v2_first_te_interval_as_prescribed",
                     "v2_te_surface_to_fan_spacing_ratio",
                     "v2_partition_adjacent_spacing_ratio",
                     "v2_no_prescribed_te_nodes_removed",
                     "v2_no_geometry_rounding"):
            report.add(name, None, v2.get("reason", "not measurable"), None)
    else:
        report.add("v2_first_te_interval_as_prescribed",
                   v2["first_te_interval_relative_error"]
                   <= V2_FIRST_TE_INTERVAL_TOLERANCE,
                   f"realized first TE surface interval within "
                   f"{V2_FIRST_TE_INTERVAL_TOLERANCE:.0%} of "
                   f"{v2['first_te_interval_prescribed']:.8e}",
                   {"realized": v2["first_te_intervals_realized"],
                    "relative_error": v2["first_te_interval_relative_error"]})
        ratio = v2["te_surface_to_fan_ratio"]
        report.add("v2_te_surface_to_fan_spacing_ratio",
                   None if ratio is None else lo <= ratio <= hi,
                   f"first TE surface interval / first fan circumferential "
                   f"interval in [{lo}, {hi}]",
                   {"ratio": ratio,
                    "fan_interval_realized": v2["fan_interval_realized"],
                    "fan_nodes_found": v2["fan_nodes_on_first_layer_circle"]})
        partition = v2["partition_adjacent_ratio"]
        report.add("v2_partition_adjacent_spacing_ratio",
                   None if partition is None
                   else partition <= V2_PARTITION_RATIO_MAX,
                   f"adjacent surface-interval ratio across x/c = "
                   f"{v2['plan']['x_partition']} at most "
                   f"{V2_PARTITION_RATIO_MAX} in either direction",
                   {"ratio": partition,
                    "partition_nodes": v2["partition_nodes_found"]})
        report.add("v2_no_prescribed_te_nodes_removed",
                   v2["missing_prescribed_stations"] == 0
                   and v2["airfoil_faces_realized"] == v2["airfoil_faces_prescribed"],
                   "every prescribed surface station must survive into the mesh",
                   {"missing": v2["missing_prescribed_stations"],
                    "faces_realized": v2["airfoil_faces_realized"],
                    "faces_prescribed": v2["airfoil_faces_prescribed"]})
        report.add("v2_no_geometry_rounding",
                   v2["max_ordinate_deviation"] <= v2["ordinate_budget"],
                   "every surface node must lie on the analytic section within "
                   f"{v2['ordinate_budget']:.0e} c",
                   v2["max_ordinate_deviation"])
    report.add("v2_no_layer_collapse",
               geometry["min_volume"] > 0.0 and geometry["min_area"] > 0.0
               and plane["min_edge"] > 0.0
               and abs(stack.realized_layers - lv.nominal_layers)
               <= MAX_LAYER_DEVIATION,
               "no cell, face or edge may collapse and the wall-layer count must "
               "hold",
               {"min_volume": geometry["min_volume"],
                "min_face_area": geometry["min_area"],
                "min_in_plane_edge": plane["min_edge"],
                "realized_layers": stack.realized_layers})
    report.add("v2_fan_sectors_unchanged",
               lv.fan_sectors == V2_FROZEN_FAN_SECTORS[level_name],
               f"fan sectors must remain {V2_FROZEN_FAN_SECTORS[level_name]}",
               lv.fan_sectors)

    report.provenance = {
        "checker_version": CHECKER_VERSION,
        "level": level_name,
        "cells": n_cells,
        "hexes": len(mesh["hexes"]),
        "prisms": len(mesh["prisms"]),
        "points": len(points),
        "internal_faces": len(internal),
        "boundary_faces": len(boundary),
        "level_parameters": lv.to_dict(),
        "layer_stack": stack.to_dict(),
        "raw_check_mesh_preserved": True,
        "cfd_launched": False,
        "small_determinant_policy": (
            "a small cell determinant is diagnostic only once independent "
            "geometric validity passes; it is never an acceptance gate here"
        ),
    }
    return report


# ----------------------------------------------------------------------
def _cell_geometry(points, cells, internal, n_hexes: int = 0) -> Dict[str, Any]:
    centres: List[Tuple[float, float, float]] = []
    volumes: List[float] = []
    min_pyr = math.inf
    min_tet = math.inf
    min_area = math.inf
    max_closure = 0.0
    min_flatness = math.inf

    for cell, local_faces in cells:
        # Face geometry first: the cell centre and volume are built from it, the
        # way OpenFOAM builds them.
        face_geometry = []
        for local in local_faces:
            fpts = [points[cell[i]] for i in local]
            face_geometry.append((fpts, *_face_centre_normal(fpts)))
        centre, volume = _cell_centre_volume(
            [(fc, sf) for _, fc, sf in face_geometry]
        )
        centres.append(centre)
        volumes.append(volume)
        for fpts, fc, normal in face_geometry:
            area = _mag(normal)
            min_area = min(min_area, area)
            # Outward orientation with respect to the cell centre. Face vertex
            # order is not assumed to be outward, so it is established here once
            # and used by both the tet and the pyramid check, which therefore
            # detect a NEGATIVE volume instead of hiding it inside abs().
            outward = 1.0 if _dot(normal, _sub(fc, centre)) >= 0.0 else -1.0
            # closure: the edge vectors of a closed polygon must sum to zero
            closure = [0.0, 0.0, 0.0]
            for i in range(len(fpts)):
                a, b = fpts[i], fpts[(i + 1) % len(fpts)]
                for k in range(3):
                    closure[k] += b[k] - a[k]
            scale = max(_mag(_sub(fpts[1], fpts[0])), 1e-300)
            max_closure = max(max_closure, _mag(closure) / scale)
            # flatness: |sum of triangle areas| vs |area vector|
            tri_area = 0.0
            for i in range(len(fpts)):
                a, b = fpts[i], fpts[(i + 1) % len(fpts)]
                d1, d2 = _sub(a, fc), _sub(b, fc)
                cr = (d1[1] * d2[2] - d1[2] * d2[1],
                      d1[2] * d2[0] - d1[0] * d2[2],
                      d1[0] * d2[1] - d1[1] * d2[0])
                t = 0.5 * _mag(cr)
                tri_area += t
                min_tet = min(min_tet, outward * _dot(cr, _sub(fc, centre)) / 6.0)
            if tri_area > 0.0:
                min_flatness = min(min_flatness, area / tri_area)
            # Face pyramid volume about the cell centre. Signed, so a cell
            # centre outside the cell is caught rather than absorbed.
            pyramid = outward * _dot(normal, _sub(fc, centre)) / 3.0
            min_pyr = min(min_pyr, pyramid)

    max_non_orth = 0.0
    max_skew = 0.0
    min_weight = math.inf
    min_ratio = math.inf
    # Where the worst offenders are, so a failure is actionable rather than a
    # bare number.
    worst: Dict[str, Any] = {}

    def note(kind: str, value: float, fc, own: int, nei: int) -> None:
        worst[kind] = {
            "value": value,
            "face_centre": [round(v, 9) for v in fc],
            "owner_volume": volumes[own],
            "neighbour_volume": volumes[nei],
            "owner_is_hex": own < n_hexes,
            "neighbour_is_hex": nei < n_hexes,
            "at_bl_outer_interface": (own < n_hexes) != (nei < n_hexes),
        }
    for key, (own, nei) in internal.items():
        # The face is the shared node set; rebuild it from the owner.
        cell, local_faces = cells[own]
        fpts = None
        for local in local_faces:
            if tuple(sorted(cell[i] for i in local)) == key:
                fpts = [points[cell[i]] for i in local]
                break
        if fpts is None:  # pragma: no cover - defensive
            continue
        fc, normal = _face_centre_normal(fpts)
        area = _mag(normal)
        if area <= 0.0:
            continue
        unit = tuple(n / area for n in normal)
        d = _sub(centres[nei], centres[own])
        dmag = _mag(d)
        if dmag <= 0.0:
            continue
        cosine = abs(_dot(unit, d) / dmag)
        angle = math.degrees(math.acos(min(1.0, cosine)))
        if angle > max_non_orth:
            max_non_orth = angle
            note("non_orthogonality", angle, fc, own, nei)
        # OpenFOAM skewness: distance from the face centre to where the
        # owner-neighbour line pierces the face plane, over |d|.
        denom = _dot(unit, d)
        if abs(denom) > 0.0:
            s = _dot(unit, _sub(fc, centres[own])) / denom
            pierce = tuple(centres[own][k] + s * d[k] for k in range(3))
            skew = _mag(_sub(fc, pierce)) / dmag
            if skew > max_skew:
                max_skew = skew
                note("skewness", skew, fc, own, nei)
        # OpenFOAM surfaceInterpolation::makeWeights:
        #   SfdOwn = |Sf . (Cf - Co)| , SfdNei = |Sf . (Cn - Cf)|
        #   w = SfdNei / (SfdOwn + SfdNei)
        # checkMesh reports min(w, 1-w). Using |Cf - Cn| / |d| instead can exceed
        # 1 when the face centre lies outside the owner-neighbour segment, which
        # produced a nonsensical negative minimum.
        sfd_own = abs(_dot(normal, _sub(fc, centres[own])))
        sfd_nei = abs(_dot(normal, _sub(centres[nei], fc)))
        if sfd_own + sfd_nei > 0.0:
            w = min(sfd_nei / (sfd_own + sfd_nei),
                    1.0 - sfd_nei / (sfd_own + sfd_nei))
            if w < min_weight:
                min_weight = w
                note("interpolation_weight", w, fc, own, nei)
        vo, vn = volumes[own], volumes[nei]
        if max(vo, vn) > 0.0:
            ratio = min(vo, vn) / max(vo, vn)
            if ratio < min_ratio:
                min_ratio = ratio
                note("face_volume_ratio", ratio, fc, own, nei)

    return {
        "min_volume": min(volumes) if volumes else 0.0,
        "min_area": min_area,
        "min_pyramid": min_pyr,
        "min_tet": min_tet,
        "pyramids_ok": min_pyr > 0.0,
        "tets_ok": min_tet > 0.0,
        "max_closure": max_closure,
        "min_flatness": min_flatness,
        "flatness_ok": max_closure <= 1e-9 and min_flatness > 0.5,
        "max_non_orthogonality": max_non_orth,
        "max_skewness": max_skew,
        "min_weight": min_weight,
        "min_volume_ratio": min_ratio,
        "worst_locations": worst,
        "metrics": {
            "worst_metric_locations": worst,
            "min_cell_volume": min(volumes) if volumes else 0.0,
            "max_cell_volume": max(volumes) if volumes else 0.0,
            "min_face_area": min_area,
            "max_non_orthogonality_deg": max_non_orth,
            "max_skewness": max_skew,
            "min_interpolation_weight": min_weight,
            "min_face_volume_ratio": min_ratio,
            "max_face_closure_error": max_closure,
            "min_face_flatness": min_flatness,
        },
    }


def _in_plane_checks(points, mesh, base) -> Dict[str, Any]:
    crossed = non_convex = bad_jac = invalid = 0
    unresolved: List[str] = []
    min_edge = math.inf
    max_stretch = 0.0

    for quad in [tuple(c[:4]) for c in mesh["hexes"]]:
        pts = [(points[i][0], points[i][1]) for i in quad]
        diag = quad_diagnostics(pts)
        if diag["area_sign"] == 0:
            invalid += 1
        if diag["crossed_edges"] is None or diag["strictly_convex"] is None \
                or diag["bilinear_jacobian_positive"] is None:
            unresolved.append("quad")
            continue
        crossed += int(bool(diag["crossed_edges"]))
        non_convex += int(not diag["strictly_convex"])
        bad_jac += int(not diag["bilinear_jacobian_positive"])
        edges = [math.dist(pts[i], pts[(i + 1) % 4]) for i in range(4)]
        min_edge = min(min_edge, min(edges))
        altitude = 2.0 * abs(diag["signed_area"]) / max(edges) if max(edges) else 0.0
        if altitude > 0.0:
            max_stretch = max(max_stretch, max(edges) / altitude)
        else:
            invalid += 1

    for tri in [tuple(c[:3]) for c in mesh["prisms"]]:
        pts = [(points[i][0], points[i][1]) for i in tri]
        area = 0.5 * abs(
            (pts[1][0] - pts[0][0]) * (pts[2][1] - pts[0][1])
            - (pts[2][0] - pts[0][0]) * (pts[1][1] - pts[0][1])
        )
        edges = [math.dist(pts[i], pts[(i + 1) % 3]) for i in range(3)]
        scale = max(max(edges), 1.0e-300) ** 2      # element-local, not domain
        if area <= SIGN_GUARD_RELATIVE * scale:
            invalid += 1
            continue
        min_edge = min(min_edge, min(edges))
        altitude = 2.0 * area / max(edges)
        max_stretch = max(max_stretch, max(edges) / altitude)

    return {
        "no_crossed": crossed == 0, "n_crossed": crossed,
        "all_valid": invalid == 0, "n_invalid": invalid,
        "quads_convex": non_convex == 0, "n_non_convex": non_convex,
        "jacobians_positive": bad_jac == 0, "n_bad_jacobian": bad_jac,
        "no_collapsed": min_edge > 0.0, "min_edge": min_edge,
        "max_stretching": max_stretch,
        "unresolved": len(unresolved),
        "metrics": {"min_in_plane_edge": min_edge,
                    "max_in_plane_stretching": max_stretch},
    }


def _concavity_scan(points, hexes, *, sample: Optional[int] = None) -> Dict[str, Any]:
    """Resolve concavity by sign on the hexes -- the prisms are simplices."""
    indices = range(len(hexes)) if sample is None else range(min(sample, len(hexes)))
    genuine = unresolved = 0
    worst: Optional[Dict[str, Any]] = None
    for i in indices:
        diag = diagnose_cell_concavity(points, hexes[i])
        if diag["classification"] == "GENUINELY_CONCAVE":
            genuine += 1
            if worst is None:
                worst = {"cell": i, **diag}
        elif diag["classification"] == "NUMERICALLY_UNRESOLVED":
            unresolved += 1
    return {
        "scanned": len(list(indices)),
        "total_hexes": len(hexes),
        "sampled": sample is not None,
        "genuine": genuine,
        "unresolved": unresolved,
        "first_genuine": worst,
        "note": ("prisms are simplices and cannot be concave, so only the "
                 "hexahedral wall layers are scanned"),
    }

# ----------------------------------------------------------------------
#: Verdict strings for the NASA Family II hierarchy. Deliberately the same
#: strings as the Gmsh path used, because the GATES are the same gates.
def _connected_regions(n_cells: int, internal) -> int:
    """Count connected cell regions across internal faces. Union-find."""
    parent = list(range(n_cells))

    def find(a: int) -> int:
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    for owner, neighbour in internal.values():
        ra, rb = find(owner), find(neighbour)
        if ra != rb:
            parent[ra] = rb
    return len({find(i) for i in range(n_cells)})


def qualify_family2(
    mesh: Dict[str, Any],
    *,
    level_name: str,
    geometry_check: Dict[str, Any],
    conversion_check: Dict[str, Any],
    span: float,
    raw_check_mesh: Optional[Dict[str, Any]] = None,
    concavity_sample: Optional[int] = None,
) -> Report:
    """Qualify one converted NASA Family II level.

    The FROZEN gates are applied by `apply_frozen_gates`, the same function the
    archived Gmsh path used, against the same module constants. On top of them sit
    the NASA-specific checks: the cell and patch counts NASA's dimensions imply,
    exact preservation of the in-plane grid, orientation, one connected fluid
    region, and agreement of NASA's surface with the frozen corrected TMR formula.

    NASA provenance is NOT a waiver. A failing gate fails here exactly as it would
    for any other mesh.
    """
    report = Report(level=level_name)
    report.raw_check_mesh = dict(raw_check_mesh or {})

    points = mesh["points"]
    cells: List[Tuple[Tuple[int, ...], Tuple[Tuple[int, ...], ...]]] = [
        (c, HEX_FACES) for c in mesh["hexes"]
    ]
    n_cells = len(cells)

    faces: Dict[Tuple[int, ...], List[int]] = {}
    for ci, (cell, local_faces) in enumerate(cells):
        for local in local_faces:
            faces.setdefault(tuple(sorted(cell[i] for i in local)), []).append(ci)
    internal = {k: v for k, v in faces.items() if len(v) == 2}
    boundary = {k: v for k, v in faces.items() if len(v) == 1}
    overfull = {k: v for k, v in faces.items() if len(v) > 2}

    report.add("no_non_manifold_connectivity", len(overfull) == 0,
               "no face may be shared by more than two cells", len(overfull))
    report.add("one_connected_fluid_region",
               _connected_regions(n_cells, internal) == 1,
               "the mesh must be a single connected fluid region",
               _connected_regions(n_cells, internal))

    # -- patches -------------------------------------------------------
    declared: Dict[Tuple[int, ...], str] = {}
    overlap = 0
    for name, patch_faces in mesh["patches"].items():
        for face in patch_faces:
            key = tuple(sorted(face))
            if key in declared:
                overlap += 1
            declared[key] = name
    missing = [k for k in boundary if k not in declared]
    extra = [k for k in declared if k not in boundary]
    report.add("correct_patch_membership",
               not missing and not extra and overlap == 0,
               "every boundary face belongs to exactly one declared patch",
               {"boundary_faces": len(boundary), "declared": len(declared),
                "undeclared_boundary_faces": len(missing),
                "declared_but_internal": len(extra), "overlapping": overlap})
    report.add("wake_is_internal_connectivity",
               bool(conversion_check.get("wake_internal")),
               "the joined C-grid wake must be interior faces, never a boundary",
               conversion_check.get("unclassified_boundary_faces"))

    # -- exactly one spanwise cell at OUR span --------------------------
    zs = sorted({p[2] for p in points})
    report.add("exactly_one_spanwise_layer",
               len(zs) == 2 and abs((zs[1] - zs[0]) - span) <= 1e-15,
               f"two spanwise point planes, exactly {span} apart",
               {"z_planes": zs,
                "span": (zs[1] - zs[0]) if len(zs) == 2 else None})

    # -- every frozen gate, shared with the archived Gmsh path ----------
    apply_frozen_gates(report, points, cells, mesh, internal,
                       concavity_sample=concavity_sample)

    # -- NASA source preservation --------------------------------------
    for name, key, detail in (
        ("nasa_cell_count", "cells_match",
         f"cells must equal {conversion_check.get('cells_identity')}"),
        ("nasa_point_count_preserved", "point_count_preserved",
         "the conversion may not add or drop a node"),
        ("nasa_in_plane_coordinates_preserved_exactly",
         "in_plane_preserved_exactly",
         "in-plane x and y must be bit-identical to NASA's"),
        ("nasa_connectivity_identical", "connectivity_identical",
         "hex connectivity must be NASA's, in NASA's order"),
        ("no_duplicate_or_merged_points", "no_duplicate_or_merged_points",
         "no node may be duplicated or merged by the conversion"),
        ("positive_cell_orientation", "orientation_positive",
         "every hex must have positive signed volume"),
        ("frontandback_faces_equal_two_per_cell",
         "frontandback_equals_two_cells",
         "one spanwise cell gives exactly two frontAndBack faces per cell"),
    ):
        report.add(name, bool(conversion_check.get(key)), detail,
                   {"flag": conversion_check.get(key),
                    "measured": conversion_check.get(
                        {"cells_match": "cells",
                         "point_count_preserved": "points",
                         "in_plane_preserved_exactly": "in_plane_coordinate_error",
                         "connectivity_identical": "connectivity_identical",
                         "no_duplicate_or_merged_points": "duplicate_points",
                         "orientation_positive": "cells_with_non_positive_volume",
                         "frontandback_equals_two_cells": "patch_faces",
                         }[key])})
    report.add("airfoil_patch_face_count_matches_nasa_surface",
               conversion_check.get("airfoil_faces")
               == conversion_check.get("airfoil_faces_expected"),
               "airfoil faces must equal NASA's surface point count minus one",
               {"realized": conversion_check.get("airfoil_faces"),
                "expected": conversion_check.get("airfoil_faces_expected")})

    # -- NASA geometry against the frozen TMR formula -------------------
    if not geometry_check.get("resolved"):
        for name in ("nasa_chord_is_unit", "nasa_trailing_edge_is_sharp",
                     "nasa_surface_matches_tmr_formula",
                     "nasa_surface_is_reflected", "nasa_farfield_extent"):
            report.add(name, None, geometry_check.get("reason", "not measurable"))
    else:
        report.add("nasa_chord_is_unit", bool(geometry_check["chord_ok"]),
                   "chord must be 1 c", geometry_check["chord"])
        report.add("nasa_trailing_edge_is_sharp",
                   bool(geometry_check["trailing_edge_sharp"]),
                   "the trailing edge must close at y = 0",
                   geometry_check["trailing_edge_closure"])
        report.add("nasa_surface_matches_tmr_formula",
                   bool(geometry_check["ordinate_within_budget"]),
                   "surface ordinates must agree with the frozen corrected TMR "
                   f"formula within {geometry_check['ordinate_budget']:.0e} c",
                   {"max_discrepancy": geometry_check["max_ordinate_discrepancy"],
                    "at": geometry_check["max_ordinate_discrepancy_at"]})
        report.add("nasa_surface_is_reflected",
                   bool(geometry_check["reflection_ok"]),
                   "upper and lower surfaces must be reflections",
                   geometry_check["reflection_max_error"])
        report.add("nasa_farfield_extent", bool(geometry_check["farfield_ok"]),
                   "farfield must extend at least 100 c",
                   geometry_check["farfield_max_radius_chords"])

    report.metrics["nasa_geometry_cross_check"] = dict(geometry_check)
    report.metrics["nasa_conversion_cross_check"] = dict(conversion_check)
    report.provenance = {
        "checker_version": CHECKER_VERSION,
        "level": level_name,
        "authority": "NASA TMR NACA0012 Numerical Analysis Family II (CGNS hex)",
        "cells": n_cells,
        "points": len(points),
        "internal_faces": len(internal),
        "boundary_faces": len(boundary),
        "span": span,
        "thresholds_source": "module constants; NASA provenance does not relax them",
        "raw_check_mesh_preserved": True,
        "cfd_launched": False,
    }
    return report
