#!/usr/bin/env python3
"""2D turbulent NACA0012 airfoil recipe: every scientific constant, all unregistered.

DO NOT FILL THESE IN WITHOUT THE AUTHORITATIVE REFERENCE. The framework
guarantee is that a recipe holding any TODO cannot produce ACCEPT: the
orchestrator downgrades the decision to INCONCLUSIVE with reason
CRITERION_NOT_REGISTERED. That guarantee is only worth something if nobody
resolves a TODO with a plausible-looking number.
"""
from __future__ import annotations

from src.families.base import TODO
from src.families.recipe import FamilyRecipe
from src.families.airfoil.spec import FAMILY, PHYSICS

RECIPE = FamilyRecipe(
    family=FAMILY,
    physics=PHYSICS,
    reference="TODO: authoritative NASA TMR-type NACA0012 reference, pending Astra review",
    numerics={
        "turbulence_model": TODO("numerics.turbulence_model", "reference states SST; the exact TMR variant must be identified and checked against Foundation v14 before use"),
        "solver": TODO("numerics.solver", "steady incompressible vs low-Mach compressible is a reference decision"),
        "mach": TODO("numerics.mach", "freestream Mach of the reference case"),
        "reynolds_number": TODO("numerics.reynolds_number", "chord Reynolds number of the reference case"),
        "turbulence_inlet_bc": TODO("numerics.turbulence_inlet_bc", "freestream k/omega or nuTilda values as the reference specifies"),
        "wall_treatment": TODO("numerics.wall_treatment", "resolved (y+~1) vs wall function, per the reference"),
    },
    bounds={
        "angle_of_attack_deg": TODO("bounds.angle_of_attack_deg", "admissible AoA envelope of the registered reference"),
        "cells": TODO("bounds.cells", "admissible grid-size range"),
    },
    tolerances={
        "CL_tolerance": TODO("tolerances.CL_tolerance", "acceptance tolerance on lift coefficient"),
        "CD_tolerance": TODO("tolerances.CD_tolerance", "acceptance tolerance on drag coefficient"),
        "Cp_profile_tolerance": TODO("tolerances.Cp_profile_tolerance", "acceptance tolerance on the surface pressure distribution"),
        "Cf_profile_tolerance": TODO("tolerances.Cf_profile_tolerance", "acceptance tolerance on skin friction"),
        "convergence_residual": TODO("tolerances.convergence_residual", "residual level at which the steady solve is converged"),
        "force_stationarity": TODO("tolerances.force_stationarity", "force-coefficient stationarity criterion"),
        "y_plus_target": TODO("tolerances.y_plus_target", "wall-normal resolution requirement"),
        "under_resolution_criterion": TODO("tolerances.under_resolution_criterion", "criterion for when a named region is under-resolved"),
    },
    reference_values={
        "CL": TODO("reference_values.CL", "reference lift coefficient at the registered condition"),
        "CD": TODO("reference_values.CD", "reference drag coefficient at the registered condition"),
        "Cp_distribution": TODO("reference_values.Cp_distribution", "reference surface pressure distribution"),
        "Cf_distribution": TODO("reference_values.Cf_distribution", "reference skin-friction distribution"),
    },
    allowed_actions=(
        "ACCEPT", "CONTINUE_RUN", "REFINE_MESH", "REFINE_REGION",
        "REQUEST_CLARIFICATION", "REJECT_UNSUPPORTED", "FAIL_SAFELY",
    ),
    region_vocabulary=('leading_edge', 'trailing_edge', 'suction_peak', 'wake'),
    notes=(
        "CORE-PENDING. Scientific recipe unregistered. Astra supplies these "
        "after reviewing the authoritative reference."
    ),
)
