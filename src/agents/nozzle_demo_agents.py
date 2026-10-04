"""The remaining LLM steps of the end-to-end nozzle demonstration.

  review_mesh_evidence  - the LLM inspects real deterministic mesh evidence and
                          states what the workflow should do next. Its answer is
                          advisory: the deterministic mesh gate has already
                          decided admissibility, and a PROCEED from the model
                          cannot resurrect a mesh that failed checkMesh.

  summarize_case        - the final engineering summary, written only after the
                          deterministic validator has issued its verdict. This
                          is the single stage where the post-hoc quasi-1D
                          comparison is revealed, and it is revealed to the
                          reporter, never to the decision loop.

The mesh review uses a structured response schema; the summary is plain text.
Both run at temperature 0 and return an explicit LLMCallRecord so a
deterministic fallback can never be mistaken for the model.
"""
from __future__ import annotations

import json
import os
import time
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


MESH_STAGE = "mesh_evidence_review"
REPORT_STAGE = "engineering_summary"


class MeshReview(BaseModel):
    assessment: str = Field(
        description="What the mesh evidence shows, in one or two sentences."
    )
    next_action: str = Field(
        description="One of PROCEED_TO_CFD_SETUP, REQUEST_DIAGNOSTIC, STOP."
    )
    reasoning: str
    evidence_used: List[str] = Field(default_factory=list)
    concerns: List[str] = Field(default_factory=list)


MESH_SYSTEM_PROMPT = """
You are the workflow-reasoning agent of a physics-constrained CFD system.

You are shown deterministic mesh evidence for an axisymmetric wedge mesh of a
converging-diverging nozzle that has already been generated and checked by
OpenFOAM utilities.

Decide what the workflow should do next.

Rules:

1. Use only the supplied evidence. Do not invent mesh metrics.

2. checkMesh reporting Mesh OK is necessary, never sufficient. Say so if you
   rely on it.

3. A mesh that failed any deterministic check must not be taken forward. In
   that case next_action is STOP.

4. next_action must be exactly one of PROCEED_TO_CFD_SETUP, REQUEST_DIAGNOSTIC
   or STOP.

5. You do not choose solvers, schemes, boundary conditions or thresholds.

6. Do not estimate or mention exit Mach number, exit pressure, mass flow or any
   analytical result.

7. Do not use Markdown. Return only the structured JSON object.
"""


REPORT_SYSTEM_PROMPT = """
You are the reporting agent of a physics-constrained CFD system.

The deterministic validator has already issued its verdict. You are writing the
engineering summary for a research audience, after the fact.

Rules:

1. The deterministic verdict is authoritative. Never contradict it, never
   soften a FAIL and never describe a rejected case as acceptable.

2. The quasi-1D comparison in this payload is a post-hoc screening comparison
   for a finite-angle conical nozzle. It is not exact truth and it did not
   influence the CFD. Say so when you use it.

3. Report measured values with their units. Do not round away significance.

4. State the scope limits: axisymmetric, inviscid, perfect gas, slip adiabatic
   walls, internal domain only, ambient used for interpretation and not imposed
   at the outlet, single-grid verification at the declared resolution.

5. Do not claim grid convergence, experimental validation or steady-state
   certainty beyond what the deterministic checks establish.

6. Write plain prose with short paragraphs and a short bullet list of key
   numbers. Keep it under 400 words.
"""


def _client():
    from google import genai

    return genai.Client(api_key=os.environ["GEMINI_API_KEY"])


# ----------------------------------------------------------------------
# Mesh evidence review
# ----------------------------------------------------------------------


def _deterministic_mesh_review(evidence: Dict[str, Any]) -> MeshReview:
    passed = bool(evidence.get("mesh_ok")) and bool(
        evidence.get("cell_centres_written")
    )

    return MeshReview(
        assessment=(
            "Deterministic mesh evidence "
            + ("satisfies" if passed else "does not satisfy")
            + " the declared topology, geometry and field-support checks."
        ),
        next_action="PROCEED_TO_CFD_SETUP" if passed else "STOP",
        reasoning=(
            "Produced by the deterministic fallback, not by the LLM. The "
            "decision mirrors the deterministic mesh gate: checkMesh "
            "-allTopology -allGeometry must report Mesh OK and the cell centres "
            "and volumes must have been written."
        ),
        evidence_used=["mesh_ok", "cell_centres_written", "cells"],
        concerns=[]
        if passed
        else ["A deterministic mesh check failed; CFD must not proceed."],
    )


def review_mesh_evidence(
    case_summary: Dict[str, Any],
    mesh_evidence: Dict[str, Any],
    *,
    allow_fallback: bool = False,
) -> Tuple[MeshReview, LLMCallRecord]:
    payload = {
        "task": (
            "Inspect the deterministic mesh evidence and decide the next "
            "workflow step."
        ),
        "case": case_summary,
        "mesh_evidence": mesh_evidence,
        "allowed_actions": [
            "PROCEED_TO_CFD_SETUP",
            "REQUEST_DIAGNOSTIC",
            "STOP",
        ],
    }

    started = time.monotonic()

    if gemini_key_present():
        try:
            from google.genai import types

            client = _client()
            response = client.models.generate_content(
                model=gemini_model_name(),
                contents=json.dumps(payload, indent=2),
                config=types.GenerateContentConfig(
                    system_instruction=MESH_SYSTEM_PROMPT,
                    response_mime_type="application/json",
                    response_schema=MeshReview,
                    temperature=0,
                ),
            )

            if not response.text:
                raise RuntimeError("Gemini returned an empty mesh review.")

            review = MeshReview.model_validate_json(response.text)

            return review, LLMCallRecord(
                stage=MESH_STAGE,
                source=GEMINI,
                model=gemini_model_name(),
                latency_s=round(time.monotonic() - started, 3),
            )

        except Exception as exc:  # noqa: BLE001
            if not allow_fallback:
                raise LLMUnavailable(f"Gemini mesh review failed: {exc}") from exc

            return _deterministic_mesh_review(mesh_evidence), LLMCallRecord(
                stage=MESH_STAGE,
                source=FALLBACK,
                ok=True,
                error=str(exc),
                latency_s=round(time.monotonic() - started, 3),
            )

    if not allow_fallback:
        raise LLMUnavailable(
            "GEMINI_API_KEY is not set and the real LLM path was required."
        )

    return _deterministic_mesh_review(mesh_evidence), LLMCallRecord(
        stage=MESH_STAGE,
        source=FALLBACK,
        ok=True,
        error="GEMINI_API_KEY is not set.",
        latency_s=round(time.monotonic() - started, 3),
    )


# ----------------------------------------------------------------------
# Final engineering summary
# ----------------------------------------------------------------------


def _deterministic_summary(payload: Dict[str, Any]) -> str:
    verdict = payload["deterministic_verdict"]
    measured = payload["measured"]
    theory = payload.get("post_hoc_quasi_1d_comparison", {})
    errors = payload.get("post_hoc_quasi_1d_error_pct", {})
    failed = payload.get("failed_checks", [])

    lines = [
        f"# {payload['case_id']} - engineering summary",
        "",
        "Written by the deterministic fallback reporter, not by the LLM.",
        "",
        f"Deterministic verdict: **{verdict}**.",
        "",
    ]

    if failed:
        lines += [
            "Failed deterministic checks: " + ", ".join(failed) + ".",
            "",
        ]

    lines += ["Measured CFD result at the exit plane:", ""]

    for key, value in measured.items():
        lines.append(f"- {key}: {value}")

    if theory:
        lines += [
            "",
            "Post-hoc quasi-1D screening comparison (not supplied to the "
            "decision loop, and not exact truth for a finite-angle conical "
            "nozzle):",
            "",
        ]
        for key, value in theory.items():
            lines.append(
                f"- {key}: {value} "
                f"(difference {errors.get(key, float('nan')):+.3f}%)"
            )

    lines += [
        "",
        "Scope: axisymmetric wedge, inviscid Euler, calorically perfect air, "
        "adiabatic slip walls, internal domain only. The ambient pressure is "
        "used for regime interpretation and is not imposed at the "
        "computational outlet. This is single-grid verification at the declared "
        "resolution; grid, timestep, wedge-angle and startup sensitivity remain "
        "properties of the frozen canonical reference campaign.",
    ]

    return "\n".join(lines)


def summarize_case(
    payload: Dict[str, Any],
    *,
    allow_fallback: bool = False,
) -> Tuple[str, LLMCallRecord]:
    """Write the post-verdict engineering summary.

    The summary is plain text: the call sets a system instruction and
    temperature 0 but no response schema, so its content is not
    schema-checked.  It never feeds back into a decision.

    ``REPORT_SYSTEM_PROMPT`` is nozzle-specific (quasi-1D comparison, wedge,
    pressure-free outlet).  ``scripts/run_forward_step_2d.py`` reuses this
    function, and therefore the nozzle prompt, for the forward-step family.
    This is a known limitation, reported in the paper walkthrough.
    """
    started = time.monotonic()

    if gemini_key_present():
        try:
            from google.genai import types

            client = _client()
            response = client.models.generate_content(
                model=gemini_model_name(),
                contents=json.dumps(payload, indent=2, default=str),
                config=types.GenerateContentConfig(
                    system_instruction=REPORT_SYSTEM_PROMPT,
                    temperature=0,
                ),
            )

            if not response.text:
                raise RuntimeError("Gemini returned an empty summary.")

            return response.text.strip(), LLMCallRecord(
                stage=REPORT_STAGE,
                source=GEMINI,
                model=gemini_model_name(),
                latency_s=round(time.monotonic() - started, 3),
            )

        except Exception as exc:  # noqa: BLE001
            if not allow_fallback:
                raise LLMUnavailable(f"Gemini summary failed: {exc}") from exc

            return _deterministic_summary(payload), LLMCallRecord(
                stage=REPORT_STAGE,
                source=FALLBACK,
                ok=True,
                error=str(exc),
                latency_s=round(time.monotonic() - started, 3),
            )

    if not allow_fallback:
        raise LLMUnavailable(
            "GEMINI_API_KEY is not set and the real LLM path was required."
        )

    return _deterministic_summary(payload), LLMCallRecord(
        stage=REPORT_STAGE,
        source=FALLBACK,
        ok=True,
        error="GEMINI_API_KEY is not set.",
        latency_s=round(time.monotonic() - started, 3),
    )
