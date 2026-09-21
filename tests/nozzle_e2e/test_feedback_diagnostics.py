from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from scripts.run_nozzle_feedback import _next_continue_horizon
from src.pipeline.nozzle.feedback_diagnostics import analyze_axial_profile, augment_evidence
from src.pipeline.nozzle.spec import CANONICAL_SPEC
from src.pipeline.nozzle.validate import monitor
from src.reasoning.evidence_packet import assert_theory_blind_payload
from src.reasoning.reference_evidence_adapter import build_evidence_from_validation


def _write_table(path: Path, rows: list[tuple[float, float]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("# Time value\n" + "\n".join(f"{t} {v}" for t, v in rows) + "\n")


def test_monitor_merges_restart_segments_and_deduplicates_boundary(tmp_path: Path):
    _write_table(
        tmp_path / "postProcessing/mass/0/volFieldValue.dat",
        [(0.0, 1.0), (0.001, 2.0)],
    )
    _write_table(
        tmp_path / "postProcessing/mass/0.001/volFieldValue.dat",
        [(0.001, 2.0), (0.003, 3.0), (0.006, 4.0)],
    )
    data = monitor(tmp_path, "mass")
    assert np.allclose(data[:, 0], [0.0, 0.001, 0.003, 0.006])
    assert np.allclose(data[:, 1], [1.0, 2.0, 3.0, 4.0])


def test_feedback_horizon_can_extend_beyond_nominal_target_within_hard_bound():
    assert _next_continue_horizon(
        0.001, target_end=0.006, increment=0.005, max_end=0.020
    ) == 0.006
    assert _next_continue_horizon(
        0.006, target_end=0.006, increment=0.005, max_end=0.020
    ) == 0.011
    assert _next_continue_horizon(
        0.019, target_end=0.006, increment=0.005, max_end=0.020
    ) == 0.020
    assert _next_continue_horizon(
        0.020, target_end=0.006, increment=0.005, max_end=0.020
    ) is None


def test_profile_diagnostics_localize_measured_gradient(tmp_path: Path):
    x = np.linspace(0.0, CANONICAL_SPEC.length_m, 67)
    p = np.linspace(190000.0, 60000.0, 67)
    T = np.linspace(295.0, 210.0, 67)
    U = np.linspace(90.0, 430.0, 67)
    M = np.linspace(0.25, 1.5, 67)
    # Inject a deliberately sharp measured jump at the finite throat.
    jump = int(np.argmin(np.abs(x - 0.155)))
    M[jump:] += 0.35
    data = np.column_stack([x, p, T, U, M])
    path = tmp_path / "axial_profile.csv"
    np.savetxt(
        path,
        data,
        delimiter=",",
        header="x_m,p_Pa,T_K,U_m_s,Mach",
        comments="",
    )
    result = analyze_axial_profile(path, CANONICAL_SPEC, mesh_cells=528)
    assert result["theory_blind"] is True
    assert result["strongest_gradient_region"] in {"throat", "converging"}
    assert result["candidate_underresolved_regions"]


def test_augmented_reasoning_packet_strips_provenance_keys_with_theory_token():
    archived = (
        Path(__file__).resolve().parents[2]
        / "validation/canonical_reference/results/mesh1_validation.json"
    )
    validation = json.loads(archived.read_text(encoding="utf-8-sig"))
    evidence = build_evidence_from_validation(
        validation,
        mesh_report={"cells": 2112, "axial_cells": 132, "radial_cells": 16},
        execution={"status": "COMPLETED", "wall_seconds": 1.0},
        case_id="feedback_case",
    )

    profile = {
        "strongest_gradient_region": "throat",
        "field_gradient_maxima": {},
        "candidate_underresolved_regions": [],
        "theory_blind": True,
    }
    visual = {
        "status": "visual_observation_complete",
        "qualitative_anomalies": [],
        "suspected_regions": ["throat"],
        "pressure_observation": "smooth measured field",
        "mach_observation": "measured acceleration",
        "velocity_observation": "measured acceleration",
        "mesh_observation": "regular cells",
    }
    diagnostic = {
        "requested_diagnostic": "stationarity",
        "focused_result": {"stationarity": {"passes_fields": False}},
        "theory_blind": True,
    }

    augment_evidence(
        evidence,
        profile_diagnostics=profile,
        image_paths={"mach_field": "mach.png"},
        visual_observation=visual,
        diagnostic_request="stationarity",
        diagnostic_result=diagnostic,
    )

    # Raw artifacts retain their provenance marker, but the autonomous packet
    # must never embed a key containing the forbidden theory token.
    assert profile["theory_blind"] is True
    assert diagnostic["theory_blind"] is True
    assert_theory_blind_payload(evidence.to_dict())
    encoded = json.dumps(evidence.to_dict()).lower()
    assert '"theory_blind"' not in encoded
