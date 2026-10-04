#!/usr/bin/env python3
"""Publish sanitized evidence from already-completed local A/B/C feedback runs.

This script does not run CFD. It discovers accepted feedback_summary.json files
under demo/, selects the demonstrated A/B/C runs, copies compact sanitized
results and field images into demo/published_campaign/, and intentionally omits
machine paths and LLM provider/model labels.

Where labels are stripped: compact_feedback(), compact_validation() and
sanitize_visual() copy only an explicit allow-list of fields, so the "model",
"source" and "provider" entries of the session records are not published, and
images_examined keeps file names only. The model identities remain in the full
session records (Zenodo archive, DOI to be added on release).
"""
from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path
from typing import Any

CASES = {
    "A": "case_A_reference",
    "B": "case_B_geometry",
    "C": "case_C_conditions",
}


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def discover(repo: Path, label: str, case: str) -> Path:
    candidates: list[tuple[int, float, Path]] = []
    for p in (repo / "demo").glob(f"**/{label}/feedback_summary.json"):
        if "published_campaign" in p.parts:
            continue
        try:
            payload = read_json(p)
        except Exception:
            continue
        if payload.get("status") != "ACCEPTED":
            continue
        iterations = int(payload.get("iterations") or 0)
        # For Case A prefer a demonstrated multi-iteration feedback run.
        bonus = 100 if case == "A" and iterations >= 2 else 0
        candidates.append((bonus + iterations, p.stat().st_mtime, p))
    if not candidates:
        raise FileNotFoundError(
            f"No accepted feedback_summary.json found for {label} under {repo / 'demo'}"
        )
    candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return candidates[0][2]


def compact_feedback(case: str, label: str, summary: dict[str, Any]) -> dict[str, Any]:
    trace = summary.get("trace") or []
    return {
        "case": case,
        "label": label,
        "status": summary.get("status"),
        "iterations": summary.get("iterations"),
        "trace": [
            {
                "iteration": item.get("iteration"),
                "action": item.get("action"),
                "approved": item.get("approved"),
                "deterministic_status": item.get("deterministic_status"),
                "failed_checks": item.get("failed_checks") or [],
                "visual_status": item.get("visual_status"),
            }
            for item in trace
        ],
    }


def compact_validation(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    raw = read_json(path)
    final = raw.get("final") or {}
    keep_final = [
        "time",
        "throat_M",
        "outlet_p",
        "outlet_T",
        "outlet_U",
        "outlet_M",
        "outlet_normal_M_min",
        "inlet_mdot",
        "outlet_mdot",
        "boundary_mismatch_pct",
        "max_window_mismatch_pct",
        "p_min",
        "p_max",
        "T_min",
        "T_max",
        "rho_min",
    ]
    return {
        "status": raw.get("status"),
        "case_id": raw.get("case_id"),
        "checks": raw.get("checks") or {},
        "final": {k: final.get(k) for k in keep_final if k in final},
        "max_Co": raw.get("max_Co"),
        "timesteps": raw.get("timesteps"),
        "final_dt": raw.get("final_dt"),
        "median_dt_last_100": raw.get("median_dt_last_100"),
        "max_transient_continuity_pct": raw.get("max_transient_continuity_pct"),
        "drift_fraction_last_2ms": raw.get("drift_fraction_last_2ms") or {},
        "field_L2_change_last_2ms": raw.get("field_L2_change_last_2ms") or {},
        "all_time_min_p_T_rho": raw.get("all_time_min_p_T_rho"),
        "scope_note": raw.get("scope_note"),
    }


def sanitize_visual(path: Path) -> dict[str, Any] | None:
    """Field-observer record without its model/provider label or machine paths."""
    if not path.exists():
        return None
    raw = read_json(path)
    return {
        "status": raw.get("status"),
        "pressure_observation": raw.get("pressure_observation"),
        "mach_observation": raw.get("mach_observation"),
        "velocity_observation": raw.get("velocity_observation"),
        "mesh_observation": raw.get("mesh_observation"),
        "suspected_regions": raw.get("suspected_regions") or [],
        "qualitative_anomalies": raw.get("qualitative_anomalies") or [],
        "visual_confidence": raw.get("visual_confidence"),
        "images_examined": [Path(x).name for x in (raw.get("images_examined") or [])],
    }


def copy_visuals(case_dir: Path, out_case: Path) -> list[str]:
    src_root = case_dir / "visuals"
    copied: list[str] = []
    if not src_root.exists():
        return copied
    for src in sorted(src_root.glob("iteration_*/*.png")):
        rel = src.relative_to(src_root)
        dst = out_case / "visuals" / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        copied.append(str(Path("visuals") / rel).replace("\\", "/"))
    return copied


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[1])
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args()

    repo = args.repo.resolve()
    out = (args.out or (repo / "demo" / "published_campaign")).resolve()
    out.mkdir(parents=True, exist_ok=True)

    campaign_cases: list[dict[str, Any]] = []
    case_results: dict[str, Any] = {}

    for case, label in CASES.items():
        summary_path = discover(repo, label, case)
        case_dir = summary_path.parent
        summary = compact_feedback(case, label, read_json(summary_path))
        campaign_cases.append(summary)

        out_case = out / label
        out_case.mkdir(parents=True, exist_ok=True)

        validation = compact_validation(case_dir / "validation.json")
        if validation is not None:
            (out_case / "RESULT_SUMMARY.json").write_text(
                json.dumps(validation, indent=2) + "\n", encoding="utf-8"
            )
            case_results[case] = validation

        visual = sanitize_visual(case_dir / "visual_observation.json")
        if visual is not None:
            (out_case / "VISUAL_OBSERVATION.json").write_text(
                json.dumps(visual, indent=2) + "\n", encoding="utf-8"
            )

        copied = copy_visuals(case_dir, out_case)
        (out_case / "FEEDBACK_SUMMARY.json").write_text(
            json.dumps({**summary, "published_visuals": copied}, indent=2) + "\n",
            encoding="utf-8",
        )

    campaign = {
        "campaign": "closed_loop_multimodal_nozzle_demo",
        "cases": campaign_cases,
        "all_accepted": all(x.get("status") == "ACCEPTED" for x in campaign_cases),
        "authority_note": (
            "LLM actions are advisory until approved by deterministic action and "
            "scientific validators. Published evidence intentionally excludes local "
            "runtime paths and provider/model labels."
        ),
    }

    (out / "CAMPAIGN_SUMMARY.json").write_text(
        json.dumps(campaign, indent=2) + "\n", encoding="utf-8"
    )
    (out / "CASE_RESULTS.json").write_text(
        json.dumps(case_results, indent=2) + "\n", encoding="utf-8"
    )

    print(json.dumps(campaign, indent=2))
    return 0 if campaign["all_accepted"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
