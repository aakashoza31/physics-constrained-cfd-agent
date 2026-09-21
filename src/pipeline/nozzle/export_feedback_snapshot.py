#!/usr/bin/env python3
"""Export a compact, theory-blind CFD snapshot for feedback reasoning.

Reads the actual OpenFOAM cell-centre fields at the latest saved time and writes
CSV/JSON artifacts that the host can visualize without depending on ParaView or
PyVista.  No analytical target values are computed or exposed here.
"""
from __future__ import annotations

import argparse
import json
import math
import re
from pathlib import Path

import numpy as np

try:
    from .foamio import field
except ImportError:
    from foamio import field


def latest_time_dir(case: Path) -> tuple[float, Path]:
    choices = []
    for item in case.iterdir():
        if not item.is_dir() or not re.fullmatch(r"[0-9.eE+-]+", item.name):
            continue
        try:
            value = float(item.name)
        except ValueError:
            continue
        if value > 0 and all((item / name).exists() for name in ("p", "T", "rho", "U")):
            choices.append((value, item))
    if not choices:
        raise ValueError("No positive saved field state found")
    return max(choices, key=lambda pair: pair[0])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("case", type=Path)
    args = ap.parse_args()
    case = args.case

    coords = field(case / "0/C")
    n = len(coords)
    time_value, folder = latest_time_dir(case)
    p = field(folder / "p", count=n)
    T = field(folder / "T", count=n)
    rho = field(folder / "rho", count=n)
    U = field(folder / "U", count=n, vector=True)

    speed = np.linalg.norm(U, axis=1)
    mach = speed / np.sqrt(1.4 * 287.0 * T)
    radius = np.sqrt(coords[:, 1] ** 2 + coords[:, 2] ** 2)

    data = np.column_stack(
        [coords[:, 0], radius, p, T, rho, U[:, 0], U[:, 1], U[:, 2], speed, mach]
    )
    out_csv = case / "feedback_snapshot.csv"
    np.savetxt(
        out_csv,
        data,
        delimiter=",",
        header="x_m,r_m,p_Pa,T_K,rho_kg_m3,Ux_m_s,Uy_m_s,Uz_m_s,speed_m_s,Mach",
        comments="",
    )

    payload = {
        "latest_time_s": float(time_value),
        "cells": int(n),
        "ranges": {
            "p_Pa": [float(np.min(p)), float(np.max(p))],
            "T_K": [float(np.min(T)), float(np.max(T))],
            "rho_kg_m3": [float(np.min(rho)), float(np.max(rho))],
            "speed_m_s": [float(np.min(speed)), float(np.max(speed))],
            "Mach": [float(np.min(mach)), float(np.max(mach))],
        },
        "finite": bool(np.isfinite(data).all()),
        "positive_thermodynamics": bool((p > 0).all() and (T > 0).all() and (rho > 0).all()),
        "source": "latest native OpenFOAM cell-centre fields",
        "theory_blind": True,
    }
    (case / "feedback_snapshot.json").write_text(json.dumps(payload, indent=2))
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
