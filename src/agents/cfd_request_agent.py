from __future__ import annotations

import json
import os
import re
from pathlib import Path

from google import genai
from google.genai import types
from pydantic import BaseModel, Field


MODEL_NAME = os.getenv(
    "GEMINI_MODEL",
    "gemini-3.6-flash",
)


# ============================================================
# STRUCTURED CFD REQUEST
# ============================================================


class BoundaryConditions(BaseModel):
    inlet_pressure_type: str | None = Field(
        default=None,
        description=(
            "Examples: total_pressure, static_pressure, "
            "unspecified."
        ),
    )

    inlet_pressure_pa: float | None = None

    inlet_temperature_type: str | None = Field(
        default=None,
        description=(
            "Examples: total_temperature, static_temperature, "
            "unspecified."
        ),
    )

    inlet_temperature_k: float | None = None

    inlet_velocity_mps: float | None = None

    inlet_mach: float | None = None

    outlet_pressure_type: str | None = Field(
        default=None,
        description=(
            "Examples: static_pressure, total_pressure, "
            "unspecified."
        ),
    )

    outlet_pressure_pa: float | None = None

    wall_velocity_condition: str | None = Field(
        default=None,
        description=(
            "Examples: no_slip, slip, unspecified."
        ),
    )

    wall_thermal_condition: str | None = Field(
        default=None,
        description=(
            "Examples: adiabatic, fixed_temperature, "
            "unspecified."
        ),
    )

    wall_temperature_k: float | None = None


class PhysicsRequest(BaseModel):
    fluid: str | None = None

    flow_type: str | None = Field(
        default=None,
        description=(
            "Examples: internal, external."
        ),
    )

    flow_regime: str | None = Field(
        default=None,
        description=(
            "Examples: compressible, incompressible."
        ),
    )

    openfoam_requested: bool = False

    solver_requested: str | None = Field(
        default=None,
        description=(
            "Specific solver only if explicitly requested."
        ),
    )

    turbulence_model: str | None = Field(
        default=None,
        description=(
            "Specific turbulence model only if explicitly "
            "requested."
        ),
    )

    boundary_conditions: BoundaryConditions


class MeshRequirements(BaseModel):
    max_elements: int | None = Field(
        default=None,
        ge=1,
    )

    min_quality: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
    )

    min_throat_nodes: int | None = Field(
        default=None,
        ge=1,
    )

    priority_regions: list[str] = Field(
        default_factory=list,
    )

    boundary_layer_requested: bool = False

    shock_sensitive_refinement: bool = False


class CFDRequest(BaseModel):
    physics: PhysicsRequest

    mesh: MeshRequirements

    requested_feedback_metrics: list[str] = Field(
        default_factory=list,
    )

    assumptions: list[str] = Field(
        default_factory=list,
    )


# ============================================================
# GEMINI SYSTEM PROMPT
# ============================================================


SYSTEM_PROMPT = """
You are the CFD request interpretation agent for an agentic
CFD meshing system.

The geometry has already been generated, verified, visually
reviewed, approved, and locked.

Your job is NOT to change the geometry.

Your job is to convert the user's CFD and meshing request into
one structured object matching the supplied schema.

Rules:

1. Copy every numerical value from the user exactly.

2. Do not invent pressures, temperatures, Mach numbers,
   velocities, mesh limits, or throat-node requirements.

3. If a physics or boundary-condition quantity is not supplied,
   return null for that quantity.

4. Correctly distinguish:
   - total pressure
   - static pressure
   - total temperature
   - static temperature

5. For walls, identify:
   - no_slip or slip
   - adiabatic or fixed_temperature

6. Set flow_type to "internal" for nozzle internal flow.

7. Set flow_regime to "compressible" only when the request
   states or clearly requires compressible flow.

8. Set openfoam_requested=true only when OpenFOAM is requested.

9. Do NOT select a specific OpenFOAM solver unless the user
   explicitly specifies one.

10. Do NOT invent a turbulence model.

11. Extract mesh constraints exactly when supplied:
    - maximum number of 3D elements
    - minimum mesh quality
    - minimum throat nodes

12. Extract mesh-priority regions such as:
    - throat
    - walls
    - high_curvature
    - shock_region
    - inlet
    - outlet

13. boundary_layer_requested should be true only if the user
    explicitly asks for boundary-layer or prism-layer meshing.

14. shock_sensitive_refinement should be true when the user
    requests refinement or attention in possible shock regions.

15. requested_feedback_metrics should include only quantities
    explicitly requested for CFD evaluation. Do not invent them.

16. Do not modify or reinterpret the approved geometry.

17. Do not use Markdown.

Return only the structured JSON object.
"""


# ============================================================
# GEMINI CLIENT
# ============================================================


def load_gemini():
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
# SIMPLE FALLBACK
# ============================================================


def deterministic_fallback(
    user_prompt: str,
) -> CFDRequest:
    """
    Minimal fallback parser.

    Gemini remains the primary interpretation agent.
    This is only used when fallback is explicitly allowed.
    """

    text = user_prompt.lower()

    fluid = (
        "air"
        if "air" in text
        else None
    )

    flow_type = (
        "internal"
        if "nozzle" in text
        else None
    )

    flow_regime = (
        "compressible"
        if "compressible" in text
        else None
    )

    openfoam_requested = (
        "openfoam" in text
    )

    inlet_pressure = None
    inlet_temperature = None
    outlet_pressure = None
    max_elements = None
    min_quality = None
    min_throat_nodes = None

    match = re.search(
        r"inlet total pressure"
        r"[^0-9]*([0-9.]+)",
        text,
    )

    if match:
        inlet_pressure = float(
            match.group(1)
        )

    match = re.search(
        r"inlet total temperature"
        r"[^0-9]*([0-9.]+)",
        text,
    )

    if match:
        inlet_temperature = float(
            match.group(1)
        )

    match = re.search(
        r"outlet static pressure"
        r"[^0-9]*([0-9.]+)",
        text,
    )

    if match:
        outlet_pressure = float(
            match.group(1)
        )

    match = re.search(
        r"maximum(?:\s+3d)?\s+elements"
        r"[^0-9]*([0-9]+)",
        text,
    )

    if match:
        max_elements = int(
            match.group(1)
        )

    match = re.search(
        r"minimum mesh quality"
        r"[^0-9]*([0-9.]+)",
        text,
    )

    if match:
        min_quality = float(
            match.group(1)
        )

    match = re.search(
        r"minimum throat nodes"
        r"[^0-9]*([0-9]+)",
        text,
    )

    if match:
        min_throat_nodes = int(
            match.group(1)
        )


    # LEVEL1_CANONICAL_BC_ALIAS_FIX
    # Accept physically equivalent terminology used by the canonical
    # Level-1 engineering prompt and normalize pressure units to Pa.

    def _pressure_value_pa(pattern: str):
        quantity_match = re.search(
            pattern
            + r"[^0-9]*([0-9.]+)\s*(mpa|kpa|pa)?",
            text,
        )

        if not quantity_match:
            return None

        value = float(quantity_match.group(1))
        unit = (
            quantity_match.group(2) or "pa"
        ).lower()

        scale = {
            "pa": 1.0,
            "kpa": 1.0e3,
            "mpa": 1.0e6,
        }[unit]

        return value * scale

    canonical_inlet_pressure = _pressure_value_pa(
        r"inlet\s+(?:total|stagnation)\s+pressure"
    )

    if canonical_inlet_pressure is not None:
        inlet_pressure = canonical_inlet_pressure

    canonical_outlet_pressure = _pressure_value_pa(
        r"(?:outlet\s+static\s+pressure|"
        r"downstream\s+back\s+pressure|"
        r"back\s+pressure)"
    )

    if canonical_outlet_pressure is not None:
        outlet_pressure = canonical_outlet_pressure

    canonical_temperature = re.search(
        r"inlet\s+(?:total|stagnation)\s+temperature"
        r"[^0-9]*([0-9.]+)",
        text,
    )

    if canonical_temperature:
        inlet_temperature = float(
            canonical_temperature.group(1)
        )

    priority_regions: list[str] = []

    region_terms = {
        "throat": "throat",
        "wall": "walls",
        "high-curvature": "high_curvature",
        "high curvature": "high_curvature",
        "shock": "shock_region",
    }

    for phrase, region in region_terms.items():
        if (
            phrase in text
            and region not in priority_regions
        ):
            priority_regions.append(
                region
            )

    return CFDRequest(
        physics=PhysicsRequest(
            fluid=fluid,
            flow_type=flow_type,
            flow_regime=flow_regime,
            openfoam_requested=(
                openfoam_requested
            ),
            solver_requested=None,
            turbulence_model=None,
            boundary_conditions=(
                BoundaryConditions(
                    inlet_pressure_type=(
                        "total_pressure"
                        if inlet_pressure
                        is not None
                        else None
                    ),
                    inlet_pressure_pa=(
                        inlet_pressure
                    ),
                    inlet_temperature_type=(
                        "total_temperature"
                        if inlet_temperature
                        is not None
                        else None
                    ),
                    inlet_temperature_k=(
                        inlet_temperature
                    ),
                    outlet_pressure_type=(
                        "static_pressure"
                        if outlet_pressure
                        is not None
                        else None
                    ),
                    outlet_pressure_pa=(
                        outlet_pressure
                    ),
                    wall_velocity_condition=(
                        "slip"
                        if (
                            "slip" in text
                            and "no-slip" not in text
                            and "no slip" not in text
                        )
                        else "no_slip"
                        if (
                            "no-slip" in text
                            or "no slip" in text
                        )
                        else None
                    ),
                    wall_thermal_condition=(
                        "adiabatic"
                        if "adiabatic" in text
                        else None
                    ),
                )
            ),
        ),
        mesh=MeshRequirements(
            max_elements=max_elements,
            min_quality=min_quality,
            min_throat_nodes=(
                min_throat_nodes
            ),
            priority_regions=(
                priority_regions
            ),
            boundary_layer_requested=(
                "boundary layer" in text
                or "boundary-layer" in text
                or "prism layer" in text
            ),
            shock_sensitive_refinement=(
                "shock" in text
            ),
        ),
        requested_feedback_metrics=[],
        assumptions=[],
    )


# ============================================================
# MAIN CFD REQUEST PARSER
# ============================================================


def parse_cfd_request(
    user_prompt: str,
    allow_fallback: bool = True,
) -> tuple[CFDRequest, str]:
    """
    Convert Prompt 2 into a structured CFD request.

    Returns:
        request
        source
    """

    api_key = os.getenv(
        "GEMINI_API_KEY"
    )

    if not api_key:
        if not allow_fallback:
            raise RuntimeError(
                "GEMINI_API_KEY is not set."
            )

        return (
            deterministic_fallback(
                user_prompt
            ),
            "deterministic_fallback",
        )

    try:
        client = load_gemini()

        response = (
            client.models.generate_content(
                model=MODEL_NAME,
                contents=user_prompt,
                config=types.GenerateContentConfig(
                    system_instruction=(
                        SYSTEM_PROMPT
                    ),
                    response_mime_type=(
                        "application/json"
                    ),
                    response_schema=(
                        CFDRequest
                    ),
                    temperature=0,
                ),
            )
        )

        if not response.text:
            raise RuntimeError(
                "Gemini returned an empty response."
            )

        request = (
            CFDRequest.model_validate_json(
                response.text
            )
        )

        return request, "gemini"

    except Exception:
        if not allow_fallback:
            raise

        return (
            deterministic_fallback(
                user_prompt
            ),
            "deterministic_fallback",
        )


# ============================================================
# SAVE STRUCTURED REQUEST
# ============================================================


def save_cfd_request(
    request: CFDRequest,
    source: str,
    output_path: Path,
) -> None:
    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    payload = {
        "source": source,
        "request": request.model_dump(),
    }

    output_path.write_text(
        json.dumps(
            payload,
            indent=2,
        ),
        encoding="utf-8",
    )