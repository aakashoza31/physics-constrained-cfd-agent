#!/usr/bin/env python3
"""The FROZEN F3 mesh hierarchy: coarse / medium / fine.

Every number here comes from the approved recipe. Two things are SOLVED rather
than transcribed, because transcribing them would let a rounding error into the
mesh:

  * the wall-normal growth ratio q, from  h1 (q^N - 1)/(q - 1) = envelope
  * the realized layer heights and envelope that q produces

Nothing in this module may be changed to hit a forecast cell count. The counts
are forecasts; the recipe is the specification.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

HIERARCHY_VERSION = "f3-gmsh-hierarchy/2.0.0"
#: Surface-distribution recipe version. v1 is archived, not deleted.
RECIPE_VERSION = "v2"

COARSE, MEDIUM, FINE = "coarse", "medium", "fine"
LEVELS = (COARSE, MEDIUM, FINE)

#: Frozen farfield box, identical on every level. Never shrunk for a coarse mesh.
X_MIN, X_MAX = -500.0, 501.0
Y_MIN, Y_MAX = -500.0, 500.0

#: Frozen span of the single spanwise cell, in chords. Used in force normalisation.
SPAN = 0.01

#: Frozen boundary-layer envelope.
BL_ENVELOPE = 0.02

#: Hard ceiling on the wall-normal growth ratio.
MAX_GROWTH_RATIO = 1.20

#: Deterministic Gmsh seed and algorithm settings, identical on every level.
GMSH_SEED = 20260927
GMSH_ALGORITHM_2D = 6           # Frontal-Delaunay
GMSH_RECOMBINE_ALGORITHM = 1    # Blossom, used only inside the BL field
GMSH_SMOOTHING_STEPS = 5
GMSH_OPTIMIZE_NETGEN = False    # must not move airfoil nodes or wreck the layers


@dataclass(frozen=True)
class Level:
    """One frozen level of the hierarchy."""

    name: str
    refinement: float           # r
    n_per_side: int             # surface intervals per side
    first_layer: float          # h1 / c
    nominal_layers: int
    fan_sectors: int
    outer_multiplier: float
    forecast_cells: Tuple[int, int]
    envelope: float = BL_ENVELOPE

    @property
    def airfoil_faces(self) -> int:
        """Airfoil faces under the ACTIVE recipe (v2): 2 (n_body + n_TE).

        Under v1 this was 2N. The v2 partition supersedes that count, which is
        why the number is derived from the surface plan rather than from N.
        """
        return 2 * (body_intervals(self) + te_progression(self)["te_intervals"])

    def to_dict(self) -> Dict[str, Any]:
        return {
            "level": self.name,
            "refinement_factor": self.refinement,
            "cosine_parameter_n": self.n_per_side,
        "surface_intervals_per_side": self.airfoil_faces // 2,
            "airfoil_faces": self.airfoil_faces,
            "first_layer_over_chord": self.first_layer,
            "nominal_normal_layers": self.nominal_layers,
            "bl_envelope_over_chord": self.envelope,
            "te_fan_sectors": self.fan_sectors,
            "outer_size_multiplier": self.outer_multiplier,
            "forecast_cells": list(self.forecast_cells),
            "forecast_note": "a planning forecast, never a target to degrade the recipe for",
        }


HIERARCHY: Dict[str, Level] = {
    COARSE: Level(COARSE, 1.00, 256, 2.0e-6, 48, 24, 1.0, (40_000, 60_000)),
    MEDIUM: Level(MEDIUM, 1.50, 384, 1.3333333e-6, 72, 36, 2.0 / 3.0,
                  (90_000, 130_000)),
    FINE: Level(FINE, 2.25, 576, 8.8888889e-7, 108, 54, 4.0 / 9.0,
                (200_000, 290_000)),
}


# ----------------------------------------------------------------------
# RECIPE v2: near-trailing-edge surface distribution.
#
# ONLY the surface distribution changes. The farfield, the wake sizing, the wall
# layer heights and counts, the wall-normal progression, the 0.02c envelope, the
# fan sector counts, the spanwise extrusion, the Gmsh settings and every mesh
# quality threshold are exactly as in v1.
#
# Each side is partitioned at x_T/c = 0.98:
#   * LE -> x_T : the TRUNCATED cosine law, so the body spacing keeps its v1
#     character;
#   * x_T -> TE : a geometric progression in surface ARC LENGTH, started at the
#     trailing edge at a prescribed first interval and solved to terminate
#     EXACTLY at x_T. No residual sliver interval is appended.
#
# The prescribed first interval is the v1 FAN circumferential spacing at the
# trailing edge, which is what v1's failure localised on: v1 put a 3.8e-5
# surface interval next to a 2.4e-7 fan interval, a ratio of 159.57 at every
# level. Matching them is the whole point of v2.
# ----------------------------------------------------------------------

#: Partition station, as a fraction of chord.
X_PARTITION = 0.98

#: theta_T = acos(1 - 2 x_T). The body zone is the cosine law truncated here.
THETA_T = math.acos(1.0 - 2.0 * X_PARTITION)

#: First surface-arc interval upstream of the TE on the COARSE level, in chords.
#: This is v1's coarse fan circumferential spacing.
DELTA_TE_BASE = 2.3831e-7

#: Growth-ratio ceiling of the TE progression on the coarse level. Refined levels
#: take q_max^(1/r), so the progression tightens as the mesh refines.
Q_MAX_BASE = 1.15

#: Frozen body-interval counts per side, from round(N * theta_T / pi). Recomputed
#: below and checked against these, so a change in N or x_T cannot pass silently.
FROZEN_BODY_INTERVALS: Dict[str, int] = {COARSE: 233, MEDIUM: 349, FINE: 524}

#: Frozen prescribed first TE intervals, from DELTA_TE_BASE / r^2.
FROZEN_DELTA_TE: Dict[str, float] = {
    COARSE: 2.3831e-7, MEDIUM: 1.0591556e-7, FINE: 4.7073580e-8,
}


def body_intervals(lv: "Level") -> int:
    """round(N theta_T / pi), verified against the frozen count."""
    computed = int(round(lv.n_per_side * THETA_T / math.pi))
    frozen = FROZEN_BODY_INTERVALS[lv.name]
    if computed != frozen:
        raise ValueError(
            f"{lv.name}: round(N theta_T / pi) = {computed}, but the frozen count "
            f"is {frozen}. The hierarchy is versioned, not silently adjusted."
        )
    return computed


def delta_te(lv: "Level") -> float:
    """Prescribed first TE surface-arc interval: DELTA_TE_BASE / r^2.

    The r^-2 scaling is prescribed and is NOT r^-1: the surface interval must
    keep pace with the fan spacing, which carries h1/r against a sector count
    that also grows with r.
    """
    computed = DELTA_TE_BASE / (lv.refinement ** 2)
    frozen = FROZEN_DELTA_TE[lv.name]
    # The frozen entries are the formula's value written to eight significant
    # figures, so they are checked at that precision and the EXACT quotient is
    # what gets prescribed. Rounding the recipe to its own printed form would be
    # a silent change to the mesh.
    if abs(computed - frozen) > 1.0e-7 * frozen:
        raise ValueError(
            f"{lv.name}: DELTA_TE_BASE / r^2 = {computed!r} disagrees with the "
            f"frozen {frozen!r} beyond its printed precision"
        )
    return computed


def te_growth_limit(lv: "Level") -> float:
    """q_max = 1.15^(1/r)."""
    return Q_MAX_BASE ** (1.0 / lv.refinement)


def te_progression(lv: "Level") -> Dict[str, Any]:
    """The solved TE geometric progression for one level.

    n_TE comes from the ceiling formula, then q is SOLVED so the progression
    lands exactly on the partition. Both are computed, never transcribed.
    """
    from src.pipeline.airfoil import geometry as _geometry

    first = delta_te(lv)
    q_max = te_growth_limit(lv)
    arc = _geometry.arc_length(X_PARTITION, 1.0)
    n_te = math.ceil(math.log(1.0 + (q_max - 1.0) * arc / first) / math.log(q_max))
    q = _geometry.geometric_progression_ratio(arc, first, n_te, q_max=q_max)
    total = first * (q ** n_te - 1.0) / (q - 1.0)
    return {
        "arc_length_partition_to_te": arc,
        "first_interval_prescribed": first,
        "growth_ratio_max": q_max,
        "te_intervals": int(n_te),
        "growth_ratio": q,
        "series_sum": total,
        "series_residual": total - arc,
        "terminates_at_partition": abs(total - arc) <= 1.0e-12 * arc,
        "last_interval": first * q ** (n_te - 1),
    }


def surface_plan(lv: "Level") -> Dict[str, Any]:
    """The complete v2 surface distribution for one level, per side."""
    n_body = body_intervals(lv)
    prog = te_progression(lv)
    n_te = prog["te_intervals"]
    return {
        "recipe_version": RECIPE_VERSION,
        "x_partition": X_PARTITION,
        "theta_t_rad": THETA_T,
        "cosine_parameter_n": lv.n_per_side,
        "body_intervals": n_body,
        "te_intervals": n_te,
        "intervals_per_side": n_body + n_te,
        "airfoil_faces": 2 * (n_body + n_te),
        "body_law": "x_j/c = (1 - cos(j theta_T / n_body)) / 2, j = 0..n_body",
        "te_law": "ds_j = delta_TE q^(j-1) in surface arc length, from the TE",
        **prog,
    }


# ----------------------------------------------------------------------
def solve_growth_ratio(
    first_layer: float, n_layers: int, envelope: float = BL_ENVELOPE,
) -> float:
    """The unique q > 1 with h1 (q^N - 1)/(q - 1) = envelope, by bisection.

    Bisection on a monotone function, halved until the ends are adjacent doubles:
    bracketed, reproducible, and it cannot wander off the root.
    """
    if first_layer <= 0.0 or n_layers < 2 or envelope <= 0.0:
        raise ValueError("first_layer, n_layers and envelope must be positive")
    if first_layer * n_layers >= envelope:
        raise ValueError(
            f"a uniform stack of {n_layers} layers of {first_layer} already "
            f"exceeds the envelope {envelope}; q would have to be <= 1"
        )

    def total(q: float) -> float:
        return first_layer * (q ** n_layers - 1.0) / (q - 1.0)

    lo, hi = 1.0 + 1.0e-12, 2.0
    while total(hi) < envelope:
        hi *= 2.0
        if hi > 1.0e3:  # pragma: no cover - defensive
            raise RuntimeError("no growth ratio reaches the envelope")
    for _ in range(300):
        mid = 0.5 * (lo + hi)
        if mid == lo or mid == hi:
            break
        if total(mid) < envelope:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


@dataclass(frozen=True)
class LayerStack:
    """The realized wall-normal progression for one level."""

    level: str
    first_layer: float
    nominal_layers: int
    growth_ratio: float
    heights: Tuple[float, ...]
    cumulative: Tuple[float, ...]
    envelope_target: float

    @property
    def realized_layers(self) -> int:
        return len(self.heights)

    @property
    def realized_envelope(self) -> float:
        return self.cumulative[-1] if self.cumulative else 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "level": self.level,
            "first_layer_over_chord": self.first_layer,
            "nominal_layers": self.nominal_layers,
            "realized_layers": self.realized_layers,
            "growth_ratio": self.growth_ratio,
            "growth_ratio_limit": MAX_GROWTH_RATIO,
            "growth_ratio_within_limit": self.growth_ratio < MAX_GROWTH_RATIO,
            "envelope_target_over_chord": self.envelope_target,
            "realized_envelope_over_chord": self.realized_envelope,
            "envelope_relative_error": abs(
                self.realized_envelope - self.envelope_target
            ) / self.envelope_target,
            "layer_deviation_from_nominal": self.realized_layers - self.nominal_layers,
            "last_layer_height": self.heights[-1] if self.heights else None,
            "progression": "geometric",
            "not_a_beta_law": True,
        }


def layer_stack(level: Level) -> LayerStack:
    """Solve q, then build the geometric stack it implies."""
    q = solve_growth_ratio(level.first_layer, level.nominal_layers, level.envelope)
    heights: List[float] = []
    cumulative: List[float] = []
    total = 0.0
    for n in range(level.nominal_layers):
        h = level.first_layer * q ** n
        total += h
        heights.append(h)
        cumulative.append(total)
    return LayerStack(
        level=level.name, first_layer=level.first_layer,
        nominal_layers=level.nominal_layers, growth_ratio=q,
        heights=tuple(heights), cumulative=tuple(cumulative),
        envelope_target=level.envelope,
    )


# ----------------------------------------------------------------------
# wake and outer sizing -- exactly the frozen formulae
# ----------------------------------------------------------------------
WAKE_X_MIN, WAKE_X_MAX = 1.0, 11.0


def wake_half_width(x: float) -> float:
    """|y|/c <= 0.05 + 0.20 (x/c - 1) inside the wake core."""
    return 0.05 + 0.20 * (x - 1.0)


def distance_to_wake_region(x: float, y: float) -> float:
    """Euclidean distance to the closed wake region. Zero inside it."""
    xc = min(max(x, WAKE_X_MIN), WAKE_X_MAX)
    half = wake_half_width(xc)
    dx = 0.0 if WAKE_X_MIN <= x <= WAKE_X_MAX else (
        WAKE_X_MIN - x if x < WAKE_X_MIN else x - WAKE_X_MAX
    )
    dy = max(0.0, abs(y) - half)
    return math.hypot(dx, dy)


def background_size(distance_to_airfoil: float) -> float:
    """h_b = min(50c, 0.002c + 0.12 d_a)."""
    return min(50.0, 0.002 + 0.12 * float(distance_to_airfoil))


def wake_size(x: float, y: float) -> float:
    """h_w = c(0.006 + 0.015 s) + 0.12 d_W, with s = clip(x/c - 1, 0, 10)."""
    s = min(max(x - 1.0, 0.0), 10.0)
    return (0.006 + 0.015 * s) + 0.12 * distance_to_wake_region(x, y)


def target_size(x: float, y: float, distance_to_airfoil: float,
                refinement: float) -> float:
    """h_l = min(h_b, h_w) / r, outside the wall layers."""
    return min(background_size(distance_to_airfoil), wake_size(x, y)) / refinement


def te_fan_spacing(lv: Level) -> Dict[str, float]:
    """Trailing-edge spacing DIAGNOSTIC. No threshold, no verdict, no gate.

    At the sharp trailing edge two spacings meet on the same cell face:

      * the wall-parallel surface spacing of the first interval, set by the
        frozen cosine distribution and therefore ~ (pi/n)^2 / 4;
      * the circumferential spacing of the boundary-layer FAN, which is the
        exterior turn angle times the first-layer height, over the sector count.

    Both scale with the refinement factor in the same way, so their RATIO is
    invariant across the hierarchy by construction. That is why refinement cannot
    move a metric that this mismatch drives, and it is reported so that a failure
    localised at the trailing edge is diagnosable rather than merely observed.

    Reported, never enforced: nothing here may become an acceptance criterion.
    """
    from src.pipeline.airfoil import geometry as _geometry

    loop = _geometry.section(lv.n_per_side).closed_loop()
    te, first = loop[0], loop[1]
    surface_dx = math.hypot(first[0] - te[0], first[1] - te[1])
    # Trailing-edge wedge half-angle from the analytic section's own slope.
    h = 1.0e-7
    slope = (_geometry.ordinate(1.0) - _geometry.ordinate(1.0 - h)) / h
    wedge = 2.0 * math.atan(abs(slope))
    turn = 2.0 * math.pi - (math.pi + wedge)
    fan_arc = turn * lv.first_layer / lv.fan_sectors
    return {
        "surface_spacing_adjacent_to_te": surface_dx,
        "fan_circumferential_spacing": fan_arc,
        "spacing_ratio": surface_dx / fan_arc if fan_arc > 0.0 else float("inf"),
        "te_wedge_angle_deg": math.degrees(wedge),
        "fan_exterior_turn_deg": math.degrees(turn),
        "diagnostic_only": True,
        "note": ("level-invariant by construction: both spacings carry the same "
                 "refinement factor, so refinement cannot change this ratio"),
    }


def level(name: str) -> Level:
    if name not in HIERARCHY:
        raise KeyError(f"{name!r} is not a frozen level; expected {LEVELS}")
    return HIERARCHY[name]


def hierarchy_summary() -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "hierarchy_version": HIERARCHY_VERSION,
        "levels": {},
        "farfield": {"x": [X_MIN, X_MAX], "y": [Y_MIN, Y_MAX],
                     "identical_on_all_levels": True},
        "span": SPAN,
        "gmsh": {
            "seed": GMSH_SEED, "algorithm_2d": GMSH_ALGORITHM_2D,
            "recombine_algorithm": GMSH_RECOMBINE_ALGORITHM,
            "smoothing_steps": GMSH_SMOOTHING_STEPS,
            "optimize_netgen": GMSH_OPTIMIZE_NETGEN,
            "identical_on_all_levels": True,
        },
    }
    for name in LEVELS:
        lv = level(name)
        out["levels"][name] = {
            **lv.to_dict(),
            "layer_stack": layer_stack(lv).to_dict(),
            "te_spacing_diagnostic": te_fan_spacing(lv),
            "surface_plan_v2": surface_plan(lv),
        }
    return out
