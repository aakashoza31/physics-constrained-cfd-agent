#!/usr/bin/env python3
"""Convert and qualify the NASA TMR Family II F3 mesh hierarchy. NO CFD, EVER.

    python scripts/qualify_family2_meshes.py
    python scripts/qualify_family2_meshes.py --with-openfoam
    python scripts/qualify_family2_meshes.py --levels coarse --with-openfoam

Per level (coarse = n0012familyII.6, medium = .5, fine = .4):

  1. reads NASA's unstructured hexahedral CGNS through the existing reader;
  2. preserves the in-plane coordinates and connectivity EXACTLY, changing only
     the spanwise separation to b = 0.01 c with one spanwise cell;
  3. assigns airfoil -> wall, farfield -> patch, frontAndBack -> empty, and keeps
     the joined C-grid wake as internal connectivity;
  4. cross-checks the conversion and NASA's surface against the frozen corrected
     TMR sharp-trailing-edge formula;
  5. with --with-openfoam, runs gmshToFoam and
     `checkMesh -allTopology -allGeometry` through the existing FoamRuntime
     bridge -- mesh utilities only, enforced by the stage_b allow-list -- and
     preserves the raw report verbatim;
  6. issues the deterministic qualification against the FROZEN gates.

The NASA grid is never regenerated, smoothed, projected, optimised or remeshed,
and NASA provenance never waives a failing gate.

Exit codes
  0  every requested level qualifies
  2  a registered Family II asset is missing or its digest is unregistered
  3  at least one level is NOT qualified or is INCONCLUSIVE
  4  h5py is unavailable, so the CGNS authority cannot be read
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, Optional

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.pipeline.airfoil import assets as A            # noqa: E402
from src.pipeline.airfoil import cgns                   # noqa: E402
from src.pipeline.airfoil import family2 as F2          # noqa: E402
from src.pipeline.airfoil import gmsh_pipeline as GP    # noqa: E402
from src.pipeline.airfoil import mesh_checks as MC      # noqa: E402
from src.pipeline.airfoil import mesh_hierarchy as MH   # noqa: E402
from src.pipeline.airfoil import stage_b as SB          # noqa: E402

CLI_VERSION = "f3-familyII-cli/1.0.0"


def _write_json(path: Path, payload: Dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def _stage_b(mesh_file: Path, converted: F2.Converted, level_dir: Path,
             timeout: float) -> Dict[str, Any]:
    from src.pipeline.foam_runtime import FoamRuntime

    try:
        runtime = FoamRuntime.detect()
    except Exception as exc:                       # noqa: BLE001 - reported
        return {"status": "STAGE_B_RUNTIME_UNAVAILABLE", "ok": False,
                "error": f"{type(exc).__name__}: {exc}", "solver_invoked": False}
    out = SB.run_stage_b(
        mesh_file, runtime=runtime, expected_cells=converted.cells,
        expected_patch_faces={k: len(v) for k, v in converted.mesh["patches"].items()},
        timeout=timeout,
    )
    log = []
    for command in out.get("commands", []):
        log.append(f"### {command.get('label')} (rc={command.get('returncode')})")
        log.append(command.get("stdout_tail") or "")
        if command.get("stderr_tail"):
            log.append("--- stderr ---")
            log.append(command["stderr_tail"])
    (level_dir / MH.CHECK_MESH_LOG_NAME).write_text("\n".join(log) + "\n",
                                                    encoding="utf-8")
    return out


def run_level(level: str, root: Path, *, repo_root: Optional[Path],
              with_openfoam: bool, timeout: float,
              concavity_sample: Optional[int]) -> Dict[str, Any]:
    key = A.FAMILY2_LEVEL_KEYS[level]
    status = A.check_asset(key, repo_root)
    if not status["ok"]:
        return {"level": level, "asset_status": status,
                "qualification_verdict": MC.INCONCLUSIVE,
                "failed": [], "unresolved": ["registered_asset"],
                "note": "the registered Family II asset is not in order; nothing "
                        "is substituted"}

    level_dir = root / level
    level_dir.mkdir(parents=True, exist_ok=True)

    t0 = time.time()
    converted = F2.convert(level, Path(status["path"]))
    convert_seconds = time.time() - t0

    mesh_file = level_dir / f"n0012_familyII_{level}.msh"
    GP.write_gmsh_3d(converted.mesh, mesh_file)

    conversion = converted.to_dict()
    conversion["asset_status"] = status
    conversion["mesh_file"] = str(mesh_file)
    conversion["convert_seconds"] = round(convert_seconds, 3)
    conversion["cli_version"] = CLI_VERSION
    _write_json(level_dir / MH.GENERATION_NAME, conversion)

    raw: Dict[str, Any] = {}
    if with_openfoam:
        raw = _stage_b(mesh_file, converted, level_dir, timeout)

    t1 = time.time()
    report = MC.qualify_family2(
        converted.mesh, level_name=level,
        geometry_check=converted.geometry_check,
        conversion_check=converted.conversion_check,
        span=F2.REQUIRED_SPAN, raw_check_mesh=raw,
        concavity_sample=concavity_sample,
    )
    payload = report.to_dict()
    payload["generation"] = conversion
    payload["qualification_seconds"] = round(time.time() - t1, 3)
    payload["openfoam_stage_b_requested"] = bool(with_openfoam)
    payload["cli_version"] = CLI_VERSION
    _write_json(level_dir / MH.QUALIFICATION_NAME, payload)
    return payload


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--levels", nargs="+", default=list(F2.LEVELS),
                    choices=list(F2.LEVELS))
    ap.add_argument("--out", default=None, help=f"default: {MH.REPORT_ROOT}")
    ap.add_argument("--repo-root", default=None)
    ap.add_argument("--with-openfoam", action="store_true",
                    help="also run gmshToFoam and checkMesh -allTopology "
                         "-allGeometry through the existing FoamRuntime bridge")
    ap.add_argument("--concavity-sample", type=int, default=None)
    ap.add_argument("--timeout", type=float, default=3600.0)
    args = ap.parse_args()

    dependency = cgns.dependency_status()
    if not dependency.get("available"):
        print("REQUIRED DEPENDENCY MISSING: h5py", file=sys.stderr)
        print(f"  install : {cgns.INSTALL_HINT}", file=sys.stderr)
        print("No partial CGNS parser is substituted.", file=sys.stderr)
        return 4

    repo_root = Path(args.repo_root) if args.repo_root else None
    root = Path(args.out) if args.out else MH.report_root(repo_root)

    reports: Dict[str, Dict[str, Any]] = {}
    missing_assets = []
    for level in args.levels:
        print(f"[{level}] converting {A.REGISTER[A.FAMILY2_LEVEL_KEYS[level]].filename} ...",
              flush=True)
        payload = run_level(level, root, repo_root=repo_root,
                            with_openfoam=args.with_openfoam,
                            timeout=args.timeout,
                            concavity_sample=args.concavity_sample)
        reports[level] = payload
        if payload.get("unresolved") == ["registered_asset"]:
            missing_assets.append(level)
            print(f"[{level}] registered asset not in order: "
                  f"{payload['asset_status']['reason']}", file=sys.stderr)
            continue
        gen = payload["generation"]
        print(f"[{level}] {gen['cells']} cells, {gen['points']} points, "
              f"patches {gen['patch_faces']} -> {payload['qualification_verdict']}",
              flush=True)
        if payload["failed"]:
            print(f"[{level}] failed: {payload['failed']}", flush=True)
        if payload["unresolved"]:
            print(f"[{level}] unresolved: {payload['unresolved']}", flush=True)

    summary = {
        "cli_version": CLI_VERSION,
        "generated_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "recipe_version": MH.ACTIVE_RECIPE_VERSION,
        "authority": ("NASA TMR NACA0012 Numerical Analysis Family II, "
                      "unstructured hexahedral CGNS"),
        "archived_paths": [str(r) for r in MH.ARCHIVED_ROOTS],
        "required_span": F2.REQUIRED_SPAN,
        "levels": {
            level: {
                "qualification_verdict": p["qualification_verdict"],
                "failed": p["failed"],
                "unresolved": p["unresolved"],
                "asset": A.REGISTER[A.FAMILY2_LEVEL_KEYS[level]].filename,
                "structured_dimensions": list(F2.DIMENSIONS[level]),
                "expected_cells": F2.CELLS[level],
                "cells": p.get("generation", {}).get("cells"),
                "points": p.get("generation", {}).get("points"),
                "patch_faces": p.get("generation", {}).get("patch_faces"),
            }
            for level, p in reports.items()
        },
        "thresholds": {
            "max_non_orthogonality_deg": MC.MAX_NON_ORTHOGONALITY_DEG,
            "max_skewness": MC.MAX_SKEWNESS,
            "min_interpolation_weight": MC.MIN_INTERPOLATION_WEIGHT,
            "min_face_volume_ratio": MC.MIN_FACE_VOLUME_RATIO,
            "max_in_plane_stretching": MC.MAX_IN_PLANE_STRETCHING,
        },
        "all_requested_qualified": bool(reports) and all(
            p["qualification_verdict"] == MC.PASSED for p in reports.values()
        ),
        "openfoam_check_mesh_run": bool(args.with_openfoam),
        "cfd_launched": False,
        "solver_invoked": False,
    }
    _write_json(root / MH.SUMMARY_NAME, summary)
    print(f"\nhierarchy summary: {root / MH.SUMMARY_NAME}")

    if missing_assets:
        print(f"MISSING REGISTERED ASSETS for {missing_assets}: install them with "
              "scripts/airfoil_assets.py and re-run. Nothing was substituted.",
              file=sys.stderr)
        return 2
    if not summary["all_requested_qualified"]:
        print("HIERARCHY NOT QUALIFIED -- stopping before CFD. NASA provenance "
              "does not waive a failing gate.", file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
