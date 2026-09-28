# Mesh-sensitivity study

**Family:** `forward_step` &nbsp;|&nbsp; **Case:** `mesh_sensitivity` &nbsp;|&nbsp;
**Original id:** `case_I_mesh_sensitivity` &nbsp;|&nbsp; **Archived verdict:** `REJECT`

Mesh-sensitivity evidence; the loop stopped when a proposed action was refused.

## Reproduce

```bash
./reproduce.sh              # replay the archived evidence, no solver
./reproduce.sh --live       # re-execute with OpenFOAM Foundation v14
```

```powershell
.\reproduce.ps1             # replay
.\reproduce.ps1 -Live       # re-execute
```

Replay reads the archived evidence under `demo/forward_step_2d/case_I_mesh_sensitivity` and re-derives the
deterministic decision from it. It never claims a solver was executed.

## Archived outcome

```json
{
  "verdict": "REJECT",
  "archived_status": "STOPPED_ACTION_REFUSED",
  "validation_status": null,
  "iterations": 2,
  "failed_checks": [],
  "message": "ACCEPT refused: ACCEPT refused: this request asked for a numerical-sensitivity assessment, and the registered cross-grid requirement is not met (SENSITIVITY_CRITERION_NOT_REGISTERED). NOT REGISTERED. No cross-grid tolerance exists in this repository: validate.py lists mesh independence under 'unresolved' and disclaims a mesh-independence claim, and no reference package for this family is present from which a published band could be adopted. The comparison is measured and reported; the verdict is withheld until a criterion is supplied. No tolerance is invented here.",
  "solver_invoked_in_archive": true
}
```

`expected_result.json` holds the same record in machine-readable form; a replay
that disagrees with it is a regression, not a new result.
