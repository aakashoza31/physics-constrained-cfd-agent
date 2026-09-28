#!/usr/bin/env python3
"""ParaView batch script: field contours from an OpenFOAM case.

Run with a ParaView interpreter, never with plain python:

    pvpython src/reporting/paraview_contours.py --case <case> --out <dir>

It renders whichever of pressure, velocity magnitude, Mach number, temperature
and turbulence quantities the case actually carries, and skips the rest silently
-- a field that does not exist produces no image rather than an empty frame.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

FIELDS = (
    ("p", "pressure", "Viridis (matplotlib)"),
    ("U", "velocity", "Cool to Warm"),
    ("Ma", "mach", "Inferno (matplotlib)"),
    ("T", "temperature", "Inferno (matplotlib)"),
    ("k", "turbulent_kinetic_energy", "Viridis (matplotlib)"),
    ("nut", "turbulent_viscosity", "Viridis (matplotlib)"),
)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--case", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--width", type=int, default=1400)
    ap.add_argument("--height", type=int, default=800)
    args = ap.parse_args()

    try:
        from paraview.simple import (  # type: ignore
            ColorBy, GetActiveViewOrCreate, GetColorTransferFunction,
            GetDisplayProperties, OpenFOAMReader, Render, ResetCamera,
            SaveScreenshot, Show, UpdatePipeline,
        )
    except ImportError:
        print("this script requires a ParaView interpreter (pvpython/pvbatch)",
              file=sys.stderr)
        return 2

    os.makedirs(args.out, exist_ok=True)
    foam = os.path.join(args.case, "case.foam")
    if not os.path.exists(foam):
        open(foam, "w").close()

    reader = OpenFOAMReader(FileName=foam)
    reader.MeshRegions = ["internalMesh"]
    UpdatePipeline()
    times = list(reader.TimestepValues or [0.0])
    available = set(reader.CellArrays) | set(reader.PointArrays)

    view = GetActiveViewOrCreate("RenderView")
    view.ViewSize = [args.width, args.height]
    display = Show(reader, view)
    ResetCamera()

    written = []
    for field, label, preset in FIELDS:
        if field not in available:
            continue
        ColorBy(display, ("POINTS", field))
        lut = GetColorTransferFunction(field)
        lut.ApplyPreset(preset, True)
        display.RescaleTransferFunctionToDataRange(True, False)
        display.SetScalarBarVisibility(view, True)
        view.ViewTime = times[-1]
        Render()
        path = os.path.join(args.out, f"{label}.png")
        SaveScreenshot(path, view)
        written.append(os.path.basename(path))

    with open(os.path.join(args.out, "contours_status.json"), "w") as fh:
        json.dump({"status": "RENDERED", "written": written,
                   "fields_available": sorted(available),
                   "time_rendered": times[-1]}, fh, indent=2)
    print(f"wrote {len(written)} contour image(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
