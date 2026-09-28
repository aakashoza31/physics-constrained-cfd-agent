# Forward-facing step at Mach 2.0

**Family:** `forward_step` &nbsp;|&nbsp; **Case:** `mach20_canonical` &nbsp;|&nbsp;
**Original id:** `case_B_mach20` &nbsp;|&nbsp; **Archived verdict:** `ACCEPT`

Accepted reference run of the f2 family.

## Reproduce

```bash
./reproduce.sh              # replay the archived evidence, no solver
./reproduce.sh --live       # re-execute with OpenFOAM Foundation v14
```

```powershell
.\reproduce.ps1             # replay
.\reproduce.ps1 -Live       # re-execute
```

Replay reads the archived evidence under `demo/forward_step_2d/case_B_mach20` and re-derives the
deterministic decision from it. It never claims a solver was executed.

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
