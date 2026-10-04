# Numerical method: nozzle family

This page describes the nozzle family. The forward-facing-step family (2-D planar, transient, `shockFluid`, storage-aware mass closure, no stationarity criterion) is described in the CFD Forge paper's setup appendix and in `src/pipeline/forward_step_2d/`.

The supported reference problem is internal axisymmetric inviscid converging-diverging nozzle flow with calorically perfect air.

Numerical formulation:
- OpenFOAM Foundation v14
- shockFluid
- Kurganov fluxes
- Minmod reconstruction
- Euler time integration
- structured axisymmetric 5° wedge mesh (2,112 cells: 1,980 hex + 132 prisms)
- adiabatic slip walls

Boundary treatment:
- reservoir total pressure and total temperature at the inlet
- axial inlet velocity allowed to respond to the solution
- extrapolative outlet treatment
- outlet accepted only after deterministic verification of supersonic outward flow

Initialization:
- explicit per-cell quasi-one-dimensional startup field
- written fields are read back before execution
- legacy incompatible setFields initialization is not used

Case acceptance is deterministic: 20 registered checks covering mesh validity, thermodynamic admissibility, conservation, stationarity, choking, outlet supersonicity, reservoir consistency and agreement with quasi-1-D theory (`src/pipeline/nozzle/validate.py`). Acceptance is single-mesh (`PASS_SINGLE_MESH`); no per-run mesh or numerical-sensitivity check is part of it. Mesh and numerical-control sensitivity were assessed once, in the LLM-free reference refinement campaign (`docs/REFERENCE_VALIDATION.md`).
