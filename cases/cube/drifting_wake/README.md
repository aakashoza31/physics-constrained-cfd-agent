# Surface-mounted cube with a drifting lateral wake

**Family:** `cube` &nbsp;|&nbsp; **Case:** `drifting_wake` &nbsp;|&nbsp;
**Original id:** `family3_baseline_compact` &nbsp;|&nbsp; **Archived verdict:** `REJECT`

Diagnostic study of a 3-D URANS (k-omega SST) surface-mounted cube, run outside the agent loop. The stationarity gate `cube-stationarity/1.0.0` was registered retrospectively and applied to the archived force history; it returns `STILL_DEVELOPING`, so the decision is `REJECT`.

## What this case is

- The run was executed outside the agent loop (23-24 September 2026). No model
  proposed or executed an action during the run.
- The gate `cube-stationarity/1.0.0` was registered retrospectively, on
  28 September 2026, and applied to the archived force history over the window
  t* = 59.98-79.98.
- Drag drift over the window is 0.075 % and the mean lateral force is 0.063 % of
  the drag, but the half-window ratio of mean |Fz| is 2.10 against a limit of
  1.25, so the gate returns `STILL_DEVELOPING` and the decision is `REJECT`.
- Over complete cycles of the lateral oscillation the amplitude grew by 209 %,
  137 % and 113 %: the growth rate is declining but the amplitude has not
  saturated. Between the block means for t* = 60-70 and 70-80 the drag changes by
  0.04 % while the RMS lateral force rises by 110 %.
- A separate model diagnosis of this evidence (1 October 2026, three calls) is in
  `evidence/cube/drifting_wake/llm_diagnosis/`. The validator approved all three
  proposals (`CONTINUE_RUN`, `FAIL_SAFELY`, `CONTINUE_RUN`); none was `ACCEPT`.

## Reproduce

```bash
./reproduce.sh              # replay the archived evidence, no solver
```

```powershell
.\reproduce.ps1             # replay
```

Live execution is refused for this family; only replay is available.

Replay re-derives the deterministic decision from the archived record in
`expected_result.json` (and any series in `reference/`). It never claims a solver
was executed. The archived run is in the Zenodo archive (DOI to be added on release) under `CFD_Verification_Package_20260929/03_cube` (originally `handoff/CFD_Agent_Handoff_20260924_1610/family3_baseline_compact`); it is not in this repository.

## Archived outcome

```json
{
  "verdict": "REJECT",
  "archived_status": "RETROSPECTIVE_GATE_STILL_DEVELOPING",
  "rejected_on": "STILL_DEVELOPING",
  "failed_checks": [
    "lateral_force_growth"
  ],
  "stationarity": {
    "gate_version": "cube-stationarity/1.0.0",
    "status": "STILL_DEVELOPING",
    "passed": false,
    "window": {
      "start": 59.980000000000004,
      "end": 79.98,
      "samples": 500
    },
    "measured": {
      "mean_fx": 0.706209298654447,
      "mean_fy": 0.2450782018170498,
      "mean_fz": 0.00044205078685453616,
      "drift_fraction": {
        "fx": 0.0007529082884745507,
        "fy": 0.0005290983096436084,
        "fz": 0.004620392788751231
      },
      "lateral_growth_ratio": 2.098378164488468,
      "lateral_relative_magnitude": 0.0006259486921183044,
      "mean_abs_fz_first_half": 0.0018326531209671001,
      "mean_abs_fz_second_half": 0.003845599292119006,
      "samples": 500
    },
    "thresholds": {
      "force_drift_fraction_max": 0.02,
      "lateral_growth_ratio_max": 1.25,
      "lateral_relative_max": 0.05,
      "assessment_window": 20.0
    },
    "failures": [
      "lateral_force_growth"
    ],
    "margins_relative_to_threshold": {
      "lateral_growth_ratio": 1.6787025315907744,
      "max_drift_fraction": 0.23101963943756154,
      "lateral_relative": 0.012518973842366088
    },
    "note": "the streamwise force may look settled while a lateral mode grows; this gate fails on the growth, not on the drag"
  },
  "solver_invoked_in_archive": true,
  "note": "the solver ran to the requested end time and reported no numerical failure; the rejection is on flow development"
}
```

`expected_result.json` holds the same record in machine-readable form; a replay
that disagrees with it is a regression, not a new result.
