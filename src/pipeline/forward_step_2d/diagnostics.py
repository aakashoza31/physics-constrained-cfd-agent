#!/usr/bin/env python3
"""Transient diagnostics for the 2D forward-step family, from native fields.

PROVENANCE
----------
Adapted from ``src/pipeline/forward_step/diagnostics.py``. Reused essentially
unchanged: the strict ASCII ``field`` reader, ``relative_errors``, the discrete
transient balance ``dM/dt + sum(phi)``, the structured ``Layout``, and the
gradient-based ``shock_metrics``.

Removed, because they belong to the blocked 3D extrusion: spanwise uniformity,
cyclic-patch topology, the planar-velocity invariant and the z-plane sampling.

Added for this family: a per-saved-time shock-front history, a transient
evolution measure between the last two saved states, and an explicit
reference-comparison hook that reports PENDING rather than inventing numbers
when no trusted reference package is supplied.

This module measures. It does not decide; see validate.py.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import numpy as np

from .build import FLUX_PATCHES, fixed_recipe_unchanged
from .spec import GAMMA, R_SPECIFIC, CP, ForwardStep2DSpec

IMPERMEABLE = ["bottom", "top", "obstacle"]


# ----------------------------------------------------------------------
# fatal-error detection
#
# SCOPE CONTRACT. Everything in this section reads RAW OpenFOAM output only:
# the text the solver itself wrote to log.foamRun. It is never pointed at a
# generated agent summary, a validation document, an LLM diagnosis or a
# previous error description. Those legitimately contain the words "fatal
# error" while describing a healthy run, and feeding them back into the
# scanner makes the classification recursive and self-confirming: the agent
# would then be reacting to its own prose rather than to the solver.
#
# The signatures below are specific strings OpenFOAM, the C++ runtime or the
# shell emit on an actual failure, matched case-sensitively. A broad
# case-insensitive substring search is not used, because the benign startup
# banner
#
#     sigFpe : Enabling floating point exception trapping (FOAM_SIGFPE).
#
# contains the phrase "floating point exception" and announces only that
# trapping is switched ON. It is normal Foundation startup output on every
# run, including blockMesh and checkMesh, and it is not evidence that an
# exception occurred.
# ----------------------------------------------------------------------

#: The signal-handler configuration banner, removed before any search. A real
#: trapped signal does not print this line: it prints a
#: ``Foam::sigFpe::sigHandler`` stack frame, which survives this removal and
#: is matched by the signatures below.
BENIGN_SIGNAL_BANNER = re.compile(
    r"^[ \t]*sig(?:Fpe|Segv|Int|Quit)[ \t]*:[ \t]*(?:En|Dis)abling\b.*$",
    re.M,
)

#: Ordered (name, pattern) pairs. Case-sensitive by design.
FATAL_SIGNATURES = (
    ("foam_fatal_io_error", re.compile(r"FOAM FATAL IO ERROR")),
    ("foam_fatal_error", re.compile(r"FOAM FATAL ERROR")),
    ("foam_error_stack", re.compile(r"Foam::error::printStack")),
    ("sigfpe_trapped", re.compile(r"Foam::sigFpe::sigHandler")),
    ("sigsegv_trapped", re.compile(r"Foam::sigSegv::sigHandler")),
    ("floating_point_exception", re.compile(r"Floating point exception")),
    ("segmentation_fault", re.compile(r"Segmentation fault|SIGSEGV")),
    ("core_dumped", re.compile(r"core dumped")),
    ("abnormal_termination", re.compile(
        r"^Aborted\b|terminate called|std::bad_alloc", re.M
    )),
    # C++ iostreams write non-finite values lowercase. Requiring a delimiter
    # on both sides keeps this off words and paths that merely contain the
    # letters, while still catching "Courant Number mean: nan max: nan".
    ("non_finite_value", re.compile(
        r"(?:^|[\s=:(,\[])[-+]?(?:nan|inf)(?=[\s,;)\]]|$)", re.M
    )),
)

#: Executor statuses where the bounded executor stopped the solver on purpose.
#: These are not crashes. They are graded by reached_requested_end_time and by
#: the per-step positivity monitor, and an approved CONTINUE_RUN is the
#: designed response, so they must not raise the fatal flag.
EXECUTOR_HALTED = {"TIMED_OUT", "STALLED", "NONPHYSICAL"}

#: Shell-reported deaths by signal: SIGABRT, SIGFPE, SIGSEGV.
CRASH_RETURNCODES = {134, 136, 139}


#: Filenames the fatal scanner will accept. OpenFOAM writes log.foamRun; a
#: continuation or a fetched excerpt keeps that prefix.
RAW_SOLVER_LOG_PREFIX = "log.foamRun"


def read_raw_solver_log(path) -> str:
    """Read a raw OpenFOAM solver log, refusing any generated document.

    This is a structural guard on the scope contract above. Pointing the fatal
    scanner at SCIENTIFIC_SUMMARY.md, validation.json, agent_decision.json or
    an events log would let a description of a failure be counted as the
    failure, and would make a corrected run re-fail on the text of its own
    previous error report. Refusing by filename is checkable; sniffing content
    is not.
    """
    path = Path(path)
    if not path.name.startswith(RAW_SOLVER_LOG_PREFIX):
        raise ValueError(
            f"Refusing to scan {path.name!r} for fatal errors: this detector "
            f"accepts raw OpenFOAM solver logs only ({RAW_SOLVER_LOG_PREFIX}*). "
            "Generated summaries, validation documents and LLM text can "
            "contain the words 'fatal error' while describing a healthy run."
        )
    return path.read_text(errors="replace")


def _matched_line(text: str, start: int, end: int) -> str:
    left = text.rfind("\n", 0, start) + 1
    right = text.find("\n", end)
    return text[left : right if right != -1 else len(text)].strip()[:300]


def scan_fatal_signatures(raw_log: str) -> list:
    """Find genuine fatal signatures in a RAW OpenFOAM solver log.

    ``raw_log`` must be text OpenFOAM wrote. See the scope contract above.
    Returns one record per matching signature, each carrying the exact line
    that matched, so a future false positive is diagnosable from the evidence
    alone instead of requiring the regex to be re-derived.
    """
    text = BENIGN_SIGNAL_BANNER.sub("", raw_log)
    hits = []
    for name, pattern in FATAL_SIGNATURES:
        match = pattern.search(text)
        if match:
            hits.append(
                {
                    "signature": name,
                    "source": "solver_log",
                    "line": _matched_line(text, match.start(), match.end()),
                }
            )
    return hits


def scan_process_failure(execution: list) -> list:
    """Abnormal termination as reported by the executor, not by log text.

    A nonzero or signal return code is a genuine failure. A run the executor
    itself halted (wall-clock, stall, non-physical extremum) is not: it is
    bounded control flow, recorded with its own status and graded elsewhere.
    """
    hits = []
    for index, record in enumerate(execution or []):
        status = record.get("status")
        if status in EXECUTOR_HALTED:
            continue
        code = record.get("returncode")
        crashed = isinstance(code, int) and (
            code < 0 or code in CRASH_RETURNCODES
        )
        if status == "FAILED" or crashed or (isinstance(code, int) and code != 0):
            hits.append(
                {
                    "signature": "solver_returncode",
                    "source": "execution_record",
                    "line": (
                        f"solver run {index + 1}: status={status} "
                        f"returncode={code}"
                    ),
                }
            )
    return hits


# ----------------------------------------------------------------------
# native readers
# ----------------------------------------------------------------------


def field(path, n: Optional[int] = None, vector: bool = False) -> np.ndarray:
    """Strict reader for uncompressed ASCII OpenFOAM internal fields."""
    text = Path(path).read_text()
    m = re.search(
        r"internalField\s+nonuniform\s+List<(scalar|vector)>\s+(\d+)\s*\((.*?)\)\s*;",
        text,
        re.S,
    )
    if m:
        values = np.fromstring(
            m[3].replace("(", " ").replace(")", " "), sep=" "
        )
        count = int(m[2])
        width = 3 if m[1] == "vector" else 1
        if values.size != count * width:
            raise ValueError(f"Invalid field size: {path}")
        return values.reshape(count, 3) if width == 3 else values

    m = re.search(r"internalField\s+uniform\s+([^;]+);", text)
    if not m or n is None:
        raise ValueError(f"Unsupported or missing native field: {path}")
    values = np.fromstring(m[1].replace("(", " ").replace(")", " "), sep=" ")
    return np.tile(values, (n, 1)) if vector else np.full(n, values[0])


def state(case, time, n: int) -> Dict[str, np.ndarray]:
    folder = Path(case) / str(time)
    data = {k: field(folder / k, n, k == "U") for k in ("p", "T", "rho", "U")}
    data["speed"] = np.linalg.norm(data["U"], axis=1)
    with np.errstate(invalid="ignore", divide="ignore"):
        data["Mach"] = data["speed"] / np.sqrt(GAMMA * R_SPECIFIC * data["T"])
    return data


def relative_errors(actual, reference) -> Dict[str, float]:
    a = np.asarray(actual)
    b = np.asarray(reference)
    return {
        "relative_L2": float(
            np.linalg.norm(a - b) / max(np.linalg.norm(b), 1e-300)
        ),
        "relative_Linf": float(
            np.max(np.abs(a - b)) / max(np.max(np.abs(b)), 1e-300)
        ),
    }


# ----------------------------------------------------------------------
# structured layout (single z plane)
# ----------------------------------------------------------------------


class Layout:
    """Maps unstructured cell centres onto the structured (x, y) grid."""

    def __init__(self, xyz: np.ndarray) -> None:
        self.xyz = np.asarray(xyz)
        self.x = np.unique(np.round(self.xyz[:, 0], 12))
        self.y = np.unique(np.round(self.xyz[:, 1], 12))
        self.z = np.unique(np.round(self.xyz[:, 2], 12))
        self.ix = np.searchsorted(self.x, np.round(self.xyz[:, 0], 12))
        self.iy = np.searchsorted(self.y, np.round(self.xyz[:, 1], 12))
        if len(self.z) != 1:
            raise ValueError(
                f"This family is planar; found {len(self.z)} spanwise layers"
            )
        if len({(a, b) for a, b in zip(self.ix, self.iy)}) != len(self.xyz):
            raise ValueError("Duplicate coordinate bins")

    @property
    def shape(self) -> Tuple[int, int]:
        return (len(self.y), len(self.x))

    def plane(self, values) -> np.ndarray:
        """(ny, nx) array with NaN where the step solid removes cells."""
        values = np.asarray(values)
        out = np.full(self.shape + values.shape[1:], np.nan)
        out[self.iy, self.ix] = values
        return out


# ----------------------------------------------------------------------
# conservation
# ----------------------------------------------------------------------


def transient_balance(time, mass, fluxes: Dict[str, np.ndarray]):
    """Discrete storage balance dM/dt + sum(phi), matching the Euler update."""
    t = np.asarray(time)
    m = np.asarray(mass)
    dt = np.diff(t)
    if np.any(dt <= 0):
        raise ValueError("Monitor times must increase strictly")

    net = sum(fluxes.values())
    scale = np.maximum(
        np.maximum(abs(fluxes["inlet"]), abs(fluxes["outlet"])), 1e-300
    )
    residual = np.diff(m) / dt + net[1:]
    cumulative = m[1:] - m[0] + np.cumsum(dt * net[1:])

    summary = {
        "final_inlet": float(-fluxes["inlet"][-1]),
        "final_outlet": float(fluxes["outlet"][-1]),
        "instantaneous_mismatch_fraction": float(net[-1] / scale[-1]),
        "relative_residual_max": float(np.max(abs(residual / scale[1:]))),
        "relative_residual_p99": float(
            np.quantile(abs(residual / scale[1:]), 0.99)
        ),
        "cumulative_defect_fraction_initial_mass": float(cumulative[-1] / m[0]),
        "cumulative_defect_max_abs_fraction": float(
            np.max(abs(cumulative)) / m[0]
        ),
        "impermeable_flux_max_abs": float(
            max(np.max(abs(fluxes[k])) for k in IMPERMEABLE)
        ),
        "note": (
            "Mass closure only. shockFluid's momentum/energy boundary fluxes "
            "are local predictor temporaries, so no momentum or energy closure "
            "is claimed."
        ),
    }
    table = np.c_[
        t[1:], m[1:], net[1:], residual, residual / scale[1:], cumulative
    ]
    return summary, table


# ----------------------------------------------------------------------
# shock structure
# ----------------------------------------------------------------------


def shock_metrics(layout: Layout, data: Dict[str, np.ndarray], spec) -> Dict[str, Any]:
    """Gradient-based regional measurements. No theoretical state is imposed."""
    x, y = layout.x, layout.y
    p = layout.plane(data["p"])
    rho = layout.plane(data["rho"])
    T = layout.plane(data["T"])

    search = x[:-1] < spec.step_x * 1.3
    if not search.any():
        return {"available": False, "reason": "no sampling band upstream of the step"}

    dp = np.diff(p, axis=1) / np.diff(x)[None, :]
    with np.errstate(invalid="ignore"):
        loc = np.nanargmax(np.where(np.isnan(dp[:, search]), -np.inf, dp[:, search]), axis=1)
    front = (x[:-1] + np.diff(x) / 2)[loc]

    low = (y > 0.025 * spec.height) & (y < min(0.1 * spec.height, 0.5 * spec.step_height))
    fit = (y > 0.35 * spec.height) & (y < 0.65 * spec.height)

    angle = (
        float(np.degrees(np.arctan2(1, np.polyfit(y[fit], front[fit], 1)[0])))
        if fit.sum() >= 2
        else None
    )

    result: Dict[str, Any] = {
        "available": True,
        "upper_stem_x": float(np.mean(front[y > 0.85 * spec.height])),
        "regional_angle_deg": angle,
        "qualification": (
            "Gradient-based regional measurements on a moving, curved shock "
            "system. Not an exact stationary-shock interpretation and not a "
            "grid-converged measurement."
        ),
    }

    if not low.any():
        result["lower_front_x"] = None
        return result

    xf = float(np.mean(front[low]))
    dx = float(np.median(np.diff(x)))
    result["lower_front_x"] = xf

    # Sampling bands are geometric fractions of the step position, not fixed
    # cell counts, so the same physical region is sampled at any resolution.
    # At the canonical resolution these reproduce the 13dx/7dx and 3dx/7dx
    # windows the 3D diagnostics used.
    far, near = 0.2708 * spec.step_x, 0.1458 * spec.step_x
    inner, outer = 0.0625 * spec.step_x, 0.1458 * spec.step_x
    far = max(far, 2 * dx)
    near = max(min(near, far - dx), dx)
    inner = max(inner, dx)
    outer = max(outer, inner + dx)

    up = low[:, None] & (x[None, :] > xf - far) & (x[None, :] < xf - near)
    down = (
        low[:, None]
        & (x[None, :] > xf + inner)
        & (x[None, :] < min(xf + outer, spec.step_x - dx))
    )
    result["sample_counts"] = [int(up.sum()), int(down.sum())]

    if up.sum() and down.sum():
        with np.errstate(invalid="ignore"):
            result["jumps"] = {
                k: float(np.nanmean(a[down]) / np.nanmean(a[up]))
                for k, a in (("p", p), ("rho", rho), ("T", T))
            }
            upstream_mach = float(np.nanmean(layout.plane(data["Mach"])[up]))
        pr = 1 + 2 * GAMMA / (GAMMA + 1) * (upstream_mach**2 - 1)
        rr = (GAMMA + 1) * upstream_mach**2 / ((GAMMA - 1) * upstream_mach**2 + 2)
        result["sample_upstream_Mach"] = upstream_mach
        result["stationary_normal_shock_sanity"] = {
            "p": pr,
            "rho": rr,
            "T": pr / rr,
            "note": "Sanity reference for a stationary normal shock; not an acceptance band.",
        }

    return result


# ----------------------------------------------------------------------
# main entry
# ----------------------------------------------------------------------


def _monitor(case: Path, name: str) -> np.ndarray:
    directory = case / "postProcessing" / name
    files = sorted(directory.rglob("*.dat"))
    if not files:
        raise ValueError(f"Missing monitor output: {name}")
    rows = [
        np.loadtxt(f, comments="#", ndmin=2) for f in files
    ]
    table = np.vstack([r for r in rows if r.size])
    order = np.argsort(table[:, 0], kind="stable")
    table = table[order]
    # A continuation re-writes the restart time; keep the last record per time.
    _, keep = np.unique(table[:, 0][::-1], return_index=True)
    keep = len(table) - 1 - keep
    return table[np.sort(keep)]


def diagnose(case, output, spec=None, reference: Optional[str] = None):
    """Measure a completed or partially completed run. Returns (result, layout, data)."""
    case = Path(case)
    out = Path(output)
    out.mkdir(parents=True, exist_ok=True)

    spec = spec or ForwardStep2DSpec.load(case / "spec.json")

    xyz = field(case / "0/C", vector=True)
    n = len(xyz)
    vol = field(case / "0/Vc", n)
    layout = Layout(xyz)

    times = sorted(
        [
            p.name
            for p in case.iterdir()
            if p.is_dir()
            and re.fullmatch(r"[0-9]+(?:\.[0-9]+)?(?:[eE][-+]?[0-9]+)?", p.name)
            and float(p.name) > 0
        ],
        key=float,
    )
    if not times:
        raise ValueError("No saved solution states")

    finite = True
    positive = True
    history = []
    ranges = {k: [float("inf"), -float("inf")] for k in ("p", "rho", "T", "speed", "Mach")}
    front_history = []
    previous = None
    data = None

    for t in times:
        previous = data
        data = state(case, t, n)
        finite &= all(np.isfinite(a).all() for a in data.values())
        positive &= all((data[k] > 0).all() for k in ("p", "rho", "T"))
        for k in ranges:
            ranges[k] = [
                min(ranges[k][0], float(np.min(data[k]))),
                max(ranges[k][1], float(np.max(data[k]))),
            ]
        momentum = np.sum((data["rho"] * vol)[:, None] * data["U"], axis=0)
        energy = float(
            np.sum(
                data["rho"] * vol * ((CP - R_SPECIFIC) * data["T"] + 0.5 * data["speed"] ** 2)
            )
        )
        history.append(
            [float(t), float(np.sum(data["rho"] * vol)), *momentum.tolist(), energy]
        )
        shock = shock_metrics(layout, data, spec)
        front_history.append(
            [
                float(t),
                shock.get("lower_front_x") if shock.get("lower_front_x") is not None else np.nan,
                shock.get("upper_stem_x", np.nan),
            ]
        )

    # Raw solver output. Nothing generated by the agent is read here; see the
    # scope contract above scan_fatal_signatures.
    solver_log_path = case / "log.foamRun"
    log = read_raw_solver_log(solver_log_path)
    mesh_log = (case / "log.checkMesh").read_text()

    execution = json.loads((case / "execution.json").read_text(encoding="utf-8-sig"))
    if isinstance(execution, dict):
        execution = [execution]
    mesh_steps = json.loads((case / "mesh_steps.json").read_text(encoding="utf-8-sig"))

    fatal_hits = scan_fatal_signatures(log) + scan_process_failure(execution)

    result: Dict[str, Any] = {
        "spec": spec.to_dict(),
        "cells": n,
        "final_time": float(times[-1]),
        "saved_times": len(times),
        "requested_end_time": spec.end_time,
        "reached_requested_end_time": abs(float(times[-1]) - spec.end_time) < 1e-9,
        "solver_completed": bool(
            execution
            and execution[-1].get("status") == "COMPLETED"
            and execution[-1].get("returncode") == 0
            and "End" in log
        ),
        "solver_runs": len(execution),
        "continuation_used": any(r.get("continuation") for r in execution),
        "mesh_ok": "Mesh OK" in mesh_log,
        "two_solution_directions": "2 solution (non-empty) directions" in mesh_log,
        "mesh_failed_step": mesh_steps.get("failed_step") or None,
        "fatal_error": bool(fatal_hits),
        "fatal_error_evidence": fatal_hits,
        "fatal_scan": {
            "solver_log": solver_log_path.name,
            "solver_log_bytes": len(log),
            "solver_log_complete": True,
            "signatures_checked": [name for name, _ in FATAL_SIGNATURES],
            "benign_excluded": (
                "FOAM_SIGFPE / sigSegv / sigInt / sigQuit startup banner"
            ),
        },
        "finite_all_saved": bool(finite),
        "positive_all_saved": bool(positive),
        "ranges_all_saved": ranges,
        "final_ranges": {
            k: [float(np.min(data[k])), float(np.max(data[k]))] for k in ranges
        },
        "runtime_seconds": sum(float(r.get("wall_seconds", 0.0)) for r in execution),
        "steps": len(re.findall(r"^Time = ", log, re.M)),
        "nominal_inlet_Mach": spec.mach,
        "realized_inlet_Mach": spec.realized_mach,
        "gas": {"R": R_SPECIFIC, "gamma": GAMMA, "Cp": CP},
        "warnings": [l for l in log.splitlines() if "Warning" in l][:20],
        "energy_momentum_scope": (
            "Stored domain totals only. Boundary momentum and energy flux "
            "closure is not computed and is not claimed."
        ),
    }

    boundary = (case / "constant/polyMesh/boundary").read_text()
    result["boundary"] = {
        "empty_patch_present": bool(re.search(r"\btype\s+empty;", boundary)),
        "cyclic_patch_count": len(re.findall(r"\btype\s+cyclic;", boundary)),
        "expected_patches_present": all(
            re.search(rf"^\s*{p}\s*$", boundary, re.M) for p in FLUX_PATCHES
        ),
    }
    result["fixed_recipe_unchanged"] = fixed_recipe_unchanged(case)
    result["cell_count_matches_spec"] = n == spec.cells

    initial = {k: field(case / "0" / k, n, k == "U") for k in ("p", "T", "U")}
    result["initial_state_errors"] = {
        "p": float(np.max(abs(initial["p"] - spec.pressure))),
        "T": float(np.max(abs(initial["T"] - spec.temperature))),
        "U": float(np.max(abs(initial["U"] - np.array([spec.velocity, 0, 0])))),
    }

    courant = [
        float(v)
        for v in re.findall(
            r"Courant Number mean: \S+ max: (\S+)", log.split("Starting time loop")[-1]
        )
    ]
    result["Co"] = {
        "target": spec.max_co,
        "time_loop_max": max(courant) if courant else None,
        "last": courant[-1] if courant else None,
        "samples": len(courant),
    }
    result["courant_finite_positive"] = bool(
        courant and np.isfinite(courant).all() and min(courant) > 0
    )

    for key, pattern in [
        ("max_nonorthogonality", r"Mesh non-orthogonality Max: (\S+)"),
        ("max_skewness", r"Max skewness = (\S+)"),
        ("max_aspect_ratio", r"Max aspect ratio = (\S+)"),
    ]:
        m = re.search(pattern, mesh_log)
        result[key] = float(m[1]) if m else None

    mass = _monitor(case, "mass")
    fluxes = {}
    for patch in FLUX_PATCHES:
        table = _monitor(case, "flux_" + patch)
        if not np.array_equal(table[:, 0], mass[:, 0]):
            raise ValueError(f"Monitor times differ for flux_{patch}")
        fluxes[patch] = table[:, 1]

    result["mass"], balance_table = transient_balance(mass[:, 0], mass[:, 1], fluxes)
    result["minima_every_step"] = dict(
        zip(["rho", "p", "T"], _monitor(case, "minima")[:, 1:].min(axis=0).tolist())
    )

    result["transient_evolution"] = (
        {k: relative_errors(data[k], previous[k]) for k in ("p", "rho", "T", "U")}
        if previous is not None
        else {}
    )
    result["shock"] = shock_metrics(layout, data, spec)

    if reference:
        result["reference_comparison"] = compare_reference(
            layout, data, spec, reference
        )
    else:
        result["reference_comparison"] = {
            "status": "PENDING_NO_REFERENCE_PACKAGE",
            "note": (
                "The trusted 2D reference evidence package is not present in "
                "this repository. No reference numbers are invented. Supply a "
                "reference .npz to enable this comparison."
            ),
        }

    np.savetxt(
        out / "stored_totals.csv",
        history,
        delimiter=",",
        header="time,mass,momentum_x,momentum_y,momentum_z,total_energy",
        comments="",
    )
    np.savetxt(
        out / "transient_mass.csv",
        balance_table,
        delimiter=",",
        header="time,mass,net_outward_flux,residual,relative_residual,cumulative_defect",
        comments="",
    )
    np.savetxt(
        out / "shock_front_history.csv",
        np.asarray(front_history, dtype=float),
        delimiter=",",
        header="time,lower_front_x,upper_stem_x",
        comments="",
    )
    np.savez_compressed(
        out / "native_final.npz", coordinates=xyz, volumes=vol, **data
    )

    (out / "diagnostics.json").write_text(
        json.dumps(result, indent=2, allow_nan=False)
    )
    return result, layout, data


def compare_reference(layout: Layout, data, spec, reference) -> Dict[str, Any]:
    """Compare against a trusted reference .npz written by this pipeline."""
    ref = np.load(reference)
    ref_layout = Layout(ref["coordinates"])

    if not (
        np.allclose(layout.x, ref_layout.x, rtol=0, atol=1e-10)
        and np.allclose(layout.y, ref_layout.y, rtol=0, atol=1e-10)
    ):
        return {
            "status": "NOT_APPLICABLE_DIFFERENT_GRID",
            "note": "Reference and target grids differ; no field comparison attempted.",
        }

    comparison: Dict[str, Any] = {"status": "MEASURED"}
    for k in ("Mach", "p", "rho", "T", "U", "speed"):
        a = layout.plane(data[k])
        b = ref_layout.plane(ref[k])
        valid = np.isfinite(b) & np.isfinite(a)
        comparison[k] = relative_errors(a[valid], b[valid])
    return comparison
