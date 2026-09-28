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
    """Write a status file with repository-relative paths."""
    from src.reporting.report_builder import relativise

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(relativise(payload), indent=2, default=str) + "\n",
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

    # -- family-specific physics plots, from archived series only ------
    written += _physics_plots(run, out_dir, plt, missing)

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


#: Names the original pipeline gave its rendered fields, mapped to ours.
_FIELD_ALIASES = {
    "mach_field": "mach", "Mach_field": "mach",
    "p_field": "pressure", "pressure_field": "pressure",
    "T_field": "temperature", "temperature_field": "temperature",
    "rho_field": "density", "speed_field": "velocity",
    "shock_density_contours": "shock_density",
    "mesh_cells": "mesh",
}


def _archived_contours(run: Any, out_dir: Path) -> List[str]:
    """Copy field images the original pipeline already rendered.

    These are archived renders, not something produced now, and the status file
    says so. They are real output of the recorded run; nothing is re-coloured,
    re-scaled or synthesised.
    """
    root = (run.artifacts or {}).get("evidence_root")
    if not root:
        return []
    roots = [Path(root)]
    # A campaign directory often holds the rendered visuals for the same case.
    case_meta = (run.artifacts or {}).get("case") or {}
    for related in case_meta.get("related_campaigns", []) or []:
        roots.append(Path(related))
    # The tracked artifact directory for this case. It holds the same archived
    # renders and, unlike the large demo/ archive, it ships with the repository
    # -- so a clone reproduces the same media as the development tree.
    case_dir = case_meta.get("case_dir")
    if case_dir:
        parts = Path(case_dir).parts
        if len(parts) >= 2:
            tracked = Path("evidence") / parts[-2] / parts[-1]
            if (tracked / "contours").is_dir():
                roots.append(tracked)
    candidates: List[Path] = []
    for base in roots:
        if not base.exists():
            continue
        for pattern in ("iteration_*/figures/*.png", "visuals/iteration_*/*.png",
                        "figures/*.png", "contours/*.png"):
            candidates.extend(sorted(base.glob(pattern)))
    if not candidates:
        return []
    # Prefer the LAST iteration when a case iterated.
    chosen: Dict[str, Path] = {}
    for path in candidates:
        label = _FIELD_ALIASES.get(path.stem, path.stem)
        chosen[label] = path            # later paths sort last, so they win
    written = []
    for label, path in sorted(chosen.items()):
        target = out_dir / f"{label}.png"
        target.write_bytes(path.read_bytes())
        written.append(target.name)
    _record(out_dir / "contours_status.json", {
        "visuals_version": VISUALS_VERSION,
        "status": "ARCHIVED_RENDERS",
        "written": written,
        "source": [str(r) for r in roots],
        "note": ("these images were rendered by the original run's own "
                 "visualisation step and are copied verbatim. They are not "
                 "re-rendered here, and nothing was synthesised."),
    })
    return written


#: Reported when a case's archive was compacted: the post-processed series and
#: logs survived, the raw field time directories did not, so there is nothing to
#: contour and nothing is invented in their place.
FLOW_CONTOURS_NOT_AVAILABLE = "FLOW_CONTOURS_NOT_AVAILABLE_FROM_COMPACT_ARCHIVE"


def make_contours(run: Any, out_dir: Path) -> List[str]:
    """Render field contours. Requires field data AND a renderer; says which."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    archived = _archived_contours(run, out_dir)
    if archived:
        return archived
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
        status["status"] = FLOW_CONTOURS_NOT_AVAILABLE
        status["reason"] = (
            "the archived evidence carries post-processed series and logs but no "
            "reconstructed field time directories, so there is nothing to "
            "contour. Re-run the case live to produce fields.")
        status["what_exists_instead"] = (
            "time-resolved integral series (forces, probes, fluxes) and the "
            "solver logs; those are plotted and animated, and they are not "
            "flow-field visualisations")
        status["not_done"] = ("no flow field was synthesised, interpolated or "
                              "stood in for the missing time directories")
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


def make_history_video(run: Any, out_dir: Path) -> Optional[str]:
    """Animate what genuinely evolves. Never invent time for a steady solver."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    contract = ((run.artifacts or {}).get("contract") or {}).get("capabilities", {})
    transient = bool((contract.get("physics") or {}).get("transient"))
    samples = _force_samples(run)
    status: Dict[str, Any] = {"visuals_version": VISUALS_VERSION,
                              "status": NOT_AVAILABLE,
                              "transient_family": transient}

    series_label = "force"
    if not samples:
        # A transient family without forces may still have a time-resolved
        # front history. Animate that, and say which quantity it is.
        root = (run.artifacts or {}).get("evidence_root")
        shock = (next(iter(sorted(Path(root).rglob(
            "shock_front_history.csv"))), None) if root else None)
        if shock is not None:
            header, rows = _csv(shock)
            index = {name: i for i, name in enumerate(header)}
            if rows and "time" in index and "lower_front_x" in index:
                samples = [{"t": r[index["time"]],
                            "fx": r[index["lower_front_x"]],
                            "fy": 0.0,
                            "fz": r[index.get("upper_stem_x", index["lower_front_x"])]}
                           for r in rows]
                series_label = "shock front"
    if not samples:
        # Compact tracked evidence may retain the genuine historical animation
        # but not its source CSV. Preserve it only when its manifest explicitly
        # identifies it as a history, never as a field movie.
        from src.reporting.report_builder import REPO_ROOT
        case_dir = ((run.artifacts or {}).get('case') or {}).get('case_dir')
        if case_dir:
            parts = Path(case_dir).parts
            archived = REPO_ROOT / 'evidence' / parts[-2] / parts[-1] / 'video'
            try:
                old = json.loads((archived/'video_status.json').read_text())
                if old.get('is_flow_field_animation') is False and (archived/'simulation.mp4').is_file():
                    shutil.copyfile(archived/'simulation.mp4', out_dir/'history_evolution.mp4')
                    old.update(file='history_evolution.mp4', source='tracked archived history animation',
                               status='ARCHIVED_HISTORY', is_flow_field_animation=False)
                    _record(out_dir/'history_status.json',old)
                    return 'history_evolution.mp4'
            except (OSError, ValueError, IndexError):
                pass
        status["reason"] = (
            "no time-resolved series is archived for this case, so there is "
            "nothing to animate. A steady solver never receives a fabricated "
            "time evolution here.")
        _record(out_dir / "history_status.json", status)
        return None

    try:
        plt = _matplotlib()
        import matplotlib.animation as animation
    except Exception as exc:                        # noqa: BLE001
        status["reason"] = f"matplotlib unavailable: {exc}"
        _record(out_dir / "history_status.json", status)
        return None

    times = [s["t"] for s in samples]
    fz = [s["fz"] for s in samples]
    fx = [s["fx"] for s in samples]
    label = ("SOLVER TIME (transient run)" if transient
             else "ITERATION HISTORY — not physical time (steady solver)")
    # Name the quantity in the label too: this is an integral-series animation,
    # never a flow-field movie. The distinction is the whole point.
    quantity_note = ("integral force history" if series_label == "force"
                     else f"{series_label} history")

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(8, 5), sharex=True)
    ax1.set_xlim(min(times), max(times))
    ax1.set_ylim(min(fx) * 0.98, max(fx) * 1.02)
    ax2.set_xlim(min(times), max(times))
    ax2.set_ylim(min(fz) * 1.1, max(fz) * 1.1)
    ax1.set_ylabel("streamwise $F_x$" if series_label == "force"
                   else "lower shock front x")
    ax2.set_ylabel("lateral $F_z$" if series_label == "force"
                   else "upper stem x")
    ax2.set_xlabel(label)
    line1, = ax1.plot([], [], lw=0.9)
    line2, = ax2.plot([], [], lw=0.9, color="crimson")
    title = ax1.set_title("")

    step = max(1, len(times) // 200)
    frames = sorted(set([1, *range(step, len(times), step), len(times)]))

    def update(index: int):
        line1.set_data(times[:index], fx[:index])
        line2.set_data(times[:index], fz[:index])
        title.set_text(f"{run.family}/{run.case} — {quantity_note} — {label} — "
                       f"t = {times[index-1]:.2f}")
        return line1, line2, title

    anim = animation.FuncAnimation(fig, update, frames=frames, blit=False)
    target = out_dir / "history_evolution.mp4"
    encoder = shutil.which("ffmpeg")
    if not encoder:
        try:
            import imageio_ffmpeg
            encoder = imageio_ffmpeg.get_ffmpeg_exe()
        except ImportError:
            pass
    writer = "ffmpeg" if encoder else None
    try:
        if writer:
            plt.rcParams['animation.ffmpeg_path'] = encoder
            anim.save(target, writer=writer, fps=25, dpi=120)
            name = target.name
        else:
            target = out_dir / "history_evolution.gif"
            anim.save(target, writer="pillow", fps=20, dpi=100)
            name = target.name
        status.update({"status": "RENDERED", "file": name, "represents": label,
                       "quantity": series_label,
                       "is_flow_field_animation": False,
                       "note": (f"this animates the {quantity_note} written by "
                                "the solver's function objects. It is NOT a "
                                "flow-field visualisation, and no flow field "
                                "was fabricated."),
                       "frames": len(frames)})
    except Exception as exc:                        # noqa: BLE001 - reported
        status["reason"] = f"animation failed: {type(exc).__name__}: {exc}"
        name = None
    finally:
        plt.close(fig)
    _record(out_dir / "history_status.json", status)
    return name if status["status"] == "RENDERED" else None


def _csv(path: Path):
    """Read a numeric CSV with a header row. Returns (columns, rows)."""
    lines = [ln for ln in path.read_text().splitlines() if ln.strip()]
    if len(lines) < 2:
        return [], []
    header = [h.strip() for h in lines[0].split(",")]
    rows = []
    for line in lines[1:]:
        try:
            rows.append([float(v) for v in line.split(",")])
        except ValueError:
            continue
    return header, rows


def _physics_plots(run: Any, out_dir: Path, plt, missing: List[str]) -> List[str]:
    """Plots that only make sense for one family, drawn from what exists."""
    root = (run.artifacts or {}).get("evidence_root")
    if not root:
        return []
    root = Path(root)
    written: List[str] = []
    family = run.family or ""

    if family == "nozzle":
        path = root / "axial_profile.csv"
        if not path.exists():
            missing.append("axial_profile: not in the archived evidence")
            return written
        header, rows = _csv(path)
        if not rows:
            return written
        index = {name: i for i, name in enumerate(header)}
        x = [r[index["x_m"]] for r in rows]
        fig, axes = plt.subplots(3, 1, figsize=(9, 8), sharex=True)
        for ax, key, label in ((axes[0], "Mach", "Mach number"),
                               (axes[1], "p_Pa", "pressure [Pa]"),
                               (axes[2], "T_K", "temperature [K]")):
            if key in index:
                ax.plot(x, [r[index[key]] for r in rows], lw=1.3)
                ax.set_ylabel(label)
                ax.grid(alpha=0.3)
        axes[0].set_title(f"{family}/{run.case}: axial profile "
                          "(archived solver output, steady solution)")
        axes[-1].set_xlabel("axial position [m]")
        fig.tight_layout()
        fig.savefig(out_dir / "physics_specific_axial_profile.png", dpi=140)
        plt.close(fig)
        written.append("physics_specific_axial_profile.png")

    if family == "forward_step_2d":
        shock = next(iter(sorted(root.glob("iteration_*/shock_front_history.csv"))),
                     None)
        if shock is not None:
            header, rows = _csv(shock)
            index = {name: i for i, name in enumerate(header)}
            if rows and "time" in index:
                t = [r[index["time"]] for r in rows]
                fig, ax = plt.subplots(figsize=(9, 4))
                for key, label in (("lower_front_x", "lower shock front"),
                                   ("upper_stem_x", "upper stem")):
                    if key in index:
                        ax.plot(t, [r[index[key]] for r in rows], lw=1.2,
                                marker="o", ms=2.5, label=label)
                ax.set_xlabel("solver time")
                ax.set_ylabel("x position")
                ax.set_title(f"{family}/{run.case}: shock-front history "
                             "(archived solver output)")
                ax.legend(fontsize=8)
                ax.grid(alpha=0.3)
                fig.tight_layout()
                fig.savefig(out_dir / "physics_specific_shock_front.png", dpi=140)
                plt.close(fig)
                written.append("physics_specific_shock_front.png")
        mass = next(iter(sorted(root.glob("iteration_*/transient_mass.csv"))), None)
        if mass is not None:
            header, rows = _csv(mass)
            index = {name: i for i, name in enumerate(header)}
            if rows and "relative_residual" in index:
                t = [r[index["time"]] for r in rows]
                fig, ax = plt.subplots(figsize=(9, 3.6))
                ax.semilogy(t, [abs(r[index["relative_residual"]]) or 1e-300
                                for r in rows], lw=0.9)
                ax.set_xlabel("solver time")
                ax.set_ylabel("|relative mass residual|")
                ax.set_title("Transient mass closure (archived solver output)")
                ax.grid(True, which="both", alpha=0.3)
                fig.tight_layout()
                fig.savefig(out_dir / "conservation.png", dpi=140)
                plt.close(fig)
                written.append("conservation.png")
    return written


# Compatibility API: this produces only an explicitly named history animation.
make_video = make_history_video
