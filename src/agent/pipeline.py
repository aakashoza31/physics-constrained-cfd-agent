#!/usr/bin/env python3
"""The product contract, implemented as one ordered pipeline.

    natural-language problem (+ optional STEP)
      -> request interpreter          [model proposes]
      -> geometry characterization    [deterministic]
      -> family router                [model proposes, code decides]
      -> registered family contract   [deterministic]
      -> case / mesh generation       [deterministic]
      -> OpenFOAM execution           [deterministic, live mode only]
      -> evidence extraction          [deterministic]
      -> LLM diagnosis                [model proposes]
      -> deterministic authority      [deterministic]
      -> bounded correction loop      [code decides which actions are permitted]
      -> ACCEPT / REJECT / INCONCLUSIVE
      -> engineering report + contours + video + provenance

Every stage records what it did into an `AgentRun`, and the stages that a model
touches are marked as proposals in the authority trace. The pipeline STOPS at the
first stage that refuses: an unsupported geometry never reaches mesh generation,
and a non-routable family never reaches a solver.

Modes
-----
  live     execute OpenFOAM. Requires Foundation v14 and an explicit opt-in.
  replay   read archived evidence for a registered case. Never claims a solver ran.
  dry-run  stop after admissibility and the family contract. Touches nothing.

Scope note: this generic pipeline, and its ``gemini`` backend in particular, is
a simplified demonstration path. It is not the path used for the paper's runs,
which go through the family runners (``scripts/run_nozzle_feedback.py``,
``scripts/run_nozzle_e2e.py``, ``scripts/run_forward_step_2d.py``). Action
vocabularies come from ``src/families/capabilities.py``; a proposed action is
permitted only if it is an exact member of the family's vocabulary.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.agent import backends as agent_backends
from src.agent.interpret import ProblemStatement, interpret
from src.authority import AuthorityTrace, Decision, final_decision
from src.families import capabilities as caps
from src.geometry import features as geom
from src.geometry import matching

PIPELINE_VERSION = "agent-pipeline/1.0.0"

LIVE, REPLAY, DRY_RUN = "live", "replay", "dry-run"
MODES = (LIVE, REPLAY, DRY_RUN)

STAGES = (
    "request_interpretation",
    "geometry_characterization",
    "family_routing",
    "family_contract",
    "case_and_mesh",
    "execution",
    "evidence_extraction",
    "llm_diagnosis",
    "deterministic_authority",
    "bounded_correction",
    "final_decision",
    "reporting",
)

#: Terminal statuses a run can stop at before reaching a solver.
UNSUPPORTED = "UNSUPPORTED"
NOT_ROUTABLE = "NOT_ROUTABLE"


@dataclass
class StageRecord:
    name: str
    status: str
    detail: Dict[str, Any] = field(default_factory=dict)
    decided_by: str = "deterministic"

    def to_dict(self) -> Dict[str, Any]:
        return {"stage": self.name, "status": self.status,
                "decided_by": self.decided_by, "detail": self.detail}


@dataclass
class AgentRun:
    """One pass through the pipeline, and everything it produced."""

    prompt: str
    mode: str
    family: Optional[str] = None
    case: Optional[str] = None
    statement: Optional[ProblemStatement] = None
    stages: List[StageRecord] = field(default_factory=list)
    trace: AuthorityTrace = field(default_factory=AuthorityTrace)
    decision: Optional[Decision] = None
    backend: Any = None
    artifacts: Dict[str, Any] = field(default_factory=dict)
    started_utc: str = field(
        default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))

    def stage(self, name: str, status: str, **detail: Any) -> StageRecord:
        record = StageRecord(name=name, status=status, detail=detail)
        self.stages.append(record)
        return record

    @property
    def stopped_at(self) -> Optional[str]:
        for record in self.stages:
            if record.status not in ("OK", "PROPOSED", "SKIPPED"):
                return record.name
        return None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "pipeline_version": PIPELINE_VERSION,
            "started_utc": self.started_utc,
            "prompt": self.prompt,
            "mode": self.mode,
            "family": self.family,
            "case": self.case,
            "interpretation": self.statement.to_dict() if self.statement else None,
            "stages": [s.to_dict() for s in self.stages],
            "stopped_at": self.stopped_at,
            "authority_trace": self.trace.to_dict(),
            "final_decision": self.decision.to_dict() if self.decision else None,
            "artifacts": dict(self.artifacts),
            "agent_backend": (self.backend.to_dict() if self.backend is not None
                              else {"backend": "deterministic", "calls": []}),
            "solver_invoked": bool(self.artifacts.get("solver_invoked", False)),
        }


def _contract(family: str) -> Dict[str, Any]:
    """The registered scientific contract a family runs under."""
    from src.families import registry

    registry.install_standing_register()
    record = registry.get(family)
    capability = caps.capabilities(family)
    contract: Dict[str, Any] = {
        "capabilities": capability.to_dict(),
        "registered": record is not None,
    }
    if record is not None:
        contract["register_status"] = getattr(record, "status", None)
    try:
        adapter = registry.adapter(family)
        recipe = getattr(adapter, "recipe", None)
        if recipe is not None:
            contract["recipe_reference"] = getattr(recipe, "reference", "")
            contract["unresolved_constants"] = list(recipe.unresolved())
            contract["allowed_actions"] = list(recipe.allowed_actions)
    except Exception as exc:                      # noqa: BLE001 - reported
        contract["adapter_error"] = f"{type(exc).__name__}: {exc}"
    return contract


def run_pipeline(prompt: str, *, mode: str = DRY_RUN,
                 geometry: Optional[Path] = None,
                 family: Optional[str] = None,
                 case: Optional[str] = None,
                 parameters: Optional[Dict[str, float]] = None,
                 allow_cfd: bool = False,
                 backend: str = agent_backends.DETERMINISTIC,
                 live_kwargs: Optional[Dict[str, Any]] = None) -> AgentRun:
    """Run the product contract end to end, stopping at the first refusal."""
    if mode not in MODES:
        raise ValueError(f"mode must be one of {MODES}; got {mode!r}")
    run = AgentRun(prompt=prompt, mode=mode, case=case)

    # -- 1. request interpretation (model proposes) --------------------
    source = geom.STEP if geometry else geom.PARAMETRIC
    engine = agent_backends.make(backend)
    run.backend = engine
    statement = engine.interpret(prompt, geometry_source=source)
    if statement.proposed_family and statement.proposed_family not in caps.TABLE:
        statement.proposed_family = None
    if family:
        statement.proposed_family = family
        statement.confidence_note += " | family supplied explicitly by the caller"
    run.statement = statement
    run.trace.proposal("interpret_user_intent", statement.to_dict(),
                       model=statement.interpreter)
    run.stage("request_interpretation", "PROPOSED",
              proposed_family=statement.proposed_family,
              parameters=statement.parameters)

    # -- 2. geometry characterization (deterministic) ------------------
    if geometry:
        features = geom.from_step(Path(geometry))
    else:
        merged = dict(statement.parameters)
        merged.update(parameters or {})
        characteristic = ""
        if statement.proposed_family in caps.TABLE:
            characteristic = caps.capabilities(
                statement.proposed_family).characteristic_dimension
        features = geom.from_parameters(merged, characteristic_name=characteristic)
    # An unsupported geometry is UNRESOLVED, not failed: the system is not
    # asserting that the part is bad, only that it cannot judge it. That is the
    # difference between INCONCLUSIVE and REJECT, and it matters to a user who
    # brings a CAD file.
    run.trace.gate("geometry_admissibility", True if features.usable else None,
                   measured=features.status,
                   threshold="the geometry must be characterisable",
                   detail=features.reason)
    run.stage("geometry_characterization",
              "OK" if features.usable else UNSUPPORTED,
              source=features.source, geometry_status=features.status,
              reason=features.reason)
    run.artifacts["geometry"] = features.to_dict()

    # -- 3. family routing (model proposes, code decides) --------------
    # Replaying a registered case is a different question from routing a new
    # request: an archived REJECTION must stay replayable, which is precisely
    # what the cube demonstration is for. Routability gates LIVE execution.
    if mode == REPLAY and family:
        from src.orchestration import replay as _replay

        canonical = caps.resolve(family)
        try:
            registered = _replay.case_dir(family, case)
            known = True
            detail = f"registered case {family}/{registered.name}"
        except Exception as exc:                  # noqa: BLE001 - reported
            known = False
            detail = str(exc)
        run.family = canonical if known else None
        run.trace.family = canonical
        run.trace.case = case or ""
        run.trace.gate("family_compatibility", known,
                       measured={"family": canonical, "case": case},
                       threshold="the case must be in the registered library",
                       detail=detail)
        run.stage("family_routing", "OK" if known else NOT_ROUTABLE,
                  selected=canonical, replay=True, detail=detail)
        if not known:
            run.decision = final_decision(
                run.trace, reason=f"no registered case to replay: {detail}")
            return run
        contract = _contract(canonical)
        run.artifacts["contract"] = contract
        run.stage("family_contract", "OK",
                  family_status=contract["capabilities"]["status"],
                  routable=contract["capabilities"]["routable"])
        from src.orchestration import replay

        outcome = replay.replay_case(canonical, case)
        run.artifacts.update(outcome.artifacts)
        run.artifacts["solver_invoked"] = False
        for name, status, detail_ in outcome.stages:
            run.stage(name, status, **detail_)
        for gate in outcome.gates:
            run.trace.gate(gate["question"], gate["passed"],
                           measured=gate.get("measured"),
                           threshold=gate.get("threshold"),
                           detail=gate.get("detail", ""))
        allowed = contract["capabilities"]["allowed_actions"]
        proposed_actions = [p["content"] for p in outcome.proposals
                            if p["activity"] == "propose_bounded_action"]
        # A model backend diagnoses the real evidence. Its action must be in the
        # registered vocabulary, and the gate below checks that -- the model does
        # not get to widen its own action set.
        if engine.name == agent_backends.GEMINI:
            call = engine.diagnose(canonical, outcome.artifacts)
            if call.parsed.get("diagnosis"):
                run.trace.proposal("diagnose_evidence", call.parsed["diagnosis"],
                                   model=f"{call.provider}:{call.model}")
            if call.proposed_action:
                proposed_actions.append(call.proposed_action)
                run.trace.proposal("propose_bounded_action", call.proposed_action,
                                   model=f"{call.provider}:{call.model}",
                                   accepted_by_authority=call.action_in_vocabulary)
        run.trace.gate(
            "permitted_actions",
            all(str(a) in allowed for a in proposed_actions)
            if proposed_actions else True,
            measured={"proposed": proposed_actions, "allowed": allowed},
            threshold="a proposed action must be in the family's registered "
                      "vocabulary",
            detail="an action outside the vocabulary is refused, not executed")
        for proposal in outcome.proposals:
            run.trace.proposal(proposal["activity"], proposal["content"],
                               model=proposal.get("model", "archived"),
                               accepted_by_authority=proposal.get(
                                   "accepted_by_authority"))
        run.case = outcome.case
        run.trace.case = outcome.case
        run.decision = final_decision(run.trace, reason=outcome.reason)
        return run

    routing = matching.match(features, proposed=statement.proposed_family)
    run.artifacts["routing"] = routing
    selected = routing["selected_family"]
    run.family = selected
    run.trace.family = selected or ""
    run.trace.case = case or ""
    run.trace.proposal("propose_family_route", statement.proposed_family,
                       model=statement.interpreter,
                       accepted_by_authority=routing["llm_proposal_was_accepted"])
    unsupported_source = (features.source == geom.STEP) or not features.usable
    run.trace.gate("family_compatibility",
                   True if selected else (None if unsupported_source else False),
                   measured=routing["admissible_families"],
                   threshold="exactly one admissible routable family",
                   detail=("no registered family can accept this geometry"
                           if not selected else f"routed to {selected}"))
    if not selected:
        run.stage("family_routing", NOT_ROUTABLE,
                  admissible=routing["admissible_families"],
                  proposed=statement.proposed_family)
        run.artifacts["solver_invoked"] = False
        reason = ("no registered family can accept this request. Nothing was "
                  "meshed and no solver was launched.")
        if unsupported_source:
            reason = (
                "UNSUPPORTED: " + (features.reason or reason) +
                " No registered family declares this geometry source, so the "
                "request is returned as INCONCLUSIVE rather than judged. "
                "Nothing was meshed and no solver was launched.")
        run.decision = final_decision(run.trace, reason=reason)
        return run
    run.stage("family_routing", "OK", selected=selected)

    # -- 4. registered family contract (deterministic) -----------------
    contract = _contract(selected)
    run.artifacts["contract"] = contract
    unresolved = contract.get("unresolved_constants") or []
    run.trace.gate("physical_model", not unresolved,
                   measured=unresolved or "all acceptance constants registered",
                   threshold="no unresolved acceptance constant",
                   detail=contract.get("recipe_reference", ""))
    run.stage("family_contract", "OK" if not unresolved else "INCOMPLETE_CONTRACT",
              unresolved=unresolved)

    # -- 5-7. case / mesh / execution / evidence -----------------------
    if mode == DRY_RUN:
        for name in ("case_and_mesh", "execution", "evidence_extraction",
                     "llm_diagnosis", "bounded_correction"):
            run.stage(name, "SKIPPED", reason="dry-run stops after the contract")
        run.artifacts["solver_invoked"] = False
        # A dry-run has validated nothing. Leaving the evidence gates UNRESOLVED
        # is what makes its verdict INCONCLUSIVE instead of an accidental ACCEPT.
        for question in ("numerical_health", "conservation", "convergence",
                         "stationarity", "validation"):
            run.trace.gate(question, None, measured="not evaluated",
                           threshold="requires an executed or archived run",
                           detail="dry-run stops before any evidence exists")
        run.decision = final_decision(
            run.trace,
            reason=("dry-run: the request was interpreted, the geometry "
                    "characterised and the family contract checked. No mesh was "
                    "built, no solver was launched, and nothing was validated."))
        return run

    if mode == REPLAY:
        from src.orchestration import replay

        outcome = replay.replay_case(selected, case)
        run.artifacts.update(outcome.artifacts)
        run.artifacts["solver_invoked"] = False
        for name, status, detail in outcome.stages:
            run.stage(name, status, **detail)
        for gate in outcome.gates:
            run.trace.gate(gate["question"], gate["passed"],
                           measured=gate.get("measured"),
                           threshold=gate.get("threshold"),
                           detail=gate.get("detail", ""))
        for proposal in outcome.proposals:
            run.trace.proposal(proposal["activity"], proposal["content"],
                               model=proposal.get("model", "archived"),
                               accepted_by_authority=proposal.get(
                                   "accepted_by_authority"))
        run.case = outcome.case
        run.trace.case = outcome.case
        run.decision = final_decision(run.trace, reason=outcome.reason)
        return run

    # -- live -----------------------------------------------------------
    def _no_evidence(reason: str) -> None:
        """Nothing ran, so every evidence gate is UNRESOLVED, not passed."""
        for question in ("numerical_health", "conservation", "convergence",
                         "stationarity", "validation"):
            run.trace.gate(question, None, measured="not evaluated",
                           threshold="requires an executed run", detail=reason)

    if not allow_cfd:
        refusal = ("live mode launches OpenFOAM and requires an explicit "
                   "opt-in: pass --i-want-to-run-cfd")
        run.stage("execution", "REFUSED", reason=refusal)
        run.artifacts["solver_invoked"] = False
        _no_evidence(refusal)
        run.decision = final_decision(
            run.trace, reason="live execution was not authorised by the caller")
        return run
    from src.orchestration import live

    outcome = live.run_case(selected, case, run=run, **(live_kwargs or {}))
    run.artifacts.update(outcome.artifacts)
    run.artifacts.setdefault("solver_invoked", False)
    if run.artifacts["solver_invoked"]:
        # The runner executed. Its deterministic record becomes gates in this
        # trace, so a live run and a replay are judged by the same machinery.
        for gate in outcome.gates:
            run.trace.gate(gate["question"], gate["passed"],
                           measured=gate.get("measured"),
                           threshold=gate.get("threshold"),
                           detail=gate.get("detail", ""))
        for proposal in outcome.proposals:
            run.trace.proposal(proposal["activity"], proposal["content"],
                               model=proposal.get("model", "live"),
                               accepted_by_authority=proposal.get(
                                   "accepted_by_authority"))
        if not outcome.gates:
            _no_evidence("the runner produced no decision record")
    else:
        _no_evidence(outcome.reason)
    run.decision = final_decision(run.trace, reason=outcome.reason)
    return run


def write_run(run: AgentRun, out_dir: Path) -> Path:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "agent_run.json"
    path.write_text(json.dumps(run.to_dict(), indent=2) + "\n", encoding="utf-8")
    return path
