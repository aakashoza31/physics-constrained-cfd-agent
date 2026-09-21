from __future__ import annotations

import json

import pytest

from src.pipeline.nozzle.feedback import (
    configure_continuation_text,
    manifest_with_end_time,
    refined_spec,
)
from src.pipeline.nozzle.spec import CANONICAL_SPEC


def test_continuation_updates_inline_control_entries():
    original = (
        "application foamRun;\n"
        "solver shockFluid;\n"
        "startFrom startTime; startTime 0; stopAt endTime; endTime 0.001;\n"
    )
    updated = configure_continuation_text(
        original,
        current_time=0.001,
        end_time=0.006,
    )
    assert "startFrom latestTime;" in updated
    assert "startTime 0.001;" in updated
    assert "endTime 0.006;" in updated


def test_manifest_end_time_stays_self_consistent():
    manifest = CANONICAL_SPEC.manifest()
    updated = manifest_with_end_time(manifest, 0.006)
    assert updated["end_time"] == 0.006
    assert updated["case_spec"]["end_time_s"] == 0.006
    assert manifest["end_time"] == CANONICAL_SPEC.end_time_s


def test_throat_refinement_is_local_bounded_and_preserves_physics():
    refined, record = refined_spec(CANONICAL_SPEC, "REFINE_THROAT", "throat")
    assert refined.inlet_radius_m == CANONICAL_SPEC.inlet_radius_m
    assert refined.throat_radius_m == CANONICAL_SPEC.throat_radius_m
    assert refined.total_pressure_pa == CANONICAL_SPEC.total_pressure_pa
    assert refined.base_axial_cells[0] == CANONICAL_SPEC.base_axial_cells[0]
    assert refined.base_axial_cells[4] == CANONICAL_SPEC.base_axial_cells[4]
    assert refined.base_axial_cells[2] > CANONICAL_SPEC.base_axial_cells[2]
    assert record["total_cells_after"] <= 13200


def test_gradient_refinement_rejects_unknown_region():
    with pytest.raises(ValueError):
        refined_spec(CANONICAL_SPEC, "REFINE_GRADIENT_REGION", "somewhere mysterious")
