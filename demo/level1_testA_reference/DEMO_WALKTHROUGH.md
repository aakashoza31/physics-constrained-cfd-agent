# Level-1 Autonomous CFD Demo

## Demonstration

Engineering prompt
-> geometry
-> mesh
-> deterministic physics / mesh checks
-> OpenFOAM
-> numerical and visual evidence
-> theory-blind Gemini CFD reasoning
-> proposed action
-> deterministic Python validator
-> approved CFD action
-> post-hoc quasi-1D comparison

## Autonomous trajectory

### 1.000 ms

Gemini diagnosis:

UNCONVERGED

Proposed action:

CONTINUE_RUN

Confidence:

high

Deterministic validator:

APPROVED

The existing OpenFOAM solution and mesh were continued without remeshing.

### 1.100 ms

Gemini diagnosis:

UNCONVERGED

Proposed action:

CONTINUE_RUN

Confidence:

high

Deterministic validator:

APPROVED

The same case was autonomously continued to 1.200 ms.

No geometry regeneration, remeshing, or human CFD intervention occurred
during the two continuation actions.

## Final monitored state

Time:

1.200 ms

Exit Mach:

CFD: 1.48790
Theory: 1.50440
Error: approximately -1.10 %

Exit pressure:

CFD: 54.725 kPa
Theory: 54.134 kPa
Error: approximately +1.09 %

Exit temperature:

CFD: 208.172 K
Theory: 206.520 K
Error: approximately +0.80 %

Exit velocity:

CFD: 430.319 m/s
Theory: 433.361 m/s
Error: approximately -0.70 %

Boundary mass-flow mismatch:

approximately 1.077 %

Configured acceptance threshold:

1.0 %

The deterministic scientific policy therefore correctly withheld a
fully converged ACCEPT decision.

## Interpretation

This is strong preliminary Level-1 validation evidence.

It is not presented as a fully converged steady-state solution.

Analytical exit targets were hidden from the CFD reasoning agent and
used only during post-hoc validation.

## Current limitation

A localized inlet pressure / temperature overshoot remains.

Inlet boundary-condition compatibility is a leading hypothesis, but the
present evidence does not establish causality.
