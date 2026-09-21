# Numerical Method

The supported reference problem is internal axisymmetric inviscid converging-diverging nozzle flow with calorically perfect air.

Numerical formulation:
- OpenFOAM Foundation v14
- shockFluid
- Kurganov fluxes
- Minmod reconstruction
- Euler time integration
- structured axisymmetric wedge mesh
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

Case acceptance is deterministic and checks mesh validity, thermodynamic admissibility, conservation, stationarity, choking, outlet supersonicity, reservoir consistency, and numerical sensitivity.
