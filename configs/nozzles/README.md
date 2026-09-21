# Three-case nozzle E2E campaign

## Case A — canonical reference

Purpose:
Reproduce the validated canonical nozzle through the new
parameterized end-to-end pipeline.

Geometry:
- inlet radius: 0.0500 m
- throat radius: 0.0326 m
- exit radius: 0.0354 m

Reservoir:
- p0 = 200 kPa
- T0 = 300 K

This is the scientific anchor case.

---

## Case B — geometry transfer

Purpose:
Test whether the SAME CFD recipe and validation pipeline can handle
a nearby unseen geometry without manual OpenFOAM repair.

Change relative to A:
- exit radius: 0.0354 m -> 0.0370 m

Everything else remains in the same declared physics family.

---

## Case C — operating-condition transfer

Purpose:
Test whether the SAME CFD recipe and validation pipeline can handle
a nearby reservoir-condition change.

Change relative to A:
- p0: 200 kPa -> 220 kPa

Geometry and T0 remain unchanged.

---

## Scientific scope

Supported demo scope:

- internal nozzle
- axisymmetric wedge representation
- inviscid Euler flow
- ideal-gas air
- adiabatic slip walls
- choked/supersonic outlet branch
- pressure-free outlet validated by computed supersonicity

The 30 kPa ambient pressure is external-environment metadata.
It must NOT automatically be imposed as a fixed static pressure at
the computational outlet.

Case acceptance remains deterministic.
The LLM may interpret requests and explain outcomes, but it does not
decide whether conservation, stationarity, positivity, mesh quality,
or outlet admissibility passed.
