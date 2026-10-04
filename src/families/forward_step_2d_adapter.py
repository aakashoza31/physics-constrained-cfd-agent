#!/usr/bin/env python3
"""Forward-step (2-D) family adapter.

Pure delegation. Every CFD decision stays in src/pipeline/forward_step_2d and
src/reasoning/forward_step_*. This file only translates between those existing
signatures and the shared FamilyAdapter contract, and adds the REFINE_REGION
hook, which is architecture rather than physics.

The frozen scientific recipe is NOT touched: the numbers below are read from
the family modules, not restated here.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from src.families.base import (
    ACCEPT,
    CORRECT_AND_RERUN,
    INCONCLUSIVE,
    REJECT,
    ActionRuling,
    Decision,
    Proposal,
    ScopeResult,
)
from src.families.recipe import FamilyRecipe
from src.families.refine_region import (
    ACTION as REFINE_REGION,
    RefineRegionPolicy,
    rule_on_region_request,
)
from src.pipeline.forward_step_2d import regions as fs_regions
from src.pipeline.forward_step_2d.build import build as fs_build
from src.pipeline.forward_step_2d.collect_evidence import collect as fs_collect
from src.pipeline.forward_step_2d.execute import execute as fs_execute
from src.pipeline.forward_step_2d.spec import (
    CANONICAL_CELLS,
    FAMILY,
    FAMILY_REFERENCE_HORIZON,
    MAX_CELLS,
    PHYSICS,
    ForwardStep2DSpec,
)
from src.pipeline.forward_step_2d.validate import (
    STATUS_FAIL,
    STATUS_HEALTHY_TARGET_NOT_REACHED,
    STATUS_INCOMPLETE,
    STATUS_PASS,
    validate as fs_validate,
)
from src.reasoning.forward_step_actions import (
    ForwardStepAction,
    ForwardStepDiagnosis,
    validate_action as fs_validate_action,
)
from src.reasoning.forward_step_scope_gate import BOUNDS, evaluate_scope as fs_scope

RECIPE = FamilyRecipe(
    family=FAMILY,
    physics=PHYSICS,
    reference=(
        "OpenFOAM forwardStep benchmark case (vendored template under "
        "src/pipeline/forward_step/template); family reference horizon "
        f"t = {FAMILY_REFERENCE_HORIZON} taken from the vendored controlDict endTime"
    ),
    numerics={
        "solver": "shockFluid via foamRun",
        "time_integration": "Euler",
        "flux": "Kurganov",
        "limiter": "vanLeer / vanLeerV",
        "canonical_cells": CANONICAL_CELLS,
        "max_cells": MAX_CELLS,
    },
    bounds=dict(BOUNDS),
    tolerances={
        # Registered in the family validator; restated here as provenance only.
        "transient_mass_relative_residual_max": 1e-6,
        "restart_mass_continuity": 1e-9,
        "initial_state_error_max": 1e-9,
    },
    capability_criteria={
        # REFINE_REGION is an OPTIONAL capability for this frozen family. Its
        # criterion is unregistered, so the capability is unavailable -- but a
        # result that never needed local refinement is still acceptable, which
        # is why this is not in `tolerances`.
        REFINE_REGION: {
            "under_resolution_criterion": fs_regions.UNDER_RESOLUTION_CRITERION,
        },
    },
    reference_values={"family_reference_horizon": FAMILY_REFERENCE_HORIZON},
    allowed_actions=tuple(a.value for a in ForwardStepAction) + (REFINE_REGION,),
    region_vocabulary=fs_regions.CLOSED_VOCABULARY,
    notes=(
        "Frozen and registered for acceptance. This adapter delegates and adds "
        "no scientific value. under_resolution_criterion is deliberately "
        "unresolved, which disables REFINE_REGION for this family -- the "
        "capability refuses rather than guessing -- without affecting the "
        "acceptance of runs that did not need it."
    ),
)


class ForwardStep2DAdapter:
    name = FAMILY
    status = "CORE"
    physics = PHYSICS
    recipe = RECIPE
    region_policy = RefineRegionPolicy(max_total_cells=MAX_CELLS)

    # -- request handling ------------------------------------------------
    def parse_request(self, text: str) -> Tuple[ForwardStep2DSpec, Dict[str, Any]]:
        from src.agents.forward_step_spec_agent import interpret_request

        result = interpret_request(text)
        # interpret_request returns (spec, record) in the existing pipeline;
        # tolerate either shape rather than assuming.
        if isinstance(result, tuple):
            spec, record = result[0], result[1]
        else:  # pragma: no cover
            spec, record = result, {}
        return spec, (record if isinstance(record, dict) else record.__dict__)

    def load_spec(self, path: Path) -> ForwardStep2DSpec:
        return ForwardStep2DSpec.load(Path(path))

    def load_evidence(self, path: Path) -> Dict[str, Any]:
        """Replay an existing output directory. Reads only; no CFD."""
        import json

        path = Path(path)
        diagnostics_path = path / "diagnostics.json"
        if not diagnostics_path.exists():
            raise FileNotFoundError(
                f"{self.name}: no diagnostics.json under {path}; the forward-step "
                "evidence document is written by collect_evidence()"
            )
        diagnostics = json.loads(diagnostics_path.read_text())
        validation_path = path / "validation.json"
        validation = (
            json.loads(validation_path.read_text())
            if validation_path.exists()
            else None
        )
        index_path = path / "evidence_index.json"
        index = json.loads(index_path.read_text()) if index_path.exists() else None
        return self.wrap_evidence(diagnostics, validation, index=index)

    def check_scope(self, spec: ForwardStep2DSpec) -> ScopeResult:
        r = fs_scope(spec)
        return ScopeResult(
            approved=r.approved,
            decision=r.decision,
            reasons=list(r.reasons),
            checks=dict(r.checks),
            measurements=dict(r.measurements),
            clarification_needed=list(r.clarification_needed),
        )

    # -- case lifecycle --------------------------------------------------
    def build_case(self, spec: ForwardStep2DSpec, destination: Path) -> Path:
        return fs_build(spec, destination)

    def run_case(self, case: Path, *, append: bool = False) -> int:
        return fs_execute(Path(case), append=append)

    def collect_evidence(self, case: Path, out: Path) -> Dict[str, Any]:
        """Collect, then present the family's diagnostics in the shared shape.

        The family's own diagnostics dict is carried verbatim under
        ``raw_diagnostics`` -- nothing is reinterpreted or dropped, because the
        validator and the action gate both consume that exact document.
        """
        import json

        out = Path(out)
        index = fs_collect(Path(case), out)
        diagnostics = json.loads((out / "diagnostics.json").read_text())
        validation = json.loads((out / "validation.json").read_text())
        return self.wrap_evidence(diagnostics, validation, index=index)

    @staticmethod
    def wrap_evidence(
        diagnostics: Dict[str, Any],
        validation: Optional[Dict[str, Any]] = None,
        *,
        index: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Shared-shape evidence around an existing family diagnostics dict.

        Used by collect_evidence, by the parity tests and by fault injection, so
        all three see the identical structure.
        """
        return {
            "family": FAMILY,
            "spec": diagnostics.get("spec", {}),
            "mesh": {
                "mesh_ok": diagnostics.get("mesh_ok"),
                "cells": diagnostics.get("cells"),
                "cell_count_matches_spec": diagnostics.get("cell_count_matches_spec"),
                "two_solution_directions": diagnostics.get("two_solution_directions"),
                "mesh_failed_step": diagnostics.get("mesh_failed_step"),
                "boundary": diagnostics.get("boundary", {}),
            },
            "solver": {
                "solver_completed": diagnostics.get("solver_completed"),
                "fatal_error": diagnostics.get("fatal_error"),
                "final_time": diagnostics.get("final_time"),
                "reached_requested_end_time": diagnostics.get(
                    "reached_requested_end_time"
                ),
                "courant_finite_positive": diagnostics.get("courant_finite_positive"),
            },
            "conservation": diagnostics.get("mass", {}),
            "stationarity": {
                "note": "transient family: stationarity is not an acceptance axis",
                "minima_every_step": diagnostics.get("minima_every_step", {}),
            },
            "quantitative": {
                "shock": diagnostics.get("shock", {}),
                "final_ranges": diagnostics.get("final_ranges", {}),
                "initial_state_errors": diagnostics.get("initial_state_errors", {}),
            },
            "provenance": {
                "evidence_index": index or {},
                "fixed_recipe_unchanged": diagnostics.get("fixed_recipe_unchanged"),
            },
            # Verbatim family documents. The authority consumes these.
            "raw_diagnostics": diagnostics,
            "raw_validation": validation,
        }

    # -- reasoning -------------------------------------------------------
    def diagnose(
        self, evidence: Dict[str, Any], spec: ForwardStep2DSpec, *,
        iterations_used: int = 1, max_iterations: int = 4,
    ) -> Tuple[Proposal, Dict[str, Any]]:
        """LLM diagnosis through the family's own reasoning stack.

        ``iterations_used`` / ``max_iterations`` are passed to the diagnosis
        payload. Their defaults (1, 4) are the values this method always used;
        src.orchestrator.loop.decide_once does not pass them, so its behaviour
        is unchanged.
        """
        from src.reasoning.forward_step_diagnosis import diagnose as fs_diagnose

        diagnostics = evidence["raw_diagnostics"]
        validation = evidence.get("raw_validation") or fs_validate(diagnostics)
        decision, gate, record, _payload = fs_diagnose(
            spec,
            diagnostics,
            validation,
            max_end_time=BOUNDS["end_time"][1],
            iterations_used=iterations_used,
            max_iterations=max_iterations,
        )
        proposal = Proposal(
            diagnosis=str(getattr(decision, "diagnosis", "")),
            action=str(getattr(decision, "action", "")),
            reasoning_summary=str(getattr(decision, "reasoning_summary", "") or ""),
            region_hint=getattr(decision, "region_hint", None),
            confidence=str(getattr(decision, "confidence", "unknown")),
            raw={"gate_preview": gate.to_dict()},
        )
        return proposal, record.__dict__ if hasattr(record, "__dict__") else dict(record)

    def deterministic_proposal(
        self, evidence: Dict[str, Any], spec: ForwardStep2DSpec
    ) -> Proposal:
        """Recipe-driven action, used by the baseline and no-diagnosis modes.

        No new science: it reads the family validator's own disposition.
        """
        d = evidence["raw_diagnostics"]
        v = evidence.get("raw_validation") or fs_validate(d)
        status = v.get("status")
        if status == STATUS_PASS:
            return Proposal(ForwardStepDiagnosis.HEALTHY_COMPLETE.value,
                            ForwardStepAction.ACCEPT.value,
                            "recipe: validator reports PASS")
        if status in (STATUS_INCOMPLETE, STATUS_HEALTHY_TARGET_NOT_REACHED):
            reached = bool(d.get("reached_requested_end_time"))
            action = (ForwardStepAction.EXTEND_END_TIME.value if reached
                      else ForwardStepAction.CONTINUE_RUN.value)
            return Proposal(ForwardStepDiagnosis.HEALTHY_INCOMPLETE.value, action,
                            "recipe: horizon not reached")
        return Proposal(ForwardStepDiagnosis.INSUFFICIENT_EVIDENCE.value,
                        ForwardStepAction.FAIL_SAFELY.value,
                        f"recipe: validator status {status}")

    def allowed_actions(
        self, evidence: Dict[str, Any], spec: ForwardStep2DSpec
    ) -> List[str]:
        return list(self.recipe.allowed_actions)

    # -- authority -------------------------------------------------------
    def execute_action(
        self,
        action: str,
        spec: ForwardStep2DSpec,
        evidence: Dict[str, Any],
        *,
        validation: Optional[Dict[str, Any]] = None,
        proposal: Optional[Proposal] = None,
        iterations_used: int = 1,
        max_iterations: int = 4,
        **kw: Any,
    ) -> ActionRuling:
        diagnostics = evidence["raw_diagnostics"]
        validation = validation or evidence.get("raw_validation") or fs_validate(
            diagnostics
        )

        if action == REFINE_REGION:
            return self._rule_refine_region(spec, diagnostics, proposal)

        gate = fs_validate_action(
            action,
            spec,
            diagnostics,
            validation,
            max_end_time=BOUNDS["end_time"][1],
            iterations_used=iterations_used,
            max_iterations=max_iterations,
            clarification=kw.get("clarification"),
            sensitivity=kw.get("sensitivity"),
        )
        corrected = self._apply(action, spec, gate)
        return ActionRuling(
            approved=gate.approved,
            action=gate.action,
            reasons=list(gate.reasons),
            resulting_changes=dict(gate.resulting_changes),
            corrected_spec=corrected,
        )

    def _rule_refine_region(
        self,
        spec: ForwardStep2DSpec,
        diagnostics: Dict[str, Any],
        proposal: Optional[Proposal],
    ) -> ActionRuling:
        hint = proposal.region_hint if proposal is not None else None
        # An unnamed region defaults to the family's primary structure. The
        # default is declared here, not chosen by the model.
        name = hint or fs_regions.SHOCK
        selection = (
            fs_regions.select_region(name, spec, diagnostics,
                                     levels=self.region_policy.levels_per_action)
            if name in fs_regions.CLOSED_VOCABULARY
            else None
        )
        return rule_on_region_request(
            region_hint=hint,
            vocabulary=fs_regions.CLOSED_VOCABULARY,
            selection=selection,
            resolution_verdict=fs_regions.resolution_verdict(name, spec, diagnostics),
            policy=self.region_policy,
            levels_already_applied=spec.refinement_level,
        )

    @staticmethod
    def _apply(
        action: str, spec: ForwardStep2DSpec, gate: Any
    ) -> Optional[ForwardStep2DSpec]:
        """Turn an approved ruling into the next spec, using family code only."""
        if not gate.approved:
            return None
        changes = gate.resulting_changes or {}
        if action == ForwardStepAction.REFINE_MESH.value:
            from src.reasoning.forward_step_mesh_study import refine

            return refine(spec)
        fields = {k: v for k, v in changes.items()
                  if k in ForwardStep2DSpec.__dataclass_fields__}
        if not fields:
            return None
        return ForwardStep2DSpec.from_dict({**spec.to_dict(), **fields})

    def validate(
        self, evidence: Dict[str, Any], spec: ForwardStep2DSpec
    ) -> Dict[str, Any]:
        return fs_validate(evidence["raw_diagnostics"])

    def maps_to_decision(self, validation: Dict[str, Any]) -> Decision:
        status = validation.get("status")
        if status == STATUS_PASS:
            return ACCEPT
        if status in (STATUS_INCOMPLETE, STATUS_HEALTHY_TARGET_NOT_REACHED):
            return CORRECT_AND_RERUN
        if status == STATUS_FAIL:
            return REJECT
        return INCONCLUSIVE

    def summarize(self, *, spec: Any, evidence: Dict[str, Any],
                  validation: Dict[str, Any], out: Path) -> None:
        import json

        Path(out).mkdir(parents=True, exist_ok=True)
        (Path(out) / "family_summary.json").write_text(
            json.dumps(
                {
                    "family": self.name,
                    "status": validation.get("status"),
                    "failed_checks": validation.get("failed_checks", []),
                    "recipe_registered": self.recipe.is_registered(),
                    "unresolved_criteria": self.recipe.unresolved(),
                },
                indent=2,
            )
        )
