#!/usr/bin/env python3
"""Recompute the final status and the proposal order of each session in data/session_ledger.json.

Reads the archived agent sessions (`demo/` in the session archive on Zenodo, DOI to
be added on release) and, for every ledger entry, sets:

  status             final session status recorded by the archive:
                       nozzle feedback sessions: feedback_summary.json `status`, else the
                         case entry in the campaign's FEEDBACK_CAMPAIGN_SUMMARY.json;
                       other nozzle sessions: case_result.json `status`;
                       step sessions: agent_result.json `status`.
                     (In the feedback campaigns case_result.json describes only the
                     initial 1 ms stage, so it is not used there.)
  validation_status  last deterministic validator status: acceptance.json
                     `deterministic_status` (nozzle) or the last iteration's
                     `validation_status` in provenance.json (step).
  status_source      archive file the status was read from.
  proposals          [diagnosis, action] pairs in chronological order: the initial
                     end-to-end decision (initial_e2e_agent_decision.json) first, then
                     iterations/iteration_NN or iteration_NN in order of NN; a
                     top-level agent_decision.json is used only when no iteration copy
                     of it exists. Decisions are deduplicated by model-call latency.
                     Only decision files in the session's own folder are used (the
                     resumed run keeps all seven iterations in its final folder).
  ledger_id, paper_decision
                     row of the paper's session ledger and its decision
                     (ACCEPT / REJECT / INCONCLUSIVE / not accepted).

All other fields (n_json_calls, by_stage, duplicates_of_earlier_sessions,
*_all_records, ...) are left unchanged.

Usage: python ledger_statuses.py --demo <archive>/demo [--ledger data/session_ledger.json] [--check]
"""
import argparse
import glob
import json
import os
import re
from pathlib import Path

LEDGER = Path(__file__).resolve().parents[1] / "data" / "session_ledger.json"

# rows of the paper's ledger table (Appendix, Table "ledger")
LEDGER_ID = {
    "nozzle_e2e/case_A_reference": "N1",
    "nozzle_e2e/case_B_geometry": "N2",
    "nozzle_e2e/case_C_conditions": "N3",
    "nozzle_feedback/case_A_reference": "N4",
    "nozzle_feedback_v2/case_A_reference": "N5",
    "nozzle_feedback_v2_hotfix/case_A_reference": "N6",
    "nozzle_feedback_final/case_B_geometry": "N7",
    "nozzle_feedback_final/case_C_conditions": "N8",
    "forward_step_2d/live_run_01": "S1",
    "forward_step_2d/case_B_mach20": "S2",
    "forward_step_2d/case_C_mach35": "S3",
    "forward_step_2d/case_E_step010": "S4",
    "forward_step_2d/case_F_step030": "S5",
    "forward_step_2d/case_G_step030_x100": "S6",
    "forward_step_2d/case_H_iterative_short_run": "S7",
    "forward_step_2d/case_I_mesh_sensitivity": "S8",
}
# session status -> decision (paper Sec. 2.2)
DECISION = {
    "ACCEPTED": "ACCEPT",
    "STOPPED_FAIL_SAFELY": "REJECT",
    "STOPPED_ACTION_REFUSED": "INCONCLUSIVE",
}


def load(p):
    return json.load(open(p, encoding="utf-8-sig"))


def final_status(demo, session):
    d = demo / session
    rel = lambda p: str(p.relative_to(demo)).replace("\\", "/")
    if session.startswith("nozzle"):
        fs = d / "feedback_summary.json"
        if fs.exists():
            return load(fs)["status"], rel(fs)
        camp = d.parent / "FEEDBACK_CAMPAIGN_SUMMARY.json"
        if camp.exists():
            for c in load(camp).get("cases", []):
                if c.get("label") == d.name:
                    return c["status"], rel(camp)
        cr = d / "case_result.json"
        return load(cr)["status"], rel(cr)
    ar = d / "agent_result.json"
    return load(ar)["status"], rel(ar)


def validation_status(demo, session):
    d = demo / session
    if session.startswith("nozzle"):
        acc = d / "acceptance.json"
        return load(acc).get("deterministic_status") if acc.exists() else None
    prov = d / "provenance.json"
    its = load(prov).get("iterations", []) if prov.exists() else []
    return its[-1].get("validation_status") if its else None


def proposals(demo, session):
    d = demo / session
    found = []  # (order, latency, diagnosis, action)
    for f in glob.glob(str(d / "**" / "*agent_decision.json"), recursive=True):
        rel = os.path.relpath(f, d).replace("\\", "/")
        if rel.startswith("history/") or "reanalysis" in rel:
            continue
        name = os.path.basename(f)
        if name == "initial_e2e_agent_decision.json":
            order = 0
        elif name == "agent_decision.json":
            m = re.search(r"iteration_(\d+)/agent_decision\.json$", rel)
            order = int(m[1]) if m else None  # top-level copy
        else:
            continue
        rec = load(f)
        dec = rec.get("decision", rec)
        lat = round((rec.get("llm_call") or {}).get("latency_s") or -1, 3)
        found.append((order, lat, dec.get("diagnosis"), dec.get("action")))
    iters = {lat for order, lat, *_ in found if order is not None}
    out, seen = [], set()
    for order, lat, diag, act in sorted(found, key=lambda x: 10**6 if x[0] is None else x[0]):
        if order is None and lat in iters:
            continue  # top-level copy of an iteration decision
        if lat in seen:
            continue
        seen.add(lat)
        out.append([diag, act])
    return out


def paper_decision(session, status):
    if "/history/" in session:
        return "not terminal (run resumed in a later session)"
    if status.startswith("UNEXECUTED_ACTION") or status == "ERROR":
        return "not accepted"
    return DECISION.get(status, "not accepted")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--demo", required=True, type=Path, help="archive demo/ directory")
    ap.add_argument("--ledger", type=Path, default=LEDGER)
    ap.add_argument("--check", action="store_true", help="report differences only; do not write")
    a = ap.parse_args()
    ledger = json.load(open(a.ledger, encoding="utf-8"))
    changed = False
    for e in ledger:
        s = e["session"]
        status, src = final_status(a.demo, s)
        new = {
            "status": status,
            "status_source": src,
            "validation_status": validation_status(a.demo, s),
            "proposals": proposals(a.demo, s),
            "ledger_id": LEDGER_ID.get(s, LEDGER_ID.get(s.split("/history/")[0], "") + " (earlier session)"),
            "paper_decision": paper_decision(s, status),
        }
        for k, v in new.items():
            if e.get(k) != v:
                print(f"{s}: {k}: {e.get(k)!r} -> {v!r}")
                e[k] = v
                changed = True
    if a.check:
        raise SystemExit(1 if changed else 0)
    if changed:
        with open(a.ledger, "w", encoding="utf-8") as fh:
            json.dump(ledger, fh, indent=1)
    print("text calls (additive):", sum(e["n_json_calls"] for e in ledger))


if __name__ == "__main__":
    main()
