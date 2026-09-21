# Limitations

This repository is a research prototype with a deliberately narrow validated domain.

## Physics limitations

The demonstrated solver path is restricted to internal axisymmetric inviscid nozzle flow with calorically perfect air and adiabatic slip walls. It does not validate turbulence, boundary layers, viscosity, heat transfer, real-gas effects, external jets, arbitrary shock-containing back-pressure branches, or general three-dimensional geometries.

## Transfer limitations

The software scope gate permits a wider numerical envelope than the three demonstrated cases. Those bounds are safety/transfer guardrails, not proof of validated accuracy everywhere inside the box.

Only the following nearby changes were directly demonstrated in the public A/B/C campaign:

- exit radius 35.4 mm -> 37.0 mm
- reservoir total pressure 200 kPa -> 220 kPa

## Single-grid transfer cases

B and C are `PASS_SINGLE_MESH` results. They do not independently repeat the canonical grid-convergence, timestep, wedge-angle, and startup-sensitivity studies.

## LLM limitations

The LLM proposes high-level actions and can make incorrect interpretations. Deterministic scope, action, and scientific validators therefore remain mandatory.

Visual observations are qualitative. The model is explicitly forbidden from declaring convergence from images or reading precise physical values from colormaps.

## Feedback-action validation

The architecture supports multiple actions, but the demonstrated multi-iteration public trajectory specifically exercises `CONTINUE_RUN -> ACCEPT` in Case A. Refinement, diagnostic requests, and clean restart are implemented/guarded pathways, but should be described as supported mechanisms unless separately exercised and archived in a dedicated experiment.

## Numerical-reference interpretation

The canonical campaign is a numerically verified reference, not experimental validation and not a formal exact-solution proof. Quasi-1D theory is a useful screening/reference model for this problem but is not exact truth for the finite-angle multidimensional nozzle.
