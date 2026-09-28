#!/usr/bin/env python3
"""Live execution: the only path that launches OpenFOAM.

Live mode is deliberately narrow. It refuses unless three things hold:

  1. the caller passed an explicit CFD opt-in;
  2. the family is ACCEPTED and therefore routable;
  3. OpenFOAM Foundation v14 is actually reachable through the existing
     FoamRuntime bridge.

If any fails, the run stops with a reason and `solver_invoked: false`. There is
no fallback that quietly replays archived evidence and calls it a live run.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from src.families import capabilities as caps


@dataclass
class LiveOutcome:
    reason: str
    artifacts: Dict[str, Any] = field(default_factory=dict)
    stages: List[Tuple[str, str, Dict[str, Any]]] = field(default_factory=list)


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


def run_case(family: str, case: Optional[str], *, run: Any = None) -> LiveOutcome:
    """Execute a registered case. Refuses cleanly when it cannot."""
    capability = caps.TABLE.get(family)
    if capability is None or not capability.routable:
        status = capability.status if capability else "UNREGISTERED"
        if run is not None:
            run.stage("execution", "REFUSED", family=family, status=status)
        return LiveOutcome(
            reason=(f"{family} has status {status} and may not be executed for "
                    "acceptance. Its archived evidence is replayable."),
            artifacts={"solver_invoked": False, "family_status": status})

    state = runtime_status()
    if not state["available"]:
        if run is not None:
            run.stage("execution", "REFUSED", runtime=state)
        return LiveOutcome(
            reason=("OpenFOAM Foundation v14 is not reachable, so no live run "
                    f"was attempted: {state.get('reason')}"),
            artifacts={"solver_invoked": False, "runtime": state})

    # The family runners remain the execution path; this wrapper does not
    # reimplement them.
    runner = {
        "nozzle": "scripts/run_nozzle_e2e.py",
        "forward_step_2d": "scripts/run_forward_step_2d.py",
    }.get(family)
    if run is not None:
        run.stage("execution", "HANDOFF", runner=runner, runtime=state)
    return LiveOutcome(
        reason=(f"live execution for {family} runs through {runner}, which owns "
                "the validated build/execute/analyse sequence for this family. "
                "Invoke it directly to execute; this wrapper does not duplicate "
                "its logic."),
        artifacts={"solver_invoked": False, "runtime": state, "runner": runner})
