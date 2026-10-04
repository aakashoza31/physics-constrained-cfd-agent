#!/usr/bin/env python3
"""Mandatory zero-CFD mesh audit for the airfoil family. NEVER launches the flow solver.

Not part of the CFD Forge paper; development tooling for the airfoil mesh
qualification.

    python scripts/audit_airfoil_mesh.py                       # Stage A only
    python scripts/audit_airfoil_mesh.py --with-openfoam       # Stage A + Stage B
    python scripts/audit_airfoil_mesh.py --grid mesh_canonical --with-openfoam \
        --out build/airfoil

Stage A runs here in pure Python. Stage B needs OpenFOAM Foundation v14 and runs
on the repository's existing FoamRuntime bridge: gmshToFoam, a deterministic
merge of the spanwise patches into one `frontAndBack` patch of type `empty`, then
checkMesh -allTopology -allGeometry with its report PARSED rather than trusted.

Without --with-openfoam the audit stays MESH_AUDIT_INCOMPLETE. With it, and with
Foundation v14 present, it can reach MESH_AUDIT_PASSED.

NO FLOW SOLVER IS EVER INVOKED. Stage B enforces a mesh-utility allow-list and
refuses any command naming foamRun, simpleFoam, incompressibleFluid or similar.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.families.airfoil.spec import GRID_DIMENSIONS  # noqa: E402
from src.pipeline.airfoil import assets as A  # noqa: E402
from src.pipeline.airfoil import mesh_audit  # noqa: E402
from src.pipeline.airfoil import stage_b as stage_b_mod  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--grid", choices=sorted(GRID_DIMENSIONS), default=None,
                    help="audit one grid; default is both")
    ap.add_argument("--out", default="build/airfoil",
                    help="directory for the converted mesh")
    ap.add_argument("--no-write", action="store_true",
                    help="audit without writing the converted mesh")
    ap.add_argument("--with-openfoam", action="store_true",
                    help="run Stage B (gmshToFoam / boundary rewrite / checkMesh) "
                         "on the FoamRuntime bridge. Mesh utilities only.")
    args = ap.parse_args()

    # Report the required assets BEFORE doing any long conversion work.
    audit = A.audit_assets()
    if not audit["all_required_ok"]:
        print("REQUIRED ASSETS ARE NOT IN ORDER -- no conversion attempted.\n",
              file=sys.stderr)
        for status in audit["statuses"]:
            if status["required"] and not status["ok"]:
                print(f"  - {status['filename']}: {status['reason']}", file=sys.stderr)
        print("\nRun: python scripts/airfoil_assets.py report", file=sys.stderr)
        print(json.dumps({"family": "airfoil", "cfd_launched": False,
                          "status": "ASSETS_NOT_REGISTERED",
                          "assets": audit}, indent=2))
        return 3

    out_dir = None if args.no_write else Path(args.out)

    runtime = None
    if args.with_openfoam:
        if args.no_write:
            print("refusing: Stage B needs the converted mesh on disk; drop "
                  "--no-write.", file=sys.stderr)
            return 3
        from src.pipeline.foam_runtime import FoamRuntime, FoamRuntimeError

        try:
            runtime = FoamRuntime.detect()
        except FoamRuntimeError as exc:
            print(f"refusing: no OpenFOAM runtime: {exc}", file=sys.stderr)
            return 3
        print(f"Stage B enabled: FoamRuntime mode={runtime.mode} "
              f"bashrc={runtime.bashrc}", file=sys.stderr)
        print(f"Stage B tools (mesh utilities only): "
              f"{', '.join(stage_b_mod.ALLOWED_TOOLS)}", file=sys.stderr)
        print("No flow solver is invoked.", file=sys.stderr)

    if args.grid:
        report = mesh_audit.audit_grid(
            args.grid, out_dir=out_dir, runtime=runtime
        ).to_dict()
        print(json.dumps(report, indent=2, default=str))
        return 0 if report["status"] == "MESH_AUDIT_PASSED" else 1

    result = mesh_audit.audit_all(out_dir=out_dir, runtime=runtime)
    print(json.dumps(result, indent=2, default=str))
    return 0 if result["all_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
