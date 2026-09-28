#!/usr/bin/env python3
"""The standard artifact directory, and the honesty rules inside it."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.agent.pipeline import REPLAY, run_pipeline
from src.reporting import report_builder


@pytest.fixture(scope="module")
def cube_artifacts(tmp_path_factory):
    run = run_pipeline("replay the cube", mode=REPLAY, family="cube",
                       case="drifting_wake")
    out = tmp_path_factory.mktemp("cube_report")
    paths = report_builder.build(run, out, make_media=False)
    return run, out, paths


def test_the_standard_directory_is_written(cube_artifacts):
    _run, out, _paths = cube_artifacts
    for relative in ("report/report.md", "report/report.json",
                     "diagnostics/llm_trace.json",
                     "diagnostics/proposed_actions.json",
                     "diagnostics/authority_trace.json",
                     "provenance.json", "final_decision.json"):
        assert (out / relative).exists(), relative


def test_only_applicable_evidence_documents_are_written(cube_artifacts):
    _run, out, _paths = cube_artifacts
    names = {p.stem for p in (out / "evidence").glob("*.json")}
    # the cube has stationarity and convergence; it never reached validation
    assert "stationarity" in names
    assert "convergence" in names
    assert "validation" not in names       # not applicable, so not fabricated


def test_the_decision_is_carried_verbatim(cube_artifacts):
    run, out, _paths = cube_artifacts
    decision = json.loads((out / "final_decision.json").read_text())
    assert decision["verdict"] == "REJECT"
    assert decision["decided_by"] == "deterministic_authority"
    assert decision["llm_override_possible"] is False


def test_provenance_records_that_no_solver_ran(cube_artifacts):
    _run, out, _paths = cube_artifacts
    provenance = json.loads((out / "provenance.json").read_text())
    assert provenance["solver_invoked"] is False
    assert provenance["mode"] == "replay"
    assert provenance["python"]


def test_model_proposals_are_marked_non_binding(cube_artifacts):
    _run, out, _paths = cube_artifacts
    trace = json.loads((out / "diagnostics" / "llm_trace.json").read_text())
    assert trace["count"] >= 1
    assert all(p["binding"] is False for p in trace["proposals"])


def test_the_report_states_the_verdict_and_the_reason(cube_artifacts):
    _run, out, _paths = cube_artifacts
    text = (out / "report" / "report.md").read_text()
    assert "REJECT" in text
    assert "lateral" in text.lower()
    assert "Deterministic gates" in text


def test_a_steady_case_gets_no_fabricated_time_evolution(tmp_path):
    """Video for a family with no time-resolved series must be NOT_AVAILABLE."""
    from src.reporting import visuals

    run = run_pipeline("replay nozzle", mode=REPLAY, family="nozzle",
                       case="canonical_reference")
    name = visuals.make_video(run, tmp_path / "video")
    status = json.loads((tmp_path / "video" / "video_status.json").read_text())
    if name is None:
        assert status["status"] == visuals.NOT_AVAILABLE
        assert "nothing to animate" in status["reason"]
    else:
        assert "not physical time" in status["represents"] or status["transient_family"]


def test_contours_report_what_was_missing(tmp_path):
    from src.reporting import visuals

    run = run_pipeline("replay cube", mode=REPLAY, family="cube",
                       case="drifting_wake")
    written = visuals.make_contours(run, tmp_path / "contours")
    status = json.loads((tmp_path / "contours" / "contours_status.json").read_text())
    if not written:
        assert status["status"] == visuals.NOT_AVAILABLE
        assert status["reason"]
        assert status["script"].endswith("paraview_contours.py")
