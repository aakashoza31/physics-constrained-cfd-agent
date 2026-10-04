#!/usr/bin/env python3
"""Parameterized nozzle case specification.

PROVENANCE
----------
This module is a parameterized derivative of the frozen scientific authority in
``validation/canonical_reference/``.  The authority is NOT modified.

The quasi-1D state function reproduces ``validation/canonical_reference/build.py``
``state()`` exactly, with the hard-coded throat radius, reservoir pressure and
reservoir temperature replaced by specification fields.  The gamma-dependent
numeric forms are retained verbatim, and the specification therefore REFUSES any
gas other than the registered calorically-perfect-air envelope
(gamma = 1.4, R = 287 J/(kg K)).  Generalizing gamma would change the registered
numerical path and is deliberately outside the scope of this module.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, asdict, field
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Sequence, Tuple


# The registered physics envelope. These are not free parameters.
VALIDATED_GAMMA = 1.4
VALIDATED_R = 287.0

# Canonical structured-mesh resolution ladder (segment-wise axial cell counts and
# radial cell count at scale = 1). Identical to validation/canonical_reference.
CANONICAL_AXIAL_CELLS: Tuple[int, ...] = (20, 40, 4, 48, 20)
CANONICAL_RADIAL_CELLS = 16


def num(value: Any) -> str:
    """Format a number the way the canonical dictionaries are written.

    Integral floats print without a trailing ``.0`` so that a specification
    carrying ``200000.0`` reproduces the canonical literal ``200000``.
    """
    if isinstance(value, int):
        return str(value)

    f = float(value)

    if f == int(f) and abs(f) < 1e16:
        return str(int(f))

    return repr(f)


@dataclass(frozen=True)
class NozzleCaseSpec:
    """Complete, self-contained description of one nozzle CFD case."""

    case_id: str

    inlet_radius_m: float
    throat_radius_m: float
    exit_radius_m: float

    inlet_straight_m: float
    converging_m: float
    throat_m: float
    diverging_m: float
    outlet_straight_m: float

    total_pressure_pa: float
    total_temperature_k: float

    ambient_pressure_pa: float

    description: str = ""

    ambient_imposed_at_exit: bool = False

    gamma: float = VALIDATED_GAMMA
    gas_constant_j_per_kg_k: float = VALIDATED_R

    # Numerical controls (registered recipe defaults).
    scale: float = 1.0
    wedge_angle_deg: float = 5.0
    max_courant: float = 0.4
    end_time_s: float = 0.006
    startup_perturbation: float = 0.0

    base_axial_cells: Tuple[int, ...] = CANONICAL_AXIAL_CELLS
    base_radial_cells: int = CANONICAL_RADIAL_CELLS

    numerics_recipe: str = "validated_reference_v1"
    validation_profile: str = "validated_reference_v1"

    # ------------------------------------------------------------------
    # Validation of the declared envelope
    # ------------------------------------------------------------------

    def validate(self) -> None:
        if self.gamma != VALIDATED_GAMMA:
            raise ValueError(
                "Registered envelope is calorically perfect air with "
                f"gamma = {VALIDATED_GAMMA}; got {self.gamma}."
            )

        if self.gas_constant_j_per_kg_k != VALIDATED_R:
            raise ValueError(
                "Registered envelope is calorically perfect air with "
                f"R = {VALIDATED_R} J/(kg K); got "
                f"{self.gas_constant_j_per_kg_k}."
            )

        positive = {
            "inlet_radius_m": self.inlet_radius_m,
            "throat_radius_m": self.throat_radius_m,
            "exit_radius_m": self.exit_radius_m,
            "inlet_straight_m": self.inlet_straight_m,
            "converging_m": self.converging_m,
            "throat_m": self.throat_m,
            "diverging_m": self.diverging_m,
            "outlet_straight_m": self.outlet_straight_m,
            "total_pressure_pa": self.total_pressure_pa,
            "total_temperature_k": self.total_temperature_k,
            "ambient_pressure_pa": self.ambient_pressure_pa,
            "end_time_s": self.end_time_s,
            "scale": self.scale,
            "wedge_angle_deg": self.wedge_angle_deg,
            "max_courant": self.max_courant,
        }

        for name, value in positive.items():
            if not (float(value) > 0.0):
                raise ValueError(f"{name} must be positive, got {value}.")

        if self.throat_radius_m >= self.inlet_radius_m:
            raise ValueError(
                "throat_radius_m must be smaller than inlet_radius_m."
            )

        if self.throat_radius_m >= self.exit_radius_m:
            raise ValueError(
                "throat_radius_m must be smaller than exit_radius_m "
                "(a converging-diverging nozzle is required)."
            )

        if self.ambient_pressure_pa >= self.total_pressure_pa:
            raise ValueError(
                "ambient_pressure_pa must be below total_pressure_pa."
            )

        if self.ambient_imposed_at_exit:
            raise ValueError(
                "The registered outlet is pressure-free and verified by computed "
                "supersonicity. Ambient pressure must not be imposed at the "
                "computational outlet."
            )

        if len(self.base_axial_cells) != 5:
            raise ValueError(
                "base_axial_cells must supply one count per nozzle segment."
            )

    # ------------------------------------------------------------------
    # Derived geometry
    # ------------------------------------------------------------------

    @property
    def segment_lengths_m(self) -> List[float]:
        return [
            self.inlet_straight_m,
            self.converging_m,
            self.throat_m,
            self.diverging_m,
            self.outlet_straight_m,
        ]

    @property
    def axial_breakpoints_m(self) -> List[float]:
        """Cumulative axial breakpoints.

        Accumulated in Decimal so that 0.05 + 0.10 is exactly 0.15 and the
        canonical breakpoint list [0, .05, .15, .16, .28, .33] is reproduced
        bit-for-bit rather than drifting to 0.15000000000000002.
        """
        total = Decimal("0")
        points = [0.0]

        for length in self.segment_lengths_m:
            total += Decimal(repr(float(length)))
            points.append(float(total))

        return points

    @property
    def radii_m(self) -> List[float]:
        return [
            self.inlet_radius_m,
            self.inlet_radius_m,
            self.throat_radius_m,
            self.throat_radius_m,
            self.exit_radius_m,
            self.exit_radius_m,
        ]

    @property
    def throat_start_m(self) -> float:
        return self.axial_breakpoints_m[2]

    @property
    def throat_end_m(self) -> float:
        return self.axial_breakpoints_m[3]

    @property
    def length_m(self) -> float:
        return self.axial_breakpoints_m[-1]

    @property
    def downstream_screen_x_m(self) -> float:
        """Start of the downstream normal-shock regime screen.

        Canonical value 0.17 m = throat exit (0.16 m) + one throat length
        (0.01 m) downstream.
        """
        return float(
            Decimal(repr(self.throat_end_m)) + Decimal(repr(float(self.throat_m)))
        )

    @property
    def area_ratio(self) -> float:
        return (self.exit_radius_m / self.throat_radius_m) ** 2

    @property
    def axial_cells(self) -> List[int]:
        return [round(n * self.scale) for n in self.base_axial_cells]

    @property
    def radial_cells(self) -> int:
        return round(self.base_radial_cells * self.scale)

    # ------------------------------------------------------------------
    # Quasi-1D thermodynamics (transcribed from the frozen authority)
    # ------------------------------------------------------------------

    def quasi1d_state(self, r: float, supersonic: bool):
        """Quasi-1D isentropic state at local radius ``r``.

        Transcription of validation/canonical_reference/build.py::state with the
        throat radius, reservoir pressure and reservoir temperature substituted.
        The floating-point operation sequence is preserved so that the canonical
        specification reproduces the canonical numbers bit-for-bit.
        """
        rt = self.throat_radius_m
        p0 = self.total_pressure_pa
        t0 = self.total_temperature_k

        ar = (r / rt) ** 2
        lo, hi = (1.0, 5.0) if supersonic else (1e-8, 1.0)

        for _ in range(90):
            m = (lo + hi) / 2
            a = ((5 + m * m) / 6) ** 3 / m

            if (a < ar) == supersonic:
                lo = m
            else:
                hi = m

        m = (lo + hi) / 2
        t = t0 / (1 + .2 * m * m)
        p = p0 * (t / t0) ** 3.5

        return p, t, m * math.sqrt(1.4 * 287 * t)

    def choked_mass_flow_kg_s(self) -> float:
        """Quasi-1D choked mass flow. Post-hoc comparison only."""
        return (
            math.pi
            * self.throat_radius_m ** 2
            * self.total_pressure_pa
            / math.sqrt(self.total_temperature_k)
            * math.sqrt(1.4 / 287)
            * (2 / 2.4) ** 3
        )

    def expected_initial_pressure_bounds(self) -> Tuple[float, float]:
        """Physically anchored bounds for the initialized pressure field.

        The canonical initializer asserted the absolute literals
        ``p_min < 60000`` and ``p_max > 190000``.  Those encode the canonical
        reservoir pressure and exit area ratio and silently become meaningless
        (Case C sits 0.8% from the 60 kPa literal) when either changes.

        This replaces them with the quasi-1D states the initializer is actually
        constructing: the field must reach down to the supersonic exit static
        pressure and up to the subsonic inlet static pressure, within a tolerance
        that accommodates the declared startup perturbation.

        Returns (max_allowed_p_min, min_allowed_p_max).
        """
        p_exit, _, _ = self.quasi1d_state(self.exit_radius_m, True)
        p_inlet, _, _ = self.quasi1d_state(self.inlet_radius_m, False)

        tol = 0.01 + abs(float(self.startup_perturbation))

        return p_exit * (1.0 + tol), p_inlet * (1.0 - tol)

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["base_axial_cells"] = list(self.base_axial_cells)
        return data

    def manifest(self) -> Dict[str, Any]:
        """Case manifest.

        Every key written by the canonical build.py is reproduced with the same
        name and meaning; the specification block is added so that the
        initializer and validator read the case parameters from the case itself
        rather than from a configuration file that may have moved on.
        """
        return {
            "scale": self.scale,
            "axial_cells": sum(self.axial_cells),
            "radial_cells": self.radial_cells,
            "angle_deg": self.wedge_angle_deg,
            "maxCo": self.max_courant,
            "end_time": self.end_time_s,
            "perturbation": self.startup_perturbation,
            "ambient_pa": self.ambient_pressure_pa,
            "ambient_imposed": self.ambient_imposed_at_exit,
            "solver": "shockFluid",
            "initialization": "quasi_1d_internal_only",
            "R": self.gas_constant_j_per_kg_k,
            "gamma": self.gamma,
            "case_spec": self.to_dict(),
            "provenance": (
                "Parameterized derivative of validation/canonical_reference; "
                "solver, boundary-condition philosophy, initialization strategy, "
                "numerical schemes and acceptance thresholds unchanged."
            ),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "NozzleCaseSpec":
        payload = dict(data)

        if "base_axial_cells" in payload:
            payload["base_axial_cells"] = tuple(payload["base_axial_cells"])

        known = {f.name for f in cls.__dataclass_fields__.values()}
        unknown = set(payload) - known

        if unknown:
            raise ValueError(
                f"Unknown case-specification fields: {sorted(unknown)}"
            )

        spec = cls(**payload)
        spec.validate()
        return spec

    @classmethod
    def from_manifest(cls, path: Path) -> "NozzleCaseSpec":
        manifest = json.loads(Path(path).read_text(encoding="utf-8-sig"))

        if "case_spec" not in manifest:
            raise ValueError(
                f"{path} has no case_spec block; it was not written by the "
                "parameterized pipeline."
            )

        return cls.from_dict(manifest["case_spec"])

    @classmethod
    def from_yaml(cls, path: Path) -> "NozzleCaseSpec":
        import yaml

        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8-sig"))
        return cls.from_config(raw)

    @classmethod
    def from_config(cls, raw: Dict[str, Any]) -> "NozzleCaseSpec":
        """Build a specification from the configs/nozzles YAML layout."""
        geometry = raw["geometry_m"]
        reservoir = raw["reservoir"]
        environment = raw.get("environment", {})
        physics = raw.get("physics", {})
        numerics = raw.get("numerics", {})

        spec = cls(
            case_id=raw["case_id"],
            description=raw.get("description", ""),
            inlet_radius_m=float(geometry["inlet_radius"]),
            throat_radius_m=float(geometry["throat_radius"]),
            exit_radius_m=float(geometry["exit_radius"]),
            inlet_straight_m=float(geometry["inlet_straight"]),
            converging_m=float(geometry["converging"]),
            throat_m=float(geometry["throat"]),
            diverging_m=float(geometry["diverging"]),
            outlet_straight_m=float(geometry["outlet_straight"]),
            total_pressure_pa=float(reservoir["total_pressure_pa"]),
            total_temperature_k=float(reservoir["total_temperature_K"]),
            ambient_pressure_pa=float(
                environment.get("ambient_pressure_pa", 30000.0)
            ),
            ambient_imposed_at_exit=bool(
                environment.get("ambient_imposed_at_exit", False)
            ),
            gamma=float(physics.get("gamma", VALIDATED_GAMMA)),
            gas_constant_j_per_kg_k=float(
                physics.get("R_j_per_kgK", VALIDATED_R)
            ),
            scale=float(numerics.get("scale", 1.0)),
            wedge_angle_deg=float(numerics.get("wedge_angle_deg", 5.0)),
            max_courant=float(numerics.get("maxCo", 0.4)),
            end_time_s=float(numerics.get("end_time_s", 0.006)),
            startup_perturbation=float(
                numerics.get("startup_perturbation", 0.0)
            ),
            numerics_recipe=str(numerics.get("recipe", "validated_reference_v1")),
            validation_profile=str(
                raw.get("validation", {}).get(
                    "profile", "validated_reference_v1"
                )
            ),
        )

        spec.validate()
        return spec


CANONICAL_SPEC = NozzleCaseSpec(
    case_id="canonical_reference",
    description="Frozen canonical validated reference nozzle",
    inlet_radius_m=0.05,
    throat_radius_m=0.0326,
    exit_radius_m=0.0354,
    inlet_straight_m=0.05,
    converging_m=0.10,
    throat_m=0.01,
    diverging_m=0.12,
    outlet_straight_m=0.05,
    total_pressure_pa=200000.0,
    total_temperature_k=300.0,
    ambient_pressure_pa=30000.0,
)
