# Step height 0.30, step at x=1.0

**Family:** `forward_step` &nbsp;|&nbsp; **Case:** `step_height_030_x100` &nbsp;|&nbsp;
**Original id:** `case_G_step030_x100` &nbsp;|&nbsp; **Archived verdict:** `ACCEPT`

Step-position variation (paper ledger S6): Mach 3, h=0.3 with the step at x=1.0. The front had not reached the inlet at t=4 and the run passed its contract: `PASS_2D_FORWARD_STEP` -> `ACCEPT` in one iteration. This is a separate request with a different step position, not a continuation of `step_height_030_x060`.

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
was executed. The archived session records are in the Zenodo archive (DOI to be added on release) under the same relative path, `demo/forward_step_2d/case_G_step030_x100`; they are not in this repository.

## Archived outcome

```json
{
  "verdict": "ACCEPT",
  "archived_status": "ACCEPTED",
  "validation_status": "PASS_2D_FORWARD_STEP",
  "iterations": 1,
  "failed_checks": [],
  "message": "PASS_2D_FORWARD_STEP",
  "solver_invoked_in_archive": true
}
```

`expected_result.json` holds the same record in machine-readable form; a replay
that disagrees with it is a regression, not a new result.
