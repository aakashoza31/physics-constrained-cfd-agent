#!/usr/bin/env python3
"""Execution wrapper for Family 3. Refuses to run unless the gates are closed.

The wrapper never runs CFD on its own: `execute` demands an explicit
`allow_cfd=True` AND a passing mesh audit AND registered assets. Without those
it raises, which is the behaviour every test in this family relies on.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from src.pipeline.airfoil import assets as asset_mod

#: The OpenFOAM stages, in order. Stage 1-2 are mesh utilities; only stage 4 is CFD.
STAGES = (
    "gmshToFoam <converted>.msh",
    "boundary rewrite: front/back -> empty (frontAndBack)",
    "checkMesh -allTopology -allGeometry",
    "foamRun -solver incompressibleFluid",
)

MESH_STAGES = STAGES[:3]
SOLVER_STAGE = STAGES[3]


class ExecutionRefused(RuntimeError):
    """A precondition for running this family was not satisfied."""


def preconditions(
    case: Path,
    *,
    mesh_audit_status: Optional[str] = None,
    repo_root: Optional[Path] = None,
) -> Dict[str, Any]:
    """Everything that must hold before the solver may be invoked."""
    case = Path(case)
    audit = asset_mod.audit_assets(repo_root)
    checks = {
        "case_exists": case.exists(),
        "converted_mesh_present": any(case.glob("*.msh")),
        "registered_assets_ok": bool(audit["all_required_ok"]),
        "mesh_audit_passed": mesh_audit_status == "MESH_AUDIT_PASSED",
    }
    return {
        "checks": checks,
        "failed": [k for k, v in checks.items() if not v],
        "ready": all(checks.values()),
        "assets": audit,
    }


def execute(
    case: Path,
    *,
    allow_cfd: bool = False,
    mesh_audit_status: Optional[str] = None,
    repo_root: Optional[Path] = None,
    runner: Optional[Callable[[List[str]], int]] = None,
) -> Dict[str, Any]:
    """Run the OpenFOAM stages. Raises unless explicitly permitted and ready."""
    state = preconditions(case, mesh_audit_status=mesh_audit_status,
                          repo_root=repo_root)
    if not allow_cfd:
        raise ExecutionRefused(
            "airfoil: refusing to run. `allow_cfd=True` must be passed explicitly; "
            "this family never launches a solve as a side effect of collection, "
            "validation or an audit."
        )
    if not state["ready"]:
        raise ExecutionRefused(
            "airfoil: preconditions not satisfied: " + ", ".join(state["failed"])
        )
    if runner is None:
        raise ExecutionRefused(
            "airfoil: no OpenFOAM runner supplied. Execution is delegated to the "
            "runtime; this module does not spawn processes itself."
        )
    results = []
    for stage in STAGES:
        code = runner(stage.split())
        results.append({"stage": stage, "returncode": code})
        if code != 0:
            break
    return {
        "case": str(case),
        "stages": results,
        "completed": all(r["returncode"] == 0 for r in results)
        and len(results) == len(STAGES),
        "preconditions": state,
    }
