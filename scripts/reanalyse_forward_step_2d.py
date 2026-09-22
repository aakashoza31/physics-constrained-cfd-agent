#!/usr/bin/env python3
"""Full-fidelity reanalysis of a completed 2D forward-step case. No solver.

    python scripts/reanalyse_forward_step_2d.py --case <runtime case path>

This stages the CURRENT deterministic pipeline into the OpenFOAM runtime and
re-derives every measurement from the native saved fields of a case that has
already been solved. It scans the complete raw solver log, recomputes the
diagnostics, regenerates every figure, re-runs the scientific validator, and
copies the finished evidence back beside the original handoff.

WHAT IT DOES NOT DO
-------------------
It never invokes ``foamRun``, ``shockFluid``, ``blockMesh`` or the bounded
executor, and it writes nothing inside the case directory. The case is opened
read-only and the reanalysis output goes to a separate runtime directory, so
the solved fields that are being re-judged cannot be disturbed by the act of
re-judging them. A case whose fields changed under reanalysis would be
worthless as evidence.

WHY IT EXISTS
-------------
A deterministic check that turns out to be wrong has to be re-applied to the
evidence that already exists. Rerunning the calculation would produce a
different one and destroy the ability to say "the same run, judged correctly".
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shlex
import sys
import time
from pathlib import Path, PurePosixPath
from typing import Any, Dict, List

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scripts.run_forward_step_2d import (  # noqa: E402
    ARCHIVE_IMAGE_KEYS,
    PIPELINE_DIR,
    TEMPLATE_DIR,
    fetch_binary,
    save_json,
)
from src.pipeline.foam_runtime import FoamRuntime, FoamRuntimeError  # noqa: E402
from src.reporting import event_stream as ev  # noqa: E402
from src.reporting.event_stream import EventStream  # noqa: E402

DATA_FILES = (
    "diagnostics.json",
    "validation.json",
    "evidence_index.json",
    "transient_mass.csv",
    "stored_totals.csv",
    "shock_front_history.csv",
)

#: Cap on copying the complete solver log back to the host. Above this the
#: head, the tail and a full anomaly extract are copied instead, and the
#: archive says which, so "complete log" is never claimed for an excerpt.
MAX_FULL_LOG_BYTES = 12 * 1024 * 1024


def _hash_case(runtime: FoamRuntime, case: PurePosixPath) -> str:
    """Fingerprint the solved fields, to prove reanalysis did not touch them."""
    result = runtime.bash(
        f"cd {shlex.quote(str(case))} && "
        "find . -path ./postProcessing -prune -o -type f -print "
        "| sort | xargs -r sha256sum | sha256sum",
        foam=False,
        timeout=600,
    )
    return result.stdout.split()[0] if result.ok and result.stdout.split() else ""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--case", required=True, help="Runtime case directory.")
    ap.add_argument(
        "--out",
        default=str(_REPO_ROOT / "demo/forward_step_2d/live_run_01/reanalysis_full"),
    )
    ap.add_argument("--reference", default=None, help="Trusted reference .npz.")
    ap.add_argument("--distro")
    ap.add_argument("--bashrc")
    args = ap.parse_args()

    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    stream = EventStream(out, case_id="forward_step_2d_reanalysis")
    s = stream

    print()
    print("=" * 78)
    print("  2D FORWARD-STEP FULL-FIDELITY REANALYSIS   (no solver is invoked)")
    print("=" * 78)

    summary: Dict[str, Any] = {
        "mode": "runtime_case_full_fidelity",
        "case": args.case,
        "solver_executed": False,
        "cfd_fields_modified": False,
    }

    try:
        runtime = FoamRuntime.detect()
        if args.distro:
            runtime.distro = args.distro
        if args.bashrc:
            runtime.bashrc = args.bashrc

        info = runtime.preflight()
        if not info["ok"]:
            s.fail(ev.PREFLIGHT, f"Runtime unavailable: {info.get('reason')}")
            save_json(out / "REANALYSIS_FULL.json", {**summary, "status": "NO_OPENFOAM"})
            return 1
        s.ok(
            ev.PREFLIGHT,
            f"OpenFOAM Foundation v{info['openfoam_version']} ready "
            f"({runtime.mode}, numpy {info['numpy']}).",
        )
        summary["runtime"] = info

        case = PurePosixPath(args.case)
        present = runtime.bash(
            f"test -d {shlex.quote(str(case))} && "
            f"test -f {shlex.quote(str(case))}/log.foamRun && "
            f"test -f {shlex.quote(str(case))}/spec.json && echo PRESENT",
            foam=False,
            timeout=120,
        )
        if "PRESENT" not in present.stdout:
            message = (
                f"The case is not present at {case}. A runtime cache is not "
                "permanent evidence; if it has been cleared, the fetched run "
                "directory is what remains and only the excerpt-scope "
                "reanalysis is possible."
            )
            s.fail(ev.ORCHESTRATOR, message)
            save_json(
                out / "REANALYSIS_FULL.json",
                {**summary, "status": "CASE_NOT_FOUND", "message": message},
            )
            return 1
        s.ok(ev.ORCHESTRATOR, f"Solved case found: {case}")

        before = _hash_case(runtime, case)
        summary["case_fingerprint_before"] = before

        # --- complete raw solver log --------------------------------------
        sizes = runtime.bash(
            f"wc -c < {shlex.quote(str(case))}/log.foamRun && "
            f"wc -l < {shlex.quote(str(case))}/log.foamRun",
            foam=False,
            timeout=300,
        )
        log_bytes, log_lines = (
            [int(v) for v in sizes.stdout.split()] if sizes.ok else [0, 0]
        )
        s.emit(
            ev.DIAGNOSTICS,
            f"Complete solver log: {log_bytes} bytes, {log_lines} lines.",
        )
        summary["solver_log"] = {"bytes": log_bytes, "lines": log_lines}

        logs = out / "logs"
        logs.mkdir(exist_ok=True)

        # Every warning and every error-shaped line, with context. This is the
        # part of a multi-megabyte log a reader actually needs, and it is small.
        extract = runtime.bash(
            f"grep -n -A 6 -E "
            f"'(Warning|WARNING|FOAM FATAL|error|Error|Segmentation|"
            f"core dumped|bounding|Bounding)' "
            f"{shlex.quote(str(case))}/log.foamRun || true",
            foam=False,
            timeout=600,
        )
        (logs / "log.foamRun.anomalies").write_text(
            extract.stdout or "", encoding="utf-8"
        )

        if 0 < log_bytes <= MAX_FULL_LOG_BYTES:
            fetched = runtime.fetch(case / "log.foamRun", logs / "log.foamRun")
            summary["solver_log"]["archived"] = (
                "complete" if fetched else "fetch_failed"
            )
        else:
            runtime.fetch_head(case / "log.foamRun", logs / "log.foamRun.head")
            runtime.fetch_tail(case / "log.foamRun", logs / "log.foamRun.tail")
            summary["solver_log"]["archived"] = "head_tail_and_anomalies"
        s.ok(
            ev.DIAGNOSTICS,
            f"Solver log archived ({summary['solver_log']['archived']}); "
            "anomaly extract written.",
        )

        # --- stage the CURRENT pipeline -----------------------------------
        stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
        root = runtime.make_root(f"{stamp}-forward-step-2d-reanalysis")
        code = root / "code"
        runtime.bash(
            f"mkdir -p {shlex.quote(str(code))}/pipeline/forward_step_2d "
            f"{shlex.quote(str(code))}/pipeline/forward_step/template",
            foam=False,
            timeout=120,
        )
        source = runtime.to_runtime_path(PIPELINE_DIR)
        template = runtime.to_runtime_path(TEMPLATE_DIR)
        target = code / "pipeline/forward_step_2d"
        template_target = code / "pipeline/forward_step/template"
        staged = runtime.bash(
            f"cp -- {shlex.quote(source)}/*.py {shlex.quote(source)}/*.sh "
            f"{shlex.quote(str(target))}/ && "
            f"cp -r -- {shlex.quote(template)}/* {shlex.quote(str(template_target))}/ && "
            f"sed -i 's/\\r$//' {shlex.quote(str(target))}/*.py && "
            f"ls {shlex.quote(str(target))}",
            foam=False,
            timeout=300,
        )
        if not staged.ok:
            s.fail(ev.ORCHESTRATOR, f"Staging failed: {staged.stderr}")
            save_json(out / "REANALYSIS_FULL.json", {**summary, "status": "STAGE_FAILED"})
            return 1
        s.ok(ev.ORCHESTRATOR, "Corrected deterministic pipeline staged into the runtime.")

        # --- reanalyse ----------------------------------------------------
        evidence = root / "evidence_full"
        s.emit(
            ev.DIAGNOSTICS,
            "Recomputing diagnostics from the native saved fields. "
            "The solver is not invoked.",
        )
        done = runtime.bash(
            f"cd {shlex.quote(str(code))} && "
            f"python3 -m pipeline.forward_step_2d.reanalyse "
            f"--case {shlex.quote(str(case))} --out {shlex.quote(str(evidence))}"
            + (f" --reference {shlex.quote(args.reference)}" if args.reference else ""),
            timeout=3600,
        )
        if not done.ok:
            s.fail(
                ev.DIAGNOSTICS,
                f"Reanalysis failed: {done.stdout[-2000:]}{done.stderr[-2000:]}",
            )
            save_json(
                out / "REANALYSIS_FULL.json",
                {**summary, "status": "REANALYSIS_FAILED", "stderr": done.stderr[-4000:]},
            )
            return 1

        for name in DATA_FILES:
            runtime.fetch(evidence / name, out / name)
        # The packed final fields are binary, so the text-mode fetch would
        # corrupt them. They are what a future reference comparison needs.
        if fetch_binary(runtime, evidence / "native_final.npz", out / "native_final.npz"):
            summary["native_fields_archived"] = True

        if not (out / "validation.json").exists():
            s.fail(ev.DIAGNOSTICS, "No validation document was produced.")
            save_json(out / "REANALYSIS_FULL.json", {**summary, "status": "NO_VALIDATION"})
            return 1

        diagnostics = json.loads((out / "diagnostics.json").read_text())
        validation = json.loads((out / "validation.json").read_text())
        index = (
            json.loads((out / "evidence_index.json").read_text())
            if (out / "evidence_index.json").exists()
            else {}
        )

        figures = out / "figures"
        figures.mkdir(exist_ok=True)
        archived: List[str] = []
        missing: List[str] = []
        for key in ARCHIVE_IMAGE_KEYS:
            remote = index.get("figures", {}).get(key)
            if not remote:
                missing.append(key)
                continue
            if fetch_binary(runtime, PurePosixPath(remote), figures / f"{key}.png"):
                archived.append(key)
            else:
                missing.append(key)
        summary["figures_archived"] = archived
        summary["figures_missing"] = missing
        s.emit(
            ev.DIAGNOSTICS,
            f"{len(archived)}/{len(ARCHIVE_IMAGE_KEYS)} figures archived."
            + (f" Missing: {', '.join(missing)}." if missing else ""),
        )

        after = _hash_case(runtime, case)
        summary["case_fingerprint_after"] = after
        summary["cfd_fields_modified"] = bool(before and after and before != after)
        if summary["cfd_fields_modified"]:
            s.fail(
                ev.ORCHESTRATOR,
                "The case fingerprint changed during reanalysis. The solved "
                "fields were expected to be read-only.",
            )
        else:
            s.ok(
                ev.ORCHESTRATOR,
                "Case fingerprint unchanged: the solved fields were read, not "
                "rewritten.",
            )

        summary["status"] = validation["status"]
        summary["failed_checks"] = validation["failed_checks"]
        summary["hard_checks"] = validation["hard_checks"]
        summary["shock_compression"] = validation["shock_compression"]
        summary["fatal_scan"] = validation["measured"]["fatal_scan"]["data"]
        summary["warnings"] = diagnostics.get("warnings", [])
        summary["solver_runs"] = diagnostics.get("solver_runs")

        s.emit(
            ev.SCIENTIFIC_VALIDATOR,
            f"Deterministic verdict: {validation['status']}"
            + (
                f" (failed: {', '.join(validation['failed_checks'])})"
                if validation["failed_checks"]
                else ""
            ),
            status="PASS" if not validation["failed_checks"] else "FAIL",
        )

    except FoamRuntimeError as exc:
        s.fail(ev.ORCHESTRATOR, f"Runtime error: {exc}")
        summary["status"] = "RUNTIME_ERROR"
        summary["message"] = str(exc)
    except Exception as exc:  # noqa: BLE001
        s.fail(ev.ORCHESTRATOR, f"Unhandled error: {exc}")
        summary["status"] = "ERROR"
        summary["message"] = str(exc)

    save_json(out / "REANALYSIS_FULL.json", summary)

    print()
    print("=" * 78)
    print(f"  {summary.get('status')}   evidence archived under {out}")
    print("=" * 78)
    if summary.get("warnings"):
        print()
        print("OpenFOAM warnings found in the complete solver log:")
        for warning in summary["warnings"]:
            print("  " + warning.replace("\n", "\n  "))
    return 0 if summary.get("status") == "PASS_2D_FORWARD_STEP" else 1


if __name__ == "__main__":
    raise SystemExit(main())
