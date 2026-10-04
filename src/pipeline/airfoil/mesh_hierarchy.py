#!/usr/bin/env python3
"""Where the airfoil mesh hierarchy's reports live, and what they say.

Not part of the CFD Forge paper (the airfoil family is planned; no CFD was run).

This module is the single deterministic answer to "has the frozen coarse /
medium / fine hierarchy been generated and qualified?". It reads the reports
that ``scripts/qualify_family2_meshes.py`` writes; it never generates, never
qualifies and never edits a report.

Two rules it exists to enforce:

  * the readiness gate is computed FROM the reports, so it cannot be closed by
    hand-editing a readiness file;
  * the cell count of a level is MEASURED from its report, never declared. The
    frozen recipe carries a planning forecast only.

It deliberately imports nothing from ``src.families`` so that the family spec
may depend on it.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

#: The ACTIVE canonical mesh path: the NASA TMR Family II hierarchy. The custom
#: Gmsh generator's v1 and v2 runs are archived under .../v1 and .../v2, their
#: reports are preserved unchanged, and they gate nothing.
ACTIVE_RECIPE_VERSION = "nasa_familyII"

#: Report layout, relative to the repository root. Versioned, so an archived
#: report can never be mistaken for an active one and none is overwritten.
REPORT_ROOT = Path("outputs") / "airfoil_mesh" / ACTIVE_RECIPE_VERSION
ARCHIVED_ROOTS = (Path("outputs") / "airfoil_mesh" / "v1",
                  Path("outputs") / "airfoil_mesh" / "v2")
QUALIFICATION_NAME = "qualification.json"
GENERATION_NAME = "generation.json"
SUMMARY_NAME = "hierarchy.json"
MESH_NAME = "mesh.msh"
CHECK_MESH_LOG_NAME = "checkMesh.log"

#: Copied from the checker so a caller need not import it to read a verdict.
QUALIFIED = "F3_MESH_QUALIFIED"

LEVELS = ("coarse", "medium", "fine")

_CACHE: Dict[Any, Any] = {}


def _repo_root(repo_root: Optional[Path] = None) -> Path:
    if repo_root is not None:
        return Path(repo_root)
    return Path(__file__).resolve().parents[3]


def report_root(repo_root: Optional[Path] = None) -> Path:
    return _repo_root(repo_root) / REPORT_ROOT


def level_dir(level: str, repo_root: Optional[Path] = None) -> Path:
    return report_root(repo_root) / str(level)


def qualification_path(level: str, repo_root: Optional[Path] = None) -> Path:
    return level_dir(level, repo_root) / QUALIFICATION_NAME


def generation_path(level: str, repo_root: Optional[Path] = None) -> Path:
    return level_dir(level, repo_root) / GENERATION_NAME


def summary_path(repo_root: Optional[Path] = None) -> Path:
    return report_root(repo_root) / SUMMARY_NAME


def _read_json(path: Path) -> Optional[Dict[str, Any]]:
    """Read a report, cached on (path, mtime_ns, size). Never raises."""
    try:
        stat = path.stat()
    except OSError:
        return None
    key = (str(path), stat.st_mtime_ns, stat.st_size)
    if key in _CACHE:
        return _CACHE[key]
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    _CACHE[key] = data
    return data


def read_level_report(level: str,
                      repo_root: Optional[Path] = None) -> Optional[Dict[str, Any]]:
    return _read_json(qualification_path(level, repo_root))


def hierarchy_state(repo_root: Optional[Path] = None) -> Dict[str, Any]:
    """Deterministic state of the three levels, read from their reports."""
    levels: Dict[str, Dict[str, Any]] = {}
    measured: Dict[str, Optional[int]] = {}
    qualified: List[str] = []
    missing: List[str] = []
    not_qualified: List[str] = []

    for name in LEVELS:
        report = read_level_report(name, repo_root)
        if report is None:
            levels[name] = {"present": False, "verdict": None}
            measured[name] = None
            missing.append(name)
            continue
        verdict = report.get("qualification_verdict")
        generation = report.get("generation") or {}
        cells = generation.get("cells")
        cells = int(cells) if isinstance(cells, int) else None
        levels[name] = {
            "present": True,
            "verdict": verdict,
            "failed": list(report.get("failed") or []),
            "unresolved": list(report.get("unresolved") or []),
            "cells": cells,
            "mesh_sha256": generation.get("mesh_sha256"),
            "report": str(qualification_path(name, repo_root)),
        }
        measured[name] = cells
        (qualified if verdict == QUALIFIED else not_qualified).append(name)

    return {
        "report_root": str(report_root(repo_root)),
        "levels": levels,
        "measured_cells": measured,
        "qualified_levels": qualified,
        "missing_levels": missing,
        "not_qualified_levels": not_qualified,
        "all_qualified": not missing and not not_qualified,
        "note": ("computed from the per-level qualification reports; a readiness "
                 "file cannot close this gate"),
    }
