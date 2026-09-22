#!/usr/bin/env python3
"""Runtime-side evidence collection for one 2D forward-step run.

Runs inside the OpenFOAM runtime (WSL), where the native case lives. Produces:

    <out>/diagnostics.json          measured transient evidence
    <out>/validation.json           deterministic disposition
    <out>/figures/*.png             native-field images
    <out>/stored_totals.csv
    <out>/transient_mass.csv
    <out>/shock_front_history.csv
    <out>/native_final.npz
    <out>/evidence_index.json       what was produced, and what failed

Figures are best-effort: if matplotlib is unavailable in the runtime the run is
still diagnosed and validated, and the index records that images are missing.
Numerical evidence is never best-effort.

Usage:
    python3 -m pipeline.forward_step_2d.collect_evidence <case> <out> [--reference REF.npz]
"""
from __future__ import annotations

import argparse
import json
import sys
import traceback
from pathlib import Path

from .diagnostics import diagnose
from .spec import ForwardStep2DSpec
from .validate import validate


def collect(case: Path, out: Path, reference=None) -> dict:
    case = Path(case)
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)

    spec = ForwardStep2DSpec.load(case / "spec.json")
    diagnostics, layout, data = diagnose(case, out, spec=spec, reference=reference)
    validation = validate(diagnostics)
    (out / "validation.json").write_text(json.dumps(validation, indent=2))

    index = {
        "case": str(case),
        "output": str(out),
        "status": validation["status"],
        "failed_checks": validation["failed_checks"],
        "final_time": diagnostics["final_time"],
        "reached_requested_end_time": diagnostics["reached_requested_end_time"],
        "cells": diagnostics["cells"],
        "figures": {},
        "figure_error": None,
        "data_files": sorted(
            str(p.relative_to(out))
            for p in out.rglob("*")
            if p.is_file() and p.suffix in {".csv", ".npz", ".json"}
        ),
    }

    try:
        from .plots import make_plots

        index["figures"] = make_plots(case, out, spec, layout, data)
    except Exception as exc:  # noqa: BLE001 - figures must not sink the run
        index["figure_error"] = f"{type(exc).__name__}: {exc}"
        index["figure_traceback"] = traceback.format_exc()[-1500:]

    (out / "evidence_index.json").write_text(json.dumps(index, indent=2))
    print(json.dumps({k: v for k, v in index.items() if k != "figure_traceback"}, indent=2))
    return index


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("case", type=Path)
    ap.add_argument("out", type=Path)
    ap.add_argument("--reference", default=None)
    args = ap.parse_args()

    index = collect(args.case, args.out, args.reference)
    return 0 if index["status"] != "FAIL" else 1


if __name__ == "__main__":
    sys.exit(main())
