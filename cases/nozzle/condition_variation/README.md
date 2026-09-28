# Operating-condition variation

**Family:** `nozzle` &nbsp;|&nbsp; **Case:** `condition_variation` &nbsp;|&nbsp;
**Original id:** `case_C_conditions` &nbsp;|&nbsp; **Archived verdict:** `ACCEPT`

Same geometry, altered operating conditions.

## Reproduce

```bash
./reproduce.sh              # replay the archived evidence, no solver
./reproduce.sh --live       # re-execute with OpenFOAM Foundation v14
```

```powershell
.\reproduce.ps1             # replay
.\reproduce.ps1 -Live       # re-execute
```

Replay reads the archived evidence under `demo/nozzle_e2e/case_C_conditions` and re-derives the
deterministic decision from it. It never claims a solver was executed.

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
