#!/usr/bin/env python3
"""Every frozen scientific constant, asserted against its definition.

Where a value is derived, the test recomputes it from the benchmark quantity
rather than restating the number, so a transcription error cannot pass.
"""
from __future__ import annotations

import math

import pytest

from src.families.airfoil import recipe as R
from src.families.airfoil import spec as S


# -- scaling -----------------------------------------------------------
def test_reynolds_number_is_six_million():
    assert S.RE_C == 6.0e6


def test_viscosity_is_the_quotient_not_a_transcribed_number():
    assert S.NU == pytest.approx(1.0 / 6.0e6, rel=0, abs=0)
    assert S.NU == pytest.approx(1.6666666667e-7, rel=1e-10)
    assert S.U_INF * S.CHORD_M / S.NU == pytest.approx(S.RE_C, rel=1e-12)


def test_dimensional_scaling():
    # SPAN_M is the FROZEN 0.01 c span of the one-cell Gmsh extrusion, and it is
    # what the force normalisation uses. The NASA supporting files keep their own
    # span of 1.0; the two are deliberately different numbers.
    assert (S.CHORD_M, S.U_INF, S.RHO, S.SPAN_M) == (1.0, 1.0, 1.0, 0.01)
    assert S.NASA_SPAN_M == 1.0
    assert S.dynamic_reference() == 0.5 * S.RHO * S.U_INF ** 2 * S.CHORD_M * 0.01


def test_canonical_incidence_is_zero_and_variation_is_ten():
    assert S.CANONICAL_ALPHA_DEG == 0.0
    assert S.FIRST_VARIATION_ALPHA_DEG == 10.0
    assert S.ALPHA_ENVELOPE_DEG == (0.0, 10.0)


def test_incompressible_isothermal_is_declared():
    assert R.FROZEN_SCALING["incompressible"] is True
    assert R.FROZEN_SCALING["isothermal"] is True


# -- freestream turbulence --------------------------------------------
def test_freestream_turbulence_inputs_are_the_nasa_values():
    assert S.TURBULENCE_INTENSITY == pytest.approx(0.052e-2)
    assert S.NUT_RATIO_INF == pytest.approx(0.009)


def test_k_infinity_is_recomputed_from_the_intensity():
    assert 1.5 * (S.U_INF * S.TURBULENCE_INTENSITY) ** 2 == pytest.approx(
        S.K_INF, rel=1e-12
    )
    assert S.K_INF == pytest.approx(4.056e-7, rel=1e-12)


def test_omega_infinity_is_recomputed_from_k_and_the_viscosity_ratio():
    assert S.K_INF / (S.NUT_RATIO_INF * S.NU) == pytest.approx(S.OMEGA_INF, rel=1e-12)
    assert S.OMEGA_INF == pytest.approx(270.4, rel=1e-12)


def test_derivations_are_recorded_in_provenance():
    assert "1.5 * (U_inf * Ti)^2" in R.FROZEN_SCALING["k_inf_derivation"]
    assert "0.009 * nu" in R.FROZEN_SCALING["omega_inf_derivation"]


# -- native v14 SST ----------------------------------------------------
@pytest.mark.parametrize(
    "key,value",
    [
        ("alphaK1", 0.85), ("alphaK2", 1.0), ("alphaOmega1", 0.5),
        ("alphaOmega2", 0.856), ("beta1", 0.075), ("beta2", 0.0828),
        ("betaStar", 0.09), ("gamma2", 0.44), ("a1", 0.31), ("b1", 1.0),
        ("c1", 10.0),
    ],
)
def test_native_v14_sst_coefficient(key, value):
    assert R.SST_COEFFICIENTS[key] == pytest.approx(value)


def test_gamma1_is_five_ninths_exactly():
    assert R.SST_COEFFICIENTS["gamma1"] == pytest.approx(5.0 / 9.0, rel=1e-15)


def test_F3_is_false():
    assert R.SST_COEFFICIENTS["F3"] is False


@pytest.mark.parametrize(
    "excluded",
    ["SSTm emulation", "transition model", "curvature correction",
     "sustaining source term", "any custom turbulence code"],
)
def test_model_extras_are_explicitly_excluded(excluded):
    assert excluded in R.EXCLUDED_MODEL_FEATURES


def test_no_exact_nasa_reproduction_is_claimed():
    assert R.REFERENCE_VALUES["nasa_reference_mach"] == 0.15
    assert "NONE" in R.REFERENCE_VALUES["exact_reproduction_claim"]
    assert "not a reproduction" in R.REFERENCE_VALUES["exact_reproduction_claim"]
    assert "incompressible" in R.REFERENCE_VALUES["our_formulation"]


# -- numerics ----------------------------------------------------------
def test_numerical_recipe_is_second_order_and_registers_its_limiter():
    n = R.NUMERICS
    assert n["divScheme_U"] == "bounded Gauss linearUpwind grad(U)"
    assert n["divScheme_k"] == "bounded Gauss limitedLinear 1"
    assert n["divScheme_omega"] == "bounded Gauss limitedLinear 1"
    assert n["limitedLinear_coefficient"] == 1.0
    assert n["gradSchemes_default"] == "Gauss linear"
    assert n["interpolationSchemes_default"] == "linear"
    assert "corrected" in n["laplacianSchemes_default"]
    assert n["snGradSchemes_default"] == "corrected"
    assert n["first_order_fallback_permitted_for_accepted_results"] is False


def test_relaxation_factors():
    n = R.NUMERICS
    assert (n["relaxation_p"], n["relaxation_U"], n["relaxation_k"],
            n["relaxation_omega"]) == (0.3, 0.7, 0.7, 0.7)


def test_solver_invocation_and_coupling():
    assert R.NUMERICS["solver_invocation"] == "foamRun -solver incompressibleFluid"
    assert R.NUMERICS["solver_p"] == "GAMG"
    assert "asymmetric" in R.NUMERICS["solver_U"]
    assert "SIMPLE" in R.NUMERICS["coupling"]


# -- boundary conditions ----------------------------------------------
def test_wall_boundary_conditions():
    wall = R.BOUNDARY_CONDITIONS["wall"]
    assert wall["U"] == "noSlip"
    assert wall["p"] == "zeroGradient"
    assert wall["k"] == "fixedValue 0"
    assert wall["nut"] == "nutLowReWallFunction"
    assert wall["omega"] == "omegaWallFunction"
    assert wall["omegaWallFunction_blended"] is False
    assert wall["omegaWallFunction_beta1"] == 0.075


def test_farfield_uses_native_freestream_treatment():
    far = R.BOUNDARY_CONDITIONS["farfield"]
    assert far["U"] == "freestreamVelocity"
    assert far["p"] == "freestreamPressure"
    assert far["extent_chords_approx"] == 500
    assert "rotating the freestream" in far["incidence"]


def test_front_and_back_are_empty():
    assert R.BOUNDARY_CONDITIONS["frontAndBack"]["type"] == "empty"


def test_initialisation_is_freestream_with_positive_turbulence():
    init = R.BOUNDARY_CONDITIONS["initialisation"]
    assert "freestream" in init["U"]
    assert "0" in init["p"]
    assert "positive" in init["k"] and "positive" in init["omega"]


# -- incidence by freestream rotation ---------------------------------
def test_incidence_rotates_the_freestream_not_the_airfoil():
    for alpha in (0.0, 5.0, 10.0):
        ux, uy, uz = S.freestream_velocity(alpha)
        assert uz == 0.0
        assert math.hypot(ux, uy) == pytest.approx(S.U_INF, rel=1e-12)
        assert math.degrees(math.atan2(uy, ux)) == pytest.approx(alpha, abs=1e-9)


def test_lift_and_drag_follow_the_freestream():
    for alpha in (0.0, 10.0):
        d = S.lift_drag_directions(alpha)
        drag, lift = d["drag"], d["lift"]
        assert sum(a * b for a, b in zip(drag, lift)) == pytest.approx(0.0, abs=1e-12)
        assert drag == pytest.approx(S.freestream_velocity(alpha), rel=1e-12)


# -- grids -------------------------------------------------------------
def test_active_grid_keys_are_the_frozen_gmsh_hierarchy():
    assert S.GRID_KEYS == ("coarse", "medium", "fine")
    assert S.CANONICAL_GRID == "fine"
    assert S.SENSITIVITY_GRID == "medium"


def test_the_nasa_plot3d_layout_is_kept_for_the_supporting_branch():
    """2 x 897 x 257 and 2 x 449 x 129 -- spanwise first, as NASA writes them.

    Retained, not active: the NASA grids are an optional supporting branch and
    are no longer run levels, so they are not in GRID_KEYS.
    """
    assert S.GRID_DIMENSIONS[S.NASA_CANONICAL_GRID] == (2, 897, 257)
    assert S.GRID_DIMENSIONS[S.NASA_SENSITIVITY_GRID] == (2, 449, 129)
    assert S.flow_plane_dimensions(S.NASA_CANONICAL_GRID) == (897, 257)
    assert S.flow_plane_dimensions(S.NASA_SENSITIVITY_GRID) == (449, 129)
    assert S.NASA_CANONICAL_GRID not in S.GRID_KEYS
    assert S.NASA_SENSITIVITY_GRID not in S.GRID_KEYS


def test_supporting_grid_cell_counts_are_the_identity_not_transcribed():
    assert S.NASA_CANONICAL_CELLS == (2 - 1) * (897 - 1) * (257 - 1) == 229376
    assert S.NASA_SENSITIVITY_CELLS == (2 - 1) * (449 - 1) * (129 - 1) == 57344


def test_two_spanwise_planes_give_exactly_one_spanwise_cell():
    for key in (S.NASA_CANONICAL_GRID, S.NASA_SENSITIVITY_GRID):
        ni, nj, nk = S.GRID_DIMENSIONS[key]
        assert ni == 2
        assert S.cells_for(key) == (nj - 1) * (nk - 1)


def test_active_cell_counts_are_nasa_declared_identities():
    """The active mesh is NASA's, so its cell counts ARE requirements."""
    spec = S.AirfoilSpec()
    assert S.EXPECTED_CELLS == {"coarse": 14336, "medium": 57344, "fine": 229376}
    assert spec.expected_cells == 229376
    assert spec.nasa_dimensions == (897, 257)
    assert spec.expected_cells == (897 - 1) * (257 - 1)
    # `cells` stays MEASURED: it is what the conversion actually produced.
    assert spec.cells is None or isinstance(spec.cells, int)
    assert S.measured_cells("mesh_canonical") is None      # not an active level


def test_recipe_cell_bounds_span_the_nasa_family2_hierarchy():
    assert R.RECIPE.bounds["cells"] == S.CELL_ENVELOPE == (14336, 229376)
    assert R.RECIPE.bounds["alpha_deg"] == S.ALPHA_ENVELOPE_DEG
    assert R.FROZEN_SCALING["cells_per_level"] == S.EXPECTED_CELLS


def test_a_nasa_grid_key_is_refused_as_a_run_level():
    import pytest as _pytest
    with _pytest.raises(ValueError, match="preregistered Gmsh hierarchy"):
        S.AirfoilSpec(grid="mesh_canonical")


def test_span_agrees_with_the_family2_conversion():
    from src.pipeline.airfoil import family2 as F2
    assert S.SPAN_M == F2.REQUIRED_SPAN == 0.01
    assert S.NASA_SPAN_M == 1.0          # the supporting Plot3D files' own span
