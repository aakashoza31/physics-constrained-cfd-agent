# Physics scope and boundary conditions: nozzle family

This page covers the nozzle family. For the two-dimensional forward-facing-step
family see the note at the end.

## Supported physical problem

The registered problem is internal flow through an axisymmetric conical converging-diverging nozzle.

The current pipeline assumes:

- calorically perfect air
- gamma = 1.4
- gas constant R = 287 J/(kg K)
- inviscid compressible Euler equations
- adiabatic slip walls
- axisymmetric wedge representation
- choked flow with a supersonic computational outlet branch

The computational domain ends at the nozzle exit. There is no external plume/jet domain in the demonstrated cases.

## Canonical geometry

| Quantity | Value |
| --- | ---: |
| inlet radius | 0.0500 m |
| throat radius | 0.0326 m |
| exit radius | 0.0354 m |
| inlet straight length | 0.050 m |
| converging length | 0.100 m |
| throat length | 0.010 m |
| diverging length | 0.120 m |
| outlet straight length | 0.050 m |

Case B changes only the exit radius to 0.0370 m.

## Operating conditions

Canonical / Case A:

- reservoir total pressure p0 = 200 kPa
- reservoir total temperature T0 = 300 K
- ambient pressure metadata = 30 kPa

Case C changes only reservoir total pressure to 220 kPa.

## Inlet boundary treatment

The OpenFOAM case uses reservoir-style inlet information:

- total pressure
- total temperature
- direction-aware velocity treatment

The axial inlet velocity is allowed to respond to the solution rather than being prescribed as a fixed arbitrary velocity.

## Wall boundary treatment

Walls are inviscid and adiabatic, represented with slip conditions. No boundary-layer or wall-heat-transfer physics is included.

## Outlet boundary treatment

The computational outlet uses an extrapolative / pressure-free treatment appropriate only when the computed outlet is fully outward and supersonic.

The nominal 30 kPa ambient value is **not imposed as a fixed static pressure at the computational outlet** in the demonstrated underexpanded cases.

The deterministic validator checks the computed outlet regime before acceptance.

## Why this matters

For a supersonic outflow, imposing an arbitrary downstream static pressure directly at the internal computational outlet can over-constrain the hyperbolic problem. The architecture therefore treats ambient pressure as regime metadata and verifies outlet admissibility from the computed solution.

## Numerical method

The demonstrated CFD recipe uses:

- OpenFOAM Foundation v14
- `foamRun` with `shockFluid`
- Kurganov fluxes
- Minmod reconstruction
- Euler time integration
- adjustable timestep
- maxCo = 0.4 for A/B/C
- structured wedge mesh
- explicit per-cell quasi-1D startup state

The startup fields are read back before execution to verify that the intended initialization was actually written.

## What is not covered

The registered checks and the reference refinement campaign do not establish accuracy for:

- viscous wall layers
- turbulence
- heat transfer
- real-gas thermodynamics
- arbitrary back-pressure branches
- normal shocks inside the nozzle outside the declared regime
- external supersonic jets / shock cells
- non-axisymmetric three-dimensional flow
- arbitrary nozzle families

## Forward-facing-step family (note)

The step family is a 2-D planar, transient, inviscid compressible flow
(`shockFluid`) with a Mach-2 canonical configuration (the Mach-3 case is the
OpenFOAM tutorial recipe), Δx = Δy = 0.0125 (16,128 cells for h = 0.2,
x = 0.6). Its scope gate has 14 checks (`src/reasoning/forward_step_scope_gate.py`);
acceptance uses 17 hard checks and 3 compression checks with a storage-aware mass
closure limit of 1e-6 and no stationarity criterion
(`src/pipeline/forward_step_2d/validate.py`). Its parameters are defined in
`src/pipeline/forward_step_2d/spec.py`; see the CFD Forge paper's setup appendix
for the full specification.
