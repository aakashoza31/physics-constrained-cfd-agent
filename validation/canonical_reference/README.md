# Manual OpenFOAM Foundation v14 nozzle reference

This package constructs and verifies an axisymmetric, inviscid, calorically perfect-air solution of the canonical **conical** converging-diverging nozzle. It has no LLM, API, agent framework, Gmsh, or proprietary dependency. The original research repository is not modified.

The `results` directory contains the archived verification outputs. A reference campaign is accepted only when the deterministic study validator reports `FINAL_REFERENCE`.

## One command

On the existing Windows/WSL installation, open PowerShell in this folder:

```powershell
.\RunReference.ps1
```

On Linux with Foundation OpenFOAM 14 and Python 3 + NumPy:

```bash
bash Allrun
```

`FOAM_BASHRC` may select a different Foundation v14 installation; the default is `/opt/openfoam14/etc/bashrc`. The Windows launcher defaults to `Ubuntu-24.04`; use `-Distro NAME` if necessary. No packages are downloaded. The scripts require `blockMesh`, `checkMesh`, `foamPostProcess`, and `foamRun` from the same Foundation v14 installation. OpenCFD releases are not interchangeable.

The command runs four meshes and three controlled sensitivity cases. It preserves the full cases under `~/.cache/manual-nozzle-reference/TIMESTAMP`, prints their location, and exports summaries and a lossless raw-case archive into `results/TIMESTAMP` beside these scripts. Expect substantial CPU time for the complete verification campaign. Each solver runs serially. Do not use an old, partially populated output directory: the builder refuses to overwrite an existing case.

`REFERENCE_WALL_LIMIT_S` sets the per-case wall-clock cap, default 7200 s. A timeout or stalled solver exits unsuccessfully and preserves the evidence. It never automatically reduces the timestep or declares a healthy partial state converged.

## Fixed physical specification

| Item | Value |
|---|---|
| Axial breakpoints, m | 0, 0.05, 0.15, 0.16, 0.28, 0.33 |
| Radius at breakpoints, m | 0.05, 0.05, 0.0326, 0.0326, 0.0354, 0.0354 |
| Reservoir | 200000 Pa total pressure; 300 K total temperature |
| Gas | Perfect gas; R = 287 J/(kg K); gamma = 1.4; Cv = 717.5 J/(kg K) |
| Viscosity / heat conduction | Zero; adiabatic slip wall |
| Domain | Internal nozzle only; no external plume |
| Ambient | 30000 Pa, used for regime interpretation; not imposed on the exit |

The geometry preserves the finite throat length and sharp changes of wall slope. It is not silently smoothed into a different nozzle. Quasi-1D theory is an approximate comparison for this multidimensional geometry, not an exact analytical solution of the axisymmetric Euler equations.

## Primary method

`shockFluid` advances the conservative mass, momentum, and total-energy balance to a stationary state, with `sensibleInternalEnergy` as the thermodynamic variable. The implementation uses Kurganov fluxes, `Minmod` reconstruction for density, momentum reconstruction under the `U` name, and temperature/internal energy reconstruction under the `T` name; Euler time integration; and a maximum acoustic Courant number of 0.4. It uses no artificial viscosity, temperature clipping, density floor, or target-state forcing.

The mesh is a 5-degree, one-cell azimuthal wedge. Four systematic meshes use `(axial, radial)` counts `(132,16)`, `(198,24)`, `(264,32)`, `(330,40)`: 2112, 4752, 8448, and 13200 cells. All axial segment lengths and radii remain unchanged. `checkMesh -allTopology -allGeometry` must pass. The fourth mesh was added because the preceding throat-Mach difference exceeded the declared 0.5% tolerance; the threshold was not relaxed.

At the inlet, `totalPressure` and `totalTemperature` impose the reservoir state. `directionMixed` fixes the two transverse velocity components to zero and extrapolates axial velocity. This supplies direction without prescribing mass flow or all five primitive Euler variables. It is a reservoir-style extrapolative inlet, not an exact nonreflecting characteristic boundary.

At the exit, p/T/U use `zeroGradient`; density boundary values follow the thermodynamics. This is accepted only if every exit face has outward **normal** Mach greater than 1.05 in the final solution. No 30 kPa or approximately 54 kPa exit state is imposed. A back-pressure sweep or prediction of the external underexpanded jet requires a separate problem with an external domain or a suitable subsonic-outflow formulation.

## Initialization that is actually applied

`foamPostProcess` writes the actual mesh cell centres and volumes. `initialize.py` computes a quasi-1D state at every cell centre and writes explicit nonuniform p/T/U internal fields. A radial startup component approximately follows the conical wall slope. The field is only an initial guess: the solver subsequently changes it freely. No source term or repeated reinitialization maintains it.

The initializer reads back all written values, verifies their count and numerical agreement, and requires the expected spatial pressure range. It writes `initialization_verified.json`. It does **not** use the obsolete `defaultFieldValues/regions/boxToCell/fieldValues` syntax that the archived v14 run silently ignored.

## Validation and stopping

The standard integration horizon is 6 ms. It is a convergence test horizon, not a claim that every nozzle must settle in 6 ms. A failure of stationarity means the result remains unaccepted; do not change thresholds to pass it. The final two milliseconds provide the stationarity window.

The deterministic validator requires all of the following:

| Check | Acceptance |
|---|---|
| Execution | Return code 0, `End`, requested final time reached; no fatal solver error |
| Initialization / mesh | Read-back pass; full checkMesh pass |
| Thermodynamics | Finite saved fields; strictly positive p/T/rho at every monitored timestep |
| Inlet | All faces subsonic inflow; reservoir totals within 0.1% |
| Outlet | Minimum outward-normal Mach > 1.05; pressure above 30 kPa |
| Throat | Volume-weighted finite-throat-region Mach between 0.9 and 1.1 |
| Regime | No downstream slab-average return to subsonic flow after x = 0.17 m |
| Steady mass balance | Maximum boundary mismatch over final 2 ms < 0.1% |
| Transient continuity | Maximum normalized discrete mass residual < 0.01% |
| Monitor stationarity | Relative range of monitored quantities over final 2 ms < 0.2% |
| Field stationarity | Volume-weighted relative L2 change of p/T/rho/U over final 2 ms < 0.2% |
| Energy sanity | Maximum saved stagnation-enthalpy deviation from reservoir < 5% |
| Physical versus numerical flow | Integrated rho U dot S versus solver phi agrees within 0.5% |
| Theory | Exit pressure within 5%; exit T/U/M and choked mass flow within 3% |
| Mesh sensitivity | Every mesh passes; last-pair changes in exit p/T/U/M/mass flow and throat M < 0.5% |
| Controls | Coarse-grid half-Co, half-angle, and 2% pressure-startup perturbation each pass and change reported quantities < 0.2% |

The theory tolerances are screening bounds for a finite-angle conical flow; they do not turn a quasi-1D prediction into exact CFD truth. The mesh threshold is a measured last-pair sensitivity criterion, not a formal Richardson/GCI uncertainty estimate. Timestep, wedge-angle and startup sensitivity are tested on the coarse grid; no stronger claim about a full temporal convergence study on the finest mesh is made.

For every solver timestep, the native function objects record domain mass and **all nonempty boundary fluxes**. The diagnostic uses

```
(M[n] - M[n-1])/dt[n] + sum(phi_boundary[n])
```

which matches this solver's Euler update. It reports this separately from steady inlet/outlet mismatch. All terms have the solver's outward-normal sign convention. Diagonal inviscid updates print zero linear-system residuals: those values are explicitly excluded as evidence of stationarity.

Reported full-nozzle mass flows use the actual planar-wedge area correction `2*pi/sin(angle)`. The finite polygon wedge is not scaled as if its area were an exact curved sector. Extensive quantities scale; intensive quantities do not.

## Files and independent checks

- `build.py`: deterministic mesh/dictionary generator, with protected existing paths.
- `initialize.py`, `foamio.py`: explicit field initialization and strict ASCII readers.
- `run_case.sh`, `execute.py`: mesh checks, initialized-field checks, bounded serial execution, process-status evidence.
- `validate.py`: conservation, stationarity, choking, outlet, theory, and refinement checks; nonzero exit on failure.
- `run_sensitivity.sh`: the three declared control experiments.
- `Allrun`, `RunReference.ps1`: full one-command campaign.
- `package.py`: complete field/log archive and SHA256 manifest.
- `test_validation.py`: targeted parser, branch, and conservation regression checks.

Revalidate an existing case without running CFD:

```bash
python3 validate.py /absolute/path/to/case
python3 validate.py --study /absolute/path/to/campaign
bash Allverify /absolute/path/to/campaign
python3 test_validation.py
```

`--partial` is for inspection during execution. It cannot replace a final campaign acceptance. The validator reconstructs `zeroGradient` patch values from their actual owner cells when v14 omits redundant boundary values from written fields.

`--study` compares existing validation summaries. `Allverify` first recomputes every case's checks from native fields, logs and monitors, then compares the refreshed summaries; it does not run CFD.

The raw-case archive includes generated dictionaries, all saved fields, complete logs, per-step monitors, and validation reports. No new autonomous architecture is implemented here.
