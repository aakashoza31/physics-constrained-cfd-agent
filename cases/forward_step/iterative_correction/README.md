# Correction loop completed in supervised resumed sessions

**Family:** `forward_step` &nbsp;|&nbsp; **Case:** `iterative_correction` &nbsp;|&nbsp;
**Original id:** `case_H_iterative_short_run` &nbsp;|&nbsp; **Archived verdict:** `ACCEPT`

Mach 3, h=0.2, staged horizon to t=4 (paper ledger S7). Seven proposals, two of them refused (`CONTINUE_RUN` after the requested horizon was reached; a further `EXTEND_END_TIME` after the iteration budget was exhausted), over four supervised resumed sessions. The run was accepted (`PASS_2D_FORWARD_STEP` -> `ACCEPT`) after the restart-seam treatment in the mass-closure diagnostic was corrected, so this acceptance is not an unattended result.

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
was executed. The archived session records are in the Zenodo archive (DOI to be added on release) under the same relative path, `demo/forward_step_2d/case_H_iterative_short_run`; they are not in this repository.

## Archived outcome

```json
{
  "verdict": "ACCEPT",
  "archived_status": "ACCEPTED",
  "validation_status": "PASS_2D_FORWARD_STEP",
  "iterations": 7,
  "failed_checks": [],
  "message": "PASS_2D_FORWARD_STEP",
  "solver_invoked_in_archive": true
}
```

`expected_result.json` holds the same record in machine-readable form; a replay
that disagrees with it is a regression, not a new result.
