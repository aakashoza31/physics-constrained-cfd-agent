"""NozzleCaseSpec: derived geometry, envelope enforcement, startup bounds."""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from src.pipeline.nozzle.spec import (  # noqa: E402
    CANONICAL_SPEC,
    NozzleCaseSpec,
    num,
)

CONFIGS = REPO_ROOT / "configs/nozzles"

CASES = {
    "A": CONFIGS / "case_A_reference.yaml",
    "B": CONFIGS / "case_B_geometry.yaml",
    "C": CONFIGS / "case_C_conditions.yaml",
}


@pytest.fixture(scope="module")
def specs():
    return {key: NozzleCaseSpec.from_yaml(path) for key, path in CASES.items()}


def test_all_three_configs_load(specs):
    assert specs["A"].case_id == "nozzle_A_reference"
    assert specs["B"].case_id == "nozzle_B_geometry"
    assert specs["C"].case_id == "nozzle_C_conditions"


def test_cases_differ_only_where_intended(specs):
    a, b, c = specs["A"], specs["B"], specs["C"]

    # B: geometry transfer, exit radius only.
    assert b.exit_radius_m == 0.0370
    assert a.exit_radius_m == 0.0354
    assert (b.total_pressure_pa, b.total_temperature_k) == (
        a.total_pressure_pa,
        a.total_temperature_k,
    )
    assert (b.inlet_radius_m, b.throat_radius_m) == (
        a.inlet_radius_m,
        a.throat_radius_m,
    )

    # C: operating-condition transfer, reservoir pressure only.
    assert c.total_pressure_pa == 220000.0
    assert c.total_temperature_k == a.total_temperature_k
    assert (c.inlet_radius_m, c.throat_radius_m, c.exit_radius_m) == (
        a.inlet_radius_m,
        a.throat_radius_m,
        a.exit_radius_m,
    )


def test_breakpoints_are_exact_not_accumulated_floats(specs):
    for spec in specs.values():
        assert spec.axial_breakpoints_m == [0.0, 0.05, 0.15, 0.16, 0.28, 0.33]
        assert spec.throat_start_m == 0.15
        assert spec.throat_end_m == 0.16
        assert spec.downstream_screen_x_m == 0.17
        assert spec.length_m == 0.33


def test_same_pipeline_parameters_for_all_three(specs):
    for spec in specs.values():
        assert spec.scale == 1.0
        assert spec.max_courant == 0.4
        assert spec.end_time_s == 0.006
        assert spec.wedge_angle_deg == 5.0
        assert spec.axial_cells == [20, 40, 4, 48, 20]
        assert spec.radial_cells == 16
        assert sum(spec.axial_cells) * spec.radial_cells == 2112


def test_case_c_would_have_tripped_the_canonical_hard_coded_literal(specs):
    """The reason the startup assertion had to be parameterized."""
    c = specs["C"]

    p_exit, _, _ = c.quasi1d_state(c.exit_radius_m, True)

    # Under the canonical literal the margin was 0.8% - one modelling change
    # away from a failure that has nothing to do with physics.
    assert p_exit < 60000.0
    assert (60000.0 - p_exit) / 60000.0 < 0.01

    # The parameterized bound is anchored to that same quasi-1D exit state and
    # therefore carries the declared tolerance instead of a coincidence.
    max_allowed_p_min, min_allowed_p_max = c.expected_initial_pressure_bounds()
    assert max_allowed_p_min == pytest.approx(1.01 * p_exit, rel=1e-12)
    assert max_allowed_p_min > p_exit
    assert min_allowed_p_max < c.total_pressure_pa


def test_startup_bounds_accommodate_the_declared_perturbation():
    perturbed = NozzleCaseSpec(
        **{**CANONICAL_SPEC.to_dict(), "startup_perturbation": 0.02}
    )

    plain_low, plain_high = CANONICAL_SPEC.expected_initial_pressure_bounds()
    low, high = perturbed.expected_initial_pressure_bounds()

    assert low > plain_low
    assert high < plain_high


def test_envelope_is_enforced():
    with pytest.raises(ValueError, match="gamma"):
        NozzleCaseSpec(**{**CANONICAL_SPEC.to_dict(), "gamma": 1.3}).validate()

    with pytest.raises(ValueError, match="R = 287"):
        NozzleCaseSpec(
            **{**CANONICAL_SPEC.to_dict(), "gas_constant_j_per_kg_k": 296.0}
        ).validate()

    with pytest.raises(ValueError, match="pressure-free"):
        NozzleCaseSpec(
            **{**CANONICAL_SPEC.to_dict(), "ambient_imposed_at_exit": True}
        ).validate()

    with pytest.raises(ValueError, match="converging-diverging"):
        NozzleCaseSpec(
            **{**CANONICAL_SPEC.to_dict(), "exit_radius_m": 0.03}
        ).validate()


def test_manifest_round_trip(tmp_path):
    spec = NozzleCaseSpec.from_yaml(CASES["B"])
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(spec.manifest(), indent=2))

    restored = NozzleCaseSpec.from_manifest(path)

    assert restored.to_dict() == spec.to_dict()


def test_area_ratios(specs):
    assert specs["A"].area_ratio == pytest.approx(1.17920, rel=1e-4)
    assert specs["B"].area_ratio == pytest.approx(1.28817, rel=1e-4)
    assert specs["C"].area_ratio == specs["A"].area_ratio


def test_case_c_is_an_exact_pressure_scaling_of_case_a(specs):
    """Euler with no imposed back pressure scales linearly with p0."""
    a, c = specs["A"], specs["C"]

    pa, ta, ua = a.quasi1d_state(a.exit_radius_m, True)
    pc, tc, uc = c.quasi1d_state(c.exit_radius_m, True)

    assert pc / pa == pytest.approx(220000.0 / 200000.0, rel=1e-12)
    assert tc == pytest.approx(ta, rel=1e-12)
    assert uc == pytest.approx(ua, rel=1e-12)
    assert c.choked_mass_flow_kg_s() / a.choked_mass_flow_kg_s() == pytest.approx(
        1.1, rel=1e-12
    )


def test_number_formatting_reproduces_canonical_literals():
    assert num(200000.0) == "200000"
    assert num(220000.0) == "220000"
    assert num(300.0) == "300"
    assert num(1.4) == "1.4"
    assert num(0.4) == "0.4"
    assert num(0.006) == "0.006"
