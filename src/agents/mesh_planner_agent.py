"""Legacy (CAD->Gmsh prototype, see paper Appendix C 'Prototype'); not used by the registered families.

Not part of the CFD Forge paper's registered nozzle or forward-step runs; kept
for reference.  Plans the initial Gmsh mesh strategy with Gemini.
The model identifier is read at request time from
``src.agents.llm_provenance.gemini_model_name()``.  The deterministic fallback
is opt-in (``allow_fallback=False`` by default).
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from google import genai
from google.genai import types
from pydantic import BaseModel, Field, model_validator

from src.agents.llm_provenance import gemini_model_name




# ============================================================
# DATA MODELS
# ============================================================

class GeminiMeshStrategySchema(BaseModel):
    """
    Gemini-facing schema.

    Keep this schema simple. The google-genai SDK currently
    rejects some JSON-Schema keywords produced by constrained
    Pydantic fields, such as `exclusiveMinimum`.

    Strict engineering validation happens after Gemini returns.
    """

    global_size_m: float
    throat_size_m: float
    wall_size_m: float
    diverging_size_m: float
    throat_padding_m: float
    wall_refinement_distance_m: float

    refine_throat: bool
    refine_walls: bool
    refine_diverging_section: bool
    refine_high_curvature: bool
    boundary_layer_requested: bool

    rationale: str


class MeshStrategy(BaseModel):
    """
    Strict locally validated mesh strategy.

    This model is NOT passed directly to Gemini as response_schema.
    """

    global_size_m: float = Field(gt=0.0)
    throat_size_m: float = Field(gt=0.0)
    wall_size_m: float = Field(gt=0.0)
    diverging_size_m: float = Field(gt=0.0)

    throat_padding_m: float = Field(ge=0.0)
    wall_refinement_distance_m: float = Field(gt=0.0)

    refine_throat: bool = True
    refine_walls: bool = True
    refine_diverging_section: bool = True
    refine_high_curvature: bool = True
    boundary_layer_requested: bool = False

    rationale: str

    @model_validator(mode="after")
    def validate_refinement_sizes(self) -> "MeshStrategy":

        if (
            self.refine_throat
            and self.throat_size_m > self.global_size_m
        ):
            raise ValueError(
                "throat_size_m cannot exceed global_size_m "
                "when refine_throat=True."
            )

        if (
            self.refine_walls
            and self.wall_size_m > self.global_size_m
        ):
            raise ValueError(
                "wall_size_m cannot exceed global_size_m "
                "when refine_walls=True."
            )

        if (
            self.refine_diverging_section
            and self.diverging_size_m > self.global_size_m
        ):
            raise ValueError(
                "diverging_size_m cannot exceed global_size_m "
                "when refine_diverging_section=True."
            )

        return self


# ============================================================
# GEMINI SYSTEM PROMPT
# ============================================================

SYSTEM_PROMPT = r"""
You are the initial CFD mesh-planning agent for an approved,
locked axisymmetric converging-diverging nozzle geometry.

The geometry is already approved by the user and MUST NOT be
changed.

You receive:
1. deterministic geometry analysis of the approved CAD, and
2. a structured CFD + meshing request parsed from the user's
   second prompt.

Your task is ONLY to propose an INITIAL Gmsh mesh-sizing
strategy. Do not generate a mesh and do not modify the CAD.

Engineering rules:
- All dimensions and mesh sizes are in meters.
- Prefer local refinement over making the entire mesh fine.
- The throat is normally important for compressible nozzle flow.
- Refine walls when the user asks to prioritize walls.
- Refine high-curvature regions when requested and when such
  regions exist in the geometry analysis.
- The diverging section can be treated as a candidate
  shock-sensitive region when the request asks for possible
  shock refinement.
- Do NOT claim that a shock actually exists before CFD has run.
- Do NOT claim an exact shock location before CFD has run.
- max_elements, min_quality, and min_throat_nodes are hard user
  constraints when supplied.

IMPORTANT THROAT-RESOLUTION METRIC SEMANTICS:
- min_throat_nodes means the TOTAL number of mesh nodes counted by
  the deterministic mesher inside a defined 3D throat-region control
  volume around the geometric throat.
- It does NOT mean "nodes across the throat diameter".
- It does NOT mean "nodes along the throat circumference".
- It does NOT mean "cells across the throat".
- Never estimate throat_size_m by dividing the throat diameter,
  circumference, radius, or throat length by min_throat_nodes.
- The relationship between throat_size_m and the measured throat-node
  count is not assumed analytically. Gmsh generates the mesh, Python
  measures the actual throat-node count, and the later LLM adaptation
  loop reasons from that measured feedback.
- For the initial strategy, choose a physically reasonable local throat
  size relative to the approved geometry and global mesh size, while
  respecting the user's computational budget. Do not force the initial
  proposal to hit min_throat_nodes exactly before any Gmsh measurement
  exists.

- The first mesh is only an initial proposal. A later adaptive
  loop will measure the actual mesh and revise it if needed.
- When the element budget is restrictive, avoid excessive global
  fineness. Spend resolution locally where it matters most.
- A locally refined size must not be larger than the global size.
- throat_padding_m controls the axial extent around the throat
  that receives throat-focused refinement.
- wall_refinement_distance_m controls the near-wall distance over
  which wall-focused sizing is applied.
- boundary_layer_requested MUST be true only when the structured
  user request explicitly asks for a boundary-layer/prism-layer
  mesh. A no-slip wall alone does NOT imply prism layers.

Return only the structured mesh strategy requested by the schema.
Keep the rationale short and engineering-focused.
""".strip()


# ============================================================
# HELPERS
# ============================================================

def load_gemini() -> genai.Client:
    api_key = os.getenv("GEMINI_API_KEY")

    if not api_key:
        raise RuntimeError(
            "GEMINI_API_KEY is not set."
        )

    return genai.Client(api_key=api_key)


def _extract_bbox(
    geometry_analysis: dict[str, Any],
) -> list[float] | None:

    candidates: list[Any] = [
        geometry_analysis.get("bounding_box"),
        geometry_analysis.get("bbox"),
    ]

    geometry = geometry_analysis.get("geometry")

    if isinstance(geometry, dict):
        candidates.extend(
            [
                geometry.get("bounding_box"),
                geometry.get("bbox"),
            ]
        )

    geometry_info = geometry_analysis.get("geometry_info")

    if isinstance(geometry_info, dict):
        candidates.extend(
            [
                geometry_info.get("bounding_box"),
                geometry_info.get("bbox"),
            ]
        )

    for candidate in candidates:

        if (
            isinstance(candidate, (list, tuple))
            and len(candidate) == 6
        ):
            try:
                return [
                    float(value)
                    for value in candidate
                ]

            except (TypeError, ValueError):
                continue

    return None


def _geometry_length_m(
    geometry_analysis: dict[str, Any],
) -> float:

    bbox = _extract_bbox(
        geometry_analysis
    )

    if bbox is not None:

        length = abs(
            bbox[3] - bbox[0]
        )

        if length > 0.0:
            return length

    for container_key in (
        "verified_geometry",
        "geometry_metrics",
        "profile_metrics",
    ):

        container = geometry_analysis.get(
            container_key
        )

        if isinstance(container, dict):

            value = container.get(
                "total_length_m"
            )

            if value is not None:

                try:
                    length = float(value)

                    if length > 0.0:
                        return length

                except (TypeError, ValueError):
                    pass

    return 0.4


def _mesh_request(
    cfd_request: dict[str, Any],
) -> dict[str, Any]:

    mesh = cfd_request.get(
        "mesh",
        {},
    )

    if isinstance(mesh, dict):
        return mesh

    return {}


def deterministic_fallback(
    geometry_analysis: dict[str, Any],
    cfd_request: dict[str, Any],
) -> MeshStrategy:

    length_m = _geometry_length_m(
        geometry_analysis
    )

    mesh_request = _mesh_request(
        cfd_request
    )

    priority_regions = {
        str(region).strip().lower()
        for region
        in mesh_request.get(
            "priority_regions",
            [],
        )
    }

    global_size = (
        0.04 * length_m
    )

    refine_throat = (
        "throat"
        in priority_regions
    )

    refine_walls = (
        "walls"
        in priority_regions
        or "wall"
        in priority_regions
    )

    shock_sensitive = bool(
        mesh_request.get(
            "shock_sensitive_refinement",
            False,
        )
    )

    refine_diverging = (
        "diverging"
        in priority_regions
        or "diverging_section"
        in priority_regions
        or "shock_region"
        in priority_regions
        or shock_sensitive
    )

    refine_high_curvature = (
        "high_curvature"
        in priority_regions
        or "curvature"
        in priority_regions
    )

    boundary_layer_requested = bool(
        mesh_request.get(
            "boundary_layer_requested",
            False,
        )
    )

    return MeshStrategy(
        global_size_m=global_size,
        throat_size_m=(
            0.25 * global_size
        ),
        wall_size_m=(
            0.40 * global_size
        ),
        diverging_size_m=(
            0.50 * global_size
        ),
        throat_padding_m=(
            0.03 * length_m
        ),
        wall_refinement_distance_m=(
            0.025 * length_m
        ),
        refine_throat=refine_throat,
        refine_walls=refine_walls,
        refine_diverging_section=(
            refine_diverging
        ),
        refine_high_curvature=(
            refine_high_curvature
        ),
        boundary_layer_requested=(
            boundary_layer_requested
        ),
        rationale=(
            "Deterministic scale-aware initial strategy used "
            "because the Gemini planner was unavailable or "
            "invalid. Local refinement is concentrated in "
            "explicitly requested regions while retaining a "
            "coarser global background."
        ),
    )


def _enforce_request_invariants(
    raw_strategy: dict[str, Any],
    cfd_request: dict[str, Any],
) -> dict[str, Any]:

    strategy = dict(
        raw_strategy
    )

    mesh_request = _mesh_request(
        cfd_request
    )

    # Gemini is not allowed to infer prism/boundary-layer
    # meshing merely from a no-slip wall.
    strategy[
        "boundary_layer_requested"
    ] = bool(
        mesh_request.get(
            "boundary_layer_requested",
            False,
        )
    )

    return strategy


# ============================================================
# PRIMARY PLANNER
# ============================================================

def plan_initial_mesh(
    geometry_analysis: dict[str, Any],
    cfd_request: dict[str, Any],
    allow_fallback: bool = False,
) -> tuple[MeshStrategy, str]:

    planner_input = {
        "approved_geometry_analysis": (
            geometry_analysis
        ),
        "structured_cfd_request": (
            cfd_request
        ),
        "measurement_semantics": {
            "min_throat_nodes": (
                "Total mesh nodes counted inside the deterministic "
                "3D throat-region control volume. This is NOT nodes "
                "across the throat diameter and must NOT be converted "
                "to throat_size_m by diameter/min_throat_nodes."
            ),
            "evaluation_rule": (
                "Gmsh generates the candidate mesh. Python measures "
                "the actual throat-node count afterward. The LLM "
                "should use that measured feedback in later trials."
            ),
        },
    }

    try:
        client = load_gemini()

        response = (
            client.models.generate_content(
                model=gemini_model_name(),
                contents=json.dumps(
                    planner_input,
                    indent=2,
                ),
                config=(
                    types.GenerateContentConfig(
                        system_instruction=(
                            SYSTEM_PROMPT
                        ),
                        response_mime_type=(
                            "application/json"
                        ),
                        response_schema=(
                            GeminiMeshStrategySchema
                        ),
                        temperature=0,
                    )
                ),
            )
        )

        if not response.text:
            raise RuntimeError(
                "Gemini returned an empty "
                "mesh-planning response."
            )

        gemini_strategy = (
            GeminiMeshStrategySchema
            .model_validate_json(
                response.text
            )
        )

        strategy_data = (
            _enforce_request_invariants(
                gemini_strategy.model_dump(),
                cfd_request,
            )
        )

        # Strict engineering validation occurs locally.
        strategy = (
            MeshStrategy.model_validate(
                strategy_data
            )
        )

        return (
            strategy,
            "gemini",
        )

    except Exception:

        if not allow_fallback:
            raise

        strategy = (
            deterministic_fallback(
                geometry_analysis=(
                    geometry_analysis
                ),
                cfd_request=(
                    cfd_request
                ),
            )
        )

        return (
            strategy,
            "deterministic_fallback",
        )


# ============================================================
# OUTPUT
# ============================================================

def save_mesh_strategy(
    strategy: MeshStrategy,
    source: str,
    output_path: Path,
) -> None:

    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    payload = {
        "source": source,
        "strategy": (
            strategy.model_dump()
        ),
    }

    output_path.write_text(
        json.dumps(
            payload,
            indent=2,
        ),
        encoding="utf-8",
    )