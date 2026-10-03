#!/usr/bin/env python3
"""Controller comparison on archived evidence: fixed rule vs. CFD Forge vs. LLM-only.

No CFD is run. Every decision point is an archived evidence record from the
nozzle and forward-step agent campaigns (plus the archived cube evidence and
18 planted faults seeded into a healthy step run). Each point is decided by:

  A  fixed rule     parameterized_recipe_baseline: the family recipe maps the
                    deterministic validator's disposition to an action; no LLM.
  B  CFD Forge      full_constrained_agent: the real agent diagnosis call
                    (same prompts, schema and packet as the archived agent)
                    proposes an action; the deterministic gates decide.
     B-off          the same LLM proposal with the gates switched off
                    (gates_off): the LLM's proposed action is taken as the
                    verdict. Free: no extra call.
  C  LLM only       the model receives the same evidence packet with every
                    deterministic check outcome removed and returns its own
                    acceptance verdict; no validator is consulted.

All validation uses the current, frozen validators of the repository, so the
arms face identical checks. Ground truth is the contract decision implied by
that validation, except two archived points that carry known diagnostic
defects (a false-positive fatal-error flag; a restart-seam closure error),
whose truth comes from the corrected analysis. These are scored separately.

Usage (repository root, environment with the repo requirements, google-genai
and a key):
    $env:GEMINI_API_KEY="..."; $env:GEMINI_MODEL="gemini-3.5-flash-lite"
    python paper/cfd_forge/scripts/controller_comparison.py --dry-run
    python paper/cfd_forge/scripts/controller_comparison.py --repeats 5 --fault-repeats 3
"""
from __future__ import annotations

import argparse
import collections
import copy
import hashlib
import json
import os
import sys
import time
import traceback
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))
os.chdir(REPO)  # policy files are resolved relative to the repo root

from pydantic import BaseModel  # noqa: E402

from src.families.base import ACCEPT, CORRECT_AND_RERUN, INCONCLUSIVE, REJECT, Proposal  # noqa: E402
from src.orchestrator.loop import decide_once  # noqa: E402

DEFAULT_DEMO = REPO.parent / "physics-constrained-cfd-agent-e2e" / "demo"
OUT_ROOT = REPO / "evidence" / "controller_comparison"
NOT_ACCEPT = "NOT_ACCEPT"   # truth for points where any non-ACCEPT decision is correct

# ----------------------------------------------------------------------
# decision points
# ----------------------------------------------------------------------
STEP_POINTS = [
    ("S1", "forward_step_2d/case_B_mach20/iteration_01", "Mach 2, h=0.2: complete", None),
    ("S2", "forward_step_2d/case_C_mach35/iteration_01", "Mach 3.5, h=0.2: complete", None),
    ("S3", "forward_step_2d/case_E_step010/iteration_01", "Mach 3, h=0.1: complete", None),
    ("S4", "forward_step_2d/case_F_step030/iteration_01", "Mach 3, h=0.3, x=0.6: no measurable front", None),
    ("S5", "forward_step_2d/case_G_step030_x100/iteration_01", "Mach 3, h=0.3, x=1.0: complete", None),
    ("S6", "forward_step_2d/case_H_iterative_short_run/iteration_01", "Mach 3: stopped at t=0.5 of 4", None),
    ("S7", "forward_step_2d/case_H_iterative_short_run/iteration_02", "Mach 3: stopped at t=1 of 4", None),
    ("S8", "forward_step_2d/case_H_iterative_short_run/iteration_05", "Mach 3: stopped at t=2 of 4", None),
    ("S9", "forward_step_2d/case_H_iterative_short_run/iteration_07", "Mach 3: complete after extensions", None),
    ("D1", "forward_step_2d/live_run_01/iteration_01",
     "Mach 2.5: healthy run flagged by a false-positive fatal-error check", ACCEPT),
    ("D2", "forward_step_2d/case_H_iterative_short_run/iteration_04",
     "Mach 3 at t=2: healthy run failed by the pre-fix restart-seam closure", CORRECT_AND_RERUN),
]
NOZZLE_POINTS = [
    ("N1", "nozzle_e2e/case_A_reference", ".", "reference nozzle at 6 ms", None),
    ("N2", "nozzle_e2e/case_B_geometry", ".", "exit radius 37 mm at 6 ms", None),
    ("N3", "nozzle_e2e/case_C_conditions", ".", "p0 = 220 kPa at 6 ms", None),
    ("N4", "nozzle_feedback_v2_hotfix/case_A_reference", "iterations/iteration_01",
     "reference nozzle at 1 ms: not yet stationary", None),
    ("N5", "nozzle_feedback_v2_hotfix/case_A_reference", "iterations/iteration_02",
     "reference nozzle continued to 6 ms", None),
    ("N6", "nozzle_feedback/case_A_reference", "iterations/iteration_02",
     "early continuation with time-accounting and flux-consistency failures", NOT_ACCEPT),
]


#: Nozzle checks whose failure alone means "healthy but not yet settled".
NOZZLE_SETTLING = {"steady_mass_balance", "monitors_stationary", "fields_stationary"}


def truth_from_status(status: str, family: str, failed: Optional[List[str]] = None) -> str:
    s = str(status or "")
    if s.startswith("PASS"):
        return ACCEPT
    if s in ("CURRENT_STATE_HEALTHY_TARGET_NOT_REACHED", "INCOMPLETE"):
        return CORRECT_AND_RERUN
    if family == "nozzle" and failed and set(failed) <= NOZZLE_SETTLING:
        return CORRECT_AND_RERUN
    return REJECT


# ----------------------------------------------------------------------
# token / latency capture for every Gemini call made through google-genai
# ----------------------------------------------------------------------
CALLS: List[Dict[str, Any]] = []
CONTEXT: Dict[str, Any] = {}


def install_call_recorder():
    from google.genai import models as gm

    original = gm.Models.generate_content

    def wrapped(self, *a, **kw):
        t0 = time.time()
        resp = original(self, *a, **kw)
        um = getattr(resp, "usage_metadata", None)
        CALLS.append({
            **CONTEXT, "latency_s": round(time.time() - t0, 3),
            "model": kw.get("model"),
            "prompt_tokens": getattr(um, "prompt_token_count", None) if um else None,
            "output_tokens": getattr(um, "candidates_token_count", None) if um else None,
            "total_tokens": getattr(um, "total_token_count", None) if um else None,
        })
        return resp

    gm.Models.generate_content = wrapped


# ----------------------------------------------------------------------
# arm C: LLM-only acceptance on a packet with every check outcome removed
# ----------------------------------------------------------------------
class Verdict(str, Enum):
    ACCEPT = "ACCEPT"
    NEEDS_MORE_RUNTIME = "NEEDS_MORE_RUNTIME"
    REJECT = "REJECT"
    INCONCLUSIVE = "INCONCLUSIVE"


class LLMOnlyVerdict(BaseModel):
    verdict: Verdict
    evidence_used: List[str]
    reasoning_summary: str
    confidence: str


LLM_ONLY_SYSTEM = """
You are the only reviewer of a completed CFD run. No deterministic validator
will check your judgement: your verdict is final. Using only the measured
evidence supplied, decide whether the result can be accepted for reporting.

Verdicts:
- ACCEPT: the run is complete, numerically healthy, physically admissible and,
  where the family requires it, settled. It may be reported.
- NEEDS_MORE_RUNTIME: the run is healthy but not finished: it has not reached
  the registered target time, or a steady problem has not settled.
- REJECT: the run is numerically or physically invalid.
- INCONCLUSIVE: the evidence cannot settle the question.

Do not invent measurements. Solver completion alone does not make a result
acceptable. Return only the structured response.
""".strip()

BLIND_KEYS = {
    "deterministic_checks", "deterministic_failed_checks", "passes_stationarity",
    "mass_imbalance_trend", "allowed_actions", "allowed_diagnoses",
    "visual_observation", "images_supplied", "policy_path", "previous_iterations",
    "history_instruction", "visual_note", "task",
    "hard_checks_status", "deterministic_status", "final_acceptance", "status",
    "failed_checks", "validation_status", "acceptance",
}

FAMILY_NOTES = {
    "forward_step_2d": ("Transient inviscid Mach-number flow over a forward-facing step. "
                        "The registered target end time is t = 4; an evolving solution "
                        "is expected and stationarity is not required."),
    "nozzle": ("Steady inviscid flow through a converging-diverging nozzle, run as a "
               "transient to a steady state. Acceptance requires a settled, "
               "conservative solution."),
    "cube": ("URANS flow over a surface-mounted cube; the result is to be certified "
             "as a statistically developed flow."),
}


def strip(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: strip(v) for k, v in obj.items() if k not in BLIND_KEYS}
    if isinstance(obj, list):
        return [strip(v) for v in obj]
    return obj


def blind_packet(family: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    return {"family_context": FAMILY_NOTES[family], "evidence": strip(payload)}


def step_payload(spec, diagnostics, validation) -> Dict[str, Any]:
    from src.reasoning.forward_step_diagnosis import build_evidence_payload
    return build_evidence_payload(spec, diagnostics, validation,
                                  iterations_used=1, max_iterations=4)


def nozzle_payload(adapter, spec, ev) -> Dict[str, Any]:
    from src.reasoning.evidence_packet import build_reasoning_packet
    return build_reasoning_packet(adapter.to_problem_spec(spec), adapter.to_cfd_evidence(ev),
                                  policy_path=str(REPO / "configs/cfd_reasoning_policy_v2.yaml"))


def call_llm_only(packet: Dict[str, Any], model: str, dry: bool) -> Dict[str, Any]:
    if dry:
        return {"verdict": "ACCEPT", "evidence_used": [], "reasoning_summary": "dry run",
                "confidence": "n/a", "dry": True}
    from google import genai
    from google.genai import types
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    resp = client.models.generate_content(
        model=model, contents=json.dumps(packet, indent=2, default=str),
        config=types.GenerateContentConfig(system_instruction=LLM_ONLY_SYSTEM,
                                           response_mime_type="application/json",
                                           response_schema=LLMOnlyVerdict, temperature=0))
    return LLMOnlyVerdict.model_validate_json(resp.text).model_dump(mode="json")


VERDICT_TO_DECISION = {"ACCEPT": ACCEPT, "NEEDS_MORE_RUNTIME": CORRECT_AND_RERUN,
                       "REJECT": REJECT, "INCONCLUSIVE": INCONCLUSIVE}


# ----------------------------------------------------------------------
# arms A and B on the shared orchestrator
# ----------------------------------------------------------------------
def arm_a(adapter, spec, ev):
    r = decide_once(adapter, spec, copy.deepcopy(ev), mode="parameterized_recipe_baseline")
    failed = r.validation.get("failed_checks")
    if failed is None and isinstance(r.validation.get("checks"), dict):
        failed = [k for k, v in r.validation["checks"].items() if not v]
    return {"decision": r.decision, "action": r.proposal.action, "approved": r.ruling.approved,
            "status": r.validation.get("status"), "failed": list(failed or [])}


def arm_b(adapter, spec, ev, dry: bool):
    if dry:
        prop = adapter.deterministic_proposal(copy.deepcopy(ev), spec)
        rec = {"dry": True}
    else:
        prop, rec = adapter.diagnose(copy.deepcopy(ev), spec)
    original = adapter.diagnose
    adapter.diagnose = lambda e, s: (prop, rec)
    try:
        on = decide_once(adapter, spec, copy.deepcopy(ev), mode="full_constrained_agent")
        off = decide_once(adapter, spec, copy.deepcopy(ev), mode="gates_off")
    finally:
        adapter.diagnose = original
    return {"diagnosis": prop.diagnosis, "action": prop.action, "confidence": prop.confidence,
            "approved": on.ruling.approved, "refusal": list(on.ruling.reasons)[:2]
            if not on.ruling.approved else [],
            "decision": on.decision, "decision_gates_off": off.decision,
            "reasoning": (prop.reasoning_summary or "")[:400]}


# ----------------------------------------------------------------------
def _portable(path: Path) -> str:
    """Record the archive location without machine-specific prefixes."""
    try:
        return Path(path).resolve().relative_to(REPO.parent).as_posix()
    except ValueError:
        return Path(path).name


def load_points(demo: Path):
    from src.families.forward_step_2d_adapter import ForwardStep2DAdapter
    from src.families.nozzle_adapter import NozzleAdapter
    from src.pipeline.forward_step_2d.spec import ForwardStep2DSpec
    from src.eval import faults as faults_mod

    fs, nz = ForwardStep2DAdapter(), NozzleAdapter()
    pts = []
    for pid, rel, label, override in STEP_POINTS:
        ev = fs.load_evidence(demo / rel)
        ev["raw_validation"] = None          # re-validate with the current validator
        spec = ForwardStep2DSpec.from_dict(ev["spec"])
        pts.append(dict(id=pid, group="defect" if override else "archived", family="forward_step_2d",
                        label=label, source=rel, adapter=fs, spec=spec, ev=ev, override=override))
    for pid, case, it, label, override in NOZZLE_POINTS:
        spec = nz.load_spec(demo / case)
        ev = nz.load_evidence(demo / case / it)
        pts.append(dict(id=pid, group="archived", family="nozzle", label=label,
                        source=f"{case}/{it}", adapter=nz, spec=spec, ev=ev, override=override))
    healthy = pts[0]
    for k, f in enumerate(faults_mod.faults_for("forward_step_2d"), 1):
        ev = f(copy.deepcopy(healthy["ev"]))
        ev["raw_validation"] = None
        pts.append(dict(id=f"F{k:02d}", group="fault", family="forward_step_2d",
                        label=f"planted fault: {f.name}", source=f"{healthy['source']} + {f.name}",
                        adapter=fs, spec=healthy["spec"], ev=ev, override=NOT_ACCEPT))
    return pts


def packet_for(p) -> Dict[str, Any]:
    if p["family"] == "forward_step_2d":
        from src.pipeline.forward_step_2d.validate import validate as fs_validate
        d = p["ev"]["raw_diagnostics"]
        return step_payload(p["spec"], d, fs_validate(d))
    return nozzle_payload(p["adapter"], p["spec"], p["ev"])


def score(decision: str, truth: str) -> Dict[str, bool]:
    acc = decision == ACCEPT
    if truth == NOT_ACCEPT:
        match = not acc
    else:
        match = decision == truth
    return {"match": match, "false_accept": acc and truth != ACCEPT,
            "missed_accept": truth == ACCEPT and not acc,
            "unneeded_rerun": truth == ACCEPT and decision == CORRECT_AND_RERUN}


def run_cube(repeats: int, model: str, dry: bool, out_rows: List[Dict[str, Any]]):
    """Cube: arm A = registered gate; B = archived diagnosis prompt; C = blind verdict."""
    import importlib.util
    path = REPO / "paper/cfd_forge/scripts/cube_llm_diagnosis.py"
    spec = importlib.util.spec_from_file_location("cube_diag", path)
    cd = importlib.util.module_from_spec(spec)
    sys.modules["cube_diag"] = cd
    spec.loader.exec_module(cd)
    samples = json.loads(cd.FORCES.read_text())["samples"]
    gate = cd.load_gate().assess(samples).to_dict()
    packet = cd.build_packet(samples, cd.DEFAULT_LOGS)
    truth = NOT_ACCEPT
    a_dec = ACCEPT if gate["status"] == "STATIONARY" else CORRECT_AND_RERUN
    out_rows.append(dict(point="CUBE", group="archived", family="cube", arm="A_fixed_rule",
                         repeat=0, decision=a_dec, action="CONTINUE_RUN" if a_dec != ACCEPT else "ACCEPT",
                         truth=truth, **score(a_dec, truth)))
    for r in range(1, repeats + 1):
        for arm in ("B", "C"):
            CONTEXT.update(point="CUBE", arm=arm, repeat=r)
            try:
                if arm == "B":
                    if dry:
                        dec = {"diagnosis": "STILL_DEVELOPING", "action": "CONTINUE_RUN"}
                    else:
                        from google import genai
                        from google.genai import types
                        client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
                        resp = client.models.generate_content(
                            model=model, contents=json.dumps(packet, indent=2),
                            config=types.GenerateContentConfig(
                                system_instruction=cd.SYSTEM, response_mime_type="application/json",
                                response_schema=cd.CubeDecision, temperature=0))
                        dec = cd.CubeDecision.model_validate_json(resp.text).model_dump(mode="json")
                    act = dec["action"]
                    full = dec if not dry else {"diagnosis": dec["diagnosis"], "evidence_used": [],
                                                "competing_hypotheses": [], "reasoning_summary": "",
                                                "action": act, "confidence": "n/a"}
                    ok = cd.validate(cd.CubeDecision.model_validate(full), gate)["approved"]
                    d_on = (CORRECT_AND_RERUN if act == "CONTINUE_RUN" else
                            INCONCLUSIVE if (act != "ACCEPT" or not ok) else ACCEPT)
                    d_off = {"ACCEPT": ACCEPT, "CONTINUE_RUN": CORRECT_AND_RERUN}.get(act, INCONCLUSIVE)
                    out_rows.append(dict(point="CUBE", group="archived", family="cube",
                                         arm="B_cfd_forge", repeat=r, decision=d_on,
                                         decision_gates_off=d_off, action=act, approved=ok,
                                         diagnosis=dec.get("diagnosis"), truth=truth,
                                         **score(d_on, truth),
                                         **{"gates_off_" + k: v for k, v in score(d_off, truth).items()}))
                else:
                    v = call_llm_only({"family_context": FAMILY_NOTES["cube"], "evidence": packet},
                                      model, dry)
                    d = VERDICT_TO_DECISION[v["verdict"]]
                    out_rows.append(dict(point="CUBE", group="archived", family="cube",
                                         arm="C_llm_only", repeat=r, decision=d, verdict=v["verdict"],
                                         truth=truth, reasoning=v.get("reasoning_summary", "")[:400],
                                         **score(d, truth)))
            except Exception as exc:  # noqa: BLE001
                out_rows.append(dict(point="CUBE", arm=arm, repeat=r, error=repr(exc)[:300]))


def summarise(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    ok_rows = [r for r in rows if "error" not in r]
    for group in ("archived", "defect", "fault"):
        g = [r for r in ok_rows if r.get("group") == group]
        if not g:
            continue
        out[group] = {}
        for arm in ("A_fixed_rule", "B_cfd_forge", "B_gates_off", "C_llm_only"):
            if arm == "B_gates_off":
                a = [r for r in g if r["arm"] == "B_cfd_forge"]
                key = "gates_off_"
            else:
                a = [r for r in g if r["arm"] == arm]
                key = ""
            if not a:
                continue
            n = len(a)
            out[group][arm] = {
                "n_decisions": n,
                "points": len({r["point"] for r in a}),
                "correct": sum(r[key + "match"] for r in a),
                "false_accept": sum(r[key + "false_accept"] for r in a),
                "missed_accept": sum(r[key + "missed_accept"] for r in a),
                "unneeded_rerun": sum(r[key + "unneeded_rerun"] for r in a),
            }
            if arm == "B_cfd_forge":
                out[group][arm]["proposals_refused"] = sum(1 for r in a if r.get("approved") is False)
        # consistency across repeats for the LLM arms
        for arm, field in (("B_cfd_forge", "action"), ("C_llm_only", "decision")):
            byp = collections.defaultdict(list)
            for r in g:
                if r["arm"] == arm:
                    byp[r["point"]].append(r[field])
            if byp:
                unanimous = sum(1 for v in byp.values() if len(set(v)) == 1)
                out[group][arm]["points_unanimous_across_repeats"] = f"{unanimous}/{len(byp)}"
    errors = [r for r in rows if "error" in r]
    out["errors"] = len(errors)
    toks = [c for c in CALLS if c.get("total_tokens")]
    out["llm_calls_recorded"] = len(CALLS)
    if CALLS:
        lat = sorted(c["latency_s"] for c in CALLS)
        out["latency_median_s"] = lat[len(lat) // 2]
    if toks:
        out["tokens_total"] = sum(c["total_tokens"] for c in toks)
        out["tokens_mean_per_call"] = round(out["tokens_total"] / len(toks))
    return out


def markdown(summary: Dict[str, Any]) -> str:
    lines = []
    for group in ("archived", "defect", "fault"):
        if group not in summary:
            continue
        lines.append(f"\n### {group}\n")
        lines.append("| arm | points | decisions | correct | false accept | missed accept | unneeded rerun | refused | unanimous |")
        lines.append("|---|---|---|---|---|---|---|---|---|")
        for arm, s in summary[group].items():
            lines.append(f"| {arm} | {s['points']} | {s['n_decisions']} | {s['correct']} | {s['false_accept']} | "
                         f"{s['missed_accept']} | {s['unneeded_rerun']} | {s.get('proposals_refused', '')} | "
                         f"{s.get('points_unanimous_across_repeats', '')} |")
    ok, bad = summary.get('llm_calls_recorded'), summary.get('errors')
    lines.append(f"\nLLM calls attempted: {(ok or 0) + (bad or 0)}, succeeded (recorded): {ok}, failed: {bad}, "
                 f"median latency {summary.get('latency_median_s')} s, tokens {summary.get('tokens_total')}")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--demo-root", type=Path, default=DEFAULT_DEMO)
    ap.add_argument("--repeats", type=int, default=5)
    ap.add_argument("--fault-repeats", type=int, default=3)
    ap.add_argument("--dry-run", action="store_true",
                    help="no API calls: arm B uses the recipe proposal, arm C a stub ACCEPT")
    ap.add_argument("--only", default="", help="comma-separated point ids, e.g. S1,N4,CUBE")
    args = ap.parse_args()

    model = os.environ.get("GEMINI_MODEL", "gemini-3.5-flash-lite")
    if not args.dry_run:
        if not os.environ.get("GEMINI_API_KEY"):
            sys.exit("GEMINI_API_KEY is not set (or use --dry-run).")
        install_call_recorder()

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + ("_dry" if args.dry_run else "")
    out = OUT_ROOT / stamp
    out.mkdir(parents=True, exist_ok=True)
    only = {s.strip() for s in args.only.split(",") if s.strip()}

    rows: List[Dict[str, Any]] = []
    points = load_points(args.demo_root)
    print(f"{len(points)} decision points loaded (+ cube); model {model}; dry={args.dry_run}")
    for p in points:
        if only and p["id"] not in only:
            continue
        a = arm_a(p["adapter"], p["spec"], p["ev"])
        truth = p["override"] or truth_from_status(a["status"], p["family"], a["failed"])
        base = dict(point=p["id"], group=p["group"], family=p["family"], label=p["label"],
                    source=p["source"], truth=truth, validator_status=a["status"])
        rows.append({**base, "arm": "A_fixed_rule", "repeat": 0, "decision": a["decision"],
                     "action": a["action"], **score(a["decision"], truth)})
        reps = args.fault_repeats if p["group"] == "fault" else args.repeats
        blind = blind_packet(p["family"], packet_for(p))
        for r in range(1, reps + 1):
            CONTEXT.update(point=p["id"], arm="B", repeat=r)
            try:
                b = arm_b(p["adapter"], p["spec"], p["ev"], args.dry_run)
                rows.append({**base, "arm": "B_cfd_forge", "repeat": r, **b,
                             **score(b["decision"], truth),
                             **{"gates_off_" + k: v for k, v in score(b["decision_gates_off"], truth).items()}})
            except Exception as exc:  # noqa: BLE001
                rows.append({**base, "arm": "B_cfd_forge", "repeat": r, "error": repr(exc)[:300],
                             "trace": traceback.format_exc()[-800:]})
            CONTEXT.update(point=p["id"], arm="C", repeat=r)
            try:
                v = call_llm_only(blind, model, args.dry_run)
                d = VERDICT_TO_DECISION[v["verdict"]]
                rows.append({**base, "arm": "C_llm_only", "repeat": r, "decision": d,
                             "verdict": v["verdict"], "reasoning": v.get("reasoning_summary", "")[:400],
                             **score(d, truth)})
            except Exception as exc:  # noqa: BLE001
                rows.append({**base, "arm": "C_llm_only", "repeat": r, "error": repr(exc)[:300]})
        done = [x for x in rows if x["point"] == p["id"] and "error" not in x]
        print(f"  {p['id']:4s} truth={truth:18s} A={a['decision']:18s} "
              f"B={[x['action'] for x in done if x['arm'] == 'B_cfd_forge']} "
              f"C={[x['verdict'] for x in done if x['arm'] == 'C_llm_only']}", flush=True)
    if not only or "CUBE" in only:
        run_cube(args.repeats, model, args.dry_run, rows)
        print("  CUBE done")

    summary = summarise(rows)
    meta = {"model": model, "repeats": args.repeats, "fault_repeats": args.fault_repeats,
            "dry_run": args.dry_run, "demo_root": _portable(args.demo_root), "utc": stamp,
            "llm_only_system_sha256": hashlib.sha256(LLM_ONLY_SYSTEM.encode()).hexdigest(),
            "blind_keys_removed": sorted(BLIND_KEYS)}
    (out / "records.jsonl").write_text("\n".join(json.dumps(r, default=str) for r in rows))
    (out / "calls.jsonl").write_text("\n".join(json.dumps(c) for c in CALLS))
    (out / "summary.json").write_text(json.dumps({"meta": meta, "summary": summary}, indent=2))
    md = markdown(summary)
    (out / "summary.md").write_text(md)
    print(md)
    print(f"\nrecords written to {out}")


if __name__ == "__main__":
    main()
