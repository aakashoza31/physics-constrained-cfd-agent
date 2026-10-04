#!/usr/bin/env python3
"""Corrected TMR sharp-trailing-edge NACA0012 geometry. Analytic, exact.

    f(xi) = 0.2969*sqrt(xi) - 0.1260*xi - 0.3516*xi^2 + 0.2843*xi^3 - 0.1015*xi^4

The classical NACA 0012 polynomial does not close: f(1) > 0. The TMR correction
takes the positive root xi_T of f, then rescales:

    x    = xi / xi_T
    y_pm = +- 0.6 * f(xi) / xi_T ,      0 <= xi <= xi_T

so the section is exactly closed at x = 1 with a SHARP trailing edge, chord 1,
leading edge at (0, 0) and trailing edge at (1, 0).

xi_T is SOLVED numerically to full double precision here. The rounded value
1.008930411365 is carried only as a cross-check.

There is no leading-edge rounding, no trailing-edge clipping, no finite-thickness
closure and no smoothing. Upper and lower surfaces are exact reflections of one
number each, so symmetry is structural rather than approximate.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Sequence, Tuple

GEOMETRY_VERSION = "naca0012-tmr-sharp-te/1.0.0"

#: Frozen polynomial coefficients of the corrected TMR definition.
A0, A1, A2, A3, A4 = 0.2969, -0.1260, -0.3516, 0.2843, -0.1015

#: The frozen rounded root, used only to verify the numerical solve.
XI_T_REFERENCE = 1.008930411365

#: Analytic boundary error budget, as a fraction of chord.
BOUNDARY_ERROR_BUDGET = 1.0e-12


def f(xi: float) -> float:
    """The corrected NACA 0012 thickness polynomial."""
    if xi < 0.0:
        raise ValueError(f"xi must be non-negative, got {xi}")
    return (
        A0 * math.sqrt(xi) + A1 * xi + A2 * xi * xi + A3 * xi ** 3 + A4 * xi ** 4
    )


def solve_xi_t(*, tol: float = 0.0, max_iter: int = 200) -> float:
    """The positive root of f beyond xi = 1, by bisection to machine precision.

    Bisection rather than Newton: the derivative of sqrt(xi) is fine here, but a
    bracketed method cannot leave the root, and the interval is halved until the
    two ends are adjacent doubles. That makes the answer reproducible bit for bit
    on any platform.
    """
    lo, hi = 1.0, 1.2
    if f(lo) <= 0.0:
        raise RuntimeError("f(1) must be positive for the TMR correction to apply")
    while f(hi) > 0.0:
        hi += 0.1
        if hi > 2.0:  # pragma: no cover - defensive
            raise RuntimeError("no sign change found for f beyond xi = 1")
    for _ in range(max_iter):
        mid = 0.5 * (lo + hi)
        if mid == lo or mid == hi:
            break
        if f(mid) > 0.0:
            lo = mid
        else:
            hi = mid
        if tol > 0.0 and (hi - lo) <= tol:
            break
    return 0.5 * (lo + hi)


XI_T = solve_xi_t()


def ordinate(x: float, *, xi_t: float = XI_T) -> float:
    """Upper-surface y at chordwise station x in [0, 1]. Lower is the negative."""
    if x < 0.0 or x > 1.0:
        raise ValueError(f"x/c must lie in [0, 1], got {x}")
    return 0.6 * f(x * xi_t) / xi_t


def cosine_stations(n: int) -> List[float]:
    """x_j/c = (1 - cos(pi j / N)) / 2 for j = 0..N. Frozen surface spacing."""
    if int(n) != n or n < 4:
        raise ValueError(f"N must be an integer >= 4, got {n!r}")
    return [0.5 * (1.0 - math.cos(math.pi * j / n)) for j in range(int(n) + 1)]


def polynomial_parameter_stations(n: int, *, xi_t: float = XI_T) -> List[float]:
    """The equivalent xi = xi_T t^2 parameterisation, for provenance.

    Included because the recipe names it: t = sqrt(xi/xi_T) removes the sqrt
    singularity at the leading edge, and the identity is asserted in the tests.
    """
    return [xi_t * (j / n) ** 2 for j in range(int(n) + 1)]


# ----------------------------------------------------------------------
# Surface arc length. Needed by recipe v2, which prescribes the near-trailing-
# edge spacing in ARC LENGTH rather than in x. The geometry itself is untouched:
# every ordinate still comes from `ordinate`, and nothing below alters a point
# that the v1 distribution would have produced.
# ----------------------------------------------------------------------

#: Nodes of the 20-point Gauss-Legendre rule on [-1, 1], and their weights.
#: Fixed-order Gauss-Legendre rather than an adaptive quadrature: the integrand
#: is smooth away from the leading edge, and a fixed rule gives the same answer
#: to the last bit on every platform and every run, which an adaptive subdivision
#: does not guarantee.
_GL_ORDER = 20


def _gauss_legendre(order: int = _GL_ORDER) -> Tuple[Tuple[float, ...], Tuple[float, ...]]:
    """Gauss-Legendre nodes and weights, by Newton iteration on P_n."""
    nodes: List[float] = []
    weights: List[float] = []
    for i in range(1, order + 1):
        # Chebyshev starting guess, then Newton on the Legendre polynomial.
        x = math.cos(math.pi * (i - 0.25) / (order + 0.5))
        for _ in range(100):
            p0, p1 = 1.0, 0.0
            for j in range(1, order + 1):
                p0, p1 = ((2 * j - 1) * x * p0 - (j - 1) * p1) / j, p0
            dp = order * (x * p0 - p1) / (x * x - 1.0)
            dx = -p0 / dp
            x += dx
            if abs(dx) <= 1.0e-16:
                break
        nodes.append(x)
        weights.append(2.0 / ((1.0 - x * x) * dp * dp))
    return tuple(nodes), tuple(weights)


_GL_NODES, _GL_WEIGHTS = _gauss_legendre()


def ordinate_slope(x: float, *, xi_t: float = XI_T, h: float = 1.0e-7) -> float:
    """dy/dx of the upper surface, analytically where possible.

    y(x) = 0.6 f(xi)/xi_T with xi = x*xi_T, so dy/dx = 0.6 f'(xi). The derivative
    of the sqrt term diverges at the leading edge; recipe v2 only ever needs the
    slope on [0.98, 1], where it is finite and smooth.
    """
    xi = float(x) * xi_t
    if xi <= 0.0:
        return float("inf")
    fp = (0.5 * A0 / math.sqrt(xi) + A1 + 2.0 * A2 * xi + 3.0 * A3 * xi * xi
          + 4.0 * A4 * xi ** 3)
    return 0.6 * fp


def _integrand(x: float, xi_t: float) -> float:
    slope = ordinate_slope(x, xi_t=xi_t)
    return math.sqrt(1.0 + slope * slope)


def arc_length(x0: float, x1: float, *, xi_t: float = XI_T,
               panels: int = 64) -> float:
    """Surface arc length of the analytic upper surface between two x stations.

    Composite Gauss-Legendre. Panels are laid out so the rule stays accurate
    where the slope changes fastest; 64 panels of order 20 is far beyond what the
    smooth integrand on [0.98, 1] needs, and costs microseconds.
    """
    if x1 < x0:
        return -arc_length(x1, x0, xi_t=xi_t, panels=panels)
    total = 0.0
    width = (x1 - x0) / panels
    for k in range(panels):
        a = x0 + k * width
        half = 0.5 * width
        mid = a + half
        for node, weight in zip(_GL_NODES, _GL_WEIGHTS):
            total += weight * _integrand(mid + half * node, xi_t)
    return total * 0.5 * width


def x_at_arc_from_te(s: float, *, xi_t: float = XI_T, x_min: float = 0.0,
                     tol: float = 1.0e-15, max_iter: int = 200) -> float:
    """Invert the arc length: the x whose arc distance UPSTREAM of the TE is s.

    Bisection on a monotone function. s = 0 returns the trailing edge exactly.
    """
    if s <= 0.0:
        return 1.0
    lo, hi = float(x_min), 1.0
    if arc_length(lo, 1.0, xi_t=xi_t) < s:
        raise ValueError(
            f"arc distance {s} exceeds the surface length upstream of the "
            f"trailing edge from x = {x_min}"
        )
    for _ in range(max_iter):
        mid = 0.5 * (lo + hi)
        if arc_length(mid, 1.0, xi_t=xi_t) > s:
            lo = mid
        else:
            hi = mid
        if hi - lo <= tol:
            break
    return 0.5 * (lo + hi)


def geometric_progression_ratio(total: float, first: float, n: int, *,
                                q_max: float, tol: float = 1.0e-15,
                                max_iter: int = 300) -> float:
    """The unique q > 1 with  first * (q^n - 1)/(q - 1) = total.

    Bisection on (1, q_max]. The sum is strictly increasing in q, so the root is
    unique; bisection cannot leave the bracket, and the bracket is the frozen
    q_max, so a solution that would exceed the declared growth limit is reported
    as an error rather than silently returned.
    """
    if n < 1:
        raise ValueError("n must be at least 1")
    if n == 1:
        if abs(first - total) > 1.0e-12 * max(1.0, abs(total)):
            raise ValueError("a single interval cannot match the total length")
        return 1.0

    def series(q: float) -> float:
        return first * n if abs(q - 1.0) < 1.0e-15 else first * (q ** n - 1.0) / (q - 1.0)

    lo, hi = 1.0, float(q_max)
    if series(hi) < total:
        raise ValueError(
            f"even q = q_max = {q_max} gives {series(hi)} < required {total}: the "
            "interval count is too small for the prescribed first spacing"
        )
    if series(lo) > total:
        raise ValueError(
            f"n = {n} intervals of the prescribed first spacing already exceed "
            f"{total}: the interval count is too large"
        )
    for _ in range(max_iter):
        mid = 0.5 * (lo + hi)
        if series(mid) < total:
            lo = mid
        else:
            hi = mid
        if hi - lo <= tol * hi:
            break
    return 0.5 * (lo + hi)


def v2_stations(*, n_body: int, n_te: int, x_partition: float,
                delta_te: float, q_max: float,
                xi_t: float = XI_T) -> Dict[str, Any]:
    """Recipe v2 surface stations for ONE side, leading edge to trailing edge.

    Two zones that meet exactly at ``x_partition``:

      * LE to x_T: the TRUNCATED cosine distribution, x_j = (1 - cos(j th_T/n))/2
        with th_T = acos(1 - 2 x_T). This is the v1 law restricted to the body,
        so the body spacing is unchanged in character.
      * x_T to TE: a geometric progression in SURFACE ARC LENGTH, started at the
        trailing edge with the prescribed first interval and solved so that it
        terminates EXACTLY at x_T. No residual interval is appended.

    The geometry is not touched: every station is placed on the same analytic
    section, and the ordinates come from `ordinate` as before.
    """
    theta_t = math.acos(1.0 - 2.0 * float(x_partition))
    body = [
        0.5 * (1.0 - math.cos(j * theta_t / n_body)) for j in range(n_body + 1)
    ]
    # Snap the two ends of the body zone to their exact values.
    body[0] = 0.0
    body[-1] = float(x_partition)

    total = arc_length(x_partition, 1.0, xi_t=xi_t)
    q = geometric_progression_ratio(total, delta_te, n_te, q_max=q_max)

    # March upstream from the trailing edge, accumulating arc length.
    arcs: List[float] = []
    step = delta_te
    walked = 0.0
    for _ in range(n_te):
        walked += step
        arcs.append(walked)
        step *= q
    # The last node IS the partition, by construction. Pin it rather than
    # inverting the arc length one more time, so the two zones share one vertex.
    te_zone = [x_at_arc_from_te(a, xi_t=xi_t, x_min=0.5 * x_partition)
               for a in arcs[:-1]]
    te_zone.append(float(x_partition))
    te_zone.reverse()                       # x_partition .. nearest-to-TE

    stations = body[:-1] + te_zone + [1.0]
    return {
        "stations": stations,
        "theta_t_rad": theta_t,
        "x_partition": float(x_partition),
        "n_body": int(n_body),
        "n_te": int(n_te),
        "arc_length_partition_to_te": total,
        "delta_te_prescribed": float(delta_te),
        "growth_ratio": q,
        "growth_ratio_max": float(q_max),
        "terminates_at_partition": abs(walked - total) <= 1.0e-12 * total,
        "series_residual": walked - total,
    }


def section_v2(*, n_body: int, n_te: int, x_partition: float, delta_te: float,
               q_max: float, xi_t: float = XI_T) -> Tuple["Section", Dict[str, Any]]:
    """Build the v2 section. Same geometry, same reflection, new stations."""
    build = v2_stations(n_body=n_body, n_te=n_te, x_partition=x_partition,
                        delta_te=delta_te, q_max=q_max, xi_t=xi_t)
    stations = build["stations"]
    upper = [(x, ordinate(x, xi_t=xi_t)) for x in stations]
    lower = [(x, -y) for x, y in upper]
    upper[0] = (0.0, 0.0)
    lower[0] = (0.0, 0.0)
    upper[-1] = (1.0, 0.0)
    lower[-1] = (1.0, 0.0)
    sec = Section(tuple(stations), tuple(upper), tuple(lower), xi_t,
                  len(stations) - 1)
    return sec, build


@dataclass(frozen=True)
class Section:
    """One closed airfoil polyline, upper then lower, sharing both end vertices."""

    stations: Tuple[float, ...]
    upper: Tuple[Tuple[float, float], ...]
    lower: Tuple[Tuple[float, float], ...]
    xi_t: float
    n_per_side: int

    @property
    def leading_edge(self) -> Tuple[float, float]:
        return self.upper[0]

    @property
    def trailing_edge(self) -> Tuple[float, float]:
        return self.upper[-1]

    @property
    def faces_total(self) -> int:
        """Airfoil faces: N intervals on each side."""
        return 2 * self.n_per_side

    def closed_loop(self) -> List[Tuple[float, float]]:
        """Lower TE -> LE -> upper TE, with ONE shared trailing-edge vertex.

        The loop starts at the trailing edge, runs forward along the lower
        surface to the leading edge, then back along the upper surface toward the
        trailing edge. The TE vertex appears ONCE, at index 0: the closing edge
        back to it is implied, which is what "one shared trailing-edge vertex"
        requires. The result therefore holds exactly ``2 * n_per_side`` points
        and defines the same number of airfoil faces.
        """
        lower_reversed = list(reversed(self.lower))          # TE -> LE
        upper_forward = list(self.upper[1:])                 # LE -> TE
        loop = lower_reversed + upper_forward
        assert loop[0] == loop[-1] == self.trailing_edge
        return loop[:-1]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "geometry_version": GEOMETRY_VERSION,
            "xi_t": self.xi_t,
            "xi_t_reference": XI_T_REFERENCE,
            "n_per_side": self.n_per_side,
            "airfoil_faces": self.faces_total,
            "leading_edge": list(self.leading_edge),
            "trailing_edge": list(self.trailing_edge),
            "max_thickness_over_chord": 2.0 * max(p[1] for p in self.upper),
            "spacing": "x_j/c = (1 - cos(pi j / N)) / 2",
            "definition": (
                "corrected TMR sharp trailing edge: x = xi/xi_T, "
                "y = +-0.6 f(xi)/xi_T"
            ),
        }


def section(n_per_side: int, *, xi_t: float = XI_T) -> Section:
    """Build the section at the frozen cosine stations. Exactly reflected."""
    stations = cosine_stations(n_per_side)
    upper = [(x, ordinate(x, xi_t=xi_t)) for x in stations]
    # Exact reflection: the same ordinate, negated. Not recomputed.
    lower = [(x, -y) for x, y in upper]
    # Pin the two exact vertices rather than trusting the polynomial at 0 and 1.
    upper[0] = (0.0, 0.0)
    lower[0] = (0.0, 0.0)
    upper[-1] = (1.0, 0.0)
    lower[-1] = (1.0, 0.0)
    return Section(tuple(stations), tuple(upper), tuple(lower), xi_t, int(n_per_side))


def boundary_error(sec: Section) -> Dict[str, Any]:
    """How far the discrete section sits from the analytic curve, per chord."""
    worst_ordinate = 0.0
    for x, y in sec.upper[1:-1]:
        worst_ordinate = max(worst_ordinate, abs(y - ordinate(x, xi_t=sec.xi_t)))
    te_closure = abs(f(sec.xi_t))
    return {
        "max_ordinate_error_over_chord": worst_ordinate,
        "trailing_edge_closure_residual": te_closure,
        "leading_edge_exact": sec.leading_edge == (0.0, 0.0),
        "trailing_edge_exact": sec.trailing_edge == (1.0, 0.0),
        "symmetry_max_error": max(
            abs(u[1] + l[1]) for u, l in zip(sec.upper, sec.lower)
        ),
        "budget": BOUNDARY_ERROR_BUDGET,
        "within_budget": (
            worst_ordinate <= BOUNDARY_ERROR_BUDGET
            and te_closure <= BOUNDARY_ERROR_BUDGET
        ),
    }
