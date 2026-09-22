#!/usr/bin/env python3
"""Bounded action space and deterministic action validator for forward-step 2D.

PROVENANCE
----------
Follows the authority split of ``src/reasoning/action_validator.py`` (the
nozzle family): the model proposes, deterministic code decides whether the
proposal may be executed, and the reasons are recorded either way.

The action set is deliberately small and every action maps to one bounded,
pre-defined edit. The model can never hand back free-form OpenFOAM dictionary
text, and no action changes the solver, the flux scheme, the reconstruction,
the thermophysical model or the physics. Those live in the frozen template.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from src.pipeline.forward_step_2d.spec import MAX_CELLS, ForwardStep2DSpec


class ForwardStepAction(str, Enum):
    ACCEPT = "ACCEPT"
    CONTINUE_RUN = "CONTINUE_RUN"
    EXTEND_END_TIME = "EXTEND_END_TIME"
    REDUCE_MAX_CO = "REDUCE_MAX_CO"
    REFINE_MESH = "REFINE_MESH"
    REBUILD_FROM_VALIDATED_SPEC = "REBUILD_FROM_VALIDATED_SPEC"
    REQUEST_CLARIFICATION = "REQUEST_CLARIFICATION"
    REJECT_UNSUPPORTED = "REJECT_UNSUPPORTED"
    FAIL_SAFELY = "FAIL_SAFELY"


class ForwardStepDiagnosis(str, Enum):
    HEALTHY_COMPLETE = "HEALTHY_COMPLETE"
    HEALTHY_INCOMPLETE = "HEALTHY_INCOMPLETE"
    NUMERICALLY_UNSTABLE = "NUMERICALLY_UNSTABLE"
    MESH_PROBLEM = "MESH_PROBLEM"
    NO_COMPRESSION_STRUCTURE = "NO_COMPRESSION_STRUCTURE"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    OUTSIDE_VALIDATED_FAMILY = "OUTSIDE_VALIDATED_FAMILY"


# Bounded refinement policy: one step of uniform refinement, capped.
REFINE_FACTOR = 1.5
MAX_CO_FLOOR = 0.05
MAX_EXTEND_FACTOR = 3.0


@dataclass
class ActionValidation:
    approved: bool
    action: str
    reasons: List[str] = field(default_factory=list)
    resulting_changes: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "approved": self.approved,
            "action": self.action,
            "reasons": self.reasons,
            "resulting_changes": self.resulting_changes,
            "authority": "deterministic",
        }


def _healthy(d: Dict[str, Any]) -> bool:
    """Numerically healthy enough that continuing is meaningful."""
    return (
        not d.get("fatal_error", True)
        and bool(d.get("finite_all_saved"))
        and bool(d.get("positive_all_saved"))
        and all(v > 0 for v in d.get("minima_every_step", {"x": -1}).values())
        and bool(d.get("courant_finite_positive"))
    )


def validate_action(
    action: str,
    spec: ForwardStep2DSpec,
    diagnostics: Dict[str, Any],
    validation: Dict[str, Any],
    *,
    max_end_time: float,
    iterations_used: int,
    max_iterations: int,
    clarification: Optional[str] = None,
) -> ActionValidation:
    """Decide whether a proposed action may be executed. Fail closed."""
    reasons: List[str] = []

    try:
        action = ForwardStepAction(action).value
    except ValueError:
        return ActionValidation(
            False,
            str(action),
            [f"{action!r} is not in the bounded action set for this family."],
        )

    scientific_pass = validation.get("status") == "PASS_2D_FORWARD_STEP"
    reached = bool(diagnostics.get("reached_requested_end_time"))
    healthy = _healthy(diagnostics)

    # The two horizons the action semantics turn on. `reached` is about the
    # execution that just ran; `reached_target` is about the science.
    target = float(
        spec.final_target_end_time
        if spec.final_target_end_time is not None
        else spec.end_time
    )
    final_time = float(diagnostics.get("final_time") or 0.0)
    reached_target = final_time >= target - 1e-9

    if iterations_used >= max_iterations and action in {
        ForwardStepAction.CONTINUE_RUN.value,
        ForwardStepAction.EXTEND_END_TIME.value,
        ForwardStepAction.REDUCE_MAX_CO.value,
        ForwardStepAction.REFINE_MESH.value,
        ForwardStepAction.REBUILD_FROM_VALIDATED_SPEC.value,
    }:
        return ActionValidation(
            False,
            action,
            [
                f"Iteration budget exhausted ({iterations_used}/{max_iterations}); "
                "no further CFD actions may be executed."
            ],
        )

    # ---------------- ACCEPT -----------------------------------------
    if action == ForwardStepAction.ACCEPT.value:
        if not scientific_pass:
            # Distinguish "defective" from "not finished": both block ACCEPT,
            # but only one of them is a problem with the solution.
            if not validation.get("failed_checks") and not reached_target:
                return ActionValidation(
                    False,
                    action,
                    [
                        "ACCEPT refused: the state is healthy on all hard "
                        f"checks, but the run has reached only t = "
                        f"{final_time:g} of the registered final target "
                        f"t = {target:g}. Passing the hard checks means the "
                        "state that exists is sound, not that the benchmark "
                        "has been realized. EXTEND_END_TIME is the action."
                    ],
                )
            failed = ", ".join(validation.get("failed_checks", [])) or validation.get(
                "status", "unknown"
            )
            return ActionValidation(
                False,
                action,
                [
                    "ACCEPT refused: the deterministic validator did not return "
                    f"PASS_2D_FORWARD_STEP ({validation.get('status')}). "
                    f"Outstanding: {failed}."
                ],
            )
        return ActionValidation(
            True,
            action,
            ["ACCEPT is consistent with the deterministic forward-step checks."],
        )

    # ---------------- CONTINUE_RUN -----------------------------------
    if action == ForwardStepAction.CONTINUE_RUN.value:
        if reached:
            reason = (
                "CONTINUE_RUN refused: the requested horizon "
                f"t = {spec.end_time:g} was already reached. CONTINUE_RUN "
                "resumes an execution that stopped short of its own horizon; "
                "there is nothing left to resume toward."
            )
            # Name the action that does apply. A gate that only says no leaves
            # the workflow stuck on a healthy run, which is what happened at
            # t = 1 of the first iterative experiment.
            if not reached_target:
                reason += (
                    f" The final target t = {target:g} has not been reached, "
                    "so EXTEND_END_TIME is the action for more physical "
                    "evolution."
                )
            else:
                reason += (
                    f" The final target t = {target:g} has also been reached, "
                    "so the decision is ACCEPT or FAIL_SAFELY."
                )
            return ActionValidation(False, action, [reason])
        if not healthy:
            return ActionValidation(
                False,
                action,
                [
                    "CONTINUE_RUN refused: the state is not numerically healthy; "
                    "continuing would propagate a defective solution."
                ],
            )
        return ActionValidation(
            True,
            action,
            [
                "CONTINUE_RUN is permitted: the solution is numerically healthy "
                f"and has not yet reached t = {spec.end_time:g}."
            ],
            {"resume_from": diagnostics.get("final_time"), "end_time": spec.end_time},
        )

    # ---------------- EXTEND_END_TIME --------------------------------
    if action == ForwardStepAction.EXTEND_END_TIME.value:
        if not healthy:
            return ActionValidation(
                False, action, ["EXTEND_END_TIME refused: state is not numerically healthy."]
            )
        if not reached:
            return ActionValidation(
                False,
                action,
                [
                    "EXTEND_END_TIME refused: the current horizon "
                    f"t = {spec.end_time:g} has not been reached yet "
                    f"(the run stopped at t = {final_time:g}). Moving the "
                    "horizon further away does not finish the execution that "
                    "is still outstanding; CONTINUE_RUN is the action for "
                    "that."
                ],
            )
        if reached_target:
            return ActionValidation(
                False,
                action,
                [
                    "EXTEND_END_TIME refused: the registered final target "
                    f"t = {target:g} has been reached. Extending past a "
                    "satisfied scientific horizon is not a bounded action; "
                    "the decision now is ACCEPT or FAIL_SAFELY."
                ],
            )
        # Never overshoot the declared scientific target: the loop advances
        # toward it, it does not wander past it.
        proposed = min(spec.end_time * 2.0, max_end_time, target)
        if proposed <= spec.end_time + 1e-12:
            return ActionValidation(
                False,
                action,
                [
                    "EXTEND_END_TIME refused: already at the declared maximum "
                    f"horizon {min(max_end_time, target):g}."
                ],
            )
        if proposed > ForwardStep2DSpec().end_time * MAX_EXTEND_FACTOR:
            reasons.append(
                "Extension clamped by the declared family bound "
                f"({MAX_EXTEND_FACTOR}x the canonical horizon)."
            )
            proposed = min(proposed, ForwardStep2DSpec().end_time * MAX_EXTEND_FACTOR)
        reasons.append(
            f"EXTEND_END_TIME permitted: {spec.end_time:g} -> {proposed:g} on a "
            f"healthy run that reached its current horizon; final target "
            f"t = {target:g}."
        )
        return ActionValidation(True, action, reasons, {"end_time": proposed})

    # ---------------- REDUCE_MAX_CO ----------------------------------
    if action == ForwardStepAction.REDUCE_MAX_CO.value:
        proposed = spec.max_co / 2.0
        if proposed < MAX_CO_FLOOR:
            return ActionValidation(
                False,
                action,
                [
                    f"REDUCE_MAX_CO refused: {proposed:g} is below the family floor "
                    f"{MAX_CO_FLOOR:g}; a failure at that Courant number is not a "
                    "time-step problem."
                ],
            )
        return ActionValidation(
            True,
            action,
            [
                "REDUCE_MAX_CO permitted: halving the Courant limit stays inside "
                "the trusted recipe, which caps maxCo at 0.2."
            ],
            {"max_co": proposed},
        )

    # ---------------- REFINE_MESH ------------------------------------
    if action == ForwardStepAction.REFINE_MESH.value:
        nx = int(round(spec.nx * REFINE_FACTOR))
        ny = int(round(spec.ny * REFINE_FACTOR))
        try:
            refined = spec.with_changes(nx=nx, ny=ny)
        except ValueError as exc:
            return ActionValidation(
                False, action, [f"REFINE_MESH refused: {exc}"]
            )
        if refined.cells > MAX_CELLS:
            return ActionValidation(
                False,
                action,
                [
                    f"REFINE_MESH refused: {refined.cells} cells exceeds the "
                    f"{MAX_CELLS} bound for this family."
                ],
            )
        return ActionValidation(
            True,
            action,
            [
                "REFINE_MESH permitted under the bounded uniform policy "
                f"(x{REFINE_FACTOR}): {spec.cells} -> {refined.cells} cells. "
                "Geometry and the numerical recipe are unchanged."
            ],
            {"nx": nx, "ny": ny, "cells": refined.cells},
        )

    # ---------------- REBUILD_FROM_VALIDATED_SPEC --------------------
    if action == ForwardStepAction.REBUILD_FROM_VALIDATED_SPEC.value:
        return ActionValidation(
            True,
            action,
            [
                "REBUILD_FROM_VALIDATED_SPEC permitted: a fresh case is generated "
                "from the frozen template and the already-validated specification. "
                "Existing evidence is preserved in a new directory."
            ],
            {"spec": spec.to_dict()},
        )

    # ---------------- terminal / non-CFD actions ---------------------
    if action == ForwardStepAction.REQUEST_CLARIFICATION.value:
        if not clarification:
            return ActionValidation(
                False,
                action,
                ["REQUEST_CLARIFICATION refused: no question was supplied."],
            )
        return ActionValidation(
            True, action, ["Clarification request recorded for the user."], {"question": clarification}
        )

    if action == ForwardStepAction.REJECT_UNSUPPORTED.value:
        return ActionValidation(
            True,
            action,
            ["Rejection of an unsupported request is always permitted."],
        )

    if action == ForwardStepAction.FAIL_SAFELY.value:
        return ActionValidation(
            True,
            action,
            [
                "FAIL_SAFELY permitted: evidence is preserved and no further CFD "
                "is executed."
            ],
        )

    return ActionValidation(False, action, ["Unhandled action."])
