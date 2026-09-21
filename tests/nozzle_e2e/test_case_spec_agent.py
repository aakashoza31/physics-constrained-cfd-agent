"""Natural-language interpretation and, above all, its provenance.

The deterministic fallback exists for robustness. These tests assert that it
can never be mistaken for the LLM: it is labelled, it refuses to invent a case
it could not parse, and the real-LLM path is required unless fallback is
explicitly enabled.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from src.agents.llm_provenance import FALLBACK, LLMCallRecord, LLMUnavailable  # noqa: E402
from src.agents.nozzle_case_spec_agent import (  # noqa: E402
    deterministic_fallback,
    interpret_case_request,
)
from src.pipeline.nozzle.spec import NozzleCaseSpec  # noqa: E402
from src.reasoning.nozzle_scope_gate import evaluate_scope  # noqa: E402

PROMPTS = REPO_ROOT / "examples/nozzle_e2e"
CONFIGS = REPO_ROOT / "configs/nozzles"

EXPECTED = {
    "A": ("case_A_reference.yaml", 0.0354, 200000.0),
    "B": ("case_B_geometry.yaml", 0.0370, 200000.0),
    "C": ("case_C_conditions.yaml", 0.0354, 220000.0),
}


@pytest.fixture(autouse=True)
def no_api_key(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)


@pytest.mark.parametrize("case", ["A", "B", "C"])
def test_prompts_parse_to_the_intended_cases(case):
    config, exit_radius, p0 = EXPECTED[case]
    prompt = (PROMPTS / f"PROMPT_{case}.txt").read_text()

    spec, request, record = interpret_case_request(
        prompt, allow_fallback=True, numerics={"scale": 1.0}
    )

    assert spec.exit_radius_m == pytest.approx(exit_radius, rel=1e-12)
    assert spec.total_pressure_pa == pytest.approx(p0, rel=1e-12)
    assert spec.total_temperature_k == 300.0
    assert spec.ambient_pressure_pa == 30000.0
    assert spec.inlet_radius_m == 0.05
    assert spec.throat_radius_m == 0.0326
    assert spec.ambient_imposed_at_exit is False
    assert record.source == FALLBACK


@pytest.mark.parametrize("case", ["A", "B", "C"])
def test_prompt_interpretation_matches_the_checked_in_config(case):
    config, _, _ = EXPECTED[case]

    from_config = NozzleCaseSpec.from_yaml(CONFIGS / config)
    from_prompt, _, _ = interpret_case_request(
        (PROMPTS / f"PROMPT_{case}.txt").read_text(),
        allow_fallback=True,
        numerics={
            "scale": from_config.scale,
            "end_time_s": from_config.end_time_s,
            "max_courant": from_config.max_courant,
            "wedge_angle_deg": from_config.wedge_angle_deg,
        },
    )

    physical = (
        "inlet_radius_m",
        "throat_radius_m",
        "exit_radius_m",
        "inlet_straight_m",
        "converging_m",
        "throat_m",
        "diverging_m",
        "outlet_straight_m",
        "total_pressure_pa",
        "total_temperature_k",
        "ambient_pressure_pa",
        "gamma",
        "gas_constant_j_per_kg_k",
        "scale",
        "end_time_s",
        "max_courant",
        "wedge_angle_deg",
    )

    for field in physical:
        assert getattr(from_prompt, field) == getattr(from_config, field), field


@pytest.mark.parametrize("case", ["A", "B", "C"])
def test_interpreted_cases_pass_the_scope_gate(case):
    spec, _, _ = interpret_case_request(
        (PROMPTS / f"PROMPT_{case}.txt").read_text(), allow_fallback=True
    )

    result = evaluate_scope(spec)
    assert result.approved, result.reasons


def test_real_llm_path_is_required_by_default():
    with pytest.raises(LLMUnavailable, match="GEMINI_API_KEY"):
        interpret_case_request(
            (PROMPTS / "PROMPT_A.txt").read_text(), allow_fallback=False
        )


def test_fallback_is_always_labelled_and_never_claims_to_be_the_model():
    _, _, record = interpret_case_request(
        (PROMPTS / "PROMPT_A.txt").read_text(), allow_fallback=True
    )

    assert record.source == FALLBACK
    assert record.is_llm is False
    assert record.label == "DETERMINISTIC_FALLBACK"
    assert record.model is None
    assert "GEMINI_API_KEY is not set." in (record.error or "")
    assert record.to_dict()["is_llm"] is False


def test_llm_record_label_names_the_model_when_the_model_answered():
    record = LLMCallRecord(stage="x", source="gemini", model="gemini-3.5-flash-lite")

    assert record.is_llm is True
    assert record.label == "LLM:gemini-3.5-flash-lite"


def test_fallback_refuses_to_invent_a_case_it_cannot_parse():
    with pytest.raises(ValueError, match="could not extract"):
        deterministic_fallback(
            "Please simulate the usual nozzle with the usual settings."
        )


def test_fallback_reads_units_rather_than_assuming_the_canonical_case():
    prompt = (
        "Axisymmetric conical converging-diverging nozzle. "
        "inlet radius = 48 mm, throat radius = 30 mm, outlet radius = 34 mm, "
        "inlet straight length = 40 mm, converging length = 90 mm, "
        "throat length = 12 mm, diverging length = 110 mm, "
        "outlet straight length = 40 mm. "
        "inlet stagnation pressure = 1.8 bar, "
        "inlet stagnation temperature = 310 K, back pressure = 25 kPa. "
        "gamma = 1.4, R = 287. Inviscid Euler, adiabatic slip walls."
    )

    request = deterministic_fallback(prompt)

    assert request.inlet_radius_m == 0.048
    assert request.throat_radius_m == 0.030
    assert request.exit_radius_m == 0.034
    assert request.total_pressure_pa == 180000.0
    assert request.total_temperature_k == 310.0
    assert request.ambient_pressure_pa == 25000.0
    assert request.throat_m == 0.012


def test_fallback_detects_an_explicit_request_to_impose_the_outlet_pressure():
    prompt = (PROMPTS / "PROMPT_A.txt").read_text() + (
        "\nImpose the ambient pressure at the computational outlet.\n"
    )

    request = deterministic_fallback(prompt)

    assert request.ambient_imposed_at_exit is True

    spec, _, _ = interpret_case_request(prompt, allow_fallback=True)
    assert evaluate_scope(spec).approved is False
