"""Theory-blind evidence adaptation, exercised on archived reference evidence.

These tests use validation/canonical_reference/results/mesh1_validation.json,
the real archived output of the frozen validator for the canonical coarse mesh.
No CFD is run and no OpenFOAM installation is required.
"""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from src.contracts.agent_decision import (  # noqa: E402
    AgentAction,
    AgentDecision,
    Diagnosis,
)
from src.reasoning.action_validator import validate_agent_action  # noqa: E402
from src.reasoning.evidence_packet import (  # noqa: E402
    assert_theory_blind_payload,
    build_reasoning_packet,
)
from src.reasoning.nozzle_diagnosis import _deterministic_decision  # noqa: E402
from src.reasoning.reference_evidence_adapter import (  # noqa: E402
    build_evidence_from_validation,
    withheld_from_agent,
)

ARCHIVED = (
    REPO_ROOT
    / "validation/canonical_reference/results/mesh1_validation.json"
)


@pytest.fixture(scope="module")
def validation():
    return json.loads(ARCHIVED.read_text(encoding="utf-8-sig"))


@pytest.fixture(scope="module")
def evidence(validation):
    return build_evidence_from_validation(
        validation,
        mesh_report={"cells": 2112, "axial_cells": 132, "radial_cells": 16},
        execution={"status": "COMPLETED", "wall_seconds": 128.0},
        case_id="nozzle_A_reference",
    )


def test_archived_reference_passed_every_check(validation):
    assert validation["status"] == "PASS_SINGLE_MESH"
    assert all(validation["checks"].values())


def test_measured_quantities_survive_the_adaptation(validation, evidence):
    final = validation["final"]

    assert evidence.engineering.measured_outputs["exit_mach"] == final["outlet_M"]
    assert (
        evidence.engineering.measured_outputs["exit_static_pressure_pa"]
        == final["outlet_p"]
    )
    assert evidence.conservation.inlet_mass_flow_kg_s == final["inlet_mdot"]
    assert (
        evidence.conservation.mass_imbalance_percent
        == final["max_window_mismatch_pct"]
    )
    assert evidence.solver.max_courant_number == validation["max_Co"]
    assert evidence.mesh.check_mesh_passed is True


def test_evidence_is_theory_blind(evidence):
    payload = evidence.to_dict()

    # The repository's own assertion, plus an explicit scan of the serialized
    # packet for the archived reference numbers.
    assert_theory_blind_payload(payload)

    text = json.dumps(payload)

    for token in ("theory", "analytical", "isentropic", "quasi_1d_target"):
        assert token not in text.lower()


def test_withheld_material_is_exactly_the_post_hoc_comparison(validation):
    withheld = withheld_from_agent(validation)

    assert set(withheld) == {"theory", "theory_error_pct"}
    assert withheld["theory"]["outlet_M"] == pytest.approx(1.50440, rel=1e-4)


def test_reasoning_packet_builds_and_stays_blind(evidence):
    from src.contracts.problem_spec import (
        CFDProblemSpec,
        NozzleFamily,
        NozzleGeometry,
        OperatingConditions,
    )

    problem = CFDProblemSpec(
        nozzle_family=NozzleFamily.CONICAL,
        geometry=NozzleGeometry(
            inlet_radius_m=0.05,
            throat_radius_m=0.0326,
            outlet_radius_m=0.0354,
            inlet_length_m=0.05,
            converging_length_m=0.10,
            throat_length_m=0.01,
            diverging_length_m=0.12,
            outlet_length_m=0.05,
        ),
        operating_conditions=OperatingConditions(
            inlet_total_pressure_pa=200000.0,
            inlet_total_temperature_k=300.0,
            outlet_static_pressure_pa=30000.0,
        ),
    )

    packet = build_reasoning_packet(problem, evidence)

    assert "evidence" in packet and "problem" in packet
    assert_theory_blind_payload(
        {"problem": packet["problem"], "evidence": packet["evidence"]}
    )


def test_accept_is_permitted_on_the_archived_reference_state(evidence):
    decision = AgentDecision(
        diagnosis=Diagnosis.ACCEPTABLE,
        evidence_used=["conservation", "stationarity", "boundaries"],
        competing_hypotheses=[],
        reasoning_summary="All deterministic evidence is consistent.",
        action=AgentAction.ACCEPT,
    )

    result = validate_agent_action(evidence, decision)

    assert result.approved, result.reasons


def test_accept_is_refused_when_stationarity_fails(validation):
    degraded = copy.deepcopy(validation)
    degraded["checks"]["monitors_stationary"] = False
    degraded["checks"]["fields_stationary"] = False

    evidence = build_evidence_from_validation(degraded)

    decision = AgentDecision(
        diagnosis=Diagnosis.ACCEPTABLE,
        evidence_used=["stationarity"],
        competing_hypotheses=[],
        reasoning_summary="Claiming acceptance despite failed stationarity.",
        action=AgentAction.ACCEPT,
    )

    result = validate_agent_action(evidence, decision)

    assert not result.approved
    assert any("stationarity" in r for r in result.reasons)


def test_accept_is_refused_when_conservation_fails(validation):
    degraded = copy.deepcopy(validation)
    degraded["final"]["max_window_mismatch_pct"] = 4.2

    evidence = build_evidence_from_validation(degraded)

    decision = AgentDecision(
        diagnosis=Diagnosis.ACCEPTABLE,
        evidence_used=["conservation"],
        competing_hypotheses=[],
        reasoning_summary="Claiming acceptance despite a mass imbalance.",
        action=AgentAction.ACCEPT,
    )

    result = validate_agent_action(evidence, decision)

    assert not result.approved
    assert any("conservation" in r for r in result.reasons)


def test_deterministic_fallback_decision_tracks_the_checks(validation, evidence):
    decision = _deterministic_decision(evidence)

    assert decision.action == AgentAction.ACCEPT
    assert decision.diagnosis == Diagnosis.ACCEPTABLE
    assert validate_agent_action(evidence, decision).approved

    degraded = copy.deepcopy(validation)
    degraded["checks"]["steady_mass_balance"] = False
    degraded_evidence = build_evidence_from_validation(degraded)

    fallback = _deterministic_decision(degraded_evidence)

    assert fallback.action == AgentAction.CONTINUE_RUN
    assert fallback.diagnosis == Diagnosis.UNCONVERGED
