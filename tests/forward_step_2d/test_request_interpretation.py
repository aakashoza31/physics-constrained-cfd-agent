#!/usr/bin/env python3
"""Regression tests for the reporting-versus-physics split in interpretation.

BACKGROUND
----------
The live request ended with

    "Report whether the compression structure ahead of the step is resolved
     and whether the result is trustworthy."

The interpreter set ``requests_unsupported_physics`` true, noting that
"assessing solution quality" was "not supported by case setup interpretation".
That is a category error. Asking for an assessment of a finished run is a
reporting request, not a simulation requirement: it adds no physics, changes
no dictionary and needs no solver capability the family lacks. The
deterministic validator and the reporting stage answer it after the run.

These tests pin the schema contract and the deterministic consequence. They do
not call the model: an offline test cannot assert what a model will say, and
pretending otherwise would be the sort of fake evidence this project refuses.
What they do assert is that the structure exists for the model to use, that the
prompt instructs the split, and that reporting objectives are inert with
respect to the deterministic scope gate.
"""
from __future__ import annotations

import pytest

from src.agents.forward_step_spec_agent import (
    SYSTEM_PROMPT,
    ForwardStepRequest,
    to_spec,
)
from src.pipeline.forward_step_2d.spec import ForwardStep2DSpec
from src.reasoning.forward_step_scope_gate import evaluate_scope, screen_request_text

LIVE_REQUEST = (
    "Simulate a 2D forward-facing step in the validated supersonic channel "
    "family with an inlet Mach number of 2.5 and a step height of 0.15 "
    "channel heights. Report whether the compression structure ahead of the "
    "step is resolved and whether the result is trustworthy."
)

#: The walkthrough request of the paper (Mach-2 canonical case).
PAPER_WALKTHROUGH_REQUEST = (
    "Simulate a 2D forward-facing step in the validated supersonic channel "
    "family with inlet Mach number 2.0, step height 0.20 channel heights, and "
    "step location x = 0.6. Run the CFD, inspect the transient "
    "shock/compression structure, and determine whether the final result "
    "passes deterministic scientific validation."
)

REPORTING_ASKS = [
    "Report whether the compression structure ahead of the step is resolved.",
    "Tell me whether the result is trustworthy.",
    "Assess whether the mesh resolution is adequate.",
    "Summarise the shock structure once the run finishes.",
    "Explain how accurate this is.",
]


def test_the_schema_has_somewhere_to_put_a_reporting_request():
    assert "reporting_objectives" in ForwardStepRequest.model_fields
    field = ForwardStepRequest.model_fields["reporting_objectives"]
    assert field.default_factory is list


def test_the_prompt_instructs_the_split():
    assert "SIMULATION REQUIREMENTS" in SYSTEM_PROMPT
    assert "REPORTING OBJECTIVES" in SYSTEM_PROMPT
    assert "Never set requests_unsupported_physics for an item of kind B" in SYSTEM_PROMPT


def test_the_unsupported_flag_is_scoped_to_the_simulation():
    description = ForwardStepRequest.model_fields[
        "requests_unsupported_physics"
    ].description
    assert "SIMULATION ITSELF" in description
    assert "assessed or reported is not physics" in description


def test_the_prompt_separates_answering_from_being_asked():
    """Rule 8 forbids the model answering, not the user asking."""
    assert "does not forbid the user from ASKING one" in SYSTEM_PROMPT


def test_a_reporting_request_does_not_change_the_spec():
    """The same numbers, with and without the reporting sentence attached."""
    bare = ForwardStepRequest(
        case_name="mach2p5_step0p15", summary="x", mach=2.5, step_height=0.15
    )
    with_objectives = ForwardStepRequest(
        case_name="mach2p5_step0p15",
        summary="x",
        mach=2.5,
        step_height=0.15,
        reporting_objectives=REPORTING_ASKS,
    )
    assert to_spec(bare)[0].to_dict() == to_spec(with_objectives)[0].to_dict()
    assert to_spec(bare)[1] == to_spec(with_objectives)[1]


def test_reporting_objectives_are_not_recorded_as_user_stated_physics():
    request = ForwardStepRequest(
        case_name="c", summary="x", mach=2.5, reporting_objectives=REPORTING_ASKS
    )
    _, provenance = to_spec(request)
    assert provenance["stated_by_user"] == ["mach"]


@pytest.mark.parametrize("text", REPORTING_ASKS)
def test_the_scope_gate_ignores_reporting_language(text):
    """The deterministic gate rules on simulation requirements only."""
    assert screen_request_text(text) == {}


def test_the_live_request_is_in_scope_with_its_reporting_sentence():
    spec = ForwardStep2DSpec(mach=2.5, step_height=0.15)
    result = evaluate_scope(spec, LIVE_REQUEST)
    assert result.approved
    assert result.decision == "IN_SCOPE"
    assert result.checks["request_text_in_family"] is True


def test_genuinely_unsupported_physics_is_still_caught():
    """Narrowing the flag must not disarm it."""
    for text in [
        "Include turbulence modelling with k-omega SST.",
        "Run this as a full three-dimensional case.",
        "Use a different solver, rhoCentralFoam.",
        "Add species transport and combustion.",
    ]:
        assert screen_request_text(text), text


def test_the_paper_walkthrough_request_is_in_scope():
    """Nothing in the walkthrough is turbulence or other out-of-family physics."""
    assert screen_request_text(PAPER_WALKTHROUGH_REQUEST) == {}
    spec = ForwardStep2DSpec(mach=2.0, step_height=0.2, step_x=0.6)
    result = evaluate_scope(spec, PAPER_WALKTHROUGH_REQUEST)
    assert result.approved, result.reasons
    assert result.decision == "IN_SCOPE"
    assert result.checks["request_text_in_family"] is True
    assert not result.clarification_needed
