# Forward-facing step at Mach 2.0

**Family:** `forward_step` &nbsp;|&nbsp; **Case:** `mach20_canonical` &nbsp;|&nbsp;
**Original id:** `case_B_mach20` &nbsp;|&nbsp; **Archived verdict:** `ACCEPT`

Canonical Mach-2 run of the registered 2-D forward-step family (paper ledger S2): Mach 2, h=0.2, step at x=0.6; `PASS_2D_FORWARD_STEP` -> `ACCEPT` in one iteration.

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
was executed. The archived session records are in the Zenodo archive (DOI to be added on release) under the same relative path, `demo/forward_step_2d/case_B_mach20`; they are not in this repository.

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
