# Step height 0.30, step at x=0.6

**Family:** `forward_step` &nbsp;|&nbsp; **Case:** `step_height_030_x060` &nbsp;|&nbsp;
**Original id:** `case_F_step030` &nbsp;|&nbsp; **Archived verdict:** `REJECT`

Step-height variation (paper ledger S5): Mach 3, h=0.3, step at x=0.6, run to t=4. The compression front was displaced toward the inlet, to x=0.025, and no front could be measured; the model proposed `FAIL_SAFELY`, the validator returned `FAIL` (`compression_front_measurable`), and the decision is `REJECT`. The run was preserved and rejected rather than tuned.

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
was executed. The archived session records are in the Zenodo archive (https://doi.org/10.5281/zenodo.23148676) under the same relative path, `demo/forward_step_2d/case_F_step030`; they are not in this repository.

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

The `message` field is the archived session's summary, written by the language
model (its `reasoning_summary`); it is not a deterministic measurement.

`expected_result.json` holds the same record in machine-readable form; a replay
that disagrees with it is a regression, not a new result.
