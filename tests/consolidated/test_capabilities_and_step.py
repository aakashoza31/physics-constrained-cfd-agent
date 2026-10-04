#!/usr/bin/env python3
"""Capability declarations are promises; STEP input is refused, not faked."""
from __future__ import annotations

from pathlib import Path

import pytest

from src.families import capabilities as caps
from src.geometry import features as geom
from src.geometry import matching, step_reader

STEP_SAMPLE = """ISO-10303-21;
HEADER;
FILE_DESCRIPTION(('a test part'),'2;1');
FILE_NAME('part.step','2026-01-01T00:00:00',(''),(''),'','','');
FILE_SCHEMA(('AUTOMOTIVE_DESIGN { 1 0 10303 214 }'));
ENDSEC;
DATA;
#1=CARTESIAN_POINT('',(0.,0.,0.));
#2=MANIFOLD_SOLID_BREP('',#1);
ENDSEC;
END-ISO-10303-21;
"""


def test_no_family_advertises_step_support():
    """If this ever fails, a STEP meshing path must exist to back it."""
    assert caps.step_capable_families() == ()
    for capability in caps.TABLE.values():
        assert capability.geometry_inputs.step is False
        assert capability.geometry_inputs.step_note


def test_only_accepted_families_are_routable():
    assert caps.ROUTABLE == ("nozzle", "forward_step_2d")
    assert caps.TABLE["cube"].status == caps.SUPPLEMENTARY
    assert caps.TABLE["cube"].routable is False
    assert caps.TABLE["airfoil"].status == caps.SUPPLEMENTARY
    assert caps.TABLE["airfoil"].routable is False


def test_the_cube_declaration_says_it_is_supplementary():
    note = caps.TABLE["cube"].notes.lower()
    assert "exploratory" in note
    assert "not a validated benchmark result" in note


def test_the_airfoil_declaration_says_no_cfd_was_run():
    capability = caps.TABLE["airfoil"]
    assert "no cfd was ever run" in capability.notes.lower()
    assert capability.solver == "not executed"


def test_step_header_is_read_as_text(tmp_path):
    """Header parsing needs no kernel, and claims nothing about the solid."""
    path = tmp_path / "part.step"
    path.write_text(STEP_SAMPLE)
    step = step_reader.read_step(path)
    assert step.status == step_reader.OK
    assert "AUTOMOTIVE_DESIGN" in step.schema
    assert step.entity_counts["CARTESIAN_POINT"] == 1
    # Nothing was extracted, so nothing is claimed -- and this holds whether or
    # not a CAD kernel happens to be importable in this environment.
    assert step.geometry is None
    assert step.readable_geometry is False


def test_an_importable_kernel_is_not_geometry(tmp_path, monkeypatch):
    """The decisive check: a kernel on the path must not flip the answer."""
    path = tmp_path / "part.step"
    path.write_text(STEP_SAMPLE)
    monkeypatch.setattr(step_reader, "available_backends",
                        lambda: ["OCP", "cadquery"])
    step = step_reader.read_step(path)
    assert step.backends_present == ["OCP", "cadquery"]
    assert step.geometry is None
    assert step.readable_geometry is False           # still false
    assert "not geometry" in step.note
    features = geom.from_step(path)
    assert features.status == geom.UNSUPPORTED
    assert features.usable is False
    assert features.dimensions == {}


def test_readable_geometry_is_true_only_when_geometry_exists(tmp_path):
    """Constructed directly: the property answers about geometry, nothing else."""
    step = step_reader.StepFile(path=tmp_path / "p.step", status=step_reader.OK,
                                backends_present=["OCP"])
    assert step.readable_geometry is False
    step.geometry = {"bounding_box_x": 0.12}
    step.extracted_by = "OCP"
    assert step.readable_geometry is True
    assert step.to_dict()["geometry_extracted"] is True


def test_a_non_step_file_is_refused(tmp_path):
    path = tmp_path / "not.step"
    path.write_text("this is not a STEP file")
    assert step_reader.read_step(path).status == step_reader.NOT_A_STEP_FILE


@pytest.mark.parametrize("backends", [[], ["OCP"], ["OCC", "cadquery"]])
def test_step_features_are_unsupported_whatever_is_installed(tmp_path, monkeypatch,
                                                             backends):
    """Portable: the public answer is UNSUPPORTED in every environment."""
    path = tmp_path / "part.step"
    path.write_text(STEP_SAMPLE)
    monkeypatch.setattr(step_reader, "available_backends", lambda: backends)
    features = geom.from_step(path)
    assert features.status == geom.UNSUPPORTED
    assert features.usable is False
    assert features.dimensions == {}
    assert features.characteristic_dimension is None
    result = matching.match(features, proposed="nozzle")
    assert result["selected_family"] is None
    assert result["admissible_families"] == []


def test_step_features_are_unsupported_and_nothing_is_invented(tmp_path):
    path = tmp_path / "part.step"
    path.write_text(STEP_SAMPLE)
    features = geom.from_step(path)
    assert features.status == geom.UNSUPPORTED
    assert features.usable is False
    assert features.dimensions == {}
    assert features.characteristic_dimension is None
    assert features.reason


def test_no_family_accepts_a_step_part(tmp_path):
    path = tmp_path / "part.step"
    path.write_text(STEP_SAMPLE)
    result = matching.match(geom.from_step(path), proposed="nozzle")
    assert result["selected_family"] is None
    assert result["admissible_families"] == []
    assert result["evaluations"]["nozzle"]["status"] == matching.UNSUPPORTED_SOURCE


def test_parametric_geometry_is_normalised_by_the_characteristic_dimension():
    features = geom.from_parameters(
        {"throat_radius": 0.01, "exit_radius": 0.03},
        characteristic_name="throat_radius")
    result = matching.admissible("nozzle", features)
    assert result.admissible
    assert result.normalised["exit_radius_over_throat_radius"] == pytest.approx(3.0)


def test_an_unknown_family_is_refused():
    features = geom.from_parameters({"x": 1.0}, characteristic_name="x")
    assert matching.admissible("plasma", features).status == matching.NO_FAMILY


def test_declared_action_vocabularies_are_the_paper_enums():
    """The capability table advertises exactly the actions the validators know."""
    from src.contracts.agent_decision import AgentAction
    from src.reasoning.forward_step_actions import ForwardStepAction

    assert caps.TABLE["nozzle"].allowed_actions == tuple(a.value for a in AgentAction)
    assert caps.TABLE["forward_step_2d"].allowed_actions == tuple(
        a.value for a in ForwardStepAction)
    assert set(caps.TABLE["nozzle"].allowed_actions) == {
        "ACCEPT", "CONTINUE_RUN", "REQUEST_DIAGNOSTIC", "REFINE_THROAT",
        "REFINE_GRADIENT_REGION", "REPAIR_MESH", "RESTART_CLEAN",
        "REJECT_OUTSIDE_DOMAIN"}
    assert set(caps.TABLE["forward_step_2d"].allowed_actions) == {
        "ACCEPT", "CONTINUE_RUN", "EXTEND_END_TIME", "REDUCE_MAX_CO",
        "REFINE_MESH", "REBUILD_FROM_VALIDATED_SPEC", "REQUEST_CLARIFICATION",
        "REJECT_UNSUPPORTED", "FAIL_SAFELY"}


MODEL_CALLERS = ("src.agents.cfd_visual_observer",
                 "src.reasoning.forward_step_diagnosis",
                 "src.reasoning.nozzle_diagnosis")


@pytest.mark.parametrize("module_name", MODEL_CALLERS)
def test_observer_and_diagnosis_share_one_model_default(module_name, monkeypatch):
    import importlib

    from src.agents import llm_provenance

    module = importlib.import_module(module_name)
    assert module.gemini_model_name is llm_provenance.gemini_model_name
    monkeypatch.delenv("GEMINI_MODEL", raising=False)
    assert module.gemini_model_name() == "gemini-3.5-flash-lite"
    assert llm_provenance.DEFAULT_GEMINI_MODEL == "gemini-3.5-flash-lite"
    monkeypatch.setenv("GEMINI_MODEL", "some-other-model")
    assert module.gemini_model_name() == "some-other-model"
    source = Path(module.__file__).read_text(encoding="utf-8")
    assert 'getenv("GEMINI_MODEL"' not in source
