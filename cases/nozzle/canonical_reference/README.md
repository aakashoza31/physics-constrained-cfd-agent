# Canonical converging-diverging nozzle

**Family:** `nozzle` &nbsp;|&nbsp; **Case:** `canonical_reference` &nbsp;|&nbsp;
**Original id:** `case_A_reference` &nbsp;|&nbsp; **Archived verdict:** `ACCEPT`

Canonical reference case (`PASS_SINGLE_MESH` under the registered contract), paper ledger N1: reference nozzle, p0=200 kPa, 6 ms. The related sessions N4, N5 and N6 repeat this request with a 1 ms initial horizon.

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
was executed. The archived session records are in the Zenodo archive (DOI to be added on release) under the same relative path, `demo/nozzle_e2e/case_A_reference`; they are not in this repository.

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
