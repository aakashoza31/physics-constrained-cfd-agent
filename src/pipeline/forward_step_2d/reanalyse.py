#!/usr/bin/env python3
"""Deterministic reanalysis of an already-completed 2D forward-step run.

WHY THIS EXISTS
---------------
When a deterministic check is found to be wrong, the fix must be applied to
evidence that already exists. Rerunning the solver would produce a *different*
calculation and would quietly destroy the ability to say "the same run, judged
correctly". This module therefore recomputes the log-derived flags and re-runs
the scientific validator over a finished run, and never invokes OpenFOAM.

Two entry points, for the two places a finished run can live:

``reanalyse_case``
    A case directory still present in the OpenFOAM runtime. Everything is
    available - the complete solver log and every saved field - so the full
    ``diagnose`` pass is rerun from the native fields. This is the
    highest-fidelity reanalysis and is what ``collect_evidence`` already does;
    it is exposed here so it can be invoked without the solver.

``reanalyse_run``
    A fetched run directory (``demo/forward_step_2d/<run>``), containing the
    stored ``diagnostics.json`` plus whatever raw logs were fetched back. The
    field-derived measurements are reused verbatim - they are measurements of
    fields this module does not have and must not invent - and only the
    log-derived flags are recomputed, from raw solver log text.

WHAT IS AND IS NOT RECOMPUTED BY ``reanalyse_run``
--------------------------------------------------
Recomputed: ``fatal_error`` and its evidence, from the raw solver log and the
executor records.

Reused unchanged: every field measurement (ranges, positivity, finiteness,
conservation, Courant history, shock metrics). These came from the native
OpenFOAM fields at run time. Recomputing them without the fields is impossible
and fabricating them is not an option, so they are carried forward exactly as
the original run measured them, and the provenance record says so.

HONESTY ABOUT LOG SCOPE
-----------------------
A fetched run may hold only an excerpt of the solver log. "No fatal signature
found" over an excerpt is a weaker statement than over the whole log, so the
reanalysis records ``solver_log_complete`` and, when the log is partial, the
independent grounds that still establish normal termination: OpenFOAM writes
``End`` and exits zero only after the time loop finishes: a FOAM FATAL ERROR
aborts the process, so ``End`` with return code 0 cannot coexist with one.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from .diagnostics import (
    RAW_SOLVER_LOG_PREFIX,
    read_raw_solver_log,
    scan_fatal_signatures,
    scan_process_failure,
)
from .validate import validate

#: A complete solver log, if one was fetched, ends the search.
COMPLETE_LOG_CANDIDATES = ("logs/log.foamRun", "log.foamRun")

#: Otherwise every excerpt present is scanned, so head and tail both count.
EXCERPT_LOG_CANDIDATES = (
    "logs/log.foamRun.head",
    "logs/log.foamRun.tail",
    "log.foamRun.head",
    "log.foamRun.tail",
)


def find_solver_logs(run: Path) -> List[Path]:
    """Locate raw solver logs in a fetched run directory.

    A complete log wins outright. Failing that, every excerpt present is
    returned so that head and tail are both scanned rather than one silently
    standing in for the whole run.
    """
    for relative in COMPLETE_LOG_CANDIDATES:
        candidate = run / relative
        if candidate.is_file():
            return [candidate]
    return [run / r for r in EXCERPT_LOG_CANDIDATES if (run / r).is_file()]


def _iteration_dirs(run: Path) -> List[Path]:
    return sorted(d for d in run.glob("iteration_*") if d.is_dir())


def rescan_fatal(
    diagnostics: Dict[str, Any],
    solver_logs,
    execution: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Recompute the fatal flag on a stored diagnostics document.

    ``solver_logs`` is one path or a list of raw solver logs. Returns a new
    diagnostics dict; the input is not mutated.
    """
    from .diagnostics import FATAL_SIGNATURES

    if solver_logs is None:
        solver_logs = []
    elif isinstance(solver_logs, (str, Path)):
        solver_logs = [Path(solver_logs)]

    updated = dict(diagnostics)
    records = execution if execution is not None else diagnostics.get("execution", [])

    hits: List[Dict[str, Any]] = []
    scanned: List[Dict[str, Any]] = []
    end_seen = False

    for path in solver_logs:
        text = read_raw_solver_log(path)
        found = scan_fatal_signatures(text)
        for hit in found:
            hit["log"] = path.name
        hits.extend(found)
        end_seen = end_seen or text.rstrip().endswith("End") or "\nEnd\n" in text
        scanned.append(
            {
                "log": path.name,
                "bytes": len(text),
                "excerpt": path.name != "log.foamRun",
            }
        )

    complete = any(entry["excerpt"] is False for entry in scanned)
    scan: Dict[str, Any] = {
        "logs_scanned": scanned,
        "solver_log": scanned[0]["log"] if scanned else None,
        "solver_log_bytes": sum(entry["bytes"] for entry in scanned),
        "solver_log_complete": complete,
        "signatures_checked": [name for name, _ in FATAL_SIGNATURES],
        "benign_excluded": "FOAM_SIGFPE / sigSegv / sigInt / sigQuit startup banner",
    }

    if scanned and not complete:
        scan["end_line_present"] = end_seen
        scan["partial_log_note"] = (
            "Only excerpts of the solver log are present in this run "
            "directory. Normal termination is established independently by "
            "the executor record (return code 0, status COMPLETED) and by the "
            "terminating 'End' line: OpenFOAM writes End only after the time "
            "loop completes, and a FOAM FATAL ERROR aborts the process before "
            "it, so the two cannot coexist. For a scan over the complete log, "
            "reanalyse the runtime case directory with --case."
        )
    elif not scanned:
        scan["no_log_note"] = (
            "No raw solver log was present in this run directory. The fatal "
            "flag then rests on the executor records alone."
        )

    hits.extend(scan_process_failure(records))

    updated["fatal_error"] = bool(hits)
    updated["fatal_error_evidence"] = hits
    updated["fatal_scan"] = scan
    return updated


def reanalyse_run(
    run,
    output=None,
    solver_log: Optional[Path] = None,
) -> Dict[str, Any]:
    """Re-judge a fetched run directory without touching the CFD fields.

    Writes the reanalysis beside the original evidence, never over it: the
    original diagnostics.json and validation.json are the record of what the
    agent decided at the time and are preserved.
    """
    run = Path(run)
    execution_path = run / "execution.json"
    execution: List[Dict[str, Any]] = []
    if execution_path.is_file():
        loaded = json.loads(execution_path.read_text(encoding="utf-8-sig"))
        execution = loaded if isinstance(loaded, list) else [loaded]

    logs = [Path(solver_log)] if solver_log else find_solver_logs(run)
    for path in logs:
        if not path.name.startswith(RAW_SOLVER_LOG_PREFIX):
            raise ValueError(
                f"{path.name!r} is not a raw solver log; refusing to scan it."
            )

    iterations = _iteration_dirs(run)
    if not iterations:
        raise FileNotFoundError(f"No iteration_* directory found under {run}")

    results = []
    for iteration in iterations:
        stored = iteration / "diagnostics.json"
        if not stored.is_file():
            continue
        before = json.loads(stored.read_text(encoding="utf-8-sig"))
        after = rescan_fatal(before, logs, execution)
        validation = validate(after)

        destination = Path(output) / iteration.name if output else iteration / "reanalysis"
        destination.mkdir(parents=True, exist_ok=True)
        (destination / "diagnostics.json").write_text(
            json.dumps(after, indent=2), encoding="utf-8"
        )
        (destination / "validation.json").write_text(
            json.dumps(validation, indent=2), encoding="utf-8"
        )

        previous = iteration / "validation.json"
        previous_status = None
        previous_failed: List[str] = []
        if previous.is_file():
            document = json.loads(previous.read_text(encoding="utf-8-sig"))
            previous_status = document.get("status")
            previous_failed = document.get("failed_checks", [])

        results.append(
            {
                "iteration": iteration.name,
                "previous_status": previous_status,
                "previous_failed_checks": previous_failed,
                "status": validation["status"],
                "failed_checks": validation["failed_checks"],
                "fatal_error": after["fatal_error"],
                "fatal_error_evidence": after["fatal_error_evidence"],
                "fatal_scan": after["fatal_scan"],
                "output": str(destination),
            }
        )

    summary = {
        "run": str(run),
        "mode": "fetched_run_directory",
        "solver_executed": False,
        "cfd_fields_modified": False,
        "recomputed": ["fatal_error", "fatal_error_evidence", "fatal_scan"],
        "reused_from_original_measurement": (
            "All field-derived quantities: positivity, finiteness, ranges, "
            "Courant history, transient mass balance and shock metrics. These "
            "measure native OpenFOAM fields that are not present in a fetched "
            "run directory; they are carried forward unchanged, not recomputed "
            "and not invented."
        ),
        "iterations": results,
    }

    target = Path(output) if output else run
    target.mkdir(parents=True, exist_ok=True)
    (target / "REANALYSIS.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )
    return summary


def reanalyse_case(case, output, reference: Optional[str] = None):
    """Re-judge a runtime case directory from its native fields. No solver.

    This is the full-fidelity path: the complete solver log and every saved
    field are present, so every measurement is recomputed from the fields
    themselves rather than carried forward. The spec is read from the case,
    so the reanalysis cannot silently be run against a different geometry.
    """
    from .collect_evidence import collect

    return collect(case, output, reference=reference)


def main() -> int:
    import argparse

    ap = argparse.ArgumentParser(
        description=(
            "Deterministically re-judge a completed 2D forward-step run. "
            "Never invokes OpenFOAM and never modifies CFD fields."
        )
    )
    source = ap.add_mutually_exclusive_group(required=True)
    source.add_argument("--run", help="Fetched run directory (demo/forward_step_2d/...).")
    source.add_argument("--case", help="Runtime case directory, for a full reanalysis.")
    ap.add_argument("--out", default=None)
    ap.add_argument("--solver-log", default=None, help="Explicit raw log.foamRun path.")
    ap.add_argument("--reference", default=None)
    args = ap.parse_args()

    if args.run:
        summary = reanalyse_run(
            args.run,
            output=args.out,
            solver_log=Path(args.solver_log) if args.solver_log else None,
        )
    else:
        summary = reanalyse_case(
            args.case,
            args.out or (Path(args.case).parent / "reanalysis"),
            reference=args.reference,
        )

    print(json.dumps(summary, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
