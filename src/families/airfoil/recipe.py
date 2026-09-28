#!/usr/bin/env python3
"""Family 3 recipe: frozen, reviewed, and transcribed -- not authored here.

Every numerical value below was supplied by the scientific review that froze
this family, or is a NATIVE OpenFOAM Foundation v14 default restated for
provenance. Nothing here is a guess and nothing here may be loosened to make a
result pass.

WHAT IS STILL UNREGISTERED, and therefore what keeps this family
CORE-PENDING rather than CORE:

  * the SHA256 digests of the six registered external assets -- a digest is a
    property of a specific downloaded file and cannot be invented. They are
    recorded once by scripts/airfoil_assets.py register and committed to
    configs/families/airfoil/assets.lock.json.
  * the REFINE_REGION under-resolution criterion. No deterministic criterion was
    registered, so the capability stays disabled. A local-refinement trigger is
    NOT invented merely to make the action available.

WHAT THIS FAMILY DOES NOT CLAIM: reproduction of NASA CFL3D. The NASA CFD
reference is compressible at M = 0.15; this is an incompressible Foundation-v14
validation against external evidence.
"""
from __future__ import annotations

from typing import Any, Dict

from src.families.base import TODO
from src.families.recipe import FamilyRecipe
from src.families.airfoil.spec import (
    ALPHA_ENVELOPE_DEG,
    CANONICAL_ALPHA_DEG,
    CANONICAL_GRID,
    CHORD_M,
    CELL_ENVELOPE,
    EXPECTED_CELLS,
    NASA_FAMILY2_DIMENSIONS,
    FAMILY,
    FIRST_VARIATION_ALPHA_DEG,
    K_INF,
    NU,
    NUT_INF,
    NUT_RATIO_INF,
    OMEGA_INF,
    PHYSICS,
    RE_C,
    RHO,
    SENSITIVITY_GRID,
    SPAN_M,
    TURBULENCE_INTENSITY,
    U_INF,
)
from src.pipeline.airfoil import assets as asset_mod

# ----------------------------------------------------------------------
# Native OpenFOAM Foundation v14 kOmegaSST coefficients, restated explicitly.
# This is NOT an SSTm emulation and NOT an attempt to match NASA's variant.
# ----------------------------------------------------------------------
SST_COEFFICIENTS: Dict[str, Any] = {
    "alphaK1": 0.85,
    "alphaK2": 1.0,
    "alphaOmega1": 0.5,
    "alphaOmega2": 0.856,
    "beta1": 0.075,
    "beta2": 0.0828,
    "betaStar": 0.09,
    "gamma1": 5.0 / 9.0,
    "gamma2": 0.44,
    "a1": 0.31,
    "b1": 1.0,
    "c1": 10.0,
    "F3": False,
}

#: What is explicitly excluded. Recorded so an omission is auditable.
EXCLUDED_MODEL_FEATURES = (
    "SSTm emulation",
    "transition model",
    "curvature correction",
    "sustaining source term",
    "any custom turbulence code",
)

# ----------------------------------------------------------------------
# Frozen numerical recipe. The limiter setting is registered EXPLICITLY, because
# "a limited scheme" is not a specification.
# ----------------------------------------------------------------------
NUMERICS: Dict[str, Any] = {
    "solver_invocation": "foamRun -solver incompressibleFluid",
    "openfoam": "OpenFOAM Foundation v14",
    "coupling": "steady RANS, SIMPLE-family",
    "ddtSchemes_default": "steadyState",
    "gradSchemes_default": "Gauss linear",
    "interpolationSchemes_default": "linear",
    "divScheme_U": "bounded Gauss linearUpwind grad(U)",
    # Registered explicitly: limiter family, coefficient and gradient.
    "divScheme_k": "bounded Gauss limitedLinear 1",
    "divScheme_omega": "bounded Gauss limitedLinear 1",
    "limitedLinear_coefficient": 1.0,
    "laplacianSchemes_default": "Gauss linear corrected",
    "snGradSchemes_default": "corrected",
    "relaxation_p": 0.3,
    "relaxation_U": 0.7,
    "relaxation_k": 0.7,
    "relaxation_omega": 0.7,
    "solver_p": "GAMG",
    "solver_U": "smoothSolver symGaussSeidel (asymmetric)",
    "solver_turbulence": "smoothSolver symGaussSeidel (asymmetric)",
    "first_order_fallback_permitted_for_accepted_results": False,
}

# ----------------------------------------------------------------------
# Boundary conditions. Native Foundation freestream treatment; incidence is
# imposed by rotating the freestream vector, never by rotating the airfoil.
# ----------------------------------------------------------------------
BOUNDARY_CONDITIONS: Dict[str, Any] = {
    "farfield": {
        "U": "freestreamVelocity",
        "p": "freestreamPressure",
        "k": "inletOutlet / freestream, freestreamValue k_inf",
        "omega": "inletOutlet / freestream, freestreamValue omega_inf",
        "nut": "calculated / freestream, freestreamValue nut_inf",
        "extent_chords_approx": 500,
        "incidence": "imposed by rotating the freestream velocity vector",
    },
    "wall": {
        "U": "noSlip",
        "p": "zeroGradient",
        "k": "fixedValue 0",
        "nut": "nutLowReWallFunction",
        "omega": "omegaWallFunction",
        "omegaWallFunction_blended": False,
        "omegaWallFunction_beta1": 0.075,
    },
    "frontAndBack": {"type": "empty"},
    "initialisation": {
        "U": "uniform freestream",
        "p": "uniform 0 (gauge)",
        "k": "uniform k_inf (positive)",
        "omega": "uniform omega_inf (positive)",
        "note": "wall conditions are enforced after initialisation",
    },
}

# ----------------------------------------------------------------------
# Frozen acceptance contract. PREREGISTERED. Never loosened after observing a
# result; a numerically converged case that misses these does not get "fixed" by
# more iterations.
# ----------------------------------------------------------------------
TOLERANCES: Dict[str, Any] = {
    # 1. zero-incidence symmetry -- a numerical check, NOT experimental lift accuracy
    "symmetry_abs_CL_max": 0.005,
    # 2. experimental drag, against tripped Ladson data
    "drag_relative_tolerance": 0.10,
    # 3. surface pressure vs registered NASA CFL3D Cp, per surface, absolute RMSE
    "cp_rmse_max_per_surface": 0.05,
    # 4. grid sensitivity (a demonstration, not formal asymptotic GCI)
    "grid_sensitivity_CD_relative_max": 0.02,
    "grid_sensitivity_cp_rmse_max": 0.01,
    # 5. wall resolution
    "yplus_fraction_below_one_min": 0.99,
    "yplus_threshold": 1.0,
    # 6. numerical qualification over the final `qualification_window` iterations
    "residual_max_U": 1.0e-6,
    "residual_max_k": 1.0e-6,
    "residual_max_omega": 1.0e-6,
    "residual_max_p": 1.0e-5,
    "flux_imbalance_normalised_max": 1.0e-5,
    "drag_variation_relative_max": 0.002,
    "lift_range_max": 1.0e-4,
}

REFERENCE_VALUES: Dict[str, Any] = {
    "benchmark": "NASA Turbulence Modeling Resource 2DN00 NACA0012 validation case",
    "benchmark_page": asset_mod.TMR_PAGE,
    "experimental_force_reference": "Ladson NASA TM-4074 tripped force data",
    "supporting_cfd_reference": "NASA CFL3D SST forces, Cp and Cf",
    "cp_reference_asset": asset_mod.REF_CFL3D_CP,
    "cf_reference_asset": asset_mod.REF_CFL3D_CF,
    "experimental_force_asset": asset_mod.REF_LADSON_FORCES,
    "ladson_pressure_is_not_a_gate": (
        "Ladson pressure data is NOT an exact pressure gate for this setup and is "
        "deliberately not registered as one"
    ),
    "cf_is_supporting_only": (
        "no experimental Cf is supplied here, so Cf is reported as supporting CFD "
        "evidence and is never an acceptance gate"
    ),
    "nasa_reference_mach": 0.15,
    "our_formulation": "incompressible, isothermal; Mach and temperature not solved",
    "exact_reproduction_claim": (
        "NONE. This is a validation against external evidence, not a reproduction "
        "of the NASA code."
    ),
}

FROZEN_SCALING: Dict[str, Any] = {
    "chord_m": CHORD_M,
    "U_inf": U_INF,
    "rho": RHO,
    "nu": NU,
    "Re_c": RE_C,
    "span_m": SPAN_M,
    "incompressible": True,
    "isothermal": True,
    "canonical_alpha_deg": CANONICAL_ALPHA_DEG,
    "first_variation_alpha_deg": FIRST_VARIATION_ALPHA_DEG,
    "turbulence_intensity": TURBULENCE_INTENSITY,
    "nut_ratio_inf": NUT_RATIO_INF,
    "k_inf": K_INF,
    "omega_inf": OMEGA_INF,
    "nut_inf": NUT_INF,
    "k_inf_derivation": "1.5 * (U_inf * Ti)^2, Ti = 0.052%",
    "omega_inf_derivation": "k_inf / nu_t,  nu_t = 0.009 * nu",
    "force_normalisation": "C = F / (0.5 * rho * U_inf^2 * c * b), b = actual span",
    "mesh_hierarchy": "preregistered Gmsh coarse/medium/fine (see mesh_levels)",
    "canonical_level": CANONICAL_GRID,
    "sensitivity_level": SENSITIVITY_GRID,
    "cells_per_level": dict(EXPECTED_CELLS),
    "nasa_family2_dimensions": {k: list(v) for k, v in
                                NASA_FAMILY2_DIMENSIONS.items()},
    "cell_count_status": (
        "NASA-DECLARED and re-derived as (ni-1)(nj-1). The mesh is NASA's Family II "
        "grid, so these counts are requirements the conversion must reproduce."
    ),
}

#: Bounded actions. Only what the shared architecture already supports; no new
#: action is introduced for this family.
ALLOWED_ACTIONS = (
    "ACCEPT",
    "CONTINUE_RUN",
    "REQUEST_CLARIFICATION",
    "REJECT_UNSUPPORTED",
    "FAIL_SAFELY",
    "REFINE_REGION",
)

#: Declared but unavailable: the criterion below is unregistered, so the action
#: refuses. The vocabulary is declared so it is not invented at call time.
REGION_VOCABULARY = ("leading_edge", "trailing_edge", "suction_peak", "wake")

RECIPE = FamilyRecipe(
    family=FAMILY,
    physics=PHYSICS,
    reference=(
        "NASA Turbulence Modeling Resource 2DN00 NACA0012 validation case "
        f"({asset_mod.TMR_PAGE}); experimental forces from Ladson NASA TM-4074 "
        "(tripped); supporting CFD reference NASA CFL3D SST. Our implementation "
        "is incompressible Foundation v14 and is NOT an exact NASA-code reproduction."
    ),
    numerics={
        **NUMERICS,
        "turbulence_model": "kOmegaSST (native OpenFOAM Foundation v14)",
        "sst_coefficients": SST_COEFFICIENTS,
        "excluded_model_features": EXCLUDED_MODEL_FEATURES,
        "boundary_conditions": BOUNDARY_CONDITIONS,
        "frozen_scaling": FROZEN_SCALING,
        "mesh_policy": (
            "NASA TMR NACA0012 Numerical Analysis Family II unstructured hexahedral "
            "CGNS grids, used exactly as supplied: in-plane coordinates and "
            "connectivity preserved bit for bit, never regenerated, smoothed, "
            "projected, optimised or remeshed. The ONLY modification is the "
            "spanwise separation, set to b = 0.01 c with one spanwise cell. The "
            "custom Gmsh generator (v1 and v2) is ARCHIVED EVIDENCE and is not a "
            "mesh source. ARCHIVED DESCRIPTION FOLLOWS: "
            "preregistered Gmsh hierarchy only (coarse/medium/fine), generated from "
            "the corrected TMR analytic sharp-trailing-edge NACA0012 section by one "
            "deterministic pipeline; identical farfield on every level; exactly one "
            "spanwise cell; no domain truncation and no ad-hoc remeshing. The NASA "
            "Plot3D grids and the CGNS hex mesh are an OPTIONAL supporting "
            "topology-authority branch and are not run levels."
        ),
    },
    bounds={
        "alpha_deg": ALPHA_ENVELOPE_DEG,
        #: Planning envelope of the frozen hierarchy, coarse low to fine high.
        #: Present so the family's size envelope is declared rather than
        #: discovered; qualification is by mesh_checks, never by cell count.
        "cells": CELL_ENVELOPE,
    },
    tolerances=TOLERANCES,
    reference_values=REFERENCE_VALUES,
    allowed_actions=ALLOWED_ACTIONS,
    region_vocabulary=REGION_VOCABULARY,
    capability_criteria={
        "REFINE_REGION": {
            "under_resolution_criterion": TODO(
                "airfoil.under_resolution_criterion",
                "no deterministic under-resolution criterion was registered for "
                "this family. A local-refinement trigger is NOT invented to make "
                "the action available; REFINE_REGION therefore refuses.",
            ),
        },
    },
    notes=(
        "CORE-PENDING. The scientific recipe is frozen and registered; what "
        "remains is asset registration (SHA256 digests of the six registered "
        "external files), a passing zero-CFD mesh audit, a numerically sane "
        "coarse pilot, and canonical validation. Acceptance criteria are "
        "preregistered and are never loosened after observing a result."
    ),
)


def asset_gate(repo_root: Any = None) -> Dict[str, Any]:
    """Whether the registered external assets are in order. Fails closed upstream."""
    return asset_mod.audit_assets(repo_root)
