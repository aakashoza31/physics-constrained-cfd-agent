# Demonstrated Cases

All three cases pass through the same parameterized prompt -> mesh -> CFD -> evidence -> LLM -> deterministic-validation pipeline.

## Case A: canonical reference with forced feedback demonstration

Geometry:

- inlet radius = 50.0 mm
- throat radius = 32.6 mm
- exit radius = 35.4 mm

Operating conditions:

- p0 = 200 kPa
- T0 = 300 K
- ambient metadata = 30 kPa

For the feedback demonstration, the first CFD horizon is deliberately limited to 0.001 s.

Iteration 1:

- solver completes normally
- 17/20 deterministic checks pass
- failed checks: `steady_mass_balance`, `monitors_stationary`, `fields_stationary`
- numerical state remains physically admissible
- visual observation completes
- LLM diagnosis: `UNCONVERGED`
- LLM action: `CONTINUE_RUN`
- deterministic action validator: approved

Iteration 2:

- existing OpenFOAM state continues from 0.001 s to 0.006 s
- new numerical diagnostics and new field images are generated
- all deterministic checks pass
- LLM diagnosis: `ACCEPTABLE`
- LLM action: `ACCEPT`
- deterministic action validator: approved
- final scientific verdict: `PASS_SINGLE_MESH`

This case demonstrates the actual feedback loop.

## Case B: geometry transfer

Only one engineering variable is changed from Case A:

- exit radius: 35.4 mm -> 37.0 mm

Reservoir conditions remain 200 kPa and 300 K.

Observed behavior:

- mesh generated and validated automatically
- 2,112-cell structured wedge mesh
- OpenFOAM runs to 0.006 s in serial
- 20/20 deterministic checks pass
- multimodal visual observation examines 5 generated images
- LLM returns `ACCEPTABLE -> ACCEPT`
- deterministic validator returns `PASS_SINGLE_MESH`
- feedback controller stops after 1 iteration because no intervention is needed

## Case C: operating-condition transfer

Geometry returns to the canonical dimensions. One operating variable changes:

- reservoir total pressure: 200 kPa -> 220 kPa

Observed behavior:

- mesh generated and validated automatically
- 2,112-cell structured wedge mesh
- OpenFOAM runs to 0.006 s in serial
- 20/20 deterministic checks pass
- multimodal visual observation examines 5 generated images
- LLM returns `ACCEPTABLE -> ACCEPT`
- deterministic validator returns `PASS_SINGLE_MESH`
- feedback controller stops after 1 iteration

## What the three cases establish

The campaign demonstrates:

1. an actual evidence-driven feedback action when the first CFD state is insufficient (Case A),
2. nearby geometry transfer through the same pipeline (Case B), and
3. nearby operating-condition transfer through the same pipeline (Case C).

It does **not** establish that every geometry or condition inside the software scope gate has validated CFD accuracy. The parameter gate prevents unsupported requests from silently running; it is not a substitute for a broader validation campaign.
