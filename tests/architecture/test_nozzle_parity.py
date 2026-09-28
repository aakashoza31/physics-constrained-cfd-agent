#!/usr/bin/env python3
"""Nozzle decision-level parity. Replay only -- no OpenFOAM, no WSL, no CFD.

Two layers:

  * synthetic-evidence tests, which exercise the adapter's delegation and the
    Family-1 -> shared decision mapping wherever the reasoning stack imports;
  * real-artifact tests against
    demo/nozzle_feedback_v2_hotfix/case_A_reference/iterations/iteration_0{1,2},
    which skip ONLY when those directories genuinely do not exist.

The archived pair is authoritative:
  iteration_01  validator FAIL (steady_mass_balance, monitors_stationary,
                fields_stationary) -> UNCONVERGED -> CONTINUE_RUN, gate
                APPROVED -> shared CORRECT_AND_RERUN
  iteration_02  validator PASS_SINGLE_MESH 20/20 -> ACCEPTABLE -> ACCEPT, gate
                APPROVED -> shared ACCEPT
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.families.base import ACCEPT, CORRECT_AND_RERUN
from src.families.nozzle_adapter import NozzleAdapter
from src.orchestrator import modes as modes_mod
from src.orchestrator.ledger import Ledger
from src.orchestrator.loop import decide_once

REPO = Path(__file__).resolve().parents[2]
ARCHIVE = REPO / "demo/nozzle_feedback_v2_hotfix/case_A_reference/iterations"

ITER1 = ARCHIVE / "iteration_01"
ITER2 = ARCHIVE / "iteration_02"

#: The failures the archived iteration 1 records, and only these.
ITER1_FAILED = {"steady_mass_balance", "monitors_stationary", "fields_stationary"}

#: Check names build_evidence_from_validation consumes. Used only to fabricate
#: synthetic evidence; the real tests read the archived document instead.
SYNTHETIC_CHECKS = (
    "solver_completed", "no_fatal", "positive_finite",
    "steady_mass_balance", "monitors_stationary", "fields_stationary",
    "stagnation_enthalpy", "inlet_subsonic_inflow", "outlet_all_supersonic",
    "reservoir_conditions",
)


def _replay_available() -> bool:
    return NozzleAdapter.self_check()["replay_ok"]


replay_only = pytest.mark.skipif(
    not _replay_available(),
    reason="nozzle replay targets unavailable (incomplete working copy)",
)


class _Spec:
    """Stand-in spec object. Continuation must carry it through unchanged."""

    case_id = "case_A_reference"


def _synthetic_validation(status: str, failed: set) -> dict:
    return {
        "status": status,
        "case_id": "case_A_reference",
        "checks": {n: (n not in failed) for n in SYNTHETIC_CHECKS},
        "failed_checks": sorted(failed),
        "final": {
            "max_window_mismatch_pct": 0.2,
            "outlet_normal_M_min": 1.4,
            "inlet_mdot": 1.0,
            "outlet_mdot": 1.0,
        },
        "drift_fraction_last_2ms": {},
        "field_L2_change_last_2ms": {},
        "all_time_min_p_T_rho": [1.0, 1.0, 1.0],
    }


# ----------------------------------------------------------------------
# 1. load_spec: the case_spec.json wrapper
# ----------------------------------------------------------------------
def test_load_spec_unwraps_the_case_spec_wrapper(tmp_path, monkeypatch):
    """case_spec.json is {"spec": {...}, "llm_interpretation":..., "llm_call":...}.

    from_dict must receive the INNER dictionary, untouched.
    """
    import src.families.nozzle_adapter as mod

    seen = {}

    class FakeSpec:
        @classmethod
        def from_dict(cls, data):
            seen["data"] = data
            return cls()

    monkeypatch.setattr(
        mod, "_resolve", lambda key: FakeSpec if key == "spec" else None
    )
    inner = {"case_id": "case_A_reference", "throat_radius_m": 0.01}
    (tmp_path / "case_spec.json").write_text(
        json.dumps({"spec": inner, "llm_interpretation": "x", "llm_call": {"m": 1}})
    )
    NozzleAdapter().load_spec(tmp_path / "case_spec.json")
    assert seen["data"] == inner, "the wrapper envelope was passed to from_dict"
    assert "llm_call" not in seen["data"] and "llm_interpretation" not in seen["data"]


def test_load_spec_accepts_an_unwrapped_spec_unchanged(tmp_path, monkeypatch):
    import src.families.nozzle_adapter as mod

    seen = {}

    class FakeSpec:
        @classmethod
        def from_dict(cls, data):
            seen["data"] = data
            return cls()

    monkeypatch.setattr(
        mod, "_resolve", lambda key: FakeSpec if key == "spec" else None
    )
    raw = {"case_id": "c", "throat_radius_m": 0.01}
    (tmp_path / "spec.json").write_text(json.dumps(raw))
    NozzleAdapter().load_spec(tmp_path / "spec.json")
    assert seen["data"] == raw


def test_load_spec_finds_case_spec_json_in_a_directory(tmp_path, monkeypatch):
    import src.families.nozzle_adapter as mod

    class FakeSpec:
        @classmethod
        def from_dict(cls, data):
            return data

    monkeypatch.setattr(
        mod, "_resolve", lambda key: FakeSpec if key == "spec" else None
    )
    (tmp_path / "case_spec.json").write_text(json.dumps({"spec": {"case_id": "c"}}))
    assert NozzleAdapter().load_spec(tmp_path) == {"case_id": "c"}


# ----------------------------------------------------------------------
# 2. delegation uses the family's real APIs
# ----------------------------------------------------------------------
def test_action_vocabulary_is_the_families_own_enum():
    from src.contracts.agent_decision import AgentAction

    assert set(NozzleAdapter.recipe.allowed_actions) == {a.value for a in AgentAction}
    assert "REFINE_REGION" not in NozzleAdapter.recipe.allowed_actions
    assert NozzleAdapter.recipe.region_vocabulary == ()


def test_recipe_carries_the_frozen_validator_thresholds():
    tol = NozzleAdapter.recipe.tolerances
    assert tol["theory_outlet_pressure_error_pct_max"] == 5.0
    assert tol["theory_other_output_error_pct_max"] == 3.0
    assert NozzleAdapter.recipe.is_registered()


def test_to_problem_spec_reports_missing_geometry_rather_than_inventing_it():
    class Bare:
        inlet_radius_m = 0.05
        throat_radius_m = 0.01
        exit_radius_m = 0.03

    with pytest.raises(NotImplementedError) as exc:
        NozzleAdapter().to_problem_spec(Bare())
    message = str(exc.value)
    assert "converging_length_m" in message
    assert "NOT invented" in message
    assert "decision-level parity is unaffected" in message


def test_to_problem_spec_maps_existing_fields_only():
    class Full:
        inlet_radius_m, throat_radius_m, exit_radius_m = 0.05, 0.01, 0.03
        inlet_straight_m = converging_m = 0.02
        throat_m = diverging_m = outlet_straight_m = 0.02
        total_pressure_pa, total_temperature_k = 5.0e5, 300.0
        ambient_pressure_pa, gamma, gas_constant_j_per_kg_k = 1.0e5, 1.4, 287.0

    from src.contracts.problem_spec import NozzleFamily

    problem = NozzleAdapter().to_problem_spec(Full())
    assert problem.nozzle_family is NozzleFamily.CONICAL
    assert problem.geometry.outlet_radius_m == 0.03      # exit_radius_m mapped
    assert problem.operating_conditions.outlet_static_pressure_pa == 1.0e5
    problem.validate()



def test_parse_request_keeps_the_actual_llm_record(monkeypatch):
    import src.families.nozzle_adapter as mod

    class Record:
        def to_dict(self):
            return {"stage": "case_spec_interpretation", "source": "test"}

    fake_spec = object()
    fake_request = object()
    fake_record = Record()

    def fake_resolve(key):
        if key == "parse":
            return lambda text: (fake_spec, fake_request, fake_record)
        raise AssertionError(key)

    monkeypatch.setattr(mod, "_resolve", fake_resolve)

    spec, record = NozzleAdapter().parse_request("test")
    assert spec is fake_spec
    assert record == {
        "stage": "case_spec_interpretation",
        "source": "test",
    }


# ----------------------------------------------------------------------
# 3. Family-1 correction semantics through the shared loop (synthetic)
# ----------------------------------------------------------------------
@replay_only
def test_unconverged_fail_is_a_correction_not_a_rejection():
    adapter, spec = NozzleAdapter(), _Spec()
    evidence = adapter.wrap_evidence(
        _synthetic_validation("FAIL", ITER1_FAILED),
        execution={"status": "ok"}, mesh_report={}, case_id="iteration_01",
    )
    step = decide_once(adapter, spec, evidence, mode=modes_mod.RECIPE_BASELINE)

    assert step.proposal.diagnosis == "UNCONVERGED"
    assert step.proposal.action == "CONTINUE_RUN"
    assert step.ruling.approved is True
    assert step.decision == CORRECT_AND_RERUN
    # Continuation must not terminate the loop.
    assert step.next_spec is spec
    assert step.ruling.resulting_changes["continuation"]


@replay_only
def test_all_checks_passing_maps_to_accept():
    adapter, spec = NozzleAdapter(), _Spec()
    evidence = adapter.wrap_evidence(
        _synthetic_validation("PASS_SINGLE_MESH", set()),
        execution={"status": "ok"}, mesh_report={}, case_id="iteration_02",
    )
    step = decide_once(adapter, spec, evidence, mode=modes_mod.RECIPE_BASELINE)
    assert step.proposal.diagnosis == "ACCEPTABLE"
    assert step.proposal.action == "ACCEPT"
    assert step.ruling.approved is True
    assert step.decision == ACCEPT


@replay_only
def test_proposal_uses_enum_values_and_preserves_the_original_decision():
    adapter = NozzleAdapter()
    evidence = adapter.wrap_evidence(
        _synthetic_validation("FAIL", ITER1_FAILED),
        execution={"status": "ok"}, mesh_report={}, case_id="x",
    )
    proposal = adapter.deterministic_proposal(evidence, _Spec())
    assert proposal.diagnosis == "UNCONVERGED", "str(enum) would give 'Diagnosis.…'"
    assert "." not in proposal.diagnosis and "." not in proposal.action
    assert "agent_decision" in proposal.raw
    assert proposal.raw["agent_decision"]["action"] in ("CONTINUE_RUN", "ACCEPT")


@replay_only
def test_solver_failure_still_rejects():
    """The mapping must not turn every FAIL into a correction either."""
    from src.families.base import REJECT

    adapter = NozzleAdapter()
    evidence = adapter.wrap_evidence(
        _synthetic_validation("FAIL", {"solver_completed", "positive_finite"}),
        execution={"status": "crashed"}, mesh_report={}, case_id="bad",
    )
    step = decide_once(adapter, _Spec(), evidence, mode=modes_mod.RECIPE_BASELINE)
    assert step.proposal.diagnosis == "NUMERICAL_FAILURE"
    assert step.decision == REJECT


@replay_only
def test_the_family_action_gate_is_the_one_used():
    """No second action validator: the ruling must come from validate_agent_action."""
    adapter = NozzleAdapter()
    evidence = adapter.wrap_evidence(
        _synthetic_validation("FAIL", ITER1_FAILED),
        execution={"status": "ok"}, mesh_report={}, case_id="x",
    )
    from src.reasoning.action_validator import validate_agent_action
    from src.reasoning.nozzle_diagnosis import _deterministic_decision

    cfd_evidence = adapter.to_cfd_evidence(evidence)
    expected = validate_agent_action(
        cfd_evidence, _deterministic_decision(cfd_evidence)
    )
    ruling = adapter.execute_action("CONTINUE_RUN", _Spec(), evidence)
    assert ruling.approved == expected.approved
    assert ruling.reasons == list(expected.reasons)


# ----------------------------------------------------------------------
# 4. REAL archived artifacts. Skip only if they genuinely do not exist.
# ----------------------------------------------------------------------
real_archive = pytest.mark.skipif(
    not (ITER1.exists() and ITER2.exists()),
    reason=f"archived replay pair not present under {ARCHIVE}",
)


def _replay(directory: Path):
    adapter = NozzleAdapter()
    evidence = adapter.load_evidence(directory)
    spec = _Spec()
    step = decide_once(
        adapter, spec, evidence, mode=modes_mod.RECIPE_BASELINE,
        ledger=Ledger(mode=modes_mod.RECIPE_BASELINE),
    )
    return adapter, spec, evidence, step


@real_archive
@replay_only
def test_real_iteration_01_is_correct_and_rerun():
    adapter, spec, evidence, step = _replay(ITER1)

    validation = evidence["raw_validation"]
    assert validation["status"] == "FAIL"
    failed = {k for k, ok in validation.get("checks", {}).items() if not ok}
    assert failed == ITER1_FAILED, f"archived failures changed: {sorted(failed)}"

    assert step.proposal.diagnosis == "UNCONVERGED"
    assert step.proposal.action == "CONTINUE_RUN"
    assert step.ruling.approved is True
    assert step.decision == CORRECT_AND_RERUN
    assert step.next_spec is spec


@real_archive
@replay_only
def test_real_iteration_02_is_accept():
    adapter, spec, evidence, step = _replay(ITER2)

    validation = evidence["raw_validation"]
    assert validation["status"] == "PASS_SINGLE_MESH"
    checks = validation.get("checks", {})
    assert checks and all(checks.values()), "archived iteration 2 was not 20/20"
    assert len(checks) == 20, f"expected 20 checks, found {len(checks)}"

    assert step.proposal.diagnosis == "ACCEPTABLE"
    assert step.proposal.action == "ACCEPT"
    assert step.ruling.approved is True
    assert step.decision == ACCEPT


@real_archive
@replay_only
def test_real_replay_launches_nothing():
    """Replay must not touch FoamRuntime or any subprocess."""
    import subprocess

    import src.pipeline.foam_runtime as foam_runtime

    calls = []

    def boom(*a, **k):  # pragma: no cover - must never run
        calls.append(a)
        raise AssertionError("replay attempted to launch a process")

    original_run, original_popen = subprocess.run, subprocess.Popen
    original_cmd = foam_runtime.FoamRuntime.__dict__.get("run")
    subprocess.run, subprocess.Popen = boom, boom
    if original_cmd is not None:
        foam_runtime.FoamRuntime.run = boom  # type: ignore[assignment]
    try:
        for directory in (ITER1, ITER2):
            _replay(directory)
    finally:
        subprocess.run, subprocess.Popen = original_run, original_popen
        if original_cmd is not None:
            foam_runtime.FoamRuntime.run = original_cmd  # type: ignore[assignment]
    assert not calls


@real_archive
def test_real_case_spec_wrapper_loads():
    """The wrapper shape is what the archive actually holds."""
    candidates = [
        p
        for name in ("case_spec.json", "feedback_case_spec.json", "spec.json")
        for p in ARCHIVE.parent.rglob(name)
    ]
    if not candidates:
        pytest.skip("no case_spec.json in the archive")
    data = json.loads(candidates[0].read_text())
    if not (isinstance(data, dict) and isinstance(data.get("spec"), dict)):
        pytest.skip(f"{candidates[0].name} is not the wrapper shape")
    assert data["spec"], "wrapper carries an empty inner spec"
    if NozzleAdapter.self_check()["targets"].get("spec") == "ok":
        assert NozzleAdapter().load_spec(candidates[0]) is not None
