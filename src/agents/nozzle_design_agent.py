from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Literal

from google import genai
from google.genai import types
from pydantic import BaseModel, Field

from src.cad.nozzle_generator import NozzleSpec

MODEL_NAME = os.getenv("GEMINI_MODEL", "gemini-3.6-flash")

NozzleFamily = Literal[
    "conical",
    "smooth_cosine",
    "bell",
    "spline",
    "custom",
]


class CFDPhysics(BaseModel):
    fluid: str = "air"
    compressible: bool = True
    inlet_total_pressure_pa: float | None = None
    inlet_total_temperature_k: float | None = None
    outlet_static_pressure_pa: float | None = None
    walls: str = "no_slip_adiabatic"
    turbulence_model: str = "kOmegaSST"
    solver: str = "shockFluid"


class MeshConstraints(BaseModel):
    max_elements: int = 5000
    min_quality: float = 0.28
    min_throat_nodes: int = 180
    important_regions: list[str] = Field(
        default_factory=lambda: ["throat", "walls", "diverging_section"]
    )


class GeometryPlan(BaseModel):
    family: NozzleFamily
    selection_reason: str
    inlet_radius: float
    throat_radius: float
    outlet_radius: float
    inlet_length: float
    converging_length: float
    throat_length: float
    diverging_length: float
    outlet_length: float
    bell_exponent: float = 1.7
    profile_points: list[list[float]] = Field(default_factory=list)


class NozzleCasePlan(BaseModel):
    case_name: str
    geometry: GeometryPlan
    physics: CFDPhysics
    mesh_constraints: MeshConstraints
    assumptions: list[str] = Field(default_factory=list)


SYSTEM_PROMPT = """
You are the design-planning agent for an agentic CFD meshing system.

SUPPORTED DOMAIN:
- axisymmetric
- single inlet
- single connected minimum-area throat
- single outlet
- converging-diverging internal-flow nozzle

SUPPORTED FAMILY LABELS:
conical, smooth_cosine, bell, spline, custom

The CAD backend is generic: every family is ultimately converted into an
(x, radius) profile. Do not leave the supported domain.

RULES:
1. If the user explicitly selects a family other than "auto", honor it.
2. If the user selects "auto", choose the most appropriate supported family
   and explain the choice briefly in selection_reason.
3. Copy any numerical geometry or CFD values explicitly supplied by the user.
4. Do not invent missing CFD boundary-condition values. Return null when a
   pressure or temperature is not supplied.
5. If geometry dimensions are missing, you may choose physically valid,
   moderate demonstration dimensions in SI meters. Record such choices in
   assumptions.
6. The throat radius must be smaller than both inlet and outlet radii.
7. All axial lengths must be positive.
8. For spline/custom:
   - profile_points must contain 8-30 [x, radius] points
   - x must strictly increase
   - radius must remain positive
   - there must be one connected minimum-radius throat region
   - the contour must converge before the throat and diverge after it
9. For conical, smooth_cosine, or bell, profile_points should normally be [].
10. Bell means a generic bell-like contour, not a claim of Rao optimization.
11. Mesh constraints default to max_elements=5000, min_quality=0.28,
    min_throat_nodes=180 only when the user does not specify them.
12. Use kOmegaSST and shockFluid as defaults for the later compressible
    OpenFOAM stage unless the user explicitly requests something else.
13. Return JSON only, matching the schema.
"""


def _fallback_profile_points() -> list[list[float]]:
    return [
        [0.000, 0.050],
        [0.050, 0.050],
        [0.070, 0.045],
        [0.090, 0.034],
        [0.115, 0.024],
        [0.150, 0.020],
        [0.165, 0.020],
        [0.195, 0.023],
        [0.245, 0.030],
        [0.305, 0.036],
        [0.345, 0.040],
        [0.395, 0.040],
    ]


def _fallback_plan(
    user_prompt: str,
    requested_family: str,
    case_name: str,
) -> NozzleCasePlan:
    family: NozzleFamily = (
        "smooth_cosine"
        if requested_family == "auto"
        else requested_family  # type: ignore[assignment]
    )

    profile_points = (
        _fallback_profile_points()
        if family in {"spline", "custom"}
        else []
    )

    return NozzleCasePlan(
        case_name=case_name,
        geometry=GeometryPlan(
            family=family,
            selection_reason=(
                "Deterministic fallback used because the LLM planning call "
                "was unavailable."
            ),
            inlet_radius=0.050,
            throat_radius=0.020,
            outlet_radius=0.040,
            inlet_length=0.050,
            converging_length=0.100,
            throat_length=0.015,
            diverging_length=0.180,
            outlet_length=0.050,
            bell_exponent=1.7,
            profile_points=profile_points,
        ),
        physics=CFDPhysics(),
        mesh_constraints=MeshConstraints(),
        assumptions=[
            "Fallback geometry values were used.",
            f"Original user prompt retained: {user_prompt}",
        ],
    )


def plan_nozzle_case(
    user_prompt: str,
    requested_family: str,
    case_name: str,
    allow_fallback: bool = True,
) -> tuple[NozzleCasePlan, str]:
    if requested_family not in {
        "auto",
        "conical",
        "smooth_cosine",
        "bell",
        "spline",
        "custom",
    }:
        raise ValueError(f"Unsupported requested family: {requested_family}")

    api_key = os.getenv("GEMINI_API_KEY")

    if not api_key:
        if allow_fallback:
            return (
                _fallback_plan(user_prompt, requested_family, case_name),
                "deterministic_fallback",
            )
        raise RuntimeError("GEMINI_API_KEY is not set.")

    client = genai.Client(api_key=api_key)

    prompt = f"""
CASE NAME:
{case_name}

USER-SELECTED FAMILY:
{requested_family}

USER REQUEST:
{user_prompt}
"""

    try:
        response = client.models.generate_content(
            model=MODEL_NAME,
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT,
                response_mime_type="application/json",
                response_schema=NozzleCasePlan,
            ),
        )

        if not response.text:
            raise RuntimeError("Gemini returned no text response.")

        plan = NozzleCasePlan.model_validate_json(response.text)
        plan.case_name = case_name

        if requested_family != "auto":
            plan.geometry.family = requested_family  # type: ignore[assignment]

        return plan, "gemini"

    except Exception:
        if not allow_fallback:
            raise

        return (
            _fallback_plan(user_prompt, requested_family, case_name),
            "deterministic_fallback",
        )


def plan_to_nozzle_spec(plan: NozzleCasePlan) -> NozzleSpec:
    geometry = plan.geometry

    return NozzleSpec(
        name=plan.case_name,
        family=geometry.family,
        inlet_radius=geometry.inlet_radius,
        throat_radius=geometry.throat_radius,
        outlet_radius=geometry.outlet_radius,
        inlet_length=geometry.inlet_length,
        converging_length=geometry.converging_length,
        throat_length=geometry.throat_length,
        diverging_length=geometry.diverging_length,
        outlet_length=geometry.outlet_length,
        bell_exponent=geometry.bell_exponent,
        profile_points=geometry.profile_points,
    )


def save_plan(
    plan: NozzleCasePlan,
    source: str,
    path: Path,
) -> None:
    payload = {
        "planner_source": source,
        "model": MODEL_NAME if source == "gemini" else None,
        "plan": plan.model_dump(),
    }

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
