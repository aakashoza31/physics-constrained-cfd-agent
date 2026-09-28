# NACA0012 mesh rejection (supplementary)

**Family:** `airfoil` &nbsp;|&nbsp; **Case:** `mesh_rejection` &nbsp;|&nbsp;
**Original id:** `naca0012_2DN00` &nbsp;|&nbsp; **Archived verdict:** `REJECT`

S1: every candidate mesh failed the frozen quality contract, so cfd was never run.

## Reproduce

```bash
./reproduce.sh              # replay the archived evidence, no solver
./reproduce.sh --live       # re-execute with OpenFOAM Foundation v14
```

```powershell
.\reproduce.ps1             # replay
.\reproduce.ps1 -Live       # re-execute
```

Replay reads the archived evidence under `outputs/airfoil_mesh` and re-derives the
deterministic decision from it. It never claims a solver was executed.

## Archived outcome

```json
{
  "verdict": "REJECT",
  "archived_status": "MESH_REJECTED_CFD_NOT_RUN",
  "failed_checks": [
    "all_in_plane_elements_valid",
    "max_non_orthogonality",
    "max_skewness",
    "positive_cell_orientation"
  ],
  "mesh_levels": {
    "coarse": "F3_MESH_NOT_QUALIFIED",
    "medium": "F3_MESH_NOT_QUALIFIED",
    "fine": "F3_MESH_NOT_QUALIFIED"
  },
  "solver_invoked_in_archive": false,
  "note": "CFD_NOT_RUN: no flow solver was ever launched for this family"
}
```

`expected_result.json` holds the same record in machine-readable form; a replay
that disagrees with it is a regression, not a new result.
