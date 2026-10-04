#!/usr/bin/env python3
"""Deterministic stationarity / development gate for the surface-mounted cube.

The point of this gate is the case it rejects. The cube was run outside the
agent loop (2026-09-23/24); this gate was registered retrospectively on
2026-09-28. Over the assessment window t* = 59.98-79.98 of the archived run the
streamwise force is nearly constant (drift 0.075% of its mean; mean lateral
force 0.063% of the drag), while the mean |lateral force| over the second half
of the window is 2.10 times that over the first half, against a registered
limit of 1.25. A supplementary complete-cycle audit agrees: successive
complete-cycle lateral amplitudes grow by 209%, 137% and 113% (the growth rate
is declining but has not saturated), and between the t* = 60-70 and 70-80
blocks the mean drag changes by 0.04% while the RMS lateral force rises by
110%. A convergence test that watched only the drag would have accepted a run
whose flow field was still developing. This gate watches all three components
and the direction of growth.

THRESHOLDS ARE REGISTERED HERE, NOT TUNED TO THE DATA
-----------------------------------------------------
Each is scale-free and stated as a physical requirement:

  * FORCE_DRIFT_FRACTION_MAX -- across the assessment window, the least-squares
    trend of any force component, multiplied by the window length, may not exceed
    2% of the mean streamwise force. A force still moving by more than 2% of the
    primary load per window is not stationary.
  * LATERAL_GROWTH_RATIO_MAX -- the mean |lateral force| over the second half of
    the assessment window may not exceed 1.25x its value over the first half. A
    quantity whose magnitude is still growing is by definition not developed.
  * LATERAL_RELATIVE_MAX -- a converged symmetric configuration may not carry a
    mean lateral force above 5% of the streamwise force.

These bounds were registered on 2026-09-28, after the archived cube data existed
(2026-09-23/24), so the gate is retrospective. On the archived run the drag drift
is 0.075%, within the 2% bound, and the lateral growth ratio is 2.10 against the
1.25 bound (a factor of about 1.7); the verdict comes from the lateral growth.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

GATE_VERSION = "cube-stationarity/1.0.0"

#: Length of the window, in solver time units, over which stationarity is judged.
ASSESSMENT_WINDOW = 20.0

#: Registered thresholds. See the module docstring for the reasoning.
FORCE_DRIFT_FRACTION_MAX = 0.02
LATERAL_GROWTH_RATIO_MAX = 1.25
LATERAL_RELATIVE_MAX = 0.05

STATIONARY = "STATIONARY"
NOT_STATIONARY = "NOT_STATIONARY"
STILL_DEVELOPING = "STILL_DEVELOPING"
INSUFFICIENT_HISTORY = "INSUFFICIENT_HISTORY"


def _linear_trend(times: Sequence[float], values: Sequence[float]) -> float:
    n = len(values)
    if n < 2:
        return 0.0
    tm = sum(times) / n
    vm = sum(values) / n
    num = sum((t - tm) * (v - vm) for t, v in zip(times, values))
    den = sum((t - tm) ** 2 for t in times)
    return num / den if den else 0.0


def _mean(values: Sequence[float]) -> float:
    return sum(values) / len(values) if values else 0.0


@dataclass
class StationarityResult:
    """What the gate measured, what it required, and what it decided."""

    status: str
    window: Dict[str, float] = field(default_factory=dict)
    measured: Dict[str, Any] = field(default_factory=dict)
    thresholds: Dict[str, float] = field(default_factory=dict)
    failures: List[str] = field(default_factory=list)
    margins: Dict[str, float] = field(default_factory=dict)
    note: str = ""

    @property
    def passed(self) -> bool:
        return self.status == STATIONARY

    def to_dict(self) -> Dict[str, Any]:
        return {
            "gate_version": GATE_VERSION,
            "status": self.status,
            "passed": self.passed,
            "window": dict(self.window),
            "measured": dict(self.measured),
            "thresholds": dict(self.thresholds),
            "failures": list(self.failures),
            "margins_relative_to_threshold": dict(self.margins),
            "note": self.note,
        }


def assess(samples: Sequence[Dict[str, float]], *,
           window: float = ASSESSMENT_WINDOW,
           end_time: Optional[float] = None) -> StationarityResult:
    """Judge stationarity and development from a force history.

    ``samples`` are dicts with ``t``, ``fx``, ``fy``, ``fz``. The assessment uses
    the LAST ``window`` time units, because a transient run earns its verdict at
    the end, not on its average.
    """
    thresholds = {
        "force_drift_fraction_max": FORCE_DRIFT_FRACTION_MAX,
        "lateral_growth_ratio_max": LATERAL_GROWTH_RATIO_MAX,
        "lateral_relative_max": LATERAL_RELATIVE_MAX,
        "assessment_window": window,
    }
    if not samples:
        return StationarityResult(status=INSUFFICIENT_HISTORY,
                                  thresholds=thresholds,
                                  note="no force history was supplied")
    end = float(end_time if end_time is not None else max(s["t"] for s in samples))
    start = end - window
    chunk = [s for s in samples if start <= s["t"] <= end]
    if len(chunk) < 8 or (max(s["t"] for s in chunk) - min(s["t"] for s in chunk)) < 0.5 * window:
        return StationarityResult(
            status=INSUFFICIENT_HISTORY,
            window={"start": start, "end": end, "samples": len(chunk)},
            thresholds=thresholds,
            note=("the force history does not cover the assessment window; "
                  "stationarity is reported as unresolved rather than assumed"))

    times = [s["t"] for s in chunk]
    fx = [s["fx"] for s in chunk]
    fy = [s["fy"] for s in chunk]
    fz = [s["fz"] for s in chunk]
    reference = abs(_mean(fx)) or 1.0

    drift = {name: abs(_linear_trend(times, vals) * window) / reference
             for name, vals in (("fx", fx), ("fy", fy), ("fz", fz))}

    mid = start + 0.5 * window
    first = [abs(s["fz"]) for s in chunk if s["t"] < mid]
    second = [abs(s["fz"]) for s in chunk if s["t"] >= mid]
    growth = (_mean(second) / _mean(first)) if first and _mean(first) > 0 else math.inf

    lateral_relative = abs(_mean(fz)) / reference

    failures: List[str] = []
    for name, value in drift.items():
        if value > FORCE_DRIFT_FRACTION_MAX:
            failures.append(f"{name}_drift")
    if growth > LATERAL_GROWTH_RATIO_MAX:
        failures.append("lateral_force_growth")
    if lateral_relative > LATERAL_RELATIVE_MAX:
        failures.append("lateral_force_magnitude")

    status = STATIONARY
    if "lateral_force_growth" in failures:
        status = STILL_DEVELOPING
    elif failures:
        status = NOT_STATIONARY

    measured = {
        "mean_fx": _mean(fx), "mean_fy": _mean(fy), "mean_fz": _mean(fz),
        "drift_fraction": drift,
        "lateral_growth_ratio": growth,
        "lateral_relative_magnitude": lateral_relative,
        "mean_abs_fz_first_half": _mean(first),
        "mean_abs_fz_second_half": _mean(second),
        "samples": len(chunk),
    }
    margins = {
        "lateral_growth_ratio": growth / LATERAL_GROWTH_RATIO_MAX,
        "max_drift_fraction": max(drift.values()) / FORCE_DRIFT_FRACTION_MAX,
        "lateral_relative": lateral_relative / LATERAL_RELATIVE_MAX,
    }
    note = ("the streamwise force may look settled while a lateral mode grows; "
            "this gate fails on the growth, not on the drag")
    return StationarityResult(status=status,
                              window={"start": start, "end": end,
                                      "samples": len(chunk)},
                              measured=measured, thresholds=thresholds,
                              failures=failures, margins=margins, note=note)
