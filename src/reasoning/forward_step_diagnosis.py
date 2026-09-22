#!/usr/bin/env python3
"""Reference-blind LLM diagnosis for the 2D forward-step family.

PROVENANCE
----------
Mirrors ``src/reasoning/nozzle_diagnosis.py``: build a payload, call the model
with a structured schema, then run the deterministic action validator on
whatever it proposes. The model's answer is advisory in both paths.

REFERENCE-BLINDNESS
-------------------
``build_evidence_payload`` strips every reference comparison and every
canonical-answer hint before the model sees anything. The model reasons from
the evidence a genuinely new run would legitimately have: solver health, the
transient balance, field ranges, Courant behaviour, measured compression
structure and the rendered field images. It is not told what the canonical
solution looks like, and it is not told whether this spec is the canonical one.
"""
from __future__ import annotations

import copy
import json
import os
import time
from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel, Field

from src.agents.llm_provenance import (
    GEMINI,
    LLMCallRecord,
    LLMUnavailable,
    gemini_key_present,
    gemini_model_name,
)
from src.pipeline.forward_step_2d.spec import ForwardStep2DSpec
from src.reasoning.forward_step_actions import (
    ActionValidation,
    ForwardStepAction,
    ForwardStepDiagnosis,
    validate_action,
)

STAGE = "forward_step_reference_blind_diagnosis"

# Keys that would leak a known answer or a reference comparison.
WITHHELD_KEYS = {
    "reference_comparison",
    "canonical_case",
    "stationary_normal_shock_sanity",
}


class ForwardStepDecision(BaseModel):
    diagnosis: str = Field(description="One of the allowed diagnosis labels.")
    reasoning_summary: str = Field(description="Two or three sentences, no hidden reasoning.")
    evidence_used: List[str] = Field(default_factory=list)

    # The two facts that decide between CONTINUE_RUN and EXTEND_END_TIME.
    # Requiring them to be stated before the action is chosen makes the
    # distinction part of the contract rather than something the model may
    # skip, and the orchestrator records whether each restatement matched the
    # deterministic evidence.
    current_horizon_reached: bool = Field(
        default=False,
        description=(
            "True if the solver reached the end time this execution was asked "
            "for (horizon.reached_current_requested_end_time in the evidence)."
        ),
    )
    final_target_reached: bool = Field(
        default=False,
        description=(
            "True if the run has reached the final target horizon "
            "(horizon.reached_final_target_end_time in the evidence)."
        ),
    )

    action: str = Field(description="One of the allowed action labels.")
    clarification_question: Optional[str] = Field(default=None)
    confidence: str = Field(default="medium", description="low, medium or high.")


SYSTEM_PROMPT = """
You are the CFD reasoning agent for a 2D forward-facing-step family solved with
OpenFOAM Foundation v14 shockFluid (inviscid compressible Euler).

You are shown evidence from one run: solver health, transient diagnostics,
conservation measurements, field ranges, measured compression structure, and
rendered images of the actual fields.

Decide what the workflow should do next.

Rules:

1. Use only the supplied evidence. Do not invent numbers and do not assume a
   known reference answer; you have not been given one.

2. This is a TRANSIENT benchmark. The solution is expected to still be evolving
   at the end of the run. Do NOT diagnose a healthy evolving transient as a
   failure, and do not ask for a steady state.

3. Images help you localize structure qualitatively. They cannot override a
   hard numerical failure. If the numbers say the run is unhealthy, say so even
   if the pictures look plausible.

4. TWO HORIZONS. Read both before choosing an action, and state both in
   current_horizon_reached and final_target_reached.

     current_requested_end_time  the end time THIS execution was asked for
     final_target_end_time       the horizon final scientific acceptance needs

   They are usually different. A workflow may run to an early horizon first
   and advance toward the final target in bounded steps.

5. The action follows from those two facts, and confusing them stalls the
   workflow:

     reached_current_requested_end_time == false
       The execution stopped short of its OWN horizon. There is an outstanding
       execution to finish.
       -> CONTINUE_RUN

     reached_current_requested_end_time == true
     and reached_final_target_end_time == false
       The execution finished what it was asked to do, but the run has not
       reached the horizon acceptance requires. There is nothing to resume;
       the horizon itself must move.
       -> EXTEND_END_TIME

     both true, evidence healthy
       -> ACCEPT

   CONTINUE_RUN on a run that already reached its current horizon will be
   refused: there is nothing left to resume toward.

6. Propose exactly one action from the allowed list. Do not propose changing the
   solver, the flux scheme, the reconstruction or the gas model: those are fixed
   for this family and you cannot alter them.

7. Passing every hard check does NOT mean the run is finished. It means the
   state that exists is numerically and physically healthy. A flawless solution
   at an early horizon is a partial realization of the benchmark, and
   deterministic_status will say so
   (CURRENT_STATE_HEALTHY_TARGET_NOT_REACHED).

8. ACCEPT means "the evidence looks acceptable to me". A deterministic validator
   decides actual acceptance, and it requires the final target horizon as well
   as the hard checks; if either is outstanding, your ACCEPT will be refused.

9. MESH RESOLUTION. mesh_resolution says how fine the current grid is and
   whether the request asked for a resolution assessment.

   A solution that passes every hard check has been shown to be healthy ON THE
   GRID IT WAS COMPUTED ON. That is not the same as showing the answer no
   longer depends on the grid. When
   mesh_resolution.sensitivity_assessment_requested is true and
   mesh_resolution.sensitivity reports that the cross-grid requirement is not
   met, the missing evidence is another grid, and REFINE_MESH is the action
   that produces it.

   REFINE_MESH maps to one registered refinement operation. You do not choose a
   refinement factor, a cell count, a geometry or any dictionary entry, and you
   cannot propose a different mesh. A refined grid is a fresh solve from the
   physical initial condition, not a continuation.

   Do not propose REFINE_MESH for a failure that is not about spatial
   resolution: a broken mesh, a wrong inlet state, an edited recipe or a
   crashed solver are not fixed by more cells, and the gate will refuse it.

10. REQUEST_CLARIFICATION requires a concrete question in clarification_question.

11. Do not use Markdown. Return only the structured JSON object.
"""


def _strip(obj: Any) -> Any:
    """Recursively drop reference/answer keys."""
    if isinstance(obj, dict):
        return {
            k: _strip(v)
            for k, v in obj.items()
            if k not in WITHHELD_KEYS
        }
    if isinstance(obj, list):
        return [_strip(v) for v in obj]
    return obj


def build_evidence_payload(
    spec: ForwardStep2DSpec,
    diagnostics: Dict[str, Any],
    validation: Dict[str, Any],
    *,
    images: Optional[Dict[str, str]] = None,
    visual_observation: Optional[Dict[str, Any]] = None,
    iterations_used: int = 0,
    max_iterations: int = 4,
    sensitivity: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Assemble the reference-blind packet handed to the model."""
    d = _strip(copy.deepcopy(diagnostics))
    v = _strip(copy.deepcopy(validation))

    payload = {
        "task": (
            "Diagnose this 2D forward-step run and choose the next workflow "
            "action from the allowed list."
        ),
        "case": {
            "family": spec.family,
            "physics": spec.physics,
            "geometry": {
                "length": spec.length,
                "height": spec.height,
                "step_x": spec.step_x,
                "step_height": spec.step_height,
            },
            "inflow": {
                "mach": spec.mach,
                "pressure": spec.pressure,
                "temperature": spec.temperature,
            },
            "resolution": {"nx": spec.nx, "ny": spec.ny, "cells": spec.cells},
            "run_control": {
                "initial_execution_end_time": spec.initial_execution_end_time,
                "current_requested_end_time": spec.end_time,
                "final_target_end_time": spec.final_target_end_time,
                "max_co": spec.max_co,
            },
        },
        "solver_health": {
            k: d.get(k)
            for k in (
                "solver_completed",
                "fatal_error",
                "finite_all_saved",
                "positive_all_saved",
                "courant_finite_positive",
                "steps",
                "runtime_seconds",
                "warnings",
            )
        },
        "horizon": {
            "initial_execution_end_time": spec.initial_execution_end_time,
            "current_requested_end_time": d.get("requested_end_time"),
            "final_target_end_time": spec.final_target_end_time,
            "final_time": d.get("final_time"),
            "reached_current_requested_end_time": d.get(
                "reached_requested_end_time"
            ),
            "reached_final_target_end_time": bool(
                float(d.get("final_time") or 0.0)
                >= float(spec.final_target_end_time) - 1e-9
            ),
            "saved_states": d.get("saved_times"),
            "note": (
                "current_requested_end_time is what this execution was asked "
                "for. final_target_end_time is what acceptance requires. "
                "CONTINUE_RUN finishes an outstanding execution; "
                "EXTEND_END_TIME moves the horizon after one finished."
            ),
        },
        "mesh": {
            k: d.get(k)
            for k in (
                "mesh_ok",
                "two_solution_directions",
                "mesh_failed_step",
                "cells",
                "cell_count_matches_spec",
                "max_nonorthogonality",
                "max_skewness",
                "max_aspect_ratio",
            )
        },
        "field_ranges": d.get("final_ranges"),
        "minima_every_step": d.get("minima_every_step"),
        "courant": d.get("Co"),
        "transient_conservation": d.get("mass"),
        "transient_evolution": d.get("transient_evolution"),
        "measured_compression_structure": d.get("shock"),
        "deterministic_checks": v.get("hard_checks"),
        "deterministic_failed_checks": v.get("failed_checks"),
        "deterministic_status": v.get("status"),
        "hard_checks_status": v.get("hard_checks_status"),
        "final_acceptance": v.get("final_acceptance"),
        "mesh_resolution": {
            "refinement_level": spec.refinement_level,
            "cells": spec.cells,
            "dx": spec.dx,
            "dy": spec.dy,
            "sensitivity_assessment_requested": (
                spec.sensitivity_assessment_requested
            ),
            **({"sensitivity": _strip(copy.deepcopy(sensitivity))}
               if sensitivity else {}),
        },
        "iterations_used": iterations_used,
        "max_iterations": max_iterations,
        "allowed_diagnoses": [x.value for x in ForwardStepDiagnosis],
        "allowed_actions": [x.value for x in ForwardStepAction],
        "important_instruction": (
            "No reference or benchmark solution is provided. Do not infer one. "
            "This is a transient problem; an evolving solution is expected."
        ),
    }

    if images:
        payload["images_supplied"] = sorted(images)
    if visual_observation:
        payload["visual_observation"] = _strip(visual_observation)

    # Fail closed: refuse to hand over anything carrying a reference answer.
    text = json.dumps(payload)
    for key in WITHHELD_KEYS:
        if key in text:
            raise ValueError(f"Reference material leaked into the payload: {key}")

    return payload


def _call_gemini(payload: Dict[str, Any]) -> ForwardStepDecision:
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    response = client.models.generate_content(
        model=gemini_model_name(),
        contents=json.dumps(payload, indent=2, default=str),
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            response_mime_type="application/json",
            response_schema=ForwardStepDecision,
            temperature=0,
        ),
    )
    if not response.text:
        raise RuntimeError("Gemini returned an empty forward-step diagnosis.")
    return ForwardStepDecision.model_validate_json(response.text)


def diagnose(
    spec: ForwardStep2DSpec,
    diagnostics: Dict[str, Any],
    validation: Dict[str, Any],
    *,
    images: Optional[Dict[str, str]] = None,
    visual_observation: Optional[Dict[str, Any]] = None,
    max_end_time: float,
    iterations_used: int,
    max_iterations: int,
    sensitivity: Optional[Dict[str, Any]] = None,
) -> Tuple[ForwardStepDecision, ActionValidation, LLMCallRecord, Dict[str, Any]]:
    """Reference-blind diagnosis followed by the deterministic action gate."""
    payload = build_evidence_payload(
        spec,
        diagnostics,
        validation,
        images=images,
        visual_observation=visual_observation,
        iterations_used=iterations_used,
        max_iterations=max_iterations,
        sensitivity=sensitivity,
    )

    if not gemini_key_present():
        raise LLMUnavailable(
            "GEMINI_API_KEY is not set. The diagnosis stage is an LLM "
            "responsibility in this agent and is not simulated."
        )

    started = time.monotonic()
    try:
        decision = _call_gemini(payload)
    except Exception as exc:  # noqa: BLE001
        raise LLMUnavailable(f"Gemini forward-step diagnosis failed: {exc}") from exc

    record = LLMCallRecord(
        stage=STAGE,
        source=GEMINI,
        model=gemini_model_name(),
        ok=True,
        latency_s=round(time.monotonic() - started, 3),
    )

    gate = validate_action(
        decision.action,
        spec,
        diagnostics,
        validation,
        max_end_time=max_end_time,
        iterations_used=iterations_used,
        max_iterations=max_iterations,
        clarification=decision.clarification_question,
        sensitivity=sensitivity,
    )

    return decision, gate, record, payload
