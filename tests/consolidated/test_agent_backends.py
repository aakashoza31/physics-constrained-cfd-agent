#!/usr/bin/env python3
"""Backends propose. They never decide, and a no-key run is never called an LLM run."""
from __future__ import annotations

import json
import types

import pytest

from src.agent import backends
from src.agent.pipeline import REPLAY, run_pipeline


def test_the_three_backends_are_declared():
    assert backends.BACKENDS == ("deterministic", "gemini", "replay")


def test_the_deterministic_backend_needs_no_key_and_says_what_it_is():
    engine = backends.make("deterministic")
    statement = engine.interpret("Simulate a supersonic nozzle, throat radius 0.01")
    assert statement.proposed_family == "nozzle"
    assert statement.interpreter == "deterministic"
    record = engine.to_dict()
    assert record["llm_calls"] == 0
    assert all(call["is_llm"] is False for call in record["calls"])


def test_gemini_refuses_without_a_key_instead_of_downgrading(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(backends.BackendUnavailable) as exc:
        backends.make("gemini")
    assert "must not be described as an LLM run" in str(exc.value)


def _fake_gemini(monkeypatch, payload, *, usage=(120, 45)):
    """Install a fake model call that returns `payload` as JSON."""
    def fake(prompt, call):
        call.provider = "google"
        call.model = "gemini-test"
        call.temperature = 0.0
        call.raw_response = json.dumps(payload)
        call.latency_s = 0.01
        call.input_tokens, call.output_tokens = usage
        return payload
    monkeypatch.setattr(backends, "_gemini_json", fake)
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")


def test_a_model_interpretation_is_recorded_with_full_provenance(monkeypatch):
    _fake_gemini(monkeypatch, {"family": "nozzle",
                               "parameters": {"throat_radius": 0.01},
                               "reasoning": "a converging-diverging nozzle"})
    engine = backends.make("gemini")
    statement = engine.interpret("simulate my nozzle")
    assert statement.proposed_family == "nozzle"
    call = engine.to_dict()["calls"][0]
    assert call["is_llm"] is True
    assert call["binding"] is False
    assert call["provider"] == "google"
    assert call["model"] == "gemini-test"
    assert call["temperature"] == 0.0
    assert call["prompt_schema_version"] == backends.PROMPT_SCHEMA_VERSION
    assert call["input_tokens"] == 120 and call["output_tokens"] == 45
    assert call["latency_s"] is not None


def test_a_model_may_not_invent_a_family(monkeypatch):
    _fake_gemini(monkeypatch, {"family": "plasma_torch", "parameters": {},
                               "reasoning": "made it up"})
    engine = backends.make("gemini")
    statement = engine.interpret("simulate a plasma torch")
    assert statement.proposed_family is None
    assert any("not registered" in d for d in engine.calls[0].dropped)


def test_an_action_outside_the_vocabulary_is_refused(monkeypatch):
    _fake_gemini(monkeypatch, {"diagnosis": "looks fine",
                               "evidence_used": ["solver"],
                               "action": "OVERRIDE_GATES"})
    engine = backends.make("gemini")
    call = engine.diagnose("nozzle", {"solver": {"completed": True}})
    assert call.action_in_vocabulary is False
    assert call.proposed_action is None
    assert any("outside the registered vocabulary" in d for d in call.dropped)


def test_a_valid_action_is_kept_but_still_non_binding(monkeypatch):
    _fake_gemini(monkeypatch, {"diagnosis": "needs more time",
                               "evidence_used": ["solver"],
                               "action": "CONTINUE_RUN"})
    engine = backends.make("gemini")
    call = engine.diagnose("nozzle", {"solver": {"completed": False}})
    assert call.proposed_action == "CONTINUE_RUN"
    assert call.action_in_vocabulary is True
    assert call.to_dict()["binding"] is False


def test_a_model_cannot_change_a_verdict(monkeypatch):
    """The model insists on ACCEPT; the cube case must still be REJECTED."""
    _fake_gemini(monkeypatch, {"diagnosis": "fully converged, accept it",
                               "evidence_used": [], "action": "CONTINUE_RUN"})
    run = run_pipeline("replay the cube", mode=REPLAY, family="cube",
                       case="drifting_wake", backend="gemini")
    assert run.decision.verdict == "REJECT"
    trace = run.trace.to_dict()
    assert any(p["activity"] == "diagnose_evidence" for p in trace["llm_proposals"])
    assert all(p["binding"] is False for p in trace["llm_proposals"])


def test_the_backend_record_reaches_the_run_artifact(monkeypatch):
    _fake_gemini(monkeypatch, {"family": "nozzle", "parameters": {},
                               "reasoning": "ok"})
    run = run_pipeline("a nozzle", mode="dry-run", backend="gemini")
    record = run.to_dict()["agent_backend"]
    assert record["backend"] == "gemini"
    assert record["llm_calls"] >= 1
    assert "decides" in record["note"]
