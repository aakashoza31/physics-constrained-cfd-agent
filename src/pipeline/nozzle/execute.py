#!/usr/bin/env python3
"""Bounded serial execution; distinguish timeout, stall, and numerical failure.

PROVENANCE
----------
Transcription of validation/canonical_reference/execute.py (frozen scientific
authority).  The control flow, wall-clock bound, stall detection, non-physical
extrema detection, process-group termination, exit code recording and process
return semantics are unchanged.

The only addition is an optional ``--events`` flag that prints real solver
progress lines to stdout while the loop is already polling the log, so the
orchestrator's event stream reflects actual solver state rather than an
animation.  It does not change any decision the script makes.
"""
import argparse
import json
import os
import re
import signal
import subprocess
import sys
import time
from pathlib import Path


def tail(path, n=12000):
    try:
        with path.open('rb') as f:
            f.seek(0, 2)
            f.seek(max(0, f.tell() - n))
            return f.read().decode(errors='replace')
    except FileNotFoundError:
        return ''


def execute(case: Path, events: bool = False) -> int:
    wall_limit = float(os.environ.get('REFERENCE_WALL_LIMIT_S', '7200'))

    end_time = None

    try:
        end_time = float(
            json.loads(
                (case / 'manifest.json').read_text(encoding='utf-8-sig')
            )['end_time']
        )
    except Exception:
        end_time = None

    start = time.monotonic()
    last_progress = start
    last_time = -1.
    last_event = 0.
    reason = None

    env = os.environ.copy()
    env['FOAM_SIGFPE'] = 'true'

    with (case / 'log.foamRun').open('w') as log:
        p = subprocess.Popen(
            ['foamRun', '-case', str(case)],
            stdout=log,
            stderr=subprocess.STDOUT,
            env=env,
            start_new_session=True,
        )

        while p.poll() is None:
            time.sleep(2)

            now = time.monotonic()
            txt = tail(case / 'log.foamRun')
            matches = re.findall(r'^Time = ([\d.eE+-]+)s', txt, re.M)

            if matches and float(matches[-1]) > last_time:
                last_time = float(matches[-1])
                last_progress = now

            mins = tail(
                case / 'postProcessing/extrema/0/volFieldValue.dat', 2000
            ).splitlines()

            if mins and not mins[-1].startswith('#'):
                try:
                    vals = [float(s) for s in mins[-1].split()]

                    if len(vals) == 4 and any(
                        not (v > 0 and v < float('inf')) for v in vals[1:]
                    ):
                        reason = 'NONPHYSICAL'
                except ValueError:
                    pass

            if events and now - last_event >= 10 and last_time > 0:
                last_event = now
                fraction = (
                    f' ({100 * last_time / end_time:5.1f}%)'
                    if end_time
                    else ''
                )
                print(
                    f'[EXECUTOR] shockFluid solver time = {last_time:.6g} s'
                    f'{fraction}  wall = {now - start:.0f} s',
                    flush=True,
                )

            if now - start > wall_limit:
                reason = 'TIMED_OUT'
            elif now - last_progress > 180:
                reason = 'STALLED'

            if reason:
                os.killpg(p.pid, signal.SIGTERM)

                try:
                    p.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    os.killpg(p.pid, signal.SIGKILL)
                    p.wait()

                break

        code = p.wait()

    elapsed = time.monotonic() - start

    (case / 'solver.exitcode').write_text(str(code) + '\n')

    (case / 'execution.json').write_text(
        json.dumps(
            {
                'status': reason
                or ('COMPLETED' if code == 0 else 'FAILED'),
                'returncode': code,
                'wall_seconds': elapsed,
                'last_observed_time': last_time,
                'wall_limit_seconds': wall_limit,
                'serial': True,
            },
            indent=2,
        )
    )

    print((case / 'execution.json').read_text())

    return 0 if code == 0 and reason is None else 3


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('case', type=Path)
    ap.add_argument('--events', action='store_true')
    args = ap.parse_args()

    sys.exit(execute(args.case, args.events))
