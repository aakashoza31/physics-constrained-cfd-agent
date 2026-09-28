# Family registration protocol

A *family* is a closed class of CFD problems with one registered scientific
contract. Adding a family means declaring that contract; it never means adding a
branch to the agent.

## What a family must declare

1. **Capabilities** — `src/families/capabilities.py`:

```yaml
geometry_inputs:
  parametric: true
  step: false
  step_note: "why STEP is not accepted"

physics:
  compressible: true
  turbulent: false
  transient: false
  dimensionality: "2-D planar"
  model: "inviscid compressible (Euler)"

allowed_actions: [ACCEPT, CONTINUE_RUN, REFINE_MESH, REQUEST_CLARIFICATION,
                  REJECT_UNSUPPORTED, FAIL_SAFELY]
characteristic_dimension: throat_radius
status: ACCEPTED          # ACCEPTED | SUPPLEMENTARY | NOT_IMPLEMENTED
```

2. **A recipe** — `FamilyRecipe`: the benchmark reference, the numerics, the
   admissible envelope, the acceptance tolerances and the reference values. Any
   constant not yet justified is written `TODO(...)`, and a recipe with an
   unresolved acceptance constant **can never produce ACCEPT**.

3. **An adapter** — `check_scope`, `build_case`, `run_case`, `collect_evidence`,
   `validate`, `diagnose`, `deterministic_proposal`, `execute_action`.

4. **Registered cases** — one directory per case under `cases/<family>/`.

## Status semantics

| Status | Routable | Meaning |
|---|---|---|
| `ACCEPTED` | yes | validated, may execute and may be accepted |
| `SUPPLEMENTARY` | no | preserved evidence only; never executed for acceptance |
| `NOT_IMPLEMENTED` | no | declared for completeness, deliberately not built |

Only `ACCEPTED` families can reach a solver through the agent. Supplementary
studies remain reproducible without being presented as validated families.

## Registered families

| Family | Status | Physics | STEP | Cases |
|---|---|---|---|---|
| `nozzle` | ACCEPTED | compressible Euler, 2-D | no | 3 |
| `forward_step_2d` | ACCEPTED | compressible Euler, 2-D transient | no | 8 |
| `cube` | SUPPLEMENTARY | incompressible RANS, 3-D transient | no | 1 |
| `airfoil` | SUPPLEMENTARY | incompressible RANS, 2-D | no | 1 (mesh rejection, CFD_NOT_RUN) |
| `backward_step` | NOT_IMPLEMENTED | — | no | 0 |

See `docs/adding_a_family.md` for the step-by-step.
