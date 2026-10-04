# Nozzle reference refinement campaign

The LLM-free reference campaign of the nozzle family (`validation/canonical_reference/`, results in `validation/canonical_reference/results/`). The canonical nozzle was evaluated on four systematically refined meshes and three numerical-control cases.

Finest-grid results:
- cells: 13,200
- exit Mach: 1.524386
- exit pressure: 52.42521 kPa
- exit temperature: 204.81096 K
- exit mass flow: 1.5349148 kg/s

Final mesh-pair changes:
- throat Mach: 0.41472%
- exit pressure: 0.26769%
- exit temperature: 0.09308%
- exit speed: 0.10134%
- exit Mach: 0.14809%
- exit mass flow: 0.07433%

Control sensitivities:
- halved Courant limit: 0.01882%
- halved wedge angle: 0.01703%
- startup-pressure perturbation: 0.03576%

The campaign passed its registered criteria. The agent's canonical run (2,112 cells) is bit-identical to mesh 1 of this campaign. No formal grid-convergence index is reported, and individual agent runs remain single-mesh (`PASS_SINGLE_MESH`).

This campaign is restricted to the internal axisymmetric inviscid supersonic nozzle. It is not an external-jet, turbulence, viscous-flow, or arbitrary-back-pressure validation.
