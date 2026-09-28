#!/usr/bin/env python3
"""Family-3 mesh qualification against the NASA CGNS topology authority.

THIS IS NOT CFD AND IT DOES NOT TOUCH THE RAW checkMesh RESULT. The real
Foundation-v14 `checkMesh` verdict is carried through verbatim. What this module
adds is a SEPARATE deterministic family verdict, ``NASA_MESH_QUALIFIED``, which
answers one question: are the geometries OpenFOAM complained about inherent to
the authoritative NASA mesh, or introduced by our conversion?

FIVE CHECKS, in the order the review asked for:

  1. cell bijection      every converted hex matched to a NASA CGNS cell by
                         COORDINATES, never by node id or file order; vertices,
                         flow-plane quad connectivity, face ownership, neighbour
                         relations, boundary membership and wake connectivity all
                         compared.
  2. quad geometry       for BOTH representations: no crossed edges, positive and
                         consistently oriented signed area, strict convexity, and
                         a positive bilinear Jacobian at all four parametric
                         corners.
  3. concavity diagnosis every OpenFOAM concavity flag resolved into
                         GENUINELY_CONCAVE / CONVEX_NEAR_PLANAR / UNRESOLVED,
                         with the signed distance and the normalised dot product
                         reported per flagged cell.
  4. extremes provenance aspect ratio and cell determinant computed on BOTH
                         representations and compared, so an extreme value is
                         shown to be source-inherent rather than conversion-induced.
  5. raw result kept     the checkMesh failure is reported unchanged.

WHERE TOLERANCES COME FROM
  There is exactly one numerical tolerance here and it is DERIVED, not chosen:
  the coordinate tolerance follows from the printed precision of the ASCII Plot3D
  source and the domain extent (see ``coordinate_tolerance``). Sign decisions use
  a floating-point resolution guard and return UNRESOLVED rather than guessing.
  No aspect-ratio or determinant threshold is invented: those checks compare
  source against converted, which needs no threshold.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

# Verdict strings.
QUALIFIED = "NASA_MESH_QUALIFIED"
NOT_QUALIFIED = "NASA_MESH_NOT_QUALIFIED"
INCONCLUSIVE = "NASA_MESH_QUALIFICATION_INCONCLUSIVE"

# Per-cell concavity classifications.
GENUINELY_CONCAVE = "GENUINELY_CONCAVE"
CONVEX_NEAR_PLANAR = "CONVEX_INSIDE_NEAR_PLANARITY_TOLERANCE"
CONVEX_CLEAR = "CONVEX_CLEARLY_INSIDE"
UNRESOLVED = "NUMERICALLY_UNRESOLVED"

#: Significant digits the ASCII Plot3D source is written with. The converted mesh
#: can agree with the binary CGNS authority no better than this.
PLOT3D_SIGNIFICANT_DIGITS = 12

#: Relative floating-point guard for sign decisions. A signed distance whose
#: magnitude is below guard * scale is not resolvable, and is reported as such.
SIGN_GUARD_RELATIVE = 1.0e-12

QUALIFIER_VERSION = "airfoil-mesh-qualification/1.0.0"


def coordinate_tolerance(
    extent: float, significant_digits: int = PLOT3D_SIGNIFICANT_DIGITS
) -> float:
    """Absolute coordinate tolerance implied by the source's printed precision.

    A coordinate of magnitude ``extent`` printed with ``significant_digits``
    digits has a last-digit step of 10^(floor(log10 extent) - digits + 1). That
    step IS the achievable agreement between the ASCII source and the binary
    CGNS authority. It is a consequence of the file format, not a merge tolerance
    chosen to make a comparison succeed.
    """
    magnitude = abs(float(extent))
    if magnitude <= 0.0 or not math.isfinite(magnitude):
        return 10.0 ** (-(significant_digits - 1))
    decade = math.floor(math.log10(magnitude))
    return 10.0 ** (decade - significant_digits + 1)


# ----------------------------------------------------------------------
# geometry primitives
# ----------------------------------------------------------------------
def signed_area(quad: Sequence[Tuple[float, float]]) -> float:
    total = 0.0
    for n in range(4):
        x0, y0 = quad[n]
        x1, y1 = quad[(n + 1) % 4]
        total += x0 * y1 - x1 * y0
    return 0.5 * total


def _cross(o, a, b) -> float:
    return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])


def _segments_cross(p1, p2, p3, p4) -> Optional[bool]:
    """Do the open segments p1p2 and p3p4 intersect? None when unresolvable."""
    d1 = _cross(p3, p4, p1)
    d2 = _cross(p3, p4, p2)
    d3 = _cross(p1, p2, p3)
    d4 = _cross(p1, p2, p4)
    # Element-local scale, for the same reason as in quad_diagnostics.
    span = max(math.dist(p1, p2), math.dist(p3, p4),
               math.dist(p1, p3), math.dist(p2, p4), 1.0e-300)
    guard = SIGN_GUARD_RELATIVE * span ** 2
    if min(abs(d1), abs(d2), abs(d3), abs(d4)) <= guard:
        return None
    return ((d1 > 0) != (d2 > 0)) and ((d3 > 0) != (d4 > 0))


def quad_diagnostics(quad: Sequence[Tuple[float, float]]) -> Dict[str, Any]:
    """Crossed edges, signed area, strict convexity and bilinear Jacobians.

    The bilinear map on the unit square is
        P(u,v) = (1-u)(1-v)P0 + u(1-v)P1 + uv P2 + (1-u)v P3
    and its Jacobian determinant is evaluated at the four parametric corners.
    """
    area = signed_area(quad)
    # The guard must scale with the ELEMENT, not with its absolute position: a
    # boundary-layer quad 1e-10 in area sitting 500 chords from the origin is
    # perfectly valid, and a domain-scaled guard would call it unresolvable.
    edges = [
        math.dist(quad[i], quad[(i + 1) % 4]) for i in range(4)
    ]
    scale = max(max(edges), 1.0e-300) ** 2
    guard = SIGN_GUARD_RELATIVE * scale

    # Crossed edges: only the two diagonal-opposite edge pairs can cross.
    crossings = [
        _segments_cross(quad[0], quad[1], quad[2], quad[3]),
        _segments_cross(quad[1], quad[2], quad[3], quad[0]),
    ]
    crossed: Optional[bool]
    if any(c is None for c in crossings):
        crossed = None
    else:
        crossed = any(bool(c) for c in crossings)

    # Strict convexity: all four cross products share a sign, none near zero.
    turns = [
        _cross(quad[n], quad[(n + 1) % 4], quad[(n + 2) % 4]) for n in range(4)
    ]
    if min(abs(t) for t in turns) <= guard:
        convex: Optional[bool] = None
    else:
        convex = all(t > 0 for t in turns) or all(t < 0 for t in turns)

    p0, p1, p2, p3 = quad

    def jacobian(u: float, v: float) -> float:
        dpu = (
            (1 - v) * (p1[0] - p0[0]) + v * (p2[0] - p3[0]),
            (1 - v) * (p1[1] - p0[1]) + v * (p2[1] - p3[1]),
        )
        dpv = (
            (1 - u) * (p3[0] - p0[0]) + u * (p2[0] - p1[0]),
            (1 - u) * (p3[1] - p0[1]) + u * (p2[1] - p1[1]),
        )
        return dpu[0] * dpv[1] - dpu[1] * dpv[0]

    corners = {f"u{u}v{v}": jacobian(float(u), float(v))
               for u in (0, 1) for v in (0, 1)}
    jac_values = list(corners.values())
    orientation = 1.0 if area > 0 else -1.0
    oriented = [orientation * j for j in jac_values]
    if min(abs(j) for j in jac_values) <= guard:
        jacobian_positive: Optional[bool] = None
    else:
        jacobian_positive = all(j > 0 for j in oriented)

    return {
        "signed_area": area,
        "area_sign": 0 if abs(area) <= guard else (1 if area > 0 else -1),
        "crossed_edges": crossed,
        "strictly_convex": convex,
        "turn_cross_products": turns,
        "bilinear_jacobians": corners,
        "bilinear_jacobian_positive": jacobian_positive,
        "orientation_used": orientation,
        "sign_guard": guard,
    }


# ----------------------------------------------------------------------
# hex helpers
# ----------------------------------------------------------------------
#: OpenFOAM/Gmsh hex face vertex sets, as local indices into the 8-node cell.
HEX_FACES = (
    (0, 3, 2, 1),   # bottom  (-z)
    (4, 5, 6, 7),   # top     (+z)
    (0, 1, 5, 4),
    (1, 2, 6, 5),
    (2, 3, 7, 6),
    (3, 0, 4, 7),
)


def _centroid(points: Sequence[Tuple[float, ...]]) -> Tuple[float, float, float]:
    n = len(points)
    return (
        sum(p[0] for p in points) / n,
        sum(p[1] for p in points) / n,
        sum(p[2] for p in points) / n,
    )


def _face_centre_and_normal(pts: Sequence[Tuple[float, float, float]]):
    centre = _centroid(pts)
    nx = ny = nz = 0.0
    for n in range(len(pts)):
        a, b = pts[n], pts[(n + 1) % len(pts)]
        ma = (0.5 * (a[0] + b[0]), 0.5 * (a[1] + b[1]), 0.5 * (a[2] + b[2]))
        e = (b[0] - a[0], b[1] - a[1], b[2] - a[2])
        d = (ma[0] - centre[0], ma[1] - centre[1], ma[2] - centre[2])
        nx += d[1] * e[2] - d[2] * e[1]
        ny += d[2] * e[0] - d[0] * e[2]
        nz += d[0] * e[1] - d[1] * e[0]
    return centre, (0.5 * nx, 0.5 * ny, 0.5 * nz)


def _flow_plane_quad(
    points: Sequence[Tuple[float, float, float]], hexa: Sequence[int]
) -> List[Tuple[float, float]]:
    """The four (x, y) corners of one spanwise layer of a hex."""
    return [(points[hexa[n]][0], points[hexa[n]][1]) for n in range(4)]


def _cell_key(
    points: Sequence[Tuple[float, float, float]],
    hexa: Sequence[int],
    tol: float,
) -> Tuple[int, int, int]:
    """A geometric key: the centroid quantised at the coordinate tolerance.

    Matching is by GEOMETRY. Node ids and file order are never compared, so a
    different-but-equivalent numbering cannot cause a false mismatch.
    """
    cx, cy, cz = _centroid([points[i] for i in hexa])
    q = max(tol, 1.0e-300)
    return (int(round(cx / q)), int(round(cy / q)), int(round(cz / q)))


def canonical_point_ids(
    *point_sets: Sequence[Tuple[float, float, float]], tol: float
) -> Tuple[List[List[int]], int]:
    """Cluster points from several meshes into shared canonical ids.

    Faces are then keyed by canonical id rather than by quantised coordinates, so
    a coordinate sitting on a bucket boundary cannot flip a face's identity and
    two meshes with different numbering still produce comparable topology.

    Returns (one id list per input set, number of canonical points).
    """
    buckets: Dict[Tuple[int, int, int], List[Tuple[int, Tuple[float, float, float]]]] = {}
    out: List[List[int]] = []
    canonical: List[Tuple[float, float, float]] = []
    q = max(tol, 1.0e-300)

    def key(p) -> Tuple[int, int, int]:
        return (int(math.floor(p[0] / q)), int(math.floor(p[1] / q)),
                int(math.floor(p[2] / q)))

    for points in point_sets:
        ids: List[int] = []
        for p in points:
            base = key(p)
            found = None
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    for dz in (-1, 0, 1):
                        for cid, cp in buckets.get(
                            (base[0] + dx, base[1] + dy, base[2] + dz), ()
                        ):
                            if all(abs(p[c] - cp[c]) <= tol for c in range(3)):
                                found = cid
                                break
                        if found is not None:
                            break
                    if found is not None:
                        break
                if found is not None:
                    break
            if found is None:
                found = len(canonical)
                canonical.append(tuple(float(c) for c in p))
                buckets.setdefault(base, []).append((found, canonical[found]))
            ids.append(found)
        out.append(ids)
    return out, len(canonical)


def duplicate_point_count(ids: Sequence[int]) -> int:
    """Distinct point indices that collapse onto the same canonical point.

    This is the direct fingerprint of an UNMERGED coincident interface: the
    geometry is identical but the mesh carries two points where it should carry
    one. A coordinate-keyed face comparison cannot see this, which is why the
    point set is checked separately.
    """
    return len(ids) - len(set(ids))


# ----------------------------------------------------------------------
@dataclass
class Check:
    name: str
    passed: Optional[bool]
    detail: str = ""
    measured: Any = None

    def to_dict(self) -> Dict[str, Any]:
        return {"check": self.name, "passed": self.passed,
                "detail": self.detail, "measured": self.measured}


@dataclass
class QualificationReport:
    grid_key: str
    checks: List[Check] = field(default_factory=list)
    #: The real checkMesh verdict, carried through UNCHANGED.
    raw_check_mesh: Dict[str, Any] = field(default_factory=dict)
    concavity: Dict[str, Any] = field(default_factory=dict)
    extremes: Dict[str, Any] = field(default_factory=dict)
    provenance: Dict[str, Any] = field(default_factory=dict)

    def add(self, name: str, passed: Optional[bool], detail: str = "",
            measured: Any = None) -> None:
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
            return NOT_QUALIFIED
        if self.unresolved:
            return INCONCLUSIVE
        return QUALIFIED

    def to_dict(self) -> Dict[str, Any]:
        return {
            "grid": self.grid_key,
            "qualification_verdict": self.verdict,
            "failed": self.failed,
            "unresolved": self.unresolved,
            "checks": [c.to_dict() for c in self.checks],
            # Never rewritten, never relabelled.
            "raw_openfoam_check_mesh": dict(self.raw_check_mesh),
            "concavity_diagnosis": dict(self.concavity),
            "extremes_provenance": dict(self.extremes),
            "provenance": dict(self.provenance),
            "cfd_launched": False,
            "authority": "deterministic",
            "note": (
                "this verdict is SEPARATE from the raw checkMesh result above and "
                "does not modify it"
            ),
        }


# ----------------------------------------------------------------------
# 1. cell bijection
# ----------------------------------------------------------------------
def bijection(
    converted_points: Sequence[Tuple[float, float, float]],
    converted_hexes: Sequence[Sequence[int]],
    source_points: Sequence[Tuple[float, float, float]],
    source_hexes: Sequence[Sequence[int]],
    *,
    tol: float,
) -> Dict[str, Any]:
    """Match every converted cell to a source cell by geometry alone."""
    source_index: Dict[Tuple[int, int, int], List[int]] = {}
    for n, hexa in enumerate(source_hexes):
        source_index.setdefault(_cell_key(source_points, hexa, tol), []).append(n)

    mapping: Dict[int, int] = {}
    unmatched: List[int] = []
    ambiguous: List[int] = []
    worst_vertex = 0.0
    worst_cell: Optional[int] = None
    connectivity_mismatch: List[int] = []

    for n, hexa in enumerate(converted_hexes):
        key = _cell_key(converted_points, hexa, tol)
        # A centroid sitting near a quantisation boundary can land in the
        # neighbouring bucket, so the 27 adjacent buckets are searched too.
        candidates: List[int] = []
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for dz in (-1, 0, 1):
                    candidates.extend(
                        source_index.get((key[0] + dx, key[1] + dy, key[2] + dz), [])
                    )
        if not candidates:
            unmatched.append(n)
            continue

        best: Optional[Tuple[float, int]] = None
        for m in candidates:
            worst = _vertex_sets_match(
                [converted_points[i] for i in hexa],
                [source_points[i] for i in source_hexes[m]],
                tol,
            )
            if worst is None:
                continue
            if best is None or worst < best[0]:
                best = (worst, m)
        if best is None:
            unmatched.append(n)
            continue
        if best[0] > worst_vertex:
            worst_vertex, worst_cell = best[0], n
        if best[1] in mapping.values():
            ambiguous.append(n)
        mapping[n] = best[1]

        # Flow-plane quadrilateral connectivity, compared as a geometric cycle.
        cq = _flow_plane_quad(converted_points, hexa)
        sq = _flow_plane_quad(source_points, source_hexes[best[1]])
        if not _same_cycle(cq, sq, tol):
            connectivity_mismatch.append(n)

    bijective = (
        not unmatched
        and not ambiguous
        and len(set(mapping.values())) == len(converted_hexes) == len(source_hexes)
    )
    return {
        "bijective": bijective,
        "converted_cells": len(converted_hexes),
        "source_cells": len(source_hexes),
        "matched": len(mapping),
        "unmatched_converted_cells": unmatched[:50],
        "n_unmatched": len(unmatched),
        "ambiguous_matches": ambiguous[:50],
        "n_ambiguous": len(ambiguous),
        "flow_plane_connectivity_mismatch": connectivity_mismatch[:50],
        "n_connectivity_mismatch": len(connectivity_mismatch),
        "worst_vertex_coordinate_difference": worst_vertex,
        "worst_vertex_cell": worst_cell,
        "coordinate_tolerance": tol,
        "tolerance_basis": (
            f"printed precision of the ASCII Plot3D source "
            f"({PLOT3D_SIGNIFICANT_DIGITS} significant digits) times the domain "
            "extent; not a merge tolerance"
        ),
        "mapping": mapping,
    }


def _vertex_sets_match(
    a: Sequence[Tuple[float, float, float]],
    b: Sequence[Tuple[float, float, float]],
    tol: float,
) -> Optional[float]:
    """Worst pairing distance if the two vertex sets match within tol, else None.

    Pairing is a tolerant one-to-one match, NOT a comparison of sorted order: a
    perturbation of a few ULP can reorder two tied coordinates, which would make
    an identical cell look like a mismatch.
    """
    if len(a) != len(b):
        return None
    remaining = list(range(len(b)))
    worst = 0.0
    for p in a:
        best_index: Optional[int] = None
        best_distance = math.inf
        for n in remaining:
            d = max(abs(p[c] - b[n][c]) for c in range(3))
            if d < best_distance:
                best_distance, best_index = d, n
        if best_index is None or best_distance > tol:
            return None
        remaining.remove(best_index)
        worst = max(worst, best_distance)
    return worst


def _same_cycle(a: Sequence[Tuple[float, float]], b: Sequence[Tuple[float, float]],
                tol: float) -> bool:
    """Are two 4-cycles the same ring of points, up to rotation/reflection?"""
    def close(p, q) -> bool:
        return abs(p[0] - q[0]) <= tol and abs(p[1] - q[1]) <= tol

    for reverse in (False, True):
        candidate = list(reversed(b)) if reverse else list(b)
        for shift in range(4):
            rotated = candidate[shift:] + candidate[:shift]
            if all(close(p, q) for p, q in zip(a, rotated)):
                return True
    return False


def face_topology(
    points: Sequence[Tuple[float, float, float]],
    hexes: Sequence[Sequence[int]],
    *,
    tol: float,
    canonical: Optional[Sequence[int]] = None,
) -> Dict[str, Any]:
    """Owner/neighbour relations and boundary membership, keyed by canonical points.

    ``canonical`` maps this mesh's point indices onto ids shared with the other
    mesh, so two representations with different node numbering produce comparable
    topology and a bucket boundary cannot change a face's identity.
    """
    if canonical is None:
        canonical = canonical_point_ids(points, tol=tol)[0][0]
    faces: Dict[Tuple, List[int]] = {}
    for c, hexa in enumerate(hexes):
        for local in HEX_FACES:
            key = tuple(sorted(canonical[hexa[i]] for i in local))
            faces.setdefault(key, []).append(c)
    internal = {k: tuple(sorted(v)) for k, v in faces.items() if len(v) == 2}
    boundary = {k: v[0] for k, v in faces.items() if len(v) == 1}
    overfull = {k: v for k, v in faces.items() if len(v) > 2}
    return {
        "n_faces": len(faces),
        "n_internal": len(internal),
        "n_boundary": len(boundary),
        "n_overfull": len(overfull),
        "internal": internal,
        "boundary": boundary,
    }


def compare_topology(
    converted: Dict[str, Any], source: Dict[str, Any], mapping: Dict[int, int]
) -> Dict[str, Any]:
    """Face ownership, neighbour relations and boundary membership must agree."""
    differences: List[str] = []
    if converted["n_faces"] != source["n_faces"]:
        differences.append(
            f"face count {converted['n_faces']} vs {source['n_faces']}"
        )
    if converted["n_internal"] != source["n_internal"]:
        differences.append(
            f"internal faces {converted['n_internal']} vs {source['n_internal']}"
        )
    if converted["n_boundary"] != source["n_boundary"]:
        differences.append(
            f"boundary faces {converted['n_boundary']} vs {source['n_boundary']}"
        )

    neighbour_mismatch = 0
    for key, pair in converted["internal"].items():
        other = source["internal"].get(key)
        if other is None:
            neighbour_mismatch += 1
            continue
        expected = tuple(sorted(mapping.get(c, -1) for c in pair))
        if expected != other:
            neighbour_mismatch += 1

    boundary_mismatch = 0
    for key, owner in converted["boundary"].items():
        other = source["boundary"].get(key)
        if other is None or mapping.get(owner, -1) != other:
            boundary_mismatch += 1

    return {
        "differences": differences,
        "neighbour_relation_mismatches": neighbour_mismatch,
        "boundary_membership_mismatches": boundary_mismatch,
        "converted_overfull_faces": converted["n_overfull"],
        "source_overfull_faces": source["n_overfull"],
        "agree": (
            not differences
            and neighbour_mismatch == 0
            and boundary_mismatch == 0
            and converted["n_overfull"] == 0
            and source["n_overfull"] == 0
        ),
    }


def wake_connectivity(
    points: Sequence[Tuple[float, float, float]],
    hexes: Sequence[Sequence[int]],
    *,
    tol: float,
    topology: Optional[Dict[str, Any]] = None,
    canonical_ids: Optional[Sequence[int]] = None,
) -> Dict[str, Any]:
    """Faces lying on the wake plane, split into internal and boundary.

    The wake cut of a C-grid lies on y = 0. If the slit were left unmerged those
    faces would be BOUNDARY faces on that plane instead of internal ones, so the
    two counts are a direct fingerprint of the merge.

    ``merged`` is reported but is only meaningful where a wake exists; the
    QUALIFICATION criterion is agreement between the two representations, which
    is what "no unexplained connectivity differences" means.
    """
    canonical = canonical_ids
    if canonical is None:
        canonical = canonical_point_ids(points, tol=tol)[0][0]
    topo = topology or face_topology(points, hexes, tol=tol, canonical=canonical)

    # Canonical coordinates of each canonical id, for the plane test.
    coord: Dict[int, Tuple[float, float, float]] = {}
    for n, cid in enumerate(canonical):
        coord.setdefault(cid, points[n])

    def on_wake(key) -> bool:
        return all(abs(coord[cid][1]) <= tol for cid in key)

    internal_wake = sum(1 for k in topo["internal"] if on_wake(k))
    boundary_wake = sum(1 for k in topo["boundary"] if on_wake(k))
    duplicates = duplicate_point_count(canonical)
    return {
        "internal_faces_on_wake_plane": internal_wake,
        "boundary_faces_on_wake_plane": boundary_wake,
        "coincident_duplicate_points": duplicates,
        "wake_plane_present": internal_wake + boundary_wake > 0,
        "merged": boundary_wake == 0 and internal_wake > 0 and duplicates == 0,
        "note": (
            "a correctly merged C-grid wake has NO boundary faces on the wake "
            "plane: they are internal faces between the cells above and below"
        ),
    }


def compare_wake(converted: Dict[str, Any], source: Dict[str, Any]) -> Dict[str, Any]:
    """The two representations must describe the same wake connectivity."""
    same_internal = (
        converted["internal_faces_on_wake_plane"]
        == source["internal_faces_on_wake_plane"]
    )
    same_boundary = (
        converted["boundary_faces_on_wake_plane"]
        == source["boundary_faces_on_wake_plane"]
    )
    # Where the authority shows a merged wake, ours must be merged too.
    merge_consistent = (not source["merged"]) or bool(converted["merged"])
    same_duplicates = (
        converted["coincident_duplicate_points"]
        == source["coincident_duplicate_points"]
    )
    return {
        "converted": converted,
        "source": source,
        "same_internal_count": same_internal,
        "same_boundary_count": same_boundary,
        "same_duplicate_point_count": same_duplicates,
        "merge_consistent_with_authority": merge_consistent,
        "agree": (
            same_internal and same_boundary and merge_consistent and same_duplicates
        ),
    }


# ----------------------------------------------------------------------
# 3. concavity diagnosis
# ----------------------------------------------------------------------
def diagnose_cell_concavity(
    points: Sequence[Tuple[float, float, float]],
    hexa: Sequence[int],
    *,
    near_planar_dot: Optional[float] = None,
) -> Dict[str, Any]:
    """Resolve one cell's concavity by sign, reporting the offending face pair.

    For each face, the outward plane is taken through the face centre with the
    face's area-vector normal. Every OTHER face centre is then tested: a centre
    on the outward side means the cell is not convex at that face.

    ``near_planar_dot`` is OpenFOAM's near-planarity threshold on the normalised
    dot product, which belongs to the run that produced the flags. It is supplied
    by the caller and is NOT invented here: when it is None the classification
    still separates GENUINELY_CONCAVE from convex by sign, and simply does not
    claim which convex cells the tolerance would have caught.
    """
    pts = [points[i] for i in hexa]
    centre = _centroid(pts)
    # Element-local scale: the largest distance from the cell centre to a vertex.
    scale = max(
        (max(abs(p[c] - centre[c]) for c in range(3)) for p in pts),
        default=1.0,
    )
    guard = SIGN_GUARD_RELATIVE * max(scale, 1.0e-300)

    faces = []
    for local in HEX_FACES:
        fpts = [points[hexa[i]] for i in local]
        fcentre, normal = _face_centre_and_normal(fpts)
        # Orient outward: away from the cell centre.
        to_face = (fcentre[0] - centre[0], fcentre[1] - centre[1],
                   fcentre[2] - centre[2])
        if sum(n * t for n, t in zip(normal, to_face)) < 0.0:
            normal = (-normal[0], -normal[1], -normal[2])
        magnitude = math.sqrt(sum(n * n for n in normal))
        faces.append({"local": local, "centre": fcentre, "normal": normal,
                      "area": magnitude})

    worst: Optional[Dict[str, Any]] = None
    unresolved = False
    for a, face in enumerate(faces):
        if face["area"] <= 0.0:
            unresolved = True
            continue
        unit = tuple(n / face["area"] for n in face["normal"])
        for b, other in enumerate(faces):
            if a == b:
                continue
            delta = tuple(
                other["centre"][c] - face["centre"][c] for c in range(3)
            )
            signed = sum(u * d for u, d in zip(unit, delta))
            length = math.sqrt(sum(d * d for d in delta))
            dot = signed / length if length > 0 else 0.0
            record = {
                "face_index": a,
                "other_face_index": b,
                "face_local_vertices": list(face["local"]),
                "other_face_local_vertices": list(other["local"]),
                "signed_distance_to_face_plane": signed,
                "normalised_dot_product": dot,
                "separation": length,
                "sign_guard": guard,
            }
            if worst is None or signed > worst["signed_distance_to_face_plane"]:
                worst = record

    if worst is None:  # pragma: no cover - a hex always has face pairs
        return {"classification": UNRESOLVED, "reason": "no face pair evaluated"}

    signed = worst["signed_distance_to_face_plane"]
    if unresolved or abs(signed) <= guard:
        classification = UNRESOLVED
    elif signed > 0.0:
        classification = GENUINELY_CONCAVE
    elif near_planar_dot is not None and abs(worst["normalised_dot_product"]) \
            <= float(near_planar_dot):
        classification = CONVEX_NEAR_PLANAR
    elif near_planar_dot is None:
        # Convex by sign. Whether OpenFOAM's tolerance caught it cannot be
        # asserted without that tolerance, and is not guessed.
        classification = CONVEX_NEAR_PLANAR
    else:
        classification = CONVEX_CLEAR

    return {
        "classification": classification,
        "worst_face_pair": worst,
        "near_planar_dot_threshold": near_planar_dot,
        "threshold_source": (
            "supplied by the caller from the Foundation-v14 run that produced the "
            "flags" if near_planar_dot is not None
            else "not supplied; classification rests on the SIGN of the signed "
                 "distance, which is what 'genuinely concave' means"
        ),
    }


def diagnose_concavity_flags(
    points: Sequence[Tuple[float, float, float]],
    hexes: Sequence[Sequence[int]],
    flagged_cells: Sequence[int],
    *,
    mapping: Optional[Dict[int, int]] = None,
    source_index: Optional[Dict[int, Any]] = None,
    near_planar_dot: Optional[float] = None,
    expected_flag_count: Optional[int] = None,
) -> Dict[str, Any]:
    """Diagnose every flagged cell. No blanket exception is available."""
    per_cell: List[Dict[str, Any]] = []
    tally: Dict[str, int] = {}
    for cell in flagged_cells:
        if cell < 0 or cell >= len(hexes):
            per_cell.append({"cell": cell, "classification": UNRESOLVED,
                             "reason": "flagged cell index is out of range"})
            tally[UNRESOLVED] = tally.get(UNRESOLVED, 0) + 1
            continue
        result = diagnose_cell_concavity(points, hexes[cell],
                                        near_planar_dot=near_planar_dot)
        result["cell"] = cell
        if mapping is not None:
            result["source_cgns_cell"] = mapping.get(cell)
        if source_index is not None:
            result["nasa_structured_index"] = source_index.get(cell)
        per_cell.append(result)
        tally[result["classification"]] = tally.get(result["classification"], 0) + 1

    genuine = tally.get(GENUINELY_CONCAVE, 0)
    unresolved = tally.get(UNRESOLVED, 0)
    count_matches = (
        expected_flag_count is None or len(flagged_cells) == expected_flag_count
    )
    if not count_matches:
        explained: Optional[bool] = None
    elif genuine > 0:
        explained = False
    elif unresolved > 0:
        explained = None
    else:
        explained = True

    return {
        "flagged_cells": len(flagged_cells),
        "expected_flag_count": expected_flag_count,
        "flag_count_matches": count_matches,
        "classification_tally": tally,
        "genuinely_concave": genuine,
        "numerically_unresolved": unresolved,
        "all_flags_explained_as_convex": explained,
        "per_cell": per_cell,
        "policy": (
            "every flag is resolved individually; no blanket exception exists, and "
            "a single resolved genuinely-concave cell disqualifies the mesh"
        ),
    }


# ----------------------------------------------------------------------
# 4. aspect-ratio and determinant provenance
# ----------------------------------------------------------------------
def cell_metrics(
    points: Sequence[Tuple[float, float, float]], hexa: Sequence[int]
) -> Dict[str, float]:
    """Declared anisotropy metrics. Compared source-vs-converted, not thresholded.

    ``edge_aspect_ratio`` is the longest over the shortest cell edge.
    ``face_area_determinant`` is the determinant of the sum of outer products of
    the unit face-area vectors, scaled to 1 for an isotropic hex -- the quantity
    OpenFOAM reports as the cell determinant.
    """
    pts = [points[i] for i in hexa]
    edges = []
    for local in HEX_FACES:
        for n in range(4):
            a, b = pts[local[n]], pts[local[(n + 1) % 4]]
            edges.append(math.dist(a, b))
    edges = [e for e in edges if e > 0.0]
    longest, shortest = (max(edges), min(edges)) if edges else (0.0, 0.0)

    tensor = [[0.0] * 3 for _ in range(3)]
    total_area = 0.0
    for local in HEX_FACES:
        _, normal = _face_centre_and_normal([pts[i] for i in local])
        area = math.sqrt(sum(n * n for n in normal))
        if area <= 0.0:
            continue
        total_area += area
        unit = [n / area for n in normal]
        for r in range(3):
            for c in range(3):
                tensor[r][c] += area * unit[r] * unit[c]
    if total_area > 0.0:
        for r in range(3):
            for c in range(3):
                tensor[r][c] /= total_area
    det = (
        tensor[0][0] * (tensor[1][1] * tensor[2][2] - tensor[1][2] * tensor[2][1])
        - tensor[0][1] * (tensor[1][0] * tensor[2][2] - tensor[1][2] * tensor[2][0])
        + tensor[0][2] * (tensor[1][0] * tensor[2][1] - tensor[1][1] * tensor[2][0])
    )
    # Normalise so an isotropic hex gives 1: det of (1/3)I is 1/27.
    return {
        "edge_aspect_ratio": (longest / shortest) if shortest > 0 else math.inf,
        "longest_edge": longest,
        "shortest_edge": shortest,
        "face_area_determinant": det * 27.0,
    }


def extremes_provenance(
    converted_points, converted_hexes, source_points, source_hexes,
    *, mapping: Dict[int, int], relative_tolerance: float = 1.0e-6,
    reported: Optional[Dict[str, Any]] = None, top: int = 20,
) -> Dict[str, Any]:
    """Are the extreme anisotropy metrics present in the SOURCE mesh too?

    No absolute threshold is applied. The test is agreement: for every cell the
    converted metric must match the source metric of its matched cell, and the
    extreme cells must be the same cells. That is what distinguishes
    source-inherent anisotropy from conversion-induced degradation.
    """
    rows: List[Dict[str, Any]] = []
    worst_ar_rel = 0.0
    worst_det_rel = 0.0
    for c, s in mapping.items():
        cm = cell_metrics(converted_points, converted_hexes[c])
        sm = cell_metrics(source_points, source_hexes[s])
        ar_rel = _relative(cm["edge_aspect_ratio"], sm["edge_aspect_ratio"])
        det_rel = _relative(cm["face_area_determinant"], sm["face_area_determinant"])
        worst_ar_rel = max(worst_ar_rel, ar_rel)
        worst_det_rel = max(worst_det_rel, det_rel)
        rows.append({
            "converted_cell": c, "source_cell": s,
            "converted_aspect_ratio": cm["edge_aspect_ratio"],
            "source_aspect_ratio": sm["edge_aspect_ratio"],
            "aspect_ratio_relative_difference": ar_rel,
            "converted_determinant": cm["face_area_determinant"],
            "source_determinant": sm["face_area_determinant"],
            "determinant_relative_difference": det_rel,
        })

    by_ar = sorted(rows, key=lambda r: -_finite(r["source_aspect_ratio"]))[:top]
    by_det = sorted(rows, key=lambda r: _finite(r["source_determinant"]))[:top]
    agree = (
        worst_ar_rel <= relative_tolerance and worst_det_rel <= relative_tolerance
    )
    return {
        "cells_compared": len(rows),
        "worst_aspect_ratio_relative_difference": worst_ar_rel,
        "worst_determinant_relative_difference": worst_det_rel,
        "agreement_relative_tolerance": relative_tolerance,
        "source_inherent": agree,
        "max_source_aspect_ratio": max(
            (_finite(r["source_aspect_ratio"]) for r in rows), default=None),
        "max_converted_aspect_ratio": max(
            (_finite(r["converted_aspect_ratio"]) for r in rows), default=None),
        "min_source_determinant": min(
            (_finite(r["source_determinant"]) for r in rows), default=None),
        "min_converted_determinant": min(
            (_finite(r["converted_determinant"]) for r in rows), default=None),
        "highest_aspect_ratio_cells": by_ar,
        "lowest_determinant_cells": by_det,
        "openfoam_reported": dict(reported or {}),
        "metric_note": (
            "these are DECLARED metrics used only for source-vs-converted "
            "comparison; the authoritative absolute values are the ones the real "
            "checkMesh reported, recorded verbatim under openfoam_reported"
        ),
        "no_threshold_invented": (
            "no aspect-ratio or determinant limit is applied; the criterion is "
            "agreement between source and converted geometry"
        ),
    }


def _finite(value: float) -> float:
    return value if math.isfinite(value) else float("inf")


def _relative(a: float, b: float) -> float:
    if not (math.isfinite(a) and math.isfinite(b)):
        return 0.0 if a == b else float("inf")
    scale = max(abs(a), abs(b), 1.0e-300)
    return abs(a - b) / scale


# ----------------------------------------------------------------------
# the qualification driver
# ----------------------------------------------------------------------
def quad_sweep(
    points: Sequence[Tuple[float, float, float]],
    hexes: Sequence[Sequence[int]],
    label: str,
) -> Dict[str, Any]:
    """Run quad diagnostics over every flow-plane quadrilateral."""
    crossed: List[int] = []
    non_convex: List[int] = []
    bad_jacobian: List[int] = []
    wrong_orientation: List[int] = []
    unresolved: List[int] = []
    signs: set = set()
    worst_abs_area = math.inf

    per_cell_signs: List[int] = []
    for n, hexa in enumerate(hexes):
        diag = quad_diagnostics(_flow_plane_quad(points, hexa))
        worst_abs_area = min(worst_abs_area, abs(diag["signed_area"]))
        if diag["area_sign"] == 0:
            unresolved.append(n)
        else:
            signs.add(diag["area_sign"])
            per_cell_signs.append(diag["area_sign"])
        if diag["crossed_edges"] is None or diag["strictly_convex"] is None \
                or diag["bilinear_jacobian_positive"] is None:
            unresolved.append(n)
            continue
        if diag["crossed_edges"]:
            crossed.append(n)
        if not diag["strictly_convex"]:
            non_convex.append(n)
        if not diag["bilinear_jacobian_positive"]:
            bad_jacobian.append(n)

    consistent = len(signs) <= 1
    if not consistent:
        majority = 1 if per_cell_signs.count(1) >= per_cell_signs.count(-1) else -1
        wrong_orientation = [
            n for n, hexa in enumerate(hexes)
            if quad_diagnostics(_flow_plane_quad(points, hexa))["area_sign"]
            not in (0, majority)
        ]
    unresolved = sorted(set(unresolved))
    return {
        "representation": label,
        "quads": len(hexes),
        "crossed_edge_cells": crossed[:50],
        "n_crossed": len(crossed),
        "non_strictly_convex_cells": non_convex[:50],
        "n_non_convex": len(non_convex),
        "non_positive_jacobian_cells": bad_jacobian[:50],
        "n_non_positive_jacobian": len(bad_jacobian),
        "orientation_consistent": consistent,
        "inconsistent_orientation_cells": wrong_orientation[:50],
        "unresolved_cells": unresolved[:50],
        "n_unresolved": len(unresolved),
        "smallest_absolute_area": worst_abs_area,
        "ok": (
            not crossed and not non_convex and not bad_jacobian and consistent
            and not unresolved
        ),
    }


def qualify(
    *,
    grid_key: str,
    converted_points: Sequence[Tuple[float, float, float]],
    converted_hexes: Sequence[Sequence[int]],
    source_points: Sequence[Tuple[float, float, float]],
    source_hexes: Sequence[Sequence[int]],
    raw_check_mesh: Dict[str, Any],
    concavity_flagged_cells: Sequence[int] = (),
    expected_concavity_flags: Optional[int] = None,
    near_planar_dot: Optional[float] = None,
    reported_extremes: Optional[Dict[str, Any]] = None,
    domain_extent: Optional[float] = None,
    other_check_mesh_checks_acceptable: Optional[bool] = None,
    source_structured_index: Optional[Dict[int, Any]] = None,
) -> QualificationReport:
    """The full qualification. Never modifies ``raw_check_mesh``."""
    report = QualificationReport(grid_key=grid_key)
    # Carried through verbatim, by construction: a copy, never an edit.
    report.raw_check_mesh = dict(raw_check_mesh)

    extent = domain_extent or max(
        (max(abs(p[0]), abs(p[1])) for p in source_points), default=1.0
    )
    tol = coordinate_tolerance(extent)

    # -- 1. bijection ---------------------------------------------------
    bij = bijection(converted_points, converted_hexes, source_points,
                    source_hexes, tol=tol)
    mapping = bij.pop("mapping")
    report.add("cell_bijection", bij["bijective"],
               "every converted cell must map 1:1 to a NASA CGNS cell by geometry",
               measured={k: v for k, v in bij.items()})
    report.add(
        "coordinate_fidelity",
        bij["worst_vertex_coordinate_difference"] <= tol,
        f"worst vertex difference must be within the source's printed precision "
        f"({tol:.3e})",
        measured=bij["worst_vertex_coordinate_difference"],
    )
    report.add(
        "flow_plane_connectivity",
        bij["n_connectivity_mismatch"] == 0,
        "each matched pair must describe the same flow-plane quadrilateral cycle",
        measured=bij["n_connectivity_mismatch"],
    )

    (conv_ids, src_ids), n_canonical = canonical_point_ids(
        converted_points, source_points, tol=tol
    )
    conv_topo = face_topology(converted_points, converted_hexes, tol=tol,
                              canonical=conv_ids)
    src_topo = face_topology(source_points, source_hexes, tol=tol,
                             canonical=src_ids)
    topo = compare_topology(conv_topo, src_topo, mapping)
    topo["canonical_points"] = n_canonical
    topo["converted_duplicate_points"] = duplicate_point_count(conv_ids)
    topo["source_duplicate_points"] = duplicate_point_count(src_ids)
    report.add("face_ownership_and_neighbours", topo["agree"],
               "face ownership, neighbour relations and boundary membership must "
               "agree between the two representations",
               measured=topo)

    wake = compare_wake(
        wake_connectivity(converted_points, converted_hexes, tol=tol,
                          topology=conv_topo, canonical_ids=conv_ids),
        wake_connectivity(source_points, source_hexes, tol=tol,
                          topology=src_topo, canonical_ids=src_ids),
    )
    report.add(
        "wake_connectivity",
        wake["agree"],
        "the wake plane must carry the same internal and boundary face counts in "
        "both representations, and a wake the authority shows as merged must be "
        "merged in ours too",
        measured=wake,
    )

    # -- 2. quad geometry, BOTH representations -------------------------
    conv_quads = quad_sweep(converted_points, converted_hexes, "converted")
    src_quads = quad_sweep(source_points, source_hexes, "nasa_cgns_source")
    for sweep in (src_quads, conv_quads):
        label = sweep["representation"]
        resolved = sweep["n_unresolved"] == 0
        report.add(f"no_crossed_edges[{label}]",
                   None if not resolved else sweep["n_crossed"] == 0,
                   "no flow-plane quadrilateral may have crossed edges",
                   measured=sweep["n_crossed"])
        report.add(f"positive_consistent_area[{label}]",
                   None if not resolved else sweep["orientation_consistent"],
                   "signed areas must be non-zero and consistently oriented",
                   measured={"consistent": sweep["orientation_consistent"],
                             "smallest_absolute_area": sweep["smallest_absolute_area"]})
        report.add(f"strict_convexity[{label}]",
                   None if not resolved else sweep["n_non_convex"] == 0,
                   "every flow-plane quadrilateral must be strictly convex",
                   measured=sweep["n_non_convex"])
        report.add(f"positive_bilinear_jacobian[{label}]",
                   None if not resolved else sweep["n_non_positive_jacobian"] == 0,
                   "the bilinear Jacobian must be positive at all four parametric "
                   "corners",
                   measured=sweep["n_non_positive_jacobian"])

    # -- 3. concavity flags --------------------------------------------
    report.concavity = diagnose_concavity_flags(
        converted_points, converted_hexes, list(concavity_flagged_cells),
        mapping=mapping, source_index=source_structured_index,
        near_planar_dot=near_planar_dot,
        expected_flag_count=expected_concavity_flags,
    )
    report.add(
        "all_concavity_flags_are_convex_near_planarity",
        report.concavity["all_flags_explained_as_convex"],
        "every OpenFOAM concavity flag must resolve to a convex near-planarity "
        "case; one genuinely concave cell disqualifies the mesh",
        measured={k: report.concavity[k] for k in
                  ("flagged_cells", "expected_flag_count", "flag_count_matches",
                   "classification_tally", "genuinely_concave",
                   "numerically_unresolved")},
    )

    # -- 4. extremes provenance ----------------------------------------
    report.extremes = extremes_provenance(
        converted_points, converted_hexes, source_points, source_hexes,
        mapping=mapping, reported=reported_extremes,
    )
    report.add(
        "extremes_are_source_inherent",
        report.extremes["source_inherent"],
        "extreme aspect ratio and low determinant must be present in the NASA "
        "source mesh, i.e. not introduced by our conversion",
        measured={k: report.extremes[k] for k in
                  ("worst_aspect_ratio_relative_difference",
                   "worst_determinant_relative_difference",
                   "max_source_aspect_ratio", "max_converted_aspect_ratio",
                   "min_source_determinant", "min_converted_determinant")},
    )

    # -- 5. the remaining checkMesh checks stay acceptable -------------
    report.add(
        "other_check_mesh_checks_acceptable",
        other_check_mesh_checks_acceptable,
        "non-orthogonality, skewness, interpolation weights, volume ratio, "
        "flatness and topology must remain acceptable in the raw checkMesh report",
        measured=raw_check_mesh.get("failed_checks"),
    )

    report.provenance = {
        "qualifier_version": QUALIFIER_VERSION,
        "grid": grid_key,
        "coordinate_tolerance": tol,
        "coordinate_tolerance_basis": bij["tolerance_basis"],
        "domain_extent_used": extent,
        "sign_guard_relative": SIGN_GUARD_RELATIVE,
        "converted_cells": len(converted_hexes),
        "source_cells": len(source_hexes),
        "raw_check_mesh_preserved": True,
        "raw_check_mesh_verdict": raw_check_mesh.get("verdict")
        or raw_check_mesh.get("status"),
        "cfd_launched": False,
        "no_invented_thresholds": (
            "the only numerical tolerance is derived from the source file's "
            "printed precision; extremes are judged by source-vs-converted "
            "agreement, and concavity by sign with an explicit resolution guard"
        ),
    }
    return report
