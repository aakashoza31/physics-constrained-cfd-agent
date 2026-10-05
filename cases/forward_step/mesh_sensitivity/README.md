# Mesh-sensitivity request

**Family:** `forward_step` &nbsp;|&nbsp; **Case:** `mesh_sensitivity` &nbsp;|&nbsp;
**Original id:** `case_I_mesh_sensitivity` &nbsp;|&nbsp; **Archived verdict:** `INCONCLUSIVE`

Mach 3, h=0.2 numerical-sensitivity request (paper ledger S8). `REFINE_MESH` was approved (4,032 to 16,128 cells, fresh solve) and both grids passed their hard checks; the model then proposed `ACCEPT`, which the validator refused because no cross-grid tolerance is registered for the step family. Final status `STOPPED_ACTION_REFUSED` -> `INCONCLUSIVE`.

## Reproduce

```bash
./reproduce.sh              # replay the archived evidence, no solver
./reproduce.sh --live       # re-execute with OpenFOAM Foundation v14
```

```powershell
.\reproduce.ps1             # replay
.\reproduce.ps1 -Live       # re-execute
```

Replay re-derives the deterministic decision from the archived record in
`expected_result.json` (and any series in `reference/`). It never claims a solver
was executed. The archived session records are in the Zenodo archive (https://doi.org/10.5281/zenodo.23148676) under the same relative path, `demo/forward_step_2d/case_I_mesh_sensitivity`; they are not in this repository.

## Archived outcome

```json
{
  "verdict": "INCONCLUSIVE",
  "archived_status": "STOPPED_ACTION_REFUSED",
  "validation_status": null,
  "iterations": 2,
  "failed_checks": [],
  "message": "ACCEPT refused: this request asked for a numerical-sensitivity assessment, and the registered cross-grid requirement is not met (SENSITIVITY_CRITERION_NOT_REGISTERED). NOT REGISTERED. No cross-grid tolerance exists in this repository: validate.py lists mesh independence under 'unresolved' and disclaims a mesh-independence claim, and no reference package for this family is present from which a published band could be adopted. The comparison is measured and reported; the verdict is withheld until a criterion is supplied. No tolerance is invented here.",
  "solver_invoked_in_archive": true
}
```

`expected_result.json` holds the same record in machine-readable form; a replay
that disagrees with it is a regression, not a new result.
