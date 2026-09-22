#!/usr/bin/env python3
"""Regression tests for deterministic reanalysis of a completed run.

A deterministic check that is found to be wrong has to be re-applied to
evidence that already exists. Rerunning the solver would produce a different
calculation and destroy the ability to say "the same run, judged correctly",
so reanalysis must never invoke OpenFOAM and must never alter the CFD fields.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from src.pipeline.forward_step_2d.reanalyse import (
    find_solver_logs,
    reanalyse_run,
    rescan_fatal,
)
from src.pipeline.forward_step_2d.validate import STATUS_FAIL, STATUS_PASS

BANNER = "sigFpe : Enabling floating point exception trapping (FOAM_SIGFPE).\n"
HEALTHY_LOG = BANNER + "Starting time loop\n\nTime = 4s\nExecutionTime = 112 s\n\nEnd\n"
CRASHED_LOG = BANNER + "Time = 0.2s\n\n--> FOAM FATAL ERROR:\nsolver diverged\n"


def _fetched_run(root: Path, diagnostics: dict, log_text: str, log_name: str) -> Path:
    """Build a run directory shaped like one the orchestrator fetches back."""
    run = root / "live_run"
    (run / "iteration_01").mkdir(parents=True)
    (run / "logs").mkdir()
    (run / "logs" / log_name).write_text(log_text)
    (run / "execution.json").write_text(
        json.dumps([{"status": "COMPLETED", "returncode": 0}])
    )
    (run / "iteration_01" / "diagnostics.json").write_text(json.dumps(diagnostics))
    (run / "iteration_01" / "validation.json").write_text(
        json.dumps({"status": STATUS_FAIL, "failed_checks": ["no_fatal_error"]})
    )
    return run


def test_reanalysis_clears_a_false_positive(tmp_path, synthetic_diagnostics):
    """The live_run_01 situation: one bad check, everything else healthy."""
    stale = dict(synthetic_diagnostics)
    stale["fatal_error"] = True
    stale["fatal_error_evidence"] = [
        {"signature": "legacy_substring_match", "line": BANNER.strip()}
    ]
    run = _fetched_run(tmp_path, stale, HEALTHY_LOG, "log.foamRun")

    summary = reanalyse_run(run)
    (result,) = summary["iterations"]

    assert summary["solver_executed"] is False
    assert summary["cfd_fields_modified"] is False
    assert result["previous_status"] == STATUS_FAIL
    assert result["previous_failed_checks"] == ["no_fatal_error"]
    assert result["status"] == STATUS_PASS
    assert result["failed_checks"] == []
    assert result["fatal_error"] is False
    assert result["fatal_scan"]["solver_log_complete"] is True


def test_reanalysis_still_fails_a_genuinely_crashed_run(tmp_path, synthetic_diagnostics):
    run = _fetched_run(tmp_path, synthetic_diagnostics, CRASHED_LOG, "log.foamRun")
    (result,) = reanalyse_run(run)["iterations"]
    assert result["status"] == STATUS_FAIL
    assert "no_fatal_error" in result["failed_checks"]
    assert result["fatal_error_evidence"][0]["signature"] == "foam_fatal_error"


def test_reanalysis_preserves_the_original_evidence(tmp_path, synthetic_diagnostics):
    stale = dict(synthetic_diagnostics)
    stale["fatal_error"] = True
    run = _fetched_run(tmp_path, stale, HEALTHY_LOG, "log.foamRun")
    original = (run / "iteration_01" / "validation.json").read_bytes()
    original_diagnostics = (run / "iteration_01" / "diagnostics.json").read_bytes()

    reanalyse_run(run)

    assert (run / "iteration_01" / "validation.json").read_bytes() == original
    assert (run / "iteration_01" / "diagnostics.json").read_bytes() == original_diagnostics
    assert (run / "iteration_01" / "reanalysis" / "validation.json").is_file()


def test_field_measurements_are_carried_forward_not_recomputed(
    tmp_path, synthetic_diagnostics
):
    """Fields are absent from a fetched run, so they must not be invented."""
    stale = dict(synthetic_diagnostics)
    stale["fatal_error"] = True
    updated = rescan_fatal(stale, None, [{"status": "COMPLETED", "returncode": 0}])

    changed = {k for k in updated if updated[k] != stale.get(k)}
    assert changed <= {"fatal_error", "fatal_error_evidence", "fatal_scan"}
    assert updated["mass"] == stale["mass"]
    assert updated["final_ranges"] == stale["final_ranges"]
    assert updated["shock"] == stale["shock"]


def test_a_partial_log_is_declared_partial(tmp_path, synthetic_diagnostics):
    run = _fetched_run(
        tmp_path, synthetic_diagnostics, HEALTHY_LOG, "log.foamRun.tail"
    )
    (result,) = reanalyse_run(run)["iterations"]
    scan = result["fatal_scan"]
    assert scan["solver_log_complete"] is False
    assert "partial_log_note" in scan
    assert scan["end_line_present"] is True


def test_head_and_tail_are_both_scanned(tmp_path, synthetic_diagnostics):
    run = _fetched_run(tmp_path, synthetic_diagnostics, BANNER, "log.foamRun.head")
    (run / "logs" / "log.foamRun.tail").write_text(CRASHED_LOG)

    names = {p.name for p in find_solver_logs(run)}
    assert names == {"log.foamRun.head", "log.foamRun.tail"}

    (result,) = reanalyse_run(run)["iterations"]
    assert result["status"] == STATUS_FAIL
    assert result["fatal_error_evidence"][0]["log"] == "log.foamRun.tail"


def test_a_complete_log_wins_over_excerpts(tmp_path, synthetic_diagnostics):
    run = _fetched_run(tmp_path, synthetic_diagnostics, HEALTHY_LOG, "log.foamRun")
    (run / "logs" / "log.foamRun.tail").write_text(CRASHED_LOG)
    assert [p.name for p in find_solver_logs(run)] == ["log.foamRun"]


def test_reanalysis_refuses_a_generated_document_as_the_log(
    tmp_path, synthetic_diagnostics
):
    run = _fetched_run(tmp_path, synthetic_diagnostics, HEALTHY_LOG, "log.foamRun")
    summary = run / "SCIENTIFIC_SUMMARY.md"
    summary.write_text("Status FAIL: a FOAM FATAL ERROR was reported.")
    with pytest.raises(ValueError, match="not a raw solver log"):
        reanalyse_run(run, solver_log=summary)


# ----------------------------------------------------------------------
# the full-fidelity path: a runtime case, re-judged from its native fields
# ----------------------------------------------------------------------


def _fingerprint(case: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    for path in sorted(case.rglob("*")):
        if path.is_file() and "postProcessing" not in str(path):
            digest.update(path.read_bytes())
    return digest.hexdigest()


def test_full_reanalysis_does_not_modify_the_solved_case(tmp_path):
    """A case that changed under reanalysis would be worthless as evidence."""
    from src.pipeline.forward_step_2d.reanalyse import reanalyse_case
    from tests.forward_step_2d.synthetic import make_case

    case = make_case(tmp_path)
    before = _fingerprint(case)
    reanalyse_case(case, tmp_path / "evidence_full")
    assert _fingerprint(case) == before


def test_full_reanalysis_regenerates_every_expected_figure(tmp_path):
    """The first live run archived eight of nine; transient_conservation was
    dropped by the fetch list, not by the plotting code."""
    from scripts.run_forward_step_2d import ARCHIVE_IMAGE_KEYS
    from src.pipeline.forward_step_2d.reanalyse import reanalyse_case
    from tests.forward_step_2d.synthetic import make_case

    case = make_case(tmp_path)
    index = reanalyse_case(case, tmp_path / "evidence_full")

    assert index["figure_error"] is None
    assert set(ARCHIVE_IMAGE_KEYS) <= set(index["figures"])
    assert "transient_conservation" in index["figures"]
    for path in index["figures"].values():
        assert Path(path).stat().st_size > 0


def test_full_reanalysis_declares_a_complete_log_scan(tmp_path):
    from src.pipeline.forward_step_2d.reanalyse import reanalyse_case
    from tests.forward_step_2d.synthetic import make_case

    case = make_case(tmp_path)
    reanalyse_case(case, tmp_path / "evidence_full")
    diagnostics = json.loads(
        (tmp_path / "evidence_full" / "diagnostics.json").read_text()
    )
    assert diagnostics["fatal_scan"]["solver_log_complete"] is True
    assert diagnostics["fatal_error"] is False
