from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from google import genai
from google.genai import types

from src.agents.mesh_planner_agent import MeshStrategy


MODEL_NAME = os.getenv("GEMINI_MODEL", "gemini-3.6-flash")


# ============================================================
# GEMINI-SAFE RESPONSE SCHEMA
# ============================================================


class GeminiMeshAdaptationSchema(BaseModel):
    """
    Plain schema passed to google-genai.

    Keep this model free of gt/ge/le constraints because the Google SDK
    schema transformer can reject some JSON-Schema numeric keywords.
    Strict engineering validation is performed locally after Gemini
    responds.
    """

    accept_mesh: bool

    diagnosis: str
    action: str
    target_regions: list[str]
    rationale: str

    expected_element_effect: str
    expected_quality_effect: str
    expected_throat_node_effect: str

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


# ============================================================
# LOCALLY VALIDATED ADAPTATION RESULT
# ============================================================


class MeshAdaptationProposal(BaseModel):
    accept_mesh: bool

    diagnosis: str
    action: str
    target_regions: list[str]
    rationale: str

    expected_element_effect: str
    expected_quality_effect: str
    expected_throat_node_effect: str

    next_strategy: MeshStrategy


ALLOWED_ACTIONS = {
    "accept",
    "coarsen",
    "refine",
    "rebalance",
    "improve_quality",
}

ALLOWED_EFFECTS = {
    "increase",
    "decrease",
    "similar",
    "uncertain",
}


SYSTEM_PROMPT = """
You are the engineering reasoning layer of an agentic CFD meshing system.

You are NOT merely translating text into JSON.

Your job is to reason like a CFD meshing engineer using:
1. the approved geometry analysis,
2. the user's CFD and meshing request,
3. the current meshing strategy,
4. the actual mesh produced by Gmsh,
5. the hard constraints supplied by the user,
6. the previous adaptation history.

Gmsh is the mesh generator and measurement engine.
Python is the validator, guardrail, and execution layer.
YOU are the reasoning layer that diagnoses the current mesh and proposes the
next engineering meshing strategy.

GENERAL ENGINEERING PRINCIPLES

- More elements are not automatically better.
- Fewer elements are not automatically better.
- A mesh is useful when it provides sufficient resolution and quality for the
  engineering objective at an acceptable computational cost.
- Treat a user-supplied maximum element count as a hard computational-budget
  constraint.
- Treat user-supplied minimum quality and local-resolution requirements as hard
  constraints.

IMPORTANT THROAT-RESOLUTION METRIC SEMANTICS:
- min_throat_nodes means the TOTAL number of mesh nodes counted by the
  deterministic mesher inside a defined 3D throat-region control volume around
  the geometric throat.
- measured_gmsh_result.throat_nodes uses exactly this same definition.
- It does NOT mean "nodes across the throat diameter".
- It does NOT mean "nodes along the throat circumference".
- It does NOT mean "cells across the throat".
- Never derive throat_size_m by dividing throat diameter, circumference, radius,
  or throat length by min_throat_nodes.
- Treat the actual Gmsh measurement as empirical feedback. Use the current
  throat_nodes value and previous trials to reason about how changing
  throat_size_m, throat_padding_m, and other regional sizes affected the mesh.
- If throat_nodes is safely above the required minimum while the element budget
  is violated, you may coarsen expensive regions while preserving enough throat
  resolution.
- If throat_nodes is below the required minimum, prefer targeted throat
  refinement rather than blindly refining the entire mesh.
- Do not assume a fixed analytical relationship between mesh size and throat-node
  count. Gmsh generates the mesh and Python measures the resulting count.

- If a hard constraint was not supplied, do not invent one.
- Among meshes that satisfy the user's hard constraints, prefer a lower-cost
  mesh when it can be obtained without sacrificing required resolution.
- Do not blindly scale every mesh size together. You may reason that some
  regions should be coarsened while important regions remain protected or are
  refined.
- Use the actual Gmsh measurements as the source of truth about the generated
  mesh.
- Use previous trials to avoid repeating unsuccessful strategies or oscillating
  between nearly identical settings.

WHAT YOU MAY CHANGE

You may reason about and propose changes to:
- global_size_m
- throat_size_m
- wall_size_m
- diverging_size_m
- throat_padding_m
- wall_refinement_distance_m
- refine_throat
- refine_walls
- refine_diverging_section
- refine_high_curvature

You may choose where to preserve, increase, decrease, or remove refinement.

WHAT YOU MUST NOT CHANGE

- Do not change the approved CAD geometry.
- Do not change the user's CFD boundary conditions.
- Do not change the user's hard mesh constraints.
- Do not invent physical results that have not yet been produced by OpenFOAM.
- Do not claim an exact shock location before CFD evidence exists.
- A possible shock region may justify cautious pre-CFD refinement, but it is
  only a physics prior until OpenFOAM provides evidence.
- boundary_layer_requested must remain exactly what the structured user request
  says. No-slip walls alone do not imply a prism/boundary-layer mesh.

ACTIONS

Use exactly one of these action strings:

accept
    The current mesh is acceptable for the present pre-CFD objective.

coarsen
    The mesh is unnecessarily expensive or exceeds the computational budget,
    and resolution can be reduced safely.

refine
    The mesh lacks required resolution and additional local resolution is
    needed.

rebalance
    Different regions need different changes, for example coarsen the global
    or wall mesh while protecting throat resolution.

improve_quality
    The primary issue is poor element quality and the sizing/refinement
    transition should be changed to improve it.

IMPORTANT

Return a COMPLETE next mesh strategy even when only one parameter changes.

DETERMINISTIC SINGLE-STEP SAFETY ENVELOPE
- For global_size_m, throat_size_m, wall_size_m, and diverging_size_m,
  each proposed value must remain between 0.25x and 4.0x its CURRENT value.
- This is a Python safety guardrail, not an optimization rule.
- Do not intentionally propose a value outside that interval.
- If stronger coarsening or refinement is needed, reach it over multiple
  measured Gmsh trials rather than one extreme jump.

If accept_mesh is true:
- action must be "accept"
- return the CURRENT mesh strategy unchanged.

If accept_mesh is false:
- action must not be "accept"
- propose a genuinely revised strategy.

Your rationale should be a concise engineering explanation based on the
supplied evidence. Do not provide hidden chain-of-thought or lengthy internal
reasoning. State the diagnosis, engineering justification, and intended effect.

All dimensions are in meters.
Return only the structured response matching the provided schema.
"""


# ============================================================
# GEMINI CLIENT
# ============================================================


def load_gemini() -> genai.Client:
    api_key = os.getenv("GEMINI_API_KEY")

    if not api_key:
        raise RuntimeError(
            "GEMINI_API_KEY is not set. In PowerShell, run:\n"
            '$env:GEMINI_API_KEY="your-real-api-key"'
        )

    return genai.Client(api_key=api_key)


# ============================================================
# PUBLIC ADAPTATION ENTRY POINT
# ============================================================


def propose_mesh_adaptation(
    geometry_analysis: dict[str, Any],
    cfd_request: dict[str, Any],
    current_strategy: MeshStrategy,
    mesh_result: dict[str, Any],
    history: list[dict[str, Any]] | None = None,
    allow_fallback: bool = True,
    response_cache_path: Path | None = None,
) -> tuple[MeshAdaptationProposal, str]:
    """
    Ask Gemini to reason over one measured Gmsh mesh and propose the next
    meshing strategy.

    Returns
    -------
    proposal, source
        source is "gemini" when the LLM produced a valid proposal.
        A conservative deterministic fallback is used only when allowed.
    """

    history = history or []

    payload = {
        "approved_geometry_analysis": geometry_analysis,
        "structured_cfd_request": cfd_request,
        "current_mesh_strategy": current_strategy.model_dump(),
        "measured_gmsh_result": _compact_mesh_result(mesh_result),
        "adaptation_history": history,
        "measurement_semantics": {
            "throat_nodes": (
                "Total mesh nodes counted inside the deterministic 3D "
                "throat-region control volume. This is NOT nodes across "
                "the throat diameter."
            ),
            "min_throat_nodes": (
                "Hard lower bound on that same regional node count when "
                "supplied by the user."
            ),
            "adaptation_rule": (
                "Use measured Gmsh feedback and trial history empirically. "
                "Do not compute throat_size_m as a geometric dimension "
                "divided by min_throat_nodes."
            ),
        },
        "instruction": (
            "Diagnose the measured mesh and decide whether to accept it or "
            "propose the next engineering meshing strategy."
        ),
    }

    try:
        canonical_payload = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
        )

        payload_sha256 = hashlib.sha256(
            canonical_payload.encode("utf-8")
        ).hexdigest()

        response_text: str | None = None
        response_source = "gemini"

        if (
            response_cache_path is not None
            and response_cache_path.exists()
        ):
            try:
                cached = json.loads(
                    response_cache_path.read_text(
                        encoding="utf-8"
                    )
                )

                if (
                    cached.get("payload_sha256")
                    == payload_sha256
                    and isinstance(
                        cached.get("response_text"),
                        str,
                    )
                    and cached["response_text"].strip()
                ):
                    response_text = (
                        cached[
                            "response_text"
                        ]
                    )
                    response_source = (
                        "gemini_cached"
                    )

                    print(
                        "Reusing cached Gemini adaptation response "
                        "for this exact measured trial."
                    )
            except Exception:
                # A malformed/stale cache must never block the live agent.
                response_text = None

        if response_text is None:
            client = load_gemini()

            response = client.models.generate_content(
                model=MODEL_NAME,
                contents=json.dumps(payload, indent=2),
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM_PROMPT,
                    response_mime_type="application/json",
                    response_schema=GeminiMeshAdaptationSchema,
                    temperature=0,
                ),
            )

            if not response.text:
                raise RuntimeError(
                    "Gemini returned an empty mesh-adaptation response."
                )

            response_text = response.text

            # Cache RAW Gemini output before any local validation.
            # If validation code needs repair later, the exact response
            # can be replayed without spending another API request.
            if response_cache_path is not None:
                response_cache_path.parent.mkdir(
                    parents=True,
                    exist_ok=True,
                )

                response_cache_path.write_text(
                    json.dumps(
                        {
                            "model": MODEL_NAME,
                            "payload_sha256": payload_sha256,
                            "payload": payload,
                            "response_text": response_text,
                        },
                        indent=2,
                    ),
                    encoding="utf-8",
                )

        raw = GeminiMeshAdaptationSchema.model_validate_json(
            response_text
        )

        proposal = _validate_and_build_proposal(
            raw=raw,
            geometry_analysis=geometry_analysis,
            cfd_request=cfd_request,
            current_strategy=current_strategy,
            mesh_result=mesh_result,
            history=history,
        )

        return proposal, response_source

    except Exception as exc:
        print()
        print("=" * 68)
        print("GEMINI MESH-ADAPTATION ERROR")
        print("=" * 68)
        print(f"Exception type : {type(exc).__name__}")
        print(f"Exception      : {exc}")
        print("=" * 68)
        print()

        if not allow_fallback:
            raise

        print(
            "Gemini adaptation failed validation/API execution. "
            "Using deterministic fallback for this trial."
        )
        print()

        proposal = _fallback_proposal(
            cfd_request=cfd_request,
            current_strategy=current_strategy,
            mesh_result=mesh_result,
        )

        return proposal, "deterministic_fallback"


# ============================================================
# VALIDATION
# ============================================================


def _normalize_action(
    value: str,
) -> str:
    """
    Normalize a verbose LLM action label to the small local action enum.

    The normalized label is metadata describing Gemini's engineering
    choice; it does not change any mesh-size number.
    """

    text = str(value).strip().lower()

    if text in ALLOWED_ACTIONS:
        return text

    if "accept" in text:
        return "accept"

    if "coars" in text or "reduce" in text:
        return "coarsen"

    if "refin" in text:
        return "refine"

    if "rebalanc" in text or "balance" in text:
        return "rebalance"

    if "quality" in text or "improve" in text:
        return "improve_quality"

    raise ValueError(
        f"Unsupported adaptation action '{value}'. "
        f"Allowed actions: {sorted(ALLOWED_ACTIONS)}"
    )


def _normalize_effect(
    value: str,
) -> str:
    """
    Convert verbose expected-effect prose to:
    increase / decrease / similar / uncertain.

    These expected-effect fields are explanatory metadata only.
    The actual mesh is always generated by Gmsh and measured by Python.
    """

    text = str(value).strip().lower()

    if text in ALLOWED_EFFECTS:
        return text

    uncertain_terms = (
        "uncertain",
        "unknown",
        "unclear",
        "indeterminate",
        "not sure",
    )

    if any(
        term in text
        for term in uncertain_terms
    ):
        return "uncertain"

    decrease_terms = (
        "decrease",
        "decreasing",
        "decreased",
        "reduction",
        "reduce",
        "reduced",
        "lower",
        "lowering",
        "drop",
        "dropping",
        "fewer",
        "less",
        "coarsen",
        "coarser",
    )

    increase_terms = (
        "increase",
        "increasing",
        "increased",
        "higher",
        "rise",
        "rising",
        "grow",
        "growing",
        "more",
        "refine",
        "finer",
        "improve",
        "improvement",
    )

    similar_terms = (
        "similar",
        "same",
        "unchanged",
        "stable",
        "maintain",
        "maintained",
        "preserve",
        "preserved",
        "roughly constant",
        "little change",
        "no significant change",
    )

    has_decrease = any(
        term in text
        for term in decrease_terms
    )

    has_increase = any(
        term in text
        for term in increase_terms
    )

    has_similar = any(
        term in text
        for term in similar_terms
    )

    # When prose contains conflicting directions, retain uncertainty
    # rather than inventing a stronger deterministic interpretation.
    directional_count = sum(
        (
            bool(has_decrease),
            bool(has_increase),
            bool(has_similar),
        )
    )

    if directional_count > 1:
        # A phrase such as "decrease but remain similar" is qualitative.
        return "uncertain"

    if has_decrease:
        return "decrease"

    if has_increase:
        return "increase"

    if has_similar:
        return "similar"

    # Do not crash a valid numeric strategy merely because an explanatory
    # metadata sentence used unexpected wording.
    return "uncertain"


def _validate_and_build_proposal(
    raw: GeminiMeshAdaptationSchema,
    geometry_analysis: dict[str, Any],
    cfd_request: dict[str, Any],
    current_strategy: MeshStrategy,
    mesh_result: dict[str, Any],
    history: list[dict[str, Any]],
) -> MeshAdaptationProposal:
    action = _normalize_action(
        raw.action
    )
    accept_mesh = bool(raw.accept_mesh) or action == "accept"
    

    effects = {
        "expected_element_effect": (
            _normalize_effect(
                raw.expected_element_effect
            )
        ),
        "expected_quality_effect": (
            _normalize_effect(
                raw.expected_quality_effect
            )
        ),
        "expected_throat_node_effect": (
            _normalize_effect(
                raw.expected_throat_node_effect
            )
        ),
    }

    requested_boundary_layer = bool(
        cfd_request.get("mesh", {}).get(
            "boundary_layer_requested",
            False,
        )
    )

    if raw.boundary_layer_requested != requested_boundary_layer:
        print(
            "Deterministic request invariant restored "
            "boundary_layer_requested to the user's value."
        )

    candidate = MeshStrategy(
        global_size_m=float(raw.global_size_m),
        throat_size_m=float(raw.throat_size_m),
        wall_size_m=float(raw.wall_size_m),
        diverging_size_m=float(raw.diverging_size_m),
        throat_padding_m=float(raw.throat_padding_m),
        wall_refinement_distance_m=float(
            raw.wall_refinement_distance_m
        ),
        refine_throat=bool(raw.refine_throat),
        refine_walls=bool(raw.refine_walls),
        refine_diverging_section=bool(
            raw.refine_diverging_section
        ),
        refine_high_curvature=bool(
            raw.refine_high_curvature
        ),
        boundary_layer_requested=(
            requested_boundary_layer
        ),
        rationale=raw.rationale.strip(),
    )

    if accept_mesh:
        # Acceptance refers to the already measured CURRENT mesh.
        # Ignore any accidental numeric edits in the structured response.
        candidate = current_strategy

    (
        candidate,
        guardrail_adjustments,
    ) = _apply_single_step_safety_envelope(
        current=current_strategy,
        candidate=candidate,
    )

    if guardrail_adjustments:
        print(
            "Deterministic safety envelope adjusted Gemini's "
            "numeric proposal:"
        )
        for item in guardrail_adjustments:
            print(f"  - {item}")

    _validate_numeric_safety(
        current=current_strategy,
        candidate=candidate,
        geometry_analysis=geometry_analysis,
    )

    _validate_decision_logic(
        action=action,
        accept_mesh=accept_mesh,
        current_strategy=current_strategy,
        candidate=candidate,
        cfd_request=cfd_request,
        mesh_result=mesh_result,
    )

    _reject_repeated_strategy(
        candidate=candidate,
        current_strategy=current_strategy,
        history=history,
        accept_mesh=accept_mesh,
    )

    return MeshAdaptationProposal(
        accept_mesh=accept_mesh,
        diagnosis=raw.diagnosis.strip(),
        action=action,
        target_regions=[
            str(item).strip()
            for item in raw.target_regions
            if str(item).strip()
        ],
        rationale=raw.rationale.strip(),
        expected_element_effect=effects[
            "expected_element_effect"
        ],
        expected_quality_effect=effects[
            "expected_quality_effect"
        ],
        expected_throat_node_effect=effects[
            "expected_throat_node_effect"
        ],
        next_strategy=candidate,
    )


def _apply_single_step_safety_envelope(
    current: MeshStrategy,
    candidate: MeshStrategy,
) -> tuple[MeshStrategy, list[str]]:
    """
    Deterministically project only the four mesh-size controls into
    the already-declared 0.25x..4.0x single-step safety envelope.

    This is not an optimizer. It does not decide whether to refine,
    coarsen, rebalance, or accept. Gemini still makes that engineering
    decision. Python only prevents one unsafe numeric jump from
    terminating the whole pipeline.

    The refinement invariants are then restored conservatively:
    when a local refinement flag is enabled, its local size cannot be
    larger than the global size.
    """

    data = candidate.model_dump()
    adjustments: list[str] = []

    fields = (
        "global_size_m",
        "throat_size_m",
        "wall_size_m",
        "diverging_size_m",
    )

    for name in fields:
        old_value = float(
            getattr(
                current,
                name,
            )
        )
        proposed = float(
            data[name]
        )

        lower = (
            0.25
            * old_value
        )
        upper = (
            4.0
            * old_value
        )

        clipped = min(
            max(
                proposed,
                lower,
            ),
            upper,
        )

        if not math.isclose(
            clipped,
            proposed,
            rel_tol=1e-12,
            abs_tol=1e-15,
        ):
            adjustments.append(
                f"{name}: {proposed:.12g} -> {clipped:.12g} "
                f"(allowed range {lower:.12g}..{upper:.12g})"
            )
            data[name] = (
                clipped
            )

    # Preserve the semantic meaning of enabled local refinement.
    global_size = float(
        data[
            "global_size_m"
        ]
    )

    local_rules = (
        (
            "refine_throat",
            "throat_size_m",
        ),
        (
            "refine_walls",
            "wall_size_m",
        ),
        (
            "refine_diverging_section",
            "diverging_size_m",
        ),
    )

    for flag_name, size_name in local_rules:
        if (
            bool(
                data[
                    flag_name
                ]
            )
            and float(
                data[
                    size_name
                ]
            )
            > global_size
        ):
            previous = float(
                data[
                    size_name
                ]
            )
            data[
                size_name
            ] = (
                global_size
            )
            adjustments.append(
                f"{size_name}: {previous:.12g} -> "
                f"{global_size:.12g} to preserve "
                f"{flag_name}=True"
            )

    normalized = (
        MeshStrategy
        .model_validate(
            data
        )
    )

    return (
        normalized,
        adjustments,
    )


def _validate_numeric_safety(
    current: MeshStrategy,
    candidate: MeshStrategy,
    geometry_analysis: dict[str, Any],
) -> None:
    positive_values = {
        "global_size_m": candidate.global_size_m,
        "throat_size_m": candidate.throat_size_m,
        "wall_size_m": candidate.wall_size_m,
        "diverging_size_m": candidate.diverging_size_m,
        "wall_refinement_distance_m": (
            candidate.wall_refinement_distance_m
        ),
    }

    for name, value in positive_values.items():
        if not math.isfinite(float(value)) or float(value) <= 0.0:
            raise ValueError(
                f"{name} must be finite and positive."
            )

    if (
        not math.isfinite(float(candidate.throat_padding_m))
        or candidate.throat_padding_m < 0.0
    ):
        raise ValueError(
            "throat_padding_m must be finite and nonnegative."
        )

    # Local refinement sizes must actually be local refinements when enabled.
    if (
        candidate.refine_throat
        and candidate.throat_size_m > candidate.global_size_m
    ):
        raise ValueError(
            "refine_throat=True requires throat_size_m <= global_size_m."
        )

    if (
        candidate.refine_walls
        and candidate.wall_size_m > candidate.global_size_m
    ):
        raise ValueError(
            "refine_walls=True requires wall_size_m <= global_size_m."
        )

    if (
        candidate.refine_diverging_section
        and candidate.diverging_size_m > candidate.global_size_m
    ):
        raise ValueError(
            "refine_diverging_section=True requires "
            "diverging_size_m <= global_size_m."
        )

    # Guardrail only, not an optimizer: prevent a single LLM step from
    # proposing an absurd several-orders-of-magnitude jump.
    current_values = {
        "global_size_m": current.global_size_m,
        "throat_size_m": current.throat_size_m,
        "wall_size_m": current.wall_size_m,
        "diverging_size_m": current.diverging_size_m,
    }

    candidate_values = {
        "global_size_m": candidate.global_size_m,
        "throat_size_m": candidate.throat_size_m,
        "wall_size_m": candidate.wall_size_m,
        "diverging_size_m": candidate.diverging_size_m,
    }

    for name, old_value in current_values.items():
        new_value = candidate_values[name]
        ratio = new_value / old_value

        if ratio < 0.25 or ratio > 4.0:
            raise ValueError(
                f"{name} changed by an unsafe single-step ratio "
                f"({ratio:.3f}). Allowed guardrail range is "
                "0.25x to 4.0x the current value."
            )

    bbox = geometry_analysis.get("bounding_box")

    if isinstance(bbox, (list, tuple)) and len(bbox) >= 6:
        length = abs(float(bbox[3]) - float(bbox[0]))

        if length > 0.0:
            if candidate.throat_padding_m > length:
                raise ValueError(
                    "throat_padding_m cannot exceed the nozzle length."
                )

            if candidate.wall_refinement_distance_m > length:
                raise ValueError(
                    "wall_refinement_distance_m cannot exceed "
                    "the nozzle length."
                )


def _validate_decision_logic(
    action: str,
    accept_mesh: bool,
    current_strategy: MeshStrategy,
    candidate: MeshStrategy,
    cfd_request: dict[str, Any],
    mesh_result: dict[str, Any],
) -> None:
    violations = _constraint_violations(
        cfd_request=cfd_request,
        mesh_result=mesh_result,
    )

    if accept_mesh:
        if action != "accept":
            raise ValueError(
                "accept_mesh=True requires action='accept'."
            )

        if violations:
            raise ValueError(
                "Gemini attempted to accept a mesh that violates "
                f"hard user constraints: {violations}"
            )

        if not _strategies_equal(
            current_strategy,
            candidate,
        ):
            raise ValueError(
                "When accepting a mesh, Gemini must return the current "
                "strategy unchanged."
            )

        return

    if action == "accept":
        raise ValueError(
            "action='accept' requires accept_mesh=True."
        )

    if _strategies_equal(
        current_strategy,
        candidate,
    ):
        raise ValueError(
            "A non-accept adaptation proposal must genuinely change "
            "the mesh strategy."
        )

    # Python is not deciding the engineering action here.
    # It only prevents logically impossible acceptance of a known failure.
    # Gemini remains free to choose coarsen/refine/rebalance/quality actions.


def _constraint_violations(
    cfd_request: dict[str, Any],
    mesh_result: dict[str, Any],
) -> list[str]:
    mesh_request = cfd_request.get("mesh", {})

    max_elements = mesh_request.get("max_elements")
    min_quality = mesh_request.get("min_quality")
    min_throat_nodes = mesh_request.get(
        "min_throat_nodes"
    )

    elements = int(mesh_result["elements_3d"])
    quality = float(
        mesh_result["minimum_quality_minSICN"]
    )
    throat_nodes = int(mesh_result["throat_nodes"])

    violations: list[str] = []

    if (
        max_elements is not None
        and elements > int(max_elements)
    ):
        violations.append(
            "element budget exceeded"
        )

    if (
        min_quality is not None
        and quality < float(min_quality)
    ):
        violations.append(
            "minimum quality below target"
        )

    if (
        min_throat_nodes is not None
        and throat_nodes < int(min_throat_nodes)
    ):
        violations.append(
            "throat-node target not reached"
        )

    return violations


def _reject_repeated_strategy(
    candidate: MeshStrategy,
    current_strategy: MeshStrategy,
    history: list[dict[str, Any]],
    accept_mesh: bool,
) -> None:
    if accept_mesh:
        return

    signature = _strategy_signature(candidate)

    if signature == _strategy_signature(
        current_strategy
    ):
        raise ValueError(
            "Gemini repeated the current strategy."
        )

    for record in history:
        previous = record.get("strategy")

        if not isinstance(previous, dict):
            continue

        if _dict_strategy_signature(previous) == signature:
            raise ValueError(
                "Gemini proposed a strategy already executed "
                "in the adaptation history."
            )


# ============================================================
# FALLBACK
# ============================================================


def _fallback_proposal(
    cfd_request: dict[str, Any],
    current_strategy: MeshStrategy,
    mesh_result: dict[str, Any],
) -> MeshAdaptationProposal:
    """
    Conservative backup only.

    The intended architecture uses Gemini as the reasoning layer.
    This fallback exists for robustness when allow_fallback=True and
    should always be reported as deterministic_fallback.
    """

    violations = _constraint_violations(
        cfd_request=cfd_request,
        mesh_result=mesh_result,
    )

    if not violations:
        return MeshAdaptationProposal(
            accept_mesh=True,
            diagnosis=(
                "Current mesh satisfies all supplied hard constraints."
            ),
            action="accept",
            target_regions=[],
            rationale=(
                "Fallback accepts the already feasible mesh rather than "
                "performing unsupported engineering reasoning."
            ),
            expected_element_effect="similar",
            expected_quality_effect="similar",
            expected_throat_node_effect="similar",
            next_strategy=current_strategy,
        )

    factor = 1.25

    candidate = MeshStrategy(
        global_size_m=current_strategy.global_size_m * factor,
        throat_size_m=current_strategy.throat_size_m * factor,
        wall_size_m=current_strategy.wall_size_m * factor,
        diverging_size_m=(
            current_strategy.diverging_size_m * factor
        ),
        throat_padding_m=current_strategy.throat_padding_m,
        wall_refinement_distance_m=(
            current_strategy.wall_refinement_distance_m
        ),
        refine_throat=current_strategy.refine_throat,
        refine_walls=current_strategy.refine_walls,
        refine_diverging_section=(
            current_strategy.refine_diverging_section
        ),
        refine_high_curvature=(
            current_strategy.refine_high_curvature
        ),
        boundary_layer_requested=(
            current_strategy.boundary_layer_requested
        ),
        rationale=(
            "Conservative deterministic fallback used because Gemini "
            "adaptation was unavailable or invalid."
        ),
    )

    return MeshAdaptationProposal(
        accept_mesh=False,
        diagnosis=(
            "Current mesh violates one or more hard constraints."
        ),
        action="coarsen",
        target_regions=["global_mesh"],
        rationale=(
            "Fallback applies only a conservative uniform coarsening "
            "step. Gemini should be used for the intended engineering "
            "reasoning workflow."
        ),
        expected_element_effect="decrease",
        expected_quality_effect="uncertain",
        expected_throat_node_effect="decrease",
        next_strategy=candidate,
    )


# ============================================================
# SERIALIZATION
# ============================================================


def save_adaptation_proposal(
    proposal: MeshAdaptationProposal,
    source: str,
    output_path: Path,
) -> None:
    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    payload = {
        "source": source,
        "proposal": proposal.model_dump(),
    }

    output_path.write_text(
        json.dumps(
            payload,
            indent=2,
        ),
        encoding="utf-8",
    )


# ============================================================
# COMPACT INPUT / SIGNATURE HELPERS
# ============================================================


def _compact_mesh_result(
    mesh_result: dict[str, Any],
) -> dict[str, Any]:
    return {
        "nodes": mesh_result.get("nodes"),
        "elements_3d": mesh_result.get(
            "elements_3d"
        ),
        "minimum_quality_minSICN": (
            mesh_result.get(
                "minimum_quality_minSICN"
            )
        ),
        "average_quality_minSICN": (
            mesh_result.get(
                "average_quality_minSICN"
            )
        ),
        "throat_nodes": mesh_result.get(
            "throat_nodes"
        ),
        "constraints": mesh_result.get(
            "constraints"
        ),
        "feasible_initial_mesh": (
            mesh_result.get(
                "feasible_initial_mesh"
            )
        ),
        "violations": mesh_result.get(
            "violations"
        ),
        "boundary_layer_status": (
            mesh_result.get(
                "boundary_layer_status"
            )
        ),
    }


def _strategies_equal(
    first: MeshStrategy,
    second: MeshStrategy,
) -> bool:
    return (
        _strategy_signature(first)
        == _strategy_signature(second)
    )


def _strategy_signature(
    strategy: MeshStrategy,
) -> tuple[Any, ...]:
    return (
        round(float(strategy.global_size_m), 12),
        round(float(strategy.throat_size_m), 12),
        round(float(strategy.wall_size_m), 12),
        round(float(strategy.diverging_size_m), 12),
        round(float(strategy.throat_padding_m), 12),
        round(
            float(
                strategy.wall_refinement_distance_m
            ),
            12,
        ),
        bool(strategy.refine_throat),
        bool(strategy.refine_walls),
        bool(
            strategy.refine_diverging_section
        ),
        bool(strategy.refine_high_curvature),
        bool(strategy.boundary_layer_requested),
    )


def _dict_strategy_signature(
    strategy: dict[str, Any],
) -> tuple[Any, ...]:
    return (
        round(float(strategy["global_size_m"]), 12),
        round(float(strategy["throat_size_m"]), 12),
        round(float(strategy["wall_size_m"]), 12),
        round(float(strategy["diverging_size_m"]), 12),
        round(float(strategy["throat_padding_m"]), 12),
        round(
            float(
                strategy[
                    "wall_refinement_distance_m"
                ]
            ),
            12,
        ),
        bool(strategy["refine_throat"]),
        bool(strategy["refine_walls"]),
        bool(
            strategy[
                "refine_diverging_section"
            ]
        ),
        bool(strategy["refine_high_curvature"]),
        bool(
            strategy[
                "boundary_layer_requested"
            ]
        ),
    )
