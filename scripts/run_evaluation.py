#!/usr/bin/env python3
"""Legacy ablation harness over the registered cases. Never invents a run.

This is NOT the paper's controller comparison. The comparison reported in the
CFD Forge paper (arms A fixed rule, B CFD Forge, B' gates off, C model-only) is
produced by paper/cfd_forge/scripts/controller_comparison.py; its archived run
is evidence/controller_comparison/20261001T213031Z/. No number in the paper
comes from this script. See evaluation/README.md.

    python scripts/run_evaluation.py --arm full_agent --mode replay
    python scripts/run_evaluation.py --summarise

Records land in `evaluation/records/<arm>.jsonl`. With no records, the summary
prints NOT_RUN for every metric. A per-run quantity that this harness does not
observe is written as null and listed under "not_measured"; every metric that
depends on it is then reported as NOT_MEASURED rather than computed from a
placeholder.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.agent.pipeline import REPLAY, run_pipeline            # noqa: E402
from src.evaluation.metrics import ARMS, RunRecord, summarise  # noqa: E402

RECORDS = _ROOT / "evaluation" / "records"

NOT_MEASURED = "NOT_MEASURED"

#: Per-run fields that may be unobserved, and the metrics computed from them.
_DEPENDENT_METRICS: Dict[str, tuple] = {
    "iterations": ("first_attempt_success",),
    "actions": ("corrected_success", "actions_per_run"),
    "solver_attempts": ("solver_attempts",),
    "human_interventions": ("human_interventions",),
}


def _cases() -> List[tuple]:
    out = []
    for family_dir in sorted(p for p in (_ROOT / "cases").iterdir() if p.is_dir()):
        for case_dir in sorted(p for p in family_dir.iterdir() if p.is_dir()):
            expected = json.loads(
                (case_dir / "expected_result.json").read_text(encoding="utf-8"))
            out.append((family_dir.name, case_dir.name, expected["expected"]))
    return out


def _record(family: str, case: str, expected: Dict[str, Any], arm: str,
            mode: str) -> Dict[str, Any]:
    started = time.time()
    run = run_pipeline(f"evaluate {family}/{case}", mode=mode,
                       family=family, case=case)
    decision = run.decision.to_dict() if run.decision else {}
    solver_invoked = run.artifacts.get("solver_invoked")
    # iterations: the archived session's iteration count, where the archived
    # record carries one (forward-step sessions); otherwise not observed.
    iterations: Optional[int] = expected.get("iterations")
    # actions executed: neither the replay nor the archived case record
    # reports a count, so it is not measured.
    actions: Optional[int] = None
    # solver launches in THIS run: observed directly from the pipeline.
    solver_attempts: Optional[int] = (int(bool(solver_invoked))
                                      if solver_invoked is not None else None)
    record = {
        "case": f"{family}/{case}", "arm": arm,
        "verdict": decision.get("verdict", "NONE"),
        "ground_truth": expected["verdict"],
        "iterations": iterations, "actions": actions,
        "solver_attempts": solver_attempts,
        # manual interventions are not observable from a replay.
        "human_interventions": None,
        "runtime_seconds": time.time() - started,
        "evidence_complete": bool(run.trace.gates),
    }
    record["not_measured"] = sorted(k for k in _DEPENDENT_METRICS
                                    if record[k] is None)
    return record


def _summarise(lines: List[Dict[str, Any]]) -> Dict[str, Any]:
    records: List[RunRecord] = []
    unmeasured: Dict[str, Set[str]] = {}
    for data in lines:
        missing = set(data.pop("not_measured", []))
        missing |= {k for k in _DEPENDENT_METRICS if data.get(k) is None}
        # The dataclass needs integers; the substituted 0 is never reported,
        # because every metric that reads the field is overwritten below.
        for key in missing:
            data[key] = 0
        unmeasured.setdefault(data["arm"], set()).update(missing)
        records.append(RunRecord(**data))
    summary = summarise(records)
    for arm, missing in unmeasured.items():
        metrics = summary["arms"].get(arm, {}).get("metrics", {})
        for key in missing:
            for metric in _DEPENDENT_METRICS[key]:
                if metric in metrics:
                    metrics[metric] = NOT_MEASURED
    return summary


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--arm", choices=list(ARMS))
    ap.add_argument("--mode", default=REPLAY)
    ap.add_argument("--summarise", action="store_true")
    args = ap.parse_args()

    RECORDS.mkdir(parents=True, exist_ok=True)

    if args.summarise or not args.arm:
        lines: List[Dict[str, Any]] = []
        for path in sorted(RECORDS.glob("*.jsonl")):
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    lines.append(json.loads(line))
        print(json.dumps(_summarise(lines), indent=2))
        return 0

    if args.arm != "full_agent":
        print(f"arm {args.arm!r} is declared but its runner is not implemented; "
              "no record is written and the metric stays NOT_RUN",
              file=sys.stderr)
        return 2

    written = 0
    with (RECORDS / f"{args.arm}.jsonl").open("w", encoding="utf-8") as fh:
        for family, case, expected in _cases():
            fh.write(json.dumps(_record(family, case, expected, args.arm,
                                        args.mode)) + "\n")
            written += 1
    print(f"wrote {written} record(s) for arm {args.arm} in mode {args.mode}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
