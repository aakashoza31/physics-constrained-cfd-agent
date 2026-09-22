#!/usr/bin/env python3
"""Natural-language engineering request -> ForwardStep2DSpec.

PROVENANCE
----------
Same plumbing as ``src/agents/nozzle_case_spec_agent.py``: google-genai with a
pydantic ``response_schema``, temperature 0, and an explicit
``LLMCallRecord`` so a fallback can never be mistaken for the model. No second
provider is introduced.

The model proposes. It has no authority over admissibility: the deterministic
scope gate rules on the result, and the validator rules on the finished run.

Defaults the model is allowed to infer are exactly the registered family
defaults (the canonical tutorial values). Every inferred field is recorded in
``inferred_defaults`` so provenance shows what the user did not state.
"""
from __future__ import annotations

import os
import time
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel, Field

from src.agents.llm_provenance import (
    FALLBACK,
    GEMINI,
    LLMCallRecord,
    LLMUnavailable,
    gemini_key_present,
    gemini_model_name,
)
from src.pipeline.forward_step_2d.spec import CANONICAL_SPEC, ForwardStep2DSpec

STAGE = "forward_step_case_spec_interpretation"

# Fields the model may leave unstated; the family default is then used.
INFERABLE = [
    "length",
    "height",
    "step_x",
    "step_height",
    "span",
    "nx",
    "ny",
    "pressure",
    "temperature",
    "end_time",
    "max_co",
    "write_interval",
]


class ForwardStepRequest(BaseModel):
    """Structured interpretation of a forward-step engineering request."""

    case_name: str = Field(description="Short lowercase identifier for the run.")
    summary: str = Field(description="One-line restatement of the request.")

    mach: Optional[float] = Field(default=None, description="Inlet Mach number.")
    step_height: Optional[float] = Field(default=None)
    step_x: Optional[float] = Field(default=None)
    length: Optional[float] = Field(default=None)
    height: Optional[float] = Field(default=None)
    pressure: Optional[float] = Field(default=None)
    temperature: Optional[float] = Field(default=None)
    end_time: Optional[float] = Field(default=None)
    max_co: Optional[float] = Field(default=None)
    nx: Optional[int] = Field(default=None)
    ny: Optional[int] = Field(default=None)

    requests_unsupported_physics: bool = Field(
        default=False,
        description=(
            "True only if the request asks for the SIMULATION ITSELF to model "
            "physics outside inviscid 2D Euler. A question about how the "
            "finished result should be assessed or reported is not physics "
            "and must not set this flag."
        ),
    )
    unsupported_notes: List[str] = Field(default_factory=list)
    reporting_objectives: List[str] = Field(
        default_factory=list,
        description=(
            "Questions the user wants answered ABOUT the completed run, such "
            "as whether a feature is resolved or whether the result is "
            "trustworthy. These are reporting requests, not simulation "
            "requirements, and they do not change the case setup."
        ),
    )
    notes: List[str] = Field(default_factory=list)


SYSTEM_PROMPT = """
You are the case-interpretation agent for a 2D forward-facing-step CFD family.

Convert the engineering request into one structured object matching the schema.

The registered family, which you may not change:
- two-dimensional forward-facing step in a rectangular channel
- inviscid compressible Euler, normalized ideal gas
- supersonic inflow
- OpenFOAM Foundation v14, solver shockFluid
- a fixed numerical recipe (Kurganov fluxes, vanLeer reconstruction, Euler
  time integration). You do not choose schemes, solvers or gas models.

Rules:

1. Copy every number the request states. Do not rescale or convert; this family
   uses normalized units.

2. Leave a field null when the request does not state it. Do not guess. Null
   means "use the registered family default", which is recorded separately.

3. The canonical reference case is: channel length 3, height 1, step at x = 0.6,
   step height 0.2, inlet Mach 3, p = 1, T = 1, end time 4, maxCo 0.2.
   Mention it only if the request refers to it.

4. mach is the inlet Mach number and must be greater than 1 for this family. If
   the request asks for subsonic or incompressible flow, set
   requests_unsupported_physics true and explain in unsupported_notes.

5. Separate the two kinds of thing a request can contain.

   A. SIMULATION REQUIREMENTS: what must be modelled, meshed, solved or
      configured. Only these can be unsupported.
   B. REPORTING OBJECTIVES: what the user wants told about the finished run,
      such as "report whether the shock is resolved", "assess the mesh
      resolution", "say whether the result is trustworthy", "explain the
      accuracy", "summarise the compression structure".

   Put every item of kind B into reporting_objectives, verbatim or closely
   paraphrased. Never set requests_unsupported_physics for an item of kind B.
   Asking for an assessment of a run this family can perform is a supported
   request: the deterministic validator and the reporting stage answer it
   after the solver finishes. It adds no physics.

6. Set requests_unsupported_physics true, with a note, only when a SIMULATION
   REQUIREMENT falls outside the family: turbulence, viscosity or boundary
   layers, heat transfer, combustion, multiphase flow, species transport,
   three-dimensional or spanwise effects, imported CAD, a different solver, or
   different numerical schemes.

7. nx and ny are mesh resolution counts across the full channel length and
   height. Only set them if the request asks for a specific resolution.

8. Do not predict results. Do not state shock angles, pressure ratios or any
   expected answer. This forbids you from ANSWERING an assessment question; it
   does not forbid the user from ASKING one. Record the question in
   reporting_objectives and leave it unanswered.

9. case_name is a short lowercase identifier such as mach2p5_step0p15.

10. Do not use Markdown. Return only the structured JSON object.
"""


def _clean(value: float, places: str = "1E-9") -> float:
    """Remove representation noise from an interpreted quantity."""
    return float(
        Decimal(repr(float(value))).quantize(Decimal(places), rounding=ROUND_HALF_UP)
    )


def _call_gemini(prompt: str) -> ForwardStepRequest:
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    response = client.models.generate_content(
        model=gemini_model_name(),
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            response_mime_type="application/json",
            response_schema=ForwardStepRequest,
            temperature=0,
        ),
    )
    if not response.text:
        raise RuntimeError("Gemini returned an empty forward-step interpretation.")
    return ForwardStepRequest.model_validate_json(response.text)


def to_spec(
    request: ForwardStepRequest,
) -> Tuple[ForwardStep2DSpec, Dict[str, Any]]:
    """Build a spec from the interpretation, recording what was inferred."""
    defaults = CANONICAL_SPEC.to_dict()
    data: Dict[str, Any] = {}
    inferred: List[str] = []
    stated: List[str] = []

    for name in ["mach"] + INFERABLE:
        value = getattr(request, name, None)
        if value is None:
            data[name] = defaults[name]
            if name != "span":
                inferred.append(name)
        else:
            data[name] = (
                int(value)
                if name in ("nx", "ny")
                else _clean(value)
            )
            stated.append(name)

    provenance = {
        "stated_by_user": sorted(stated),
        "inferred_from_family_defaults": sorted(inferred),
        "defaults_source": "canonical OpenFOAM v14 shockFluid/forwardStep tutorial",
    }
    return ForwardStep2DSpec.from_dict(data), provenance


def interpret_request(
    prompt: str,
    *,
    allow_fallback: bool = False,
) -> Tuple[Optional[ForwardStep2DSpec], ForwardStepRequest, Dict[str, Any], LLMCallRecord]:
    """Interpret a request. Returns (spec_or_None, raw, provenance, record).

    ``spec`` is None when the interpretation itself is structurally invalid for
    the family; the orchestrator then reports a deterministic rejection rather
    than constructing an out-of-family case.
    """
    started = time.monotonic()

    if not gemini_key_present():
        if not allow_fallback:
            raise LLMUnavailable(
                "GEMINI_API_KEY is not set and the real LLM path was required. "
                "This agent does not substitute a regex parser for the model."
            )
        raise LLMUnavailable(
            "GEMINI_API_KEY is not set. The forward-step family has no "
            "deterministic request parser: natural-language interpretation is "
            "an LLM responsibility here, and faking it would misrepresent the "
            "agent. Set GEMINI_API_KEY to run the demonstration."
        )

    try:
        raw = _call_gemini(prompt)
        record = LLMCallRecord(
            stage=STAGE,
            source=GEMINI,
            model=gemini_model_name(),
            ok=True,
            latency_s=round(time.monotonic() - started, 3),
        )
    except LLMUnavailable:
        raise
    except Exception as exc:  # noqa: BLE001 - provenance matters more
        raise LLMUnavailable(
            f"Gemini forward-step interpretation failed: {exc}"
        ) from exc

    try:
        spec, provenance = to_spec(raw)
    except ValueError as exc:
        return None, raw, {"construction_error": str(exc)}, record

    return spec, raw, provenance, record
