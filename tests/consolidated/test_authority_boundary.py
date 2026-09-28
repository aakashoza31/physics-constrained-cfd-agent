#!/usr/bin/env python3
"""The agent/authority boundary. These tests ARE the safety argument."""
from __future__ import annotations

import pytest

from src.authority import (
    AUTHORITY_DECIDES, LLM_MAY, AuthorityTrace, AuthorityViolation,
    assert_authority_owns, assert_llm_may, final_decision,
)


def test_the_two_sets_do_not_overlap():
    assert not (set(LLM_MAY) & set(AUTHORITY_DECIDES))


def test_every_scientific_question_is_owned_by_code():
    for question in ("family_compatibility", "geometry_admissibility",
                     "mesh_quality", "physical_model",
                     "boundary_condition_consistency", "numerical_health",
                     "conservation", "convergence", "stationarity",
                     "validation", "permitted_actions", "final_decision"):
        assert question in AUTHORITY_DECIDES
        assert_authority_owns(question)


@pytest.mark.parametrize("question", AUTHORITY_DECIDES)
def test_a_model_may_never_answer_an_authority_question(question):
    with pytest.raises(AuthorityViolation):
        assert_llm_may(question)


def test_an_undeclared_model_activity_is_refused():
    with pytest.raises(AuthorityViolation):
        assert_llm_may("decide_whether_this_is_good_enough")


def test_a_proposal_can_never_become_a_gate():
    trace = AuthorityTrace(family="nozzle", case="canonical_reference")
    trace.proposal("diagnose_evidence", "looks converged to me")
    assert trace.verdict() == "INCONCLUSIVE"       # a proposal is not evidence
    assert all(p["binding"] is False for p in trace.proposals)


def test_a_failed_gate_rejects_however_confident_the_model_was():
    trace = AuthorityTrace(family="cube", case="drifting_wake")
    trace.gate("numerical_health", True)
    trace.gate("convergence", True)
    trace.gate("stationarity", False, measured={"growth": 2.1}, threshold=1.25)
    for _ in range(20):
        trace.proposal("diagnose_evidence", "ACCEPTABLE, definitely converged")
        trace.proposal("propose_bounded_action", "ACCEPT")
    decision = final_decision(trace)
    assert decision.verdict == "REJECT"
    assert decision.to_dict()["llm_override_possible"] is False


def test_an_unresolved_gate_is_not_a_pass():
    trace = AuthorityTrace()
    trace.gate("validation", None, measured="not evaluated")
    assert final_decision(trace).verdict == "INCONCLUSIVE"


def test_no_gates_at_all_is_inconclusive_not_accept():
    assert final_decision(AuthorityTrace()).verdict == "INCONCLUSIVE"


def test_reject_beats_inconclusive():
    trace = AuthorityTrace()
    trace.gate("validation", None)
    trace.gate("conservation", False)
    assert final_decision(trace).verdict == "REJECT"
