#!/usr/bin/env python3
"""Count model calls, proposals and validator rulings in archived agent sessions.

Reads every events.jsonl under the e2e demo tree (excluding re-analysis copies)
and the per-call latency records, and writes data/agent_stats.json.
Usage: python3 scan_agent_sessions.py <demo_dir> <out_json>
"""
import collections
import glob
import json
import re
import statistics
import sys
from pathlib import Path

demo, out = Path(sys.argv[1]), Path(sys.argv[2])
files = sorted(f for f in glob.glob(str(demo / "**/events.jsonl"), recursive=True)
               if "reanalysis_full" not in f)
stage = collections.Counter()
proposals = collections.Counter()
rulings = collections.Counter()
refusals = []
sessions = collections.Counter()
for f in files:
    sessions["nozzle" if "/nozzle" in f.replace("\\", "/") else "step"] += 1
    for line in open(f, encoding="utf-8"):
        if not line.strip():
            continue
        e = json.loads(line)
        m = e.get("message", "")
        if e.get("tag") == "LLM":
            kind = ("interpretation" if m.startswith(("Case interpreted", "Interpreted", "Interpretation"))
                    else "mesh review" if m.startswith("Mesh evidence")
                    else "field observation" if m.startswith("Multimodal")
                    else "diagnosis" if "iagnosis" in m else "other")
            stage[kind] += 1
            if kind == "field observation" and "failed" in m:
                stage["field observation (failed)"] += 1
        elif e.get("tag") == "REPORTER" and e.get("llm_source"):
            stage["summary"] += 1
        elif e.get("tag") == "ACTION VALIDATOR":
            g = re.match(r"(?:Proposed action )?(\w+) (APPROVED|REJECTED)", m)
            if g:
                proposals[g[1]] += 1
                rulings[(g[1], g[2])] += 1
                if g[2] == "REJECTED":
                    refusals.append({"file": str(Path(f).relative_to(demo)), "message": m[:240]})
lat = collections.defaultdict(list)
for f in glob.glob(str(demo / "**/llm_calls.json"), recursive=True):
    try:
        for r in json.load(open(f, encoding="utf-8-sig")):
            if r.get("is_llm") and r.get("latency_s") is not None:
                lat[r["stage"]].append(r["latency_s"])
    except Exception:
        pass
json.dump({
    "sessions": dict(sessions), "n_sessions": len(files),
    "model_calls_by_stage": dict(stage),
    "proposals_by_action": dict(proposals),
    "rulings": {f"{a}|{b}": n for (a, b), n in rulings.items()},
    "refusals": refusals,
    "latency_median_s_by_stage": {k: statistics.median(v) for k, v in lat.items()},
    "source_files": [str(Path(f).relative_to(demo)) for f in files],
}, open(out, "w"), indent=2)
print(open(out).read()[:1500])
