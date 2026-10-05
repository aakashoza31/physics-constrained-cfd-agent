# Operating-condition variation

**Family:** `nozzle` &nbsp;|&nbsp; **Case:** `condition_variation` &nbsp;|&nbsp;
**Original id:** `case_C_conditions` &nbsp;|&nbsp; **Archived verdict:** `ACCEPT`

Same geometry, altered operating conditions (paper ledger N3: p0=220 kPa; repeated as N8).

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
was executed. The archived session records are in the Zenodo archive (https://doi.org/10.5281/zenodo.23148676) under the same relative path, `demo/nozzle_e2e/case_C_conditions`; they are not in this repository.

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
