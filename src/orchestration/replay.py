#!/usr/bin/env python3
"""Replay a registered case from archived evidence. No solver is ever launched.

Replay is not a recording of a verdict. The archived EVIDENCE is re-read and the
deterministic gates are re-evaluated against it, so a replay can disagree with
what was recorded -- and if it does, that is a regression the tests catch. What
replay never does is imply that a solver ran: every artefact it produces carries
`solver_invoked: false`.

For the cube this is literal: the lateral-force gate runs again, on the archived
force history, and re-derives the rejection from 2003 samples.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

REPLAY_VERSION = "replay/1.0.0"

_ROOT = Path(__file__).resolve().parents[2]


class CaseNotFound(FileNotFoundError):
    """The requested case is not in the registered library."""


@dataclass
class ReplayOutcome:
    family: str
    case: str
    reason: str
    stages: List[Tuple[str, str, Dict[str, Any]]] = field(default_factory=list)
    gates: List[Dict[str, Any]] = field(default_factory=list)
    proposals: List[Dict[str, Any]] = field(default_factory=list)
    artifacts: Dict[str, Any] = field(default_factory=dict)


def case_dir(family: str, case: Optional[str], root: Optional[Path] = None) -> Path:
    from src.families import capabilities as caps

    root = Path(root or _ROOT)
    # The case library is keyed by the public CLI name; the register may use a
    # longer canonical key (forward_step vs forward_step_2d). Accept either.
    candidates = [family, caps.resolve(family)]
    candidates += [short for short, canonical in caps.ALIASES.items()
                   if canonical == caps.resolve(family)]
    family_dir = next((root / "cases" / name for name in candidates
                       if (root / "cases" / name).is_dir()), root / "cases" / family)
    if not family_dir.is_dir():
        raise CaseNotFound(
            f"no registered cases for family {family!r}; known families are "
            f"{sorted(p.name for p in (root / 'cases').iterdir() if p.is_dir())}"
        )
    if case is None:
        cases = sorted(p.name for p in family_dir.iterdir() if p.is_dir())
        if len(cases) != 1:
            raise CaseNotFound(
                f"family {family!r} has {len(cases)} registered cases {cases}; "
                "name one with --case"
            )
        case = cases[0]
    path = family_dir / case
    if not path.is_dir():
        raise CaseNotFound(
            f"case {family}/{case} is not registered; available: "
            f"{sorted(p.name for p in family_dir.iterdir() if p.is_dir())}"
        )
    return path


def load_case(family: str, case: Optional[str],
              root: Optional[Path] = None) -> Dict[str, Any]:
    path = case_dir(family, case, root)
    expected = json.loads((path / "expected_result.json").read_text(encoding="utf-8"))
    meta: Dict[str, Any] = {"case_dir": str(path)}
    try:
        import yaml
        meta.update(yaml.safe_load((path / "case.yaml").read_text(encoding="utf-8")))
    except Exception:                       # noqa: BLE001 - yaml is optional here
        meta["case_id"] = expected["case_id"]
        meta["family"] = expected["family"]
    meta["expected"] = expected
    return meta


def _gate(question: str, passed: Optional[bool], measured: Any = None,
          threshold: Any = None, detail: str = "") -> Dict[str, Any]:
    return {"question": question, "passed": passed, "measured": measured,
            "threshold": threshold, "detail": detail}


#: Archived statuses that record a refused or unexecuted needed action. They
#: map to INCONCLUSIVE (paper Sec. 2.2), never to ACCEPT or REJECT.
_INCONCLUSIVE_STATUSES = ("STOPPED_ACTION_REFUSED",)


def _load_cube_llm_records(path: Path) -> List[Dict[str, Any]]:
    """The archived model-diagnosis records for the cube evidence, if present.

    They live under evidence/cube/<case>/llm_diagnosis/*_runNN.json in the
    repository that holds the case directory. Each record is a real model call
    on the archived evidence packet; nothing here is synthesised.
    """
    repo = path.parents[2]
    folder = repo / "evidence" / "cube" / path.name / "llm_diagnosis"
    records: List[Dict[str, Any]] = []
    if not folder.is_dir():
        return records
    for item in sorted(folder.glob("*_run[0-9]*.json")):
        try:
            data = json.loads(item.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        decision = data.get("decision") or {}
        validation = data.get("action_validation") or {}
        usage = data.get("usage") or {}
        records.append({
            "record": str(item.relative_to(repo)),
            "model": data.get("model"),
            "source": data.get("source"),
            "repeat": data.get("repeat"),
            "diagnosis": decision.get("diagnosis"),
            "reasoning_summary": decision.get("reasoning_summary", ""),
            "action": decision.get("action"),
            "approved": validation.get("approved"),
            "executed": validation.get("executed"),
            "validator_reason": validation.get("reason", ""),
            "latency_s": data.get("latency_s"),
            "total_tokens": usage.get("total_token_count"),
        })
    return records


def _cube_gates(meta: Dict[str, Any], path: Path) -> Tuple[List[Dict[str, Any]],
                                                           List[Dict[str, Any]],
                                                           Dict[str, Any], str]:
    """Re-run the stationarity gate on the archived force history."""
    from src.families.cube.stationarity import assess

    history = json.loads((path / "reference" / "force_history.json").read_text())
    samples = history["samples"]
    result = assess(samples)
    measured = result.measured

    gates = [
        _gate("numerical_health", True,
              measured={"solver_completed": True,
                        "end_time_reached": max(s["t"] for s in samples)},
              threshold="the solver must complete without a fatal error",
              detail=("the archived run completed to its requested end time and "
                      "reported no numerical failure")),
        _gate("convergence", True,
              measured={"streamwise_force_drift_fraction":
                        measured["drift_fraction"]["fx"]},
              threshold="drift over the window <= "
                        f"{result.thresholds['force_drift_fraction_max']} of the "
                        "mean streamwise force",
              detail=("the drag looks converged -- this is exactly why watching "
                      "only the drag would have accepted the run")),
        _gate("stationarity", result.passed,
              measured={"lateral_growth_ratio": measured["lateral_growth_ratio"],
                        "mean_abs_fz_first_half":
                            measured["mean_abs_fz_first_half"],
                        "mean_abs_fz_second_half":
                            measured["mean_abs_fz_second_half"]},
              threshold=f"lateral force growth ratio <= "
                        f"{result.thresholds['lateral_growth_ratio_max']}",
              detail=("a periodic lateral mode is still growing across the "
                      "assessment window, so the flow is not developed")),
        _gate("validation", None,
              measured="not reached",
              threshold="a reference comparison requires a stationary flow first",
              detail=("validation was never attempted: a run that is still "
                      "developing cannot be compared against a reference")),
    ]
    # Archived model calls on the cube evidence (made after the run, which was
    # executed outside the agent loop). The validator's approval is reported as
    # recorded; an approved action was never executed and never decides.
    records = _load_cube_llm_records(path)
    proposals: List[Dict[str, Any]] = []
    for rec in records:
        model = f"{rec.get('source') or 'model'}:{rec.get('model')}"
        proposals.append({
            "activity": "diagnose_evidence",
            "content": (f"{rec.get('diagnosis')}: {rec.get('reasoning_summary')}"
                        if rec.get("reasoning_summary") else rec.get("diagnosis")),
            "model": model,
            "accepted_by_authority": rec.get("approved"),
            "latency_s": rec.get("latency_s"),
            "total_tokens": rec.get("total_tokens"),
            "record": rec.get("record"),
        })
        if rec.get("action"):
            proposals.append({
                "activity": "propose_bounded_action",
                "content": rec["action"],
                "model": model,
                "accepted_by_authority": rec.get("approved"),
                "executed": rec.get("executed"),
                "record": rec.get("record"),
            })
    artifacts = {
        "evidence_root": str(Path(_ROOT) / meta.get("evidence_root", "")),
        "force_history": str(path / "reference" / "force_history.json"),
        "force_samples": len(samples),
        "stationarity": result.to_dict(),
        "solver_invoked": False,
        "llm_diagnosis": (
            {"records": records,
             "note": ("archived model diagnoses of the cube evidence; the "
                      "validator's approval is recorded, no action was "
                      "executed, and the verdict comes from the gates")}
            if records else
            {"records": [],
             "note": "no model call recorded for this case"}),
    }
    mode_path = path / "reference" / "lateral_mode.json"
    mode = json.loads(mode_path.read_text()) if mode_path.exists() else {}
    if mode:
        artifacts["lateral_mode"] = mode
    cycles = mode.get("complete_cycle_amplitude_changes") if mode else None
    reason = (
        "REJECTED on flow development. The streamwise load is settled -- it "
        f"drifts by {measured['drift_fraction']['fx']:.3%} of its mean over the "
        "assessment window -- but the flow carries a growing LATERAL mode"
        + (f" of period {mode['period']:.1f} time units" if mode else "") +
        ". Across the final window the mean |lateral force| over the second "
        "half is "
        f"{measured['lateral_growth_ratio']:.2f} times that over the first half, "
        "against a registered limit of "
        f"{result.thresholds['lateral_growth_ratio_max']}"
        + (", and successive complete-cycle amplitudes changed by "
           + ", ".join(f"{float(c):+.0%}" for c in cycles) if cycles else "") +
        ", so the flow has not reached a statistically steady state. A "
        "convergence test that watched the drag alone would have accepted this "
        "run. The cube was run outside the agent loop and this gate was "
        "registered retrospectively."
    )
    return gates, proposals, artifacts, reason


def _archived_gates(meta: Dict[str, Any]) -> Tuple[List[Dict[str, Any]],
                                                   List[Dict[str, Any]],
                                                   Dict[str, Any], str]:
    """Gates re-derived from an archived deterministic record."""
    expected = meta["expected"]["expected"]
    failed = list(expected.get("failed_checks") or [])
    verdict = expected["verdict"]
    root = Path(_ROOT) / meta.get("evidence_root", "")
    # A refused or unexecuted needed action is INCONCLUSIVE, not a rejection:
    # the validation gate is left unresolved rather than failed.
    inconclusive = (verdict == "INCONCLUSIVE"
                    or expected.get("archived_status") in _INCONCLUSIVE_STATUSES)
    validation_passed: Optional[bool] = (
        True if verdict == "ACCEPT" else (None if inconclusive else False))

    gates = [
        _gate("numerical_health", True,
              measured={"archived_status": expected.get("archived_status")},
              threshold="the solver must complete without a fatal error",
              detail="read from the archived run record"),
        _gate("conservation", not any("mass" in f or "flux" in f for f in failed),
              measured={"failed_checks": failed},
              threshold="the family's registered conservation criterion",
              detail="re-read from the archived validation record"),
        # Convergence/stationarity fails only if a convergence-type check failed;
        # the transient forward-step family registers no stationarity criterion.
        _gate("convergence", verdict == "ACCEPT" or not any(
                  k in f for f in failed
                  for k in ("stationar", "converg", "horizon", "steady")),
              measured={"iterations": expected.get("iterations")},
              threshold="the family's registered convergence criterion"),
        _gate("validation", validation_passed,
              measured={"validation_status": expected.get("validation_status")
                        or expected.get("archived_status"),
                        "failed_checks": failed},
              threshold="every registered validation check must pass",
              detail=_validation_detail(expected)),
    ]
    if expected.get("solver_invoked_in_archive") is False:
        decisive = expected.get("decisive_failure") or {}
        metrics = expected.get("foundation_v14_metrics") or {}
        gates = [
            _gate("mesh_quality", False,
                  measured={"decisive_failure": decisive,
                            "foundation_v14_metrics": metrics,
                            "failed_checks": failed},
                  threshold=(f"{decisive.get('check')} <= "
                             f"{decisive.get('frozen_limit')}"),
                  detail=("the decisive genuine failure is in-plane stretching, "
                          "measured on the correctly selected constant-span "
                          "flow-plane quad. Foundation-v14 skewness PASSES on all "
                          "three levels, and cell orientation and in-plane "
                          "validity are clean once defects in the mesh-conversion "
                          "and diagnostic scripts are corrected -- neither is a "
                          "NASA-grid failure.")),
            _gate("numerical_health", None, measured="CFD_NOT_RUN",
                  threshold="not reachable without a qualified mesh",
                  detail="no solver was launched for this family"),
        ]
        artifacts_extra = {
            "corrected_diagnosis": expected.get("source_of_truth"),
            "decisive_failure": decisive,
            "foundation_v14_metrics": metrics,
        }
    proposals: List[Dict[str, Any]] = []
    if expected.get("llm_diagnosis"):
        proposals.append({
            "activity": "diagnose_evidence",
            "content": expected["llm_diagnosis"],
            "model": "archived diagnosis",
            "accepted_by_authority": bool(expected.get("llm_action_approved")),
        })
    if expected.get("llm_proposed_action"):
        proposals.append({
            "activity": "propose_bounded_action",
            "content": expected["llm_proposed_action"],
            "model": "archived diagnosis",
            "accepted_by_authority": bool(expected.get("llm_action_approved")),
        })
    artifacts = {
        "evidence_root": str(root),
        "evidence_present": root.exists(),
        "archived_record": expected,
        "solver_invoked": False,
    }
    artifacts.update(locals().get("artifacts_extra") or {})
    if expected.get("solver_invoked_in_archive") is False:
        decisive = expected.get("decisive_failure") or {}
        levels = decisive.get("levels") or {}
        worst = ", ".join(
            f"{name} {int(v['max']):,} ({v['cells_over_limit']} cells over limit)"
            for name, v in levels.items())
        reason = (
            "MESH REJECTED, CFD_NOT_RUN. The decisive genuine failure is "
            f"{decisive.get('check')} against a frozen limit of "
            f"{decisive.get('frozen_limit'):,.0f}: {worst}. Foundation-v14 "
            "skewness passes on all three levels, and orientation and in-plane "
            "validity are clean after defects in the mesh-conversion and "
            "diagnostic scripts were corrected, so neither is a NASA-grid "
            "failure. No solver was ever launched.")
    else:
        reason = (
            f"replayed from archived evidence: the run recorded "
            f"{expected.get('archived_status')}"
            + (f" with failed checks {failed}" if failed else "")
            + ". No solver was executed by this replay."
        )
    return gates, proposals, artifacts, reason


def replay_case(family: str, case: Optional[str],
                root: Optional[Path] = None) -> ReplayOutcome:
    meta = load_case(family, case, root)
    path = Path(meta["case_dir"])
    if family == "cube":
        gates, proposals, artifacts, reason = _cube_gates(meta, path)
    else:
        gates, proposals, artifacts, reason = _archived_gates(meta)

    stages = [
        ("case_and_mesh", "OK",
         {"source": "registered case", "case_dir": str(path)}),
        ("execution", "REPLAYED",
         {"solver_invoked": False,
          "note": "archived evidence was read; no solver was launched"}),
        ("evidence_extraction", "OK",
         {"evidence_root": meta.get("evidence_root")}),
        (("llm_diagnosis", "PROPOSED", {"proposals": len(proposals)})
         if proposals else
         ("llm_diagnosis", "SKIPPED",
          {"proposals": 0, "note": "no model call recorded for this case"})),
        ("bounded_correction", "SKIPPED",
         {"reason": "replay does not issue new corrective actions"}),
    ]
    artifacts["replay_version"] = REPLAY_VERSION
    artifacts["case"] = meta
    return ReplayOutcome(family=family, case=meta.get("case_id", case or ""),
                         reason=reason, stages=stages, gates=gates,
                         proposals=proposals, artifacts=artifacts)


def _validation_detail(expected: Dict[str, Any]) -> str:
    """Describe the validation gate without passing model text off as a
    deterministic result: an archived message that is just a status string is
    shown as such; free text is labelled as the model's non-binding summary."""
    base = "archived validator status and failed checks"
    message = (expected.get("message") or "").strip()
    statuses = {str(expected.get("archived_status") or ""),
                str(expected.get("validation_status") or "")}
    if not message or message in statuses or " " not in message:
        return base
    return base + "; archived message (model's non-binding summary): " + message
