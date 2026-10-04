# Limitations

Read this before relying on anything else in the repository.

## What is registered

Two families, both inviscid compressible: the converging-diverging nozzle
(axisymmetric 5° wedge) and the two-dimensional forward-facing step. Their
accepted runs pass the family's registered checks, which is narrower than
physical validation; acceptance under a family contract is not a general
statement of CFD correctness. The turbulent cube is a diagnostic study run
outside the agent loop and is not routable. Everything else in the repository
(the airfoil mesh study, the backward-facing step, the 3-D forward step and the
CAD→Gmsh prototype stack) is not part of the CFD Forge paper.

Two registered families are **not** a general-purpose CFD agent. The set of
problems the system can carry from request to accepted result is small and
closed, and each new physics family needs its own scientific contract.

## Physics not covered

No viscous wall-bounded validation, no turbulence-model validation, no reacting
flow, no multiphase, no conjugate heat transfer, no moving geometry, no
compressible turbulence. The cube run did not satisfy its stationarity gate, and
its provisional comparison with ERCOFTAC centre-line profiles is not
satisfactory, so no experimental validation is claimed. Its wall treatment is
uncertain (cube-surface y+ median 24.7, range 2.8-96.5 at t* = 80).

## Geometry

No STEP/CAD family exists. The interface classifies and refuses CAD parts; see
`docs/cad_and_step_input.md`. Parametric geometry only, and only the shapes the
two registered families generate themselves.

## Statistical and numerical rigour

- Accepted runs are single-mesh verifications (`PASS_SINGLE_MESH` for the
  nozzle). The nozzle family rests on a frozen four-mesh LLM-free reference
  campaign (`docs/REFERENCE_VALIDATION.md`), but no grid-convergence index is
  reported. The step family has neither a registered cross-grid criterion nor a
  quantitative reference-field comparison.
- No uncertainty quantification, no sensitivity to numerical scheme, no repeated
  runs to separate solver noise from physical variation.
- The cube ran at one mesh resolution, and its 20-unit gate window contains only
  about two periods of the lateral oscillation: enough to show continued growth,
  too short for a statistical stationarity claim.

## The gates themselves

Deterministic authority is only as reliable as the checks it applies. In the
first step session (S1) a false-positive fatal-error check stopped a healthy run;
the archived verdict is REJECT, and a corrected reanalysis returns
`PASS_2D_FORWARD_STEP`. The step validator was changed twice during its campaign
(removing that false positive, and forming the mass-closure residual only within
a restart segment).

The cube stationarity gate (`cube-stationarity/1.0.0`, thresholds: 2% drift,
1.25 half-window growth ratio, 5% lateral magnitude, in
`src/families/cube/stationarity.py`) was registered retrospectively, on
28 September 2026, after the cube calculation had been run. The measured growth
ratio (2.10 against 1.25) is far from the bound, but the gate was not frozen
before the data existed.

## Development cases, not a held-out evaluation

All archived agent sessions are development cases: they were run while the
corresponding pipeline was being built, and no request was held out. The nozzle
requests were repeated as the feedback loop was revised. One step run (S7) was
completed in supervised resumed sessions after a mass-closure fix, so its
acceptance is not an unattended result.

## Model involvement and repeatability

- The paper's text calls used `gemini-3.5-flash-lite` at temperature 0 through
  the `google-genai` SDK. The multimodal field observer does not record its
  model; provider usage records show `gemini-3.6-flash` (its code default when
  `GEMINI_MODEL` is unset) in the step sessions and `gemini-3.5-flash-lite` in
  the nozzle sessions. Set `GEMINI_MODEL` explicitly when rerunning.
- Temperature 0 does not make the model repeatable: in the cube diagnosis, one
  of three identical calls gave a different diagnosis, and in the controller
  comparison the proposed corrective action varied across repeats at 5 of 18
  planted faults. Model outputs are not reproducible exactly.
- One repair call in nozzle session N4 (iteration 2) was not recorded; it is
  disclosed in the paper and excluded from the call counts.
- Token counts were not logged for the historical nozzle and step sessions.
- The default backend of `scripts/run_demo.py` and `scripts/run_agent.py` is
  deterministic keyword and recipe logic, a no-key demo mode; it is not the
  configuration of the paper's agent runs.
- The controller comparison uses one small model, replays archived states rather
  than new runs, and plants faults in one family. In the check-informed
  configuration the model never proposed acceptance contrary to a failed check,
  so the enforcement layer was not tested against a model that proposes an
  unjustified acceptance. In that comparison the fixed rule reached the same
  verdicts as CFD Forge; the model's contribution is interpretation, case
  construction and choice among admissible corrections, which the comparison does
  not measure.

## Reproducibility boundaries

- Replay is reproducible and needs no solver or key.
- The historical agent sessions ran from uncommitted development trees, so the
  release reproduces the workflow and the artifacts, not the historical agent
  execution byte for byte.
- Live execution requires OpenFOAM Foundation v14 (the paper used build
  `14-7b05503f98a8` under WSL 2); results on another distribution or version are
  not claimed to match.
- Contour rendering requires ParaView; video requires ffmpeg or pillow. Both
  report NOT_AVAILABLE rather than degrading silently.

## What this repository does not claim

1. That an arbitrary engineering prompt can be simulated.
2. That arbitrary CAD geometry can be meshed or solved.
3. That the cube case is a validated simulation of flow over a cube.
4. That the NACA0012 work reproduces NASA CFL3D results; no CFD was run, and it
   is not part of the paper.
5. That model diagnosis improves acceptance decisions over a fixed rule.
