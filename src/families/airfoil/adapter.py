#!/usr/bin/env python3
"""Family 3 adapter: 2D turbulent NACA0012, NASA TMR 2DN00.

Delegates to src/pipeline/airfoil/*. Adds no science and no thresholds.

The family stays CORE-PENDING and non-routable for execution until FOUR gates
close, in order:

  1. registered benchmark assets present, with registered SHA256 digests;
  2. all three frozen Gmsh mesh levels report F3_MESH_QUALIFIED;
  3. a coarse pilot is numerically sane;
  4. canonical validation passes.

`readiness()` reports all four. `check_scope` refuses while any is open, so a
request can never reach a solver through this family by accident.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from src.families.base import (
    ACCEPT,
    CORRECT_AND_RERUN,
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
from src.families.airfoil.recipe import RECIPE, REGION_VOCABULARY
from src.families.airfoil.spec import (
    ALPHA_ENVELOPE_DEG,
    FAMILY,
    GRID_KEYS,
    PHYSICS,
    AirfoilSpec,
    refine_ceiling_cells,
)
from src.pipeline.airfoil import assets as asset_mod
from src.pipeline.airfoil import collect_evidence as collector
from src.pipeline.airfoil import execute as executor
from src.pipeline.airfoil import mesh_audit
from src.pipeline.airfoil import mesh_hierarchy
from src.pipeline.airfoil import validate as validator
from src.pipeline.airfoil.build import build as build_case_files

#: Readiness gates, in the order they must close.
GATE_ASSETS = "registered_assets"
#: All THREE frozen mesh levels must report F3_MESH_QUALIFIED. This gate is
#: computed from the per-level reports on disk, so it cannot be closed by editing
#: the readiness file.
GATE_MESH_HIERARCHY = "mesh_hierarchy_qualified"
GATE_PILOT = "coarse_pilot_sane"
GATE_CANONICAL = "canonical_validation"
GATES = (GATE_ASSETS, GATE_MESH_HIERARCHY, GATE_PILOT, GATE_CANONICAL)

#: Where a closed gate is recorded. Absent file means the gate is open.
READINESS_FILE = Path("configs") / "families" / "airfoil" / "readiness.json"


class AirfoilAdapter:
    name = FAMILY
    status = "CORE-PENDING"
    physics = PHYSICS
    recipe = RECIPE
    #: Ceiling is the finest REGISTERED level; refining past it leaves the frozen
    #: hierarchy. REFINE_REGION refuses for this family anyway, because no
    #: under-resolution criterion is registered.
    region_policy = RefineRegionPolicy(max_total_cells=refine_ceiling_cells())

    # ------------------------------------------------------------------
    @staticmethod
    def readiness(repo_root: Optional[Path] = None) -> Dict[str, Any]:
        """The four gates. Reports, never asserts readiness it cannot see."""
        import json

        root = Path(repo_root) if repo_root else Path(__file__).resolve().parents[3]
        audit = asset_mod.audit_assets(repo_root)
        recorded: Dict[str, Any] = {}
        path = root / READINESS_FILE
        if path.exists():
            try:
                recorded = json.loads(path.read_text(encoding="utf-8")) or {}
            except (OSError, ValueError):
                recorded = {}

        mesh_state = mesh_hierarchy.hierarchy_state(repo_root)
        gates = {
            GATE_ASSETS: bool(audit["all_required_ok"]),
            GATE_MESH_HIERARCHY: bool(mesh_state["all_qualified"]),
            GATE_PILOT: bool(recorded.get(GATE_PILOT)),
            GATE_CANONICAL: bool(recorded.get(GATE_CANONICAL)),
        }
        open_gates = [k for k in GATES if not gates[k]]
        return {
            "family": FAMILY,
            "status": "CORE-PENDING",
            "gates": gates,
            "open_gates": open_gates,
            "ready_for_core": not open_gates,
            "asset_audit": audit,
            "mesh_hierarchy": mesh_state,
            "readiness_file": str(path),
            "note": (
                "the family becomes routable for execution only when all four gates "
                "are closed; until then it is visible and inspectable only"
            ),
        }

    # -- request handling ------------------------------------------------
    def parse_request(self, text: str) -> Tuple[AirfoilSpec, Dict[str, Any]]:
        raise NotImplementedError(
            f"{FAMILY}: request parsing is not wired while the family is "
            "CORE-PENDING. Canonical closure comes first; see readiness()."
        )

    def load_spec(self, path: Path) -> AirfoilSpec:
        import json

        path = Path(path)
        if path.is_dir():
            path = path / "spec.json"
        return AirfoilSpec.from_dict(json.loads(path.read_text(encoding="utf-8")))

    def load_evidence(self, path: Path) -> Dict[str, Any]:
        """Assemble evidence from an output directory. Reads only; no CFD."""
        path = Path(path)
        spec_path = path / "spec.json"
        if not spec_path.exists():
            spec_path = path.parent / "case" / "spec.json"
        if not spec_path.exists():
            raise FileNotFoundError(
                f"{FAMILY}: no spec.json for the run under {path}"
            )
        spec = self.load_spec(spec_path)
        case = spec_path.parent if spec_path.parent.name == "case" else None
        return collector.assemble(spec=spec, out_dir=path, case=case)

    def check_scope(self, spec: Any) -> ScopeResult:
        """Deterministic admissibility. Refuses while any readiness gate is open."""
        reasons: List[str] = []
        checks: Dict[str, bool] = {}
        measurements: Dict[str, float] = {}

        readiness = self.readiness()
        checks["scientific_closure_complete"] = bool(readiness["ready_for_core"])
        if not readiness["ready_for_core"]:
            reasons.append(
                f"{FAMILY} is CORE-PENDING: open gates "
                f"{readiness['open_gates']}. Registered assets, three qualified "
                "mesh levels, a sane coarse pilot and canonical validation must all "
                "close before a request may execute here."
            )

        if not isinstance(spec, AirfoilSpec):
            checks["spec_is_airfoil_spec"] = False
            reasons.append("spec is not an AirfoilSpec")
            return ScopeResult(False, f"{REJECT} / OUT_OF_FAMILY", reasons, checks)
        checks["spec_is_airfoil_spec"] = True

        lo, hi = ALPHA_ENVELOPE_DEG
        checks["alpha_in_envelope"] = lo - 1e-12 <= spec.alpha_deg <= hi + 1e-12
        measurements["alpha_deg"] = float(spec.alpha_deg)
        if not checks["alpha_in_envelope"]:
            reasons.append(
                f"alpha = {spec.alpha_deg} is outside the registered attached / "
                f"pre-stall envelope [{lo}, {hi}] degrees"
            )

        checks["grid_is_registered"] = spec.grid in GRID_KEYS
        if not checks["grid_is_registered"]:
            reasons.append(
                f"grid {spec.grid!r} is not one of the preregistered levels "
                f"{GRID_KEYS}. No mesh is substituted."
            )
        mesh_state = readiness["mesh_hierarchy"]
        level_state = mesh_state["levels"].get(spec.grid, {})
        checks["requested_level_is_qualified"] = (
            level_state.get("verdict") == mesh_hierarchy.QUALIFIED
        )
        if not checks["requested_level_is_qualified"]:
            reasons.append(
                f"mesh level {spec.grid!r} is not qualified: verdict "
                f"{level_state.get('verdict')!r}, failed "
                f"{level_state.get('failed')}. Generate and qualify it first; no "
                "threshold is relaxed to route a case."
            )
        cells = spec.cells
        if cells is not None:
            measurements["cells"] = float(cells)
        checks["scaling_identity_holds"] = abs(
            spec.reynolds_number - 6.0e6
        ) / 6.0e6 < 1e-9
        measurements["Re_c"] = float(spec.reynolds_number)
        if not checks["scaling_identity_holds"]:
            reasons.append("the frozen chord/velocity/viscosity identity is violated")

        asset_state = readiness["asset_audit"]
        checks["registered_assets_present"] = bool(asset_state["all_required_ok"])
        if not asset_state["all_required_ok"]:
            reasons.append(
                "registered assets are not in order: missing "
                f"{asset_state['missing_required']}, unregistered digests "
                f"{asset_state['unregistered']}, mismatched "
                f"{asset_state['mismatched']}. Nothing is substituted."
            )

        approved = all(checks.values())
        decision = (
            "IN_SCOPE" if approved
            else f"{REJECT} / {CRITERION_NOT_REGISTERED}"
            if not checks["scientific_closure_complete"]
            else f"{REJECT} / OUTSIDE_REGISTERED_ENVELOPE"
        )
        return ScopeResult(approved, decision, reasons, checks, measurements,
                           [] if approved else list(readiness["open_gates"]))

    # -- case lifecycle --------------------------------------------------
    def build_case(self, spec: AirfoilSpec, destination: Path,
                   converted_mesh: Optional[Path] = None) -> Path:
        if converted_mesh is None:
            raise FileNotFoundError(
                f"{FAMILY}: build_case needs the converted registered mesh produced "
                "by the zero-CFD audit. This family never generates geometry."
            )
        return build_case_files(spec, destination, converted_mesh)

    def run_case(self, case: Path, *, append: bool = False) -> int:
        raise executor.ExecutionRefused(
            f"{FAMILY}: the shared loop may not launch this family's solver. "
            "Execution goes through src/pipeline/airfoil/execute.py with an "
            "explicit allow_cfd=True, a passing mesh audit and registered assets."
        )

    def collect_evidence(self, case: Path, out: Path) -> Dict[str, Any]:
        return self.load_evidence(Path(out))

    def audit_mesh(self, grid_key: str, *, out_dir: Optional[Path] = None,
                   repo_root: Optional[Path] = None,
                   runtime: Optional[Any] = None) -> Dict[str, Any]:
        """The zero-CFD mesh audit. Never launches the flow solver.

        ``runtime`` is a FoamRuntime; supplying it enables Stage B (gmshToFoam,
        the boundary rewrite and checkMesh), which are mesh utilities.
        """
        return mesh_audit.audit_grid(
            grid_key, repo_root=repo_root, out_dir=out_dir, runtime=runtime
        ).to_dict()

    @staticmethod
    def evidence_schema() -> Dict[str, Any]:
        return {
            "family": FAMILY,
            "spec": "AirfoilSpec.to_dict()",
            "mesh": "audit status, converted cell count, full conversion provenance",
            "solver": "final-window initial residuals, flux imbalance, NaN/Inf, "
                      "turbulence-field positivity, bounding, completion",
            "conservation": "normalised flux imbalance",
            "stationarity": "CD/CL series statistics over the qualification window",
            "quantitative": "CL, CD, Cp(x/c) per surface, Cp RMSE vs CFL3D, y+ stats",
            "references": "Ladson tripped drag, CFL3D forces/Cp/Cf, availability",
            "grid_sensitivity": "CD change and inter-grid Cp RMSE",
            "provenance": "asset audit, recipe fingerprint, M=0.15 vs incompressible",
        }

    # -- reasoning -------------------------------------------------------
    def diagnose(self, evidence: Dict[str, Any], spec: Any) -> Tuple[Proposal, Dict[str, Any]]:
        raise NotImplementedError(
            f"{FAMILY}: no LLM diagnosis prompt is registered while the family is "
            "CORE-PENDING."
        )

    def deterministic_proposal(self, evidence: Dict[str, Any], spec: Any) -> Proposal:
        """Recipe-driven proposal. Never proposes iterating toward a reference."""
        result = self.validate(evidence, spec)
        status = result["status"]
        if status == validator.STATUS_PASS:
            return Proposal("ACCEPTABLE", "ACCEPT", "recipe: every registered check passed")
        if status == validator.STATUS_UNQUALIFIED:
            return Proposal(
                "UNCONVERGED", "CONTINUE_RUN",
                "recipe: numerical qualification is incomplete and the run is "
                "healthy inside the declared budget",
            )
        if status == validator.STATUS_INCONCLUSIVE:
            return Proposal(
                "INSUFFICIENT_EVIDENCE", "FAIL_SAFELY",
                "recipe: registered external-reference evidence is unavailable; "
                "more iterations cannot supply it",
            )
        return Proposal(
            "OUTSIDE_VALIDATED_DOMAIN", "FAIL_SAFELY",
            "recipe: a registered criterion failed. A converged case that misses an "
            "external reference is not fixed by further iteration.",
        )

    def allowed_actions(self, evidence: Dict[str, Any], spec: Any) -> List[str]:
        return list(RECIPE.allowed_actions)

    # -- authority -------------------------------------------------------
    def execute_action(self, action: str, spec: Any, evidence: Dict[str, Any],
                       *, proposal: Optional[Proposal] = None,
                       validation: Optional[Dict[str, Any]] = None,
                       iterations_used: int = 1, max_iterations: int = 4,
                       **kw: Any) -> ActionRuling:
        if action == REFINE_REGION:
            return rule_on_region_request(
                region_hint=proposal.region_hint if proposal else None,
                vocabulary=REGION_VOCABULARY,
                selection=None,
                resolution_verdict=NOT_ESTABLISHED,
                policy=self.region_policy,
                levels_already_applied=0,
            )
        if action not in RECIPE.allowed_actions:
            return ActionRuling(
                False, action,
                [f"{action!r} is not in this family's bounded action set "
                 f"{RECIPE.allowed_actions}"],
            )

        result = validation or self.validate(evidence, spec)
        status = result["status"]

        if action == "ACCEPT":
            if status != validator.STATUS_PASS:
                return ActionRuling(
                    False, action,
                    [f"cannot ACCEPT: validator status is {status}"]
                    + [f"failed: {c}" for c in result["failed_checks"][:6]],
                )
            return ActionRuling(True, action, ["every registered criterion passed"])

        if action == "CONTINUE_RUN":
            if status == validator.STATUS_FAIL:
                return ActionRuling(
                    False, action,
                    [
                        "refusing CONTINUE_RUN: a registered criterion has FAILED. "
                        "Further iteration must not be used to close a gap against "
                        "an external reference."
                    ],
                )
            if status == validator.STATUS_INCONCLUSIVE:
                return ActionRuling(
                    False, action,
                    ["refusing CONTINUE_RUN: the reference evidence is unavailable; "
                     "more iterations cannot supply it"],
                )
            if iterations_used >= max_iterations:
                return ActionRuling(
                    False, action,
                    [f"iteration budget exhausted ({iterations_used}/{max_iterations})"],
                )
            budget = getattr(spec, "end_iterations", None)
            return ActionRuling(
                True, action,
                ["numerically unqualified but healthy; continuing inside the "
                 f"declared budget of {budget} iterations"],
                {"continuation": "same spec, integration resumes"},
                corrected_spec=spec,
            )

        return ActionRuling(True, action, [f"{action} requires no case change"])

    def validate(self, evidence: Dict[str, Any], spec: Any) -> Dict[str, Any]:
        alpha = float(getattr(spec, "alpha_deg", 0.0) or 0.0)
        result = validator.validate(evidence, alpha)
        unresolved = RECIPE.unresolved()
        if unresolved:  # pragma: no cover - acceptance recipe is registered
            result = dict(result)
            result["status"] = CRITERION_NOT_REGISTERED
            result["unresolved_criteria"] = unresolved
        result["blocked_capabilities"] = RECIPE.unresolved_capabilities()
        result["readiness"] = self.readiness()["gates"]
        return result

    def maps_to_decision(self, validation: Dict[str, Any]) -> Decision:
        status = validation.get("status")
        if status == validator.STATUS_PASS:
            return ACCEPT
        if status == validator.STATUS_UNQUALIFIED:
            return CORRECT_AND_RERUN
        if status == validator.STATUS_FAIL:
            return REJECT
        return INCONCLUSIVE

    def summarize(self, *, spec: Any, evidence: Dict[str, Any],
                  validation: Dict[str, Any], out: Path) -> None:
        import json

        out = Path(out)
        out.mkdir(parents=True, exist_ok=True)
        (out / "family_summary.json").write_text(
            json.dumps(
                {
                    "family": FAMILY,
                    "status": validation.get("status"),
                    "failed_checks": validation.get("failed_checks", []),
                    "unknown_checks": validation.get("unknown_checks", []),
                    "readiness": self.readiness()["gates"],
                    "blocked_capabilities": RECIPE.unresolved_capabilities(),
                    "wall_resolution": validation.get("wall_resolution"),
                    "provenance_note": validation.get("provenance_note"),
                },
                indent=2, default=str,
            ),
            encoding="utf-8",
        )
