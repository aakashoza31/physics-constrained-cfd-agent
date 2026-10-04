#!/usr/bin/env python3
"""Live mode must really dispatch, and must never claim a solver it did not run."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.agent.pipeline import LIVE, run_pipeline
from src.orchestration import live

_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def reachable_runtime(monkeypatch):
    monkeypatch.setattr(live, "runtime_status", lambda: {
        "available": True, "openfoam_version": "14", "missing_tools": [],
        "reason": ""})


class RecordingDispatch:
    """Stands in for subprocess.run and writes the evidence a runner would."""

    def __init__(self, record, returncode=0):
        self.calls = []
        self.record = record
        self.returncode = returncode

    def __call__(self, command, cwd=None, capture_output=True, text=True,
                 timeout=None):
        self.calls.append({"command": command, "cwd": cwd, "timeout": timeout})
        out = Path(command[command.index("--out") + 1])
        out.mkdir(parents=True, exist_ok=True)
        (out / "agent_result.json").write_text(json.dumps(self.record))
        return SimpleNamespace(returncode=self.returncode, stdout="ok", stderr="")


def test_the_runner_command_is_the_registered_family_runner():
    command = live.build_command("nozzle", "a prompt", Path("/tmp/x"))
    assert command[0] == sys.executable
    assert Path(command[1]).as_posix().endswith("scripts/run_nozzle_e2e.py")
    assert "--prompt" in command and "--out" in command
    command = live.build_command("forward_step_2d", "a prompt", Path("/tmp/x"))
    assert Path(command[1]).as_posix().endswith("scripts/run_forward_step_2d.py")
    assert "--request" in command


@pytest.mark.parametrize("family", ["nozzle", "forward_step_2d"])
def test_live_dispatches_and_ingests_accepted_evidence(family, tmp_path,
                                                       reachable_runtime):
    dispatch = RecordingDispatch({"status": "ACCEPTED", "failed_checks": []})
    outcome = live.run_case(family, None, out_dir=tmp_path / family,
                            dispatch=dispatch)
    assert len(dispatch.calls) == 1
    assert outcome.artifacts["solver_invoked"] is True
    assert outcome.artifacts["returncode"] == 0
    assert "agent_result.json" in outcome.artifacts["runner_evidence"]
    verdicts = {g["question"]: g["passed"] for g in outcome.gates}
    assert verdicts["validation"] is True
    assert verdicts["numerical_health"] is True


def test_live_ingests_a_rejection_without_softening_it(tmp_path, reachable_runtime):
    dispatch = RecordingDispatch(
        {"status": "STOPPED_FAIL_SAFELY",
         "failed_checks": ["compression_front_measurable"]})
    outcome = live.run_case("forward_step_2d", None, out_dir=tmp_path,
                            dispatch=dispatch)
    verdicts = {g["question"]: g["passed"] for g in outcome.gates}
    assert verdicts["validation"] is False
    assert outcome.artifacts["solver_invoked"] is True


def test_a_runner_that_writes_nothing_is_unresolved_not_accepted(tmp_path,
                                                                 reachable_runtime):
    class Silent(RecordingDispatch):
        def __call__(self, command, **kw):
            self.calls.append(command)
            return SimpleNamespace(returncode=0, stdout="", stderr="")

    outcome = live.run_case("nozzle", None, out_dir=tmp_path, dispatch=Silent({}))
    assert outcome.artifacts["solver_invoked"] is True
    assert [g["passed"] for g in outcome.gates] == [None]


def test_the_pipeline_reaches_a_verdict_from_live_gates(tmp_path, reachable_runtime):
    dispatch = RecordingDispatch({"status": "ACCEPTED", "failed_checks": []})
    run = run_pipeline("run the nozzle", mode=LIVE, family="nozzle",
                       case="canonical_reference", allow_cfd=True,
                       live_kwargs={"out_dir": tmp_path, "dispatch": dispatch})
    assert run.artifacts["solver_invoked"] is True
    assert run.decision.verdict == "ACCEPT"
    questions = {g.question for g in run.trace.gates}
    assert {"numerical_health", "conservation", "convergence", "validation"} <= questions


def test_a_failed_runner_cannot_produce_an_accept(tmp_path, reachable_runtime):
    dispatch = RecordingDispatch(
        {"status": "STOPPED_FAIL_SAFELY", "failed_checks": ["horizon"]},
        returncode=1)
    run = run_pipeline("run the step", mode=LIVE, family="forward_step_2d",
                       case="mach20_canonical", allow_cfd=True,
                       live_kwargs={"out_dir": tmp_path, "dispatch": dispatch})
    assert run.artifacts["solver_invoked"] is True
    assert run.decision.verdict == "REJECT"


def test_cube_and_airfoil_can_never_be_executed_live(tmp_path, reachable_runtime):
    for family, case in (("cube", "drifting_wake"), ("airfoil", "mesh_rejection")):
        dispatch = RecordingDispatch({"status": "ACCEPTED", "failed_checks": []})
        outcome = live.run_case(family, case, out_dir=tmp_path / family,
                                dispatch=dispatch)
        assert dispatch.calls == []
        assert outcome.artifacts["solver_invoked"] is False
        run = run_pipeline(family, mode=LIVE, family=family, case=case,
                           allow_cfd=True,
                           live_kwargs={"out_dir": tmp_path, "dispatch": dispatch})
        assert run.artifacts["solver_invoked"] is False
        assert run.decision.verdict != "ACCEPT"


def test_no_solver_claim_without_a_reachable_runtime(tmp_path, monkeypatch):
    monkeypatch.setattr(live, "runtime_status", lambda: {
        "available": False, "reason": "Foundation v14 not found"})
    dispatch = RecordingDispatch({"status": "ACCEPTED"})
    outcome = live.run_case("nozzle", None, out_dir=tmp_path, dispatch=dispatch)
    assert dispatch.calls == []
    assert outcome.artifacts["solver_invoked"] is False
    assert "not reachable" in outcome.reason
