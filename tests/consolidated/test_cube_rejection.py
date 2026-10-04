#!/usr/bin/env python3
"""The surface-mounted cube study must stay REJECTED, and stay reproducible.

The cube was run outside the agent loop; its stationarity gate was registered
retrospectively (cube-stationarity/1.0.0, 28 Sep 2026).
"""
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


def test_the_registered_gate_quantities_match_the_paper(samples):
    assert gate.GATE_VERSION == "cube-stationarity/1.0.0"
    result = gate.assess(samples)
    measured = result.measured
    assert result.window["start"] == pytest.approx(59.98, abs=0.01)
    assert result.window["end"] == pytest.approx(79.98, abs=0.01)
    # half-window mean|Fz| ratio 2.10 against the registered limit 1.25
    assert measured["lateral_growth_ratio"] == pytest.approx(2.10, abs=0.005)
    assert measured["lateral_growth_ratio"] > gate.LATERAL_GROWTH_RATIO_MAX
    # drag drift 0.075 %, mean lateral force 0.063 % of the drag
    assert measured["drift_fraction"]["fx"] == pytest.approx(0.00075, abs=0.00001)
    assert measured["lateral_relative_magnitude"] == pytest.approx(0.00063, abs=0.00001)
    assert result.status == gate.STILL_DEVELOPING


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


def test_the_lateral_force_is_a_periodic_mode_still_growing_at_the_end():
    mode = json.loads((CASE / "reference" / "lateral_mode.json").read_text())
    assert 8.0 < mode["period"] < 13.0
    assert mode["zero_crossings"] >= 10
    assert mode["last_peak"]["abs_fz"] > mode["first_peak"]["abs_fz"]


def test_the_registered_expectation_is_a_rejection():
    expected = json.loads((CASE / "expected_result.json").read_text())["expected"]
    assert expected["verdict"] == "REJECT"
    assert expected["archived_status"] == "RETROSPECTIVE_GATE_STILL_DEVELOPING"
    assert expected["rejected_on"] == "STILL_DEVELOPING"
    assert expected["stationarity"]["gate_version"] == "cube-stationarity/1.0.0"
    assert expected["solver_invoked_in_archive"] is True


@pytest.fixture(scope="module")
def replayed():
    from src.agent.pipeline import REPLAY, run_pipeline
    return run_pipeline("replay cube", mode=REPLAY, family="cube",
                        case="drifting_wake")


def test_the_replay_carries_the_three_model_records_and_none_accepts(replayed):
    assert replayed.decision.verdict == "REJECT"
    records = replayed.artifacts["llm_diagnosis"]["records"]
    assert len(records) == 3
    assert all(r["model"] == "gemini-3.5-flash-lite" for r in records)
    assert [r["action"] for r in records] == [
        "CONTINUE_RUN", "FAIL_SAFELY", "CONTINUE_RUN"]
    assert [r["diagnosis"] for r in records] == [
        "STILL_DEVELOPING", "NUMERICALLY_UNHEALTHY", "STILL_DEVELOPING"]
    assert all(r["approved"] is True for r in records)
    assert not any(r["action"] == "ACCEPT" for r in records)
    assert not any(r["executed"] for r in records)


def test_the_replay_text_uses_the_registered_quantities_only(replayed, tmp_path):
    from src.reporting import report_builder

    paths = report_builder.build(replayed, tmp_path / "report", make_media=False)
    texts = [replayed.decision.reason,
             Path(paths.report_md).read_text(encoding="utf-8")]
    texts += [str(g) for g in replayed.trace.gates]
    for text in texts:
        lowered = text.lower()
        assert "68x" not in lowered and "68 x" not in lowered
        assert "exponential" not in lowered
        assert "e-folding" not in lowered
    assert "2.10" in replayed.decision.reason


def test_the_case_is_never_described_as_validated():
    text = (CASE / "README.md").read_text().lower()
    assert "reject" in text
    assert "validated" not in text.replace("validation", "")
