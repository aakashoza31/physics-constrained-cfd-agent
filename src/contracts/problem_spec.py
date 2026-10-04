from dataclasses import dataclass, asdict
from enum import Enum
from typing import Any, Dict


class NozzleFamily(str, Enum):
    CONICAL = "conical"
    SMOOTH_COSINE = "smooth_cosine"
    BELL = "bell"


@dataclass
class NozzleGeometry:
    inlet_radius_m: float
    throat_radius_m: float
    outlet_radius_m: float

    inlet_length_m: float
    converging_length_m: float
    throat_length_m: float
    diverging_length_m: float
    outlet_length_m: float

    def validate(self) -> None:
        for name, value in asdict(self).items():
            if value <= 0.0:
                raise ValueError(f"{name} must be positive, got {value}")

        if self.throat_radius_m >= self.inlet_radius_m:
            raise ValueError(
                "throat_radius_m must be smaller than inlet_radius_m."
            )

        if self.throat_radius_m >= self.outlet_radius_m:
            raise ValueError(
                "throat_radius_m must be smaller than outlet_radius_m."
            )


@dataclass
class OperatingConditions:
    inlet_total_pressure_pa: float
    inlet_total_temperature_k: float
    outlet_static_pressure_pa: float

    gas: str = "air"
    gamma: float = 1.4
    gas_constant_j_kg_k: float = 287.0

    def validate(self) -> None:
        if self.gas.lower() != "air":
            raise ValueError(
                "Current registered scope supports air only."
            )

        if self.inlet_total_pressure_pa <= 0.0:
            raise ValueError(
                "inlet_total_pressure_pa must be positive."
            )

        if self.inlet_total_temperature_k <= 0.0:
            raise ValueError(
                "inlet_total_temperature_k must be positive."
            )

        if self.outlet_static_pressure_pa <= 0.0:
            raise ValueError(
                "outlet_static_pressure_pa must be positive."
            )

        if self.outlet_static_pressure_pa >= self.inlet_total_pressure_pa:
            raise ValueError(
                "outlet_static_pressure_pa must be below inlet total pressure."
            )

        if self.gamma <= 1.0:
            raise ValueError("gamma must be greater than 1.")

        if self.gas_constant_j_kg_k <= 0.0:
            raise ValueError(
                "gas_constant_j_kg_k must be positive."
            )


@dataclass
class CFDProblemSpec:
    nozzle_family: NozzleFamily
    geometry: NozzleGeometry
    operating_conditions: OperatingConditions

    engineering_objective: str = (
        "Obtain a numerically trustworthy compressible-Euler CFD solution "
        "and adapt the simulation if required."
    )

    physics_model: str = "compressible_euler"
    geometry_class: str = "axisymmetric_converging_diverging_nozzle"

    def validate(self) -> None:
        if self.physics_model != "compressible_euler":
            raise ValueError(
                "Current registered scope supports compressible Euler only."
            )

        if self.geometry_class != "axisymmetric_converging_diverging_nozzle":
            raise ValueError(
                "Current registered geometry class is an axisymmetric "
                "converging-diverging nozzle."
            )

        if not isinstance(self.nozzle_family, NozzleFamily):
            raise ValueError(
                "nozzle_family must be one of the supported NozzleFamily values."
            )

        self.geometry.validate()
        self.operating_conditions.validate()

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["nozzle_family"] = self.nozzle_family.value
        return data
