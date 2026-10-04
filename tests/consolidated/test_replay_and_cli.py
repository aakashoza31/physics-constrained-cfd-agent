#!/usr/bin/env python3
"""Every registered case replays to its archived verdict, with no solver."""
from __future__ import annotations

import json
import os
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


def test_the_mesh_sensitivity_request_is_inconclusive_not_rejected():
    """S8: ACCEPT was refused for want of a registered cross-grid tolerance."""
    expected = json.loads((CASES / "forward_step" / "mesh_sensitivity"
                           / "expected_result.json").read_text())["expected"]
    assert expected["verdict"] == "INCONCLUSIVE"
    assert expected["archived_status"] == "STOPPED_ACTION_REFUSED"
    run = run_pipeline("replay forward_step", mode=REPLAY, family="forward_step",
                       case="mesh_sensitivity")
    assert run.decision.verdict == "INCONCLUSIVE"


def _case_library_builder():
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "build_case_library", _ROOT / "scripts" / "build_case_library.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("status,verdict", [
    ("ACCEPTED", "ACCEPT"),
    ("STOPPED_ACTION_REFUSED", "INCONCLUSIVE"),
    ("STOPPED_REFINEMENT_REFUSED", "INCONCLUSIVE"),
    ("STOPPED_REBUILD_REQUIRED", "INCONCLUSIVE"),
    ("UNEXECUTED_ACTION_REQUEST_DIAGNOSTIC", "INCONCLUSIVE"),
    ("STOPPED_FAIL_SAFELY", "REJECT"),
])
def test_the_case_library_maps_archived_statuses_to_the_four_decisions(status, verdict):
    assert _case_library_builder()._verdict_for_status(status) == verdict


def test_the_case_library_refuses_without_the_archive(tmp_path):
    """A clone without the Zenodo archive must not rewrite archived verdicts."""
    import subprocess
    import sys
    before = {p: p.read_bytes() for p in CASES.rglob("expected_result.json")}
    for flag in ([], ["--check"]):
        out = subprocess.run(
            [sys.executable, str(_ROOT / "scripts" / "build_case_library.py"),
             "--archive-root", str(tmp_path), *flag],
            cwd=_ROOT, capture_output=True, text=True, timeout=300)
        assert out.returncode == 2, out.stdout + out.stderr
        assert "archive missing" in out.stdout
        assert "out of date" not in out.stdout
    assert before == {p: p.read_bytes() for p in CASES.rglob("expected_result.json")}


_ARCHIVE = os.environ.get("CFD_FORGE_ARCHIVE")


@pytest.mark.skipif(
    not _ARCHIVE or not (Path(_ARCHIVE) / "demo" / "nozzle_e2e").is_dir(),
    reason=("the archived session records are in the Zenodo archive (DOI to be "
            "added on release); set CFD_FORGE_ARCHIVE to its unpacked location"))
def test_the_case_library_is_up_to_date_with_its_evidence():
    import subprocess
    import sys
    out = subprocess.run(
        [sys.executable, str(_ROOT / "scripts" / "build_case_library.py"),
         "--archive-root", _ARCHIVE, "--check"],
        cwd=_ROOT, capture_output=True, text=True, timeout=300)
    assert out.returncode == 0, f"cases/ is stale:\n{out.stdout}"
