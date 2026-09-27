#!/usr/bin/env python3
"""The evaluation architecture: modes, fault injection, gates-off. No CFD."""
from __future__ import annotations

from src.eval import faults as faults_mod
from src.eval.harness import fault_injection, gates_off_comparison, run_modes
from src.families.base import ACCEPT
from src.orchestrator import modes as modes_mod


def test_all_four_modes_resolve_distinct_behaviour():
    resolved = [modes_mod.resolve(m) for m in modes_mod.MODES]
    assert {m.name for m in resolved} == set(modes_mod.MODES)
    full = modes_mod.resolve(modes_mod.FULL)
    assert full.use_llm_diagnosis and full.gates_authoritative
    assert not full.is_ablation
    assert not modes_mod.resolve(modes_mod.GATES_OFF).gates_authoritative
    assert not modes_mod.resolve(modes_mod.RECIPE_BASELINE).use_llm_diagnosis
    nd = modes_mod.resolve(modes_mod.NO_DIAGNOSIS)
    assert not nd.allow_corrective_actions and nd.max_iterations == 1


def test_modes_run_on_one_architecture(fs_adapter, fs_spec, fs_evidence):
    from src.families.base import Proposal

    report = run_modes(
        fs_adapter, fs_spec, fs_evidence,
        which=(modes_mod.RECIPE_BASELINE, modes_mod.NO_DIAGNOSIS,
               modes_mod.GATES_OFF),
        proposer=lambda ev: Proposal("HEALTHY_COMPLETE", "ACCEPT", "stub"),
    )
    assert len(report.trials) == 3
    assert set(report.summary) == {
        modes_mod.RECIPE_BASELINE, modes_mod.NO_DIAGNOSIS, modes_mod.GATES_OFF
    }


def test_fault_registry_covers_the_family_hard_checks(fs_adapter, fs_spec, fs_evidence):
    validation = fs_adapter.validate(fs_evidence, fs_spec)
    hard = set(validation["hard_checks"])
    covered = {f.expected_check for f in faults_mod.faults_for("forward_step_2d")}
    missing = hard - covered
    assert not missing, f"hard checks with no seeded fault: {sorted(missing)}"


def test_every_seeded_fault_is_caught(fs_adapter, fs_spec, fs_evidence):
    report = fault_injection(
        fs_adapter, fs_spec, fs_evidence,
        faults_mod.faults_for("forward_step_2d"),
    )
    assert report.summary["n_faults"] == 18
    misses = [t.label for t in report.trials if not t.detail["scored_ok"]]
    assert not misses, f"faults not caught: {misses}"
    assert report.summary["false_accepts"] == 0
    assert report.summary["catch_rate"] == 1.0


def test_faults_are_nondestructive(fs_adapter, fs_spec, fs_evidence):
    before = fs_adapter.validate(fs_evidence, fs_spec)["status"]
    for fault in faults_mod.faults_for("forward_step_2d"):
        fault(fs_evidence)
    after = fs_adapter.validate(fs_evidence, fs_spec)["status"]
    assert before == after, "a fault mutated the shared healthy evidence"


def test_gates_off_comparison_runs_paired_arms(fs_adapter, fs_spec, fs_evidence):
    report = gates_off_comparison(
        fs_adapter, fs_spec, fs_evidence,
        faults_mod.faults_for("forward_step_2d"),
    )
    assert report.summary["n_faults"] == 18
    assert report.summary["gates_on_false_accepts"] == 0
    for trial in report.trials:
        assert "gates_on_decision" in trial.detail
        assert "gates_off_decision" in trial.detail


def test_gates_prevent_a_false_accept_when_the_proposal_says_accept(
    fs_adapter, fs_spec, fs_evidence
):
    """A proposer that always says ACCEPT is the adversarial case the gates exist for."""
    from src.families.base import Proposal

    report = gates_off_comparison(
        fs_adapter, fs_spec, fs_evidence,
        faults_mod.faults_for("forward_step_2d"),
        llm_proposal=lambda ev: Proposal("HEALTHY_COMPLETE", "ACCEPT", "looks fine"),
    )
    assert report.summary["gates_off_false_accepts"] == 18, (
        "an always-ACCEPT proposer must produce a false accept on every seeded "
        "fault when the gates are not authoritative"
    )
    assert report.summary["gates_on_false_accepts"] == 0
    assert report.summary["false_accepts_prevented_by_gates"] == 18
