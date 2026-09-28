#!/usr/bin/env python3
"""F3: the surface-mounted cube must stay REJECTED, and stay reproducible."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.families.cube import stationarity as gate

_ROOT = Path(__file__).resolve().parents[2]
CASE = _ROOT / "cases" / "cube" / "drifting_wake"


@pytest.fixture(scope="module")
def samples():
    data = json.loads((CASE / "reference" / "force_history.json").read_text())
    return data["samples"]


def test_the_archived_force_history_is_present_and_long(samples):
    assert len(samples) > 1500
    assert min(s["t"] for s in samples) <= 20.0
    assert max(s["t"] for s in samples) >= 79.0


def test_thresholds_are_registered_constants():
    assert gate.FORCE_DRIFT_FRACTION_MAX == 0.02
    assert gate.LATERAL_GROWTH_RATIO_MAX == 1.25
    assert gate.LATERAL_RELATIVE_MAX == 0.05
    assert gate.ASSESSMENT_WINDOW == 20.0


def test_the_run_is_rejected_on_development_not_on_drag(samples):
    result = gate.assess(samples)
    assert result.status == gate.STILL_DEVELOPING
    assert result.passed is False
    assert result.failures == ["lateral_force_growth"]
    # the drag looks converged: that is the point of the demonstration
    assert result.measured["drift_fraction"]["fx"] < gate.FORCE_DRIFT_FRACTION_MAX
    assert result.measured["lateral_relative_magnitude"] < gate.LATERAL_RELATIVE_MAX


def test_the_rejection_is_not_knife_edge(samples):
    """It would still fail for any growth limit below 2.0."""
    ratio = gate.assess(samples).measured["lateral_growth_ratio"]
    assert ratio > 2.0
    assert ratio / gate.LATERAL_GROWTH_RATIO_MAX > 1.5


def test_a_settled_history_passes_the_same_gate():
    """The gate is not a rubber stamp for rejection."""
    settled = [{"t": 60.0 + 0.04 * i, "fx": 0.70 + 1e-6 * ((-1) ** i),
                "fy": 0.25, "fz": 1e-6 * ((-1) ** i)} for i in range(500)]
    result = gate.assess(settled)
    assert result.status == gate.STATIONARY
    assert result.passed is True


def test_a_short_history_is_unresolved_not_accepted():
    short = [{"t": 79.0 + 0.1 * i, "fx": 0.7, "fy": 0.25, "fz": 0.0}
             for i in range(5)]
    assert gate.assess(short).status == gate.INSUFFICIENT_HISTORY
    assert gate.assess([]).status == gate.INSUFFICIENT_HISTORY


def test_the_lateral_mode_is_a_growing_oscillation():
    mode = json.loads((CASE / "reference" / "lateral_mode.json").read_text())
    assert mode["amplitude_growth_factor"] > 50
    assert mode["exponential_growth_rate_per_time"] > 0.05
    assert 8.0 < mode["period"] < 13.0
    assert mode["zero_crossings"] >= 10


def test_the_registered_expectation_is_a_rejection():
    expected = json.loads((CASE / "expected_result.json").read_text())["expected"]
    assert expected["verdict"] == "REJECT"
    assert expected["archived_status"] == "RUNTIME_REJECTED"
    assert expected["solver_invoked_in_archive"] is True


def test_the_case_is_never_described_as_validated():
    text = (CASE / "README.md").read_text().lower()
    assert "reject" in text
    assert "validated" not in text.replace("validation", "")
