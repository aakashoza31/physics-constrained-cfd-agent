from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

from src.contracts.agent_decision import (
    AgentAction,
    AgentDecision,
    Diagnosis,
)
from src.contracts.cfd_evidence import CFDEvidence


@dataclass
class ActionValidationResult:
    approved: bool
    reasons: List[str] = field(default_factory=list)


def validate_agent_action(
    evidence: CFDEvidence,
    decision: AgentDecision,
) -> ActionValidationResult:

    decision.validate()

    reasons: List[str] = []

    solver_bad = (
        not evidence.solver.completed_normally
        or evidence.solver.nan_detected
        or evidence.solver.inf_detected
        or evidence.solver.solver_error_detected
        or evidence.solver.timestep_collapse_detected
    )

    admissibility_bad = (
        not evidence.admissibility.pressure_positive
        or not evidence.admissibility.temperature_positive
        or not evidence.admissibility.density_positive
    )

    boundary_bad = (
        evidence.boundaries.boundary_anomaly_detected
        or evidence.boundaries.inlet_reverse_flow_detected is True
    )

    unresolved_local_anomaly = (
        evidence.admissibility.suspicious_local_state_detected is True
    )

    local_anomaly_unknown = (
        evidence.admissibility.suspicious_local_state_detected is None
    )

    boundary_evidence_unknown = (
        evidence.boundaries.boundary_anomaly_detected is None
        or evidence.boundaries.inlet_reverse_flow_detected is None
        or evidence.boundaries.outlet_reverse_flow_detected is None
    )

    conservation_pass = (
        evidence.conservation.mass_imbalance_percent is not None
        and evidence.conservation.mass_imbalance_percent <= 1.0
    )

    stationarity_pass = evidence.stationarity.passes_stationarity

    # ------------------------------------------------------------
    # ACCEPT
    # ------------------------------------------------------------

    if decision.action == AgentAction.ACCEPT:

        if solver_bad:
            reasons.append("Cannot ACCEPT: solver-health failure exists.")

        if admissibility_bad:
            reasons.append(
                "Cannot ACCEPT: physical admissibility failure exists."
            )

        if not conservation_pass:
            reasons.append(
                "Cannot ACCEPT: configured mass-conservation criterion fails."
            )

        if not stationarity_pass:
            reasons.append(
                "Cannot ACCEPT: configured stationarity criterion fails."
            )

        if boundary_bad:
            reasons.append(
                "Cannot ACCEPT: unresolved boundary anomaly exists."
            )

        if unresolved_local_anomaly:
            reasons.append(
                "Cannot ACCEPT: unresolved local numerical anomaly exists."
            )

        if local_anomaly_unknown:
            reasons.append(
                "Cannot ACCEPT: localized numerical-anomaly status is unknown."
            )

        if boundary_evidence_unknown:
            reasons.append(
                "Cannot ACCEPT: required boundary/reverse-flow evidence is incomplete."
            )

        if reasons:
            return ActionValidationResult(False, reasons)

        return ActionValidationResult(
            True,
            ["ACCEPT is consistent with deterministic trust checks."],
        )

    # ------------------------------------------------------------
    # CONTINUE RUN
    # ------------------------------------------------------------

    if decision.action == AgentAction.CONTINUE_RUN:

        if solver_bad:
            reasons.append(
                "CONTINUE_RUN rejected because solver health is already poor."
            )

        if admissibility_bad:
            reasons.append(
                "CONTINUE_RUN rejected because thermodynamic admissibility fails."
            )

        if unresolved_local_anomaly:
            reasons.append(
                "CONTINUE_RUN alone is insufficient while a severe local "
                "anomaly remains unresolved."
            )

        if reasons:
            return ActionValidationResult(False, reasons)

        return ActionValidationResult(
            True,
            ["CONTINUE_RUN is permitted for a healthy evolving solution."],
        )

    # ------------------------------------------------------------
    # REFINE THROAT
    # ------------------------------------------------------------

    if decision.action == AgentAction.REFINE_THROAT:

        if solver_bad:
            reasons.append(
                "REFINE_THROAT rejected: solver failure must be diagnosed first."
            )

        if admissibility_bad:
            reasons.append(
                "REFINE_THROAT rejected: nonphysical state requires diagnosis first."
            )

        if boundary_bad:
            reasons.append(
                "REFINE_THROAT rejected: boundary anomaly is unresolved."
            )

        throat_supported = (
            evidence.flow_features.strongest_gradient_region == "throat"
            or evidence.flow_features.pressure_gradient_region == "throat"
            or evidence.flow_features.velocity_gradient_region == "throat"
            or evidence.flow_features.mach_gradient_region == "throat"
            or "throat"
            in evidence.flow_features.candidate_underresolved_regions
        )

        if not throat_supported:
            reasons.append(
                "REFINE_THROAT rejected: evidence does not localize an "
                "under-resolution concern to the throat."
            )

        if evidence.mesh.local_quality_issue_detected:
            reasons.append(
                "REFINE_THROAT rejected: mesh-quality defect should be "
                "distinguished from resolution deficiency."
            )

        if reasons:
            return ActionValidationResult(False, reasons)

        return ActionValidationResult(
            True,
            [
                "REFINE_THROAT is supported by localized flow-feature "
                "and mesh-resolution evidence."
            ],
        )

    # ------------------------------------------------------------
    # REFINE GENERAL GRADIENT REGION
    # ------------------------------------------------------------

    if decision.action == AgentAction.REFINE_GRADIENT_REGION:

        if solver_bad or admissibility_bad or boundary_bad:
            reasons.append(
                "REFINE_GRADIENT_REGION rejected until numerical/boundary "
                "failures are resolved."
            )

        if not decision.target_region:
            reasons.append(
                "REFINE_GRADIENT_REGION requires a target region."
            )

        candidates = set(
            evidence.flow_features.candidate_underresolved_regions
        )

        if decision.target_region not in candidates:
            reasons.append(
                "Requested refinement region is not supported by the "
                "candidate-underresolved-region evidence."
            )

        if reasons:
            return ActionValidationResult(False, reasons)

        return ActionValidationResult(
            True,
            ["Localized gradient-region refinement is evidence-supported."],
        )

    # ------------------------------------------------------------
    # REPAIR MESH
    # ------------------------------------------------------------

    if decision.action == AgentAction.REPAIR_MESH:

        if (
            evidence.mesh.check_mesh_passed
            and not evidence.mesh.local_quality_issue_detected
        ):
            return ActionValidationResult(
                False,
                [
                    "REPAIR_MESH rejected: no demonstrated mesh-quality "
                    "failure exists."
                ],
            )

        return ActionValidationResult(
            True,
            ["REPAIR_MESH is supported by mesh-quality evidence."],
        )

    # ------------------------------------------------------------
    # RESTART CLEAN
    # ------------------------------------------------------------

    if decision.action == AgentAction.RESTART_CLEAN:

        if not (
            unresolved_local_anomaly
            or decision.diagnosis
            in {
                Diagnosis.NUMERICAL_FAILURE,
                Diagnosis.SUSPECT_NUMERICAL_ANOMALY,
            }
        ):
            return ActionValidationResult(
                False,
                [
                    "RESTART_CLEAN rejected: no evidence of an untrusted "
                    "numerical/inherited state was supplied."
                ],
            )

        return ActionValidationResult(
            True,
            ["Clean restart is permitted for an untrusted numerical state."],
        )

    # ------------------------------------------------------------
    # REQUEST DIAGNOSTIC
    # ------------------------------------------------------------

    if decision.action == AgentAction.REQUEST_DIAGNOSTIC:

        return ActionValidationResult(
            True,
            [
                "Additional diagnostic acquisition is always allowed "
                "when explicitly specified."
            ],
        )

    # ------------------------------------------------------------
    # OUTSIDE DOMAIN
    # ------------------------------------------------------------

    if decision.action == AgentAction.REJECT_OUTSIDE_DOMAIN:

        if decision.diagnosis != Diagnosis.OUTSIDE_VALIDATED_DOMAIN:
            return ActionValidationResult(
                False,
                [
                    "REJECT_OUTSIDE_DOMAIN requires "
                    "OUTSIDE_VALIDATED_DOMAIN diagnosis."
                ],
            )

        return ActionValidationResult(
            True,
            ["Outside-domain rejection is internally consistent."],
        )

    return ActionValidationResult(
        False,
        [f"Unsupported or unvalidated action: {decision.action.value}"],
    )
