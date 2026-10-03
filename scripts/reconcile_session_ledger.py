#!/usr/bin/env python3
"""Make paper/cfd_forge/data/session_ledger.json additive.

The ledger lists one entry per archived session folder. A resumed run keeps its
earlier attempts under <run>/history/pre_resume_*/, and the final folder repeats
some of their call records (copied into its iteration folders). Summing the raw
per-session counts therefore double counts those calls (80 instead of 74).

This script re-reads the call records from the session archive, applies the
paper's counting convention (deduplicate within each run by (stage, latency)),
and assigns each call to the earliest session, by start time, that contains it.
`n_json_calls` and `by_stage` become additive across the ledger; the raw
per-folder counts are kept as `*_all_records`. Field-observation records
(visual_observation.json) are not text calls and are excluded, as before.

Usage: python scripts/reconcile_session_ledger.py <archive.zip> [ledger.json]
"""
import collections
import json
import sys
import zipfile

LEDGER = "paper/cfd_forge/data/session_ledger.json"


def calls_in(obj):
    if isinstance(obj, dict):
        stage = obj.get("stage") or obj.get("purpose")
        if obj.get("latency_s") is not None and stage:
            yield (stage, obj["latency_s"])
        for v in obj.values():
            yield from calls_in(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from calls_in(v)


def main(archive, ledger_path=LEDGER):
    z = zipfile.ZipFile(archive)
    ledger = json.load(open(ledger_path))
    sessions = [r["session"] for r in ledger]

    def owner(name):
        best = None
        for s in sessions:
            if name.startswith(f"demo/{s}/") and (best is None or len(s) > len(best)):
                best = s
        return best

    calls = collections.defaultdict(set)
    for name in z.namelist():
        if not name.endswith(".json") or "visual_observation" in name:
            continue
        s = owner(name)
        if s is None:
            continue
        try:
            data = json.loads(z.read(name))
        except ValueError:
            continue
        calls[s].update(calls_in(data))

    seen = collections.defaultdict(dict)          # run -> {call: first session}
    for r in sorted(ledger, key=lambda r: r["start"]):
        s = r["session"]
        raw = collections.Counter(st for st, _ in calls[s])
        if dict(raw) != r.get("by_stage_all_records", r["by_stage"]):
            raise SystemExit(f"{s}: archive does not reproduce the ledger counts")
        run = s.split("/history/")[0]
        new, dup = collections.Counter(), collections.defaultdict(list)
        for c in sorted(calls[s]):
            if c in seen[run]:
                dup[seen[run][c]].append(c[0])
            else:
                seen[run][c] = s
                new[c[0]] += 1
        r["n_json_calls_all_records"] = sum(raw.values())
        r["by_stage_all_records"] = dict(raw)
        r["n_json_calls"] = sum(new.values())
        r["by_stage"] = dict(new)
        r["duplicates_of_earlier_sessions"] = {
            k: dict(collections.Counter(v)) for k, v in dup.items()}

    json.dump(ledger, open(ledger_path, "w"), indent=1)
    total = sum(r["n_json_calls"] for r in ledger)
    raw_total = sum(r["n_json_calls_all_records"] for r in ledger)
    print(f"text calls: {total} (additive); {raw_total} counting every folder's records")


if __name__ == "__main__":
    main(*sys.argv[1:])
