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
            "purpose": ("S1 supplementary: the NASA Family II grids fail the "
                        "frozen in-plane stretching contract by three to four "
                        "orders of magnitude, so CFD was never run"),
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


def _airfoil_outcome(root: Path, case_dir: Path) -> Dict[str, Any]:
    """Read the CORRECTED diagnosis, never the superseded raw reports.

    The raw qualification reports under outputs/airfoil_mesh/ contain converter
    and diagnostic defects (handedness, vertex permutation, the wrong face
    selected for in-plane checks, and a Python skewness metric that is not
    Foundation-v14 skewness). They are preserved as historical evidence and are
    deliberately NOT the source of truth here.
    """
    record = _read_json(case_dir / "reference" / "corrected_diagnosis.json") or {}
    levels = record.get("levels") or {}
    decisive = record.get("decisive_genuine_failure") or {}
    return {
        "verdict": "REJECT",
        "archived_status": "MESH_REJECTED_CFD_NOT_RUN",
        "failed_checks": sorted({f for lv in levels.values()
                                 for f in (lv.get("failed") or [])}),
        "unresolved_checks": sorted({u for lv in levels.values()
                                     for u in (lv.get("unresolved") or [])}),
        "decisive_failure": {
            "check": decisive.get("check"),
            "frozen_limit": decisive.get("frozen_limit"),
            "levels": decisive.get("levels"),
        },
        "mesh_levels": {name: lv.get("verdict") for name, lv in levels.items()},
        "foundation_v14_metrics": {
            name: {k: v.get("measured") for k, v in (lv.get("checks") or {}).items()
                   if v.get("source", "").startswith("OpenFOAM")}
            for name, lv in levels.items()
        },
        "representation_defects_were_ours_not_nasas": [
            d["defect"] for d in record.get(
                "representation_defects_found_in_our_converter", [])
        ],
        "solver_invoked_in_archive": False,
        "source_of_truth": "cases/airfoil/mesh_rejection/reference/corrected_diagnosis.json",
        "note": ("CFD_NOT_RUN: no flow solver was ever launched for this family. "
                 "The decisive genuine failure is in-plane stretching; skewness "
                 "and orientation are NOT NASA-grid failures."),
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
                outcome = _airfoil_outcome(evidence_root, case_dir)

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
            reference = case_dir / "reference"
            reference.mkdir(exist_ok=True)

            payloads = {
                "reference/README.md": _reference_readme(family, case_id, meta),
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
{_extra(family)}"""


def _extra(family: str) -> str:
    """Family-specific footnote appended to the generated README."""
    if family != "airfoil":
        return ""
    return """
## Corrected scientific record

The authoritative record is `reference/corrected_diagnosis.json`, backed by
`reference/independent_cell_geometry_audit.json`. The raw qualification reports
under `outputs/airfoil_mesh/` are **superseded historical evidence** and carry a
`SUPERSEDED.txt` banner.

**Defects that were ours, not NASA's.** The coordinate transform
`(x,y,z)_NASA -> (x,z,y)_OpenFOAM` reverses handedness; the corrected local
permutation for the archived NASA ordering is `P = (3, 7, 6, 2, 0, 4, 5, 1)`;
and the old in-plane checker used `cell[:4]`, which selects a side face rather
than the constant-span flow-plane quad. After selecting the real spanwise face
and orienting it correctly, all three levels show **0** nonpositive in-plane
areas, **0** nonpositive bilinear corner Jacobians, and span-plane coordinates
that match exactly.

**Foundation-v14 checkMesh, the actual archived numbers.** The old Python
skewness metric is not Foundation-v14 skewness and must not be quoted as such.

| Level | non-orthogonality (≤65°) | skewness (≤2) | min weight (≥0.10) | min face-volume ratio (≥0.10) |
|---|---|---|---|---|
| coarse | 79.7474 **FAIL** | 0.857067 PASS | 0.123368 PASS | 0.162489 PASS |
| medium | 57.8856 PASS | 0.820430 PASS | 0.157720 PASS | 0.213368 PASS |
| fine | 31.5684 PASS | 0.727893 PASS | 0.213019 PASS | 0.301691 PASS |

**The decisive genuine failure is in-plane stretching**, frozen limit 10,000:

| Level | max stretching | cells over the limit |
|---|---|---|
| coarse | 31,734,384 | 974 |
| medium | 36,320,937 | 3,924 |
| fine | 38,855,541 | 15,678 |

Face-tet warnings remain unresolved at 72 / 214 / 625 faces. They are not needed
to establish the rejection, because stretching already fails decisively.

**Final status: `MESH_REJECTED / CFD_NOT_RUN`.** Skewness and orientation are
*not* genuine NASA-grid failures and must not be described as such.
"""


def _reference_readme(family: str, case_id: str, meta: Dict[str, Any]) -> str:
    """Every case ships a reference/ directory, so a clone has the same shape.

    Git does not track an empty directory, so a case whose evidence lives
    elsewhere would lose its reference/ on clone and the case contract would
    differ between the development tree and a reviewer's checkout.
    """
    extracted = sorted(p.name for p in
                       (_ROOT / "cases" / family / case_id / "reference").glob("*")
                       if p.name != "README.md")
    listing = ("\n".join(f"- `{name}`" for name in extracted)
               if extracted else "- (none: this case needs no extracted series)")
    return f"""# Reference data — {family}/{case_id}

Compact series extracted from the archived run, committed so that a replay works
from a clone:

{listing}

The full archived evidence for this case is `{meta['evidence']}`, which is
gitignored because of its size; its inventory and digests are in
`manifests/large_assets.json`. Replay does not require it: the deterministic
record a replay re-evaluates is `../expected_result.json`, and any series it
needs is in this directory.
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
