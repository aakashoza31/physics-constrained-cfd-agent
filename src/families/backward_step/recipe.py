#!/usr/bin/env python3
"""2D turbulent backward-facing step recipe: every scientific constant, all unregistered.

DO NOT FILL THESE IN WITHOUT THE AUTHORITATIVE REFERENCE. The framework
guarantee is that a recipe holding any TODO cannot produce ACCEPT: the
orchestrator downgrades the decision to INCONCLUSIVE with reason
CRITERION_NOT_REGISTERED. That guarantee is only worth something if nobody
resolves a TODO with a plausible-looking number.
"""
from __future__ import annotations

from src.families.base import TODO
from src.families.recipe import FamilyRecipe
from src.families.backward_step.spec import FAMILY, PHYSICS

RECIPE = FamilyRecipe(
    family=FAMILY,
    physics=PHYSICS,
    reference="TODO: authoritative NASA TMR-type backward-facing-step reference, pending Astra review",
    numerics={
        "turbulence_model": TODO("numerics.turbulence_model", "reference states SST; the exact variant must be checked against Foundation v14"),
        "solver": TODO("numerics.solver", "steady incompressible solver choice per the reference"),
        "reynolds_number": TODO("numerics.reynolds_number", "step-height Reynolds number of the reference case"),
        "inlet_profile": TODO("numerics.inlet_profile", "reference inlet boundary-layer state; a guessed profile invalidates the comparison"),
        "turbulence_inlet_bc": TODO("numerics.turbulence_inlet_bc", "inlet k/omega as the reference specifies"),
        "wall_treatment": TODO("numerics.wall_treatment", "resolved vs wall function, per the reference"),
    },
    bounds={
        "expansion_ratio": TODO("bounds.expansion_ratio", "admissible expansion-ratio envelope"),
        "cells": TODO("bounds.cells", "admissible grid-size range"),
    },
    tolerances={
        "reattachment_length_tolerance": TODO("tolerances.reattachment_length_tolerance", "acceptance tolerance on x_r/h"),
        "Cp_profile_tolerance": TODO("tolerances.Cp_profile_tolerance", "acceptance tolerance on wall pressure"),
        "Cf_profile_tolerance": TODO("tolerances.Cf_profile_tolerance", "acceptance tolerance on wall skin friction"),
        "velocity_profile_tolerance": TODO("tolerances.velocity_profile_tolerance", "acceptance tolerance on mean velocity profiles"),
        "convergence_residual": TODO("tolerances.convergence_residual", "residual level at which the steady solve is converged"),
        "y_plus_target": TODO("tolerances.y_plus_target", "wall-normal resolution requirement"),
        "under_resolution_criterion": TODO("tolerances.under_resolution_criterion", "criterion for when a named region is under-resolved"),
    },
    reference_values={
        "reattachment_length_over_h": TODO("reference_values.reattachment_length_over_h", "reference reattachment location"),
        "Cp_distribution": TODO("reference_values.Cp_distribution", "reference wall pressure distribution"),
        "Cf_distribution": TODO("reference_values.Cf_distribution", "reference wall skin-friction distribution"),
        "velocity_profiles": TODO("reference_values.velocity_profiles", "reference mean velocity profiles and their stations"),
    },
    allowed_actions=(
        "ACCEPT", "CONTINUE_RUN", "REFINE_MESH", "REFINE_REGION",
        "REQUEST_CLARIFICATION", "REJECT_UNSUPPORTED", "FAIL_SAFELY",
    ),
    region_vocabulary=('step_corner', 'shear_layer', 'reattachment', 'recovery'),
    notes=(
        "CORE-PENDING. Scientific recipe unregistered. Astra supplies these "
        "after reviewing the authoritative reference."
    ),
)
