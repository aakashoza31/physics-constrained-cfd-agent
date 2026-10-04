# Parameter guide for new nozzle requests

This page covers the nozzle family only. Forward-facing-step requests are
interpreted into `src/pipeline/forward_step_2d/spec.py` (inlet Mach number, step
height and step position; unstated fields are filled from family defaults) and
screened by the 14-check scope gate in `src/reasoning/forward_step_scope_gate.py`;
example requests are in `examples/forward_step_2d/`.

The agent can parse nearby natural-language nozzle requests and translate them into the same parameterized CFD pipeline.

Two different ideas must be kept separate:

1. **Demonstrated transfer:** what has actually been exercised in the nozzle Case A/B/C sessions.
2. **Software scope gate:** hard bounds used to refuse obviously unsupported requests.

Passing the software scope gate does not mean the entire range has been experimentally or numerically verified.

## Demonstrated neighborhood

The current public evidence directly demonstrates:

- exit radius: 35.4 mm and 37.0 mm at p0 = 200 kPa
- reservoir total pressure: 200 kPa and 220 kPa on the canonical geometry
- T0 = 300 K
- ambient metadata = 30 kPa
- scale = 1.0 (2,112 cells)
- wedge angle = 5 deg
- maxCo = 0.4
- internal inviscid supersonic outlet branch

For a new research experiment, staying close to this neighborhood is the scientifically conservative choice.

## Deterministic software gate

The current gate in `src/reasoning/nozzle_scope_gate.py` enforces:

| Parameter | Current software bound |
| --- | ---: |
| throat radius | 0.020 to 0.050 m |
| inlet radius | 0.030 to 0.080 m |
| exit radius | 0.020 to 0.070 m |
| exit/throat area ratio | 1.02 to 2.50 |
| reservoir total pressure | 120 to 400 kPa |
| reservoir total temperature | 250 to 400 K |
| ambient pressure metadata | 10 to 100 kPa |
| nozzle pressure ratio p0/p_ambient | 2 to 20 |
| integration horizon | 0.001 to 0.020 s |
| mesh scale | 0.5 to 4.0 |
| wedge angle | 1 to 10 deg |
| maximum Courant number | 0.05 to 0.5 |

Additional requirements:

- throat must remain the minimum radius
- gas must remain gamma = 1.4, R = 287 J/(kg K)
- ambient pressure cannot be imposed as the computational exit pressure
- the deterministic quasi-1D regime screen must support the fully supersonic outlet branch

## Natural-language template

Copy `examples/nozzle_e2e/PROMPT_TEMPLATE.txt` and replace the bracketed values.

The prompt should explicitly provide:

- inlet radius
- throat radius
- exit radius
- five axial segment lengths
- reservoir total pressure
- reservoir total temperature
- ambient/back-pressure metadata
- gamma and R
- inviscid Euler physics
- adiabatic slip walls

Keep the instruction that analytical target values must not be exposed to the CFD reasoning agent.

## Configuration template

`configs/nozzles/case_template.yaml` provides the same inputs in structured form for readers who want to understand the internal representation.

The natural-language prompt is the public agent entry point. `scripts/run_nozzle_feedback.py --prompt-file ...` runs a custom in-scope prompt through the same closed-loop controller. The YAML template is documentation and a convenient representation for extending the repository.

## Recommended workflow for a new case

1. Change one or a small number of parameters near the demonstrated A/B/C neighborhood.
2. Run the interpretation/scope path first.
3. Confirm the deterministic scope gate reports `IN_SCOPE`.
4. Run the closed-loop CFD agent with visual evidence enabled.
5. Inspect `feedback_summary.json`, per-iteration validation JSON, and visual observations.
6. Do not promote a new case to a reference benchmark without a dedicated mesh/timestep/sensitivity study.

## Run a custom in-scope prompt through the feedback loop

```powershell
python .\scripts\run_nozzle_feedback.py `
    --prompt-file .\examples\nozzle_e2e\PROMPT_TEMPLATE.txt `
    --out .\demo\runs\custom_nozzle `
    --end-time 0.006 `
    --max-end-time 0.020 `
    --feedback-increment 0.005 `
    --max-iterations 4 `
    --max-diagnostic-requests 2 `
    --require-visuals
```

The output label for an arbitrary prompt is `case_from_prompt`. The deterministic scope gate still has final authority on whether the requested parameter combination is admitted.
