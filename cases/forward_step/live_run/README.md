# Live end-to-end run

**Family:** `forward_step` &nbsp;|&nbsp; **Case:** `live_run` &nbsp;|&nbsp;
**Original id:** `live_run_01` &nbsp;|&nbsp; **Archived verdict:** `REJECT`

A live execution that ended in a safe stop.

## Reproduce

```bash
./reproduce.sh              # replay the archived evidence, no solver
./reproduce.sh --live       # re-execute with OpenFOAM Foundation v14
```

```powershell
.\reproduce.ps1             # replay
.\reproduce.ps1 -Live       # re-execute
```

Replay reads the archived evidence under `demo/forward_step_2d/live_run_01` and re-derives the
deterministic decision from it. It never claims a solver was executed.

## Archived outcome

```json
{
  "verdict": "REJECT",
  "archived_status": "STOPPED_FAIL_SAFELY",
  "validation_status": null,
  "iterations": 1,
  "failed_checks": [
    "no_fatal_error"
  ],
  "message": "Although the run reached the requested end time and saved finite positive fields, the deterministic checks show a fatal error flag triggered during the simulation. Therefore, the numerical run is classified as unstable.",
  "solver_invoked_in_archive": true
}
```

`expected_result.json` holds the same record in machine-readable form; a replay
that disagrees with it is a regression, not a new result.
