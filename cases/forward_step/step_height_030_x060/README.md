# Step height 0.30, short horizon

**Family:** `forward_step` &nbsp;|&nbsp; **Case:** `step_height_030_x060` &nbsp;|&nbsp;
**Original id:** `case_F_step030` &nbsp;|&nbsp; **Archived verdict:** `REJECT`

The inadmissible variation: the run stopped safely instead of being accepted.

## Reproduce

```bash
./reproduce.sh              # replay the archived evidence, no solver
./reproduce.sh --live       # re-execute with OpenFOAM Foundation v14
```

```powershell
.\reproduce.ps1             # replay
.\reproduce.ps1 -Live       # re-execute
```

Replay reads the archived evidence under `demo/forward_step_2d/case_F_step030` and re-derives the
deterministic decision from it. It never claims a solver was executed.

## Archived outcome

```json
{
  "verdict": "REJECT",
  "archived_status": "STOPPED_FAIL_SAFELY",
  "validation_status": null,
  "iterations": 1,
  "failed_checks": [
    "compression_front_measurable"
  ],
  "message": "Although the solver completed successfully and satisfied most checks, the deterministic check for the compression front failed because the primary shock structure has migrated upstream to the inlet boundary. Consequently, no valid measurable compression structure remains inside the domain.",
  "solver_invoked_in_archive": true
}
```

`expected_result.json` holds the same record in machine-readable form; a replay
that disagrees with it is a regression, not a new result.
