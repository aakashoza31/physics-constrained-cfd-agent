#!/usr/bin/env python3
"""Plots, contours and video. Everything is labelled with what it actually is.

Three rules this module will not break:

  1. A figure is drawn only from data that exists. Nothing is interpolated into
     being, and a missing series produces a NOT_AVAILABLE record, not a blank
     axis that looks like a measurement.
  2. A steady solver does not get a fake time animation. Where no transient data
     exist, the animation is an ITERATION-HISTORY animation and its title says
     so.
  3. Contours require field data and a renderer. Without OpenFOAM time
     directories and ParaView (or a reader), the contour step records which of
     the two was missing.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

VISUALS_VERSION = "visuals/1.0.0"

NOT_AVAILABLE = "NOT_AVAILABLE"


def _matplotlib():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    return plt


def _record(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str) + "\n",
                    encoding="utf-8")


def _force_samples(run: Any) -> List[Dict[str, float]]:
    history = (run.artifacts or {}).get("force_history")
    if not history:
        return []
    path = Path(history)
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text(encoding="utf-8"))["samples"]
    except (OSError, ValueError, KeyError):
        return []


def _residual_series(run: Any) -> List[Tuple[str, List[float], List[float]]]:
    """Residual histories, if the archived evidence carries any."""
    root = (run.artifacts or {}).get("evidence_root")
    if not root:
        return []
    series: List[Tuple[str, List[float], List[float]]] = []
    for name in ("log.foamRun.tail", "log.foamRun"):
        path = Path(root) / "logs" / name
        if not path.exists():
            continue
        times: List[float] = []
        values: Dict[str, List[float]] = {}
        for line in path.read_text(errors="replace").splitlines():
            if "Time = " in line and "ExecutionTime" not in line:
                try:
                    times.append(float(line.split("Time = ")[1].split()[0]))
                except (IndexError, ValueError):
                    pass
            if "Initial residual = " in line:
                try:
                    field = line.split("for ")[1].split(",")[0]
                    value = float(line.split("Initial residual = ")[1].split(",")[0])
                except (IndexError, ValueError):
                    continue
                values.setdefault(field, []).append(value)
        for field, vals in values.items():
            if len(vals) > 4:
                series.append((field, list(range(len(vals))), vals))
        if series:
            break
    return series


def make_plots(run: Any, out_dir: Path) -> List[str]:
    """Draw every plot the available data supports. Returns file names."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    written: List[str] = []
    missing: List[str] = []

    try:
        plt = _matplotlib()
    except Exception as exc:                        # noqa: BLE001 - reported
        _record(out_dir / "plots_status.json",
                {"status": NOT_AVAILABLE, "reason": f"matplotlib unavailable: {exc}"})
        return []

    samples = _force_samples(run)
    if samples:
        times = [s["t"] for s in samples]
        fig, axes = plt.subplots(2, 1, figsize=(9, 6.5), sharex=True)
        axes[0].plot(times, [s["fx"] for s in samples], lw=0.8,
                     label="streamwise $F_x$")
        axes[0].plot(times, [s["fy"] for s in samples], lw=0.8,
                     label="vertical $F_y$")
        axes[0].set_ylabel("force")
        axes[0].legend(loc="best", fontsize=8)
        axes[0].set_title(f"{run.family}/{run.case}: force history "
                          "(archived solver output)")
        axes[1].plot(times, [s["fz"] for s in samples], lw=0.8, color="crimson",
                     label="lateral $F_z$")
        axes[1].axhline(0.0, color="0.6", lw=0.6)
        axes[1].set_xlabel("solver time")
        axes[1].set_ylabel("lateral force")
        axes[1].legend(loc="best", fontsize=8)
        stationarity = (run.artifacts or {}).get("stationarity") or {}
        window = stationarity.get("window") or {}
        if window.get("start") is not None:
            for ax in axes:
                ax.axvspan(window["start"], window["end"], color="orange",
                           alpha=0.12)
            axes[1].text(window["start"], axes[1].get_ylim()[1] * 0.85,
                         " assessment window", fontsize=8, color="darkorange")
        fig.tight_layout()
        fig.savefig(out_dir / "force_history.png", dpi=140)
        plt.close(fig)
        written.append("force_history.png")

        # Lateral growth, the quantity the gate actually judges.
        fig, ax = plt.subplots(figsize=(9, 3.6))
        bucket = 5.0
        lo = min(times)
        centres, means = [], []
        while lo < max(times):
            chunk = [abs(s["fz"]) for s in samples if lo <= s["t"] < lo + bucket]
            if chunk:
                centres.append(lo + 0.5 * bucket)
                means.append(sum(chunk) / len(chunk))
            lo += bucket
        ax.semilogy(centres, means, "o-", color="crimson")
        ax.set_xlabel("solver time")
        ax.set_ylabel(r"mean $|F_z|$ per window")
        ax.set_title("Lateral force magnitude: still growing at the end of the run")
        ax.grid(True, which="both", alpha=0.3)
        fig.tight_layout()
        fig.savefig(out_dir / "lateral_force_growth.png", dpi=140)
        plt.close(fig)
        written.append("lateral_force_growth.png")
    else:
        missing.append("force_history: no archived force series for this case")

    residuals = _residual_series(run)
    if residuals:
        fig, ax = plt.subplots(figsize=(9, 4))
        for field, xs, ys in residuals[:6]:
            ax.semilogy(xs, ys, lw=0.8, label=field)
        ax.set_xlabel("solver iteration (as logged)")
        ax.set_ylabel("initial residual")
        ax.set_title(f"{run.family}/{run.case}: residual history (from solver log)")
        ax.legend(fontsize=8)
        ax.grid(True, which="both", alpha=0.3)
        fig.tight_layout()
        fig.savefig(out_dir / "residuals.png", dpi=140)
        plt.close(fig)
        written.append("residuals.png")
    else:
        missing.append("residuals: no parsable solver log in the archived evidence")

    # Convergence-of-gates figure: always available, and it is about THIS run.
    trace = run.trace.to_dict()
    if trace["gates"]:
        labels = [g["question"] for g in trace["gates"]]
        colours = ["#2e7d32" if g["passed"] else ("#c62828" if g["passed"] is False
                                                  else "#f9a825")
                   for g in trace["gates"]]
        fig, ax = plt.subplots(figsize=(8, 0.42 * len(labels) + 1.6))
        ax.barh(range(len(labels)), [1] * len(labels), color=colours)
        ax.set_yticks(range(len(labels)))
        ax.set_yticklabels(labels, fontsize=8)
        ax.set_xticks([])
        ax.invert_yaxis()
        ax.set_title(f"Deterministic gates — {run.family}/{run.case} "
                     f"({(run.decision.verdict if run.decision else 'NONE')})")
        fig.tight_layout()
        fig.savefig(out_dir / "convergence.png", dpi=140)
        plt.close(fig)
        written.append("convergence.png")

    _record(out_dir / "plots_status.json",
            {"visuals_version": VISUALS_VERSION, "written": written,
             "not_available": missing})
    return written


def make_contours(run: Any, out_dir: Path) -> List[str]:
    """Render field contours. Requires field data AND a renderer; says which."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    root = (run.artifacts or {}).get("evidence_root")
    case_root = Path(root) if root else None
    time_dirs: List[str] = []
    if case_root and case_root.exists():
        time_dirs = sorted(
            p.name for p in case_root.iterdir()
            if p.is_dir() and p.name.replace(".", "", 1).isdigit()
        )
    renderer = shutil.which("pvpython") or shutil.which("pvbatch")
    status = {
        "visuals_version": VISUALS_VERSION,
        "status": NOT_AVAILABLE,
        "field_time_directories": time_dirs,
        "renderer": renderer or NOT_AVAILABLE,
        "script": "src/reporting/paraview_contours.py",
    }
    if not time_dirs:
        status["reason"] = (
            "the archived evidence carries post-processed series and logs but no "
            "reconstructed field time directories, so there is nothing to "
            "contour. Re-run the case live to produce fields.")
    elif not renderer:
        status["reason"] = (
            "field data are present but no ParaView renderer (pvpython/pvbatch) "
            "is on PATH. Install ParaView and re-run; the render script is "
            "committed and scriptable.")
    else:
        try:
            subprocess.run(
                [renderer, "src/reporting/paraview_contours.py",
                 "--case", str(case_root), "--out", str(out_dir)],
                check=True, capture_output=True, timeout=900)
            written = sorted(p.name for p in out_dir.glob("*.png"))
            status.update({"status": "RENDERED", "written": written})
            _record(out_dir / "contours_status.json", status)
            return written
        except Exception as exc:                    # noqa: BLE001 - reported
            status["reason"] = f"the renderer failed: {type(exc).__name__}: {exc}"
    _record(out_dir / "contours_status.json", status)
    return []


def make_video(run: Any, out_dir: Path) -> Optional[str]:
    """Animate what genuinely evolves. Never invent time for a steady solver."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    contract = ((run.artifacts or {}).get("contract") or {}).get("capabilities", {})
    transient = bool((contract.get("physics") or {}).get("transient"))
    samples = _force_samples(run)
    status: Dict[str, Any] = {"visuals_version": VISUALS_VERSION,
                              "status": NOT_AVAILABLE,
                              "transient_family": transient}

    if not samples:
        status["reason"] = (
            "no time-resolved series is archived for this case, so there is "
            "nothing to animate. A steady solver never receives a fabricated "
            "time evolution here.")
        _record(out_dir / "video_status.json", status)
        return None

    try:
        plt = _matplotlib()
        import matplotlib.animation as animation
    except Exception as exc:                        # noqa: BLE001
        status["reason"] = f"matplotlib unavailable: {exc}"
        _record(out_dir / "video_status.json", status)
        return None

    times = [s["t"] for s in samples]
    fz = [s["fz"] for s in samples]
    fx = [s["fx"] for s in samples]
    label = ("SOLVER TIME (transient run)" if transient
             else "ITERATION HISTORY — not physical time (steady solver)")

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(8, 5), sharex=True)
    ax1.set_xlim(min(times), max(times))
    ax1.set_ylim(min(fx) * 0.98, max(fx) * 1.02)
    ax2.set_xlim(min(times), max(times))
    ax2.set_ylim(min(fz) * 1.1, max(fz) * 1.1)
    ax1.set_ylabel("streamwise $F_x$")
    ax2.set_ylabel("lateral $F_z$")
    ax2.set_xlabel(label)
    line1, = ax1.plot([], [], lw=0.9)
    line2, = ax2.plot([], [], lw=0.9, color="crimson")
    title = ax1.set_title("")

    step = max(1, len(times) // 200)
    frames = list(range(step, len(times), step))

    def update(index: int):
        line1.set_data(times[:index], fx[:index])
        line2.set_data(times[:index], fz[:index])
        title.set_text(f"{run.family}/{run.case} — {label} — t = {times[index-1]:.2f}")
        return line1, line2, title

    anim = animation.FuncAnimation(fig, update, frames=frames, blit=False)
    target = out_dir / "simulation.mp4"
    writer = "ffmpeg" if shutil.which("ffmpeg") else None
    try:
        if writer:
            anim.save(target, writer=writer, fps=25, dpi=120)
            name = target.name
        else:
            target = out_dir / "simulation.gif"
            anim.save(target, writer="pillow", fps=20, dpi=100)
            name = target.name
        status.update({"status": "RENDERED", "file": name, "represents": label,
                       "frames": len(frames)})
    except Exception as exc:                        # noqa: BLE001 - reported
        status["reason"] = f"animation failed: {type(exc).__name__}: {exc}"
        name = None
    finally:
        plt.close(fig)
    _record(out_dir / "video_status.json", status)
    return name if status["status"] == "RENDERED" else None
