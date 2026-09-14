from __future__ import annotations

import json
import math
import os
from pathlib import Path
from typing import Any, Literal

from google import genai
from google.genai import types
from pydantic import BaseModel


MODEL_NAME = os.getenv(
    "GEMINI_MODEL",
    "gemini-3.6-flash",
)


# ============================================================
# CURRENT OPENFOAM BACKEND CAPABILITIES
# ============================================================
#
# These are implementation capabilities, not engineering
# decisions. Gemini reasons within this currently validated
# backend. We can expand this list later as more OpenFOAM
# templates are implemented and verified.
# ============================================================


OPENFOAM_BACKEND_CAPABILITIES = {
    "distribution": "OpenFOAM Foundation v14",
    "execution": "foamRun under WSL",
    "supported_flow_regimes": [
        "compressible",
    ],
    "supported_fluids": [
        "air",
        "dry air",
    ],
    "supported_solvers": [
        "fluid",
    ],
    "supported_simulation_modes": [
        "transient",
    ],
    "supported_turbulence_treatments": [
        "laminar",
        "RAS",
    ],
    "supported_ras_models": [
        "kOmegaSST",
    ],
    "supported_thermophysical_packages": [
        "hePsiThermo",
    ],
    "supported_equations_of_state": [
        "perfectGas",
    ],
    "supported_transport_models": [
        "sutherland",
    ],
    "supported_energy_formulations": [
        "sensibleInternalEnergy",
    ],
    "supported_convective_flux_schemes": [
        "Kurganov",
    ],
    "supported_gradient_schemes": [
        "Gauss linear",
    ],
    "supported_laplacian_schemes": [
        "Gauss linear corrected",
    ],
    "supported_time_schemes": [
        "Euler",
    ],
}


# ============================================================
# GEMINI-SAFE RESPONSE SCHEMA
# ============================================================


class GeminiOpenFOAMSetupSchema(BaseModel):
    """
    Structured engineering setup proposed by Gemini.

    Keep numerical limits out of the Pydantic schema because
    strict engineering validation is performed locally after the
    model responds.
    """

    solver: str

    simulation_mode: Literal[
        "steady",
        "transient",
    ]

    turbulence_treatment: Literal[
        "laminar",
        "RAS",
    ]

    turbulence_model: str | None

    inlet_turbulence_intensity: float | None
    inlet_turbulence_mixing_length_m: float | None

    thermophysical_package: str

    equation_of_state: str

    transport_model: str

    energy_formulation: str

    convective_flux_scheme: str

    gradient_scheme: str

    laplacian_scheme: str

    time_scheme: str

    initial_delta_t_s: float

    max_courant_number: float

    minimum_run_steps: int

    maximum_run_steps: int

    write_interval_steps: int

    residual_target: float

    mass_flow_relative_imbalance_target: float

    convergence_window_steps: int

    output_fields: list[str]

    rationale: str

    assumptions: list[str]


# ============================================================
# LOCALLY VALIDATED RESULT
# ============================================================


class OpenFOAMSetupPlan(BaseModel):
    solver: str

    simulation_mode: Literal[
        "steady",
        "transient",
    ]

    turbulence_treatment: Literal[
        "laminar",
        "RAS",
    ]

    turbulence_model: str | None

    inlet_turbulence_intensity: float | None
    inlet_turbulence_mixing_length_m: float | None

    thermophysical_package: str

    equation_of_state: str

    transport_model: str

    energy_formulation: str

    convective_flux_scheme: str

    gradient_scheme: str

    laplacian_scheme: str

    time_scheme: str

    initial_delta_t_s: float

    max_courant_number: float

    minimum_run_steps: int

    maximum_run_steps: int

    write_interval_steps: int

    residual_target: float

    mass_flow_relative_imbalance_target: float

    convergence_window_steps: int

    output_fields: list[str]

    rationale: str

    assumptions: list[str]


# ============================================================
# GEMINI SYSTEM PROMPT
# ============================================================


SYSTEM_PROMPT = """
You are the OpenFOAM engineering-setup reasoning agent in an
agentic CFD workflow.

The geometry has already been generated, verified, visually
approved, and locked.

A Gmsh mesh has already been generated and accepted against the
user's supplied mesh constraints.

Your job is to choose the UNSPECIFIED OpenFOAM engineering setup
needed to execute the user's CFD request.

ROLE SPLIT

User:
- specifies the physical problem, boundary conditions, objectives,
  and any explicit solver/model requirements.

CFD request interpreter:
- preserves what the user actually specified.
- null means the user did not explicitly specify that choice.

You:
- make the missing engineering choices needed for OpenFOAM.
- reason from the physical request, geometry information, final
  mesh metrics, and current backend capabilities.

Python:
- validates your proposal.
- preserves hard user requirements.
- writes OpenFOAM dictionaries.
- executes gmshToFoam, checkMesh, and the solver.
- measures solver/physics diagnostics.

IMPORTANT RULES

1. Never change the approved geometry.

2. Never change the accepted mesh.

3. Never change the user's CFD boundary-condition values.

4. If the user explicitly requested a solver, preserve it exactly
   unless it is unsupported by the current backend. Do not silently
   replace an explicit user solver.

5. If the user explicitly requested a turbulence model, preserve it
   exactly unless it is unsupported by the current backend. Do not
   silently replace an explicit user model.

6. If solver_requested is null, choose an appropriate solver from
   the supplied backend capabilities.

7. If turbulence_model is null, decide whether the current problem
   should use laminar or RAS treatment. If RAS is selected, choose a
   supported RAS model.

8. If RAS is selected, also choose a physically reasonable inlet
   turbulence intensity and turbulence mixing length for this nozzle
   problem. These are engineering assumptions and must come from you,
   not be silently invented by Python. If laminar is selected, return
   both turbulence inlet quantities as null.

10. Do not invent new inlet pressure, outlet pressure, temperature,
   velocity, Mach number, wall temperature, or mesh constraints.

9. Use the current backend capabilities as implementation
   constraints. Do not invent unsupported solver/module names or
   numerical schemes.

11. For compressible nozzle flow with a large pressure ratio and
    possible shock-sensitive behavior, reason about a robust
    compressible transient setup rather than claiming a shock has
    already been detected.

12. Before CFD there is only a possible shock-sensitive region.
    Actual shock/gradient location must come from OpenFOAM results.

13. Choose conservative initial time-stepping and Courant control
    suitable for a first meaningful simulation.

14. The run should be long enough to provide useful CFD evidence,
    but this setup agent does not claim convergence in advance.

15. residual_target and mass_flow_relative_imbalance_target are
    monitoring targets. Python/OpenFOAM must measure whether they
    are achieved.

16. requested output fields should support both the current user
    result and later physics-driven remeshing. Include, when
    physically relevant:
    p, T, U, rho, Mach, mass_flow.

17. Keep rationale concise and engineering-focused. Do not expose
    hidden chain-of-thought.

18. Return only the structured response matching the schema.
"""


# ============================================================
# GEMINI CLIENT
# ============================================================


def load_gemini() -> genai.Client:
    api_key = os.getenv(
        "GEMINI_API_KEY"
    )

    if not api_key:
        raise RuntimeError(
            "GEMINI_API_KEY is not set."
        )

    return genai.Client(
        api_key=api_key
    )


# ============================================================
# PUBLIC ENTRY POINT
# ============================================================


def plan_openfoam_setup(
    geometry_analysis: dict[str, Any],
    cfd_request: dict[str, Any],
    best_mesh_metrics: dict[str, Any],
    allow_fallback: bool = True,
) -> tuple[OpenFOAMSetupPlan, str]:
    """
    Ask Gemini to choose the unspecified OpenFOAM engineering
    setup for the already approved final mesh.

    Returns
    -------
    plan, source
        source is "gemini" when Gemini produced a valid setup.
        A deterministic V5.2-derived fallback is used only when
        allow_fallback=True.
    """

    _validate_required_cfd_request(
        cfd_request=cfd_request
    )

    payload = {
        "approved_geometry_analysis": (
            geometry_analysis
        ),
        "structured_cfd_request": (
            cfd_request
        ),
        "accepted_mesh_metrics": (
            _compact_mesh_metrics(
                best_mesh_metrics
            )
        ),
        "openfoam_backend_capabilities": (
            OPENFOAM_BACKEND_CAPABILITIES
        ),
        "instruction": (
            "Choose the missing OpenFOAM engineering setup. "
            "Preserve all explicit user requirements exactly. "
            "Do not modify geometry, mesh, or CFD boundary "
            "conditions."
        ),
    }

    try:
        client = load_gemini()

        response = client.models.generate_content(
            model=MODEL_NAME,
            contents=json.dumps(
                payload,
                indent=2,
            ),
            config=types.GenerateContentConfig(
                system_instruction=(
                    SYSTEM_PROMPT
                ),
                response_mime_type=(
                    "application/json"
                ),
                response_schema=(
                    GeminiOpenFOAMSetupSchema
                ),
                temperature=0,
            ),
        )

        if not response.text:
            raise RuntimeError(
                "Gemini returned an empty OpenFOAM "
                "setup response."
            )

        raw = (
            GeminiOpenFOAMSetupSchema
            .model_validate_json(
                response.text
            )
        )

        plan = _validate_and_build_plan(
            raw=raw,
            cfd_request=cfd_request,
        )

        return plan, "gemini"

    except Exception as exc:
        print()
        print("=" * 68)
        print("GEMINI OPENFOAM-SETUP ERROR")
        print("=" * 68)
        print(
            f"Exception type : "
            f"{type(exc).__name__}"
        )
        print(
            f"Exception      : "
            f"{exc}"
        )
        print("=" * 68)
        print()

        if not allow_fallback:
            raise

        print(
            "Gemini OpenFOAM setup failed validation/API "
            "execution. Using deterministic fallback."
        )

        print()

        plan = _fallback_plan(
            cfd_request=cfd_request
        )

        return (
            plan,
            "deterministic_fallback",
        )


# ============================================================
# VALIDATION
# ============================================================


def _validate_required_cfd_request(
    cfd_request: dict[str, Any],
) -> None:
    physics = cfd_request.get(
        "physics",
        {}
    )

    if not bool(
        physics.get(
            "openfoam_requested",
            False,
        )
    ):
        raise ValueError(
            "OpenFOAM was not requested by the user."
        )

    flow_regime = str(
        physics.get(
            "flow_regime",
            ""
        )
        or ""
    ).strip().lower()

    supported_regimes = {
        str(item).lower()
        for item in (
            OPENFOAM_BACKEND_CAPABILITIES[
                "supported_flow_regimes"
            ]
        )
    }

    if flow_regime not in supported_regimes:
        raise ValueError(
            "Current OpenFOAM backend does not support "
            f"flow_regime='{flow_regime}'."
        )

    fluid = str(
        physics.get(
            "fluid",
            ""
        )
        or ""
    ).strip().lower()

    supported_fluids = {
        str(item).lower()
        for item in (
            OPENFOAM_BACKEND_CAPABILITIES[
                "supported_fluids"
            ]
        )
    }

    if fluid not in supported_fluids:
        raise ValueError(
            "Current OpenFOAM backend has a validated "
            f"template only for {sorted(supported_fluids)}, "
            f"got '{fluid}'."
        )

    bc = physics.get(
        "boundary_conditions",
        {}
    )

    required = {
        "inlet total pressure": (
            bc.get(
                "inlet_pressure_pa"
            )
        ),
        "inlet total temperature": (
            bc.get(
                "inlet_temperature_k"
            )
        ),
        "outlet static pressure": (
            bc.get(
                "outlet_pressure_pa"
            )
        ),
    }

    for label, value in required.items():
        if value is None:
            raise ValueError(
                "OpenFOAM setup requires "
                f"{label}, but it was not supplied."
            )

    if (
        bc.get(
            "inlet_pressure_type"
        )
        != "total_pressure"
    ):
        raise ValueError(
            "Current nozzle OpenFOAM backend expects "
            "inlet_pressure_type='total_pressure'."
        )

    if (
        bc.get(
            "inlet_temperature_type"
        )
        != "total_temperature"
    ):
        raise ValueError(
            "Current nozzle OpenFOAM backend expects "
            "inlet_temperature_type='total_temperature'."
        )

    if (
        bc.get(
            "outlet_pressure_type"
        )
        != "static_pressure"
    ):
        raise ValueError(
            "Current nozzle OpenFOAM backend expects "
            "outlet_pressure_type='static_pressure'."
        )


def _validate_and_build_plan(
    raw: GeminiOpenFOAMSetupSchema,
    cfd_request: dict[str, Any],
) -> OpenFOAMSetupPlan:
    physics = cfd_request[
        "physics"
    ]

    solver = (
        raw.solver
        .strip()
    )

    supported_solvers = {
        str(item).lower(): str(item)
        for item in (
            OPENFOAM_BACKEND_CAPABILITIES[
                "supported_solvers"
            ]
        )
    }

    if solver.lower() not in supported_solvers:
        raise ValueError(
            "Unsupported OpenFOAM solver "
            f"'{solver}'. Supported: "
            f"{list(supported_solvers.values())}"
        )

    solver = supported_solvers[
        solver.lower()
    ]

    explicit_solver = physics.get(
        "solver_requested"
    )

    if explicit_solver is not None:
        if (
            solver.lower()
            != str(
                explicit_solver
            ).strip().lower()
        ):
            raise ValueError(
                "Gemini attempted to override the user's "
                "explicit solver request."
            )

    supported_modes = {
        str(item).lower()
        for item in (
            OPENFOAM_BACKEND_CAPABILITIES[
                "supported_simulation_modes"
            ]
        )
    }

    if (
        raw.simulation_mode.lower()
        not in supported_modes
    ):
        raise ValueError(
            "Unsupported simulation_mode "
            f"'{raw.simulation_mode}'."
        )

    treatment = (
        raw.turbulence_treatment
        .strip()
    )

    supported_treatments = {
        str(item).lower()
        for item in (
            OPENFOAM_BACKEND_CAPABILITIES[
                "supported_turbulence_treatments"
            ]
        )
    }

    if treatment.lower() not in (
        supported_treatments
    ):
        raise ValueError(
            "Unsupported turbulence treatment "
            f"'{treatment}'."
        )

    turbulence_model = (
        raw.turbulence_model.strip()
        if raw.turbulence_model is not None
        else None
    )

    if treatment.lower() == "laminar":
        if turbulence_model not in {
            None,
            "",
        }:
            raise ValueError(
                "Laminar treatment requires "
                "turbulence_model=null."
            )

        turbulence_model = None

    else:
        if not turbulence_model:
            raise ValueError(
                "RAS treatment requires a "
                "turbulence model."
            )

        supported_models = {
            str(item).lower(): str(item)
            for item in (
                OPENFOAM_BACKEND_CAPABILITIES[
                    "supported_ras_models"
                ]
            )
        }

        if (
            turbulence_model.lower()
            not in supported_models
        ):
            raise ValueError(
                "Unsupported RAS turbulence model "
                f"'{turbulence_model}'. Supported: "
                f"{list(supported_models.values())}"
            )

        turbulence_model = (
            supported_models[
                turbulence_model.lower()
            ]
        )

    explicit_turbulence_model = physics.get(
        "turbulence_model"
    )

    if explicit_turbulence_model is not None:
        if turbulence_model is None:
            raise ValueError(
                "Gemini attempted to remove the user's "
                "explicit turbulence-model request."
            )

        if (
            turbulence_model.lower()
            != str(
                explicit_turbulence_model
            ).strip().lower()
        ):
            raise ValueError(
                "Gemini attempted to override the user's "
                "explicit turbulence-model request."
            )

    inlet_turbulence_intensity = (
        raw.inlet_turbulence_intensity
    )

    inlet_turbulence_mixing_length_m = (
        raw.inlet_turbulence_mixing_length_m
    )

    if treatment.lower() == "ras":
        if inlet_turbulence_intensity is None:
            raise ValueError(
                "RAS treatment requires "
                "inlet_turbulence_intensity."
            )

        if inlet_turbulence_mixing_length_m is None:
            raise ValueError(
                "RAS treatment requires "
                "inlet_turbulence_mixing_length_m."
            )

        _require_positive_finite(
            inlet_turbulence_intensity,
            "inlet_turbulence_intensity",
        )

        _require_positive_finite(
            inlet_turbulence_mixing_length_m,
            "inlet_turbulence_mixing_length_m",
        )

        if float(inlet_turbulence_intensity) >= 1.0:
            raise ValueError(
                "inlet_turbulence_intensity must be "
                "a fraction between 0 and 1."
            )

    else:
        if (
            inlet_turbulence_intensity is not None
            or inlet_turbulence_mixing_length_m is not None
        ):
            raise ValueError(
                "Laminar treatment requires turbulence "
                "inlet quantities to be null."
            )

    thermophysical_package = (
        _validate_supported_choice(
            value=(
                raw.thermophysical_package
            ),
            capability_key=(
                "supported_thermophysical_packages"
            ),
            label=(
                "thermophysical_package"
            ),
        )
    )

    equation_of_state = (
        _validate_supported_choice(
            value=(
                raw.equation_of_state
            ),
            capability_key=(
                "supported_equations_of_state"
            ),
            label=(
                "equation_of_state"
            ),
        )
    )

    transport_model = (
        _validate_supported_choice(
            value=(
                raw.transport_model
            ),
            capability_key=(
                "supported_transport_models"
            ),
            label=(
                "transport_model"
            ),
        )
    )

    energy_formulation = (
        _validate_supported_choice(
            value=(
                raw.energy_formulation
            ),
            capability_key=(
                "supported_energy_formulations"
            ),
            label=(
                "energy_formulation"
            ),
        )
    )

    convective_flux_scheme = (
        _validate_supported_choice(
            value=(
                raw.convective_flux_scheme
            ),
            capability_key=(
                "supported_convective_flux_schemes"
            ),
            label=(
                "convective_flux_scheme"
            ),
        )
    )

    gradient_scheme = (
        _validate_supported_choice(
            value=(
                raw.gradient_scheme
            ),
            capability_key=(
                "supported_gradient_schemes"
            ),
            label=(
                "gradient_scheme"
            ),
        )
    )

    laplacian_scheme = (
        _validate_supported_choice(
            value=(
                raw.laplacian_scheme
            ),
            capability_key=(
                "supported_laplacian_schemes"
            ),
            label=(
                "laplacian_scheme"
            ),
        )
    )

    time_scheme = (
        _validate_supported_choice(
            value=(
                raw.time_scheme
            ),
            capability_key=(
                "supported_time_schemes"
            ),
            label=(
                "time_scheme"
            ),
        )
    )

    _require_positive_finite(
        raw.initial_delta_t_s,
        "initial_delta_t_s",
    )

    _require_positive_finite(
        raw.max_courant_number,
        "max_courant_number",
    )

    _require_positive_finite(
        raw.residual_target,
        "residual_target",
    )

    _require_positive_finite(
        raw.mass_flow_relative_imbalance_target,
        "mass_flow_relative_imbalance_target",
    )

    if (
        raw.mass_flow_relative_imbalance_target
        >= 1.0
    ):
        raise ValueError(
            "mass_flow_relative_imbalance_target "
            "must be less than 1.0."
        )

    positive_ints = {
        "minimum_run_steps": (
            raw.minimum_run_steps
        ),
        "maximum_run_steps": (
            raw.maximum_run_steps
        ),
        "write_interval_steps": (
            raw.write_interval_steps
        ),
        "convergence_window_steps": (
            raw.convergence_window_steps
        ),
    }

    for name, value in positive_ints.items():
        if int(value) <= 0:
            raise ValueError(
                f"{name} must be positive."
            )

    if (
        raw.minimum_run_steps
        > raw.maximum_run_steps
    ):
        raise ValueError(
            "minimum_run_steps cannot exceed "
            "maximum_run_steps."
        )

    if (
        raw.write_interval_steps
        > raw.maximum_run_steps
    ):
        raise ValueError(
            "write_interval_steps cannot exceed "
            "maximum_run_steps."
        )

    if (
        raw.convergence_window_steps
        > raw.maximum_run_steps
    ):
        raise ValueError(
            "convergence_window_steps cannot exceed "
            "maximum_run_steps."
        )

    output_fields = (
        _normalize_output_fields(
            raw.output_fields
        )
    )

    required_output_fields = {
        "p",
        "T",
        "U",
        "rho",
        "Mach",
        "mass_flow",
    }

    missing_outputs = (
        required_output_fields
        - set(
            output_fields
        )
    )

    if missing_outputs:
        raise ValueError(
            "OpenFOAM setup must retain the fields "
            "needed for user reporting and later CFD "
            "feedback. Missing: "
            f"{sorted(missing_outputs)}"
        )

    return OpenFOAMSetupPlan(
        solver=solver,
        simulation_mode=(
            raw.simulation_mode
        ),
        turbulence_treatment=(
            "RAS"
            if treatment.lower() == "ras"
            else "laminar"
        ),
        turbulence_model=(
            turbulence_model
        ),
        inlet_turbulence_intensity=(
            None
            if inlet_turbulence_intensity is None
            else float(inlet_turbulence_intensity)
        ),
        inlet_turbulence_mixing_length_m=(
            None
            if inlet_turbulence_mixing_length_m is None
            else float(inlet_turbulence_mixing_length_m)
        ),
        thermophysical_package=(
            thermophysical_package
        ),
        equation_of_state=(
            equation_of_state
        ),
        transport_model=(
            transport_model
        ),
        energy_formulation=(
            energy_formulation
        ),
        convective_flux_scheme=(
            convective_flux_scheme
        ),
        gradient_scheme=(
            gradient_scheme
        ),
        laplacian_scheme=(
            laplacian_scheme
        ),
        time_scheme=(
            time_scheme
        ),
        initial_delta_t_s=float(
            raw.initial_delta_t_s
        ),
        max_courant_number=float(
            raw.max_courant_number
        ),
        minimum_run_steps=int(
            raw.minimum_run_steps
        ),
        maximum_run_steps=int(
            raw.maximum_run_steps
        ),
        write_interval_steps=int(
            raw.write_interval_steps
        ),
        residual_target=float(
            raw.residual_target
        ),
        mass_flow_relative_imbalance_target=float(
            raw.mass_flow_relative_imbalance_target
        ),
        convergence_window_steps=int(
            raw.convergence_window_steps
        ),
        output_fields=(
            output_fields
        ),
        rationale=(
            raw.rationale.strip()
        ),
        assumptions=[
            str(item).strip()
            for item in raw.assumptions
            if str(item).strip()
        ],
    )


def _validate_supported_choice(
    value: str,
    capability_key: str,
    label: str,
) -> str:
    clean = str(
        value
    ).strip()

    supported = {
        str(item).lower(): str(item)
        for item in (
            OPENFOAM_BACKEND_CAPABILITIES[
                capability_key
            ]
        )
    }

    if clean.lower() not in supported:
        raise ValueError(
            f"Unsupported {label} '{clean}'. "
            f"Supported: "
            f"{list(supported.values())}"
        )

    return supported[
        clean.lower()
    ]


def _require_positive_finite(
    value: float,
    label: str,
) -> None:
    numeric = float(
        value
    )

    if (
        not math.isfinite(
            numeric
        )
        or numeric <= 0.0
    ):
        raise ValueError(
            f"{label} must be finite and positive."
        )


def _normalize_output_fields(
    fields: list[str],
) -> list[str]:
    canonical = {
        "p": "p",
        "pressure": "p",
        "t": "T",
        "temperature": "T",
        "u": "U",
        "velocity": "U",
        "rho": "rho",
        "density": "rho",
        "mach": "Mach",
        "mach_number": "Mach",
        "mass_flow": "mass_flow",
        "massflow": "mass_flow",
        "mass flow": "mass_flow",
    }

    normalized: list[str] = []

    for item in fields:
        clean = str(
            item
        ).strip()

        if not clean:
            continue

        mapped = canonical.get(
            clean.lower(),
            clean,
        )

        if mapped not in normalized:
            normalized.append(
                mapped
            )

    return normalized


# ============================================================
# DETERMINISTIC FALLBACK
# ============================================================


def _fallback_plan(
    cfd_request: dict[str, Any],
) -> OpenFOAMSetupPlan:
    """
    Conservative V5.2-derived backup.

    Gemini is the intended engineering reasoning layer.
    This fallback exists only for robustness and is always
    reported as deterministic_fallback.
    """

    physics = cfd_request[
        "physics"
    ]

    explicit_solver = (
        physics.get(
            "solver_requested"
        )
    )

    solver = (
        str(
            explicit_solver
        ).strip()
        if explicit_solver is not None
        else "fluid"
    )

    explicit_turbulence_model = (
        physics.get(
            "turbulence_model"
        )
    )

    if explicit_turbulence_model is not None:
        turbulence_treatment = "RAS"
        turbulence_model = str(
            explicit_turbulence_model
        ).strip()

    else:
        turbulence_treatment = "RAS"
        turbulence_model = "kOmegaSST"

    fallback = OpenFOAMSetupPlan(
        solver=solver,
        simulation_mode="transient",
        turbulence_treatment=(
            turbulence_treatment
        ),
        turbulence_model=(
            turbulence_model
        ),
        inlet_turbulence_intensity=(
            0.005
            if turbulence_treatment == "RAS"
            else None
        ),
        inlet_turbulence_mixing_length_m=(
            0.01
            if turbulence_treatment == "RAS"
            else None
        ),
        thermophysical_package=(
            "hePsiThermo"
        ),
        equation_of_state=(
            "perfectGas"
        ),
        transport_model=(
            "sutherland"
        ),
        energy_formulation=(
            "sensibleInternalEnergy"
        ),
        convective_flux_scheme=(
            "Kurganov"
        ),
        gradient_scheme=(
            "Gauss linear"
        ),
        laplacian_scheme=(
            "Gauss linear corrected"
        ),
        time_scheme="Euler",
        initial_delta_t_s=1.0e-7,
        max_courant_number=0.5,
        minimum_run_steps=200,
        maximum_run_steps=2000,
        write_interval_steps=100,
        residual_target=1.0e-5,
        mass_flow_relative_imbalance_target=0.02,
        convergence_window_steps=50,
        output_fields=[
            "p",
            "T",
            "U",
            "rho",
            "Mach",
            "mass_flow",
        ],
        rationale=(
            "Deterministic fallback based on the previously "
            "validated V5.2 compressible-air OpenFOAM setup."
        ),
        assumptions=[
            (
                "The current backend supports the V5.2-style "
                "compressible-air pressure-based fluid template."
            ),
        ],
    )

    # Reuse the same strict local validation so fallback never
    # bypasses user constraints or backend capabilities.
    raw = GeminiOpenFOAMSetupSchema(
        **fallback.model_dump()
    )

    return _validate_and_build_plan(
        raw=raw,
        cfd_request=cfd_request,
    )


# ============================================================
# COMPACT INPUT HELPERS
# ============================================================


def _compact_mesh_metrics(
    best_mesh_metrics: dict[str, Any],
) -> dict[str, Any]:
    keys = [
        "nodes",
        "elements_3d",
        "minimum_quality_minSICN",
        "average_quality_minSICN",
        "throat_nodes",
        "constraints",
        "selected_best_mesh_file",
    ]

    compact: dict[str, Any] = {}

    for key in keys:
        if key in best_mesh_metrics:
            compact[
                key
            ] = best_mesh_metrics[
                key
            ]

    return compact


# ============================================================
# SERIALIZATION
# ============================================================


def save_openfoam_setup(
    plan: OpenFOAMSetupPlan,
    source: str,
    output_path: Path,
) -> None:
    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    payload = {
        "source": source,
        "openfoam_setup": (
            plan.model_dump()
        ),
        "backend_capabilities": (
            OPENFOAM_BACKEND_CAPABILITIES
        ),
    }

    output_path.write_text(
        json.dumps(
            payload,
            indent=2,
        ),
        encoding="utf-8",
    )


# === SUPERSONIC VALIDATION BACKEND V1 ===
#
# Adds support for clean supersonic nozzle verification without
# imposing the theoretical exit pressure.
#
# Existing static-back-pressure / RAS behavior remains available.

_legacy_validate_required_cfd_request = _validate_required_cfd_request
_legacy_validate_and_build_plan = _validate_and_build_plan


def _is_supersonic_validation_request(
    cfd_request: dict[str, Any],
) -> bool:
    physics = cfd_request.get("physics", {})
    bc = physics.get("boundary_conditions", {})

    assumptions = " ".join(
        str(x)
        for x in cfd_request.get("assumptions", [])
    ).lower()

    return (
        bc.get("wall_velocity_condition") == "slip"
        or "inviscid" in assumptions
        or "fully-supersonic" in assumptions
        or "fully supersonic" in assumptions
    )


def _validate_required_cfd_request(
    cfd_request: dict[str, Any],
) -> None:
    if not _is_supersonic_validation_request(cfd_request):
        return _legacy_validate_required_cfd_request(
            cfd_request
        )

    physics = cfd_request.get("physics", {})

    if not bool(
        physics.get("openfoam_requested", False)
    ):
        raise ValueError(
            "OpenFOAM was not requested by the user."
        )

    if str(
        physics.get("flow_regime", "")
    ).strip().lower() != "compressible":
        raise ValueError(
            "Supersonic nozzle validation requires "
            "compressible flow."
        )

    if str(
        physics.get("fluid", "")
    ).strip().lower() not in {"air", "dry air"}:
        raise ValueError(
            "Current validation backend supports air only."
        )

    bc = physics.get("boundary_conditions", {})

    if bc.get("inlet_pressure_type") != "total_pressure":
        raise ValueError(
            "Validation backend requires inlet total pressure."
        )

    if bc.get("inlet_temperature_type") != "total_temperature":
        raise ValueError(
            "Validation backend requires inlet total temperature."
        )

    if bc.get("inlet_pressure_pa") is None:
        raise ValueError(
            "Inlet total pressure is missing."
        )

    if bc.get("inlet_temperature_k") is None:
        raise ValueError(
            "Inlet total temperature is missing."
        )

    outlet_type = bc.get("outlet_pressure_type")

    if outlet_type not in {
        None,
        "unspecified",
        "supersonic",
        "fully_supersonic",
        "static_pressure",
    }:
        raise ValueError(
            f"Unsupported outlet pressure type: {outlet_type}"
        )

    # A static-pressure outlet remains legal for subsonic or
    # shock-containing cases, but fully supersonic validation
    # deliberately permits no specified pressure.
    if (
        outlet_type == "static_pressure"
        and bc.get("outlet_pressure_pa") is None
    ):
        raise ValueError(
            "static_pressure outlet requires a pressure value."
        )

    if bc.get("wall_velocity_condition") not in {
        "slip",
        "no_slip",
    }:
        raise ValueError(
            "Wall velocity condition must be slip or no_slip."
        )

    if bc.get("wall_thermal_condition") != "adiabatic":
        raise ValueError(
            "Validation backend requires adiabatic walls."
        )


def _validate_and_build_plan(
    raw: GeminiOpenFOAMSetupSchema,
    cfd_request: dict[str, Any],
) -> OpenFOAMSetupPlan:

    plan = _legacy_validate_and_build_plan(
        raw=raw,
        cfd_request=cfd_request,
    )

    if _is_supersonic_validation_request(cfd_request):
        # No turbulence model for the clean validation case.
        plan = plan.model_copy(
            update={
                "turbulence_treatment": "laminar",
                "turbulence_model": None,
            }
        )

    return plan

