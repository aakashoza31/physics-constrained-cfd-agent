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
from typing import Any, Dict, List, Optional, Tuple

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


def collect_warnings(raw_log: str, limit: int = 20) -> list:
    """Capture OpenFOAM warnings WITH their message.

    OpenFOAM writes a warning as a marker line followed by indented
    continuation lines::

        --> FOAM Warning :
            From function ...
            in file ...
            <the actual message>

    Taking only lines containing the word "Warning" therefore records
    ``'--> FOAM Warning: '`` and discards the entire content, which is what
    the first live run archived. The continuation lines are kept here so a
    warning can be read from the evidence instead of requiring the runtime
    log to still exist.
    """
    lines = raw_log.splitlines()
    warnings = []
    index = 0
    while index < len(lines) and len(warnings) < limit:
        if "Warning" not in lines[index]:
            index += 1
            continue
        block = [lines[index].rstrip()]
        index += 1
        # Continuation lines are indented or blank-then-indented; stop at the
        # first left-aligned non-empty line, which starts the next record.
        while index < len(lines) and len(block) < 8:
            candidate = lines[index]
            if candidate.strip() and not candidate[:1].isspace():
                break
            if candidate.strip():
                block.append(candidate.rstrip())
            index += 1
        warnings.append("\n".join(block))
    return warnings


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


# ----------------------------------------------------------------------
# restart-aware transient mass closure
#
# WHY THIS IS NOT A PLAIN FINITE DIFFERENCE
#
# The discrete balance dM/dt + sum(phi) is a statement about ONE timestep of
# ONE solver execution. A continued run is several executions, and OpenFOAM's
# function objects write a record at the restart time whose flux is evaluated
# on the restarted state, at the beginning of the new segment. Differencing
# straight through that record pairs a mass increment taken from the previous
# segment's timeline with a flux taken from the next segment's, which is not a
# timestep of anything.
#
# Case H made this visible. At the t = 1 seam of a 0.5 -> 1 -> 2 run:
#
#   t = 0.99944  m = 0.4332749512167377  net = -0.1079100485239115   (segment 2)
#   t = 1.00000  m = 0.4333350147443190  net = -0.1083002922915611   (segment 3)
#   t = 1.00059  m = 0.4333990977575122  net = -0.1083002922915611   (segment 3)
#
# dM/dt across the seam is 0.108108, a perfectly ordinary number. The flux it
# is differenced against is the next segment's, one timestep of flux evolution
# away (the seam and the step after it carry the same value to all 16 digits),
# and the mismatch lands as a 1.9e-4 residual. Every genuine within-segment
# residual in the same run is ~1e-11.
#
# The earlier t = 0.5 seam of the same run produced no spike at all, because
# the flux happened to be flat there. That is the argument for handling this
# structurally rather than by widening a tolerance: whether a seam shows up is
# an accident of where the flux derivative happens to be.
#
# So: residuals are formed only between samples of the SAME segment. The seam
# measurement is kept, labelled, and reported. A seam may be excluded from the
# physical statistics only if state continuity across it is independently
# demonstrated; if it is not, the seam counts and the check fails.
# ----------------------------------------------------------------------

#: A restart must reproduce the stored mass integral to round-off. The fields
#: are written with writePrecision 16, so the round trip is exact to double
#: precision, and the volume integral over 16,128 cells has a summation
#: round-off floor near N * eps = 3.6e-12. This bound sits three orders above
#: that floor: loose enough that ordinary summation order cannot trip it,
#: tight enough that any real reinitialization is caught. It is a continuity
#: test on the restart, not a conservation tolerance: the conservation
#: threshold in validate.py is unchanged.
RESTART_MASS_CONTINUITY_TOL = 1e-9

PHYSICAL_STEP = "PHYSICAL_TIMESTEP"
RESTART_BOUNDARY = "RESTART_BOUNDARY_MEASUREMENT"


def _segment_stats(residual, scale, mask) -> Dict[str, float]:
    """Residual statistics over a selected subset of consecutive pairs."""
    if not np.any(mask):
        return {"samples": 0, "relative_residual_max": 0.0,
                "relative_residual_p99": 0.0}
    relative = abs(residual[mask] / scale[mask])
    return {
        "samples": int(mask.sum()),
        "relative_residual_max": float(np.max(relative)),
        "relative_residual_p99": float(np.quantile(relative, 0.99)),
    }


def transient_balance(
    time,
    mass,
    fluxes: Dict[str, np.ndarray],
    segments=None,
):
    """Discrete storage balance dM/dt + sum(phi), matching the Euler update.

    ``segments`` labels which solver execution produced each monitor sample.
    Pairs that straddle two labels are restart-boundary measurements: they are
    computed and reported, never differenced as physics. With ``segments``
    omitted every sample is one segment and the result is the plain balance.
    """
    t = np.asarray(time, dtype=float)
    m = np.asarray(mass, dtype=float)
    seg = (
        np.zeros(len(t), dtype=int)
        if segments is None
        else np.asarray(segments, dtype=int)
    )
    if len(seg) != len(t):
        raise ValueError("Segment labels must match the monitor sample count")

    within = seg[1:] == seg[:-1]
    dt = np.diff(t)
    if np.any(dt[within] <= 0):
        raise ValueError("Monitor times must increase strictly inside a segment")

    net = sum(fluxes.values())
    scale = np.maximum(
        np.maximum(abs(fluxes["inlet"]), abs(fluxes["outlet"])), 1e-300
    )[1:]

    # The seam pair has no meaningful dt. It is computed with a guarded
    # denominator purely so the raw measurement can be reported; it is never
    # used as a physical residual.
    safe_dt = np.where(dt == 0, np.nan, dt)
    with np.errstate(invalid="ignore", divide="ignore"):
        residual = np.diff(m) / safe_dt + net[1:]
    residual = np.nan_to_num(residual, nan=0.0, posinf=0.0, neginf=0.0)
    relative = residual / scale

    # Cumulative defect accrues inside a segment and is not carried across a
    # seam, where the increment is not a timestep.
    cumulative = np.zeros(len(residual))
    per_segment: List[Dict[str, Any]] = []
    running = 0.0
    for label in np.unique(seg):
        rows = np.flatnonzero(seg == label)
        first, last = rows[0], rows[-1]
        steps = np.arange(first + 1, last + 1) - 1  # residual indices
        if steps.size:
            drift = (
                m[first + 1 : last + 1]
                - m[first]
                + np.cumsum(dt[steps] * net[first + 1 : last + 1])
            )
            cumulative[steps] = running + drift
            running = cumulative[steps][-1]
        per_segment.append(
            {
                "segment": int(label),
                "start_time": float(t[first]),
                "end_time": float(t[last]),
                "samples": int(rows.size),
                "start_mass": float(m[first]),
                "end_mass": float(m[last]),
                "cumulative_defect_fraction_initial_mass": (
                    float(drift[-1] / m[first]) if steps.size else 0.0
                ),
                **_segment_stats(residual, scale, seg[1:] == label),
            }
        )

    boundaries = np.flatnonzero(~within)
    seam_rows = []
    for i in boundaries:
        entry: Dict[str, Any] = {
            "classification": RESTART_BOUNDARY,
            "time": float(t[i + 1]),
            "from_segment": int(seg[i]),
            "to_segment": int(seg[i + 1]),
            "mass_before_restart": float(m[i]),
            "mass_after_restart": float(m[i + 1]),
            "mass_jump_across_seam": float(m[i + 1] - m[i]),
            "dt_across_seam": float(dt[i]),
            "note": (
                "Both executions record this instant. The pair spans two "
                "solver invocations, so no timestep separates them and no "
                "physical residual is defined across it."
            ),
        }
        # The measurement a naive concatenation produces, preserved verbatim.
        # Collapsing the two seam records to one and differencing straight
        # through is what reported -1.93e-4 at t = 1 in Case H: a mass
        # increment from the ending segment paired with a flux written on the
        # restarted state, one timestep of flux evolution away. Keeping the
        # number here means the historical reading can be audited rather than
        # taken on trust.
        if i >= 1 and t[i] > t[i - 1]:
            span = t[i + 1] - t[i - 1]
            naive = (m[i + 1] - m[i - 1]) / span + net[i + 1]
            entry["naive_deduplicated_residual"] = float(naive)
            entry["naive_deduplicated_relative_residual"] = float(
                naive / scale[i]
            )
            entry["naive_note"] = (
                "What a reader that keeps one record per time and differences "
                "across the seam would report. Not a physical residual."
            )
        seam_rows.append(entry)

    raw = _segment_stats(residual, scale, np.ones(len(residual), dtype=bool))
    aware = _segment_stats(residual, scale, within)

    summary: Dict[str, Any] = {
        "final_inlet": float(-fluxes["inlet"][-1]),
        "final_outlet": float(fluxes["outlet"][-1]),
        "instantaneous_mismatch_fraction": float(net[-1] / scale[-1]),
        "impermeable_flux_max_abs": float(
            max(np.max(abs(fluxes[k])) for k in IMPERMEABLE)
        ),
        "segments": per_segment,
        "restart_boundaries": seam_rows,
        # A. every consecutive pair, seams included: what a naive reading sees.
        "raw": {
            **raw,
            "includes_restart_boundaries": True,
            "cumulative_defect_fraction_initial_mass": float(
                (m[-1] - m[0] + np.sum(dt * net[1:])) / m[0]
            ),
        },
        # B. within-segment pairs only: the physical statistic.
        "restart_aware": {
            **aware,
            "restart_boundaries_excluded": len(seam_rows),
            "cumulative_defect_fraction_initial_mass": float(
                cumulative[-1] / m[0]
            ) if len(cumulative) else 0.0,
            "cumulative_defect_max_abs_fraction": float(
                np.max(abs(cumulative)) / m[0]
            ) if len(cumulative) else 0.0,
        },
        "note": (
            "Mass closure only. shockFluid's momentum/energy boundary fluxes "
            "are local predictor temporaries, so no momentum or energy closure "
            "is claimed."
        ),
    }

    # Headline keys default to the within-segment statistics. With no seam
    # present the two sets are identical and this is the plain balance;
    # select_conservation_basis revises them when a seam exists and its
    # continuity has been tested.
    summary["conservation_basis"] = "restart_aware"
    summary["relative_residual_max"] = aware["relative_residual_max"]
    summary["relative_residual_p99"] = aware["relative_residual_p99"]
    summary["cumulative_defect_fraction_initial_mass"] = summary[
        "restart_aware"
    ]["cumulative_defect_fraction_initial_mass"]
    summary["cumulative_defect_max_abs_fraction"] = summary["restart_aware"][
        "cumulative_defect_max_abs_fraction"
    ]

    classification = np.where(within, 0.0, 1.0)
    table = np.c_[
        t[1:], m[1:], net[1:], residual, relative, cumulative, classification
    ]
    return summary, table


def select_conservation_basis(
    summary: Dict[str, Any], continuity: Dict[str, Any]
) -> Dict[str, Any]:
    """Promote one statistic set to the headline keys. Fails closed.

    A restart boundary may be dropped from the physical statistics only when
    the restart is independently shown to have continued the same state. If
    any seam is unverified the raw statistics stand, seam spike included, and
    the conservation check fails on them. Both sets remain in the record
    either way.
    """
    seams_ok = bool(continuity.get("all_seams_continuous", True))
    basis = "restart_aware" if seams_ok else "raw"
    chosen = summary[basis]

    summary["restart_continuity"] = continuity
    summary["conservation_basis"] = basis
    summary["conservation_basis_reason"] = (
        "Restart boundaries excluded: every seam independently verified to "
        "continue the same solution."
        if seams_ok
        else "Restart boundaries retained: state continuity across at least "
        "one seam is not demonstrated, so no seam may be excluded."
    )
    summary["relative_residual_max"] = chosen["relative_residual_max"]
    summary["relative_residual_p99"] = chosen["relative_residual_p99"]
    summary["cumulative_defect_fraction_initial_mass"] = chosen.get(
        "cumulative_defect_fraction_initial_mass", 0.0
    )
    summary["cumulative_defect_max_abs_fraction"] = chosen.get(
        "cumulative_defect_max_abs_fraction",
        abs(chosen.get("cumulative_defect_fraction_initial_mass", 0.0)),
    )
    return summary


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


def _monitor_segments(case: Path, name: str) -> List[Tuple[float, np.ndarray]]:
    """Per-execution monitor tables, oldest first.

    OpenFOAM writes ``postProcessing/<function>/<startTime>/`` once per solver
    invocation, so the directory names ARE the segment boundaries. That is
    runtime evidence of where one execution ended and the next began, and it
    is what makes a restart seam identifiable without guessing from the data.
    """
    directory = case / "postProcessing" / name
    if not directory.is_dir():
        raise ValueError(f"Missing monitor output: {name}")

    segments: List[Tuple[float, np.ndarray]] = []
    for sub in sorted(
        (d for d in directory.iterdir() if d.is_dir()),
        key=lambda d: float(d.name),
    ):
        rows = [np.loadtxt(f, comments="#", ndmin=2) for f in sorted(sub.rglob("*.dat"))]
        rows = [r for r in rows if r.size]
        if not rows:
            continue
        table = np.vstack(rows)
        table = table[np.argsort(table[:, 0], kind="stable")]
        # Duplicates WITHIN one execution keep the last record. Duplicates
        # ACROSS executions are the seam and are deliberately not collapsed:
        # both sides are needed to verify the restart continued the state.
        _, keep = np.unique(table[:, 0][::-1], return_index=True)
        keep = len(table) - 1 - keep
        segments.append((float(sub.name), table[np.sort(keep)]))

    if not segments:
        raise ValueError(f"Missing monitor output: {name}")
    return segments


def _monitor_concatenated(case: Path, name: str) -> Tuple[np.ndarray, np.ndarray]:
    """(rows, segment_label_per_row) across every execution, in time order."""
    segments = _monitor_segments(case, name)
    tables = [table for _, table in segments]
    labels = [np.full(len(table), i, dtype=int) for i, table in enumerate(tables)]
    return np.vstack(tables), np.concatenate(labels)


def _monitor(case: Path, name: str) -> np.ndarray:
    """Flattened monitor history, one record per time. Order preserved."""
    table, _ = _monitor_concatenated(case, name)
    order = np.argsort(table[:, 0], kind="stable")
    table = table[order]
    _, keep = np.unique(table[:, 0][::-1], return_index=True)
    keep = len(table) - 1 - keep
    return table[np.sort(keep)]


def restart_continuity(
    case: Path,
    mass_segments: List[Tuple[float, np.ndarray]],
    execution: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Independently verify that each restart continued the same solution.

    A restart boundary earns exclusion from the physical conservation
    statistics only by passing every one of these, which are checked against
    different evidence so that no single artefact can carry the conclusion:

      stored mass    the segment that ended and the segment that resumed
                     report the same domain mass at the seam time
      latestTime     controlDict resumes from the last written state rather
                     than re-reading the initial condition
      continuation   the executor recorded the run as a continuation
      saved state    the time directory the restart read from exists

    Anything short of all four leaves the seam in the ordinary residual
    series, where it will fail the closure check. Fail closed.
    """
    control = ""
    control_path = case / "system/controlDict"
    if control_path.is_file():
        control = control_path.read_text(errors="replace")
    start_from_latest = bool(
        re.search(r"^\s*startFrom\s+latestTime\s*;", control, re.M)
    )

    continuations = [bool(r.get("continuation")) for r in (execution or [])]

    seams: List[Dict[str, Any]] = []
    for index in range(1, len(mass_segments)):
        start_label, table = mass_segments[index]
        _, previous = mass_segments[index - 1]

        time_before, mass_before = float(previous[-1, 0]), float(previous[-1, 1])
        time_after, mass_after = float(table[0, 0]), float(table[0, 1])
        times_match = abs(time_after - time_before) <= 1e-9 * max(
            1.0, abs(time_before)
        )
        jump = abs(mass_after - mass_before) / max(abs(mass_before), 1e-300)

        # The executor record for the segment that resumed. Missing records
        # are treated as unverified, not as verified.
        recorded = (
            continuations[index] if index < len(continuations) else False
        )
        saved_state = (case / f"{start_label:g}").is_dir() or (
            case / f"{time_before:g}"
        ).is_dir()

        checks = {
            "stored_mass_continuous": bool(jump <= RESTART_MASS_CONTINUITY_TOL),
            "seam_times_match": bool(times_match),
            "start_from_latest_time": start_from_latest,
            "recorded_as_continuation": bool(recorded),
            "restart_state_present": bool(saved_state),
        }
        seams.append(
            {
                "classification": RESTART_BOUNDARY,
                "seam_time": time_after,
                "from_segment": index - 1,
                "to_segment": index,
                "mass_before_restart": mass_before,
                "mass_after_restart": mass_after,
                "absolute_mass_jump": float(mass_after - mass_before),
                "relative_mass_jump": float(jump),
                "tolerance": RESTART_MASS_CONTINUITY_TOL,
                "checks": checks,
                "continuous": all(checks.values()),
                "fields_reinitialized": not (
                    checks["stored_mass_continuous"]
                    and checks["start_from_latest_time"]
                ),
            }
        )

    return {
        "seam_count": len(seams),
        "seams": seams,
        "all_seams_continuous": all(s["continuous"] for s in seams),
        "controlDict_start_from_latest_time": start_from_latest,
        "basis": (
            "A restart boundary is excluded from the physical conservation "
            "statistics only when the stored mass, the restart directive, the "
            "executor record and the saved state all agree that the same "
            "solution was continued."
        ),
    }


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
        "warnings": collect_warnings(log),
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

    # Segment-aware monitor history. The seam records are kept rather than
    # collapsed, so the restart can be verified from both sides of it.
    mass_segments = _monitor_segments(case, "mass")
    mass, mass_labels = _monitor_concatenated(case, "mass")
    fluxes = {}
    for patch in FLUX_PATCHES:
        table, labels = _monitor_concatenated(case, "flux_" + patch)
        if not np.array_equal(table[:, 0], mass[:, 0]) or not np.array_equal(
            labels, mass_labels
        ):
            raise ValueError(f"Monitor segments differ for flux_{patch}")
        fluxes[patch] = table[:, 1]

    balance, balance_table = transient_balance(
        mass[:, 0], mass[:, 1], fluxes, segments=mass_labels
    )
    result["mass"] = select_conservation_basis(
        balance, restart_continuity(case, mass_segments, execution)
    )
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
    # is_restart_boundary is appended last so existing column positions are
    # unchanged for anything already reading this file.
    np.savetxt(
        out / "transient_mass.csv",
        balance_table,
        delimiter=",",
        header=(
            "time,mass,net_outward_flux,residual,relative_residual,"
            "cumulative_defect,is_restart_boundary"
        ),
        comments="",
    )
    # The seam measurements again, named rather than flagged, so a reviewer
    # can read what happened at each restart without decoding a column.
    seam_lines = [
        "time,from_segment,to_segment,mass_before_restart,mass_after_restart,"
        "mass_jump_across_seam,naive_deduplicated_relative_residual,classification"
    ]
    for seam in result["mass"].get("restart_boundaries", []):
        naive = seam.get("naive_deduplicated_relative_residual")
        seam_lines.append(
            f"{seam['time']:.18e},{seam['from_segment']},{seam['to_segment']},"
            f"{seam['mass_before_restart']:.18e},"
            f"{seam['mass_after_restart']:.18e},"
            f"{seam['mass_jump_across_seam']:.18e},"
            + (f"{naive:.18e}," if naive is not None else "nan,")
            + f"{seam['classification']}"
        )
    (out / "restart_boundaries.csv").write_text("\n".join(seam_lines) + "\n")
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
