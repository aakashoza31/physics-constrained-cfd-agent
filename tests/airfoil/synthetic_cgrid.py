#!/usr/bin/env python3
"""A synthetic C-GRID TOPOLOGY FIXTURE. Not CFD, and not an airfoil.

It uses the SAME LAYOUT as the registered NASA assets: 3-D formatted Plot3D,
single block, ``nbl = 1`` then ``2 x I x J`` with the spanwise direction FIRST,
two identical x-z planes separated by y = span. It is a layout fixture, not a 2-D
surrogate.

THIS IS NOT NACA0012 AND IS NOT A REGENERATED AIRFOIL. The body is a symmetric
parabolic lens, chosen precisely because nobody could mistake it for an aerofoil
section. Its only job is to exercise the Plot3D reader, the coordinate-based
wake-cut detection, the point merge, the one-layer extrusion and the patch
inventory without the registered NASA asset present.

Family 3 never builds geometry this way. The registered NASA grid is the only
geometry the family will ever solve on.
"""
from __future__ import annotations

import gzip
import math
from pathlib import Path
from typing import List, Tuple

#: Lens half-thickness, as a fraction of chord. Deliberately fat and obvious.
LENS_THICKNESS = 0.12


def _lens(x: float) -> float:
    """Symmetric parabolic lens: sharp at x = 0 and x = 1."""
    return LENS_THICKNESS * x * (1.0 - x)


def _body_line(n_wake: int, n_surface: int, wake_end: float) -> List[Tuple[float, float]]:
    """Wake-lower -> surface (TE, round the lens, TE) -> wake-upper.

    The two wake segments are EXACTLY coincident and exactly ``n_wake`` points
    long, so the detector has an unambiguous answer to find.
    """
    # Wake x stations, outflow -> just downstream of the trailing edge.
    wake_x = [wake_end + (1.0 - wake_end) * (i / n_wake) for i in range(n_wake)]

    surface: List[Tuple[float, float]] = []
    half = n_surface // 2
    for i in range(half):                       # lower surface, TE -> just before LE
        x = 1.0 - i / half
        surface.append((x, -_lens(x)))
    for i in range(n_surface - half + 1):       # LE -> TE on the upper side
        x = i / (n_surface - half)
        surface.append((x, +_lens(x)))

    pts = [(x, 0.0) for x in wake_x]
    pts += surface
    pts += [(x, 0.0) for x in reversed(wake_x)]
    return pts
def _directions(body: List[Tuple[float, float]], n_wake: int) -> List[Tuple[float, float]]:
    """Outward push direction per i, blended so the C opens without crossing."""
    n = len(body)
    dirs: List[Tuple[float, float]] = []
    for i, (x, y) in enumerate(body):
        if i < n_wake:
            d = (0.0, -1.0)
        elif i >= n - n_wake:
            d = (0.0, +1.0)
        else:
            # Outward normal of the lens, pointing away from the chord line.
            eps = 1.0e-4
            xm, xp = max(0.0, x - eps), min(1.0, x + eps)
            sign = 1.0 if y >= 0.0 else -1.0
            dy = sign * (_lens(xp) - _lens(xm))
            dx = xp - xm
            length = math.hypot(dx, dy) or 1.0
            d = (-dy / length * sign, dx / length * sign)
            d = (d[0], d[1] if sign > 0 else d[1])
            if (d[1] > 0) != (sign > 0):
                d = (-d[0], -d[1])
        dirs.append(d)
    # Smooth across the two wake/surface junctions so no quad folds over.
    for _ in range(12):
        smoothed = list(dirs)
        for i in range(1, n - 1):
            ax, ay = dirs[i - 1]
            bx, by = dirs[i]
            cx, cy = dirs[i + 1]
            sx, sy = (ax + 2 * bx + cx) / 4.0, (ay + 2 * by + cy) / 4.0
            length = math.hypot(sx, sy) or 1.0
            smoothed[i] = (sx / length, sy / length)
        dirs = smoothed
    return dirs


def make_cgrid(
    n_wake: int = 12,
    n_surface: int = 40,
    nj: int = 17,
    farfield_chords: float = 500.0,
    wake_end: float = 501.0,
) -> Tuple[int, int, List[float], List[float]]:
    """Return (ni, nj, x, y) for a synthetic single-block C-grid."""
    body = _body_line(n_wake, n_surface, wake_end)
    ni = len(body)
    dirs = _directions(body, n_wake)

    # Geometric radial stretching from a thin first layer out to the farfield.
    first = 1.0e-5
    ratio = (farfield_chords / first) ** (1.0 / (nj - 1))
    offsets = [0.0] + [first * (ratio ** k - 1.0) / (ratio - 1.0) * (ratio - 1.0) / 1.0
                       for k in range(1, nj)]
    offsets = [0.0]
    acc = 0.0
    step = first
    for _ in range(nj - 1):
        acc += step
        offsets.append(acc)
        step *= ratio
    scale = farfield_chords / offsets[-1]
    offsets = [o * scale for o in offsets]

    x: List[float] = []
    y: List[float] = []
    for j in range(nj):
        for i in range(ni):
            bx, by = body[i]
            dx, dy = dirs[i]
            x.append(bx + dx * offsets[j])
            y.append(by + dy * offsets[j])
    return ni, nj, x, y


def write_plot3d(
    path: Path,
    *,
    gzipped: bool = True,
    span: float = 1.0,
    nbl_header: bool = True,
    plane_perturbation: float = 0.0,
    span_override: float = None,
    **kw,
) -> Path:
    """Write the fixture in NASA's 3-D formatted Plot3D layout: 2 x I x J.

    ``plane_perturbation`` and ``span_override`` exist so the tests can prove the
    reader FAILS CLOSED on a file whose planes are not identical, or whose
    separation does not match the registered span.
    """
    ni_wrap, nj_rad, xs, ys = make_cgrid(**kw)

    # NASA order: ni = 2 spanwise, nj = wrap, nk = radial; i fastest.
    n_span = 2
    x: List[float] = []
    y: List[float] = []
    z: List[float] = []
    sep = span if span_override is None else span_override
    for k in range(nj_rad):
        for j in range(ni_wrap):
            flat = j + ni_wrap * k
            for i in range(n_span):
                # OpenFOAM (x, y) <- NASA (x, z); spanwise is NASA y.
                bump = plane_perturbation if i == 1 else 0.0
                x.append(xs[flat] + bump)
                z.append(ys[flat])
                y.append(0.0 if i == 0 else sep)

    lines: List[str] = []
    if nbl_header:
        lines.append("1")
    lines.append(f"{n_span} {ni_wrap} {nj_rad}")
    for values in (x, y, z):
        for chunk in range(0, len(values), 6):
            lines.append(" ".join(f"{v:.12e}" for v in values[chunk:chunk + 6]))
    text = "\n".join(lines) + "\n"

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if gzipped:
        with gzip.open(path, "wb") as fh:
            fh.write(text.encode("ascii"))
    else:
        path.write_text(text, encoding="ascii")
    return path
