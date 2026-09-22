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

4. "reached_requested_end_time" false means the run stopped before the horizon
   the specification asked for. On an otherwise healthy run that is the normal
   reason to propose CONTINUE_RUN.

5. Propose exactly one action from the allowed list. Do not propose changing the
   solver, the flux scheme, the reconstruction or the gas model: those are fixed
   for this family and you cannot alter them.

6. ACCEPT means "the evidence looks acceptable to me". A deterministic validator
   decides actual acceptance; if its checks fail, your ACCEPT will be refused.

7. REQUEST_CLARIFICATION requires a concrete question in clarification_question.

8. Do not use Markdown. Return only the structured JSON object.
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
                "requested_end_time": spec.end_time,
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
            "requested_end_time": d.get("requested_end_time"),
            "final_time": d.get("final_time"),
            "reached_requested_end_time": d.get("reached_requested_end_time"),
            "saved_states": d.get("saved_times"),
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
    )

    return decision, gate, record, payload
