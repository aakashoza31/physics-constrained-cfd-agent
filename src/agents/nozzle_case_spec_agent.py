"""Natural-language engineering request -> structured nozzle case specification.

This is the first real LLM step of the end-to-end demonstration.  The model
reads the engineering request and returns a structured case object.  It has no
authority over whether that case is admissible: the deterministic scope gate
(src/reasoning/nozzle_scope_gate.py) decides that afterwards, and the
deterministic validator decides acceptance at the end.

The Gemini plumbing follows the pattern already used by
src/agents/cfd_request_agent.py (structured output, temperature 0, pydantic
schema).  No second provider is introduced.

The deterministic fallback parses the request with explicit regular expressions.
It is a real parser, not a replay of a stored case, and its use is always
reported as ``deterministic_fallback`` so it can never be mistaken for the LLM.
"""
from __future__ import annotations

import os
import re
import time
from decimal import Decimal, ROUND_HALF_UP
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
from src.pipeline.nozzle.spec import NozzleCaseSpec


STAGE = "case_spec_interpretation"


class NozzleCaseRequest(BaseModel):
    """Structured interpretation of the engineering request."""

    case_id: str = Field(description="Short machine-friendly identifier.")
    description: str = Field(description="One-line restatement of the request.")

    inlet_radius_m: float
    throat_radius_m: float
    exit_radius_m: float

    inlet_straight_m: float
    converging_m: float
    throat_m: float
    diverging_m: float
    outlet_straight_m: float

    total_pressure_pa: float
    total_temperature_k: float
    ambient_pressure_pa: float

    gamma: float
    gas_constant_j_per_kg_k: float

    physics_model: str
    wall_model: str
    geometry_family: str

    ambient_imposed_at_exit: bool

    notes: List[str] = Field(default_factory=list)


SYSTEM_PROMPT = """
You are the case-interpretation agent of a physics-constrained CFD system for
axisymmetric converging-diverging nozzles.

Your only job is to convert the engineering request into one structured case
object matching the supplied schema.

Rules:

1. Copy every numerical value from the request exactly. Convert units only:
   millimetres to metres, kilopascals to pascals, bar to pascals.

2. Never invent a value that the request does not state. If the request gives
   no ambient or back pressure, use 30000 Pa and say so in notes.

3. Distinguish total (stagnation, reservoir) from static pressure and
   temperature. The reservoir values belong in total_pressure_pa and
   total_temperature_k. A stated downstream, back or ambient pressure belongs
   in ambient_pressure_pa.

4. ambient_imposed_at_exit must be false unless the request explicitly demands
   that a fixed static pressure be imposed at the computational outlet. A
   request that merely states a back pressure or an ambient environment does
   NOT ask for that.

5. physics_model must be "inviscid_euler" for inviscid or Euler flow.
   wall_model must be "adiabatic_slip" for adiabatic slip walls.
   geometry_family must be "conical" for a conical nozzle.

6. gamma and gas_constant_j_per_kg_k come from the request. For air these are
   normally 1.4 and 287.

7. case_id must be a short lowercase identifier derived from the request, for
   example nozzle_exit_0p0370 or nozzle_p0_220kpa.

8. Do not choose a solver, a mesh size, a timestep or a boundary-condition
   implementation. Those are not yours to decide.

9. Do not estimate, predict or mention exit Mach number, exit pressure, mass
   flow or any analytical result.

10. Do not use Markdown. Return only the structured JSON object.
"""


# ----------------------------------------------------------------------
# Deterministic fallback parser
# ----------------------------------------------------------------------

_NUM = r"([-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?)"


def _find_length_m(text: str, *labels: str) -> Optional[float]:
    for label in labels:
        pattern = (
            re.escape(label)
            + r"[^0-9\-+]{0,20}"
            + _NUM
            + r"\s*(mm|millimet(?:re|er)s?|m\b|metres?|meters?)"
        )
        m = re.search(pattern, text, re.I)

        if m:
            unit = m.group(2).lower()

            # Exact decimal conversion: 32.6 mm must become 0.0326 m, not
            # 0.032600000000000004. A single ulp here changes every generated
            # dictionary and breaks equivalence with the frozen reference.
            quantity = Decimal(m.group(1))

            if unit.startswith("mm") or "milli" in unit:
                quantity = quantity / Decimal(1000)

            return float(quantity)

    return None


def _find_pressure_pa(text: str, *labels: str) -> Optional[float]:
    for label in labels:
        pattern = (
            re.escape(label)
            + r"[^0-9\-+]{0,20}"
            + _NUM
            + r"\s*(kpa|pa|bar|mpa)"
        )
        m = re.search(pattern, text, re.I)

        if m:
            unit = m.group(2).lower()
            factor = {"pa": 1, "kpa": 1000, "mpa": 1000000, "bar": 100000}[unit]
            return float(Decimal(m.group(1)) * Decimal(factor))

    return None


def _find_temperature_k(text: str, *labels: str) -> Optional[float]:
    for label in labels:
        pattern = re.escape(label) + r"[^0-9\-+]{0,20}" + _NUM + r"\s*(k\b|kelvin)"
        m = re.search(pattern, text, re.I)

        if m:
            return float(m.group(1))

    return None


def deterministic_fallback(prompt: str) -> NozzleCaseRequest:
    """Explicit regex interpretation of the engineering request.

    This never returns a stored case. If a required quantity is missing from
    the request, it raises rather than silently substituting the canonical
    value.
    """
    text = re.sub(r"\s+", " ", prompt)

    required = {
        "inlet_radius_m": _find_length_m(text, "inlet radius"),
        "throat_radius_m": _find_length_m(text, "throat radius"),
        "exit_radius_m": _find_length_m(
            text, "outlet radius", "exit radius"
        ),
        "inlet_straight_m": _find_length_m(text, "inlet straight length"),
        "converging_m": _find_length_m(text, "converging length"),
        "throat_m": _find_length_m(text, "throat length"),
        "diverging_m": _find_length_m(text, "diverging length"),
        "outlet_straight_m": _find_length_m(text, "outlet straight length"),
        "total_pressure_pa": _find_pressure_pa(
            text,
            "inlet stagnation pressure",
            "stagnation pressure",
            "reservoir total pressure",
            "total pressure",
            "reservoir pressure",
        ),
        "total_temperature_k": _find_temperature_k(
            text,
            "inlet stagnation temperature",
            "stagnation temperature",
            "reservoir total temperature",
            "total temperature",
            "reservoir temperature",
        ),
    }

    missing = [k for k, v in required.items() if v is None]

    if missing:
        raise ValueError(
            "Deterministic fallback could not extract "
            f"{missing} from the engineering request."
        )

    ambient = _find_pressure_pa(
        text, "back pressure", "ambient pressure", "downstream pressure"
    )

    notes = ["Interpreted by the deterministic regex parser, not by the LLM."]

    if ambient is None:
        ambient = 30000.0
        notes.append("No ambient pressure stated; 30000 Pa assumed.")

    gamma_match = re.search(r"gamma\s*=?\s*" + _NUM, text, re.I)
    r_match = re.search(r"\bR\s*=?\s*" + _NUM, text, re.I)

    imposed = bool(
        re.search(
            r"impose[sd]?\s+(?:the\s+)?(?:ambient|back|static)\s+pressure\s+at\s+"
            r"(?:the\s+)?(?:computational\s+)?(?:outlet|exit)",
            text,
            re.I,
        )
    )

    return NozzleCaseRequest(
        case_id=_derive_case_id(required, ambient),
        description="Deterministic interpretation of the engineering request.",
        inlet_radius_m=required["inlet_radius_m"],
        throat_radius_m=required["throat_radius_m"],
        exit_radius_m=required["exit_radius_m"],
        inlet_straight_m=required["inlet_straight_m"],
        converging_m=required["converging_m"],
        throat_m=required["throat_m"],
        diverging_m=required["diverging_m"],
        outlet_straight_m=required["outlet_straight_m"],
        total_pressure_pa=required["total_pressure_pa"],
        total_temperature_k=required["total_temperature_k"],
        ambient_pressure_pa=ambient,
        gamma=float(gamma_match.group(1)) if gamma_match else 1.4,
        gas_constant_j_per_kg_k=float(r_match.group(1)) if r_match else 287.0,
        physics_model="inviscid_euler",
        wall_model="adiabatic_slip",
        geometry_family="conical",
        ambient_imposed_at_exit=imposed,
        notes=notes,
    )


def _derive_case_id(required: Dict[str, float], ambient: float) -> str:
    exit_mm = required["exit_radius_m"] * 1000.0
    p0_kpa = required["total_pressure_pa"] / 1000.0

    return (
        "nozzle_re"
        + f"{exit_mm:.4g}".replace(".", "p")
        + "_p0"
        + f"{p0_kpa:.5g}".replace(".", "p")
        + "kpa"
    )


# ----------------------------------------------------------------------
# LLM call
# ----------------------------------------------------------------------


def _call_gemini(prompt: str) -> NozzleCaseRequest:
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

    response = client.models.generate_content(
        model=gemini_model_name(),
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            response_mime_type="application/json",
            response_schema=NozzleCaseRequest,
            temperature=0,
        ),
    )

    if not response.text:
        raise RuntimeError("Gemini returned an empty case-specification response.")

    return NozzleCaseRequest.model_validate_json(response.text)


def interpret_case_request(
    prompt: str,
    *,
    allow_fallback: bool = False,
    numerics: Optional[Dict[str, Any]] = None,
) -> Tuple[NozzleCaseSpec, NozzleCaseRequest, LLMCallRecord]:
    """Interpret an engineering request into a NozzleCaseSpec.

    Returns the specification, the raw structured interpretation, and an
    explicit provenance record stating whether the LLM or the deterministic
    fallback produced it.
    """
    numerics = dict(numerics or {})
    started = time.monotonic()

    if gemini_key_present():
        try:
            request = _call_gemini(prompt)
            record = LLMCallRecord(
                stage=STAGE,
                source=GEMINI,
                model=gemini_model_name(),
                ok=True,
                latency_s=round(time.monotonic() - started, 3),
            )
            return _to_spec(request, numerics), request, record

        except Exception as exc:  # noqa: BLE001 - provenance matters more
            if not allow_fallback:
                raise LLMUnavailable(
                    f"Gemini case interpretation failed: {exc}"
                ) from exc

            request = deterministic_fallback(prompt)
            record = LLMCallRecord(
                stage=STAGE,
                source=FALLBACK,
                model=None,
                ok=True,
                error=str(exc),
                latency_s=round(time.monotonic() - started, 3),
                notes=["Gemini call failed; deterministic parser used instead."],
            )
            return _to_spec(request, numerics), request, record

    if not allow_fallback:
        raise LLMUnavailable(
            "GEMINI_API_KEY is not set and the real LLM path was required. "
            "Set GEMINI_API_KEY, or pass --allow-fallback to run the "
            "deterministic parser instead (which is recorded as such)."
        )

    request = deterministic_fallback(prompt)
    record = LLMCallRecord(
        stage=STAGE,
        source=FALLBACK,
        model=None,
        ok=True,
        error="GEMINI_API_KEY is not set.",
        latency_s=round(time.monotonic() - started, 3),
        notes=["No API key present; deterministic parser used."],
    )
    return _to_spec(request, numerics), request, record


def _clean(value: float, places: str) -> float:
    """Remove representation noise from an interpreted quantity.

    A request states 32.6 mm; both the model and the regex parser must yield
    exactly 0.0326 m. One ulp of drift changes every generated OpenFOAM
    dictionary and would silently break equivalence with the frozen reference.
    """
    return float(
        Decimal(repr(float(value))).quantize(
            Decimal(places), rounding=ROUND_HALF_UP
        )
    )


def _to_spec(
    request: NozzleCaseRequest, numerics: Dict[str, Any]
) -> NozzleCaseSpec:
    length = "1E-9"
    pressure = "1E-6"

    data: Dict[str, Any] = {
        "case_id": request.case_id,
        "description": request.description,
        "inlet_radius_m": _clean(request.inlet_radius_m, length),
        "throat_radius_m": _clean(request.throat_radius_m, length),
        "exit_radius_m": _clean(request.exit_radius_m, length),
        "inlet_straight_m": _clean(request.inlet_straight_m, length),
        "converging_m": _clean(request.converging_m, length),
        "throat_m": _clean(request.throat_m, length),
        "diverging_m": _clean(request.diverging_m, length),
        "outlet_straight_m": _clean(request.outlet_straight_m, length),
        "total_pressure_pa": _clean(request.total_pressure_pa, pressure),
        "total_temperature_k": _clean(request.total_temperature_k, pressure),
        "ambient_pressure_pa": _clean(request.ambient_pressure_pa, pressure),
        "ambient_imposed_at_exit": request.ambient_imposed_at_exit,
        "gamma": _clean(request.gamma, "1E-9"),
        "gas_constant_j_per_kg_k": _clean(request.gas_constant_j_per_kg_k, "1E-9"),
    }

    data.update(numerics)

    # NozzleCaseSpec.from_dict validates the declared envelope and raises on
    # anything outside it; the scope gate then reports the full verdict.
    return NozzleCaseSpec(**data)
