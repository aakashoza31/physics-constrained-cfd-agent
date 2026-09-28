#!/usr/bin/env python3
"""Every registered case replays to its archived verdict, with no solver."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.agent.pipeline import DRY_RUN, LIVE, REPLAY, run_pipeline
from src.orchestration import replay

_ROOT = Path(__file__).resolve().parents[2]
CASES = _ROOT / "cases"


def _registered():
    for family_dir in sorted(p for p in CASES.iterdir() if p.is_dir()):
        for case_dir in sorted(p for p in family_dir.iterdir() if p.is_dir()):
            yield family_dir.name, case_dir.name


REGISTERED = list(_registered())


def test_the_case_library_is_populated():
    assert len(REGISTERED) >= 13
    families = {family for family, _ in REGISTERED}
    assert {"nozzle", "forward_step", "cube", "airfoil"} <= families


@pytest.mark.parametrize("family,case", REGISTERED)
def test_every_case_carries_the_full_contract(family, case):
    path = CASES / family / case
    for name in ("case.yaml", "expected_result.json", "README.md",
                 "reproduce.sh", "reproduce.ps1"):
        assert (path / name).exists(), f"{family}/{case} is missing {name}"
    assert (path / "reference").is_dir()


@pytest.mark.parametrize("family,case", REGISTERED)
def test_replay_reproduces_the_archived_verdict(family, case):
    expected = json.loads(
        (CASES / family / case / "expected_result.json").read_text())
    run = run_pipeline(f"replay {family}", mode=REPLAY, family=family, case=case)
    assert run.decision is not None
    assert run.decision.verdict == expected["expected"]["verdict"], (
        f"{family}/{case}: replay gave {run.decision.verdict}, archive says "
        f"{expected['expected']['verdict']}")


@pytest.mark.parametrize("family,case", REGISTERED)
def test_replay_never_claims_a_solver_ran(family, case):
    run = run_pipeline(f"replay {family}", mode=REPLAY, family=family, case=case)
    assert run.artifacts.get("solver_invoked") is False
    assert run.to_dict()["solver_invoked"] is False


def test_a_dry_run_validates_nothing_and_says_so():
    run = run_pipeline("Simulate a supersonic nozzle with throat radius 0.01",
                       mode=DRY_RUN)
    assert run.family == "nozzle"
    assert run.decision.verdict == "INCONCLUSIVE"
    assert run.artifacts["solver_invoked"] is False


def test_live_requires_an_explicit_opt_in():
    run = run_pipeline("nozzle", mode=LIVE, family="nozzle",
                       case="canonical_reference")
    assert run.artifacts["solver_invoked"] is False
    assert run.decision.verdict == "INCONCLUSIVE"
    assert "not authorised" in run.decision.reason


def test_a_non_routable_family_cannot_be_executed_live():
    run = run_pipeline("cube", mode=LIVE, family="cube", case="drifting_wake",
                       allow_cfd=True)
    assert run.artifacts["solver_invoked"] is False
    assert run.decision.verdict != "ACCEPT"


def test_an_unregistered_case_is_refused():
    run = run_pipeline("nozzle", mode=REPLAY, family="nozzle", case="no_such_case")
    assert run.decision.verdict == "INCONCLUSIVE" or run.decision.verdict == "REJECT"
    assert run.artifacts.get("solver_invoked", False) is False
    with pytest.raises(replay.CaseNotFound):
        replay.case_dir("nozzle", "no_such_case")


def test_an_unroutable_prompt_is_refused_without_simulating():
    run = run_pipeline("simulate combustion instability in a gas turbine",
                       mode=DRY_RUN)
    assert run.family is None
    assert run.decision.verdict in ("REJECT", "INCONCLUSIVE")
    assert run.artifacts["solver_invoked"] is False


def test_the_case_library_is_up_to_date_with_its_evidence():
    import subprocess
    import sys
    out = subprocess.run(
        [sys.executable, "scripts/build_case_library.py", "--check"],
        cwd=_ROOT, capture_output=True, text=True, timeout=300)
    assert out.returncode == 0, f"cases/ is stale:\n{out.stdout}"
