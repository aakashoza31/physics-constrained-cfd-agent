#!/usr/bin/env python3
"""Live execution: the only path that launches OpenFOAM.

This wrapper does NOT reimplement a family's build, solve or validation. Those
live in the registered family runners -- `scripts/run_nozzle_e2e.py` and
`scripts/run_forward_step_2d.py` -- which own the sequence that produced every
accepted result in this repository. Live mode dispatches to them, waits, and
then ingests the evidence they wrote back into the unified

    evidence -> diagnosis -> deterministic authority -> bounded correction -> report

pipeline, so a live run and a replay reach their verdict through the same gates.

Three refusals come before any process starts:

  1. the caller must pass an explicit CFD opt-in;
  2. the family must be ACCEPTED and therefore routable -- cube and airfoil are
     evidence-only and can never be executed here;
  3. OpenFOAM Foundation v14 must be reachable through the existing FoamRuntime.

`solver_invoked` becomes true only when a runner process was actually launched.
A refusal, a missing runtime or a dispatch error all leave it false.
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from src.families import capabilities as caps

LIVE_VERSION = "live-orchestration/1.0.0"

_ROOT = Path(__file__).resolve().parents[2]

#: family -> (runner script, how to name the request, how to name the output dir)
RUNNERS: Dict[str, Dict[str, str]] = {
    "nozzle": {"script": "scripts/run_nozzle_e2e.py",
               "prompt_flag": "--prompt", "out_flag": "--out"},
    "forward_step_2d": {"script": "scripts/run_forward_step_2d.py",
                        "prompt_flag": "--request", "out_flag": "--out"},
}

#: Evidence files a runner writes, in the order we prefer to read them.
EVIDENCE_FILES = ("agent_result.json", "acceptance.json", "case_result.json",
                  "validation.json")


@dataclass
class LiveOutcome:
    reason: str
    artifacts: Dict[str, Any] = field(default_factory=dict)
    stages: List[Tuple[str, str, Dict[str, Any]]] = field(default_factory=list)
    gates: List[Dict[str, Any]] = field(default_factory=list)
    proposals: List[Dict[str, Any]] = field(default_factory=list)


def runtime_status() -> Dict[str, Any]:
    """Is Foundation v14 reachable? Reported, never assumed."""
    try:
        from src.pipeline.foam_runtime import FoamRuntime
    except Exception as exc:                 # noqa: BLE001 - reported
        return {"available": False, "reason": f"FoamRuntime unavailable: {exc}"}
    try:
        runtime = FoamRuntime.detect()
        pre = runtime.preflight()
    except Exception as exc:                 # noqa: BLE001 - reported
        return {"available": False, "reason": f"{type(exc).__name__}: {exc}"}
    return {
        "available": bool(pre.get("ok")),
        "openfoam_version": pre.get("openfoam_version"),
        "missing_tools": pre.get("missing_tools", []),
        "reason": pre.get("reason", ""),
    }


def build_command(family: str, prompt: str, out_dir: Path,
                  extra: Optional[Sequence[str]] = None) -> List[str]:
    """The exact runner invocation. Exposed so tests can assert on it."""
    spec = RUNNERS[family]
    command = [sys.executable, str(_ROOT / spec["script"]),
               spec["prompt_flag"], prompt,
               spec["out_flag"], str(out_dir)]
    command.extend(extra or [])
    return command


def _find_evidence(out_dir: Path) -> Dict[str, Any]:
    """Read whatever decision record the runner wrote. Never invents one."""
    found: Dict[str, Any] = {}
    for name in EVIDENCE_FILES:
        for path in sorted(out_dir.rglob(name)):
            try:
                found[str(path.relative_to(out_dir))] = json.loads(
                    path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
    return found


def _gates_from_runner_evidence(evidence: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Translate a runner's own deterministic record into pipeline gates.

    The runner already applied the family's registered checks; this re-states
    them as gates so a live run and a replay are judged through one trace. It
    does not re-decide anything and it cannot soften a failure: an absent record
    becomes an UNRESOLVED gate, never a pass.
    """
    def gate(question: str, passed: Optional[bool], measured: Any = None,
             threshold: Any = None, detail: str = "") -> Dict[str, Any]:
        return {"question": question, "passed": passed, "measured": measured,
                "threshold": threshold, "detail": detail}

    if not evidence:
        return [gate("numerical_health", None, measured="no runner evidence found",
                     threshold="the runner must write a decision record",
                     detail=("the solver ran but no decision record was found; "
                             "the result is unresolved, not accepted"))]

    record: Dict[str, Any] = {}
    for name in EVIDENCE_FILES:
        for key, value in evidence.items():
            if key.endswith(name):
                record = value
                break
        if record:
            break

    accepted = record.get("accepted")
    status = record.get("status") or record.get("deterministic_status")
    failed = record.get("failed_checks") or []
    if accepted is None:
        accepted = status in ("ACCEPTED", "PASS_SINGLE_MESH",
                              "PASS_2D_FORWARD_STEP")
    return [
        gate("numerical_health", status is not None,
             measured={"runner_status": status},
             threshold="the runner must complete and record a status"),
        gate("conservation", not any("mass" in f or "flux" in f for f in failed),
             measured={"failed_checks": failed},
             threshold="the family's registered conservation criterion"),
        gate("convergence", bool(accepted) or not failed,
             measured={"runner_status": status},
             threshold="the family's registered convergence criterion"),
        gate("validation", bool(accepted),
             measured={"runner_status": status, "failed_checks": failed},
             threshold="every registered validation check must pass",
             detail=record.get("message", "") or ""),
    ]


def run_case(family: str, case: Optional[str], *, run: Any = None,
             prompt: Optional[str] = None, out_dir: Optional[Path] = None,
             extra_args: Optional[Sequence[str]] = None,
             timeout: float = 14400.0,
             dispatch=subprocess.run) -> LiveOutcome:
    """Execute a registered case through its registered family runner.

    ``dispatch`` is injectable so integration tests can prove the dispatch and
    the evidence handoff without launching a solver.
    """
    canonical = caps.resolve(family)
    capability = caps.TABLE.get(canonical)
    if capability is None or not capability.routable:
        status = capability.status if capability else "UNREGISTERED"
        if run is not None:
            run.stage("execution", "REFUSED", family=canonical, family_status=status)
        return LiveOutcome(
            reason=(f"{canonical} has status {status} and may not be executed for "
                    "acceptance. Its archived evidence is replayable."),
            artifacts={"solver_invoked": False, "family_status": status})

    if canonical not in RUNNERS:
        if run is not None:
            run.stage("execution", "REFUSED", family=canonical)
        return LiveOutcome(
            reason=f"no live runner is registered for {canonical}",
            artifacts={"solver_invoked": False})

    state = runtime_status()
    if not state["available"]:
        if run is not None:
            run.stage("execution", "REFUSED", runtime=state)
        return LiveOutcome(
            reason=("OpenFOAM Foundation v14 is not reachable, so no live run "
                    f"was attempted: {state.get('reason')}"),
            artifacts={"solver_invoked": False, "runtime": state})

    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    out = Path(out_dir) if out_dir else (
        _ROOT / "runs" / f"live_{stamp}_{canonical}_{case or 'case'}")
    out.mkdir(parents=True, exist_ok=True)
    text = prompt or _prompt_for(canonical, case)
    command = build_command(canonical, text, out, extra_args)

    if run is not None:
        run.stage("case_and_mesh", "OK", owner=RUNNERS[canonical]["script"],
                  note="the family runner owns build and meshing")
    started = time.time()
    try:
        completed = dispatch(command, cwd=str(_ROOT), capture_output=True,
                             text=True, timeout=timeout)
        returncode = getattr(completed, "returncode", 1)
        launched = True
    except Exception as exc:                  # noqa: BLE001 - reported
        if run is not None:
            run.stage("execution", "FAILED", error=f"{type(exc).__name__}: {exc}")
        return LiveOutcome(
            reason=f"the family runner could not be launched: {exc}",
            artifacts={"solver_invoked": False, "command": command})
    elapsed = time.time() - started

    evidence = _find_evidence(out)
    gates = _gates_from_runner_evidence(evidence)
    artifacts = {
        "solver_invoked": launched,
        "live_version": LIVE_VERSION,
        "runner": RUNNERS[canonical]["script"],
        "command": command,
        "returncode": returncode,
        "runtime": state,
        "elapsed_seconds": round(elapsed, 3),
        "evidence_root": str(out),
        "runner_evidence": sorted(evidence),
        "stdout_tail": (getattr(completed, "stdout", "") or "")[-4000:],
        "stderr_tail": (getattr(completed, "stderr", "") or "")[-2000:],
    }
    # The reporting stage needs the raw runtime case, not just compact JSON evidence.
    # This carries a location only; it cannot change any authority gate.
    for record in evidence.values():
        if isinstance(record, dict) and isinstance(record.get("runtime_case"), str):
            artifacts["raw_case"] = record["runtime_case"]
            break
    stages = [
        ("execution", "EXECUTED" if returncode == 0 else "RUNNER_FAILED",
         {"solver_invoked": True, "returncode": returncode,
          "runner": RUNNERS[canonical]["script"]}),
        ("evidence_extraction", "OK" if evidence else "NO_EVIDENCE",
         {"files": sorted(evidence)}),
        ("llm_diagnosis", "OWNED_BY_RUNNER",
         {"proposals": 0,
          "note": ("the family runner makes and records its own model calls; "
                   "this wrapper makes none")}),
        ("bounded_correction", "OWNED_BY_RUNNER",
         {"note": ("the family runner owns its own bounded correction loop; "
                   "this wrapper does not issue a second one")}),
    ]
    if run is not None:
        for name, status_, detail in stages:
            run.stage(name, status_, **detail)
    reason = (
        f"live run of {canonical}/{case or 'case'} through "
        f"{RUNNERS[canonical]['script']}: runner exit {returncode}, "
        f"{len(evidence)} evidence record(s) ingested, "
        f"{elapsed:.1f}s. The verdict below comes from the deterministic gates "
        "over that evidence.")
    return LiveOutcome(reason=reason, artifacts=artifacts, stages=stages,
                       gates=gates)


def _prompt_for(family: str, case: Optional[str]) -> str:
    """The request a registered case stands for, read from its case.yaml."""
    if not case:
        return f"run the canonical {family} case"
    path = _ROOT / "cases" / family / case / "case.yaml"
    if not path.exists():
        for alias, canonical in caps.ALIASES.items():
            if canonical == family:
                candidate = _ROOT / "cases" / alias / case / "case.yaml"
                if candidate.exists():
                    path = candidate
                    break
    if path.exists():
        try:
            import yaml
            meta = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            title = meta.get("title")
            if title:
                return str(title)
        except Exception:                      # noqa: BLE001
            pass
    return f"run the registered {family} case {case}"
