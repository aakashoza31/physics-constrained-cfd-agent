#!/usr/bin/env python3
"""Recount model calls, proposals and rulings from every call record in the session archive.

This is the counting method behind data/agent_stats.json and the paper's model-call
statistics (97 calls: 16 interpretation, 8 mesh review, 28 diagnosis, 23 field
observation of which 5 failed, 22 summary; 74 text calls; 28 proposals).

Inputs: the archived agent sessions, `demo/` in the session archive on Zenodo
(DOI to be added on release). Only the nozzle and 2-D forward-step campaigns are
counted; `reanalysis*` copies are skipped.

Method:
  * a run is a session folder with an events.jsonl; resumed attempts kept under
    <run>/history/ belong to the same run;
  * text calls are the records with an `is_llm` field in any JSON file of the run,
    deduplicated per run by (stage, latency rounded to 1 ms);
  * proposals come from agent_decision.json / initial_e2e_agent_decision.json,
    deduplicated per run by the latency of their model call; each proposal's ruling
    is the `approved` flag of the action_validation.json in the same folder
    (initial_e2e_action_validation.json for the initial decision);
  * field observations are the per-iteration visual_observation.json files; a file
    with status `visual_observation_failed` is a failed call.

Usage:
  python recount_agent_calls.py [--demo DEMO_DIR] [--out agent_stats.json] [--quiet]

Without --out the per-run breakdown and totals are printed. With --out the totals
are written in the agent_stats.json layout. The fields `note` and `model` of
data/agent_stats.json, and the words "; no retry" in its `field_observation_failures`,
are written by hand and are not produced here; every other field of that file is
reproduced (checked against the archive: 19 sessions, 16 runs, 11 distinct requests,
stage counts 16/8/28/23 (5 failed)/22, 74/74 text calls, latency medians, 28 proposals
and their rulings).
"""
import argparse
import collections
import glob
import json
import os
import re
import statistics

# stage name in the call records -> stage label used in the paper
STAGE_LABEL = {
    "case_spec_interpretation": "interpretation",
    "forward_step_case_spec_interpretation": "interpretation",
    "mesh_evidence_review": "mesh review",
    "theory_blind_diagnosis": "diagnosis",
    "forward_step_reference_blind_diagnosis": "diagnosis",
    "engineering_summary": "summary",
}
MANUAL_FIELDS = ("note", "model")


def recs(o):
    if isinstance(o, dict):
        if o.get("is_llm") is not None:
            yield o
        for v in o.values():
            yield from recs(v)
    elif isinstance(o, list):
        for v in o:
            yield from recs(v)


def load(f):
    try:
        return json.load(open(f, encoding="utf-8-sig"))
    except Exception:
        return None


def find_runs(demo):
    runs = set()
    for f in glob.glob(os.path.join(demo, "**/events.jsonl"), recursive=True):
        rel = os.path.relpath(os.path.dirname(f), demo).replace("\\", "/")
        if "reanalysis_full" in rel or not ("forward_step_2d" in rel or "nozzle" in rel):
            continue
        runs.add(rel.split("/history/")[0])
    return sorted(runs)


def count_run(demo, run):
    root = os.path.join(demo, run)
    calls, props = {}, {}
    for f in glob.glob(root + "/**/*.json", recursive=True):
        if "reanalysis" in f:
            continue
        d = load(f)
        if d is None:
            continue
        for r in recs(d):
            k = (r.get("stage"), round(r.get("latency_s") or -1, 3))
            calls[k] = (r.get("model"), r.get("is_llm"), r.get("ok"), r.get("attempts"))
        b = os.path.basename(f)
        if b in ("agent_decision.json", "initial_e2e_agent_decision.json"):
            dec = d.get("decision", d)
            k = round(d.get("llm_call", {}).get("latency_s") or -1, 3)
            val = os.path.join(os.path.dirname(f), b.replace("agent_decision", "action_validation"))
            v = load(val) if os.path.exists(val) else None
            props[k] = (dec.get("diagnosis"), dec.get("action"), None if v is None else v.get("approved"))
    # rulings as written to the event stream (step family and e2e stage)
    ev_r = set()
    for f in glob.glob(root + "/**/events.jsonl", recursive=True):
        if "reanalysis" in f:
            continue
        for line in open(f, encoding="utf-8"):
            if not line.strip():
                continue
            e = json.loads(line)
            if e.get("tag") == "ACTION VALIDATOR":
                g = re.match(r"(?:Proposed action )?(\w+) (APPROVED|REJECTED)", e["message"])
                if g:
                    ev_r.add((g[1], g[2], e.get("wall")))
    vis = [load(f) or {} for f in glob.glob(root + "/**/visual_observation.json", recursive=True)
           if "reanalysis" not in f]
    sessions = 1 + len(glob.glob(root + "/history/*/events.jsonl"))
    req = None
    for p in (os.path.join(root, "request.txt"), os.path.join(root, "provenance.json")):
        if os.path.exists(p):
            req = open(p, encoding="utf-8-sig").read() if p.endswith(".txt") else (load(p) or {}).get("request")
            if req:
                break
    return dict(run=run, calls=calls, props=props, ev_rulings=sorted(ev_r, key=lambda x: str(x[2])),
                vis=vis, sessions=sessions, request=" ".join((req or "").split()))


def totals(results):
    stage = collections.Counter()
    lat = collections.defaultdict(list)
    ok = attempts1 = 0
    for r in results:
        for (st, latency), (_model, _is_llm, good, att) in r["calls"].items():
            lab = STAGE_LABEL.get(st, st)
            stage[lab] += 1
            lat[lab].append(latency)
            ok += bool(good)
            attempts1 += bool(good) and att in (None, 1)
    n_text = sum(stage.values())
    vis = [v for r in results for v in r["vis"]]
    failed = sum(v.get("status") == "visual_observation_failed" for v in vis)
    reasons = {str(v.get("reason", ""))[:40] for v in vis if v.get("status") == "visual_observation_failed"}
    stage["field observation"] = len(vis)
    stage["field observation (failed)"] = failed
    proposals = collections.Counter()
    rulings = collections.Counter()
    for r in results:
        for diag, action, approved in r["props"].values():
            proposals[action] += 1
            rulings[f"{action}|{'APPROVED' if approved else 'REJECTED'}"] += 1
    sess = collections.Counter()
    for r in results:
        sess["nozzle" if r["run"].startswith("nozzle") else "step"] += r["sessions"]
    order = ["interpretation", "mesh review", "diagnosis", "field observation",
             "field observation (failed)", "summary"]
    return {
        "n_sessions": sum(sess.values()),
        "n_runs": len(results),
        "n_distinct_requests": len({r["request"] for r in results if r["request"]}),
        "sessions": dict(sorted(sess.items())),
        "model_calls_by_stage": {k: stage[k] for k in order if k in stage},
        "text_calls_first_attempt_success": f"{attempts1}/{n_text}",
        "field_observation_failures": (
            f"{failed}/{len(vis)}, all HTTP 503 UNAVAILABLE from the provider"
            if reasons and all("503 UNAVAILABLE" in x for x in reasons)
            else f"{failed}/{len(vis)}; reasons: {sorted(reasons)}"),
        "latency_median_s_by_stage": {k: round(statistics.median(v), 2) for k, v in lat.items()},
        "proposals_by_action": dict(sorted(proposals.items())),
        "rulings": dict(sorted(rulings.items())),
        "n_text_calls": n_text,
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--demo", default=".", help="archive demo/ directory (default: current directory)")
    ap.add_argument("--out", help="write agent_stats.json-compatible totals to this path")
    ap.add_argument("--quiet", action="store_true", help="do not print the per-run breakdown")
    a = ap.parse_args()
    results = [count_run(a.demo, run) for run in find_runs(a.demo)]
    if not results:
        raise SystemExit(f"no nozzle/forward_step_2d sessions under {a.demo}")
    if not a.quiet:
        for r in results:
            print(r["run"], len(r["calls"]),
                  dict(collections.Counter(k[0] for k in r["calls"])),
                  [(d, act, ok) for d, act, ok in r["props"].values()],
                  [(x, y) for x, y, _ in r["ev_rulings"]], "visual:", len(r["vis"]))
    t = totals(results)
    print(json.dumps(t, indent=2))
    if a.out:
        out = {"note": "Recount from every LLM call record in the archived nozzle and step campaigns "
                       "(scripts/recount_agent_calls.py). The committed file adds a hand-written note and model field."}
        out.update({k: v for k, v in t.items() if k != "n_text_calls"})
        with open(a.out, "w", encoding="utf-8") as fh:
            json.dump(out, fh, indent=2)
            fh.write("\n")
        print("wrote", a.out)


if __name__ == "__main__":
    main()
