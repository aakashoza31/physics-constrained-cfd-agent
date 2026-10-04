#!/usr/bin/env python3
"""Regression tests for the three-horizon control semantics (Case H).

BACKGROUND
----------
Case H asked for an INITIAL execution to t = 0.5 on a benchmark whose
registered horizon is t = 4. The workflow carried one horizon, so "run the
first execution to 0.5" was stored as the whole scientific ambition. The
consequence was a healthy run that could not finish:

  iteration 1  solved to t = 0.5, 17/17 hard checks, HEALTHY_INCOMPLETE
               -> EXTEND_END_TIME approved, 0.5 -> 1.0
  iteration 2  solved to t = 1.0, 17/17 hard checks, HEALTHY_INCOMPLETE
               -> CONTINUE_RUN refused: horizon t = 1 already reached
               -> STOPPED_ACTION_REFUSED

Two defects, one visible and one not:

  visible    CONTINUE_RUN and EXTEND_END_TIME were not distinguished by the
             reasoning contract, so the model picked the one that could not
             apply and the gate could only say no.
  hidden     the deterministic validator returned PASS_2D_FORWARD_STEP at
             t = 0.5 and t = 1.0. A partial realization of a benchmark was
             being reported with the token that means final acceptance.

These tests pin the corrected semantics in both directions: the loop must be
able to advance, and it must not be able to accept early.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.agents.forward_step_spec_agent import ForwardStepRequest, to_spec
from src.pipeline.forward_step_2d.spec import (
    FAMILY_REFERENCE_HORIZON,
    ForwardStep2DSpec,
)
from src.pipeline.forward_step_2d.validate import (
    FINAL_ACCEPTABLE,
    FINAL_TARGET_NOT_REACHED,
    HARD_CHECKS_PASS,
    STATUS_HEALTHY_TARGET_NOT_REACHED,
    STATUS_INCOMPLETE,
    STATUS_PASS,
    validate,
)
from src.reasoning.forward_step_actions import validate_action

_REPO = Path(__file__).resolve().parents[2]

# The Case H specification, exactly as the corrected interpreter builds it.
CASE_H = ForwardStep2DSpec(mach=3.0, step_height=0.2, step_x=0.6, end_time=0.5)


# ----------------------------------------------------------------------
# 6. the request's original intent survives
# ----------------------------------------------------------------------


def test_case_h_initial_horizon_does_not_become_the_final_target():
    """"For the initial CFD execution, use an end time of 0.5"."""
    assert CASE_H.initial_execution_end_time == 0.5
    assert CASE_H.end_time == 0.5
    assert CASE_H.final_target_end_time == 4.0
    assert CASE_H.final_target_end_time == FAMILY_REFERENCE_HORIZON


def test_the_initial_horizon_survives_every_extension():
    """Provenance of what was first asked for must not be overwritten."""
    extended = CASE_H.with_changes(end_time=1.0).with_changes(end_time=2.0)
    assert extended.initial_execution_end_time == 0.5
    assert extended.end_time == 2.0
    assert extended.final_target_end_time == 4.0


def test_an_explicit_final_horizon_is_respected():
    """A future request naming its own final horizon is not forced to 4."""
    spec = ForwardStep2DSpec(end_time=0.5, final_target_end_time=2.0)
    assert spec.final_target_end_time == 2.0
    assert spec.initial_execution_end_time == 0.5


def test_the_interpreter_keeps_the_two_horizons_apart():
    initial_only = ForwardStepRequest(
        case_name="h", summary="x", mach=3.0, step_height=0.2, end_time=0.5
    )
    spec, provenance = to_spec(initial_only)
    assert spec.end_time == 0.5
    assert spec.final_target_end_time == FAMILY_REFERENCE_HORIZON
    assert "final_target_end_time" in provenance["inferred_from_family_defaults"]

    both = ForwardStepRequest(
        case_name="x", summary="x", mach=3.0, end_time=0.5, final_target_end_time=3.0
    )
    spec, provenance = to_spec(both)
    assert (spec.end_time, spec.final_target_end_time) == (0.5, 3.0)
    assert "final_target_end_time" in provenance["stated_by_user"]


def test_a_horizon_beyond_the_family_reference_is_not_silently_shortened():
    """Clamping a requested horizon back to 4 would shorten the ask.

    An out-of-envelope horizon is the scope gate's decision, not the
    constructor's.
    """
    spec = ForwardStep2DSpec(end_time=6.0)
    assert spec.final_target_end_time == 6.0


# ----------------------------------------------------------------------
# 4. status: current-state health is not final acceptance
# ----------------------------------------------------------------------


def _at(diagnostics: dict, spec: ForwardStep2DSpec, final_time: float) -> dict:
    """The same healthy evidence, relabelled to a different horizon."""
    d = json.loads(json.dumps(diagnostics))
    d["spec"] = spec.to_dict()
    d["final_time"] = final_time
    d["requested_end_time"] = spec.end_time
    d["reached_requested_end_time"] = final_time >= spec.end_time - 1e-9
    return d


def test_healthy_but_short_of_the_target_is_not_a_pass(synthetic_diagnostics):
    """The hidden defect: t = 0.5 of a t = 4 benchmark reported as PASS."""
    result = validate(_at(synthetic_diagnostics, CASE_H, 0.5))

    assert result["failed_checks"] == []
    assert result["hard_checks_status"] == HARD_CHECKS_PASS
    assert all(result["hard_checks"].values())

    assert result["status"] == STATUS_HEALTHY_TARGET_NOT_REACHED
    assert result["status"] != STATUS_PASS
    assert result["final_acceptance"]["status"] == FINAL_TARGET_NOT_REACHED
    assert result["final_acceptance"]["final_acceptable"] is False


def test_the_same_evidence_at_the_target_is_finally_acceptable(synthetic_diagnostics):
    spec = CASE_H.with_changes(end_time=4.0)
    result = validate(_at(synthetic_diagnostics, spec, 4.0))

    assert result["hard_checks_status"] == HARD_CHECKS_PASS
    assert result["status"] == STATUS_PASS
    assert result["final_acceptance"]["status"] == FINAL_ACCEPTABLE
    assert result["final_acceptance"]["final_acceptable"] is True


def test_a_failed_hard_check_outranks_the_horizon(synthetic_diagnostics):
    d = _at(synthetic_diagnostics, CASE_H.with_changes(end_time=4.0), 4.0)
    d["fatal_error"] = True
    result = validate(d)
    assert result["status"] == "FAIL"
    assert result["hard_checks_status"] == "FAIL_HARD_CHECKS"
    assert result["final_acceptance"]["status"] == "BLOCKED_BY_FAILED_CHECKS"


def test_stopping_short_of_the_current_horizon_is_still_incomplete(
    synthetic_diagnostics,
):
    d = _at(synthetic_diagnostics, CASE_H, 0.3)
    result = validate(d)
    assert result["status"] == STATUS_INCOMPLETE


def test_final_acceptance_records_all_three_horizons(synthetic_diagnostics):
    """The report must show what was asked, what ran, and what is required."""
    spec = CASE_H.with_changes(end_time=1.0)
    acceptance = validate(_at(synthetic_diagnostics, spec, 1.0))["final_acceptance"]
    assert acceptance["initial_execution_end_time"] == 0.5
    assert acceptance["current_requested_end_time"] == 1.0
    assert acceptance["final_target_end_time"] == 4.0
    assert acceptance["final_time"] == 1.0


# ----------------------------------------------------------------------
# 1-4. action semantics
# ----------------------------------------------------------------------


def _evidence(final_time: float, spec: ForwardStep2DSpec, **overrides) -> dict:
    base = {
        "fatal_error": False,
        "finite_all_saved": True,
        "positive_all_saved": True,
        "minima_every_step": {"rho": 0.1, "p": 0.1, "T": 0.5},
        "courant_finite_positive": True,
        "final_time": final_time,
        "reached_requested_end_time": final_time >= spec.end_time - 1e-9,
    }
    base.update(overrides)
    return base


def _gate(action, spec, final_time, validation=None, **kw):
    kw.setdefault("max_end_time", 12.0)
    kw.setdefault("iterations_used", 1)
    kw.setdefault("max_iterations", 6)
    reached_target = final_time >= spec.final_target_end_time - 1e-9
    default_validation = {
        "status": STATUS_PASS if reached_target else STATUS_HEALTHY_TARGET_NOT_REACHED,
        "failed_checks": [],
    }
    return validate_action(
        action,
        spec,
        _evidence(final_time, spec),
        validation or default_validation,
        **kw,
    )


def test_1_stopped_before_the_current_target_allows_continue_run():
    """The solver stopped short of the horizon it was given."""
    spec = CASE_H.with_changes(end_time=1.0)
    result = _gate("CONTINUE_RUN", spec, final_time=0.7)
    assert result.approved
    assert result.resulting_changes["resume_from"] == 0.7
    assert result.resulting_changes["end_time"] == 1.0


def test_2_reached_the_current_target_but_not_the_final_allows_extend():
    """Case H at t = 1.0: the action that should have been available."""
    spec = CASE_H.with_changes(end_time=1.0)
    result = _gate("EXTEND_END_TIME", spec, final_time=1.0)
    assert result.approved
    assert result.resulting_changes["end_time"] == 2.0
    assert "final target t = 4" in " ".join(result.reasons)


def test_2b_continue_run_is_refused_and_names_the_right_action():
    """The exact refusal Case H hit, now carrying a way forward."""
    spec = CASE_H.with_changes(end_time=1.0)
    result = _gate("CONTINUE_RUN", spec, final_time=1.0)
    assert not result.approved
    reason = " ".join(result.reasons)
    assert "already reached" in reason
    assert "EXTEND_END_TIME is the action" in reason


def test_2c_extend_is_refused_while_an_execution_is_outstanding():
    """The mirror error: moving the horizon instead of finishing the run."""
    spec = CASE_H.with_changes(end_time=1.0)
    result = _gate("EXTEND_END_TIME", spec, final_time=0.7)
    assert not result.approved
    assert "CONTINUE_RUN is the action" in " ".join(result.reasons)


def test_3_reaching_the_final_target_allows_accept():
    spec = CASE_H.with_changes(end_time=4.0)
    result = _gate("ACCEPT", spec, final_time=4.0)
    assert result.approved


def test_3b_accept_is_refused_below_the_final_target_despite_healthy_checks():
    """Deterministic authority: the model cannot accept an unfinished run."""
    spec = CASE_H.with_changes(end_time=1.0)
    result = _gate("ACCEPT", spec, final_time=1.0)
    assert not result.approved
    reason = " ".join(result.reasons)
    assert "healthy on all hard checks" in reason
    assert "EXTEND_END_TIME is the action" in reason


def test_4_extension_never_overshoots_the_final_target():
    """Doubling 3 would reach 6; the target is 4."""
    spec = CASE_H.with_changes(end_time=3.0)
    result = _gate("EXTEND_END_TIME", spec, final_time=3.0)
    assert result.approved
    assert result.resulting_changes["end_time"] == 4.0


def test_4b_extension_past_a_satisfied_target_is_refused():
    spec = CASE_H.with_changes(end_time=4.0)
    result = _gate("EXTEND_END_TIME", spec, final_time=4.0)
    assert not result.approved
    assert "ACCEPT or FAIL_SAFELY" in " ".join(result.reasons)


def test_4c_extension_is_refused_on_an_unhealthy_state():
    spec = CASE_H.with_changes(end_time=1.0)
    unhealthy = _evidence(1.0, spec, positive_all_saved=False)
    result = validate_action(
        "EXTEND_END_TIME",
        spec,
        unhealthy,
        {"status": STATUS_HEALTHY_TARGET_NOT_REACHED, "failed_checks": []},
        max_end_time=12.0,
        iterations_used=1,
        max_iterations=6,
    )
    assert not result.approved
    assert "not numerically healthy" in " ".join(result.reasons)


def test_4d_extension_is_refused_once_the_iteration_budget_is_spent():
    spec = CASE_H.with_changes(end_time=1.0)
    result = _gate(
        "EXTEND_END_TIME", spec, final_time=1.0, iterations_used=6, max_iterations=6
    )
    assert not result.approved
    assert "budget" in " ".join(result.reasons)


def test_the_full_case_h_ladder_terminates_at_the_target():
    """0.5 -> 1 -> 2 -> 4, then ACCEPT. No step overshoots, none stalls."""
    spec = CASE_H
    reached = [spec.end_time]
    for _ in range(6):
        final_time = spec.end_time
        if final_time >= spec.final_target_end_time - 1e-9:
            break
        gate = _gate("EXTEND_END_TIME", spec, final_time=final_time)
        assert gate.approved, gate.reasons
        spec = spec.with_changes(end_time=gate.resulting_changes["end_time"])
        reached.append(spec.end_time)

    assert reached == [0.5, 1.0, 2.0, 4.0]
    assert _gate("ACCEPT", spec, final_time=4.0).approved


# ----------------------------------------------------------------------
# 7. resume must continue, not restart
# ----------------------------------------------------------------------


def test_7_continue_run_resumes_from_the_existing_solution_time():
    """resume_from is the solved time, never zero."""
    spec = CASE_H.with_changes(end_time=2.0)
    result = _gate("CONTINUE_RUN", spec, final_time=1.0)
    assert result.approved
    assert result.resulting_changes["resume_from"] == 1.0
    assert result.resulting_changes["resume_from"] != 0


def test_7b_the_orchestrator_sets_startfrom_latesttime_for_every_continuation():
    """The resume path must never emit startFrom startTime."""
    source = (_REPO / "scripts" / "run_forward_step_2d.py").read_text()
    assert "startFrom       latestTime;" in source
    assert "startFrom       startTime;" not in source
    # A continuation is tied to the CASE, not to the iteration number: an
    # iteration that runs on a newly built mesh must be a fresh solve. The
    # earlier rule, append = iteration > 1, would have continued into a grid
    # whose fields do not exist.
    assert "append = last_executed_case == case" in source
    assert "append = iteration > 1" not in source
    assert '" --append" if append else ""' in source


def test_7c_resume_skips_the_first_execution_entirely():
    """A resumed loop re-reads the existing fields before doing any solving."""
    source = (_REPO / "scripts" / "run_forward_step_2d.py").read_text()
    assert "skip_execution = resumed" in source
    assert "no solver execution" in source


def test_7d_resume_preserves_prior_iteration_numbering():
    source = (_REPO / "scripts" / "run_forward_step_2d.py").read_text()
    assert "iteration = self.iteration_offset" in source
    assert "limit = self.iteration_offset + args.max_iterations" in source


@pytest.mark.parametrize("name", ["agent_result.json", "events.log", "provenance.json"])
def test_7e_resume_archives_the_previous_run_documents(tmp_path, name):
    """The refused-action record is development provenance and must survive."""
    from scripts.run_forward_step_2d import archive_prior_run

    run = tmp_path / "case_H"
    run.mkdir()
    (run / name).write_text('{"status": "STOPPED_ACTION_REFUSED"}')
    (run / "iteration_02").mkdir()

    archive = archive_prior_run(run)

    assert archive is not None and (archive / name).is_file()
    assert "STOPPED_ACTION_REFUSED" in (archive / name).read_text()
    # Per-iteration evidence is additive and is never moved.
    assert (run / "iteration_02").is_dir()


def test_7f_resume_recovers_the_original_initial_horizon(tmp_path):
    """Case H's spec.json says 1.0; the request said 0.5.

    A case extended before the horizons were separated has lost the initial
    horizon from its spec. The run's preserved provenance still has it, and
    the resume must read it back rather than report the last extension as
    what the user asked for.
    """
    import argparse

    from scripts.run_forward_step_2d import ForwardStepRun

    run_dir = tmp_path / "case_H"
    run_dir.mkdir()
    (run_dir / "provenance.json").write_text(
        json.dumps(
            {
                "iterations": [
                    {"iteration": 1, "spec": {"end_time": 0.5}},
                    {"iteration": 2, "spec": {"end_time": 1.0}},
                ]
            }
        )
    )
    (run_dir / "iteration_01").mkdir()
    (run_dir / "iteration_02").mkdir()

    args = argparse.Namespace(out=str(run_dir), resume_case="/somewhere/case")
    run = ForwardStepRun(args, "request")

    assert run._earliest_recorded_end_time() == 0.5
    assert run.iteration_offset == 2
    assert len(run.prior_iterations) == 2
    assert run.provenance["resume"]["solver_restarted_from_zero"] is False
    assert run.provenance["iterations"] == run.prior_iterations
