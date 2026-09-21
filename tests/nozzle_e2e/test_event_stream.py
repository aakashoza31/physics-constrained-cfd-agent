"""The event stream must be a faithful, machine-checkable record."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from src.reporting import event_stream as ev  # noqa: E402
from src.reporting.event_stream import EventStream  # noqa: E402


def test_required_demo_tags_exist():
    required = {
        "ORCHESTRATOR",
        "MESH TOOL",
        "CFD SETUP",
        "EXECUTOR",
        "DIAGNOSTICS",
        "SCIENTIFIC VALIDATOR",
        "REPORTER",
    }

    assert required <= set(ev.TAGS)


def test_events_are_written_to_stdout_and_jsonl(tmp_path, capsys):
    stream = EventStream(tmp_path, case_id="case_X", echo=True)

    stream.emit(ev.ORCHESTRATOR, "Request received.")
    stream.ok(ev.MESH_TOOL, "Mesh OK.", data={"cells": 2112})
    stream.fail(ev.SCIENTIFIC_VALIDATOR, "Two checks failed.")

    captured = capsys.readouterr().out

    assert "[ORCHESTRATOR]" in captured
    assert "[MESH TOOL]" in captured
    assert "PASS" in captured and "FAIL" in captured

    lines = (tmp_path / "events.jsonl").read_text().strip().splitlines()
    events = [json.loads(line) for line in lines]

    assert [e["tag"] for e in events] == [
        "ORCHESTRATOR",
        "MESH TOOL",
        "SCIENTIFIC VALIDATOR",
    ]
    assert events[1]["data"]["cells"] == 2112
    assert all(e["case_id"] == "case_X" for e in events)
    assert all("t_s" in e for e in events)


def test_llm_provenance_is_visible_in_every_reasoning_event(tmp_path, capsys):
    stream = EventStream(tmp_path, case_id="case_X")

    stream.emit(ev.LLM, "Interpreted request.", llm_source="LLM:gemini-x")
    stream.emit(ev.LLM, "Interpreted request.", llm_source="DETERMINISTIC_FALLBACK")

    captured = capsys.readouterr().out

    assert "<LLM:gemini-x>" in captured
    assert "<DETERMINISTIC_FALLBACK>" in captured

    events = [
        json.loads(line)
        for line in (tmp_path / "events.jsonl").read_text().strip().splitlines()
    ]

    assert events[0]["llm_source"] == "LLM:gemini-x"
    assert events[1]["llm_source"] == "DETERMINISTIC_FALLBACK"

    summary = stream.summary()
    assert summary["llm_sources"] == [
        "DETERMINISTIC_FALLBACK",
        "LLM:gemini-x",
    ]


def test_unknown_tags_are_refused(tmp_path):
    stream = EventStream(tmp_path, echo=False)

    with pytest.raises(ValueError):
        stream.emit("MARKETING", "Not a real workflow stage.")


def test_failures_are_summarized(tmp_path):
    stream = EventStream(tmp_path, echo=False)

    stream.ok(ev.MESH_TOOL, "fine")
    stream.fail(ev.EXECUTOR, "solver stalled")

    summary = stream.summary()

    assert summary["event_count"] == 2
    assert len(summary["failures"]) == 1
    assert summary["failures"][0]["tag"] == "EXECUTOR"
