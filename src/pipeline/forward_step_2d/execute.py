#!/usr/bin/env python3
"""Bounded serial shockFluid execution for the 2D forward-step family.

PROVENANCE
----------
Control flow transcribed from ``src/pipeline/nozzle/execute.py``, which is the
proven bounded executor in this repository: wall-clock bound, stall detection,
non-physical extrema detection from the running monitor, process-group
termination and an ``execution.json`` record. The nozzle-specific pieces are
replaced with the forward-step monitor layout.

Differences from the nozzle executor, both required by this family:

* the non-physical screen reads ``postProcessing/minima`` (rho, p, T), not the
  nozzle's ``extrema`` object;
* ``--append`` records a continuation rather than refusing to overwrite, so an
  approved CONTINUE_RUN can extend the same case from ``latestTime``.

The solver is invoked exactly as the tutorial does: ``foamRun -case <case>``.
``shockFluid`` is selected by ``solver shockFluid;`` inside system/controlDict.
This script never edits a dictionary.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import signal
import subprocess
import sys
import time
from pathlib import Path

STALL_SECONDS = 300.0


def tail(path: Path, n: int = 16000) -> str:
    try:
        with path.open("rb") as f:
            f.seek(0, 2)
            f.seek(max(0, f.tell() - n))
            return f.read().decode(errors="replace")
    except FileNotFoundError:
        return ""


def _monitor_rows(case: Path) -> list:
    directory = case / "postProcessing/minima"
    if not directory.exists():
        return []
    files = sorted(directory.rglob("*.dat"))
    if not files:
        return []
    return tail(files[-1], 4000).splitlines()


def execute(case: Path, events: bool = False, append: bool = False) -> int:
    case = Path(case)
    wall_limit = float(os.environ.get("FORWARD_STEP_WALL_LIMIT_S", "7200"))

    end_time = None
    try:
        end_time = float(
            json.loads((case / "spec.json").read_text(encoding="utf-8-sig"))["end_time"]
        )
    except Exception:
        end_time = None

    log_path = case / "log.foamRun"
    if log_path.exists() and not append:
        raise FileExistsError(
            f"Existing solver evidence preserved: {log_path}. "
            "Pass --append for an approved continuation."
        )

    start = time.monotonic()
    last_progress = start
    last_time = -1.0
    last_event = 0.0
    reason = None

    env = os.environ.copy()
    env["FOAM_SIGFPE"] = "true"

    with log_path.open("a" if append else "w") as log:
        proc = subprocess.Popen(
            ["foamRun", "-case", str(case)],
            stdout=log,
            stderr=subprocess.STDOUT,
            env=env,
            start_new_session=True,
        )

        while proc.poll() is None:
            time.sleep(2)
            now = time.monotonic()

            text = tail(log_path)
            matches = re.findall(r"^Time = ([\d.eE+-]+)s?", text, re.M)
            if matches:
                try:
                    value = float(matches[-1])
                except ValueError:
                    value = last_time
                if value > last_time:
                    last_time = value
                    last_progress = now

            rows = _monitor_rows(case)
            if rows and not rows[-1].startswith("#"):
                try:
                    values = [float(s) for s in rows[-1].split()]
                    if len(values) == 4 and any(
                        not (v > 0 and v < float("inf")) for v in values[1:]
                    ):
                        reason = "NONPHYSICAL"
                except ValueError:
                    pass

            if events and now - last_event >= 10 and last_time > 0:
                last_event = now
                fraction = (
                    f" ({100 * last_time / end_time:5.1f}%)" if end_time else ""
                )
                print(
                    f"[EXECUTOR] shockFluid solver time = {last_time:.6g}"
                    f"{fraction}  wall = {now - start:.0f} s",
                    flush=True,
                )

            if now - start > wall_limit:
                reason = "TIMED_OUT"
            elif now - last_progress > STALL_SECONDS:
                reason = "STALLED"

            if reason:
                os.killpg(proc.pid, signal.SIGTERM)
                try:
                    proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    os.killpg(proc.pid, signal.SIGKILL)
                    proc.wait()
                break

        code = proc.wait()

    elapsed = time.monotonic() - start

    record = {
        "status": reason or ("COMPLETED" if code == 0 else "FAILED"),
        "returncode": code,
        "wall_seconds": elapsed,
        "last_observed_time": last_time,
        "requested_end_time": end_time,
        "wall_limit_seconds": wall_limit,
        "stall_limit_seconds": STALL_SECONDS,
        "serial": True,
        "continuation": bool(append),
        "command": f"foamRun -case {case}",
    }

    history_path = case / "execution.json"
    history = []
    if append and history_path.exists():
        try:
            previous = json.loads(history_path.read_text(encoding="utf-8-sig"))
            history = previous if isinstance(previous, list) else [previous]
        except json.JSONDecodeError:
            history = []
    history.append(record)
    history_path.write_text(json.dumps(history, indent=2))

    (case / "solver.exitcode").write_text(str(code) + "\n")

    print(json.dumps(record, indent=2))
    return 0 if code == 0 and reason is None else 3


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Bounded shockFluid execution.")
    ap.add_argument("case", type=Path)
    ap.add_argument("--events", action="store_true")
    ap.add_argument(
        "--append",
        action="store_true",
        help="Record a continuation instead of refusing an existing log.",
    )
    args = ap.parse_args()
    sys.exit(execute(args.case, args.events, args.append))
