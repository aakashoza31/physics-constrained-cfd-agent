# Physics-Constrained Autonomous CFD Agent — Master Brief

Frozen scope of record. Supersedes brief statements held only in chat.

**Central claim.** A physics-constrained LLM agent can autonomously construct,
execute, diagnose and validate CFD simulations within prevalidated flow
families, while deterministic scientific gates restrict corrective actions and
prevent scientifically unacceptable outputs from being silently accepted.

**Not claimed:** universal or general-purpose CFD.

## Authority split

The LLM may: interpret the request, route it to a registered family, extract
parameters, diagnose solver behaviour, propose a bounded corrective action, and
explain results. Every one of these is advisory.

The deterministic layer owns: family admissibility, mesh quality, BC/physics
consistency, convergence/stationarity, conservation and numerical health,
quantitative benchmark checks, the permitted action set, and the final
`ACCEPT` / `CORRECT-AND-RERUN` / `INCONCLUSIVE` / `REJECT`.

This is enforced structurally, not by convention. `src/orchestrator/loop.py`
passes the LLM's `Proposal` to the family's deterministic validator and takes
the decision from the validator. In the `gates_off` ablation the ruling is
still computed and written to the ledger — so the ablation measures what the
gates *would* have caught — but is not applied.

## Mandatory per-family workflow

1. Select an authoritative, previously validated benchmark.
2. Reproduce the canonical case manually; verify against the reference.
3. Freeze the recipe: geometry rules, mesh strategy, physics/model, BCs,
   numerics, convergence criteria, validation quantities, allowed actions.
4. Have the agent reproduce the same canonical case from a prompt.
5. Only then, controlled variations inside that family.
6. Record the complete action/diagnostic/provenance trace.

Physics is never invented or substituted before baseline reproduction. If the
published reference uses SST, the canonical case uses SST. Exploratory work
with other closures is retained separately and does not define a family.

## The registration guarantee

A family's scientific constants live in a declarative `FamilyRecipe`. Any
constant not yet justified by an authoritative reference is declared
`TODO(name, note)`.

- An unresolved **acceptance-critical** constant (`tolerances`,
  `reference_values`, `numerics`, `bounds`) makes the family structurally
  unable to return `ACCEPT`: the orchestrator downgrades to `INCONCLUSIVE`
  with reason `CRITERION_NOT_REGISTERED`.
- An unresolved **capability-gated** constant (`capability_criteria[action]`)
  disables that one optional action without blocking acceptance of runs that
  never used it. This is what lets a frozen, already-validated family keep
  accepting while a newer capability remains unregistered.

The guarantee is only worth something if nobody resolves a `TODO` with a
plausible-looking number.

## Bounded `REFINE_REGION`

The LLM may propose the action name and, optionally, a region drawn from a
**closed vocabulary** the family declares. It may not name cells, coordinates,
refinement factors, levels, or any dictionary entry, and it never reaches the
dictionary-writing code.

Deterministic family code owns: whether under-resolution exists, which cells a
named region covers, how many levels apply, whether the projected cell count is
admissible, and whether the refined mesh passes `checkMesh`. Region *location*
is coordinate arithmetic and is registered. Region *under-resolution* is
science and is `TODO` for every family, so the action currently refuses rather
than guesses.

## Failed and rejected cases

Preserved and reported, never silently tuned until they appear successful. See
`docs/FAMILY_REGISTER.md` for `square_duct` and `cube`.

## Paper questions

1. Can the agent reproduce validated canonical CFD workflows from user
   specifications?
2. Can one common architecture operate across qualitatively different CFD
   physics families? *(See the physics-class count in the family register —
   four families, two classes. Only the two CORE families are executable
   today.)*
3. Can the agent adapt frozen recipes to controlled geometry and
   operating-condition variations?
4. Can it diagnose problems and select bounded corrective actions?
5. Can deterministic gates prevent plausible-looking but invalid CFD from being
   accepted? *(Measured by `src/eval/harness.py: gates_off_comparison` over the
   seeded faults in `src/eval/faults.py`.)*

## Architecture map

| Concern | Module |
|---|---|
| Shared contract, decisions, TODO sentinel | `src/families/base.py` |
| Declarative recipe + registration guarantee | `src/families/recipe.py` |
| Family register and statuses | `src/families/registry.py` |
| Bounded local refinement | `src/families/refine_region.py` |
| The one orchestrator | `src/orchestrator/loop.py` |
| Experiment modes | `src/orchestrator/modes.py` |
| Append-only provenance | `src/orchestrator/ledger.py` |
| Router | `src/router/route.py` |
| Experiments and fault suite | `src/eval/harness.py`, `src/eval/faults.py` |
| Opt-in CLI (legacy runners untouched) | `scripts/run_family.py` |

## Portability

Provenance and hash documents serialize relative paths with
`Path.relative_to(...).as_posix()`, never `str(Path)`. `str()` renders the host
separator, so a Windows run would key `template_hashes.json` with
`system\fvSchemes` and stop comparing equal to the canonical representation.
Hashed bytes are unaffected; only serialization was ever at issue.
