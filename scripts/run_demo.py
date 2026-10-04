#!/usr/bin/env python3
"""Run one registered demonstration case.

    python scripts/run_demo.py --family nozzle --case canonical_reference --mode replay
    python scripts/run_demo.py --family forward_step --case mach20_canonical --mode replay
    python scripts/run_demo.py --family cube --case drifting_wake --mode replay
    python scripts/run_demo.py --family nozzle --case canonical_reference --mode live --i-want-to-run-cfd
    python scripts/run_demo.py --list

Replay reads the archived evidence of that case and re-derives the deterministic
decision from it. It never pretends a solver was executed. Live execution needs
OpenFOAM Foundation v14 and an explicit --i-want-to-run-cfd.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.agent.backends import BackendUnavailable                        # noqa: E402
from src.agent.pipeline import DRY_RUN, LIVE, MODES, REPLAY, run_pipeline  # noqa: E402
from src.families import capabilities as caps                              # noqa: E402
from src.reporting import report_builder                                   # noqa: E402


def _list_cases() -> int:
    root = _ROOT / "cases"
    print(f"{'family':16s} {'case':34s} {'status':18s} expected")
    print("-" * 92)
    for family_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        capability = caps.TABLE.get(caps.resolve(family_dir.name))
        status = capability.status if capability else "UNREGISTERED"
        for case_dir in sorted(p for p in family_dir.iterdir() if p.is_dir()):
            expected = json.loads(
                (case_dir / "expected_result.json").read_text(encoding="utf-8"))
            verdict = expected["expected"]["verdict"]
            print(f"{family_dir.name:16s} {case_dir.name:34s} {status:18s} {verdict}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--family", default=None)
    ap.add_argument("--case", default=None)
    ap.add_argument("--mode", default=REPLAY, choices=list(MODES))
    ap.add_argument("--out", default=None)
    ap.add_argument("--list", action="store_true", help="list registered cases")
    ap.add_argument("--i-want-to-run-cfd", action="store_true", dest="allow_cfd")
    ap.add_argument("--agent-backend", default="deterministic",
                    choices=["deterministic", "gemini", "replay"],
                    help=("who interprets and diagnoses. 'deterministic' needs no "
                          "API key and is NOT an LLM run; 'gemini' uses "
                          "GEMINI_API_KEY"))
    ap.add_argument("--no-media", action="store_true")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    if args.list or not args.family:
        return _list_cases()

    prompt = f"run the registered {args.family} case {args.case or '(default)'}"
    try:
        run = run_pipeline(prompt, mode=args.mode, family=args.family,
                           case=args.case, allow_cfd=args.allow_cfd,
                           backend=args.agent_backend)
    except BackendUnavailable as exc:
        print(f"agent backend unavailable: {exc}", file=sys.stderr)
        return 2
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    out = Path(args.out) if args.out else (
        _ROOT / "runs" / f"{stamp}_{run.family or args.family}_{run.case or 'case'}")
    paths = report_builder.build(run, out, make_media=not args.no_media)

    decision = run.decision.to_dict() if run.decision else {}
    expected_path = _ROOT / "cases" / args.family / (args.case or "") / "expected_result.json"
    agreement = None
    if expected_path.exists():
        expected = json.loads(expected_path.read_text(encoding="utf-8"))
        agreement = expected["expected"]["verdict"] == decision.get("verdict")

    if args.json:
        print(json.dumps({"decision": decision, "matches_expected": agreement,
                          "artifacts": paths.to_dict()}, indent=2))
    else:
        print(f"family   : {run.family}   case: {run.case}   mode: {args.mode}")
        print(f"decision : {decision.get('verdict')}")
        print(f"reason   : {decision.get('reason')}")
        print(f"solver   : invoked={run.artifacts.get('solver_invoked', False)}")
        if agreement is not None:
            print(f"expected : {'matches the archived record' if agreement else 'DIVERGES from the archived record'}")
        print(f"report   : {paths.report_md}")
        for name in paths.plots:
            print(f"plot     : {paths.root / 'plots' / name}")
        if paths.video:
            print(f"video    : {paths.root / 'video' / paths.video}")
    if agreement is False:
        return 5
    return {"ACCEPT": 0, "REJECT": 3, "INCONCLUSIVE": 4}.get(
        decision.get("verdict", ""), 1)


if __name__ == "__main__":
    raise SystemExit(main())
