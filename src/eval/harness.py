#!/usr/bin/env python3
"""Evaluation harness: every paper experiment as a mode on the one architecture.

Nothing here reimplements the system. Each experiment calls
src.orchestrator.loop.decide_once with a different mode, or the router with a
different corpus, and reads the shared ledger. That is what makes the ablations
ablations of THIS system rather than of a parallel one.

All experiments here are evidence-level and run without CFD.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence

from src.families import registry
from src.families.base import ACCEPT, INCONCLUSIVE, REJECT
from src.orchestrator import modes as modes_mod
from src.orchestrator.ledger import Ledger
from src.orchestrator.loop import decide_once
from src.router import route as route_mod


@dataclass
class Trial:
    label: str
    mode: str
    decision: str
    expected: Optional[str] = None
    ruling_approved: Optional[bool] = None
    reasons: List[str] = field(default_factory=list)
    detail: Dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> Optional[bool]:
        return None if self.expected is None else self.decision == self.expected

    def to_dict(self) -> Dict[str, Any]:
        return {
            "label": self.label, "mode": self.mode, "decision": self.decision,
            "expected": self.expected, "ok": self.ok,
            "ruling_approved": self.ruling_approved,
            "reasons": self.reasons[:4], "detail": self.detail,
        }


@dataclass
class Report:
    experiment: str
    trials: List[Trial] = field(default_factory=list)
    summary: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "experiment": self.experiment,
            "n": len(self.trials),
            "summary": self.summary,
            "trials": [t.to_dict() for t in self.trials],
        }


# ----------------------------------------------------------------------
def run_modes(
    adapter: Any,
    spec: Any,
    evidence: Dict[str, Any],
    *,
    which: Sequence[str] = modes_mod.MODES,
    ledger: Optional[Ledger] = None,
    proposer: Optional[Callable[[Dict[str, Any]], Any]] = None,
) -> Report:
    """The same evidence through every mode. No CFD.

    ``proposer`` stands in for the LLM so the modes that consult it can be
    exercised without an API key. It is a TEST/OFFLINE seam: a real experiment
    leaves it None so the genuine model is called.
    """
    report = Report("mode_comparison")
    original = adapter.diagnose
    if proposer is not None:
        adapter.diagnose = lambda ev, sp: (proposer(ev), {"stub": True})  # type: ignore[assignment]
    try:
        report = _run_modes_inner(adapter, spec, evidence, which, ledger)
    finally:
        adapter.diagnose = original  # type: ignore[assignment]
    return report


def _run_modes_inner(adapter, spec, evidence, which, ledger) -> Report:
    report = Report("mode_comparison")
    for name in which:
        led = ledger or Ledger(mode=name)
        step = decide_once(adapter, spec, evidence, mode=name, ledger=led)
        report.trials.append(
            Trial(
                label=f"{adapter.name}:{name}", mode=name, decision=step.decision,
                ruling_approved=step.ruling.approved, reasons=list(step.reasons),
                detail={"validation_status": step.validation.get("status"),
                        "proposed_action": step.proposal.action},
            )
        )
    report.summary = {t.mode: t.decision for t in report.trials}
    return report


def fault_injection(
    adapter: Any,
    spec: Any,
    healthy_evidence: Dict[str, Any],
    faults: Sequence[Any],
    *,
    mode: str = modes_mod.RECIPE_BASELINE,
) -> Report:
    """Seed each fault, decide, and score. No LLM and no CFD by default.

    RECIPE_BASELINE is the default so the confusion matrix measures the
    DETERMINISTIC gates rather than the model's mood.
    """
    report = Report("fault_injection")
    baseline = decide_once(adapter, spec, healthy_evidence, mode=mode)
    report.summary["healthy_control_decision"] = baseline.decision

    caught = missed = 0
    for fault in faults:
        step = decide_once(adapter, spec, fault(healthy_evidence), mode=mode)
        failed = list(step.validation.get("failed_checks") or [])
        named = (not fault.expected_check) or (fault.expected_check in failed)
        refused = step.decision != ACCEPT
        ok = refused and named
        caught += int(ok)
        missed += int(not ok)
        report.trials.append(
            Trial(
                label=fault.name, mode=mode, decision=step.decision,
                expected=fault.expected_decision,
                ruling_approved=step.ruling.approved,
                reasons=failed[:6],
                detail={
                    "expected_check": fault.expected_check,
                    "expected_check_failed": named,
                    "refused": refused,
                    "scored_ok": ok,
                },
            )
        )
    report.summary.update(
        {
            "n_faults": len(faults), "caught": caught, "missed": missed,
            "catch_rate": (caught / len(faults)) if faults else None,
            "false_accepts": sum(1 for t in report.trials if t.decision == ACCEPT),
            "scoring": (
                "a fault is CAUGHT when the decision is not ACCEPT and the "
                "expected deterministic check is among failed_checks"
            ),
        }
    )
    return report


def gates_off_comparison(
    adapter: Any,
    spec: Any,
    healthy_evidence: Dict[str, Any],
    faults: Sequence[Any],
    *,
    llm_proposal: Optional[Callable[[Dict[str, Any]], Any]] = None,
) -> Report:
    """The headline experiment: what the gates catch that an unchecked verdict does not.

    With gates authoritative, each seeded fault must be refused. With
    gates_off, the decision is taken from the proposal instead, and any ACCEPT
    is a false accept the gates prevented. ``llm_proposal`` may supply a stand-in
    proposer so the comparison runs without an API key; when it is None the
    family's own recipe proposal is used for both arms, which isolates the
    effect of the GATES rather than of the model.
    """
    report = Report("gates_off_vs_gates_on")
    original = adapter.diagnose
    if llm_proposal is not None:
        adapter.diagnose = lambda ev, sp: (llm_proposal(ev), {"stub": True})  # type: ignore[assignment]
    else:
        adapter.diagnose = lambda ev, sp: (  # type: ignore[assignment]
            adapter.deterministic_proposal(ev, sp), {"stub": "recipe_proposal"}
        )
    try:
        for fault in faults:
            ev = fault(healthy_evidence)
            on = decide_once(adapter, spec, ev, mode=modes_mod.FULL)
            off = decide_once(adapter, spec, ev, mode=modes_mod.GATES_OFF)
            report.trials.append(
                Trial(
                    label=fault.name, mode="paired", decision=off.decision,
                    expected=fault.expected_decision,
                    detail={
                        "gates_on_decision": on.decision,
                        "gates_off_decision": off.decision,
                        "gates_prevented_false_accept": (
                            off.decision == ACCEPT and on.decision != ACCEPT
                        ),
                        "ruling_was_computed_in_gates_off": True,
                    },
                )
            )
    finally:
        adapter.diagnose = original  # type: ignore[assignment]

    prevented = sum(
        1 for t in report.trials if t.detail["gates_prevented_false_accept"]
    )
    report.summary = {
        "n_faults": len(faults),
        "gates_off_false_accepts": sum(
            1 for t in report.trials if t.detail["gates_off_decision"] == ACCEPT
        ),
        "gates_on_false_accepts": sum(
            1 for t in report.trials if t.detail["gates_on_decision"] == ACCEPT
        ),
        "false_accepts_prevented_by_gates": prevented,
    }
    return report


def negative_routing(
    corpus: Sequence[Dict[str, str]],
    *,
    propose: Optional[Callable[[str, List[Dict[str, str]]], Optional[str]]] = None,
) -> Report:
    """Route a corpus of in-scope and out-of-scope requests."""
    registry.install_standing_register()
    report = Report("negative_routing")
    for item in corpus:
        result = route_mod.route(item["text"], propose=propose)
        decision = result.family if result.approved else result.decision
        report.trials.append(
            Trial(
                label=item.get("label", item["text"][:40]),
                mode="router", decision=str(decision),
                expected=item.get("expected"),
                reasons=list(result.reasons),
                detail={"keyword_support": list(result.keyword_support)},
            )
        )
    scored = [t for t in report.trials if t.expected is not None]
    report.summary = {
        "n": len(report.trials),
        "scored": len(scored),
        "correct": sum(1 for t in scored if t.ok),
        "incorrect": [t.label for t in scored if not t.ok],
    }
    return report


#: Out-of-scope and adversarial near-miss requests. No CFD, no LLM needed.
NEGATIVE_ROUTING_CORPUS: List[Dict[str, str]] = [
    {"label": "in_scope_nozzle", "expected": "nozzle",
     "text": "Simulate a converging-diverging nozzle with a 0.02 m throat radius."},
    {"label": "in_scope_forward_step", "expected": "forward_step_2d",
     "text": "Run the 2D forward-facing step at Mach 3 and report the shock structure."},
    {"label": "oos_les_duct", "expected": f"{REJECT} / NO_REGISTERED_FAMILY",
     "text": "Perform a large-eddy simulation of a square duct at Re_tau 300."},
    {"label": "oos_multiphase", "expected": f"{REJECT} / NO_REGISTERED_FAMILY",
     "text": "Model cavitating two-phase flow through a marine propeller."},
    {"label": "oos_combustion", "expected": f"{REJECT} / NO_REGISTERED_FAMILY",
     "text": "Simulate a premixed methane-air burner with detailed chemistry."},
    {"label": "oos_conjugate_ht", "expected": f"{REJECT} / NO_REGISTERED_FAMILY",
     "text": "Conjugate heat transfer in a gas-turbine blade with internal cooling."},
    {"label": "near_miss_viscous_nozzle", "expected": "nozzle",
     "text": "Viscous nozzle flow with a resolved boundary layer and heat flux at the wall.",
     "note": "router may route to nozzle; the nozzle scope gate must then veto the viscous request"},
    {"label": "oos_free_surface", "expected": f"{REJECT} / NO_REGISTERED_FAMILY",
     "text": "Dam-break free-surface flow using VOF."},
    {"label": "oos_rotating_machinery", "expected": f"{REJECT} / NO_REGISTERED_FAMILY",
     "text": "Unsteady sliding-mesh simulation of a centrifugal pump impeller."},
    {"label": "ambiguous_step_no_direction", "expected": f"{REJECT} / NO_REGISTERED_FAMILY",
     "text": "Run a turbulent step flow and give me the reattachment length.",
     "note": "backward_step is CORE-PENDING and forward_step_2d is inviscid; "
             "keyword support spans both, so the router must refuse rather than "
             "collapse onto the executable one"},
    {"label": "pending_airfoil_not_executable",
     "expected": f"{REJECT} / NO_REGISTERED_FAMILY",
     "text": "Give me CL and CD for a NACA0012 at 10 degrees angle of attack.",
     "note": "airfoil is registered and visible but CORE-PENDING, so it is not "
             "executable until its scientific recipe is registered"},
]
