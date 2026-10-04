from dataclasses import dataclass, asdict, field
from enum import Enum
from typing import Any, Dict, List, Optional


class Diagnosis(str, Enum):
    ACCEPTABLE = "ACCEPTABLE"

    UNCONVERGED = "UNCONVERGED"

    MESH_RESOLUTION = "MESH_RESOLUTION"
    MESH_QUALITY = "MESH_QUALITY"

    NUMERICAL_FAILURE = "NUMERICAL_FAILURE"
    BOUNDARY_ANOMALY = "BOUNDARY_ANOMALY"

    SUSPECT_NUMERICAL_ANOMALY = "SUSPECT_NUMERICAL_ANOMALY"

    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"

    OUTSIDE_VALIDATED_DOMAIN = "OUTSIDE_VALIDATED_DOMAIN"


class AgentAction(str, Enum):
    ACCEPT = "ACCEPT"

    CONTINUE_RUN = "CONTINUE_RUN"

    REQUEST_DIAGNOSTIC = "REQUEST_DIAGNOSTIC"

    REFINE_THROAT = "REFINE_THROAT"
    REFINE_GRADIENT_REGION = "REFINE_GRADIENT_REGION"

    REPAIR_MESH = "REPAIR_MESH"

    RESTART_CLEAN = "RESTART_CLEAN"

    REJECT_OUTSIDE_DOMAIN = "REJECT_OUTSIDE_DOMAIN"


@dataclass
class CompetingHypothesis:
    hypothesis: str

    evidence_for: List[str] = field(default_factory=list)
    evidence_against: List[str] = field(default_factory=list)


@dataclass
class AgentDecision:
    diagnosis: Diagnosis

    evidence_used: List[str]

    competing_hypotheses: List[CompetingHypothesis]

    reasoning_summary: str

    action: AgentAction

    target_region: Optional[str] = None

    requested_diagnostic: Optional[str] = None

    confidence: str = "medium"

    def validate(self) -> None:
        allowed_confidence = {"low", "medium", "high"}

        if self.confidence not in allowed_confidence:
            raise ValueError(
                f"confidence must be one of {allowed_confidence}"
            )

        if not self.evidence_used:
            raise ValueError(
                "AgentDecision must cite at least one evidence item."
            )

        if self.action == AgentAction.REQUEST_DIAGNOSTIC:
            if not self.requested_diagnostic:
                raise ValueError(
                    "REQUEST_DIAGNOSTIC requires requested_diagnostic."
                )

        if self.action in {
            AgentAction.REFINE_THROAT,
            AgentAction.REFINE_GRADIENT_REGION,
            AgentAction.REPAIR_MESH,
        }:
            if not self.target_region:
                raise ValueError(
                    f"{self.action.value} requires target_region."
                )

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["diagnosis"] = self.diagnosis.value
        data["action"] = self.action.value
        return data
