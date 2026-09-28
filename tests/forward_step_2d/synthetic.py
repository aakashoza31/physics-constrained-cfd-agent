#!/usr/bin/env python3
"""Fabricate an OpenFOAM-shaped 2D forward-step case for testing.

THIS IS NOT CFD. The fields here are analytic placeholders whose only job is to
exercise the readers, the conservation arithmetic, the validator branches and
the plotting code without an OpenFOAM installation. Nothing produced here is a
simulation result and nothing produced here is ever presented as one.

The file layout, however, is the real one: the same directory names, monitor
formats and log phrases the pipeline parses from a genuine run, so that a test
passing here means the parsing logic is right.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Dict, List

import numpy as np

from src.pipeline.forward_step_2d.build import FLUX_PATCHES, build
from src.pipeline.forward_step_2d.spec import ForwardStep2DSpec

HEADER = "FoamFile {{ format ascii; class {cls}; object {obj}; }}\n"


def _block_centres(spec: ForwardStep2DSpec):
    a, b = spec.splits
    xs_low = (np.arange(a) + 0.5) * (spec.step_x / a)
    xs_high = spec.step_x + (np.arange(spec.nx - a) + 0.5) * (
        (spec.length - spec.step_x) / (spec.nx - a)
    )
    ys_low = (np.arange(b) + 0.5) * (spec.step_height / b)
    ys_high = spec.step_height + (np.arange(spec.ny - b) + 0.5) * (
        (spec.height - spec.step_height) / (spec.ny - b)
    )

    points = []
    for y in ys_low:
        for x in xs_low:
            points.append((x, y))
    for y in ys_high:
        for x in np.r_[xs_low, xs_high]:
            points.append((x, y))
    return np.array(points)


def _write_field(path: Path, values: np.ndarray, name: str, vector: bool) -> None:
    cls = "volVectorField" if vector else "volScalarField"
    if vector:
        body = "\n".join(
            "(" + " ".join(f"{v:.16g}" for v in row) + ")" for row in values
        )
        kind = "vector"
    else:
        body = "\n".join(f"{v:.16g}" for v in values)
        kind = "scalar"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        HEADER.format(cls=cls, obj=name)
        + f"internalField   nonuniform List<{kind}>\n{len(values)}\n(\n{body}\n);\n"
        + "boundaryField { }\n"
    )


def _fields(spec: ForwardStep2DSpec, xy: np.ndarray, t: float) -> Dict[str, np.ndarray]:
    """Placeholder fields with a moving compression front. Not physics."""
    x, y = xy[:, 0], xy[:, 1]
    # Compression ahead of the step: low p upstream (small x), high p behind
    # the front, which is the orientation of the real bow shock.
    front = 0.40 - 0.30 * t
    ramp = 1.0 / (1.0 + np.exp(-(x - front) / 0.05))

    p = spec.pressure * (1.0 + 9.0 * ramp)
    T = spec.temperature * (1.0 + 1.6 * ramp)
    rho = p / (T * 0.7142825028696203)
    ux = spec.velocity * (1.0 - 0.75 * ramp)
    uy = 0.12 * spec.velocity * ramp * np.sin(np.pi * y / spec.height)
    U = np.c_[ux, uy, np.zeros_like(ux)]
    return {"p": p, "T": T, "rho": rho, "U": U}


def _poly_mesh(case: Path, spec: ForwardStep2DSpec) -> None:
    """Minimal polyMesh: the outer boundary only, enough for plots/boundary checks."""
    w = spec.span / 2
    xy = [
        (0, 0), (spec.step_x, 0), (spec.step_x, spec.step_height),
        (spec.length, spec.step_height), (spec.length, spec.height), (0, spec.height),
    ]
    points = [(x, y, z) for z in (-w, w) for x, y in xy]
    n = len(xy)
    faces: List[List[int]] = []
    for i in range(n):
        j = (i + 1) % n
        faces.append([i, j, j + n, i + n])

    pm = case / "constant/polyMesh"
    pm.mkdir(parents=True, exist_ok=True)
    pm.joinpath("points").write_text(
        HEADER.format(cls="vectorField", obj="points")
        + f"\n{len(points)}\n(\n"
        + "\n".join("(%.12g %.12g %.12g)" % p for p in points)
        + "\n)\n"
    )
    pm.joinpath("faces").write_text(
        HEADER.format(cls="faceList", obj="faces")
        + f"\n{len(faces)}\n(\n"
        + "\n".join("4(" + " ".join(str(i) for i in f) + ")" for f in faces)
        + "\n)\n"
    )
    body = ""
    start = 0
    for name, kind in [
        ("inlet", "patch"), ("outlet", "patch"), ("bottom", "symmetryPlane"),
        ("top", "symmetryPlane"), ("obstacle", "patch"), ("defaultFaces", "empty"),
    ]:
        body += (
            f"    {name}\n    {{\n        type {kind};\n"
            f"        nFaces 1;\n        startFace {start};\n    }}\n"
        )
        start += 1
    pm.joinpath("boundary").write_text(
        HEADER.format(cls="polyBoundaryMesh", obj="boundary") + f"\n6\n(\n{body})\n"
    )


def _monitor(
    case: Path,
    name: str,
    times: np.ndarray,
    values: np.ndarray,
    restart_at: float = None,
    seam_offset: float = 0.0,
) -> None:
    """Write a monitor history, optionally split across two executions.

    ``seam_offset`` shifts the SECOND execution's values only, including its
    own record of the seam time. That is what a restart which did not
    continue the same state looks like from the monitors: the segment that
    ended and the segment that resumed disagree about the domain at the same
    instant. Shifting a single concatenated array instead would put the jump
    inside one segment, which is a different defect.

    OpenFOAM names one postProcessing subdirectory per solver invocation,
    after the time that invocation started. With ``restart_at`` set, the
    history is split the way a continued run really lays it out: the first
    execution's directory ends AT the seam time, and the second execution's
    directory begins at the same time with its own record of it. Both records
    of the seam exist, which is what makes the restart auditable.
    """
    rows = np.c_[times, np.asarray(values)]
    header = "# Forward-step synthetic monitor\n# Time\tvalue\n"

    if restart_at is None:
        blocks = [(0.0, rows)]
    else:
        cut = int(np.searchsorted(times, restart_at, side="right"))
        first, second = rows[:cut].copy(), rows[cut - 1 :].copy()
        if seam_offset:
            second[:, 1:] = second[:, 1:] + seam_offset
        blocks = [(0.0, first), (float(restart_at), second)]

    for start, block in blocks:
        directory = case / "postProcessing" / name / f"{start:g}"
        directory.mkdir(parents=True, exist_ok=True)
        directory.joinpath("volFieldValue.dat").write_text(
            header
            + "\n".join("\t".join(f"{v:.16g}" for v in row) for row in block)
            + "\n"
        )


def make_case(
    root: Path,
    spec: ForwardStep2DSpec = None,
    *,
    save_times=(0.1, 0.2, 0.3),
    completed: bool = True,
    mesh_ok: bool = True,
    restart_at: float = None,
    seam_mass_jump: float = 0.0,
    two_directions: bool = True,
    positive: bool = True,
    reached_end: bool = True,
) -> Path:
    """Write a complete synthetic case tree and return its path."""
    # final_target_end_time is stated explicitly and equal to end_time: this
    # fixture stands for a run that HAS reached the horizon its request asked
    # for, so it exercises the final-acceptance path. Leaving it unset would
    # silently inherit the family reference horizon of 4 and make every
    # synthetic run a healthy-but-unfinished one, which is a different case
    # and is covered by its own tests.
    spec = spec or ForwardStep2DSpec(
        nx=60, ny=20, end_time=0.3, write_interval=0.1, final_target_end_time=0.3
    )
    case = Path(root) / "case"
    build(spec, case)

    xy = _block_centres(spec)
    n = len(xy)
    assert n == spec.cells, f"synthetic mesh {n} != spec {spec.cells}"

    _write_field(case / "0/C", np.c_[xy, np.zeros(n)], "C", vector=True)
    _write_field(
        case / "0/Vc",
        np.full(n, spec.dx * spec.dy * spec.span),
        "Vc",
        vector=False,
    )
    _poly_mesh(case, spec)

    for t in save_times:
        data = _fields(spec, xy, t)
        if not positive and t == save_times[-1]:
            data["p"] = data["p"] - data["p"].max() * 1.1
        folder = case / f"{t:g}"
        for key in ("p", "T", "rho", "U"):
            _write_field(folder / key, data[key], key, vector=(key == "U"))

    # monitors: every step, mass drifts with a consistent net flux
    steps = np.linspace(0.0, float(save_times[-1]), 31)
    inlet = np.full_like(steps, -0.42)
    outlet = np.full_like(steps, 0.40)
    walls = np.zeros_like(steps)
    net = inlet + outlet
    mass = 0.63 - np.concatenate([[0.0], np.cumsum(np.diff(steps) * net[1:])])
    # A non-zero seam_mass_jump is a restart that did NOT continue the same
    # state: the resumed segment reports a different domain mass at the seam.
    _monitor(case, "mass", steps, mass, restart_at, seam_offset=seam_mass_jump)
    _monitor(case, "minima", steps, np.c_[
        np.full_like(steps, 0.05), np.full_like(steps, 0.02), np.full_like(steps, 0.7)
    ], restart_at)
    for patch, values in zip(FLUX_PATCHES, [inlet, outlet, walls, walls, walls]):
        _monitor(case, "flux_" + patch, steps, values, restart_at)

    final = float(save_times[-1]) if reached_end else float(save_times[-1])
    log = ["Starting time loop\n"]
    for t in steps[1:]:
        log.append(f"Courant Number mean: 0.05 max: {0.19 + 0.002 * (t > 0.2):.6g}\n")
        log.append(f"Time = {t:.6g}s\n")
    if completed:
        log.append("End\n")
    (case / "log.foamRun").write_text("".join(log))

    (case / "log.checkMesh").write_text(
        "Checking geometry...\n"
        + ("    Mesh has 2 solution (non-empty) directions (1 1 0)\n" if two_directions else
           "    Mesh has 3 solution (non-empty) directions (1 1 1)\n")
        + "Mesh non-orthogonality Max: 0 average: 0\n"
        + "Max skewness = 1.2e-13 OK.\n"
        + "Max aspect ratio = 1.0000001 OK.\n"
        + ("Mesh OK.\nEnd\n" if mesh_ok else "***Failed 1 mesh checks.\nEnd\n")
    )

    records = [{
        "status": "COMPLETED" if completed else "TIMED_OUT",
        "returncode": 0 if completed else 3,
        "wall_seconds": 12.5,
        "last_observed_time": restart_at if restart_at is not None else final,
        "requested_end_time": restart_at if restart_at is not None else spec.end_time,
        "continuation": False,
        "command": f"foamRun -case {case}",
    }]
    if restart_at is not None:
        # A genuine continuation: resumed from latestTime, recorded as such,
        # with the state it restarted from still on disk.
        records.append({
            "status": "COMPLETED" if completed else "TIMED_OUT",
            "returncode": 0 if completed else 3,
            "wall_seconds": 9.0,
            "last_observed_time": final,
            "requested_end_time": spec.end_time,
            "continuation": True,
            "command": f"foamRun -case {case}",
        })
        control = case / "system/controlDict"
        control.write_text(
            re.sub(
                r"^startFrom\s+[^;]+;",
                "startFrom       latestTime;",
                control.read_text(),
                flags=re.M,
            )
        )
        (case / f"{float(restart_at):g}").mkdir(exist_ok=True)
    (case / "execution.json").write_text(json.dumps(records, indent=2))

    (case / "mesh_steps.json").write_text(json.dumps({
        "case": str(case),
        "openfoam_version": "14",
        "failed_step": "" if mesh_ok else "checkMesh_reports_Mesh_OK",
        "returncode": 0 if mesh_ok else 1,
        "steps": [{"name": "blockMesh", "returncode": 0, "log": ""}],
    }, indent=2))

    return case
