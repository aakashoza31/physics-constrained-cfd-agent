#!/usr/bin/env python3
"""Nozzle (Family 1) adapter.

DECISION-LEVEL PARITY IS WIRED. build_case / run_case are NOT.

Everything below delegates to Family 1's own reasoning stack:
``nozzle_diagnosis.diagnose`` for the LLM path, ``_deterministic_decision`` for
the recipe path, ``build_evidence_from_validation`` for the theory-blind
evidence packet, and ``action_validator.validate_agent_action`` for the action
gate. No second validator, no second classifier, no re-derived thresholds.

This adapter can load a frozen nozzle spec and replay an ARCHIVED validation
document through the shared decision loop without launching CFD. Case
construction and execution remain unwired, because they are not pure
delegation: they live inline in scripts/run_nozzle_feedback.py
(_mesh_new_case / _run_solver / _continue_case) mixed with WSL transport and
iteration bookkeeping, and lifting them would mean rewriting Family 1's
execution path rather than delegating to it.

STATUS IN THIS CLOUD WORKING COPY: UNVERIFIED.

This container's copy of the repo is missing the nozzle family's own modules --
src/pipeline/nozzle/spec.py, feedback.py, feedback_diagnostics.py,
scripts/run_nozzle_e2e.py and src/agents/nozzle_demo_agents.py are all absent,
so nothing below could be executed or parity-tested here. Every import is
therefore lazy and every delegation target is named explicitly, so that on the
full repo this file either works or fails with a precise message rather than
silently doing something else.

``self_check()`` reports exactly which delegation targets resolve. Run it first
on the real repo; nozzle parity is meaningless until it returns ok=True.

As with the forward-step adapter, no CFD is reimplemented here and the frozen
nozzle recipe is not touched.
"""
from __future__ import annotations

import importlib
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

def _agent_actions():
    """The family's real AgentAction members, read rather than restated."""
    from src.contracts.agent_decision import AgentAction

    return tuple(AgentAction)


#: NozzleCaseSpec fields that map onto contracts.problem_spec.NozzleGeometry.
#: Only fields the spec actually carries are mapped; a field the spec does not
#: define is reported, never invented.
GEOMETRY_MAP = {
    "inlet_radius_m": ("inlet_radius_m",),
    "throat_radius_m": ("throat_radius_m",),
    "outlet_radius_m": ("exit_radius_m", "outlet_radius_m"),
    "inlet_length_m": ("inlet_straight_m", "inlet_length_m"),
    "converging_length_m": ("converging_m", "converging_length_m"),
    "throat_length_m": ("throat_m", "throat_length_m"),
    "diverging_length_m": ("diverging_m", "diverging_length_m"),
    "outlet_length_m": ("outlet_straight_m", "outlet_length_m"),
}

#: NozzleCaseSpec fields that map onto OperatingConditions.
OPERATING_MAP = {
    "inlet_total_pressure_pa": ("total_pressure_pa",),
    "inlet_total_temperature_k": ("total_temperature_k",),
    "outlet_static_pressure_pa": ("ambient_pressure_pa",),
    "gamma": ("gamma",),
    "gas_constant_j_kg_k": ("gas_constant_j_per_kg_k",),
}

#: Filenames scripts/run_nozzle_feedback.py writes into an iteration output
#: directory. Reading them is how decision-level replay works.
EVIDENCE_FILES = {
    "validation": "validation.json",
    "execution": "execution.json",
    "mesh": "mesh_evidence.json",
    "mesh_steps": "mesh_steps.json",
    "acceptance": "acceptance.json",
}

#: Candidate spec filenames, in the order run_nozzle_feedback.py uses them.
SPEC_FILENAMES = ("feedback_case_spec.json", "case_spec.json", "spec.json")

#: Delegation targets. Kept as data so self_check can probe them without
#: importing anything at module load.
TARGETS = {
    "spec": ("src.pipeline.nozzle.spec", "NozzleCaseSpec"),
    "scope": ("src.reasoning.nozzle_scope_gate", "evaluate_scope"),
    "diagnose": ("src.reasoning.nozzle_diagnosis", "diagnose"),
    "fallback_decision": ("src.reasoning.nozzle_diagnosis", "_deterministic_decision"),
    "evidence": ("src.reasoning.reference_evidence_adapter",
                 "build_evidence_from_validation"),
    "action_gate": ("src.reasoning.action_validator", "validate_agent_action"),
    "parse": ("src.agents.nozzle_case_spec_agent", "interpret_case_request"),
    "feedback": ("src.pipeline.nozzle.feedback", None),
    "feedback_diagnostics": ("src.pipeline.nozzle.feedback_diagnostics", None),
}

RECIPE = FamilyRecipe(
    family="nozzle",
    physics="compressible_euler",
    reference=(
        "quasi-1D isentropic compressible-flow theory for a converging-diverging "
        "nozzle; frozen canonical case validated analytically"
    ),
    numerics={
        "gas": "calorically perfect air",
        "gamma": 1.4,
        "gas_constant_j_per_kg_k": 287.0,
        "outlet": "pressure-free (ambient is interpretation metadata, never a BC)",
    },
    tolerances={
        # Registered in the frozen Family-1 validator. Transcribed here as
        # provenance only: this adapter does not own them, does not evaluate
        # them, and must never be the place they are changed.
        "theory_outlet_pressure_error_pct_max": 5.0,
        "theory_other_output_error_pct_max": 3.0,
    },
    reference_values={
        "source": "quasi-1D isentropic compressible-flow theory (computed, not tabulated)",
    },
    # The ACTUAL bounded action set, taken from src/contracts/agent_decision.py
    # AgentAction. No generic names are invented here: an action this family
    # does not define could never be ruled on by its own action validator.
    allowed_actions=tuple(a.value for a in _agent_actions()),
    region_vocabulary=(),
    notes=(
        "Frozen scientific recipe. Adapter unverified in this working copy; see "
        "self_check(). REFINE_REGION is deliberately not offered for this family "
        "until a region vocabulary is registered for it."
    ),
)


def _resolve(key: str) -> Any:
    module_name, attr = TARGETS[key]
    module = importlib.import_module(module_name)
    return module if attr is None else getattr(module, attr)


class NozzleAdapter:
    name = "nozzle"
    status = "CORE"
    physics = "compressible_euler"
    recipe = RECIPE

    # ------------------------------------------------------------------
    @staticmethod
    def self_check() -> Dict[str, Any]:
        """Probe every delegation target. Run this before trusting the adapter."""
        results: Dict[str, str] = {}
        for key in TARGETS:
            try:
                _resolve(key)
                results[key] = "ok"
            except Exception as exc:  # noqa: BLE001
                results[key] = f"{type(exc).__name__}: {exc}"
        missing = [k for k, v in results.items() if v != "ok"]
        replay_missing = [
            k for k in NozzleAdapter.REPLAY_TARGETS if results.get(k) != "ok"
        ]
        return {
            "family": "nozzle",
            "ok": not missing,
            "replay_ok": not replay_missing,
            "targets": results,
            "missing": missing,
            "replay_missing": replay_missing,
            "note": (
                "adapter is UNVERIFIED while any target is missing; do not run "
                "nozzle parity until ok is True"
            ),
        }

    #: Targets the decision-level replay path needs, and nothing more. Splitting
    #: this from the full set is what lets replay work in a tree where, say, the
    #: request parser is unavailable: a method must demand only what it uses.
    REPLAY_TARGETS = ("evidence", "fallback_decision", "action_gate")

    def _require(self, *keys: str) -> None:
        """Assert the named delegation targets resolve. No keys means all of them."""
        wanted = keys or tuple(TARGETS)
        missing = []
        for key in wanted:
            try:
                _resolve(key)
            except Exception as exc:  # noqa: BLE001
                missing.append(f"{key} ({type(exc).__name__})")
        if missing:
            raise RuntimeError(
                "nozzle adapter cannot run: missing delegation targets "
                + ", ".join(missing)
                + ". This working copy of the repo is incomplete for Family 1."
            )

    # -- request handling ------------------------------------------------
    def parse_request(self, text: str) -> Tuple[Any, Dict[str, Any]]:
        self._require("parse")
        result = _resolve("parse")(text)
        if isinstance(result, tuple):
            spec = result[0]
            record = result[2] if len(result) >= 3 else result[1]
        else:  # pragma: no cover
            spec, record = result, {}
        return spec, _record_dict(record)

    def load_spec(self, path: Path) -> Any:
        """Load a frozen nozzle spec from disk.

        The construction API is probed rather than assumed: this adapter must
        not encode a second, divergent idea of how a NozzleCaseSpec is built.
        """
        import json

        self._require("spec")
        path = Path(path)
        if path.is_dir():
            found = next(
                (path / n for n in SPEC_FILENAMES if (path / n).exists()), None
            )
            if found is None:
                found = next(
                    (p for n in SPEC_FILENAMES
                     for p in path.rglob(n)), None
                )
            if found is None:
                raise FileNotFoundError(
                    f"nozzle: no spec file under {path}; looked for "
                    + ", ".join(SPEC_FILENAMES)
                )
            path = found

        spec_cls = _resolve("spec")
        data = json.loads(path.read_text())

        # case_spec.json is a WRAPPER written by the Family-1 runner:
        #   {"spec": {...raw spec...}, "llm_interpretation": ..., "llm_call": ...}
        # NozzleCaseSpec.from_dict expects the inner raw dictionary. Unwrap it
        # rather than passing the envelope, and leave the spec itself untouched.
        wrapped = isinstance(data, dict) and isinstance(data.get("spec"), dict)
        raw = data["spec"] if wrapped else data

        from_dict = getattr(spec_cls, "from_dict", None)
        if callable(from_dict):
            return from_dict(raw)
        fields = getattr(spec_cls, "__dataclass_fields__", None)
        if fields:
            return spec_cls(**{k: v for k, v in raw.items() if k in fields})
        for attr in ("load", "from_json", "from_file"):
            fn = getattr(spec_cls, attr, None)
            if callable(fn) and not wrapped:
                return fn(path)
        raise TypeError(
            "nozzle: NozzleCaseSpec exposes no from_dict constructor and is not a "
            "dataclass; wire load_spec explicitly rather than guessing"
        )

    def load_evidence(self, path: Path) -> Dict[str, Any]:
        """Rebuild shared-shape evidence from an archived iteration directory.

        Reads only the documents Family 1 already wrote. No solver, no WSL, no
        CFD. This is what makes decision-level parity possible.
        """
        import json

        path = Path(path)

        def read(key: str) -> Optional[Dict[str, Any]]:
            candidate = path / EVIDENCE_FILES[key]
            if candidate.exists():
                return json.loads(candidate.read_text())
            return None

        validation = read("validation")
        if validation is None:
            raise FileNotFoundError(
                f"nozzle: no {EVIDENCE_FILES['validation']} under {path}; "
                "decision-level replay needs the archived validation document "
                "that src/pipeline/nozzle/feedback_diagnostics.py produced"
            )
        mesh = read("mesh") or {}
        if not mesh:
            steps = read("mesh_steps")
            if steps is not None:
                mesh = {"mesh_steps": steps}
        return self.wrap_evidence(
            validation,
            mesh_report=mesh,
            execution=read("execution") or {},
            case_id=validation.get("case_id") or path.name,
            acceptance=read("acceptance"),
        )

    def check_scope(self, spec: Any) -> ScopeResult:
        self._require("scope")
        r = _resolve("scope")(spec)
        d = r.to_dict()
        return ScopeResult(
            approved=bool(d["approved"]),
            decision=str(d.get("decision", "")),
            reasons=list(d.get("reasons", [])),
            checks=dict(d.get("checks", {})),
            measurements=dict(d.get("measurements", {})),
            clarification_needed=[],
        )

    # -- case lifecycle --------------------------------------------------
    def build_case(self, spec: Any, destination: Path) -> Path:
        raise NotImplementedError(
            "nozzle case construction lives in scripts/run_nozzle_feedback.py "
            "(_mesh_new_case) and src/pipeline/nozzle/feedback.py, neither of "
            "which is present in this working copy. Wire this on the real repo; "
            "do not reimplement the mesh here."
        )

    def run_case(self, case: Path, *, append: bool = False) -> int:
        raise NotImplementedError(
            "nozzle execution lives in scripts/run_nozzle_feedback.py "
            "(_run_solver / _continue_case). Wire on the real repo."
        )

    def collect_evidence(self, case: Path, out: Path) -> Dict[str, Any]:
        raise NotImplementedError(
            "nozzle evidence acquisition lives in scripts/run_nozzle_feedback.py "
            "(_acquire_feedback_evidence). Wire on the real repo."
        )

    @staticmethod
    def wrap_evidence(validation: Dict[str, Any], **kw: Any) -> Dict[str, Any]:
        """Shared-shape evidence from an existing nozzle validation document."""
        return {
            "family": "nozzle",
            "spec": kw.get("spec", {}),
            "mesh": kw.get("mesh_report", {}) or {},
            "solver": kw.get("execution", {}) or {},
            "conservation": {
                k: validation.get(k)
                for k in ("mass_imbalance_percent", "mass_imbalance_trend")
                if k in validation
            },
            "stationarity": validation.get("drift_fraction_last_2ms", {}),
            "quantitative": validation.get("final", {}),
            "provenance": {
                "case_id": kw.get("case_id"),
                "acceptance": kw.get("acceptance"),
                "replayed_from_archive": True,
            },
            "raw_validation": validation,
        }

    # -- conversions to the family's own contracts -----------------------
    def to_problem_spec(self, spec: Any) -> Any:
        """NozzleCaseSpec -> contracts.problem_spec.CFDProblemSpec.

        A thin, deterministic field mapping. Only fields the spec actually
        carries are used; a geometry field the spec does not define is REPORTED,
        never filled in with a plausible number.
        """
        from src.contracts.problem_spec import (
            CFDProblemSpec,
            NozzleFamily,
            NozzleGeometry,
            OperatingConditions,
        )

        def pick(names) -> Any:
            for name in names:
                value = getattr(spec, name, None)
                if value is not None:
                    return value
            return None

        geometry_kw = {k: pick(v) for k, v in GEOMETRY_MAP.items()}
        missing = sorted(k for k, v in geometry_kw.items() if v is None)
        if missing:
            raise NotImplementedError(
                "nozzle: NozzleCaseSpec carries no value for "
                + ", ".join(missing)
                + ". These are required by contracts.problem_spec.NozzleGeometry "
                "and are NOT invented here. The deterministic replay path "
                "(deterministic_proposal / execute_action / validate) does not "
                "need a CFDProblemSpec, so decision-level parity is unaffected; "
                "only the LLM diagnose() path requires this conversion."
            )

        operating_kw = {k: pick(v) for k, v in OPERATING_MAP.items()}
        operating_kw = {k: v for k, v in operating_kw.items() if v is not None}

        return CFDProblemSpec(
            nozzle_family=NozzleFamily.CONICAL,
            geometry=NozzleGeometry(**geometry_kw),
            operating_conditions=OperatingConditions(**operating_kw),
        )

    def to_cfd_evidence(self, evidence: Dict[str, Any]) -> Any:
        """Rebuild the family's theory-blind CFDEvidence packet.

        Delegates to build_evidence_from_validation, which is also what applies
        the theory-blind guard, so a reference target can never reach a
        decision through this adapter.
        """
        self._require(*self.REPLAY_TARGETS)
        return _resolve("evidence")(
            evidence["raw_validation"],
            mesh_report=evidence.get("mesh") or {},
            execution=evidence.get("solver") or {},
            iteration=int(evidence.get("provenance", {}).get("iteration") or 1),
            case_id=evidence.get("provenance", {}).get("case_id"),
        )

    # -- reasoning -------------------------------------------------------
    def diagnose(self, evidence: Dict[str, Any], spec: Any) -> Tuple[Proposal, Dict[str, Any]]:
        """Family 1's real diagnosis API: diagnose(problem, evidence, ...)."""
        self._require("spec", "diagnose", *self.REPLAY_TARGETS)
        problem = self.to_problem_spec(spec)
        cfd_evidence = self.to_cfd_evidence(evidence)
        decision, gate, record = _resolve("diagnose")(problem, cfd_evidence)
        return self._to_proposal(decision, gate), _record_dict(record)

    def deterministic_proposal(self, evidence: Dict[str, Any], spec: Any) -> Proposal:
        """Delegate to Family 1's own deterministic reasoning function.

        The recipe-baseline and no-diagnosis modes therefore preserve the
        existing Family-1 classification exactly, instead of a second
        status-string heuristic invented here.
        """
        self._require(*self.REPLAY_TARGETS)
        decision = _resolve("fallback_decision")(self.to_cfd_evidence(evidence))
        return self._to_proposal(decision, None)

    @staticmethod
    def _to_proposal(decision: Any, gate: Any) -> Proposal:
        """AgentDecision -> shared Proposal, preserving the original payload."""
        raw: Dict[str, Any] = {}
        to_dict = getattr(decision, "to_dict", None)
        if callable(to_dict):
            raw["agent_decision"] = to_dict()
        elif hasattr(decision, "__dataclass_fields__"):
            from dataclasses import asdict

            raw["agent_decision"] = asdict(decision)
        if gate is not None:
            raw["family_action_gate"] = {
                "approved": bool(getattr(gate, "approved", False)),
                "reasons": list(getattr(gate, "reasons", [])),
            }
        return Proposal(
            # .value, not str(enum): str() on a str-Enum member renders
            # "Diagnosis.UNCONVERGED" on some Python versions, which would not
            # compare equal to the family's own vocabulary.
            diagnosis=_enum_value(getattr(decision, "diagnosis", "")),
            action=_enum_value(getattr(decision, "action", "")),
            reasoning_summary=str(getattr(decision, "reasoning_summary", "") or ""),
            confidence=str(getattr(decision, "confidence", "unknown")),
            raw=raw,
        )

    def allowed_actions(self, evidence: Dict[str, Any], spec: Any) -> List[str]:
        return list(self.recipe.allowed_actions)

    def execute_action(self, action: str, spec: Any, evidence: Dict[str, Any],
                       *, proposal: Optional[Proposal] = None,
                       **kw: Any) -> ActionRuling:
        """Delegate to Family 1's own action validator.

        Its real signature is validate_agent_action(evidence, decision), so the
        AgentDecision is reconstructed and handed over intact. This adapter does
        NOT implement a second action validator.
        """
        self._require(*self.REPLAY_TARGETS)
        cfd_evidence = self.to_cfd_evidence(evidence)
        decision = self._as_agent_decision(action, proposal, cfd_evidence)
        gate = _resolve("action_gate")(cfd_evidence, decision)

        approved = bool(getattr(gate, "approved", False))
        resolved = _enum_value(decision.action)

        # CONTINUE_RUN is a correction, not a termination: carrying the SAME spec
        # forward as corrected_spec is what lets the shared loop take another
        # iteration instead of stopping because next_spec is None. No spec field
        # is changed, because continuing a run does not change the case.
        corrected = spec if (approved and resolved == "CONTINUE_RUN") else None

        return ActionRuling(
            approved=approved,
            action=resolved,
            reasons=list(getattr(gate, "reasons", [])),
            resulting_changes=(
                {"continuation": "same spec, integration resumes"}
                if corrected is not None else {}
            ),
            corrected_spec=corrected,
        )

    def _as_agent_decision(self, action: str, proposal: Optional[Proposal],
                           cfd_evidence: Any) -> Any:
        """The AgentDecision to rule on.

        Prefers the ORIGINAL decision preserved in Proposal.raw, so the gate
        sees exactly what the family produced. Falls back to Family 1's own
        deterministic decision, and only rebuilds a minimal decision when the
        caller asked about a different action than the one proposed.
        """
        from src.contracts.agent_decision import AgentAction, AgentDecision

        if proposal is not None:
            payload = (proposal.raw or {}).get("agent_decision")
            if isinstance(payload, dict) and _enum_value(
                payload.get("action", "")
            ) == _enum_value(action):
                return AgentDecision(**_decision_kwargs(payload))

        decision = _resolve("fallback_decision")(cfd_evidence)
        if _enum_value(decision.action) == _enum_value(action):
            return decision

        # A different action was asked about: keep the family's diagnosis and
        # rationale, swap only the action, and let the family's gate rule.
        decision.action = AgentAction(_enum_value(action))
        decision.reasoning_summary = (
            f"[action substituted for evaluation: {_enum_value(action)}] "
            + decision.reasoning_summary
        )
        decision.validate()
        return decision

    # -- authority -------------------------------------------------------
    def validate(self, evidence: Dict[str, Any], spec: Any) -> Dict[str, Any]:
        """Nozzle validation is produced upstream by the family pipeline.

        The adapter does not recompute it, because recomputing it here would be
        a second, divergent implementation of the family's authority.

        It does record the family's OWN deterministic classification of this
        evidence, because maps_to_decision is handed only the validation
        document and Family-1 correction semantics are a function of the
        evidence, not of the status string. decide_once always calls validate()
        before maps_to_decision(), and the cache is keyed on the exact document
        so a stale classification can never be reused.
        """
        v = evidence.get("raw_validation")
        if v is None:
            raise RuntimeError(
                "nozzle evidence carries no raw_validation document; the family "
                "validator runs in src/pipeline/nozzle/feedback_diagnostics.py"
            )
        try:
            decision = _resolve("fallback_decision")(self.to_cfd_evidence(evidence))
            self._family_diagnosis = (id(v), _enum_value(decision.diagnosis))
        except Exception:  # noqa: BLE001 - classification is advisory to mapping
            self._family_diagnosis = None
        return v

    #: (id(validation), Family-1 Diagnosis value) recorded by validate().
    _family_diagnosis: Optional[Tuple[int, str]] = None

    def maps_to_decision(self, validation: Dict[str, Any]) -> Decision:
        """Family-1 semantics, not a status-string rule.

        A validator FAIL whose cause is incomplete convergence is a CORRECTION,
        not a rejection: that is the behaviour Family 1 already had
        (UNCONVERGED -> CONTINUE_RUN) and mapping every FAIL to REJECT would
        destroy it.
        """
        cached = self._family_diagnosis
        if cached is not None and cached[0] == id(validation):
            return _DIAGNOSIS_DECISION.get(cached[1], INCONCLUSIVE)

        # No classification available (validate() was not called on this
        # document): fall back to the status string, and never claim ACCEPT
        # without it.
        status = str(validation.get("status", ""))
        if status.startswith("PASS") and not (validation.get("failed_checks") or []):
            return ACCEPT
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
                    "recipe_registered": self.recipe.is_registered(),
                    "unresolved_criteria": self.recipe.unresolved(),
                    "adapter_self_check": self.self_check(),
                },
                indent=2,
            )
        )


#: Family-1 Diagnosis -> shared Decision. This is the ONLY place the two
#: vocabularies meet, and it is written so that "unconverged" stays a
#: correction.
_DIAGNOSIS_DECISION: Dict[str, str] = {
    "ACCEPTABLE": ACCEPT,
    "UNCONVERGED": CORRECT_AND_RERUN,
    "MESH_RESOLUTION": CORRECT_AND_RERUN,
    "MESH_QUALITY": CORRECT_AND_RERUN,
    "NUMERICAL_FAILURE": REJECT,
    "BOUNDARY_ANOMALY": REJECT,
    "OUTSIDE_VALIDATED_DOMAIN": REJECT,
    "SUSPECT_NUMERICAL_ANOMALY": INCONCLUSIVE,
    "INSUFFICIENT_EVIDENCE": INCONCLUSIVE,
}


def _enum_value(obj: Any) -> str:
    """The enum's .value, never str(enum)."""
    value = getattr(obj, "value", obj)
    return "" if value is None else str(value)


def _decision_kwargs(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Rebuild AgentDecision kwargs from a serialized decision."""
    from src.contracts.agent_decision import (
        AgentAction,
        CompetingHypothesis,
        Diagnosis,
    )

    kw = dict(payload)
    kw["diagnosis"] = Diagnosis(_enum_value(kw.get("diagnosis")))
    kw["action"] = AgentAction(_enum_value(kw.get("action")))
    kw["competing_hypotheses"] = [
        h if isinstance(h, CompetingHypothesis) else CompetingHypothesis(**h)
        for h in (kw.get("competing_hypotheses") or [])
    ]
    from src.contracts.agent_decision import AgentDecision

    return {k: v for k, v in kw.items() if k in AgentDecision.__dataclass_fields__}


def _record_dict(record: Any) -> Dict[str, Any]:
    if record is None:
        return {}
    to_dict = getattr(record, "to_dict", None)
    if callable(to_dict):
        return to_dict()
    return dict(getattr(record, "__dict__", {}) or {})
