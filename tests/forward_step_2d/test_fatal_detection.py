#!/usr/bin/env python3
"""Regression tests for the forward-step fatal-error detector and reanalysis.

BACKGROUND
----------
The first live 2D forward-step run returned FAIL on exactly one check,
``no_fatal_error``. The matched text was

    sigFpe : Enabling floating point exception trapping (FOAM_SIGFPE).

which is normal OpenFOAM Foundation startup output on every run, including
blockMesh and checkMesh. It announces that floating-point trapping is switched
ON; it is not a trapped exception. The old detector searched
``FOAM FATAL|Floating point exception|\\bnan\\b`` case-insensitively, so the
lowercase banner matched the capitalised shell message, and a healthy run that
reached t = 4 with finite positive fields was graded FAIL.

These tests pin both directions: the banner must never fail a run, and genuine
failures must still fail one.
"""
from __future__ import annotations

import json

import pytest

from src.pipeline.forward_step_2d.diagnostics import (
    read_raw_solver_log,
    scan_fatal_signatures,
    scan_process_failure,
)
from src.pipeline.forward_step_2d.reanalyse import rescan_fatal
from src.pipeline.forward_step_2d.validate import STATUS_FAIL, STATUS_PASS, validate

# The exact line the live run tripped on, in its real startup context.
SIGFPE_BANNER = "sigFpe : Enabling floating point exception trapping (FOAM_SIGFPE)."

STARTUP = f"""/*---------------------------------------------------------------*\\
| =========                 |                                     |
\\*---------------------------------------------------------------*/
Build  : 14
Exec   : foamRun -case /home/u/.cache/case
Date   : Sep 22 2026
nProcs : 1
sigFpe : Enabling floating point exception trapping (FOAM_SIGFPE).
sigSegv : Enabling segmentation fault trapping (FOAM_SIGSEGV).
fileModificationChecking : Monitoring run-time modified files.
allowSystemOperations : Allowing user-supplied system call operations
"""

HEALTHY = STARTUP + """
Starting time loop

Time = 0.1s
Courant Number mean: 0.152 max: 0.2004
ExecutionTime = 3.1 s  ClockTime = 3 s

Time = 4s
Courant Number mean: 0.1387 max: 0.1805
ExecutionTime = 111.9 s  ClockTime = 112 s

End
"""


# ----------------------------------------------------------------------
# A. the benign startup banner must never be classified as a failure
# ----------------------------------------------------------------------


def test_sigfpe_startup_banner_alone_is_not_fatal():
    assert scan_fatal_signatures(SIGFPE_BANNER) == []


def test_sigfpe_banner_in_a_healthy_run_is_not_fatal():
    assert scan_fatal_signatures(HEALTHY) == []


def test_every_startup_signal_banner_is_benign():
    for line in STARTUP.splitlines():
        assert scan_fatal_signatures(line) == [], line


def test_healthy_run_passes_the_validator_end_to_end(synthetic_diagnostics):
    diagnostics = rescan_fatal(synthetic_diagnostics, None, HEALTHY_EXECUTION)
    assert diagnostics["fatal_error"] is False
    assert validate(diagnostics)["status"] == STATUS_PASS


# ----------------------------------------------------------------------
# B. genuine failures must still be classified as failures
# ----------------------------------------------------------------------

FOAM_FATAL = STARTUP + """
Time = 0.1s

--> FOAM FATAL ERROR:
Maximum number of iterations exceeded

    From function Foam::solve()
"""

FOAM_FATAL_IO = STARTUP + """
--> FOAM FATAL IO ERROR:
keyword divSchemes is undefined in dictionary "system/fvSchemes"
"""

# A real trap prints a stack frame. Note the benign banner is ALSO present,
# exactly as it is in a real crashed run: excluding the banner must not blind
# the detector to the crash that follows it.
REAL_FPE = STARTUP + """
Time = 0.3s
#0  Foam::error::printStack(Foam::Ostream&) at ??:?
#1  Foam::sigFpe::sigHandler(int) at ??:?
#2  ? in /lib/x86_64-linux-gnu/libc.so.6
Floating point exception (core dumped)
"""

SEGFAULT = STARTUP + """
#1  Foam::sigSegv::sigHandler(int) at ??:?
Segmentation fault (core dumped)
"""

NAN_BLOWUP = STARTUP + """
Time = 0.2s
Courant Number mean: nan max: nan
deltaT = 1e-18
"""

ABORTED = STARTUP + """
terminate called after throwing an instance of 'std::bad_alloc'
Aborted (core dumped)
"""


@pytest.mark.parametrize(
    "log, expected",
    [
        (FOAM_FATAL, "foam_fatal_error"),
        (FOAM_FATAL_IO, "foam_fatal_io_error"),
        (REAL_FPE, "floating_point_exception"),
        (SEGFAULT, "segmentation_fault"),
        (NAN_BLOWUP, "non_finite_value"),
        (ABORTED, "abnormal_termination"),
    ],
)
def test_genuine_failures_are_detected(log, expected):
    hits = scan_fatal_signatures(log)
    assert hits, f"no fatal signature found in:\n{log}"
    assert expected in {hit["signature"] for hit in hits}


def test_a_real_fpe_is_found_despite_the_benign_banner():
    """The crash and the banner coexist in a real crashed run."""
    assert SIGFPE_BANNER in REAL_FPE
    signatures = {hit["signature"] for hit in scan_fatal_signatures(REAL_FPE)}
    assert {"sigfpe_trapped", "floating_point_exception", "core_dumped"} <= signatures


def test_fatal_hits_carry_the_matched_line():
    """A future false positive must be diagnosable from the evidence alone."""
    (hit,) = [
        h for h in scan_fatal_signatures(FOAM_FATAL) if h["signature"] == "foam_fatal_error"
    ]
    assert "FOAM FATAL ERROR" in hit["line"]
    assert hit["source"] == "solver_log"


def test_a_genuine_failure_fails_the_validator(synthetic_diagnostics):
    diagnostics = rescan_fatal(synthetic_diagnostics, None, HEALTHY_EXECUTION)
    diagnostics["fatal_error"] = True
    result = validate(diagnostics)
    assert result["status"] == STATUS_FAIL
    assert "no_fatal_error" in result["failed_checks"]


# ----------------------------------------------------------------------
# process-level failure, distinguished from a bounded executor halt
# ----------------------------------------------------------------------

HEALTHY_EXECUTION = [{"status": "COMPLETED", "returncode": 0}]


@pytest.mark.parametrize(
    "record, fatal",
    [
        ({"status": "COMPLETED", "returncode": 0}, False),
        ({"status": "FAILED", "returncode": 1}, True),
        ({"status": "FAILED", "returncode": 139}, True),
        ({"status": "FAILED", "returncode": -11}, True),
        # The executor stopped the solver on purpose. These are bounded
        # control flow, graded by the horizon and positivity checks, and an
        # approved CONTINUE_RUN is the designed response.
        ({"status": "TIMED_OUT", "returncode": -15}, False),
        ({"status": "STALLED", "returncode": -15}, False),
        ({"status": "NONPHYSICAL", "returncode": -15}, False),
    ],
)
def test_process_failure_distinguishes_crashes_from_bounded_halts(record, fatal):
    assert bool(scan_process_failure([record])) is fatal


# ----------------------------------------------------------------------
# the detector must only ever be pointed at raw solver logs
# ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "name",
    [
        "SCIENTIFIC_SUMMARY.md",
        "validation.json",
        "agent_decision.json",
        "llm_evidence_payload.json",
        "events.log",
        "REANALYSIS.json",
    ],
)
def test_generated_documents_are_refused(tmp_path, name):
    """A description of a failure must never be counted as the failure."""
    path = tmp_path / name
    path.write_text("The run was graded FAIL because of a FOAM FATAL ERROR.")
    with pytest.raises(ValueError, match="raw OpenFOAM solver logs only"):
        read_raw_solver_log(path)


@pytest.mark.parametrize("name", ["log.foamRun", "log.foamRun.tail", "log.foamRun.head"])
def test_raw_solver_logs_are_accepted(tmp_path, name):
    path = tmp_path / name
    path.write_text(HEALTHY)
    assert read_raw_solver_log(path) == HEALTHY


def test_a_prior_error_report_cannot_re_fail_a_corrected_run(tmp_path):
    """The exact recursion the scope contract exists to prevent."""
    report = tmp_path / "SCIENTIFIC_SUMMARY.md"
    report.write_text(
        "Status: FAIL. The deterministic checks flagged a fatal error "
        "(FOAM FATAL ERROR) and a Floating point exception was reported."
    )
    with pytest.raises(ValueError):
        read_raw_solver_log(report)


# ----------------------------------------------------------------------
# warnings must be archived with their message, not just their marker
# ----------------------------------------------------------------------

WARNING_LOG = STARTUP + """
--> FOAM Warning :
    From function void Foam::polyMesh::checkTopology() const
    in file meshes/polyMesh/polyMesh.C at line 921
    Mesh has multiple regions

Starting time loop

Time = 0.1s
"""


def test_a_warning_is_captured_with_its_message():
    from src.pipeline.forward_step_2d.diagnostics import collect_warnings

    (warning,) = collect_warnings(WARNING_LOG)
    assert "FOAM Warning" in warning
    assert "Mesh has multiple regions" in warning
    assert "polyMesh.C at line 921" in warning


def test_warning_capture_stops_at_the_next_record():
    from src.pipeline.forward_step_2d.diagnostics import collect_warnings

    (warning,) = collect_warnings(WARNING_LOG)
    assert "Starting time loop" not in warning
    assert "Time = 0.1s" not in warning


def test_a_healthy_log_records_no_warnings():
    from src.pipeline.forward_step_2d.diagnostics import collect_warnings

    assert collect_warnings(HEALTHY) == []


def test_a_warning_is_not_a_fatal_error():
    assert scan_fatal_signatures(WARNING_LOG) == []
