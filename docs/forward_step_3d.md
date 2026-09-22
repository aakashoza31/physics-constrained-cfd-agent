# Periodic 3D forward-facing-step Euler family

**Current scientific status: BLOCKED_PLANAR_INVARIANCE.** FS-A completed to t=4 with positive fields and excellent transient mass closure, but developed Uz up to 0.360 from a zero-Uz initialization. Small differences between z planes do not establish planar flow. FS-B/C/D are prepared configs only and were deliberately not run. The family is implemented and unit-tested, but is not a verified production CFD family. See the accompanying checkpoint report and scientific_review.json. Resolve the numerical spanwise-velocity growth before further campaign execution or router integration.

This isolated family reproduces the OpenFOAM Foundation v14 `shockFluid/forwardStep` physics in a true three-dimensional extruded mesh. It does not generalize to arbitrary CFD, viscosity, turbulence, side-wall boundary layers, arbitrary obstacles, reacting gas, or arbitrary numerical schemes. No LLM/router is implemented.

## Provenance and physical interpretation

The source is `/opt/openfoam14/tutorials/shockFluid/forwardStep`, build `14-7b05503f98a8`. The prior verified 2D run completed at t=4 with 16,128 cells, one empty layer and credible large-scale shock structure. It remains a tutorial reproduction without formal mesh independence or independent uncertainty quantification. The preserved original nine inputs are included in `src/pipeline/forward_step/template/`; the builder copies them without editing the installed tutorial.

The canonical 3D domain is 3 x 1 with a step beginning at x=0.6, height 0.2 and span 0.1. At nominal Nx=240, Ny=80 and Nz=8 it contains 129,024 fluid cells, with dx=dy=dz=0.0125. Nx/Ny describe full-domain division counts; the three fluid blocks omit the solid step. Splits are rounded proportionally while preserving exact geometric vertices. Non-aligned geometry therefore produces piecewise uniform spacings, which are exposed in the generated dictionary and checked by checkMesh.

Paired cyclic span boundaries model a periodically repeated extrusion without artificial side walls. Unlike an empty patch, the mesh and solver have three solution directions. Uniform initial data and forcing select a planar solution in this 3D domain. Agreement with 2D does not demonstrate stability to spanwise disturbances or fully three-dimensional turbulent physics.

The fixed thermodynamics are the tutorial's normalized ideal gas (Cp=2.5, molecular weight 11640.3, mu=0), giving gamma about 1.4 and R about 0.7142825. The `mach` input is nominal: velocity equals mach*sqrt(T), preserving U=3 exactly at the official p=T=1 setup. Due to rounded molecular weight, actual Mach is about 3 parts per million above nominal and is explicitly reported. Initial conditions are uniform inlet values, without imposing any downstream shock or theoretical exit state.

The original Kurganov, vanLeer/vanLeerV and Euler recipe is retained. maxCo defaults to 0.2 and may be reduced, not raised through this family. High global writePrecision=16 and timePrecision=14 improve output diagnostics; they do not change the governing equations or convergence target. Written restart accuracy changes, but these runs start from uniform time zero and do not restart. EndTime=4 is a transient observation time, not a stationarity criterion.

## Interfaces and commands

Modules expose `ForwardStep3DSpec`, `build`, `initial_state`, `execute`, `diagnose` and `validate`. `scripts/run_forward_step.py` provides separate build/execute/analyze operations and `all`. They run inside Linux/WSL with a sourced Foundation v14 environment. Native Linux case directories avoid slow Windows-mounted solver I/O. The existing generic FoamRuntime remains untouched; callers can invoke this CLI through it later.

```bash
source /opt/openfoam14/etc/bashrc
python3 scripts/run_forward_step.py all --config configs/forward_step/case_A_reference.yaml --case /home/USER/new_FS_A --reference /path/to/verified_2d/native_final.npz
python3 scripts/run_forward_step.py all --config configs/forward_step/case_B_step_height.yaml --case /home/USER/new_FS_B --ranks 4
python3 scripts/run_forward_step.py all --config configs/forward_step/case_C_mach.yaml --case /home/USER/new_FS_C --ranks 4
python3 scripts/run_forward_step.py all --config configs/forward_step/case_D_span.yaml --case /home/USER/new_FS_D --ranks 4
```

Use a fresh destination: build and execution reject existing evidence. The optional rank count controls execution only. Parallel runs preserve decomposePar, mpirun/foamRun and reconstructPar logs and timing; reconstructed native fields are used for analysis. No processor output is deleted. Changing rank count can change floating-point reduction order.

The only runtime dependencies are Python 3, NumPy, PyYAML, Matplotlib and Foundation v14; no AI API key is involved. JSON configs work as well as YAML. Unspecified fields receive canonical defaults. Supported parameters are length, height, step_x, step_height, span, nx, ny, nz, nominal mach, pressure, temperature, end_time, max_co and write_interval. Gas composition and fvSchemes are intentionally fixed. Grading is uniform within blocks; arbitrary grading/refinement is not exposed. Valid geometry and positive finite thermodynamic inputs are required. Nz must exceed one, inflow must be supersonic and each block must receive cells. Accepted syntax is not a guarantee of numerical robustness across every parameter combination.

## Diagnostics and interpretation

Numerical health checks include successful completion at the requested time, three-dimensional mesh validity, expected cell count, finite saved fields, positive p/rho/T at saved times and every monitored step, no fatal solver error and supersonic inlet. Courant behavior is measured against the configured target; the adaptive controller can briefly overshoot. No undocumented post-hoc pass band is used.

Transient mass closure uses `(M[n]-M[n-1])/dt + sum(phi[n])` with the solver's native boundary mass fluxes. The periodic pair is included, as are solid boundaries. Both per-step normalized residual and cumulative defect are reported. A nonzero inlet/outlet difference is not a failure by itself. Domain momentum and total-energy histories are also computed, but exact flux closure is not claimed: shockFluid constructs `phiUp` and `phiEp` as local predictor temporaries. A naive product of saved primitive variables and mass flux would not reproduce those numerical fluxes.

For canonical XY grids, midplane values are interpolated between the two central cell planes. Direct 2D comparisons report relative L2 and relative L-infinity errors, with norms normalized by the reference norm/peak. Discontinuity displacement can dominate pointwise errors; pressure/density profiles and gradient-based front locations accompany them. A regional angle describes only part of the curved shock. Plateau jumps are measured where samples exist; stationary normal-shock formulae are a qualified sanity check on a moving curved front, not imposed targets.

Spanwise diagnostics compare each native z-plane to the spanwise mean and report maximum deviation and plane L2 differences, plus absolute Uz. Recent saved-state differences are recorded without demanding stationarity. The deterministic validator returns hard health failures separately from measurements that require scientific interpretation. `NUMERICAL_HEALTH_PASS_SCIENTIFIC_REVIEW_REQUIRED` deliberately does not claim formal validation.

Every plotted scalar comes from native OpenFOAM cells. Three-dimensional mesh plots read actual polyMesh points, faces and boundary ranges. The display expands the thin span visually and labels that change. Several native z slices, x-z/y-z sections and exported profiles allow direct inspection.

## Tests and evidence

```bash
python3 -m unittest discover -s tests/forward_step -v
```

These tests do not launch CFD. The explicit CLI `all` commands above are expensive integration runs; they are not part of ordinary test discovery. Executed case diagnostics, configs, figures, timings and full logs are recorded in the accompanying campaign report. Nozzle modules and existing untracked outputs are preserved.

Before later router registration, retain scope rejection, explicit numeric specs, evidence paths and qualified validator states. Important scientific gaps remain mesh/time-step sensitivity, independent benchmark digitization with uncertainty, corner treatment, exact energy/momentum flux audits and robustness to nonuniform spanwise perturbations. An AI layer must not turn a measured value or a successful solver exit into an unconditional physical-validation claim.
