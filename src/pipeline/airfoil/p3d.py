#!/usr/bin/env python3
"""Registered NASA Plot3D grid ingestion and deterministic conversion.

WHAT THIS DOES
  Reads the registered NASA structured C-grid in formatted Plot3D (``.p3dfmt``,
  optionally gzipped), merges the coincident C-grid wake interface, and emits a
  Gmsh 2.2 ASCII mesh with named physical surfaces.

THE ACTUAL NASA LAYOUT
  These files are 3-D, single block, with the SPANWISE direction first:

      nbl = 1
      ni nj nk  =  2  897  257     (canonical)
      ni nj nk  =  2  449  129     (sensitivity)

  ni = 2 is the two spanwise planes. NASA describes them as two identical x-z
  planes separated by y = 1, which is exactly one spanwise cell of span b = 1.
  Coordinates are written x, y, z with i fastest (Fortran order).

  AXIS MAPPING, NASA -> OpenFOAM, recorded in provenance:

      OpenFOAM x  <-  NASA x   (chordwise)
      OpenFOAM y  <-  NASA z   (normal, in the flow plane)
      OpenFOAM z  <-  NASA y   (spanwise; the empty direction)

  GRID INDEX MAPPING:

      wrap index   i_wrap  <-  NASA j   (around the C, wake -> body -> wake)
      radial index j_rad   <-  NASA k   (body out to the farfield)

  NOTHING IS RE-EXTRUDED. The two spanwise planes supplied by NASA become the
  two spanwise point planes of the converted mesh, at their own y values. The
  converter never invents a span or replaces the geometry.

WHAT THIS DOES NOT DO
  It does not generate geometry. There is no NACA polynomial and no C-grid
  generator here: the airfoil shape, the sharp trailing edge, the wake cut and
  the ~500-chord farfield all come from the registered NASA file and are carried
  through unchanged. The domain is never truncated.

WHY GMSH AND NOT polyMesh
  Face/owner/neighbour construction is the one place a silent topology bug would
  survive until a solve. Emitting a cell-and-point mesh and letting
  ``gmshToFoam`` build the connectivity keeps that responsibility in OpenFOAM,
  which then reports on it through ``checkMesh``. The conversion toolchain is
  recorded in provenance as exactly that two-stage pipeline.

WAKE MERGING
  On the body line (j = 0) the two wake segments of a C-grid are geometrically
  coincident. The number of coincident points is DETECTED from the coordinates,
  not assumed from an index range, and the pairs are merged to one point each.
  Merging turns those boundary faces into internal faces, which is what closes
  the C-grid. If the detected topology does not look like a C-grid, conversion
  fails closed rather than producing a mesh with a slit in it.
"""
from __future__ import annotations

import gzip
import io
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

#: Coordinate tolerance for calling two points coincident, as a fraction of chord.
COINCIDENT_TOL_CHORD = 1.0e-9

#: How close, as a fraction of the interior chordwise extent, the innermost
#: coincident point must sit to the downstream end of the airfoil for it to BE
#: the trailing edge rather than a wake station.
#:
#: This is a topology-classification parameter, not a physical tolerance. On the
#: registered grids the trailing-edge spacing is O(1e-4) chord, so any value well
#: below 1 separates the two cases unambiguously; 0.10 also tolerates a coarse
#: test fixture. Which branch was taken is REPORTED in the audit, and a
#: misclassification is caught by the sharp-trailing-edge and
#: airfoil-patch-excludes-wake checks.
TE_ATTACH_FRACTION_CHORD = 0.10

#: Strict tolerance for "the two spanwise planes are identical in the flow
#: plane", as an absolute coordinate difference. NASA writes the planes from the
#: same 2-D section, so they agree to the printed precision; anything larger
#: means the file is not the registered two-plane grid.
PLANE_IDENTITY_TOL = 1.0e-10

#: Tolerance on the spanwise separation matching the registered span.
SPAN_TOL = 1.0e-10

#: The axis mapping, as data, so provenance records exactly what was applied.
AXIS_MAP = {
    "openfoam_x": "nasa_x (chordwise)",
    "openfoam_y": "nasa_z (flow-plane normal)",
    "openfoam_z": "nasa_y (spanwise, empty direction)",
    "wrap_index": "nasa_j",
    "radial_index": "nasa_k",
    "spanwise_index": "nasa_i (size 2)",
    "note": (
        "the two NASA spanwise planes are used as supplied; no re-extrusion and "
        "no regenerated geometry"
    ),
}

#: Patch names the converted mesh carries. Fixed, so the audit can assert them.
PATCH_AIRFOIL = "airfoil"
PATCH_FARFIELD = "farfield"
PATCH_FRONT = "front"
PATCH_BACK = "back"
EXPECTED_PATCHES = (PATCH_AIRFOIL, PATCH_FARFIELD, PATCH_FRONT, PATCH_BACK)

CONVERSION_VERSION = "airfoil-p3d-convert/2.0.0-nasa3d"
CONVERSION_TOOLCHAIN = (
    "src/pipeline/airfoil/p3d.py (NASA 3-D formatted Plot3D, 2 x I x J, "
    "spanwise-first; axes remapped NASA(x,z,y) -> OpenFOAM(x,y,z); wake merged; "
    "supplied spanwise planes preserved) -> gmshToFoam -> deterministic boundary "
    "rewrite (front/back -> empty) -> checkMesh -allTopology -allGeometry"
)


class ConversionError(RuntimeError):
    """The registered grid could not be converted deterministically."""


# ----------------------------------------------------------------------
@dataclass
class Plot3DGrid:
    """One structured block from a NASA formatted Plot3D file.

    Stored in NASA's own index order, ``ni x nj x nk`` with ni the spanwise
    direction of size 2. ``point()`` returns FLOW-PLANE coordinates already
    mapped to OpenFOAM axes, so downstream code never repeats the mapping.
    """

    ni: int
    nj: int
    nk: int
    x: List[float]
    y: List[float]
    z: List[float]

    def raw(self, i: int, j: int, k: int) -> int:
        """Fortran ordering: i fastest, then j, then k."""
        return i + self.ni * (j + self.nj * k)

    # -- OpenFOAM-facing accessors ------------------------------------
    @property
    def n_wrap(self) -> int:
        return self.nj

    @property
    def n_radial(self) -> int:
        return self.nk

    @property
    def n_span_planes(self) -> int:
        return self.ni

    def index(self, i_wrap: int, j_rad: int) -> int:
        """Flat index into the flow-plane point set (wrap fastest)."""
        return i_wrap + self.n_wrap * j_rad

    def point(self, i_wrap: int, j_rad: int, plane: int = 0) -> Tuple[float, float]:
        """Flow-plane (OpenFOAM x, y) = NASA (x, z)."""
        n = self.raw(plane, i_wrap, j_rad)
        return self.x[n], self.z[n]

    def span_coordinate(self, plane: int) -> float:
        """OpenFOAM z = NASA y, for one spanwise plane."""
        return self.y[self.raw(plane, 0, 0)]

    @property
    def cells_2d(self) -> int:
        return (self.n_wrap - 1) * (self.n_radial - 1)

    @property
    def cells_3d(self) -> int:
        return (self.ni - 1) * (self.nj - 1) * (self.nk - 1)

    @property
    def dimensions(self) -> Tuple[int, int, int]:
        return (self.ni, self.nj, self.nk)


def _open_text(path: Path) -> io.TextIOBase:
    path = Path(path)
    if path.suffix == ".gz":
        return io.TextIOWrapper(gzip.open(path, "rb"), encoding="ascii", errors="strict")
    return path.open("r", encoding="ascii", errors="strict")


def read_plot3d(path: Path) -> Plot3DGrid:
    """Read the registered NASA 3-D formatted Plot3D grid. Fails closed.

    Accepts exactly the layout NASA publishes: an optional block count of 1,
    then ``ni nj nk`` with ni == 2, then three coordinate arrays of ni*nj*nk
    values each in Fortran order. Anything else is refused rather than guessed
    at, because a misread grid is a silently wrong scientific input.

    Line structure carries no meaning -- NASA wraps coordinates arbitrarily --
    so the whole file is tokenised.
    """
    path = Path(path)
    with _open_text(path) as fh:
        tokens = fh.read().split()
    if not tokens:
        raise ConversionError(f"{path.name}: file is empty")

    def as_int(index: int) -> Optional[int]:
        try:
            value = float(tokens[index])
        except (IndexError, ValueError):
            return None
        return int(value) if value == int(value) else None

    # Two accepted headers: "nbl ni nj nk" with nbl == 1, or bare "ni nj nk".
    header_candidates = [(1, (as_int(1), as_int(2), as_int(3))),
                         (0, (as_int(0), as_int(1), as_int(2)))]
    chosen: Optional[Tuple[int, Tuple[int, int, int]]] = None
    for offset, dims in header_candidates:
        if None in dims:
            continue
        ni, nj, nk = dims  # type: ignore[misc]
        if ni < 1 or nj < 3 or nk < 3:
            continue
        if offset == 1 and as_int(0) != 1:
            continue
        expected = ni * nj * nk * 3
        if len(tokens) - (offset + 3) == expected:
            chosen = (offset + 3, (ni, nj, nk))
            break
    if chosen is None:
        raise ConversionError(
            f"{path.name}: cannot interpret the Plot3D header. Expected the NASA "
            "layout 'nbl=1' then 'ni nj nk' (ni = 2 spanwise planes) followed by "
            f"3*ni*nj*nk coordinates; found {len(tokens)} tokens beginning "
            f"{' '.join(tokens[:6])!r}. Refusing to guess."
        )

    cursor, (ni, nj, nk) = chosen
    if ni != 2:
        raise ConversionError(
            f"{path.name}: the first dimension is {ni}, not 2. The registered NASA "
            "grids carry exactly two spanwise planes; this family will not "
            "collapse, duplicate or re-extrude a different spanwise topology."
        )

    count = ni * nj * nk
    try:
        numbers = [float(v) for v in tokens[cursor:cursor + 3 * count]]
    except ValueError as exc:
        raise ConversionError(f"{path.name}: non-numeric coordinate value") from exc

    return Plot3DGrid(
        ni=ni, nj=nj, nk=nk,
        x=numbers[:count],
        y=numbers[count:2 * count],
        z=numbers[2 * count:3 * count],
    )


@dataclass
class SpanwiseCheck:
    """Whether the two supplied NASA planes really are two identical planes."""

    n_planes: int
    max_flow_plane_difference: float
    separation: float
    separation_is_uniform: bool
    max_separation_deviation: float
    identical_within_tolerance: bool
    separation_matches_span: bool
    expected_span: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            "spanwise_planes": self.n_planes,
            "max_flow_plane_coordinate_difference": self.max_flow_plane_difference,
            "plane_identity_tolerance": PLANE_IDENTITY_TOL,
            "planes_identical_in_flow_plane": self.identical_within_tolerance,
            "spanwise_separation": self.separation,
            "separation_is_uniform": self.separation_is_uniform,
            "max_separation_deviation": self.max_separation_deviation,
            "expected_span": self.expected_span,
            "separation_matches_registered_span": self.separation_matches_span,
            "span_tolerance": SPAN_TOL,
        }


def check_spanwise_planes(grid: Plot3DGrid, *, expected_span: float = 1.0) -> SpanwiseCheck:
    """Verify the two planes are identical in the flow plane and b apart.

    This is the check that makes "one spanwise cell" a measured fact about the
    registered file rather than an assumption of the converter.
    """
    if grid.ni != 2:
        raise ConversionError(f"expected 2 spanwise planes, found {grid.ni}")

    worst_flow = 0.0
    separations: List[float] = []
    for k in range(grid.nk):
        for j in range(grid.nj):
            a, b = grid.raw(0, j, k), grid.raw(1, j, k)
            worst_flow = max(
                worst_flow,
                abs(grid.x[a] - grid.x[b]),
                abs(grid.z[a] - grid.z[b]),
            )
            separations.append(grid.y[b] - grid.y[a])

    span = separations[0]
    deviation = max(abs(s - span) for s in separations)
    return SpanwiseCheck(
        n_planes=grid.ni,
        max_flow_plane_difference=worst_flow,
        separation=span,
        separation_is_uniform=deviation <= SPAN_TOL,
        max_separation_deviation=deviation,
        identical_within_tolerance=worst_flow <= PLANE_IDENTITY_TOL,
        separation_matches_span=abs(abs(span) - expected_span) <= SPAN_TOL,
        expected_span=expected_span,
    )


# ----------------------------------------------------------------------
@dataclass
class Topology:
    """What the coordinates say about this grid's C-topology."""

    wake_pairs: int
    pure_wake_pairs: int
    te_is_coincident: bool
    surface_i_start: int
    surface_i_end: int
    chord: float
    leading_edge: Tuple[float, float]
    trailing_edge: Tuple[float, float]
    trailing_edge_gap: float
    farfield_extent_chords: float
    notes: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "wake_coincident_point_pairs": self.wake_pairs,
            "pure_wake_pairs": self.pure_wake_pairs,
            "trailing_edge_in_coincident_run": self.te_is_coincident,
            "airfoil_surface_i_range": [self.surface_i_start, self.surface_i_end],
            "chord": self.chord,
            "leading_edge": list(self.leading_edge),
            "trailing_edge": list(self.trailing_edge),
            "trailing_edge_gap": self.trailing_edge_gap,
            "sharp_trailing_edge": self.trailing_edge_gap <= COINCIDENT_TOL_CHORD * 10,
            "farfield_extent_chords": self.farfield_extent_chords,
            "notes": list(self.notes),
        }


def detect_topology(grid: Plot3DGrid) -> Topology:
    """Find the wake cut and the airfoil surface from the coordinates alone."""
    ni, nj = grid.n_wrap, grid.n_radial

    xs = [grid.point(i, 0)[0] for i in range(ni)]
    ys = [grid.point(i, 0)[1] for i in range(ni)]

    # The body line spans the airfoil AND the wake, so its extent is not the
    # chord. Detect the wake cut first with a tolerance scaled by the whole
    # extent -- coincident points in a structured grid are identical to within
    # round-off, so a loose tolerance is safe here -- then measure the chord on
    # the airfoil surface alone.
    line_extent = max(xs) - min(xs)
    if line_extent <= 0.0:
        raise ConversionError("body line has zero chordwise extent")
    tol = COINCIDENT_TOL_CHORD * line_extent

    pairs = 0
    for i in range(ni // 2):
        mirror = ni - 1 - i
        if (
            abs(xs[i] - xs[mirror]) <= tol
            and abs(ys[i] - ys[mirror]) <= tol
        ):
            pairs += 1
        else:
            break

    if pairs == 0:
        raise ConversionError(
            "no coincident points found on the body line: this does not look like "
            "a C-grid with a wake cut. Refusing to convert rather than emitting a "
            "mesh whose wake interface may be unmerged."
        )
    if pairs * 2 >= ni - 2:
        raise ConversionError(
            f"detected {pairs} coincident pairs on a body line of {ni} points, "
            "which would leave no airfoil surface. Refusing."
        )

    # A SHARP trailing edge is itself a coincident pair: the lower- and
    # upper-surface ends are the same point, so the run detected above ends ON
    # the trailing edge rather than just before it. Including it in the wake
    # would silently drop the two wall faces adjacent to the trailing edge from
    # the airfoil patch -- and with them their contribution to force and Cp.
    #
    # Distinguish by position: wake points lie DOWNSTREAM of the whole airfoil;
    # the trailing edge does not.
    inner_x = xs[pairs:ni - pairs]
    if inner_x:
        inner_extent = max(inner_x) - min(inner_x)
        gap = xs[pairs - 1] - max(inner_x)
        te_is_coincident = (
            inner_extent > 0.0
            and -tol <= gap <= TE_ATTACH_FRACTION_CHORD * inner_extent
        )
    else:  # pragma: no cover - guarded earlier
        te_is_coincident = False
    if te_is_coincident:
        surface_start, surface_end = pairs - 1, ni - pairs
        wake_pairs_pure = pairs - 1
    else:
        surface_start, surface_end = pairs, ni - 1 - pairs
        wake_pairs_pure = pairs

    surface_x = xs[surface_start:surface_end + 1]
    surface_y = ys[surface_start:surface_end + 1]

    chord = max(surface_x) - min(surface_x)
    if chord <= 0.0:
        raise ConversionError("detected airfoil surface has zero chordwise extent")

    le_i = surface_start + min(
        range(len(surface_x)), key=lambda n: surface_x[n]
    )
    leading_edge = (xs[le_i], ys[le_i])
    trailing_edge = (xs[surface_start], ys[surface_start])
    te_gap = math.hypot(
        xs[surface_start] - xs[surface_end], ys[surface_start] - ys[surface_end]
    )

    far_x = [grid.point(i, nj - 1)[0] for i in range(ni)]
    far_y = [grid.point(i, nj - 1)[1] for i in range(ni)]
    extent = max(
        max(abs(v) for v in far_x),
        max(abs(v) for v in far_y),
    ) / chord

    notes = [
        f"wake cut detected from coordinates: {pairs} coincident point pairs on "
        f"the body line (tolerance {tol:.3e}, scaled by the body-line extent "
        f"{line_extent:.6g})",
        f"chord measured on the detected surface only: {chord:.6g}",
        (
            "the trailing edge is part of the coincident run (sharp trailing edge): "
            f"{wake_pairs_pure} pure wake pairs plus the trailing-edge point, so "
            "the wall patch keeps its trailing-edge faces"
            if te_is_coincident
            else f"{wake_pairs_pure} wake pairs; the trailing edge is not coincident"
        ),
        f"airfoil surface spans i = {surface_start} .. {surface_end} "
        f"({surface_end - surface_start} faces)",
    ]
    return Topology(
        wake_pairs=pairs,
        pure_wake_pairs=wake_pairs_pure,
        te_is_coincident=te_is_coincident,
        surface_i_start=surface_start,
        surface_i_end=surface_end,
        chord=chord,
        leading_edge=leading_edge,
        trailing_edge=trailing_edge,
        trailing_edge_gap=te_gap,
        farfield_extent_chords=extent,
        notes=notes,
    )


# ----------------------------------------------------------------------
def _quad_area(p0, p1, p2, p3) -> float:
    """Signed area of a planar quad by the shoelace formula."""
    pts = (p0, p1, p2, p3)
    total = 0.0
    for n in range(4):
        x0, y0 = pts[n]
        x1, y1 = pts[(n + 1) % 4]
        total += x0 * y1 - x1 * y0
    return 0.5 * total


@dataclass
class ConvertedMesh:
    """A converted mesh, in memory, before it is written."""

    points: List[Tuple[float, float, float]]
    hexes: List[Tuple[int, ...]]
    patches: Dict[str, List[Tuple[int, ...]]]
    topology: Topology
    span: float
    merged_point_pairs: int
    min_cell_volume: float
    max_cell_volume: float
    negative_or_zero_volume_cells: int
    source_dimensions: Tuple[int, int, int]
    spanwise: "SpanwiseCheck" = None  # type: ignore[assignment]
    span_coordinates: Tuple[float, float] = (0.0, 0.0)

    @property
    def cells(self) -> int:
        return len(self.hexes)


def convert(
    grid: Plot3DGrid,
    *,
    span: float = 1.0,
    scale: float = 1.0,
) -> ConvertedMesh:
    """Merge the wake and build cells between the SUPPLIED spanwise planes.

    ``span`` is the REGISTERED span the file is checked against, not a value
    applied to the mesh: the two spanwise coordinates come from NASA's own y
    values. Nothing is extruded and no geometry is regenerated.
    """
    spanwise = check_spanwise_planes(grid, expected_span=span)
    if not spanwise.identical_within_tolerance:
        raise ConversionError(
            "the two spanwise planes are not identical in the flow plane: worst "
            f"coordinate difference {spanwise.max_flow_plane_difference:.3e} "
            f"exceeds {PLANE_IDENTITY_TOL:.1e}. Refusing: this is not the "
            "registered two-plane NASA grid."
        )
    if not spanwise.separation_is_uniform:
        raise ConversionError(
            "the spanwise separation is not uniform: worst deviation "
            f"{spanwise.max_separation_deviation:.3e}. Refusing."
        )
    if not spanwise.separation_matches_span:
        raise ConversionError(
            f"the spanwise separation is {spanwise.separation:.12g}, which does not "
            f"match the registered span b = {span:.12g} within {SPAN_TOL:.1e}. "
            "Refusing rather than rescaling a registered scientific asset."
        )

    topology = detect_topology(grid)
    ni, nj = grid.n_wrap, grid.n_radial

    # Point identity map over the FLOW-PLANE point set: merged wake pairs share
    # an index, which is what closes the C-grid.
    ident = list(range(ni * nj))
    merged = 0
    for i in range(topology.wake_pairs):
        a, b = grid.index(i, 0), grid.index(ni - 1 - i, 0)
        ident[max(a, b)] = min(a, b)
        merged += 1

    plane_index: Dict[int, int] = {}
    plane_points: List[Tuple[float, float]] = []
    for n in range(ni * nj):
        root = ident[n]
        if root not in plane_index:
            plane_index[root] = len(plane_points)
            i_wrap, j_rad = root % ni, root // ni
            px, py = grid.point(i_wrap, j_rad, plane=0)
            plane_points.append((px * scale, py * scale))

    def pid(i: int, j: int, layer: int) -> int:
        base = plane_index[ident[grid.index(i, j)]]
        return base + layer * len(plane_points)

    # The two spanwise coordinates are NASA's own y values, mapped to OpenFOAM z.
    z0 = grid.span_coordinate(0) * scale
    z1 = grid.span_coordinate(1) * scale
    points: List[Tuple[float, float, float]] = [
        (px, py, z0) for px, py in plane_points
    ] + [(px, py, z1) for px, py in plane_points]
    span_actual = abs(z1 - z0)

    hexes: List[Tuple[int, ...]] = []
    patches: Dict[str, List[Tuple[int, ...]]] = {k: [] for k in EXPECTED_PATCHES}
    vmin, vmax, bad = math.inf, -math.inf, 0

    for j in range(nj - 1):
        for i in range(ni - 1):
            n0, n1 = (i, j), (i + 1, j)
            n2, n3 = (i + 1, j + 1), (i, j + 1)
            area = _quad_area(
                grid.point(*n0), grid.point(*n1), grid.point(*n2), grid.point(*n3)
            )
            volume = abs(area) * span_actual * scale * scale
            vmin, vmax = min(vmin, volume), max(vmax, volume)
            if volume <= 0.0 or not math.isfinite(volume):
                bad += 1
            order = (n0, n1, n2, n3) if area > 0 else (n0, n3, n2, n1)
            bottom = [pid(a, b, 0) for a, b in order]
            top = [pid(a, b, 1) for a, b in order]
            hexes.append(tuple(bottom + top))

            patches[PATCH_BACK].append(tuple(bottom))
            patches[PATCH_FRONT].append(tuple(reversed(top)))

            if j == 0 and topology.surface_i_start <= i < topology.surface_i_end:
                patches[PATCH_AIRFOIL].append(
                    (pid(i, 0, 0), pid(i + 1, 0, 0), pid(i + 1, 0, 1), pid(i, 0, 1))
                )
            if j == nj - 2:
                patches[PATCH_FARFIELD].append(
                    (
                        pid(i, nj - 1, 0), pid(i + 1, nj - 1, 0),
                        pid(i + 1, nj - 1, 1), pid(i, nj - 1, 1),
                    )
                )
            if i == 0:
                patches[PATCH_FARFIELD].append(
                    (pid(0, j, 0), pid(0, j + 1, 0), pid(0, j + 1, 1), pid(0, j, 1))
                )
            if i == ni - 2:
                patches[PATCH_FARFIELD].append(
                    (
                        pid(ni - 1, j, 0), pid(ni - 1, j + 1, 0),
                        pid(ni - 1, j + 1, 1), pid(ni - 1, j, 1),
                    )
                )

    return ConvertedMesh(
        points=points,
        hexes=hexes,
        patches=patches,
        topology=topology,
        span=span_actual,
        merged_point_pairs=merged,
        min_cell_volume=vmin,
        max_cell_volume=vmax,
        negative_or_zero_volume_cells=bad,
        source_dimensions=grid.dimensions,
        spanwise=spanwise,
        span_coordinates=(z0, z1),
    )


def write_gmsh(mesh: ConvertedMesh, path: Path) -> Path:
    """Write Gmsh 2.2 ASCII. Physical surfaces carry the patch names."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    names = list(EXPECTED_PATCHES)
    tags = {name: n + 1 for n, name in enumerate(names)}
    volume_tag = len(names) + 1

    out: List[str] = ["$MeshFormat", "2.2 0 8", "$EndMeshFormat", "$PhysicalNames",
                      str(len(names) + 1)]
    for name in names:
        out.append(f'2 {tags[name]} "{name}"')
    out.append(f'3 {volume_tag} "internal"')
    out.append("$EndPhysicalNames")

    out.append("$Nodes")
    out.append(str(len(mesh.points)))
    for n, (px, py, pz) in enumerate(mesh.points, start=1):
        out.append(f"{n} {px:.12g} {py:.12g} {pz:.12g}")
    out.append("$EndNodes")

    total = len(mesh.hexes) + sum(len(v) for v in mesh.patches.values())
    out.append("$Elements")
    out.append(str(total))
    eid = 0
    for cell in mesh.hexes:
        eid += 1
        nodes = " ".join(str(n + 1) for n in cell)
        out.append(f"{eid} 5 2 {volume_tag} {volume_tag} {nodes}")
    for name in names:
        tag = tags[name]
        for face in mesh.patches[name]:
            eid += 1
            nodes = " ".join(str(n + 1) for n in face)
            out.append(f"{eid} 3 2 {tag} {tag} {nodes}")
    out.append("$EndElements")
    path.write_text("\n".join(out) + "\n", encoding="ascii")
    return path


def duplicate_face_count(mesh: ConvertedMesh) -> int:
    """Boundary faces that appear twice -- an unmerged coincident wake interface.

    After correct merging the wake faces are internal and cannot appear in any
    boundary patch. A non-zero count here means the C-grid slit is still open.
    """
    seen: Dict[Tuple[int, ...], int] = {}
    for name in (PATCH_AIRFOIL, PATCH_FARFIELD):
        for face in mesh.patches[name]:
            key = tuple(sorted(face))
            seen[key] = seen.get(key, 0) + 1
    return sum(1 for count in seen.values() if count > 1)
