#!/usr/bin/env python3
"""Forward-step parity: the shared orchestrator must decide what the family decides.

Parity is asserted at the DECISION level on evidence that already exists, so no
CFD runs. The legacy arm calls the family's own validate() and validate_action()
exactly as scripts/run_forward_step_2d.py does; the new arm calls
orchestrator.loop.decide_once. They must agree on the validation document, on
the action ruling and on the terminal disposition.
"""
from __future__ import annotations

import pytest

from src.families.base import ACCEPT, CORRECT_AND_RERUN, INCONCLUSIVE, REJECT
from src.orchestrator import modes as modes_mod
from src.orchestrator.ledger import Ledger
from src.orchestrator.loop import decide_once
from src.pipeline.forward_step_2d.validate import validate as fs_validate
from src.reasoning.forward_step_actions import validate_action as fs_validate_action
from src.reasoning.forward_step_scope_gate import BOUNDS


def _legacy(spec, diagnostics, action, *, iterations_used=1, max_iterations=4):
    """Exactly the legacy sequence: family validator, then family action gate."""
    validation = fs_validate(diagnostics)
    gate = fs_validate_action(
        action, spec, diagnostics, validation,
        max_end_time=BOUNDS["end_time"][1],
        iterations_used=iterations_used, max_iterations=max_iterations,
    )
    return validation, gate


def test_validation_document_is_byte_identical(fs_adapter, fs_spec, fs_evidence):
    legacy_validation = fs_validate(fs_evidence["raw_diagnostics"])
    new_validation = fs_adapter.validate(fs_evidence, fs_spec)
    assert new_validation == legacy_validation


@pytest.mark.parametrize(
    "action",
    ["ACCEPT", "CONTINUE_RUN", "EXTEND_END_TIME", "REDUCE_MAX_CO",
     "REFINE_MESH", "REBUILD_FROM_VALIDATED_SPEC", "FAIL_SAFELY",
     "REJECT_UNSUPPORTED"],
)
def test_action_ruling_parity(fs_adapter, fs_spec, fs_evidence, action):
    validation, gate = _legacy(fs_spec, fs_evidence["raw_diagnostics"], action)
    ruling = fs_adapter.execute_action(
        action, fs_spec, fs_evidence, validation=validation,
        iterations_used=1, max_iterations=4,
    )
    assert ruling.approved == gate.approved, action
    assert ruling.action == gate.action, action
    assert ruling.reasons == list(gate.reasons), action
    assert ruling.resulting_changes == dict(gate.resulting_changes), action


def test_orchestrator_decision_matches_the_family_disposition(
    fs_adapter, fs_spec, fs_evidence
):
    """decide_once in RECIPE_BASELINE mode uses no LLM, so it is reproducible."""
    step = decide_once(
        fs_adapter, fs_spec, fs_evidence,
        mode=modes_mod.RECIPE_BASELINE, ledger=Ledger(),
    )
    legacy_validation = fs_validate(fs_evidence["raw_diagnostics"])
    assert step.validation == legacy_validation
    assert step.decision == fs_adapter.maps_to_decision(legacy_validation)
    assert step.decision in (ACCEPT, CORRECT_AND_RERUN, INCONCLUSIVE, REJECT)


def test_frozen_family_can_still_accept_despite_a_blocked_capability(
    fs_adapter, fs_spec, fs_evidence
):
    """A registered family must not be blocked by an OPTIONAL capability's TODO.

    forward_step_2d is frozen and registered for acceptance, while
    REFINE_REGION remains unavailable. Those are different things and the
    recipe keeps them in different places.
    """
    assert fs_adapter.recipe.is_registered()
    assert fs_adapter.recipe.unresolved() == []
    blocked = fs_adapter.recipe.unresolved_capabilities()
    assert "REFINE_REGION" in blocked
    assert not fs_adapter.recipe.capability_available("REFINE_REGION")

    step = decide_once(fs_adapter, fs_spec, fs_evidence,
                       mode=modes_mod.RECIPE_BASELINE)
    legacy = fs_validate(fs_evidence["raw_diagnostics"])
    assert step.decision == fs_adapter.maps_to_decision(legacy)


def test_unresolved_acceptance_criterion_downgrades_accept(
    fs_adapter, fs_spec, fs_evidence, monkeypatch
):
    """The CRITERION_NOT_REGISTERED mechanism, on an acceptance-critical TODO."""
    from src.families.base import CRITERION_NOT_REGISTERED, TODO
    from dataclasses import replace

    unregistered = replace(
        fs_adapter.recipe,
        tolerances={**fs_adapter.recipe.tolerances,
                    "pretend_open": TODO("fs2d.pretend_open", "test")},
    )
    monkeypatch.setattr(fs_adapter, "recipe", unregistered, raising=False)
    monkeypatch.setattr(
        type(fs_adapter), "maps_to_decision", lambda self, v: ACCEPT, raising=True
    )
    step = decide_once(fs_adapter, fs_spec, fs_evidence,
                       mode=modes_mod.RECIPE_BASELINE)
    assert step.decision == INCONCLUSIVE
    assert any(CRITERION_NOT_REGISTERED in r for r in step.reasons)


def test_ledger_records_every_stage_of_a_decision(fs_adapter, fs_spec, fs_evidence, tmp_path):
    ledger = Ledger(path=tmp_path / "ledger.jsonl", mode=modes_mod.RECIPE_BASELINE)
    decide_once(fs_adapter, fs_spec, fs_evidence,
                mode=modes_mod.RECIPE_BASELINE, ledger=ledger)
    stages = ledger.stages()
    for required in ("evidence", "diagnosis", "proposed_action", "validation",
                     "deterministic_ruling"):
        assert required in stages, required
    rows = Ledger.read(tmp_path / "ledger.jsonl")
    assert len(rows) == len(ledger.rows)
    assert [r["seq"] for r in rows] == sorted(r["seq"] for r in rows)


def test_no_diagnosis_mode_refuses_corrective_actions(fs_adapter, fs_spec, fs_evidence):
    step = decide_once(fs_adapter, fs_spec, fs_evidence, mode=modes_mod.NO_DIAGNOSIS)
    assert step.ruling.approved is False
    assert "disabled in this mode" in " ".join(step.ruling.reasons)


def test_gates_off_still_computes_and_records_the_ruling(fs_adapter, fs_spec, fs_evidence):
    """The ablation must measure what the gates WOULD have said.

    An offline stub stands in for the model: this test is about the ablation's
    bookkeeping, not about the model's output.
    """
    from src.families.base import Proposal

    fs_adapter.diagnose = lambda ev, sp: (
        Proposal("HEALTHY_COMPLETE", "ACCEPT", "stub"), {"stub": True}
    )
    ledger = Ledger(mode=modes_mod.GATES_OFF)
    step = decide_once(fs_adapter, fs_spec, fs_evidence,
                       mode=modes_mod.GATES_OFF, ledger=ledger)
    rulings = ledger.of_stage("deterministic_ruling")
    assert rulings and rulings[0]["authoritative"] is False
    assert any("gates_off" in r for r in step.reasons)
