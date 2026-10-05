#!/usr/bin/env python3
"""Regenerate the evidence-derived records in cases/ from the archived sessions.

The archived session records are not in this repository: they are distributed
in the Zenodo archive (https://doi.org/10.5281/zenodo.23148676), whose top level holds
`demo/...` (the agent sessions) and `CFD_Verification_Package_20260929/...`
(the verification package, including the cube run). Each catalogue entry below
names its evidence by that archive-relative path; pass the directory where the
archive is unpacked with --archive-root.

What is read and what is fixed here:

* nozzle and forward-step outcomes (verdict, archived status, failed checks,
  iterations, message) are read from the archived session records
  (acceptance.json / agent_decision.json, agent_result.json /
  iteration_*/validation.json). The verdict is the four-way decision of the
  paper (Sec. 2.2): a refused or unexecuted needed action maps to
  INCONCLUSIVE, never to REJECT.
* the cube outcome re-runs the registered stationarity gate on the committed
  force history (cases/cube/drifting_wake/reference/force_history.json); the
  verdict, archived status and gate registration date are fixed by this script,
  because the gate was registered retrospectively and the archived run itself
  carries no agent decision.
* the airfoil outcome is read from the committed corrected diagnosis
  (cases/airfoil/mesh_rejection/reference/corrected_diagnosis.json); its
  verdict and status are fixed here. This family is not part of the CFD Forge
  paper.

The builder refuses to write if any required evidence root is missing, so a
clone without the archive cannot rewrite archived verdicts. It (re)writes
expected_result.json; the narrative files of an existing case (README.md,
case.yaml, reference/README.md) are curated and are only created when absent,
or rewritten with --rewrite-narrative.

    python3 scripts/build_case_library.py --archive-root /path/to/archive
    python3 scripts/build_case_library.py --archive-root /path/to/archive --check
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

#: family -> case_id -> metadata. "evidence" is relative to the archive root;
#: "archived": False marks an entry whose outcome is derived only from files
#: committed in this repository (its evidence root is then not required).
CATALOGUE: Dict[str, Dict[str, Dict[str, Any]]] = {
    "nozzle": {
        "canonical_reference": {
            "original_id": "case_A_reference",
            "evidence": "demo/nozzle_e2e/case_A_reference",
            "title": "Canonical converging-diverging nozzle",
            "purpose": "the canonical reference case of the nozzle family",
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
            "purpose": "accepted canonical run of the 2-D forward-step family",
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
        "step_height_030_x060": {
            "original_id": "case_F_step030",
            "evidence": "demo/forward_step_2d/case_F_step030",
            "title": "Step height 0.30, step at x=0.6",
            "purpose": ("the compression front was displaced toward the inlet "
                        "and could not be measured; the run stopped safely "
                        "and was rejected"),
        },
        "step_height_030_x100": {
            "original_id": "case_G_step030_x100",
            "evidence": "demo/forward_step_2d/case_G_step030_x100",
            "title": "Step height 0.30, step at x=1.0",
            "purpose": ("accepted; a separate request with a different step "
                        "position, not a continuation of step_height_030_x060"),
        },
        "iterative_correction": {
            "original_id": "case_H_iterative_short_run",
            "evidence": "demo/forward_step_2d/case_H_iterative_short_run",
            "title": "Correction loop completed in supervised resumed sessions",
            "purpose": ("accepted after seven proposals over four supervised "
                        "resumed sessions; not an unattended result"),
        },
        "mesh_sensitivity": {
            "original_id": "case_I_mesh_sensitivity",
            "evidence": "demo/forward_step_2d/case_I_mesh_sensitivity",
            "title": "Mesh-sensitivity study",
            "purpose": ("REFINE_MESH was approved; ACCEPT was refused because no "
                        "cross-grid tolerance is registered, so the decision "
                        "is INCONCLUSIVE"),
        },
        "live_run": {
            "original_id": "live_run_01",
            "evidence": "demo/forward_step_2d/live_run_01",
            "title": "Live end-to-end run (Mach 2.5, h=0.15)",
            "purpose": ("stopped by a false-positive fatal-error check; the "
                        "archived decision is REJECT, and a corrected "
                        "deterministic reanalysis returns PASS_2D_FORWARD_STEP"),
        },
    },
    "cube": {
        "drifting_wake": {
            "original_id": "family3_baseline_compact",
            "evidence": "CFD_Verification_Package_20260929/03_cube",
            "original_path": ("handoff/CFD_Agent_Handoff_20260924_1610/"
                              "family3_baseline_compact"),
            "title": "Surface-mounted cube with a drifting lateral wake",
            "purpose": ("diagnostic study of a 3-D URANS (k-omega SST) "
                        "surface-mounted cube, run outside the agent loop; the "
                        "retrospectively registered stationarity gate returns "
                        "STILL_DEVELOPING, so the decision is REJECT"),
        },
    },
    "airfoil": {
        "mesh_rejection": {
            "original_id": "naca0012_2DN00",
            "evidence": "outputs/airfoil_mesh",
            "archived": False,
            "title": "NACA0012 mesh rejection",
            "purpose": ("not part of the CFD Forge paper; the NASA Family II "
                        "grids exceed this project's frozen in-plane "
                        "stretching limit on all three levels, so CFD was not "
                        "run"),
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


#: Archived step-session statuses recording a refused needed action or an
#: approved action that was not executed. Per the paper's four decisions
#: (Sec. 2.2) these are INCONCLUSIVE, never REJECT.
_INCONCLUSIVE_STATUSES = frozenset({
    "STOPPED_ACTION_REFUSED",
    "STOPPED_REFINEMENT_REFUSED",
    "STOPPED_REBUILD_REQUIRED",
})


def _verdict_for_status(status: Optional[str]) -> str:
    if status == "ACCEPTED":
        return "ACCEPT"
    if status in _INCONCLUSIVE_STATUSES or str(status).startswith("UNEXECUTED_ACTION"):
        return "INCONCLUSIVE"
    return "REJECT"


def _forward_step_outcome(root: Path) -> Dict[str, Any]:
    result = _read_json(root / "agent_result.json") or {}
    status = result.get("status")
    iterations = sorted(p.name for p in root.glob("iteration_*"))
    last = _read_json(root / iterations[-1] / "validation.json") if iterations else None
    verdict = _verdict_for_status(status)
    return {
        "verdict": verdict,
        "archived_status": status,
        "validation_status": result.get("validation_status"),
        "iterations": len(iterations),
        "failed_checks": (last or {}).get("failed_checks", []),
        "message": result.get("message"),
        "solver_invoked_in_archive": True,
    }


#: Date the cube stationarity gate was registered (retrospectively, after the
#: archived run of 2026-09-23/24). Fixed here, not read from the archive.
CUBE_GATE_REGISTERED_ON = "2026-09-28"


def _cube_outcome(root: Path, case_dir: Path) -> Dict[str, Any]:
    """Re-run the registered gate on the committed force history.

    The verdict and archived status are fixed here: the cube was run outside
    the agent loop, so the archive holds no agent decision to read.
    """
    from src.families.cube import stationarity

    history = _read_json(case_dir / "reference" / "force_history.json") or {}
    samples = history.get("samples", [])
    result = stationarity.assess(samples).to_dict() if samples else {}
    return {
        "verdict": "REJECT",
        "archived_status": "RETROSPECTIVE_GATE_STILL_DEVELOPING",
        "gate_version": stationarity.GATE_VERSION,
        "gate_registered_on": CUBE_GATE_REGISTERED_ON,
        "rejected_on": result.get("status"),
        "failed_checks": result.get("failures", []),
        "stationarity": result,
        "solver_invoked_in_archive": True,
        "note": ("the solver ran to the requested end time and reported no "
                 "numerical failure; the rejection is on flow development"),
    }


def _airfoil_outcome(root: Path, case_dir: Path) -> Dict[str, Any]:
    """Read the CORRECTED diagnosis, never the superseded raw reports.

    Not part of the CFD Forge paper. The verdict and status are fixed here; the
    failed checks and metrics are read from the committed corrected diagnosis.

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


class ArchiveMissing(RuntimeError):
    """A required evidence root is not present under the archive root."""


#: Files of a case that are curated by hand once they exist.
NARRATIVE_FILES = ("reference/README.md", "case.yaml", "README.md",
                   "reproduce.sh", "reproduce.ps1")


def missing_evidence(archive_root: Path) -> List[str]:
    """Archive-relative evidence roots that are required but absent."""
    return [meta["evidence"]
            for cases in CATALOGUE.values() for meta in cases.values()
            if meta.get("archived", True)
            and not (archive_root / meta["evidence"]).exists()]


def build(root: Path, *, check: bool, archive_root: Optional[Path] = None,
          rewrite_narrative: bool = False) -> List[str]:
    """Return the case files that differ from the evidence (written unless check).

    Raises ArchiveMissing, before anything is written, if any required evidence
    root is absent under archive_root.
    """
    archive_root = archive_root or root
    missing = missing_evidence(archive_root)
    if missing:
        raise ArchiveMissing(
            f"archive missing under {archive_root}: " + ", ".join(missing))

    changed: List[str] = []
    for family, cases in CATALOGUE.items():
        for case_id, meta in cases.items():
            case_dir = root / "cases" / family / case_id
            evidence_root = archive_root / meta["evidence"]
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
                "evidence_present": (root / meta["evidence"]).exists(),
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

            payloads = {
                "reference/README.md": _reference_readme(root, family, case_id, meta),
                "case.yaml": _as_yaml(case_yaml),
                "expected_result.json": json.dumps(expected, indent=2) + "\n",
                "README.md": _readme(family, case_id, meta, outcome),
                "reproduce.sh": _reproduce_sh(family, case_id),
                "reproduce.ps1": _reproduce_ps1(family, case_id),
            }
            for name, text in payloads.items():
                path = case_dir / name
                if path.exists():
                    if name in NARRATIVE_FILES and not rewrite_narrative:
                        continue
                    if path.read_text(encoding="utf-8") == text:
                        continue
                changed.append(str(path.relative_to(root)))
                if not check:
                    path.parent.mkdir(parents=True, exist_ok=True)
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

Replay re-derives the deterministic decision from the archived record in
`expected_result.json` (and any series in `reference/`). It never claims a solver
was executed. {_archive_sentence(meta)}

## Archived outcome

```json
{json.dumps(outcome, indent=2)}
```

`expected_result.json` holds the same record in machine-readable form; a replay
that disagrees with it is a regression, not a new result.
{_extra(family)}"""


def _extra(family: str) -> str:
    """Family-specific footnote appended to the generated README.

    Fixed text: the values are transcribed from reference/corrected_diagnosis.json
    and the archived checkMesh logs, not read at build time.
    """
    if family != "airfoil":
        return ""
    return """
## Corrected scientific record

The authoritative record is `reference/corrected_diagnosis.json`, backed by
`reference/independent_cell_geometry_audit.json`. The raw qualification reports
under `outputs/airfoil_mesh/` (not distributed) are superseded historical evidence
and carry a `SUPERSEDED.txt` banner.

**Converter and checker defects in this project's pipeline (not properties of the
NASA grids).** The coordinate transform
`(x,y,z)_NASA -> (x,z,y)_OpenFOAM` reverses handedness; the corrected local
permutation for the archived NASA ordering is `P = (3, 7, 6, 2, 0, 4, 5, 1)`;
and the old in-plane checker used `cell[:4]`, which selects a side face rather
than the constant-span flow-plane quad. After selecting the real spanwise face
and orienting it correctly, all three levels show **0** nonpositive in-plane
areas, **0** nonpositive bilinear corner Jacobians, and span-plane coordinates
that match exactly.

**Foundation-v14 checkMesh, archived values.** The old Python
skewness metric is not Foundation-v14 skewness and must not be quoted as such.

| Level | non-orthogonality (≤65°) | skewness (≤2) | min weight (≥0.10) | min face-volume ratio (≥0.10) |
|---|---|---|---|---|
| coarse | 79.7474 **FAIL** | 0.857067 PASS | 0.123368 PASS | 0.162489 PASS |
| medium | 57.8856 PASS | 0.820430 PASS | 0.157720 PASS | 0.213368 PASS |
| fine | 31.5684 PASS | 0.727893 PASS | 0.213019 PASS | 0.301691 PASS |

**The decisive check is in-plane stretching.** The maximum in-plane stretching
exceeds this project's frozen qualification limit of 10,000 on all three levels.
The limit is an internal acceptance criterion of this pipeline, not a statement
about the suitability of the NASA grids for their intended solvers:

| Level | max stretching | cells over the limit |
|---|---|---|
| coarse | 31,734,384 | 974 |
| medium | 36,320,937 | 3,924 |
| fine | 38,855,541 | 15,678 |

Face-tet warnings remain unresolved at 72 / 214 / 625 faces. They are not needed
to establish the rejection, because stretching already exceeds the limit.

**Final status: `MESH_REJECTED / CFD_NOT_RUN`.** Skewness and orientation do not
fail once the converter defects above are corrected.
"""


def _reference_readme(root: Path, family: str, case_id: str,
                      meta: Dict[str, Any]) -> str:
    """Every case ships a reference/ directory, so a clone has the same shape.

    Git does not track an empty directory, so a case whose evidence lives
    elsewhere would lose its reference/ on clone and the case contract would
    differ between the development tree and a clone.
    """
    extracted = sorted(p.name for p in
                       (root / "cases" / family / case_id / "reference").glob("*")
                       if p.name != "README.md")
    listing = ("\n".join(f"- `{name}`" for name in extracted)
               if extracted else "- (none: this case needs no extracted series)")
    return f"""# Reference data — {family}/{case_id}

Compact series extracted from the archived run, committed so that a replay works
from a clone:

{listing}

{_archive_sentence(meta)} Replay does not need them: the deterministic record a
replay re-evaluates is `../expected_result.json`, and any series it needs is in
this directory.
"""


def _archive_sentence(meta: Dict[str, Any]) -> str:
    if not meta.get("archived", True):
        return (f"The raw records (`{meta['evidence']}`) are not distributed; "
                "the corrected record is in this directory.")
    original = (f" (originally `{meta['original_path']}`)"
                if meta.get("original_path") else "")
    return ("The archived records are in the Zenodo archive "
            f"(https://doi.org/10.5281/zenodo.23148676) under `{meta['evidence']}`{original}; they are not in "
            "this repository.")


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
    ap.add_argument("--archive-root", type=Path, default=None,
                    help=("directory holding the unpacked Zenodo archive "
                          "(demo/..., CFD_Verification_Package_20260929/...); "
                          "default: the repository root"))
    ap.add_argument("--check", action="store_true",
                    help="report drift without writing")
    ap.add_argument("--rewrite-narrative", action="store_true",
                    help=("also regenerate README.md, case.yaml, "
                          "reference/README.md and reproduce scripts of "
                          "existing cases (they are curated by default)"))
    args = ap.parse_args()
    try:
        changed = build(_ROOT, check=args.check, archive_root=args.archive_root,
                        rewrite_narrative=args.rewrite_narrative)
    except ArchiveMissing as exc:
        print(f"{exc}\nNothing was {'checked' if args.check else 'written'}: "
              "the archived evidence is in the Zenodo archive "
              "(https://doi.org/10.5281/zenodo.23148676); pass its location with --archive-root.")
        return 2
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
