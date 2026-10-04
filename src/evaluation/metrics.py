#!/usr/bin/env python3
"""Evaluation metrics for the legacy ablation harness. Nothing here fabricates a number.

This module is a separate legacy ablation harness. The paper's controller
comparison (arms A fixed rule, B CFD Forge, B' gates off, C model-only) was run
by paper/cfd_forge/scripts/controller_comparison.py: arms A, B and B' call
src.orchestrator.loop.decide_once, and arm C is implemented in that script.
The arms defined below are not those arms.

Every metric is defined as a function of runs that ACTUALLY HAPPENED. A metric
computed over zero runs returns `NOT_RUN`, never 0.0 -- a false-acceptance rate
of "0" that nobody measured is worse than an honest blank.

The headline metric is `false_acceptance_rate`: the fraction of runs that were
ACCEPTED when the registered ground truth says they should not have been. It is
the number the architecture exists to keep at zero, so it is the number that must
never be reported from an unexecuted experiment.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

METRICS_VERSION = "evaluation-metrics/1.0.0"

NOT_RUN = "NOT_RUN"

#: The four configurations of this legacy ablation harness (not the paper's
#: controller-comparison arms; see the module docstring).
ARM_FULL = "full_agent"
ARM_RECIPE = "fixed_recipe_fixed_rules"
ARM_NO_GATES = "agent_without_deterministic_gates"
ARM_NO_DIAGNOSIS = "gates_without_diagnosis_or_repair"
ARMS = (ARM_FULL, ARM_RECIPE, ARM_NO_GATES, ARM_NO_DIAGNOSIS)

METRIC_DEFINITIONS: Dict[str, str] = {
    "valid_completion": "runs that produced a decision with complete evidence",
    "false_acceptance": "runs ACCEPTED whose registered ground truth is not ACCEPT",
    "correct_rejection": "runs REJECTED whose ground truth is REJECT",
    "first_attempt_success": "runs ACCEPTED on iteration 1, ground truth ACCEPT",
    "corrected_success": "runs ACCEPTED after >= 1 corrective action",
    "actions_per_run": "mean number of corrective actions executed",
    "solver_attempts": "mean number of solver launches per run",
    "runtime_seconds": "mean wall-clock seconds per run",
    "human_interventions": "manual interventions required",
    "llm_cost": "LLM tokens or currency where the provider reports it",
}


@dataclass
class RunRecord:
    """One evaluated run. `ground_truth` is the registered expected verdict."""

    case: str
    arm: str
    verdict: str
    ground_truth: str
    iterations: int = 1
    actions: int = 0
    solver_attempts: int = 0
    runtime_seconds: Optional[float] = None
    human_interventions: int = 0
    llm_cost: Optional[float] = None
    evidence_complete: bool = True

    @property
    def false_acceptance(self) -> bool:
        return self.verdict == "ACCEPT" and self.ground_truth != "ACCEPT"

    @property
    def correct_rejection(self) -> bool:
        return self.verdict == "REJECT" and self.ground_truth == "REJECT"


@dataclass
class ArmResult:
    arm: str
    runs: List[RunRecord] = field(default_factory=list)

    def metric(self, name: str) -> Any:
        if not self.runs:
            return NOT_RUN
        n = len(self.runs)
        if name == "valid_completion":
            return sum(r.evidence_complete for r in self.runs) / n
        if name == "false_acceptance":
            return sum(r.false_acceptance for r in self.runs) / n
        if name == "correct_rejection":
            expected = [r for r in self.runs if r.ground_truth == "REJECT"]
            return (sum(r.correct_rejection for r in expected) / len(expected)
                    if expected else NOT_RUN)
        if name == "first_attempt_success":
            return sum(r.verdict == "ACCEPT" and r.iterations == 1
                       and r.ground_truth == "ACCEPT" for r in self.runs) / n
        if name == "corrected_success":
            return sum(r.verdict == "ACCEPT" and r.actions > 0 for r in self.runs) / n
        if name == "actions_per_run":
            return sum(r.actions for r in self.runs) / n
        if name == "solver_attempts":
            return sum(r.solver_attempts for r in self.runs) / n
        if name == "runtime_seconds":
            values = [r.runtime_seconds for r in self.runs if r.runtime_seconds]
            return sum(values) / len(values) if values else NOT_RUN
        if name == "human_interventions":
            return sum(r.human_interventions for r in self.runs)
        if name == "llm_cost":
            values = [r.llm_cost for r in self.runs if r.llm_cost is not None]
            return sum(values) if values else NOT_RUN
        raise KeyError(f"unknown metric {name!r}")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "arm": self.arm,
            "runs": len(self.runs),
            "metrics": {name: self.metric(name) for name in METRIC_DEFINITIONS},
        }


def summarise(records: Sequence[RunRecord]) -> Dict[str, Any]:
    """Full study summary. Arms with no runs are reported as NOT_RUN."""
    arms = {arm: ArmResult(arm=arm) for arm in ARMS}
    for record in records:
        arms.setdefault(record.arm, ArmResult(arm=record.arm)).runs.append(record)
    return {
        "metrics_version": METRICS_VERSION,
        "metric_definitions": dict(METRIC_DEFINITIONS),
        "arms": {name: result.to_dict() for name, result in arms.items()},
        "total_runs": len(records),
        "status": NOT_RUN if not records else "PARTIAL" ,
        "note": ("a metric over zero runs is NOT_RUN, never 0.0; no number in "
                 "this summary may be reported unless its runs were executed"),
    }
