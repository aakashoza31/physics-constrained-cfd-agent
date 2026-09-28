# Family Register

Machine-readable source of truth: `src/families/registry.py`
(`install_standing_register()`). Regenerate this table with
`python3 scripts/run_family.py register`.

| Family | Status | Physics class | Routable | Notes |
|---|---|---|---|---|
| `nozzle` | **CORE** / frozen | compressible inviscid Euler | yes | Validated against quasi-1D isentropic theory. Adapter **UNVERIFIED** in the cloud working copy — see blocker B1. |
| `forward_step_2d` | **CORE** / frozen | compressible inviscid Euler | yes | OpenFOAM benchmark reproduction + controlled variations + a safe-rejection case. Acceptance criteria fully registered. |
| `airfoil` | **CORE-PENDING** | incompressible / low-Mach RANS | **no** | 2D NACA0012, SST. Scientific recipe **unregistered** — 20 open constants. Structurally cannot ACCEPT. |
| `backward_step` | **CORE-PENDING** | incompressible RANS | **no** | 2D backward-facing step, SST. Scientific recipe **unregistered** — 19 open constants. Structurally cannot ACCEPT. |
| `square_duct` | **SUPPORTING** | incompressible RANS | **no** | Cross-version incompatibility evidence. Preserved, not deleted. |
| `cube` | **NONACCEPTED** | incompressible RANS | **no** | Stationarity stress test / safe-rejection evidence. |

## Physics-class count, stated honestly

Four core families span **two** physics classes: compressible inviscid Euler
(`nozzle`, `forward_step_2d`) and incompressible/low-Mach turbulent RANS
(`airfoil`, `backward_step`). Paper claims about architecture generality should
say "four families across two physics classes", not imply four independent
classes. `nozzle` and `forward_step_2d` further share a solver lineage and
differ by regime (smooth isentropic expansion vs. discontinuity capture).

## `square_duct` — why it is SUPPORTING and not CORE

Evidence root:
`C:\Users\Aakash\Documents\Codex\2026-09-20\i-am-attaching-a-full-project\outputs\family3_square_duct_audit`

The McConkey `kOmegaSST` square-duct case is OpenCFD v2006; the production
environment is OpenFOAM Foundation v14. The compatibility audit found that v14
`omegaWallFunction` behaviour is not equivalent to the v2006 default
`binomial2` behaviour, that the omega wall formula and near-wall production
treatment differ, and that further semantic differences exist (e.g. pressure
relaxation configuration). A dictionary conversion from v2006 to v14 therefore
cannot be defended as the same numerical experiment.

**The validation protocol was not the problem.** The original McConkey run
passes our residual and forcing-stationarity gates. What failed is the
benchmark's cross-version implementation dependence.

Retained as: evidence that **matching turbulence-model names across CFD
versions does not imply equivalent numerical physics.** This is a usable
negative result, and it is the reason the register records a `physics` string
per family rather than only a model name.

## `cube` — why it is NONACCEPTED

The solver looked numerically healthy while a lateral mode continued to grow,
and the deterministic stationarity gate rejected the run. Retained as a
stationarity stress test and a safe-rejection example. Evidence path is `TODO`
and must not block implementation.

## Status semantics

- **CORE** — frozen, validated, routable, acceptance criteria registered.
- **CORE-PENDING** — visible in the register and **inspectable** (its adapter
  and recipe construct, so `run_family.py recipe <name>` works), but **not
  executable**: the recipe carries unresolved acceptance constants, so nothing
  it produced could be accepted. `registry.adapter(name, for_execution=True)`
  raises `PermissionError`, and the router refuses any proposal naming it.
- **SUPPORTING** — preserved evidence, **not routable**.
- **NONACCEPTED** — preserved rejection evidence, **not routable**.

**Only `CORE` is routable for execution.** The router refuses any proposal
naming a non-executable family with `REJECT / NO_REGISTERED_FAMILY`, and the
refusal reason distinguishes a pending recipe from retained evidence.

Keyword support is nevertheless computed against the **whole** register, so a
request straddling an executable and a pending family is recognised as
ambiguous rather than collapsing onto whichever one happens to be executable.
That is what stops "turbulent step flow ... reattachment length" from routing
to the inviscid `forward_step_2d` family.
