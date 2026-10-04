"""The deterministic scope gate must admit A, B and C and refuse the rest."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from src.pipeline.nozzle.spec import NozzleCaseSpec  # noqa: E402
from src.reasoning.nozzle_scope_gate import evaluate_scope  # noqa: E402

CONFIGS = REPO_ROOT / "configs/nozzles"


@pytest.mark.parametrize(
    "config",
    ["case_A_reference.yaml", "case_B_geometry.yaml", "case_C_conditions.yaml"],
)
def test_demonstration_cases_are_in_scope(config):
    spec = NozzleCaseSpec.from_yaml(CONFIGS / config)
    result = evaluate_scope(spec)

    assert result.approved, result.reasons
    assert result.to_dict()["decision"] == "IN_SCOPE"
    assert all(result.checks.values())


def _spec(**overrides) -> NozzleCaseSpec:
    base = NozzleCaseSpec.from_yaml(CONFIGS / "case_A_reference.yaml")
    return NozzleCaseSpec(**{**base.to_dict(), **overrides})


def test_rejects_imposed_ambient_at_the_outlet():
    result = evaluate_scope(_spec(ambient_imposed_at_exit=True))

    assert not result.approved
    assert result.checks["ambient_not_imposed_at_exit"] is False
    assert any("pressure-free" in r for r in result.reasons)


def test_rejects_a_gas_outside_the_registered_envelope():
    result = evaluate_scope(_spec(gamma=1.667, gas_constant_j_per_kg_k=2077.0))

    assert not result.approved
    assert result.checks["gas_is_validated_air"] is False


def test_rejects_a_geometry_that_is_not_converging_diverging():
    result = evaluate_scope(_spec(exit_radius_m=0.030))

    assert not result.approved
    assert result.checks["converging_diverging"] is False


def test_rejects_a_pressure_ratio_that_cannot_run_supersonic_at_the_exit():
    # Ambient above the fully supersonic exit static pressure: the declared
    # pressure-free outlet is then not justified.
    result = evaluate_scope(_spec(ambient_pressure_pa=90000.0))

    assert not result.approved
    assert result.checks["supersonic_outlet_branch_available"] is False
    assert any("underexpanded" in r for r in result.reasons)


def test_rejects_a_reservoir_far_outside_the_verified_transfer_range():
    result = evaluate_scope(_spec(total_pressure_pa=1_000_000.0))

    assert not result.approved
    assert result.checks["total_pressure_pa_in_range"] is False


def test_rejects_an_area_ratio_far_from_the_anchor():
    result = evaluate_scope(_spec(exit_radius_m=0.065))

    assert not result.approved
    assert result.checks["area_ratio_in_range"] is False


def test_gate_reports_measurements_for_the_event_stream():
    spec = NozzleCaseSpec.from_yaml(CONFIGS / "case_B_geometry.yaml")
    result = evaluate_scope(spec)

    assert result.measurements["cells"] == 2112
    assert result.measurements["nozzle_pressure_ratio"] == pytest.approx(
        200000.0 / 30000.0
    )
    assert result.measurements["area_ratio"] == pytest.approx(1.28817, rel=1e-4)
    assert result.to_dict()["authority"] == "deterministic"
