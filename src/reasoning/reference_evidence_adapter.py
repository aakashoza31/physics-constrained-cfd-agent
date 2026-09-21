"""Adapt deterministic validator output into theory-blind CFDEvidence.

The parameterized validator (src/pipeline/nozzle/validate.py) writes a
validation.json that contains BOTH the measured CFD state and the post-hoc
quasi-1D comparison (``theory`` and ``theory_error_pct``).  The comparison is
research evaluation material and must never enter the autonomous decision loop.

This adapter therefore:

  1. reads only measured, deterministically computed quantities,
  2. never reads ``theory``, ``theory_error_pct`` or ``theory_consistency``,
  3. runs the repository's existing theory-blindness assertion over its own
     output before returning it.

It deliberately does not soften anything.  The deterministic check outcomes are
carried through as they are; the LLM is given the same failures the validator
found, and the final acceptance decision is made elsewhere, by the validator,
not by whatever the LLM concludes from this packet.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from src.contracts.cfd_evidence import (
    BoundaryEvidence,
    CFDEvidence,
    ConservationEvidence,
    EngineeringEvidence,
    FlowFeatureEvidence,
    MeshEvidence,
    PhysicalAdmissibilityEvidence,
    SolverHealthEvidence,
    StationarityEvidence,
    VisualEvidence,
)
from src.reasoning.evidence_packet import assert_theory_blind_payload


WITHHELD_KEYS = ("theory", "theory_error_pct")
WITHHELD_CHECKS = ("theory_consistency",)


def _pct(value: Optional[float]) -> Optional[float]:
    """Convert a relative fraction to a percentage."""
    return None if value is None else 100.0 * float(value)


def build_evidence_from_validation(
    validation: Dict[str, Any],
    *,
    mesh_report: Optional[Dict[str, Any]] = None,
    execution: Optional[Dict[str, Any]] = None,
    iteration: int = 1,
    case_id: Optional[str] = None,
) -> CFDEvidence:
    checks: Dict[str, bool] = dict(validation.get("checks", {}))
    final: Dict[str, Any] = dict(validation.get("final", {}))
    drift: Dict[str, float] = dict(validation.get("drift_fraction_last_2ms", {}))
    l2: Dict[str, float] = dict(validation.get("field_L2_change_last_2ms", {}))
    mesh_report = mesh_report or {}
    execution = execution or {}

    all_time_min = validation.get("all_time_min_p_T_rho") or [None, None, None]

    median_dt = validation.get("median_dt_last_100")
    timestep_collapse = bool(
        median_dt is not None and float(median_dt) <= 1e-9
    )

    solver = SolverHealthEvidence(
        completed_normally=bool(checks.get("solver_completed")),
        max_courant_number=validation.get("max_Co"),
        # A failure to reach the requested horizon is not, by itself, timestep
        # collapse.  Collapse is the specific small-dt condition used by the
        # deterministic validator.
        timestep_collapse_detected=timestep_collapse,
        nan_detected=not bool(checks.get("no_fatal", True)),
        inf_detected=not bool(checks.get("positive_finite", True)),
        solver_error_detected=not bool(checks.get("no_fatal", True)),
        notes=[
            f"execution status: {execution.get('status', 'unknown')}",
            f"timesteps: {validation.get('timesteps')}",
            f"final dt: {validation.get('final_dt')}",
            f"median dt over last 100 monitor steps: {validation.get('median_dt_last_100')}",
            f"monitor last physical time: {validation.get('monitor_last_time_s')}",
            f"requested physical horizon: {validation.get('requested_end_time_s')}",
            "Diagonal inviscid explicit updates print zero linear residuals; "
            "these are not steady-convergence evidence.",
        ],
    )

    conservation = ConservationEvidence(
        inlet_mass_flow_kg_s=final.get("inlet_mdot"),
        outlet_mass_flow_kg_s=final.get("outlet_mdot"),
        # The worst mismatch over the declared stationarity window, not the
        # instantaneous final value: the conservative number is the one the
        # reasoning step should see.
        mass_imbalance_percent=final.get("max_window_mismatch_pct"),
        mass_imbalance_trend=(
            "within declared steady balance criterion"
            if checks.get("steady_mass_balance")
            else "exceeds declared steady balance criterion"
        ),
    )

    stationarity = StationarityEvidence(
        enough_samples=bool(validation.get("history") is not None or final),
        passes_stationarity=bool(
            checks.get("monitors_stationary") and checks.get("fields_stationary")
        ),
        mass_flow_range_percent=_pct(drift.get("outlet_mdot")),
        mass_flow_drift_percent=_pct(drift.get("inlet_mdot")),
        outlet_pressure_range_percent=_pct(drift.get("outlet_p")),
        outlet_pressure_drift_percent=_pct(l2.get("p")),
        outlet_temperature_range_percent=_pct(drift.get("outlet_T")),
        outlet_temperature_drift_percent=_pct(l2.get("T")),
        outlet_velocity_range_percent=_pct(drift.get("outlet_U")),
        outlet_velocity_drift_percent=_pct(l2.get("U")),
        pressure_extrema_trend=f"all-time minimum p = {all_time_min[0]}",
        temperature_extrema_trend=f"all-time minimum T = {all_time_min[1]}",
        density_extrema_trend=f"all-time minimum rho = {all_time_min[2]}",
    )

    positive = bool(checks.get("positive_finite"))

    admissibility = PhysicalAdmissibilityEvidence(
        pressure_positive=positive,
        temperature_positive=positive,
        density_positive=positive,
        pressure_min_pa=final.get("p_min"),
        pressure_max_pa=final.get("p_max"),
        temperature_min_k=final.get("T_min"),
        temperature_max_k=final.get("T_max"),
        density_min_kg_m3=final.get("rho_min"),
        density_max_kg_m3=None,
        suspicious_local_state_detected=not bool(
            checks.get("stagnation_enthalpy", False)
        ),
        suspicious_region=(
            None
            if checks.get("stagnation_enthalpy")
            else "stagnation-enthalpy deviation exceeds the declared bound"
        ),
        notes=[
            "Maximum saved stagnation-enthalpy relative deviation: "
            f"{validation.get('max_saved_h0_relative_error')}",
        ],
    )

    inlet_ok = bool(checks.get("inlet_subsonic_inflow"))
    outlet_ok = bool(checks.get("outlet_all_supersonic"))
    reservoir_ok = bool(checks.get("reservoir_conditions"))

    boundaries = BoundaryEvidence(
        inlet_mass_flow_kg_s=final.get("inlet_mdot"),
        outlet_mass_flow_kg_s=final.get("outlet_mdot"),
        inlet_flow_direction_valid=inlet_ok,
        outlet_flow_direction_valid=outlet_ok,
        inlet_reverse_flow_detected=not inlet_ok,
        outlet_reverse_flow_detected=(
            None
            if final.get("outlet_normal_M_min") is None
            else float(final["outlet_normal_M_min"]) <= 0.0
        ),
        boundary_anomaly_detected=not (inlet_ok and outlet_ok and reservoir_ok),
        notes=[
            f"minimum outward-normal outlet Mach: {final.get('outlet_normal_M_min')}",
            f"maximum outward-normal inlet Mach: {final.get('inlet_normal_M_max')}",
            "Prescribed reservoir totals recovered at the inlet within "
            f"{final.get('inlet_max_p0_relative_error')} (p0) and "
            f"{final.get('inlet_max_T0_relative_error')} (T0) relative error.",
            "Outlet is pressure-free; no static pressure is imposed there.",
        ],
    )

    mesh = MeshEvidence(
        check_mesh_passed=bool(checks.get("mesh_ok")),
        cell_count=mesh_report.get("cells"),
        max_non_orthogonality_deg=mesh_report.get("max_non_orthogonality_deg"),
        max_skewness=mesh_report.get("max_skewness"),
        max_aspect_ratio=mesh_report.get("max_aspect_ratio"),
        local_quality_issue_detected=not bool(checks.get("mesh_ok")),
        local_quality_issue_region=None,
        region_resolution={
            "axial_cells": mesh_report.get("axial_cells"),
            "radial_cells": mesh_report.get("radial_cells"),
        },
        notes=["checkMesh -allTopology -allGeometry"],
    )

    flow_features = FlowFeatureEvidence(
        strongest_gradient_region="throat and diverging section",
        pressure_gradient_region="diverging section",
        velocity_gradient_region="throat",
        mach_gradient_region="throat",
        density_gradient_region="diverging section",
        shock_candidate_detected=not bool(
            checks.get("no_internal_normal_shock", True)
        ),
        shock_candidate_region=(
            None
            if checks.get("no_internal_normal_shock", True)
            else "downstream slab average returns to subsonic flow"
        ),
        sonic_transition_detected=bool(checks.get("sonic_throat")),
        sonic_transition_region="finite throat region",
        candidate_underresolved_regions=[],
        notes=[
            "minimum downstream slab-average Mach: "
            f"{validation.get('min_downstream_slab_Mach')}",
            "volume-weighted finite-throat Mach: " f"{final.get('throat_M')}",
        ],
    )

    # No image pixels are supplied to this text reasoning stage tonight.
    visuals = VisualEvidence(
        visual_anomaly_detected=None,
        visual_candidate_regions=[],
        notes=["No visual evidence stage in this run."],
    )

    engineering = EngineeringEvidence(
        requested_outputs=[
            "exit Mach number",
            "exit static pressure",
            "exit static temperature",
            "exit velocity",
            "mass flow rate",
            "throat Mach number",
        ],
        measured_outputs={
            "exit_mach": final.get("outlet_M"),
            "exit_static_pressure_pa": final.get("outlet_p"),
            "exit_static_temperature_k": final.get("outlet_T"),
            "exit_velocity_m_s": final.get("outlet_U"),
            "exit_mass_flow_kg_s": final.get("outlet_mdot"),
            "inlet_mass_flow_kg_s": final.get("inlet_mdot"),
            "throat_mach": final.get("throat_M"),
            "minimum_outlet_normal_mach": final.get("outlet_normal_M_min"),
            "boundary_mismatch_pct": final.get("boundary_mismatch_pct"),
            "max_window_mismatch_pct": final.get("max_window_mismatch_pct"),
            "max_transient_continuity_pct": validation.get(
                "max_transient_continuity_pct"
            ),
            "deterministic_checks": {
                k: v for k, v in checks.items() if k not in WITHHELD_CHECKS
            },
        },
    )

    evidence = CFDEvidence(
        solver=solver,
        conservation=conservation,
        stationarity=stationarity,
        admissibility=admissibility,
        boundaries=boundaries,
        mesh=mesh,
        flow_features=flow_features,
        visuals=visuals,
        engineering=engineering,
        iteration=iteration,
        case_id=case_id or validation.get("case_id"),
    )

    # Fail closed: refuse to hand over a packet containing reference targets.
    assert_theory_blind_payload(evidence.to_dict())

    return evidence


def withheld_from_agent(validation: Dict[str, Any]) -> Dict[str, Any]:
    """The post-hoc comparison that is revealed only after the agent decides."""
    return {
        key: validation[key] for key in WITHHELD_KEYS if key in validation
    }
