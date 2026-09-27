#!/usr/bin/env python3
"""Nozzle adapter: self-check must be honest about what is missing here."""
from __future__ import annotations

from pathlib import Path

import pytest

from src.families.nozzle_adapter import NozzleAdapter


def test_self_check_separates_full_from_replay_readiness():
    check = NozzleAdapter.self_check()
    assert "replay_ok" in check and "replay_missing" in check
    assert set(NozzleAdapter.REPLAY_TARGETS) == {
        "evidence", "fallback_decision", "action_gate"
    }
    # replay_ok must be implied by ok, never the reverse.
    if check["ok"]:
        assert check["replay_ok"]


def test_self_check_enumerates_delegation_targets():
    check = NozzleAdapter.self_check()
    assert set(check["targets"]) == {
        "spec", "scope", "diagnose", "fallback_decision", "evidence",
        "action_gate", "parse", "feedback", "feedback_diagnostics",
    }
    assert isinstance(check["ok"], bool)


def test_adapter_refuses_the_paths_whose_targets_are_missing():
    """A method demands only what it uses: a missing parser must not block replay."""
    adapter = NozzleAdapter()
    check = adapter.self_check()
    if check["ok"]:
        pytest.skip("all nozzle targets present on this copy")
    for key, call in (("scope", lambda: adapter.check_scope(None)),
                      ("parse", lambda: adapter.parse_request("x")),
                      ("spec", lambda: adapter.load_spec(Path("nope.json")))):
        if check["targets"].get(key) == "ok":
            continue
        with pytest.raises(RuntimeError) as exc:
            call()
        assert "incomplete for Family 1" in str(exc.value)
        assert key in str(exc.value)


def test_recipe_is_registered_with_the_frozen_validator_thresholds():
    """The nozzle recipe is now registered; the values are transcribed, not owned."""
    adapter = NozzleAdapter()
    assert adapter.recipe.is_registered()
    assert adapter.recipe.unresolved() == []
    assert adapter.recipe.tolerances == {
        "theory_outlet_pressure_error_pct_max": 5.0,
        "theory_other_output_error_pct_max": 3.0,
    }


def test_no_region_vocabulary_means_no_refine_region():
    assert NozzleAdapter.recipe.region_vocabulary == ()
    assert "REFINE_REGION" not in NozzleAdapter.recipe.allowed_actions


def test_evidence_and_spec_filenames_match_the_family_runner():
    """The names this adapter reads must be the ones Family 1 actually writes."""
    from pathlib import Path

    from src.families.nozzle_adapter import EVIDENCE_FILES, SPEC_FILENAMES

    runner = (
        Path(__file__).resolve().parents[2] / "scripts/run_nozzle_feedback.py"
    ).read_text()
    for name in EVIDENCE_FILES.values():
        assert name in runner, f"{name} is not written by run_nozzle_feedback.py"
    assert any(n in runner for n in SPEC_FILENAMES)


def test_load_evidence_refuses_without_an_archived_validation(tmp_path):
    adapter = NozzleAdapter()
    if not adapter.self_check()["ok"]:
        pytest.skip("nozzle modules absent in this working copy")
    with pytest.raises(FileNotFoundError) as exc:
        adapter.load_evidence(tmp_path)
    assert "validation.json" in str(exc.value)


def test_load_evidence_replays_an_archived_validation_without_cfd(tmp_path):
    """Decision-level replay: reads archived documents, launches nothing."""
    import json

    adapter = NozzleAdapter()
    if not adapter.self_check()["ok"]:
        pytest.skip("nozzle modules absent in this working copy")
    (tmp_path / "validation.json").write_text(
        json.dumps({"status": "PASS", "case_id": "replay", "checks": {},
                    "final": {}, "drift_fraction_last_2ms": {}})
    )
    (tmp_path / "execution.json").write_text(json.dumps({"returncode": 0}))
    evidence = adapter.load_evidence(tmp_path)
    assert evidence["family"] == "nozzle"
    assert evidence["raw_validation"]["status"] == "PASS"
    assert evidence["provenance"]["replayed_from_archive"] is True
    assert evidence["provenance"]["case_id"] == "replay"


def test_build_and_run_remain_unwired_with_an_explicit_reason(tmp_path):
    adapter = NozzleAdapter()
    for call in (lambda: adapter.build_case(None, tmp_path),
                 lambda: adapter.run_case(tmp_path)):
        with pytest.raises(NotImplementedError) as exc:
            call()
        assert "run_nozzle_feedback.py" in str(exc.value)
