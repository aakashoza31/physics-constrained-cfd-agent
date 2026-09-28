#!/usr/bin/env python3
"""Family 3 inside the frozen shared architecture. No CFD, no OpenFOAM."""
from __future__ import annotations

import json

import pytest

from src.families import registry
from src.families.airfoil.adapter import GATES, AirfoilAdapter
from src.families.airfoil.recipe import RECIPE, REGION_VOCABULARY
from src.families.airfoil.spec import AirfoilSpec
from src.families.base import CRITERION_NOT_REGISTERED, NO_REGISTERED_FAMILY, REJECT
from src.families.refine_region import ACTION as REFINE_REGION
from src.pipeline.airfoil import build as builder
from src.pipeline.airfoil import execute as executor
from src.router.route import route


# -- status and routing ------------------------------------------------
def test_family_is_core_pending_and_not_routable():
    registry.install_standing_register()
    record = registry.get("airfoil")
    assert record.status == "CORE-PENDING"
    assert record.routable is False
    assert record.inspectable is True


def test_pending_family_cannot_route_for_execution():
    registry.install_standing_register()
    result = route("NACA0012 at zero incidence, Re 6 million",
                   propose=lambda t, m: "airfoil")
    assert result.approved is False
    assert NO_REGISTERED_FAMILY in result.decision
    assert "not executable" in " ".join(result.reasons)


def test_adapter_is_refused_for_execution_but_available_for_inspection():
    registry.install_standing_register()
    assert registry.adapter("airfoil") is not None
    with pytest.raises(PermissionError):
        registry.adapter("airfoil", for_execution=True)


def test_f1_and_f2_remain_core():
    registry.install_standing_register()
    assert registry.get("nozzle").status == "CORE"
    assert registry.get("forward_step_2d").status == "CORE"
    assert set(registry.routable_names()) == {"nozzle", "forward_step_2d"}


# -- readiness gates ---------------------------------------------------
def test_four_readiness_gates_are_declared():
    assert GATES == ("registered_assets", "mesh_hierarchy_qualified",
                     "coarse_pilot_sane", "canonical_validation")


def test_readiness_is_open_until_the_gates_close(fake_repo):
    readiness = AirfoilAdapter.readiness(fake_repo)
    assert readiness["ready_for_core"] is False
    assert set(readiness["open_gates"]) == set(GATES)


def test_assets_gate_closes_once_registered(installed_assets):
    readiness = AirfoilAdapter.readiness(installed_assets)
    assert readiness["gates"]["registered_assets"] is True
    # The other three remain open: registration alone is not closure.
    assert set(readiness["open_gates"]) == {
        "mesh_hierarchy_qualified", "coarse_pilot_sane", "canonical_validation"
    }


def test_scope_gate_refuses_while_any_gate_is_open(fake_repo):
    result = AirfoilAdapter().check_scope(AirfoilSpec())
    assert result.approved is False
    assert CRITERION_NOT_REGISTERED in result.decision
    assert "CORE-PENDING" in " ".join(result.reasons)


def test_scope_gate_refuses_an_out_of_envelope_incidence():
    result = AirfoilAdapter().check_scope(AirfoilSpec(alpha_deg=18.0))
    assert result.approved is False
    assert result.checks["alpha_in_envelope"] is False
    assert "pre-stall envelope" in " ".join(result.reasons)


def test_scope_gate_refuses_a_foreign_spec():
    result = AirfoilAdapter().check_scope(object())
    assert result.approved is False
    assert "OUT_OF_FAMILY" in result.decision


# -- REFINE_REGION stays disabled --------------------------------------
def test_refine_region_is_declared_but_unavailable():
    assert REFINE_REGION in RECIPE.allowed_actions
    assert RECIPE.region_vocabulary == REGION_VOCABULARY
    blocked = RECIPE.unresolved_capabilities()
    assert REFINE_REGION in blocked
    assert not RECIPE.capability_available(REFINE_REGION)


def test_refine_region_refuses_rather_than_inventing_a_trigger():
    from src.families.base import Proposal

    ruling = AirfoilAdapter().execute_action(
        REFINE_REGION, AirfoilSpec(), {},
        proposal=Proposal("MESH_RESOLUTION", REFINE_REGION,
                          region_hint="leading_edge"),
    )
    assert ruling.approved is False
    assert CRITERION_NOT_REGISTERED in " ".join(ruling.reasons)


def test_an_arbitrary_region_name_is_refused():
    from src.families.base import Proposal

    ruling = AirfoilAdapter().execute_action(
        REFINE_REGION, AirfoilSpec(), {},
        proposal=Proposal("MESH_RESOLUTION", REFINE_REGION,
                          region_hint="wherever_yplus_is_high"),
    )
    assert ruling.approved is False
    assert "closed" in " ".join(ruling.reasons)


def test_acceptance_recipe_is_registered_so_the_family_can_in_principle_accept():
    assert RECIPE.is_registered()
    assert RECIPE.unresolved() == []


def test_an_unlisted_action_is_refused():
    ruling = AirfoilAdapter().execute_action("REFINE_MESH", AirfoilSpec(), {})
    assert ruling.approved is False
    assert "bounded action set" in " ".join(ruling.reasons)


# -- case generation ---------------------------------------------------
def test_build_refuses_without_the_converted_registered_mesh(tmp_path):
    with pytest.raises(FileNotFoundError) as exc:
        AirfoilAdapter().build_case(AirfoilSpec(), tmp_path / "case")
    assert "never generates geometry" in str(exc.value)


def test_case_dictionaries_carry_the_frozen_recipe(tmp_path):
    mesh = tmp_path / "grid.msh"
    mesh.write_text("$MeshFormat\n2.2 0 8\n$EndMeshFormat\n")
    case = builder.build(AirfoilSpec(), tmp_path / "case", mesh)

    momentum = (case / "constant/momentumTransport").read_text()
    assert "kOmegaSST" in momentum
    assert "alphaK1       0.85;" in momentum
    assert "gamma1        0.555555555556;" in momentum
    assert "F3            false;" in momentum
    # The dictionary states the model is native v14 and disclaims SSTm emulation;
    # what must be absent is an SSTm MODEL SELECTION, not the word in a comment.
    assert "model           kOmegaSST;" in momentum
    assert "NOT an SSTm" in momentum
    selections = [l for l in momentum.splitlines()
                  if l.strip().startswith("model") and not l.strip().startswith("//")]
    assert selections == ["    model           kOmegaSST;   // native Foundation v14"]

    physical = (case / "constant/physicalProperties").read_text()
    assert "1.66666666667e-07" in physical
    assert "Mach and temperature are not solved" in physical

    schemes = (case / "system/fvSchemes").read_text()
    assert "bounded Gauss linearUpwind grad(U)" in schemes
    assert "bounded Gauss limitedLinear 1" in schemes
    assert "corrected" in schemes
    assert "upwind;" not in schemes.replace("linearUpwind", "")

    solution = (case / "system/fvSolution").read_text()
    assert "GAMG" in solution and "smoothSolver" in solution
    assert "p               0.3;" in solution
    assert "U               0.7;" in solution

    control = (case / "system/controlDict").read_text()
    assert "solver          incompressibleFluid;" in control

    assert (case / "grid.msh").exists()
    assert json.loads((case / "spec.json").read_text())["nu"] == AirfoilSpec().nu


def test_boundary_conditions_as_frozen(tmp_path):
    mesh = tmp_path / "g.msh"
    mesh.write_text("$MeshFormat\n2.2 0 8\n$EndMeshFormat\n")
    case = builder.build(AirfoilSpec(), tmp_path / "case", mesh)

    u = (case / "0/U").read_text()
    assert "noSlip" in u and "freestreamVelocity" in u and "empty" in u
    assert "(1 0 0)" in u                      # alpha = 0 freestream

    p = (case / "0/p").read_text()
    assert "zeroGradient" in p and "freestreamPressure" in p

    k = (case / "0/k").read_text()
    assert "fixedValue" in k and "uniform 0;" in k
    assert "4.056e-07" in k

    omega = (case / "0/omega").read_text()
    assert "omegaWallFunction" in omega
    assert "blended         false;" in omega
    assert "beta1           0.075;" in omega
    assert "270.4" in omega

    nut = (case / "0/nut").read_text()
    assert "nutLowReWallFunction" in nut


def test_incidence_appears_only_in_the_freestream_vector(tmp_path):
    for n, alpha in enumerate((0.0, 10.0)):
        mesh = tmp_path / f"g{n}.msh"
        mesh.write_text("$MeshFormat\n2.2 0 8\n$EndMeshFormat\n")
        case = builder.build(AirfoilSpec(alpha_deg=alpha), tmp_path / f"c{n}", mesh)
        copied = case / mesh.name
        u = (case / "0/U").read_text()
        if alpha == 0.0:
            assert "(1 0 0)" in u
        else:
            assert "0.984807753012" in u and "0.173648177667" in u
        # No geometry file differs between incidences.
        assert copied.read_bytes() == mesh.read_bytes()


# -- execution is gated ------------------------------------------------
def test_execute_refuses_without_explicit_permission(tmp_path):
    with pytest.raises(executor.ExecutionRefused) as exc:
        executor.execute(tmp_path)
    assert "allow_cfd=True" in str(exc.value)


def test_execute_refuses_when_preconditions_are_open(tmp_path, fake_repo):
    with pytest.raises(executor.ExecutionRefused) as exc:
        executor.execute(tmp_path, allow_cfd=True, repo_root=fake_repo,
                         runner=lambda cmd: 0)
    assert "preconditions not satisfied" in str(exc.value)


def test_shared_loop_cannot_launch_this_family(tmp_path):
    with pytest.raises(executor.ExecutionRefused) as exc:
        AirfoilAdapter().run_case(tmp_path)
    assert "allow_cfd=True" in str(exc.value)


def test_solver_stage_is_last_and_named(tmp_path, installed_assets):
    assert executor.SOLVER_STAGE.startswith("foamRun -solver incompressibleFluid")
    assert "checkMesh" in " ".join(executor.MESH_STAGES)
    assert "foamRun" not in " ".join(executor.MESH_STAGES)


# -- spec / evidence hooks --------------------------------------------
def test_load_spec_round_trips(tmp_path):
    spec = AirfoilSpec(alpha_deg=10.0)
    (tmp_path / "spec.json").write_text(json.dumps(spec.to_dict()))
    assert AirfoilAdapter().load_spec(tmp_path).to_dict() == spec.to_dict()


def test_evidence_schema_names_every_shared_section():
    schema = AirfoilAdapter.evidence_schema()
    for section in ("family", "spec", "mesh", "solver", "conservation",
                    "stationarity", "quantitative", "provenance"):
        assert section in schema


def test_validate_reports_readiness_and_blocked_capabilities():
    result = AirfoilAdapter().validate({}, AirfoilSpec())
    assert set(result["readiness"]) == set(GATES)
    assert REFINE_REGION in result["blocked_capabilities"]
    assert "not an exact NASA-code reproduction" in result["provenance_note"]
