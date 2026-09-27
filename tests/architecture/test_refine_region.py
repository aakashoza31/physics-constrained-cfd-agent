#!/usr/bin/env python3
"""Bounded REFINE_REGION: the LLM may name a region and nothing else."""
from __future__ import annotations

import pytest

from src.families.base import CRITERION_NOT_REGISTERED, Proposal
from src.families.refine_region import (
    ACTION,
    ADEQUATELY_RESOLVED,
    NOT_ESTABLISHED,
    UNDER_RESOLVED,
    RefineRegionPolicy,
    RegionSelection,
    refine_mesh_dict,
    rule_on_region_request,
    topo_set_dict,
)
from src.pipeline.forward_step_2d import regions as fs_regions

POLICY = RefineRegionPolicy()


def _selection(**kw):
    base = dict(
        name="shock", box_min=(0.1, 0.0, -0.1), box_max=(0.2, 1.0, 0.1),
        cell_count=1000, total_cells=16128, levels=1,
        derivation="test selection",
    )
    base.update(kw)
    return RegionSelection(**base)


# -- the LLM's bounded freedom ------------------------------------------
def test_region_hint_outside_the_closed_vocabulary_is_refused():
    r = rule_on_region_request(
        region_hint="wherever_the_solution_looks_wrong",
        vocabulary=fs_regions.CLOSED_VOCABULARY, selection=_selection(),
        resolution_verdict=UNDER_RESOLVED, policy=POLICY,
        levels_already_applied=0,
    )
    assert not r.approved
    assert "closed" in " ".join(r.reasons)


def test_unaudited_region_is_refused():
    r = rule_on_region_request(
        region_hint="shock", vocabulary=fs_regions.CLOSED_VOCABULARY,
        selection=_selection(derivation=""), resolution_verdict=UNDER_RESOLVED,
        policy=POLICY, levels_already_applied=0,
    )
    assert not r.approved and "derivation" in " ".join(r.reasons)


def test_no_region_detected_is_refused():
    r = rule_on_region_request(
        region_hint="shock", vocabulary=fs_regions.CLOSED_VOCABULARY,
        selection=None, resolution_verdict=UNDER_RESOLVED, policy=POLICY,
        levels_already_applied=0,
    )
    assert not r.approved and "no region" in " ".join(r.reasons)


# -- the scientific gate ------------------------------------------------
def test_unregistered_under_resolution_criterion_refuses_rather_than_guessing():
    r = rule_on_region_request(
        region_hint="shock", vocabulary=fs_regions.CLOSED_VOCABULARY,
        selection=_selection(), resolution_verdict=NOT_ESTABLISHED,
        policy=POLICY, levels_already_applied=0,
    )
    assert not r.approved
    assert CRITERION_NOT_REGISTERED in " ".join(r.reasons)


def test_adequately_resolved_region_is_refused():
    r = rule_on_region_request(
        region_hint="shock", vocabulary=fs_regions.CLOSED_VOCABULARY,
        selection=_selection(), resolution_verdict=ADEQUATELY_RESOLVED,
        policy=POLICY, levels_already_applied=0,
    )
    assert not r.approved and "adequately resolved" in " ".join(r.reasons)


# -- architectural bounds ----------------------------------------------
@pytest.mark.parametrize(
    "kw,expect",
    [
        ({"cell_count": 15000}, "global refinement"),
        ({"cell_count": 5}, "below"),
        ({"cell_count": 60000, "total_cells": 70000}, "global refinement"),
    ],
)
def test_region_size_bounds(kw, expect):
    r = rule_on_region_request(
        region_hint="shock", vocabulary=fs_regions.CLOSED_VOCABULARY,
        selection=_selection(**kw), resolution_verdict=UNDER_RESOLVED,
        policy=POLICY, levels_already_applied=0,
    )
    assert not r.approved
    assert expect in " ".join(r.reasons)


def test_level_cap_is_enforced():
    r = rule_on_region_request(
        region_hint="shock", vocabulary=fs_regions.CLOSED_VOCABULARY,
        selection=_selection(), resolution_verdict=UNDER_RESOLVED,
        policy=POLICY, levels_already_applied=POLICY.max_levels,
    )
    assert not r.approved and "level cap" in " ".join(r.reasons)


def test_cell_ceiling_is_enforced():
    policy = RefineRegionPolicy(max_total_cells=20000)
    r = rule_on_region_request(
        region_hint="shock", vocabulary=fs_regions.CLOSED_VOCABULARY,
        selection=_selection(cell_count=4000), resolution_verdict=UNDER_RESOLVED,
        policy=policy, levels_already_applied=0,
    )
    assert not r.approved and "ceiling" in " ".join(r.reasons)


def test_an_admissible_request_is_approved_and_reports_the_projection():
    r = rule_on_region_request(
        region_hint="shock", vocabulary=fs_regions.CLOSED_VOCABULARY,
        selection=_selection(cell_count=1200), resolution_verdict=UNDER_RESOLVED,
        policy=POLICY, levels_already_applied=0,
    )
    assert r.approved
    assert r.resulting_changes["region"]["projected_cells"] == 16128 + 1200 * 3
    assert "deterministically" in " ".join(r.reasons)


# -- deterministic region detection on the real family -----------------
def test_shock_region_is_located_from_a_measured_quantity(fs_spec, fs_evidence):
    sel = fs_regions.select_region(
        fs_regions.SHOCK, fs_spec, fs_evidence["raw_diagnostics"]
    )
    if not fs_evidence["raw_diagnostics"].get("shock", {}).get("available"):
        pytest.skip("synthetic case exposes no measurable front")
    assert sel is not None
    assert "upper_stem_x" in sel.derivation
    assert sel.cell_count > 0
    assert 0.0 < sel.fraction < 1.0
    assert sel.box_max[0] > sel.box_min[0]


def test_step_corner_region_is_located_from_spec_geometry(fs_spec, fs_evidence):
    sel = fs_regions.select_region(
        fs_regions.STEP_CORNER, fs_spec, fs_evidence["raw_diagnostics"]
    )
    assert sel is not None
    assert "step corner" in sel.derivation
    assert sel.box_min[0] <= fs_spec.step_x <= sel.box_max[0]


def test_family_reports_the_criterion_as_unregistered(fs_spec, fs_evidence):
    assert fs_regions.resolution_verdict(
        fs_regions.SHOCK, fs_spec, fs_evidence["raw_diagnostics"]
    ) == NOT_ESTABLISHED
    status = fs_regions.criterion_status()
    assert status["registered"] is False
    assert "REFINE_REGION is refused" in status["consequence"]


def test_adapter_refuses_refine_region_end_to_end(fs_adapter, fs_spec, fs_evidence):
    ruling = fs_adapter.execute_action(
        ACTION, fs_spec, fs_evidence,
        proposal=Proposal("MESH_PROBLEM", ACTION, region_hint=fs_regions.SHOCK),
    )
    assert not ruling.approved
    assert CRITERION_NOT_REGISTERED in " ".join(ruling.reasons)


def test_adapter_refuses_an_arbitrary_region_name(fs_adapter, fs_spec, fs_evidence):
    ruling = fs_adapter.execute_action(
        ACTION, fs_spec, fs_evidence,
        proposal=Proposal("MESH_PROBLEM", ACTION, region_hint="cells_42_to_99"),
    )
    assert not ruling.approved and "closed" in " ".join(ruling.reasons)


# -- dictionary emission -----------------------------------------------
def test_topo_set_dict_contains_only_deterministic_coordinates():
    text = topo_set_dict(_selection())
    assert "boxToCell" in text and "cellSet" in text
    assert "0.1" in text and "0.2" in text
    assert "GENERATED" in text and "no LLM-authored values" in text


def test_refine_mesh_dict_keeps_a_2d_family_planar():
    text = refine_mesh_dict()
    assert "directions      ( tan1 tan2 )" in text
    assert "tan3" not in text
