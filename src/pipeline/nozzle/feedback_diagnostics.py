"""Theory-blind numerical and visual diagnostics for closed-loop nozzle control.

These diagnostics do not decide acceptance.  They expose measured gradients,
mesh resolution, native-field images, and iteration trends so the LLM can form
and test hypotheses while deterministic validators retain authority.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

import numpy as np

from src.contracts.cfd_evidence import CFDEvidence
from src.reasoning.evidence_packet import FORBIDDEN_THEORY_KEYS
from src.pipeline.nozzle.spec import NozzleCaseSpec


REGION_NAMES = ("inlet", "converging", "throat", "diverging", "outlet")


def _reasoning_safe_copy(obj: Any) -> Any:
    """Copy measured diagnostics while stripping keys forbidden in LLM evidence.

    Raw diagnostic artifacts may carry provenance markers such as
    ``theory_blind``.  The repository's fail-closed guard intentionally rejects
    any key containing theory/reference tokens, so those bookkeeping keys must
    not be embedded inside the autonomous reasoning packet.  Values are not
    altered and raw artifacts remain unchanged on disk.
    """
    if isinstance(obj, dict):
        safe: Dict[str, Any] = {}
        for key, value in obj.items():
            key_lower = str(key).lower()
            if any(token in key_lower for token in FORBIDDEN_THEORY_KEYS):
                continue
            safe[str(key)] = _reasoning_safe_copy(value)
        return safe
    if isinstance(obj, list):
        return [_reasoning_safe_copy(v) for v in obj]
    if isinstance(obj, tuple):
        return tuple(_reasoning_safe_copy(v) for v in obj)
    return obj


def _region_at(x: float, spec: NozzleCaseSpec) -> str:
    edges = spec.axial_breakpoints_m
    for i, name in enumerate(REGION_NAMES):
        if x <= edges[i + 1] + 1e-12:
            return name
    return "outlet"


def analyze_axial_profile(
    profile_path: Path,
    spec: NozzleCaseSpec,
    *,
    mesh_cells: Optional[int] = None,
) -> Dict[str, Any]:
    data = np.loadtxt(profile_path, delimiter=",", skiprows=1)
    if data.ndim == 1:
        data = data.reshape(1, -1)
    if data.shape[0] < 3 or data.shape[1] < 5:
        raise ValueError("axial profile is too small for gradient diagnostics")

    x, p, T, U, M = [data[:, i] for i in range(5)]
    xm = 0.5 * (x[:-1] + x[1:])

    def rel_jump(values: np.ndarray) -> np.ndarray:
        denom = np.maximum(0.5 * (np.abs(values[:-1]) + np.abs(values[1:])), 1e-12)
        return np.abs(np.diff(values)) / denom

    metrics = {
        "mach_abs_cell_jump": np.abs(np.diff(M)),
        "pressure_relative_cell_jump": rel_jump(p),
        "temperature_relative_cell_jump": rel_jump(T),
        "velocity_relative_cell_jump": rel_jump(U),
    }

    maxima: Dict[str, Any] = {}
    for name, values in metrics.items():
        idx = int(np.argmax(values))
        maxima[name] = {
            "value": float(values[idx]),
            "x_m": float(xm[idx]),
            "region": _region_at(float(xm[idx]), spec),
        }

    # Dimensionless score used only to rank where more resolution might be
    # useful.  It is not an acceptance criterion and never overrides validate.py.
    score = np.maximum.reduce(
        [
            metrics["mach_abs_cell_jump"] / 0.05,
            metrics["pressure_relative_cell_jump"] / 0.03,
            metrics["temperature_relative_cell_jump"] / 0.02,
            metrics["velocity_relative_cell_jump"] / 0.03,
        ]
    )
    idx = int(np.argmax(score))
    strongest_region = _region_at(float(xm[idx]), spec)

    cells = int(mesh_cells) if mesh_cells is not None else None
    canonical_cells = 2112
    locally_sharp = bool(
        maxima["mach_abs_cell_jump"]["value"] > 0.08
        or maxima["pressure_relative_cell_jump"]["value"] > 0.06
        or maxima["temperature_relative_cell_jump"]["value"] > 0.04
        or maxima["velocity_relative_cell_jump"]["value"] > 0.06
    )
    coarse_vs_reference = cells is not None and cells < canonical_cells

    candidates = [strongest_region] if (locally_sharp and coarse_vs_reference) else []

    return {
        "strongest_gradient_region": strongest_region,
        "strongest_gradient_x_m": float(xm[idx]),
        "strongest_dimensionless_jump_score": float(score[idx]),
        "field_gradient_maxima": maxima,
        "candidate_underresolved_regions": candidates,
        "candidate_rule": (
            "A region is only flagged when measured cell-to-cell variation is "
            "sharp and the mesh is coarser than the validated 2112-cell baseline. "
            "This is an action-support heuristic, not a CFD acceptance test."
        ),
        "mesh_cells": cells,
        "canonical_baseline_cells": canonical_cells,
        "profile_rows": int(data.shape[0]),
        "theory_blind": True,
    }


def render_native_field_images(
    snapshot_csv: Path,
    output_dir: Path,
) -> Dict[str, str]:
    """Render actual latest-time cell-centre fields using matplotlib.

    The wedge is mirrored around the axis for readability.  Pixels come from
    native OpenFOAM cell values; no analytical reference field is drawn.
    """
    try:
        import matplotlib.pyplot as plt
    except Exception as exc:  # pragma: no cover - optional dependency
        return {"error": f"matplotlib unavailable: {type(exc).__name__}: {exc}"}

    data = np.loadtxt(snapshot_csv, delimiter=",", skiprows=1)
    if data.ndim == 1:
        data = data.reshape(1, -1)
    if data.shape[1] < 10:
        raise ValueError("feedback snapshot has unexpected columns")

    x = data[:, 0]
    r = data[:, 1]
    p = data[:, 2]
    T = data[:, 3]
    speed = data[:, 8]
    mach = data[:, 9]

    output_dir.mkdir(parents=True, exist_ok=True)
    images: Dict[str, str] = {}

    def field_image(key: str, values: np.ndarray, title: str, units: str) -> None:
        fig, ax = plt.subplots(figsize=(10, 3.8))
        xx = np.concatenate([x, x])
        rr = np.concatenate([r, -r])
        vv = np.concatenate([values, values])
        sc = ax.scatter(xx, rr, c=vv, s=14, marker="s", linewidths=0)
        ax.set_xlabel("x [m]")
        ax.set_ylabel("radius [m]")
        ax.set_title(title)
        ax.set_xlim(float(np.min(x)), float(np.max(x)))
        ax.set_ylim(-1.05 * float(np.max(r)), 1.05 * float(np.max(r)))
        cb = fig.colorbar(sc, ax=ax)
        cb.set_label(units)
        fig.tight_layout()
        path = output_dir / f"{key}.png"
        fig.savefig(path, dpi=160)
        plt.close(fig)
        images[key] = str(path)

    field_image("mach_field", mach, "Latest OpenFOAM Mach field", "Mach")
    field_image("pressure_field", p, "Latest OpenFOAM static-pressure field", "Pa")
    field_image("temperature_field", T, "Latest OpenFOAM temperature field", "K")
    field_image("speed_field", speed, "Latest OpenFOAM speed field", "m/s")

    fig, ax = plt.subplots(figsize=(10, 3.8))
    ax.scatter(np.concatenate([x, x]), np.concatenate([r, -r]), s=5)
    ax.set_xlabel("x [m]")
    ax.set_ylabel("radius [m]")
    ax.set_title("Structured cell-centre distribution")
    ax.set_xlim(float(np.min(x)), float(np.max(x)))
    ax.set_ylim(-1.05 * float(np.max(r)), 1.05 * float(np.max(r)))
    fig.tight_layout()
    path = output_dir / "mesh_cells.png"
    fig.savefig(path, dpi=160)
    plt.close(fig)
    images["mesh_cells"] = str(path)

    return images



def fulfill_diagnostic_request(
    request: str,
    *,
    validation: Dict[str, Any],
    execution: Dict[str, Any],
    mesh: Dict[str, Any],
    profile_diagnostics: Dict[str, Any],
    visual_observation: Dict[str, Any],
) -> Dict[str, Any]:
    """Return a theory-blind diagnostic response from already measured data.

    REQUEST_DIAGNOSTIC is an observation action, not permission to invent new
    physics.  The agent receives a focused view plus the full standard bundle.
    """
    text = (request or "").lower()
    final = validation.get("final", {})
    focused: Dict[str, Any] = {}

    if any(word in text for word in ("time", "timestep", "courant", "dt")):
        focused["time_integration"] = {
            "execution_status": execution.get("status"),
            "execution_last_observed_time_s": execution.get("last_observed_time"),
            "monitor_last_time_s": validation.get("monitor_last_time_s"),
            "requested_end_time_s": validation.get("requested_end_time_s"),
            "final_dt_s": validation.get("final_dt"),
            "median_dt_last_100_s": validation.get("median_dt_last_100"),
            "max_courant": validation.get("max_Co"),
        }

    if any(word in text for word in ("station", "converg", "drift", "steady")):
        focused["stationarity"] = {
            "monitor_drift_fraction": validation.get("drift_fraction_last_2ms", {}),
            "field_l2_change": validation.get("field_L2_change_last_2ms", {}),
            "passes_monitors": validation.get("checks", {}).get("monitors_stationary"),
            "passes_fields": validation.get("checks", {}).get("fields_stationary"),
        }

    if any(word in text for word in ("mass", "conserv", "continuity", "flux")):
        focused["conservation"] = {
            "inlet_mdot_kg_s": final.get("inlet_mdot"),
            "outlet_mdot_kg_s": final.get("outlet_mdot"),
            "boundary_mismatch_pct": final.get("boundary_mismatch_pct"),
            "max_window_mismatch_pct": final.get("max_window_mismatch_pct"),
            "max_transient_continuity_pct": validation.get("max_transient_continuity_pct"),
        }

    if any(word in text for word in ("mesh", "gradient", "resolution", "throat", "shock")):
        focused["mesh_and_gradients"] = {
            "mesh": mesh,
            "profile_diagnostics": profile_diagnostics,
        }

    if any(word in text for word in ("visual", "image", "contour", "field")):
        focused["visual"] = _without_provenance(visual_observation)

    if not focused:
        focused["standard_bundle"] = {
            "failed_checks": [k for k, v in validation.get("checks", {}).items() if not v and k != "theory_consistency"],
            "time": {
                "last_observed_time_s": execution.get("last_observed_time"),
                "monitor_last_time_s": validation.get("monitor_last_time_s"),
                "requested_end_time_s": validation.get("requested_end_time_s"),
                "median_dt_last_100_s": validation.get("median_dt_last_100"),
            },
            "stationarity": validation.get("drift_fraction_last_2ms", {}),
            "field_l2": validation.get("field_L2_change_last_2ms", {}),
            "conservation": {
                "max_window_mismatch_pct": final.get("max_window_mismatch_pct"),
                "max_transient_continuity_pct": validation.get("max_transient_continuity_pct"),
            },
            "mesh_and_gradients": profile_diagnostics,
            "visual": _without_provenance(visual_observation),
        }

    return {
        "requested_diagnostic": request,
        "focused_result": focused,
        "source": "deterministic measured evidence + qualitative image observation",
        "theory_blind": True,
    }

def augment_evidence(
    evidence: CFDEvidence,
    *,
    profile_diagnostics: Dict[str, Any],
    image_paths: Dict[str, str],
    visual_observation: Dict[str, Any],
    diagnostic_request: Optional[str] = None,
    diagnostic_result: Optional[Dict[str, Any]] = None,
) -> CFDEvidence:
    # Keep the complete raw diagnostics on disk, but only place a guard-safe
    # copy in the LLM evidence packet.  In particular, raw artifacts contain a
    # provenance key named ``theory_blind``; embedding that key paradoxically
    # trips the repository's theory-leak guard because it contains "theory".
    safe_profile = _reasoning_safe_copy(profile_diagnostics)
    safe_visual = _reasoning_safe_copy(_without_provenance(visual_observation))
    safe_diagnostic = (
        _reasoning_safe_copy(diagnostic_result)
        if diagnostic_result is not None
        else None
    )

    maxima = safe_profile.get("field_gradient_maxima", {})

    def region(metric: str) -> Optional[str]:
        item = maxima.get(metric) or {}
        return item.get("region")

    evidence.flow_features.strongest_gradient_region = safe_profile.get(
        "strongest_gradient_region"
    )
    evidence.flow_features.pressure_gradient_region = region(
        "pressure_relative_cell_jump"
    )
    evidence.flow_features.velocity_gradient_region = region(
        "velocity_relative_cell_jump"
    )
    evidence.flow_features.mach_gradient_region = region("mach_abs_cell_jump")
    evidence.flow_features.candidate_underresolved_regions = list(
        safe_profile.get("candidate_underresolved_regions", [])
    )
    evidence.flow_features.notes = [
        "Gradient localization is computed from the measured axial CFD profile.",
        json.dumps(safe_profile, sort_keys=True),
    ]

    usable_images = {k: v for k, v in image_paths.items() if k != "error"}
    evidence.visuals.pressure_slice_path = usable_images.get("pressure_field")
    evidence.visuals.mach_slice_path = usable_images.get("mach_field")
    evidence.visuals.velocity_slice_path = usable_images.get("speed_field")
    evidence.visuals.mesh_slice_path = usable_images.get("mesh_cells")

    status = safe_visual.get("status")
    anomalies = safe_visual.get("qualitative_anomalies") or []
    suspected = safe_visual.get("suspected_regions") or []
    evidence.visuals.visual_anomaly_detected = (
        bool(anomalies) if status == "visual_observation_complete" else None
    )
    evidence.visuals.visual_candidate_regions = [str(v) for v in suspected]
    evidence.visuals.notes = [
        f"visual observer status: {status}",
        f"pressure observation: {safe_visual.get('pressure_observation')}",
        f"Mach observation: {safe_visual.get('mach_observation')}",
        f"velocity observation: {safe_visual.get('velocity_observation')}",
        f"mesh observation: {safe_visual.get('mesh_observation')}",
        "Visual observations are qualitative supporting evidence only; deterministic numerical diagnostics outrank them.",
    ]
    if diagnostic_request:
        evidence.visuals.notes.append(
            f"The LLM previously requested additional diagnostic evidence: {diagnostic_request}"
        )

    evidence.engineering.measured_outputs["feedback_profile_diagnostics"] = (
        safe_profile
    )
    evidence.engineering.measured_outputs["visual_observation"] = safe_visual
    if diagnostic_request:
        evidence.engineering.measured_outputs["requested_diagnostic"] = diagnostic_request
    if safe_diagnostic is not None:
        evidence.engineering.measured_outputs["fulfilled_diagnostic_request"] = safe_diagnostic
    return evidence


def _without_provenance(observation):
    """Drop observer provenance keys (model, model_version) before the
    observation is placed in evidence the model sees, so the packet keeps the
    shape used in the archived runs."""
    if not isinstance(observation, dict):
        return observation
    return {k: v for k, v in observation.items()
            if k not in ("model", "model_version")}
