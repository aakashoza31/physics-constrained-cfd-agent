"""Deterministic scope gate for the parameterized nozzle pipeline.

The LLM interprets the engineering request. This gate decides, without the LLM,
whether the resulting case specification lies inside the declared registered
envelope. A rejection here is final: the orchestrator does not run CFD on a
specification this gate refuses, and the LLM cannot overrule it.

The envelope is the one declared by the frozen canonical reference and by
configs/nozzles/README.md:

  - internal axisymmetric converging-diverging nozzle, wedge representation
  - inviscid Euler, calorically perfect air, gamma = 1.4, R = 287 J/(kg K)
  - adiabatic slip walls
  - reservoir-style total-pressure / total-temperature inlet
  - pressure-free outlet whose supersonicity is verified after the fact
  - ambient pressure is external metadata and is never imposed at the outlet

The geometric and operating bounds below are transfer limits around the
registered anchor, not physical laws. They exist so that a request far outside
what was actually verified is refused rather than quietly simulated.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List

from src.pipeline.nozzle.spec import NozzleCaseSpec, VALIDATED_GAMMA, VALIDATED_R


# Declared transfer envelope around the canonical anchor.
BOUNDS: Dict[str, Any] = {
    "throat_radius_m": (0.020, 0.050),
    "inlet_radius_m": (0.030, 0.080),
    "exit_radius_m": (0.020, 0.070),
    "area_ratio": (1.02, 2.50),
    "total_pressure_pa": (1.2e5, 4.0e5),
    "total_temperature_k": (250.0, 400.0),
    "ambient_pressure_pa": (1.0e4, 1.0e5),
    "nozzle_pressure_ratio": (2.0, 20.0),
    "end_time_s": (1.0e-3, 2.0e-2),
    "scale": (0.5, 4.0),
    "wedge_angle_deg": (1.0, 10.0),
    "max_courant": (0.05, 0.5),
}


@dataclass
class ScopeGateResult:
    approved: bool
    case_id: str
    reasons: List[str] = field(default_factory=list)
    checks: Dict[str, bool] = field(default_factory=dict)
    measurements: Dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "approved": self.approved,
            "case_id": self.case_id,
            "decision": "IN_SCOPE" if self.approved else "REJECT_OUTSIDE_DOMAIN",
            "reasons": self.reasons,
            "checks": self.checks,
            "measurements": self.measurements,
            "authority": "deterministic",
        }


def _bounded(
    checks: Dict[str, bool],
    reasons: List[str],
    name: str,
    value: float,
    label: str = "",
) -> None:
    low, high = BOUNDS[name]
    ok = low <= float(value) <= high
    checks[f"{name}_in_range"] = ok

    if not ok:
        reasons.append(
            f"{label or name} = {value:g} is outside the declared registered "
            f"transfer envelope [{low:g}, {high:g}]."
        )


def evaluate_scope(spec: NozzleCaseSpec) -> ScopeGateResult:
    reasons: List[str] = []
    checks: Dict[str, bool] = {}

    # 1. Structural validity of the specification itself.
    try:
        spec.validate()
        checks["specification_valid"] = True
    except ValueError as exc:
        checks["specification_valid"] = False
        reasons.append(str(exc))

    # 2. Physics envelope.  (The check key keeps its archived name.)
    checks["gas_is_validated_air"] = (
        spec.gamma == VALIDATED_GAMMA
        and spec.gas_constant_j_per_kg_k == VALIDATED_R
    )

    if not checks["gas_is_validated_air"]:
        reasons.append(
            "Registered envelope is calorically perfect air with gamma = 1.4 and "
            "R = 287 J/(kg K)."
        )

    # 3. Outlet philosophy: ambient is interpretation metadata, never a
    #    computational boundary condition.
    checks["ambient_not_imposed_at_exit"] = not spec.ambient_imposed_at_exit

    if spec.ambient_imposed_at_exit:
        reasons.append(
            "The registered outlet is pressure-free. Imposing the ambient static "
            "pressure at the computational outlet changes the registered "
            "boundary-condition philosophy."
        )

    # 4. Converging-diverging topology.
    checks["converging_diverging"] = (
        spec.throat_radius_m < spec.inlet_radius_m
        and spec.throat_radius_m < spec.exit_radius_m
    )

    if not checks["converging_diverging"]:
        reasons.append(
            "Geometry is not a converging-diverging nozzle "
            "(throat must be the minimum radius)."
        )

    # 5. Quantitative transfer envelope.
    npr = (
        spec.total_pressure_pa / spec.ambient_pressure_pa
        if spec.ambient_pressure_pa
        else float("inf")
    )
    area_ratio = spec.area_ratio if spec.throat_radius_m else float("inf")

    _bounded(checks, reasons, "throat_radius_m", spec.throat_radius_m, "throat radius")
    _bounded(checks, reasons, "inlet_radius_m", spec.inlet_radius_m, "inlet radius")
    _bounded(checks, reasons, "exit_radius_m", spec.exit_radius_m, "exit radius")
    _bounded(checks, reasons, "area_ratio", area_ratio, "exit/throat area ratio")
    _bounded(
        checks, reasons, "total_pressure_pa", spec.total_pressure_pa, "reservoir pressure"
    )
    _bounded(
        checks,
        reasons,
        "total_temperature_k",
        spec.total_temperature_k,
        "reservoir temperature",
    )
    _bounded(
        checks, reasons, "ambient_pressure_pa", spec.ambient_pressure_pa, "ambient pressure"
    )
    _bounded(checks, reasons, "nozzle_pressure_ratio", npr, "nozzle pressure ratio")
    _bounded(checks, reasons, "end_time_s", spec.end_time_s, "integration horizon")
    _bounded(checks, reasons, "scale", spec.scale, "mesh scale")
    _bounded(checks, reasons, "wedge_angle_deg", spec.wedge_angle_deg, "wedge angle")
    _bounded(checks, reasons, "max_courant", spec.max_courant, "maximum Courant number")

    # 6. The supersonic branch must exist for this pressure ratio, otherwise the
    #    declared choked/supersonic outlet regime is not the physical answer and
    #    the pressure-free outlet is not admissible.
    try:
        p_exit_supersonic, _, _ = spec.quasi1d_state(spec.exit_radius_m, True)
        supersonic_branch_possible = spec.ambient_pressure_pa < p_exit_supersonic
    except (ZeroDivisionError, ValueError, OverflowError) as exc:
        p_exit_supersonic = float("nan")
        supersonic_branch_possible = False
        reasons.append(
            f"Quasi-1D exit state could not be evaluated for this geometry: {exc}"
        )

    checks["supersonic_outlet_branch_available"] = bool(supersonic_branch_possible)

    if not supersonic_branch_possible:
        reasons.append(
            f"Quasi-1D fully supersonic exit static pressure is "
            f"{p_exit_supersonic:.0f} Pa, at or below the {spec.ambient_pressure_pa:.0f} Pa "
            "ambient. The declared underexpanded/supersonic outlet regime, and "
            "therefore the pressure-free outlet, is not justified for this request."
        )

    measurements = {
        "area_ratio": area_ratio,
        "nozzle_pressure_ratio": npr,
        "quasi1d_exit_pressure_pa": p_exit_supersonic,
        "throat_to_inlet_radius_ratio": (
            spec.throat_radius_m / spec.inlet_radius_m
            if spec.inlet_radius_m
            else float("nan")
        ),
        "cells": float(sum(spec.axial_cells) * spec.radial_cells),
        "length_m": spec.length_m,
    }

    return ScopeGateResult(
        approved=all(checks.values()),
        case_id=spec.case_id,
        reasons=reasons,
        checks=checks,
        measurements=measurements,
    )
