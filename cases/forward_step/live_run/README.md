# Live end-to-end run (Mach 2.5, h=0.15)

**Family:** `forward_step` &nbsp;|&nbsp; **Case:** `live_run` &nbsp;|&nbsp;
**Original id:** `live_run_01` &nbsp;|&nbsp; **Archived verdict:** `REJECT`

First live forward-step session (paper ledger S1): Mach 2.5, h=0.15. It was stopped by a false-positive fatal-error check; the archived decision is `REJECT`, and a corrected deterministic reanalysis returns `PASS_2D_FORWARD_STEP`.

## Known validator defect

The archived session stopped on the `no_fatal_error` check, and that check was a
false positive: the fatal-error scan matched the `FOAM_SIGFPE` start-up banner
that OpenFOAM prints at every launch, not a runtime failure. The model proposed
`FAIL_SAFELY`, the validator returned `FAIL`, and the archived decision is
`REJECT`. That record is kept unchanged here and in `expected_result.json`.

After the scan was corrected, a deterministic reanalysis of the same run
directory (no solver re-run, no fields modified) returns `PASS_2D_FORWARD_STEP`.
The reanalysis record is in this repository under
[`demo/forward_step_2d/live_run_01/`](../../../demo/forward_step_2d/live_run_01/)
(`REANALYSIS.json`, `iteration_01/reanalysis/`).

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
was executed. The archived session records are in the Zenodo archive (https://doi.org/10.5281/zenodo.23148676) under the same relative path, `demo/forward_step_2d/live_run_01`; they are not in this repository.

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

The `message` field is the archived session's summary, written by the language
model (its `reasoning_summary`); it is not a deterministic measurement.

`expected_result.json` holds the same record in machine-readable form; a replay
that disagrees with it is a regression, not a new result.
