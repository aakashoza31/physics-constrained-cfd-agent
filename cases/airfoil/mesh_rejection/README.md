# NACA0012 mesh rejection

**Family:** `airfoil` &nbsp;|&nbsp; **Case:** `mesh_rejection` &nbsp;|&nbsp;
**Original id:** `naca0012_2DN00` &nbsp;|&nbsp; **Archived verdict:** `REJECT`

Not part of the CFD Forge paper; development record of a mesh-qualification check. The maximum in-plane stretching of the NASA Family II NACA0012 grids exceeds this project's frozen limit (10,000) on all three levels, so the grids were not qualified for this pipeline and CFD was not run.

## Reproduce

```bash
./reproduce.sh              # replay the archived evidence, no solver
```

```powershell
.\reproduce.ps1             # replay
```

Live execution is refused for this family; only replay is available.

Replay re-derives the deterministic decision from the archived record in
`expected_result.json` (and any series in `reference/`). It never claims a solver
was executed. The raw mesh-qualification outputs are not distributed (this family is not part of the CFD Forge paper); the corrected record is in `reference/`.

## Archived outcome

```json
{
  "verdict": "REJECT",
  "archived_status": "MESH_REJECTED_CFD_NOT_RUN",
  "failed_checks": [
    "max_in_plane_stretching",
    "max_non_orthogonality"
  ],
  "unresolved_checks": [
    "face_tet_checks"
  ],
  "decisive_failure": {
    "check": "max_in_plane_stretching",
    "frozen_limit": 10000.0,
    "levels": {
      "coarse": {
        "max": 31734384.049936082,
        "cells_over_limit": 974,
        "cells_total": 14336
      },
      "medium": {
        "max": 36320937.1389407,
        "cells_over_limit": 3924,
        "cells_total": 57344
      },
      "fine": {
        "max": 38855541.17768772,
        "cells_over_limit": 15678,
        "cells_total": 229376
      }
    }
  },
  "mesh_levels": {
    "coarse": "F3_MESH_NOT_QUALIFIED",
    "medium": "F3_MESH_NOT_QUALIFIED",
    "fine": "F3_MESH_NOT_QUALIFIED"
  },
  "foundation_v14_metrics": {
    "coarse": {
      "max_non_orthogonality": 79.7474,
      "max_skewness": 0.857067,
      "min_interpolation_weight": 0.123368,
      "min_face_volume_ratio": 0.162489,
      "face_tet_checks": {
        "warning_faces": 72
      }
    },
    "medium": {
      "max_non_orthogonality": 57.8856,
      "max_skewness": 0.82043,
      "min_interpolation_weight": 0.15772,
      "min_face_volume_ratio": 0.213368,
      "face_tet_checks": {
        "warning_faces": 214
      }
    },
    "fine": {
      "max_non_orthogonality": 31.5684,
      "max_skewness": 0.727893,
      "min_interpolation_weight": 0.213019,
      "min_face_volume_ratio": 0.301691,
      "face_tet_checks": {
        "warning_faces": 625
      }
    }
  },
  "representation_defects_were_ours_not_nasas": [
    "handedness",
    "vertex permutation",
    "wrong face selected by the in-plane checker",
    "non-equivalent skewness metric"
  ],
  "solver_invoked_in_archive": false,
  "source_of_truth": "cases/airfoil/mesh_rejection/reference/corrected_diagnosis.json",
  "note": "CFD_NOT_RUN: no flow solver was ever launched for this family. The decisive genuine failure is in-plane stretching; skewness and orientation are NOT NASA-grid failures."
}
```

`expected_result.json` holds the same record in machine-readable form; a replay
that disagrees with it is a regression, not a new result.

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
