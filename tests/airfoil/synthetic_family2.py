#!/usr/bin/env python3
"""A NASA-Family-II-SHAPED synthetic CGNS grid. TEST FIXTURE ONLY.

This is not a NASA file. It is an O-grid built from the SAME frozen corrected TMR
sharp-trailing-edge geometry, wrapped so that the seam behind the airfoil is
interior connectivity (the joined-wake property the real C-grids have), with two
spanwise planes at NASA's own span of 1.0.

Its purpose is to exercise the Family II conversion and the frozen gates end to
end -- patch classification, span rescaling, coordinate preservation, orientation,
one connected region -- without the multi-hundred-megabyte real assets.
"""
from __future__ import annotations

import math
from pathlib import Path
from typing import Dict, List, Sequence, Tuple

from src.pipeline.airfoil import geometry as G
from tests.airfoil.synthetic_cgns import write_cgns_hex

#: NASA's own span in the Family II hex files: two planes separated by 1.
SOURCE_SPAN = 1.0


def _surface_ring(n_per_side: int) -> List[Tuple[float, float]]:
    """Closed airfoil ring, TE once, from the frozen analytic section."""
    return G.section(n_per_side).closed_loop()


def build(*, n_per_side: int = 32, n_radial: int = 12,
          farfield_radius: float = 500.0,
          growth: float = 1.0) -> Tuple[List[Tuple[float, float, float]],
                                        List[Tuple[int, ...]], Dict[str, int]]:
    """Points (OpenFOAM axes) and hexes of the synthetic O-grid.

    Radial stations are a geometric progression from the wall out to the farfield
    circle, so the mesh is smooth rather than merely valid.
    """
    ring = _surface_ring(n_per_side)
    ni = len(ring)                       # wrap count; the seam is shared
    centre = (0.5, 0.0)

    # Geometric radial distribution from a first offset to the farfield radius.
    first = 1.0e-3
    if growth <= 1.0:
        # Solve the ratio that reaches the farfield in n_radial-1 steps.
        lo, hi = 1.0 + 1e-12, 4.0
        target = farfield_radius - 0.5
        for _ in range(200):
            mid = 0.5 * (lo + hi)
            total = first * (mid ** (n_radial - 1) - 1.0) / (mid - 1.0)
            if total < target:
                lo = mid
            else:
                hi = mid
        growth = 0.5 * (lo + hi)
    offsets = [0.0]
    step = first
    for _ in range(n_radial - 1):
        offsets.append(offsets[-1] + step)
        step *= growth

    plane: List[Tuple[float, float]] = []
    for j, offset in enumerate(offsets):
        blend = offset / offsets[-1]
        for x, y in ring:
            # Outward normal direction, taken from the airfoil point itself.
            dx, dy = x - centre[0], y - centre[1]
            norm = math.hypot(dx, dy) or 1.0
            ux, uy = dx / norm, dy / norm
            # Blend from the section to a circle of the farfield radius.
            cx = centre[0] + farfield_radius * ux
            cy = centre[1] + farfield_radius * uy
            plane.append((x + (cx - x) * blend, y + (cy - y) * blend))

    n_plane = len(plane)
    points = [(x, y, 0.0) for x, y in plane] + [(x, y, SOURCE_SPAN) for x, y in plane]

    def node(j: int, i: int, k: int) -> int:
        return k * n_plane + j * ni + (i % ni)

    hexes: List[Tuple[int, ...]] = []
    for j in range(n_radial - 1):
        for i in range(ni):
            a, b = node(j, i, 0), node(j, i + 1, 0)
            c, d = node(j + 1, i + 1, 0), node(j + 1, i, 0)
            hexes.append((a, b, c, d,
                          a + n_plane, b + n_plane, c + n_plane, d + n_plane))
    counts = {"ni": ni, "n_radial": n_radial, "cells": len(hexes),
              "points": len(points)}
    return points, hexes, counts


def write(path: Path, **kwargs) -> Tuple[Path, Dict[str, int]]:
    points, hexes, counts = build(**kwargs)
    write_cgns_hex(Path(path), points, hexes)
    return Path(path), counts
