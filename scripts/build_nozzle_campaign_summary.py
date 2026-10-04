#!/usr/bin/env python3
"""Build a machine-independent A/B/C campaign summary from feedback outputs.

clean_case() keeps an explicit allow-list of fields, so runtime paths and the
model/provider labels of the session records are not written to the summary.
The model identities remain in the full session records (Zenodo archive, DOI
to be added on release).
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

CASES = {
    "A": "case_A_reference",
    "B": "case_B_geometry",
    "C": "case_C_conditions",
}


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def clean_case(case: str, label: str, payload: dict[str, Any]) -> dict[str, Any]:
    trace = payload.get("trace") or []
    return {
        "case": case,
        "label": label,
        "status": payload.get("status"),
        "iterations": payload.get("iterations"),
        "actions": [item.get("action") for item in trace],
        "approved_actions": [item.get("approved") for item in trace],
        "deterministic_statuses": [item.get("deterministic_status") for item in trace],
        "failed_checks_by_iteration": [item.get("failed_checks") or [] for item in trace],
        "visual_statuses": [item.get("visual_status") for item in trace],
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()

    cases = []
    missing = []
    for case, label in CASES.items():
        path = args.root / label / "feedback_summary.json"
        if not path.exists():
            missing.append(str(path))
            continue
        cases.append(clean_case(case, label, read_json(path)))

    if missing:
        raise SystemExit("Missing feedback summaries:\n  " + "\n  ".join(missing))

    result = {
        "campaign": "closed_loop_multimodal_nozzle_demo",
        "cases": cases,
        "all_accepted": all(item.get("status") == "ACCEPTED" for item in cases),
        "authority_note": (
            "LLM actions are advisory until approved by deterministic action and "
            "scientific validators. Machine-specific runtime paths and model labels "
            "are intentionally excluded from this summary."
        ),
    }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    return 0 if result["all_accepted"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
