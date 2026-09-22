"""Tests for the standalone 2D forward-step agent.

No test in this file launches OpenFOAM. The CFD-dependent behaviour is
exercised against a synthetic case whose file layout matches a real run
(tests/forward_step_2d/synthetic.py), so parsing, arithmetic and validator
branches are covered without a solver.
"""
from __future__ import annotations

import json
import re
import sys
import tempfile
from pathlib import Path

import numpy as np
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from src.pipeline.forward_step_2d import build as build_mod  # noqa: E402
from src.pipeline.forward_step_2d.build import TEMPLATE, build, fixed_recipe_unchanged  # noqa: E402
from src.pipeline.forward_step_2d.collect_evidence import collect  # noqa: E402
from src.pipeline.forward_step_2d.diagnostics import (  # noqa: E402
    Layout,
    transient_balance,
)
from src.pipeline.forward_step_2d.spec import (  # noqa: E402
    CANONICAL_CELLS,
    CANONICAL_SPEC,
    MAX_CELLS,
    ForwardStep2DSpec,
)
from src.pipeline.forward_step_2d.validate import validate  # noqa: E402
from src.reasoning.forward_step_actions import (  # noqa: E402
    ForwardStepAction,
    validate_action,
)
from src.reasoning.forward_step_diagnosis import build_evidence_payload  # noqa: E402
from src.reasoning.forward_step_scope_gate import evaluate_scope  # noqa: E402
from tests.forward_step_2d.synthetic import make_case  # noqa: E402

NONCANONICAL = ForwardStep2DSpec(mach=2.5, step_height=0.15)


# ----------------------------------------------------------------------
# specification
# ----------------------------------------------------------------------


def test_canonical_spec_reproduces_the_tutorial_case():
    s = CANONICAL_SPEC
    assert s.splits == (48, 16)
    assert s.cells == CANONICAL_CELLS == 16128
    assert s.block_cells == [768, 3072, 12288]
    assert s.dx == pytest.approx(0.0125)
    assert s.dy == pytest.approx(0.0125)
    assert s.velocity == 3.0
    assert s.realized_mach == pytest.approx(3.0, rel=1e-5)
    assert s.is_canonical


def test_generated_mesh_matches_the_frozen_template():
    """The trusted tutorial mesh must be reproduced exactly, not approximately."""

    def parse(text):
        block = re.search(r"vertices\s*\((.*?)\);", text, re.S)[1]
        verts = [
            tuple(float(v) for v in m.split())
            for m in re.findall(r"\(([^()]+)\)", block)
        ]
        blocks = re.findall(r"hex \([^)]*\)\s*\((\d+)\s+(\d+)\s+(\d+)\)", text)
        return verts, [tuple(int(v) for v in b) for b in blocks]

    tv, tb = parse((TEMPLATE / "system/blockMeshDict").read_text())
    gv, gb = parse(build_mod.mesh_dictionary(CANONICAL_SPEC))

    assert gv == tv
    assert gb == tb == [(48, 16, 1), (48, 64, 1), (192, 64, 1)]
    assert sum(a * b * c for a, b, c in tb) == CANONICAL_CELLS


def test_spec_round_trips_and_rejects_unknown_keys():
    data = NONCANONICAL.to_dict()
    assert ForwardStep2DSpec.from_dict(data).to_dict() == data

    with pytest.raises(ValueError, match="Unsupported specification keys"):
        ForwardStep2DSpec.from_dict({**data, "turbulence_model": "kOmegaSST"})


@pytest.mark.parametrize(
    "changes, message",
    [
        ({"mach": 0.8}, "supersonic"),
        ({"step_height": 1.2}, "strictly below"),
        ({"step_x": 3.5}, "strictly inside"),
        ({"max_co": 0.4}, "trusted 0.2"),
        ({"end_time": -1.0}, "positive"),
        ({"nx": 1}, "integer >= 2"),
        ({"write_interval": 99.0}, "must not exceed end_time"),
        ({"family": "cavity"}, "forward-step family"),
    ],
)
def test_invalid_specifications_are_refused(changes, message):
    with pytest.raises(ValueError, match=message):
        ForwardStep2DSpec.from_dict({**CANONICAL_SPEC.to_dict(), **changes})


def test_cell_count_is_bounded():
    with pytest.raises(ValueError, match="exceeds"):
        ForwardStep2DSpec(nx=2000, ny=700)


# ----------------------------------------------------------------------
# case generation / parameter propagation
# ----------------------------------------------------------------------


def test_parameters_propagate_into_the_generated_case(tmp_path):
    spec = ForwardStep2DSpec(
        mach=2.5, step_height=0.15, nx=120, ny=40, end_time=1.5,
        max_co=0.15, write_interval=0.25,
    )
    case = build(spec, tmp_path / "case")

    control = (case / "system/controlDict").read_text()
    assert "endTime 1.5;" in control
    assert "maxCo 0.15;" in control
    assert "writeInterval 0.25;" in control
    assert "solver          shockFluid;" in control

    mesh = (case / "system/blockMeshDict").read_text()
    a, b = spec.splits
    assert f"({a} {b} 1)" in mesh
    assert "type empty;" in mesh
    assert "cyclic" not in mesh

    assert "internalField   uniform (2.5 0 0);" in (case / "0/U").read_text()
    assert "internalField   uniform 1;" in (case / "0/p").read_text()
    assert json.loads((case / "spec.json").read_text())["mach"] == 2.5


def test_fixed_recipe_is_copied_unchanged(tmp_path):
    case = build(NONCANONICAL, tmp_path / "case")
    assert fixed_recipe_unchanged(case)

    hashes = json.loads((case / "template_hashes.json").read_text())
    assert "system/fvSchemes" in hashes

    schemes = (case / "system/fvSchemes").read_text()
    assert "Kurganov" in schemes and "vanLeerV" in schemes

    # tamper -> detected
    (case / "system/fvSchemes").write_text(schemes.replace("Kurganov", "Tadmor"))
    assert not fixed_recipe_unchanged(case)


def test_build_refuses_to_overwrite_and_never_touches_the_template(tmp_path):
    before = {
        p: p.read_bytes() for p in TEMPLATE.rglob("*") if p.is_file()
    }
    case = build(NONCANONICAL, tmp_path / "case")
    with pytest.raises(FileExistsError):
        build(NONCANONICAL, case)
    assert all(p.read_bytes() == data for p, data in before.items())


def test_flux_monitors_cover_every_real_patch(tmp_path):
    case = build(NONCANONICAL, tmp_path / "case")
    control = (case / "system/controlDict").read_text()
    for patch in ["inlet", "outlet", "bottom", "top", "obstacle"]:
        assert f"flux_{patch}" in control
    assert "flux_defaultFaces" not in control
    assert "flux_spanMinus" not in control


# ----------------------------------------------------------------------
# scope gate
# ----------------------------------------------------------------------


def test_canonical_and_noncanonical_requests_are_in_scope():
    assert evaluate_scope(CANONICAL_SPEC).approved
    result = evaluate_scope(
        NONCANONICAL, "2D forward-facing step at Mach 2.5 with step height 0.15"
    )
    assert result.approved, result.reasons
    assert result.decision == "IN_SCOPE"


@pytest.mark.parametrize(
    "text",
    [
        "run the forward step in 3D with spanwise extrusion",
        "import my STEP file and mesh it",
        "use rhoCentralFoam instead",
        "switch the flux to a second order scheme",
        "simulate subsonic flow over the step",
    ],
)
def test_out_of_family_requests_are_rejected(text):
    result = evaluate_scope(CANONICAL_SPEC, text)
    assert not result.approved
    assert result.decision == "REJECT_UNSUPPORTED"


def test_viscous_wording_asks_for_clarification_rather_than_rejecting():
    result = evaluate_scope(
        CANONICAL_SPEC, "forward step, please resolve the boundary layer"
    )
    assert result.clarification_needed
    assert any("inviscid" in q for q in result.clarification_needed)


def test_out_of_envelope_values_are_rejected():
    assert not evaluate_scope(ForwardStep2DSpec(mach=8.0)).approved
    assert not evaluate_scope(ForwardStep2DSpec(end_time=20.0)).approved


# ----------------------------------------------------------------------
# conservation arithmetic
# ----------------------------------------------------------------------


def test_transient_balance_is_exact_for_a_consistent_history():
    t = np.linspace(0, 1, 11)
    inlet = np.full_like(t, -0.5)
    outlet = np.full_like(t, 0.3)
    zero = np.zeros_like(t)
    net = inlet + outlet  # -0.2 net outward -> mass grows at 0.2 per unit time
    mass = 1.0 + 0.2 * t

    summary, table = transient_balance(
        t, mass, {"inlet": inlet, "outlet": outlet, "bottom": zero, "top": zero, "obstacle": zero}
    )
    assert summary["relative_residual_max"] == pytest.approx(0.0, abs=1e-12)
    assert summary["impermeable_flux_max_abs"] == 0.0
    assert summary["final_inlet"] == pytest.approx(0.5)
    assert table.shape[1] == 6


def test_storage_is_not_confused_with_a_steady_mismatch():
    """A net boundary flux with matching storage is conservative, not a defect."""
    t = np.array([0.0, 1e-3, 2e-3])
    inlet = np.array([-0.42, -0.42, -0.42])
    outlet = np.array([0.40, 0.40, 0.40])
    zero = np.zeros(3)
    mass = np.array([0.63, 0.63 + 0.02e-3, 0.63 + 0.04e-3])
    summary, _ = transient_balance(
        t, mass, {"inlet": inlet, "outlet": outlet, "bottom": zero, "top": zero, "obstacle": zero}
    )
    assert summary["relative_residual_max"] < 1e-12
    assert abs(summary["instantaneous_mismatch_fraction"]) > 0.04


def test_layout_refuses_a_three_dimensional_field():
    xyz = np.array([[0.0, 0.0, -0.05], [0.0, 0.0, 0.05]])
    with pytest.raises(ValueError, match="planar"):
        Layout(xyz)


# ----------------------------------------------------------------------
# diagnostics + validator against a synthetic case
# ----------------------------------------------------------------------


@pytest.fixture(scope="module")
def synthetic():
    root = Path(tempfile.mkdtemp())
    case = make_case(root)
    index = collect(case, root / "out")
    return root, case, index


def test_synthetic_case_passes_every_hard_check(synthetic):
    root, _, index = synthetic
    validation = json.loads((root / "out/validation.json").read_text())
    assert validation["status"] == "PASS_2D_FORWARD_STEP"
    assert validation["failed_checks"] == []
    assert all(validation["hard_checks"].values())


def test_field_images_and_transient_series_are_produced(synthetic):
    root, _, index = synthetic
    assert index["figure_error"] is None
    for key in ("Mach_field", "p_field", "rho_field", "mesh_cells"):
        assert Path(index["figures"][key]).exists()
    for name in ("transient_mass.csv", "stored_totals.csv", "shock_front_history.csv"):
        assert (root / "out" / name).exists()


def test_compression_structure_is_measured(synthetic):
    root, _, _ = synthetic
    shock = json.loads((root / "out/diagnostics.json").read_text())["shock"]
    assert shock["available"]
    assert shock["jumps"]["p"] > 1
    assert shock["jumps"]["rho"] > 1


def test_reference_comparison_is_pending_not_invented(synthetic):
    root, _, _ = synthetic
    validation = json.loads((root / "out/validation.json").read_text())
    assert validation["reference_comparison"]["status"] == "PENDING_NO_REFERENCE_PACKAGE"


def test_validator_has_no_stationarity_requirement(synthetic):
    root, _, _ = synthetic
    validation = json.loads((root / "out/validation.json").read_text())
    assert not any("station" in k for k in validation["hard_checks"])
    assert "NOT_REQUIRED_STEADY" in validation["measured"]["transient_evolution"]["status"]


def test_negative_pressure_fails_the_validator(tmp_path):
    # The deterministic validator reports failure as evidence; it does not
    # raise. A nonphysical saved field must therefore surface as FAIL with the
    # offending check named, and must never be reported as a pass.
    case = make_case(tmp_path, positive=False)
    collect(case, tmp_path / "out")
    validation = json.loads((tmp_path / "out/validation.json").read_text())
    assert validation["status"] == "FAIL"
    assert "positive_all_saved" in validation["failed_checks"]
    assert validation["hard_checks"]["positive_all_saved"] is False


def test_unreached_horizon_is_reported_as_incomplete(synthetic):
    root, _, _ = synthetic
    diagnostics = json.loads((root / "out/diagnostics.json").read_text())
    truncated = dict(diagnostics)
    truncated["reached_requested_end_time"] = False
    result = validate(truncated)
    assert result["status"] == "INCOMPLETE_HORIZON_NOT_REACHED"
    assert result["failed_checks"] == []


# ----------------------------------------------------------------------
# bounded action validation
# ----------------------------------------------------------------------


def _evidence(**overrides):
    base = {
        "fatal_error": False,
        "finite_all_saved": True,
        "positive_all_saved": True,
        "minima_every_step": {"rho": 0.1, "p": 0.1, "T": 0.5},
        "courant_finite_positive": True,
        "reached_requested_end_time": True,
        "final_time": 4.0,
    }
    base.update(overrides)
    return base


PASS_VALIDATION = {"status": "PASS_2D_FORWARD_STEP", "failed_checks": []}
FAIL_VALIDATION = {"status": "FAIL", "failed_checks": ["positive_all_saved"]}


def _gate(action, spec=CANONICAL_SPEC, diagnostics=None, validation=None, **kw):
    kw.setdefault("max_end_time", 12.0)
    kw.setdefault("iterations_used", 1)
    kw.setdefault("max_iterations", 4)
    return validate_action(
        action, spec, diagnostics or _evidence(), validation or PASS_VALIDATION, **kw
    )


def test_accept_requires_the_deterministic_pass():
    assert _gate("ACCEPT").approved
    refused = _gate("ACCEPT", validation=FAIL_VALIDATION)
    assert not refused.approved
    assert "ACCEPT refused" in refused.reasons[0]


def test_continue_run_only_when_healthy_and_unfinished():
    assert not _gate("CONTINUE_RUN").approved  # horizon already reached

    unfinished = _evidence(reached_requested_end_time=False, final_time=1.0)
    approved = _gate("CONTINUE_RUN", diagnostics=unfinished, validation=FAIL_VALIDATION)
    assert approved.approved
    assert approved.resulting_changes["resume_from"] == 1.0

    unhealthy = _evidence(reached_requested_end_time=False, positive_all_saved=False)
    assert not _gate("CONTINUE_RUN", diagnostics=unhealthy).approved


def test_bounded_numerical_actions():
    reduced = _gate("REDUCE_MAX_CO")
    assert reduced.approved and reduced.resulting_changes["max_co"] == 0.1

    floor = _gate("REDUCE_MAX_CO", spec=CANONICAL_SPEC.with_changes(max_co=0.06))
    assert not floor.approved

    refine = _gate("REFINE_MESH", spec=ForwardStep2DSpec(nx=60, ny=20))
    assert refine.approved
    assert refine.resulting_changes["cells"] > ForwardStep2DSpec(nx=60, ny=20).cells

    # One uniform refinement step of this mesh would cross the cell cap, so
    # the gate must refuse it rather than let the agent grow the case.
    too_big = _gate("REFINE_MESH", spec=ForwardStep2DSpec(nx=600, ny=200))
    assert not too_big.approved
    assert "REFINE_MESH refused" in too_big.reasons[0]


def test_unknown_and_budgeted_actions_are_refused():
    assert not _gate("EDIT_FVSCHEMES").approved
    exhausted = _gate("CONTINUE_RUN", iterations_used=4, max_iterations=4)
    assert not exhausted.approved
    assert "budget" in exhausted.reasons[0]


def test_clarification_requires_a_question():
    assert not _gate("REQUEST_CLARIFICATION").approved
    assert _gate("REQUEST_CLARIFICATION", clarification="Which Mach number?").approved


def test_every_action_in_the_enum_is_handled():
    for action in ForwardStepAction:
        result = _gate(action.value)
        assert result.action == action.value
        assert result.reasons


# ----------------------------------------------------------------------
# reference-blindness of the reasoning payload
# ----------------------------------------------------------------------


def test_diagnosis_payload_is_reference_blind(synthetic):
    root, _, _ = synthetic
    diagnostics = json.loads((root / "out/diagnostics.json").read_text())
    validation = json.loads((root / "out/validation.json").read_text())

    payload = build_evidence_payload(
        CANONICAL_SPEC, diagnostics, validation, iterations_used=1, max_iterations=4
    )
    text = json.dumps(payload)
    for token in ("reference_comparison", "canonical_case", "stationary_normal_shock_sanity"):
        assert token not in text

    assert payload["horizon"]["reached_current_requested_end_time"] is True
    assert payload["allowed_actions"]
    assert "transient" in payload["important_instruction"]


def test_payload_builder_fails_closed_if_reference_material_appears(synthetic):
    root, _, _ = synthetic
    diagnostics = json.loads((root / "out/diagnostics.json").read_text())
    validation = json.loads((root / "out/validation.json").read_text())

    poisoned = dict(validation)
    poisoned["measured"] = dict(poisoned["measured"])
    poisoned["measured"]["sneaky"] = {"reference_comparison": {"p": 1.0}}

    # The stripper removes it; the guard then finds nothing to complain about.
    payload = build_evidence_payload(
        CANONICAL_SPEC, diagnostics, poisoned, iterations_used=1, max_iterations=4
    )
    assert "reference_comparison" not in json.dumps(payload)


# ----------------------------------------------------------------------
# LLM provenance
# ----------------------------------------------------------------------


def test_request_interpretation_never_silently_falls_back(monkeypatch):
    from src.agents.forward_step_spec_agent import interpret_request
    from src.agents.llm_provenance import LLMUnavailable

    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(LLMUnavailable, match="GEMINI_API_KEY"):
        interpret_request("forward step at Mach 2.5", allow_fallback=False)
    with pytest.raises(LLMUnavailable):
        interpret_request("forward step at Mach 2.5", allow_fallback=True)


def test_inferred_defaults_are_recorded_separately():
    from src.agents.forward_step_spec_agent import ForwardStepRequest, to_spec

    request = ForwardStepRequest(
        case_name="mach2p5_step0p15",
        summary="Mach 2.5, step height 0.15",
        mach=2.5,
        step_height=0.15,
    )
    spec, provenance = to_spec(request)

    assert spec.mach == 2.5 and spec.step_height == 0.15
    assert set(provenance["stated_by_user"]) == {"mach", "step_height"}
    assert "end_time" in provenance["inferred_from_family_defaults"]
    assert spec.end_time == CANONICAL_SPEC.end_time


def test_shell_scripts_are_lf_only():
    for path in (REPO_ROOT / "src/pipeline/forward_step_2d").rglob("*.sh"):
        assert b"\r" not in path.read_bytes(), path
