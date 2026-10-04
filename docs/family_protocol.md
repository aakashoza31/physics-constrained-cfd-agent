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
  model: "inviscid compressible (Euler), shockFluid"

allowed_actions: [ACCEPT, CONTINUE_RUN, EXTEND_END_TIME, REDUCE_MAX_CO,
                  REFINE_MESH, REBUILD_FROM_VALIDATED_SPEC,
                  REQUEST_CLARIFICATION, REJECT_UNSUPPORTED, FAIL_SAFELY]
characteristic_dimension: step_height
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
| `ACCEPTED` | yes | registered: may execute, and a run may be accepted when it passes the registered checks |
| `SUPPLEMENTARY` | no | preserved evidence only; never executed for acceptance |
| `NOT_IMPLEMENTED` | no | declared for completeness, deliberately not built |

Only `ACCEPTED` (registered) families can reach a solver through the agent.
Supplementary studies remain reproducible without being presented as registered
families. Registration is not a claim of physical validation.

## Families in the register

| Family | Status | Physics | STEP | Cases |
|---|---|---|---|---|
| `nozzle` | ACCEPTED (registered) | inviscid compressible, axisymmetric 5° wedge | no | 3 |
| `forward_step_2d` | ACCEPTED (registered) | inviscid compressible, 2-D planar, transient | no | 8 |
| `cube` | SUPPLEMENTARY (diagnostic study, not part of the agent loop) | URANS k-ω SST, 3-D transient | no | 1 |
| `airfoil` | SUPPLEMENTARY (not part of the paper) | incompressible RANS, 2-D | no | 1 (mesh rejection, CFD_NOT_RUN) |
| `backward_step` | NOT_IMPLEMENTED (not part of the paper) | — | no | 0 |

The action vocabularies of the two registered families are listed in
`docs/architecture_detail.md`.

See `docs/adding_a_family.md` for the step-by-step.
