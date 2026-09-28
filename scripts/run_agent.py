#!/usr/bin/env python3
"""The public entry point: an engineering problem in, a decision out.

    python scripts/run_agent.py --prompt "Simulate a supersonic nozzle with
        throat radius 0.01 m" --mode dry-run
    python scripts/run_agent.py --prompt "..." --geometry part.step
    python scripts/run_agent.py --prompt "..." --family nozzle
        --case canonical_reference --mode replay

Modes
  dry-run  interpret, characterise the geometry, check the family contract. Stops
           there. Nothing is meshed, nothing is executed, and the verdict is
           INCONCLUSIVE because nothing was validated.
  replay   re-derive the decision from archived evidence for a registered case.
           Never claims a solver ran.
  live     execute OpenFOAM. Requires --i-want-to-run-cfd and Foundation v14.

STEP/CAD input is classified and then refused: no family in this system declares
STEP support, so a CAD part returns INCONCLUSIVE / UNSUPPORTED without launching
CFD. That refusal is the feature.
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

from src.agent.pipeline import DRY_RUN, LIVE, MODES, REPLAY, run_pipeline  # noqa: E402
from src.reporting import report_builder                                    # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--prompt", required=True, help="the engineering request")
    ap.add_argument("--geometry", default=None,
                    help="optional STEP/CAD part (classified, then refused)")
    ap.add_argument("--family", default=None, help="skip routing and name a family")
    ap.add_argument("--case", default=None, help="registered case id, for replay")
    ap.add_argument("--mode", default=DRY_RUN, choices=list(MODES))
    ap.add_argument("--out", default=None,
                    help="artifact directory (default: runs/<timestamp>_<family>)")
    ap.add_argument("--i-want-to-run-cfd", action="store_true",
                    dest="allow_cfd", help="explicit opt-in for live execution")
    ap.add_argument("--no-media", action="store_true",
                    help="skip plots, contours and video")
    ap.add_argument("--json", action="store_true", help="print the decision as JSON")
    args = ap.parse_args()

    run = run_pipeline(args.prompt, mode=args.mode,
                       geometry=Path(args.geometry) if args.geometry else None,
                       family=args.family, case=args.case,
                       allow_cfd=args.allow_cfd)

    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    out = Path(args.out) if args.out else (
        _ROOT / "runs" / f"{stamp}_{run.family or 'unrouted'}_{run.case or args.mode}")
    paths = report_builder.build(run, out, make_media=not args.no_media)

    decision = run.decision.to_dict() if run.decision else {}
    if args.json:
        print(json.dumps({"decision": decision, "artifacts": paths.to_dict()},
                         indent=2))
    else:
        print(f"decision : {decision.get('verdict')}")
        print(f"reason   : {decision.get('reason')}")
        print(f"family   : {run.family or '(none)'}   case: {run.case or '(none)'}")
        print(f"solver   : invoked={run.artifacts.get('solver_invoked', False)}")
        print(f"report   : {paths.report_md}")
        if paths.plots:
            print(f"plots    : {', '.join(paths.plots)}")
        if paths.video:
            print(f"video    : {paths.video}")
    return {"ACCEPT": 0, "REJECT": 3, "INCONCLUSIVE": 4}.get(
        decision.get("verdict", ""), 1)


if __name__ == "__main__":
    raise SystemExit(main())
