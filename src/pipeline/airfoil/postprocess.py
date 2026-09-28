#!/usr/bin/env python3
"""Force, Cp and y+ post-processing. Pure arithmetic on collected evidence.

Nothing here reads a reference dataset or decides whether a number is acceptable:
that belongs to validate.py. This module only turns raw surface and force data
into the normalised quantities the acceptance contract is written against.
"""
from __future__ import annotations

import math
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from src.families.airfoil.spec import RHO, dynamic_reference, lift_drag_directions

UPPER = "upper"
LOWER = "lower"


def normalise_forces(
    force_xyz: Sequence[float],
    *,
    alpha_deg: float,
    span_m: float,
    u_inf: float = 1.0,
    chord_m: float = 1.0,
    rho: float = RHO,
) -> Dict[str, float]:
    """C_L, C_D = F / (0.5 rho U^2 c b), resolved along the FREESTREAM.

    b is the actual span of the one-layer extruded mesh, not a nominal 1 m.
    """
    reference = 0.5 * rho * u_inf * u_inf * chord_m * float(span_m)
    if reference <= 0.0:
        raise ValueError("force reference 0.5*rho*U^2*c*b must be positive")
    dirs = lift_drag_directions(alpha_deg)
    fx, fy, fz = (float(v) for v in force_xyz)

    def project(d: Tuple[float, float, float]) -> float:
        return fx * d[0] + fy * d[1] + fz * d[2]

    return {
        "CD": project(dirs["drag"]) / reference,
        "CL": project(dirs["lift"]) / reference,
        "force_reference": reference,
        "span_m": float(span_m),
        "alpha_deg": float(alpha_deg),
        "drag_direction": list(dirs["drag"]),
        "lift_direction": list(dirs["lift"]),
    }


def surface_cp(
    points: Iterable[Dict[str, float]],
    *,
    u_inf: float = 1.0,
    rho: float = RHO,
    p_reference: float = 0.0,
) -> Dict[str, List[Tuple[float, float]]]:
    """Split surface pressure into upper and lower Cp(x/c), sorted by x/c.

    Each input point needs ``x_over_c``, ``p`` and ``y`` (the sign of y assigns
    the surface). Cp = (p - p_ref) / (0.5 rho U^2); for an incompressible solver
    p is kinematic pressure, so rho is applied here once and only here.
    """
    q = 0.5 * u_inf * u_inf  # kinematic dynamic pressure
    out: Dict[str, List[Tuple[float, float]]] = {UPPER: [], LOWER: []}
    for point in points:
        x = float(point["x_over_c"])
        p = float(point["p"])
        y = float(point.get("y", 0.0))
        cp = (p - p_reference) / q
        out[UPPER if y >= 0.0 else LOWER].append((x, cp))
    for values in out.values():
        values.sort()
    return out


def interpolate(curve: Sequence[Tuple[float, float]], x: float) -> Optional[float]:
    """Linear interpolation. Returns None outside the curve, never extrapolates."""
    if len(curve) < 2:
        return None
    if x < curve[0][0] or x > curve[-1][0]:
        return None
    for n in range(len(curve) - 1):
        x0, y0 = curve[n]
        x1, y1 = curve[n + 1]
        if x0 <= x <= x1:
            if x1 == x0:
                return y0
            t = (x - x0) / (x1 - x0)
            return y0 + t * (y1 - y0)
    return None


def cp_rmse(
    computed: Sequence[Tuple[float, float]],
    reference: Sequence[Tuple[float, float]],
) -> Dict[str, Any]:
    """Absolute Cp RMSE at every supplied reference point.

    ABSOLUTE, never relative: a percentage error is meaningless near Cp = 0.
    Every reference point must be usable; points the computed curve cannot cover
    are reported as unmatched rather than silently dropped.
    """
    residuals: List[float] = []
    unmatched: List[float] = []
    for x, cp_ref in reference:
        cp_num = interpolate(computed, x)
        if cp_num is None:
            unmatched.append(x)
            continue
        residuals.append(cp_num - cp_ref)
    rmse = (
        math.sqrt(sum(r * r for r in residuals) / len(residuals))
        if residuals else None
    )
    return {
        "rmse": rmse,
        "n_reference_points": len(list(reference)),
        "n_matched": len(residuals),
        "unmatched_x_over_c": unmatched,
        "max_abs_residual": max((abs(r) for r in residuals), default=None),
        "metric": "absolute Cp RMSE over all supplied reference points",
    }


def yplus_statistics(
    samples: Sequence[Dict[str, float]],
    *,
    threshold: float = 1.0,
) -> Dict[str, Any]:
    """Surface-length-weighted y+ statistics and exceedance regions.

    Weighting is by surface length, not by face count, because the acceptance
    contract is written against surface length.
    """
    if not samples:
        return {
            "available": False,
            "reason": "no y+ samples were collected",
            "fraction_below_threshold": None,
        }
    total = 0.0
    below = 0.0
    per_surface: Dict[str, Dict[str, float]] = {}
    exceedances: List[Dict[str, float]] = []
    max_yplus = -math.inf
    max_at = None

    for sample in samples:
        length = float(sample.get("length", 0.0))
        yplus = float(sample["yplus"])
        x = float(sample.get("x_over_c", float("nan")))
        surface = str(sample.get("surface") or "unknown")
        total += length
        stats = per_surface.setdefault(
            surface, {"length": 0.0, "below": 0.0, "max_yplus": -math.inf}
        )
        stats["length"] += length
        if yplus <= threshold:
            below += length
            stats["below"] += length
        else:
            exceedances.append(
                {"x_over_c": x, "surface": surface, "yplus": yplus, "length": length}
            )
        if yplus > stats["max_yplus"]:
            stats["max_yplus"] = yplus
        if yplus > max_yplus:
            max_yplus, max_at = yplus, {"x_over_c": x, "surface": surface}

    for stats in per_surface.values():
        stats["fraction_below_threshold"] = (
            stats["below"] / stats["length"] if stats["length"] > 0 else 0.0
        )

    exceedances.sort(key=lambda e: -e["yplus"])
    return {
        "available": True,
        "threshold": threshold,
        "surface_length": total,
        "fraction_below_threshold": (below / total) if total > 0 else 0.0,
        "max_yplus": max_yplus,
        "max_yplus_location": max_at,
        "by_surface": per_surface,
        "exceedance_regions": exceedances,
        "n_exceedances": len(exceedances),
        "weighting": "surface length",
    }


def series_statistics(values: Sequence[float]) -> Dict[str, Any]:
    """Range, relative variation and finiteness of a monitored series."""
    clean = [float(v) for v in values]
    if not clean:
        return {"available": False, "n": 0}
    finite = [v for v in clean if math.isfinite(v)]
    lo, hi = (min(finite), max(finite)) if finite else (None, None)
    mean = (sum(finite) / len(finite)) if finite else None
    scale = abs(mean) if mean not in (None, 0.0) else None
    return {
        "available": True,
        "n": len(clean),
        "min": lo,
        "max": hi,
        "mean": mean,
        "range": (hi - lo) if finite else None,
        "relative_variation": ((hi - lo) / scale) if (finite and scale) else None,
        "all_finite": len(finite) == len(clean),
    }
