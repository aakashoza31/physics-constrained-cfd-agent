# Geometry variation

**Family:** `nozzle` &nbsp;|&nbsp; **Case:** `geometry_variation` &nbsp;|&nbsp;
**Original id:** `case_B_geometry` &nbsp;|&nbsp; **Archived verdict:** `ACCEPT`

Same physics, altered nozzle geometry (paper ledger N2: exit radius 37 mm; repeated as N7).

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
was executed. The archived session records are in the Zenodo archive (DOI to be added on release) under the same relative path, `demo/nozzle_e2e/case_B_geometry`; they are not in this repository.

## Archived outcome

```json
{
  "verdict": "ACCEPT",
  "archived_status": "PASS_SINGLE_MESH",
  "failed_checks": [],
  "llm_diagnosis": "ACCEPTABLE",
  "llm_proposed_action": "ACCEPT",
  "llm_action_approved": true,
  "authority": "deterministic validator (src/pipeline/nozzle/validate.py)",
  "solver_invoked_in_archive": true
}
```

`expected_result.json` holds the same record in machine-readable form; a replay
that disagrees with it is a regression, not a new result.
