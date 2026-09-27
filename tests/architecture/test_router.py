#!/usr/bin/env python3
"""Router: LLM proposes, register verifies, family vetoes."""
from __future__ import annotations

from src.eval.harness import NEGATIVE_ROUTING_CORPUS, negative_routing
from src.families import registry
from src.families.base import NO_REGISTERED_FAMILY, REJECT
from src.router.route import keyword_support, route


def test_unknown_family_name_from_the_llm_is_refused():
    registry.install_standing_register()
    r = route("anything", propose=lambda t, m: "hypersonic_scramjet")
    assert not r.approved
    assert NO_REGISTERED_FAMILY in r.decision
    assert r.proposed_family == "hypersonic_scramjet"


def test_llm_cannot_route_to_a_nonexecutable_family():
    registry.install_standing_register()
    for name in ("square_duct", "cube", "airfoil", "backward_step"):
        r = route("some request", propose=lambda t, m, n=name: n)
        assert not r.approved, f"{name} must not be executable"
        assert NO_REGISTERED_FAMILY in r.decision
        assert "not executable" in " ".join(r.reasons)


def test_pending_family_refusal_names_the_unregistered_recipe():
    registry.install_standing_register()
    r = route("NACA0012 at 10 degrees", propose=lambda t, m: "airfoil")
    assert not r.approved
    assert "recipe is unregistered" in " ".join(r.reasons)


def test_pending_families_are_absent_from_the_llm_menu():
    registry.install_standing_register()
    from src.router.route import describe_families

    names = {m["name"] for m in describe_families()}
    assert names == {"nozzle", "forward_step_2d"}


def test_keyword_support_still_sees_the_whole_register():
    """Ambiguity must be judged against every family, not only executable ones."""
    registry.install_standing_register()
    support = keyword_support("a turbulent naca0012 airfoil section")
    assert "airfoil" in support, (
        "a pending family must still register keyword support so that requests "
        "aimed at it are recognised rather than mis-routed"
    )


def test_no_proposal_and_no_keyword_support_is_rejected():
    registry.install_standing_register()
    r = route("please compute something interesting")
    assert not r.approved and NO_REGISTERED_FAMILY in r.decision


def test_keyword_fallback_routes_an_unambiguous_request():
    registry.install_standing_register()
    r = route("Simulate a converging-diverging nozzle with a 20 mm throat.")
    assert r.approved and r.family == "nozzle"


def test_ambiguous_keyword_support_refuses_rather_than_guessing():
    registry.install_standing_register()
    text = "a forward step and a backward step in the same channel"
    assert len(keyword_support(text)) > 1
    r = route(text)
    assert not r.approved
    assert "must say which" in " ".join(r.reasons)


def test_a_request_mentioning_only_a_pending_family_is_refused():
    registry.install_standing_register()
    r = route("compute CL and CD for a naca0012 aerofoil")
    assert not r.approved
    joined = " ".join(r.reasons)
    assert "not executable" in joined and "airfoil" in joined


def test_turbulent_step_request_does_not_collapse_onto_the_inviscid_family():
    """The regression the register-wide ambiguity check exists to prevent."""
    registry.install_standing_register()
    text = "Run a turbulent step flow and give me the reattachment length."
    support = keyword_support(text)
    assert {"forward_step_2d", "backward_step"} <= set(support)
    r = route(text)
    assert not r.approved, (
        "with backward_step pending, this must NOT silently route to the "
        "inviscid forward-step family"
    )


def test_routing_without_keyword_support_is_flagged_for_the_scope_gate():
    registry.install_standing_register()
    r = route("compute the thing", propose=lambda t, m: "forward_step_2d")
    assert r.approved
    assert any("scope gate retains veto" in s for s in r.reasons)


def test_negative_routing_corpus_scores():
    report = negative_routing(NEGATIVE_ROUTING_CORPUS)
    assert report.summary["scored"] >= 8
    # Every out-of-scope request must be refused.
    for trial in report.trials:
        if trial.label.startswith("oos_"):
            assert REJECT in trial.decision, f"{trial.label} was not refused"
