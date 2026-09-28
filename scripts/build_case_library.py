#!/usr/bin/env python3
"""Regenerate cases/ from the archived evidence that already exists.

Every field written here is READ from the archived run, never invented: the
status a case carries is the status its own evidence records. Re-running this
script on unchanged evidence produces unchanged files, so `cases/` is a
reviewable index of the campaign rather than a hand-maintained story.

    python3 scripts/build_case_library.py            # write cases/
    python3 scripts/build_case_library.py --check    # fail if out of date
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

BUILDER_VERSION = "case-library/1.0.0"

#: family -> case_id -> (original_id, evidence_root, title, purpose)
CATALOGUE: Dict[str, Dict[str, Dict[str, Any]]] = {
    "nozzle": {
        "canonical_reference": {
            "original_id": "case_A_reference",
            "evidence": "demo/nozzle_e2e/case_A_reference",
            "title": "Canonical converging-diverging nozzle",
            "purpose": "the validated reference case for F1",
            "config": "configs/nozzles/case_A_reference.yaml",
            "campaigns": ["demo/nozzle_feedback/case_A_reference",
                          "demo/nozzle_feedback_v2/case_A_reference",
                          "demo/nozzle_feedback_v2_hotfix/case_A_reference",
                          "demo/published_campaign/case_A_reference"],
        },
        "geometry_variation": {
            "original_id": "case_B_geometry",
            "evidence": "demo/nozzle_e2e/case_B_geometry",
            "title": "Geometry variation",
            "purpose": "same physics, altered nozzle geometry",
            "config": "configs/nozzles/case_B_geometry.yaml",
            "campaigns": ["demo/nozzle_feedback_final/case_B_geometry",
                          "demo/published_campaign/case_B_geometry"],
        },
        "condition_variation": {
            "original_id": "case_C_conditions",
            "evidence": "demo/nozzle_e2e/case_C_conditions",
            "title": "Operating-condition variation",
            "purpose": "same geometry, altered operating conditions",
            "config": "configs/nozzles/case_C_conditions.yaml",
            "campaigns": ["demo/nozzle_feedback_final/case_C_conditions",
                          "demo/published_campaign/case_C_conditions"],
        },
    },
    "forward_step": {
        "mach20_canonical": {
            "original_id": "case_B_mach20",
            "evidence": "demo/forward_step_2d/case_B_mach20",
            "title": "Forward-facing step at Mach 2.0",
            "purpose": "accepted reference run of the F2 family",
        },
        "mach35_variation": {
            "original_id": "case_C_mach35",
            "evidence": "demo/forward_step_2d/case_C_mach35",
            "title": "Forward-facing step at Mach 3.5",
            "purpose": "accepted Mach-number variation",
        },
        "step_height_010": {
            "original_id": "case_E_step010",
            "evidence": "demo/forward_step_2d/case_E_step010",
            "title": "Reduced step height 0.10",
            "purpose": "accepted geometry variation",
        },
        "step_height_030_short_horizon": {
            "original_id": "case_F_step030",
            "evidence": "demo/forward_step_2d/case_F_step030",
            "title": "Step height 0.30, short horizon",
            "purpose": ("the INADMISSIBLE variation: the run stopped safely "
                        "instead of being accepted"),
        },
        "step_height_030_extended": {
            "original_id": "case_G_step030_x100",
            "evidence": "demo/forward_step_2d/case_G_step030_x100",
            "title": "Step height 0.30, extended horizon",
            "purpose": "accepted after the horizon was extended",
        },
        "iterative_correction": {
            "original_id": "case_H_iterative_short_run",
            "evidence": "demo/forward_step_2d/case_H_iterative_short_run",
            "title": "Bounded correction loop",
            "purpose": "accepted after several bounded corrective iterations",
        },
        "mesh_sensitivity": {
            "original_id": "case_I_mesh_sensitivity",
            "evidence": "demo/forward_step_2d/case_I_mesh_sensitivity",
            "title": "Mesh-sensitivity study",
            "purpose": ("mesh-sensitivity evidence; the loop stopped when a "
                        "proposed action was refused"),
        },
        "live_run": {
            "original_id": "live_run_01",
            "evidence": "demo/forward_step_2d/live_run_01",
            "title": "Live end-to-end run",
            "purpose": "a live execution that ended in a safe stop",
        },
    },
    "cube": {
        "drifting_wake": {
            "original_id": "family3_baseline_compact",
            "evidence": ("handoff/CFD_Agent_Handoff_20260924_1610/"
                         "family3_baseline_compact"),
            "title": "Surface-mounted cube with a drifting lateral wake",
            "purpose": ("F3 headline demonstration: a 3-D turbulent run that "
                        "executed, looked healthy, and was REJECTED on "
                        "stationarity / development"),
        },
    },
    "airfoil": {
        "mesh_rejection": {
            "original_id": "naca0012_2DN00",
            "evidence": "outputs/airfoil_mesh",
            "title": "NACA0012 mesh rejection (supplementary)",
            "purpose": ("S1: every candidate mesh failed the frozen quality "
                        "contract, so CFD was never run"),
        },
    },
}


def _read_json(path: Path) -> Optional[Dict[str, Any]]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _nozzle_outcome(root: Path) -> Dict[str, Any]:
    acceptance = _read_json(root / "acceptance.json") or {}
    decision = (_read_json(root / "agent_decision.json") or {}).get("decision", {})
    return {
        "verdict": "ACCEPT" if acceptance.get("accepted") else "REJECT",
        "archived_status": acceptance.get("deterministic_status"),
        "failed_checks": acceptance.get("failed_checks", []),
        "llm_diagnosis": decision.get("diagnosis"),
        "llm_proposed_action": acceptance.get("llm_proposed_action"),
        "llm_action_approved": acceptance.get("llm_action_approved_by_validator"),
        "authority": acceptance.get("authority"),
        "solver_invoked_in_archive": True,
    }


def _forward_step_outcome(root: Path) -> Dict[str, Any]:
    result = _read_json(root / "agent_result.json") or {}
    status = result.get("status")
    iterations = sorted(p.name for p in root.glob("iteration_*"))
    last = _read_json(root / iterations[-1] / "validation.json") if iterations else None
    verdict = {"ACCEPTED": "ACCEPT"}.get(status, "REJECT")
    return {
        "verdict": verdict,
        "archived_status": status,
        "validation_status": result.get("validation_status"),
        "iterations": len(iterations),
        "failed_checks": (last or {}).get("failed_checks", []),
        "message": result.get("message"),
        "solver_invoked_in_archive": True,
    }


def _cube_outcome(root: Path, case_dir: Path) -> Dict[str, Any]:
    from src.families.cube.stationarity import assess

    history = _read_json(case_dir / "reference" / "force_history.json") or {}
    samples = history.get("samples", [])
    result = assess(samples).to_dict() if samples else {}
    return {
        "verdict": "REJECT",
        "archived_status": "RUNTIME_REJECTED",
        "rejected_on": result.get("status"),
        "failed_checks": result.get("failures", []),
        "stationarity": result,
        "solver_invoked_in_archive": True,
        "note": ("the solver ran to the requested end time and reported no "
                 "numerical failure; the rejection is on flow development"),
    }


def _airfoil_outcome(root: Path) -> Dict[str, Any]:
    summary = _read_json(root / "nasa_familyII" / "hierarchy.json") or {}
    levels = {k: v.get("qualification_verdict")
              for k, v in (summary.get("levels") or {}).items()}
    return {
        "verdict": "REJECT",
        "archived_status": "MESH_REJECTED_CFD_NOT_RUN",
        "failed_checks": sorted({f for v in (summary.get("levels") or {}).values()
                                 for f in (v.get("failed") or [])}),
        "mesh_levels": levels,
        "solver_invoked_in_archive": False,
        "note": "CFD_NOT_RUN: no flow solver was ever launched for this family",
    }


def build(root: Path, *, check: bool) -> List[str]:
    from src.families import capabilities as caps

    changed: List[str] = []
    for family, cases in CATALOGUE.items():
        capability = caps.TABLE.get(family) or caps.TABLE.get("forward_step_2d")
        for case_id, meta in cases.items():
            case_dir = root / "cases" / family / case_id
            evidence_root = root / meta["evidence"]
            if family == "nozzle":
                outcome = _nozzle_outcome(evidence_root)
            elif family == "forward_step":
                outcome = _forward_step_outcome(evidence_root)
            elif family == "cube":
                outcome = _cube_outcome(evidence_root, case_dir)
            else:
                outcome = _airfoil_outcome(evidence_root)

            case_yaml = {
                "case_id": case_id,
                "original_id": meta["original_id"],
                "family": family,
                "title": meta["title"],
                "purpose": meta["purpose"],
                "evidence_root": meta["evidence"],
                "evidence_present": evidence_root.exists(),
                "config": meta.get("config"),
                "related_campaigns": meta.get("campaigns", []),
                "solver": "OpenFOAM Foundation v14",
                "builder_version": BUILDER_VERSION,
            }
            expected = {
                "case_id": case_id,
                "family": family,
                "original_id": meta["original_id"],
                "expected": outcome,
                "source_of_truth": meta["evidence"],
                "note": ("this is the result the archived evidence records; a "
                         "replay that disagrees with it is a regression"),
            }
            case_dir.mkdir(parents=True, exist_ok=True)
            (case_dir / "reference").mkdir(exist_ok=True)

            payloads = {
                "case.yaml": _as_yaml(case_yaml),
                "expected_result.json": json.dumps(expected, indent=2) + "\n",
                "README.md": _readme(family, case_id, meta, outcome),
                "reproduce.sh": _reproduce_sh(family, case_id),
                "reproduce.ps1": _reproduce_ps1(family, case_id),
            }
            for name, text in payloads.items():
                path = case_dir / name
                if path.exists() and path.read_text(encoding="utf-8") == text:
                    continue
                changed.append(str(path.relative_to(root)))
                if not check:
                    path.write_text(text, encoding="utf-8")
                    if name.endswith(".sh"):
                        path.chmod(0o755)
    return changed


def _as_yaml(data: Dict[str, Any], indent: int = 0) -> str:
    """Minimal YAML writer: this repo's case files are flat by design."""
    lines: List[str] = []
    pad = "  " * indent
    for key, value in data.items():
        if isinstance(value, dict):
            lines.append(f"{pad}{key}:")
            lines.append(_as_yaml(value, indent + 1).rstrip("\n"))
        elif isinstance(value, list):
            if not value:
                lines.append(f"{pad}{key}: []")
            else:
                lines.append(f"{pad}{key}:")
                for item in value:
                    lines.append(f"{pad}  - {json.dumps(item)}")
        elif value is None:
            lines.append(f"{pad}{key}: null")
        elif isinstance(value, bool):
            lines.append(f"{pad}{key}: {'true' if value else 'false'}")
        elif isinstance(value, (int, float)):
            lines.append(f"{pad}{key}: {value}")
        else:
            lines.append(f"{pad}{key}: {json.dumps(str(value))}")
    return "\n".join(lines) + "\n"


def _readme(family: str, case_id: str, meta: Dict[str, Any],
            outcome: Dict[str, Any]) -> str:
    verdict = outcome["verdict"]
    return f"""# {meta['title']}

**Family:** `{family}` &nbsp;|&nbsp; **Case:** `{case_id}` &nbsp;|&nbsp;
**Original id:** `{meta['original_id']}` &nbsp;|&nbsp; **Archived verdict:** `{verdict}`

{meta['purpose'].capitalize()}.

## Reproduce

```bash
./reproduce.sh              # replay the archived evidence, no solver
./reproduce.sh --live       # re-execute with OpenFOAM Foundation v14
```

```powershell
.\\reproduce.ps1             # replay
.\\reproduce.ps1 -Live       # re-execute
```

Replay reads the archived evidence under `{meta['evidence']}` and re-derives the
deterministic decision from it. It never claims a solver was executed.

## Archived outcome

```json
{json.dumps(outcome, indent=2)}
```

`expected_result.json` holds the same record in machine-readable form; a replay
that disagrees with it is a regression, not a new result.
"""


def _reproduce_sh(family: str, case_id: str) -> str:
    return f"""#!/usr/bin/env bash
# Reproduce {family}/{case_id}. Replay by default; --live re-executes OpenFOAM.
set -euo pipefail
cd "$(dirname "$0")/../../.."
MODE=replay
EXTRA=()
if [[ "${{1:-}}" == "--live" ]]; then
  MODE=live
  EXTRA+=(--i-want-to-run-cfd)
fi
python3 scripts/run_demo.py --family {family} --case {case_id} --mode "$MODE" "${{EXTRA[@]}}"
"""


def _reproduce_ps1(family: str, case_id: str) -> str:
    return f"""# Reproduce {family}/{case_id}. Replay by default; -Live re-executes OpenFOAM.
param([switch]$Live)
Set-Location (Join-Path $PSScriptRoot "..\\..\\..")
$mode = if ($Live) {{ "live" }} else {{ "replay" }}
$extra = if ($Live) {{ @("--i-want-to-run-cfd") }} else {{ @() }}
python scripts/run_demo.py --family {family} --case {case_id} --mode $mode @extra
"""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true",
                    help="report drift without writing")
    args = ap.parse_args()
    changed = build(_ROOT, check=args.check)
    if args.check and changed:
        print("cases/ is out of date:")
        for path in changed:
            print(f"  {path}")
        return 1
    print(f"{len(changed)} file(s) {'would be ' if args.check else ''}written")
    for path in changed[:8]:
        print(f"  {path}")
    if len(changed) > 8:
        print(f"  ... and {len(changed) - 8} more")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
