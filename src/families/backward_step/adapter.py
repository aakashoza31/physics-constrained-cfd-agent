#!/usr/bin/env python3
"""2D turbulent backward-facing step adapter skeleton.

Every hook the shared orchestrator calls exists and is wired to the shared
decision machinery, so the family is already exercised by the architecture
tests. Nothing that requires a scientific constant will run: those hooks raise
NotImplementedError with the specific missing constant named, and validate()
returns CRITERION_NOT_REGISTERED so the decision can only be INCONCLUSIVE.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from src.families.base import (
    CRITERION_NOT_REGISTERED,
    INCONCLUSIVE,
    REJECT,
    ActionRuling,
    Decision,
    Proposal,
    ScopeResult,
)
from src.families.refine_region import (
    ACTION as REFINE_REGION,
    NOT_ESTABLISHED,
    RefineRegionPolicy,
    rule_on_region_request,
)
from src.families.backward_step.recipe import RECIPE
from src.families.backward_step.spec import FAMILY, PHYSICS, BackwardStepSpec

#: Closed vocabulary of regions the LLM may name once the family is registered.
#: Naming a region is architecture; deciding it is under-resolved is science and
#: stays TODO.
REGION_VOCABULARY = ('step_corner', 'shear_layer', 'reattachment', 'recovery')


class BackwardStepAdapter:
    name = FAMILY
    status = "CORE-PENDING"
    physics = PHYSICS
    recipe = RECIPE
    region_policy = RefineRegionPolicy()

    # -- request handling ------------------------------------------------
    def parse_request(self, text: str) -> Tuple[BackwardStepSpec, Dict[str, Any]]:
        raise NotImplementedError(
            f"{FAMILY}: request parsing needs the registered request envelope; "
            f"unresolved: {RECIPE.unresolved()}"
        )

    def load_spec(self, path: Path) -> BackwardStepSpec:
        """Load a frozen spec once the recipe is registered.

        Refuses while acceptance constants are unresolved: loading a spec would
        imply a registered envelope this family does not have.
        """
        import json

        unresolved = RECIPE.unresolved()
        if unresolved:
            raise NotImplementedError(
                f"{FAMILY}: cannot load a spec while these acceptance "
                f"constants are unregistered: {', '.join(unresolved)}"
            )
        return BackwardStepSpec.from_dict(json.loads(Path(path).read_text()))  # pragma: no cover

    def load_evidence(self, path: Path) -> Dict[str, Any]:
        raise NotImplementedError(
            f"{FAMILY}: evidence layout is unregistered; the target shape is "
            "given by evidence_schema()"
        )

    def check_scope(self, spec: BackwardStepSpec) -> ScopeResult:
        """Refuse until the envelope is registered. Fails closed by design."""
        unresolved = RECIPE.unresolved()
        if unresolved:
            return ScopeResult(
                approved=False,
                decision=f"{REJECT} / {CRITERION_NOT_REGISTERED}",
                reasons=[
                    f"family {FAMILY} has no registered scientific envelope; "
                    f"unresolved: {', '.join(unresolved)}"
                ],
                checks={"envelope_registered": False},
                clarification_needed=list(unresolved),
            )
        raise NotImplementedError(  # pragma: no cover - reached once registered
            f"{FAMILY}: implement the scope gate once the envelope is registered"
        )

    # -- case lifecycle --------------------------------------------------
    def build_case(self, spec: BackwardStepSpec, destination: Path) -> Path:
        raise NotImplementedError(
            f"{FAMILY}: mesh strategy is unregistered ({MESH_NOTE})"
        )

    def run_case(self, case: Path, *, append: bool = False) -> int:
        raise NotImplementedError(f"{FAMILY}: solver recipe unregistered")

    def collect_evidence(self, case: Path, out: Path) -> Dict[str, Any]:
        raise NotImplementedError(f"{FAMILY}: evidence schema below is the target shape")

    @staticmethod
    def evidence_schema() -> Dict[str, Any]:
        """The shape collect_evidence must return once implemented."""
        return {
            "family": FAMILY,
            "spec": "BackwardStepSpec.to_dict()",
            "mesh": "checkMesh report, cell count, y+ distribution",
            "solver": "residual history, completion, iteration count",
            "conservation": "inlet/outlet mass balance",
            "stationarity": "residual plateau and reattachment-location drift",
            "quantitative": "x_r/h, Cp(x/h), Cf(x/h), U profiles at reference stations",
            "provenance": "case fingerprint, solver version, dict hashes",
        }

    # -- reasoning -------------------------------------------------------
    def diagnose(self, evidence: Dict[str, Any], spec: BackwardStepSpec) -> Tuple[Proposal, Dict[str, Any]]:
        raise NotImplementedError(f"{FAMILY}: no diagnosis prompt registered yet")

    def deterministic_proposal(self, evidence: Dict[str, Any], spec: BackwardStepSpec) -> Proposal:
        return Proposal(
            diagnosis="INSUFFICIENT_EVIDENCE",
            action="FAIL_SAFELY",
            reasoning_summary=(
                f"recipe unregistered: {', '.join(RECIPE.unresolved())}"
            ),
        )

    def allowed_actions(self, evidence: Dict[str, Any], spec: BackwardStepSpec) -> List[str]:
        return list(RECIPE.allowed_actions)

    # -- authority -------------------------------------------------------
    def execute_action(self, action: str, spec: BackwardStepSpec, evidence: Dict[str, Any],
                       *, proposal: Optional[Proposal] = None, **kw: Any) -> ActionRuling:
        if action == REFINE_REGION:
            return rule_on_region_request(
                region_hint=proposal.region_hint if proposal else None,
                vocabulary=REGION_VOCABULARY,
                selection=None,
                resolution_verdict=NOT_ESTABLISHED,
                policy=self.region_policy,
                levels_already_applied=0,
            )
        return ActionRuling(
            False,
            action,
            [
                f"{CRITERION_NOT_REGISTERED}: no corrective action can be "
                f"justified for {FAMILY} while these are unresolved: "
                f"{', '.join(RECIPE.unresolved())}"
            ],
        )

    def validate(self, evidence: Dict[str, Any], spec: BackwardStepSpec) -> Dict[str, Any]:
        unresolved = RECIPE.unresolved()
        return {
            "family": FAMILY,
            "status": CRITERION_NOT_REGISTERED,
            "failed_checks": [],
            "unresolved_criteria": unresolved,
            "unresolved_detail": RECIPE.unresolved_detail(),
            "authority": "deterministic",
            "note": (
                "no acceptance criteria are registered for this family, so no "
                "result may be accepted"
            ),
        }

    def maps_to_decision(self, validation: Dict[str, Any]) -> Decision:
        return INCONCLUSIVE

    def summarize(self, *, spec: Any, evidence: Dict[str, Any],
                  validation: Dict[str, Any], out: Path) -> None:
        import json

        Path(out).mkdir(parents=True, exist_ok=True)
        (Path(out) / "family_summary.json").write_text(
            json.dumps(
                {
                    "family": FAMILY,
                    "status": self.status,
                    "recipe_registered": RECIPE.is_registered(),
                    "unresolved_criteria": RECIPE.unresolved(),
                    "unresolved_detail": RECIPE.unresolved_detail(),
                },
                indent=2,
            )
        )


MESH_NOTE = "mesh target, y+ target and grid family all unregistered"
