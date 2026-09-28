#!/usr/bin/env python3
"""Run the ablation study, or summarise what has been run. Never invents a run.

    python scripts/run_evaluation.py --arm full_agent --mode replay
    python scripts/run_evaluation.py --summarise

Records land in `evaluation/records/<arm>.jsonl`. With no records, the summary
prints NOT_RUN for every metric -- which is the current, honest state.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import List

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.agent.pipeline import REPLAY, run_pipeline            # noqa: E402
from src.evaluation.metrics import ARMS, RunRecord, summarise  # noqa: E402

RECORDS = _ROOT / "evaluation" / "records"


def _cases() -> List[tuple]:
    out = []
    for family_dir in sorted(p for p in (_ROOT / "cases").iterdir() if p.is_dir()):
        for case_dir in sorted(p for p in family_dir.iterdir() if p.is_dir()):
            expected = json.loads(
                (case_dir / "expected_result.json").read_text(encoding="utf-8"))
            out.append((family_dir.name, case_dir.name,
                        expected["expected"]["verdict"]))
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--arm", choices=list(ARMS))
    ap.add_argument("--mode", default=REPLAY)
    ap.add_argument("--summarise", action="store_true")
    args = ap.parse_args()

    RECORDS.mkdir(parents=True, exist_ok=True)

    if args.summarise or not args.arm:
        records: List[RunRecord] = []
        for path in sorted(RECORDS.glob("*.jsonl")):
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    records.append(RunRecord(**json.loads(line)))
        print(json.dumps(summarise(records), indent=2))
        return 0

    if args.arm != "full_agent":
        print(f"arm {args.arm!r} is declared but its runner is not implemented; "
              "no record is written and the metric stays NOT_RUN",
              file=sys.stderr)
        return 2

    written = 0
    with (RECORDS / f"{args.arm}.jsonl").open("w", encoding="utf-8") as fh:
        for family, case, ground_truth in _cases():
            started = time.time()
            run = run_pipeline(f"evaluate {family}/{case}", mode=args.mode,
                               family=family, case=case)
            decision = run.decision.to_dict() if run.decision else {}
            record = RunRecord(
                case=f"{family}/{case}", arm=args.arm,
                verdict=decision.get("verdict", "NONE"),
                ground_truth=ground_truth,
                iterations=1, actions=0, solver_attempts=0,
                runtime_seconds=time.time() - started,
                evidence_complete=bool(run.trace.gates),
            )
            fh.write(json.dumps(record.__dict__) + "\n")
            written += 1
    print(f"wrote {written} record(s) for arm {args.arm} in mode {args.mode}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
