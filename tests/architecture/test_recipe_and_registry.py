#!/usr/bin/env python3
"""The structural guarantee: an unregistered criterion cannot become an ACCEPT."""
from __future__ import annotations

import pytest

from src.families import registry
from src.families.base import (
    ACCEPT,
    CORE,
    CORE_PENDING,
    CRITERION_NOT_REGISTERED,
    INCONCLUSIVE,
    NONACCEPTED,
    SUPPORTING,
    TODO,
    is_unresolved,
)
from src.families.recipe import FamilyRecipe


def test_todo_sentinel_is_falsy_and_named():
    t = TODO("airfoil.CL_tolerance", "awaiting reference")
    assert is_unresolved(t)
    assert not t
    assert t.name == "airfoil.CL_tolerance"
    assert "awaiting" in t.note


def test_recipe_enumerates_unresolved_across_all_sections():
    r = FamilyRecipe(
        family="x", physics="y", reference="z",
        numerics={"model": TODO("x.model", "n")},
        bounds={"aoa": (0.0, TODO("x.aoa_hi", "n"))},
        tolerances={"CL": TODO("x.CL", "n"), "resid": 1e-6},
        reference_values={"CL": TODO("x.CL_ref", "n")},
    )
    assert r.unresolved() == [
        "bounds.aoa", "numerics.model", "reference_values.CL", "tolerances.CL"
    ]
    assert not r.is_registered()
    assert {d["constant"] for d in r.unresolved_detail()} == set(r.unresolved())


def test_fully_registered_recipe_reports_clean():
    r = FamilyRecipe(family="x", physics="y", reference="z",
                     tolerances={"resid": 1e-6})
    assert r.is_registered() and r.unresolved() == []


def test_recipe_to_dict_renders_todos_visibly():
    r = FamilyRecipe(family="x", physics="y", reference="z",
                     tolerances={"CL": TODO("x.CL", "awaiting Astra")})
    d = r.to_dict()
    assert d["tolerances"]["CL"] == {"TODO": "x.CL", "awaiting": "awaiting Astra"}
    assert d["registered"] is False


def test_standing_register_has_the_declared_statuses():
    registry.install_standing_register()
    expected = {
        "nozzle": CORE,
        "forward_step_2d": CORE,
        "airfoil": CORE_PENDING,
        "backward_step": CORE_PENDING,
        "square_duct": SUPPORTING,
        "cube": NONACCEPTED,
    }
    for name, status in expected.items():
        record = registry.get(name)
        assert record is not None, f"{name} is not registered"
        assert record.status == status, f"{name}: {record.status} != {status}"


def test_square_duct_is_preserved_as_supporting_evidence_not_deleted():
    registry.install_standing_register()
    r = registry.get("square_duct")
    assert r.status == SUPPORTING
    assert not r.routable, "a SUPPORTING family must not be routable"
    assert "cross-version" in r.retained_as
    assert r.evidence_root and "family3_square_duct_audit" in r.evidence_root
    assert "v2006" in r.description and "v14" in r.description


def test_cube_is_preserved_as_nonaccepted_stress_test():
    registry.install_standing_register()
    r = registry.get("cube")
    assert r.status == NONACCEPTED
    assert not r.routable
    assert "stationarity" in r.retained_as
    # Evidence path is allowed to be TODO and must not block anything.
    assert r.evidence_root == "TODO"


def test_only_core_families_are_routable():
    registry.install_standing_register()
    assert set(registry.routable_names()) == {"nozzle", "forward_step_2d"}


def test_pending_families_are_visible_but_not_executable():
    registry.install_standing_register()
    pending = {r.name for r in registry.pending_families()}
    assert pending == {"airfoil", "backward_step"}
    for name in pending:
        record = registry.get(name)
        assert record is not None, "must stay visible in the register"
        assert record.status == CORE_PENDING
        assert not record.routable, "a pending family must not be routable"
        assert record.inspectable, "its recipe must remain inspectable"
        # Constructible for inspection...
        assert registry.adapter(name) is not None
        # ...but refused for execution.
        with pytest.raises(PermissionError) as exc:
            registry.adapter(name, for_execution=True)
        assert "not executable" in str(exc.value)
        assert "recipe is not registered" in str(exc.value)


def test_non_core_evidence_families_have_no_adapter_at_all():
    registry.install_standing_register()
    for name in ("square_duct", "cube"):
        assert not registry.get(name).inspectable
        with pytest.raises(KeyError):
            registry.adapter(name)


@pytest.mark.parametrize("family", ["airfoil", "backward_step"])
def test_pending_families_cannot_accept(family):
    registry.install_standing_register()
    adapter = registry.adapter(family)
    assert not adapter.recipe.is_registered()
    validation = adapter.validate({}, None)
    assert validation["status"] == CRITERION_NOT_REGISTERED
    assert adapter.maps_to_decision(validation) == INCONCLUSIVE
    assert adapter.maps_to_decision(validation) != ACCEPT


@pytest.mark.parametrize("family", ["airfoil", "backward_step"])
def test_pending_family_scope_gate_fails_closed(family):
    registry.install_standing_register()
    adapter = registry.adapter(family)
    scope = adapter.check_scope(None)
    assert scope.approved is False
    assert CRITERION_NOT_REGISTERED in scope.decision


@pytest.mark.parametrize("family", ["airfoil", "backward_step"])
def test_pending_family_spec_refuses_to_be_built_from_guesses(family):
    from importlib import import_module

    spec_cls = [
        v for v in vars(import_module(f"src.families.{family}.spec")).values()
        if hasattr(v, "__dataclass_fields__")
    ][0]
    with pytest.raises(ValueError):
        spec_cls()
