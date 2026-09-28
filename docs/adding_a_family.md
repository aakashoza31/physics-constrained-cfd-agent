# Adding a family

The agent contains no family-specific branches. Adding a family is five files and
a case directory; nothing in `src/agent/` or `src/authority/` changes.

## 1. Declare capabilities

`src/families/capabilities.py` — add a `FamilyCapabilities` entry. Be honest
about `geometry_inputs`: if there is no STEP path, `step: false` and say why in
`step_note`. The matcher enforces that declaration.

## 2. Write the recipe

`src/families/<name>/recipe.py` — a `FamilyRecipe` with the benchmark reference,
numerics, bounds, tolerances, reference values and the allowed action
vocabulary. Any constant you cannot yet justify is `TODO("name", "why")`. A
recipe with an unresolved acceptance constant can never return ACCEPT, so an
incomplete family is safe by construction.

## 3. Write the adapter

`src/families/<name>/adapter.py` implementing the adapter protocol:
`check_scope`, `build_case`, `run_case`, `collect_evidence`, `validate`,
`diagnose`, `deterministic_proposal`, `allowed_actions`, `execute_action`,
`readiness`.

## 4. Write the gates

The gates are the family's scientific contract in code: mesh quality,
conservation, convergence, stationarity, validation. They must be pure functions
of evidence, and they must carry their thresholds as module constants with the
reasoning written down. `src/families/cube/stationarity.py` is a compact worked
example.

## 5. Register the cases

```
cases/<family>/<case>/
    case.yaml              # id, original id, evidence pointer, config
    README.md              # what it demonstrates, how to reproduce
    expected_result.json   # the result a replay must reproduce
    reference/             # small extracted series, not raw fields
    reproduce.sh / .ps1
```

`scripts/build_case_library.py` regenerates these from archived evidence, so the
status a case advertises is the status its evidence records.

## 6. Add tests

At minimum: the recipe registers, the capability declaration matches the
implementation, the gates reject a known-bad evidence bundle, and a replay of
each registered case reproduces `expected_result.json`.

## What you must not do

- Do not add a branch on family name in `src/agent/` or `src/authority/`.
- Do not widen a gate to make a case pass.
- Do not declare a geometry input the family cannot actually process.
- Do not register a case whose `expected_result.json` was written by hand rather
  than derived from evidence.
