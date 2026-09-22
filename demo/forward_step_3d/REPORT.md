# 3D forward-step checkpoint: scientific blocker

**FS-A completed; the intended planar 3D baseline is NOT scientifically accepted. FS-B/C/D were not run.** The user explicitly required stopping for unexpected three-dimensional behavior or numerical instability. Nonzero spanwise velocity grew from roundoff-sized values into an order-0.1, spatially alternating field near the step corner despite zero spanwise initialization and forcing. The precise numerical mechanism remains unproven. This is not an approval-service failure and not a solver crash.

## A. Repository and recovery

Repository: `C:\Backup from one drive\Desktop\Research\physics-constrained-cfd-agent-e2e`.
Branch: `feature/forward-step-3d`; base commit `007a71d192620e42efd2f26d5f9904ffcfa0064c`.
No pre-existing tracked file was modified. New files are confined to `src/pipeline/forward_step/`, `configs/forward_step/`, `scripts/run_forward_step.py`, `tests/forward_step/`, `docs/forward_step_3d.md`, and the isolated demo handoff. Earlier nozzle artifacts remain untouched. No commit or broad staging was performed.

The existing solver had already finished during the earlier interruption. It was not restarted. The official tutorial and verified 2D evidence were preserved. The prior blocked command was `wsl -d Ubuntu-24.04 -- mpirun --version`; approval review reported a usage limit. It did not run and did not affect CFD. Subsequent read-only recovery was approved.

## B. Canonical 3D case

Official source: `/opt/openfoam14/tutorials/shockFluid/forwardStep`, Foundation v14 build `14-7b05503f98a8`.
Completed case: `/home/aakash/codex_forward_step_3d_20260922/FS-A`.
Geometry: 3x1 channel, step x=0.6, height 0.2, span 0.1. Nominal Nx/Ny/Nz=240/80/8; three fluid blocks give 129,024 cells. Cubic spacing is 0.0125. Two matched translational cyclic patches replace empty spanwise boundaries. The planar extrusion has three solution directions and introduces no side walls.

checkMesh: Mesh OK, non-orthogonality 0, maximum skewness 2.8312e-13, maximum aspect ratio 1.000000000000125. Both cyclic patches have 16,128 faces; matching passed. The parameterized builder reproduces the baseline cell-centre coordinates exactly. Fixed schemes, fvSolution and gas inputs are byte-identical.

Unchanged physics: inviscid normalized ideal gas, p=T=1,U=(3,0,0), gamma approximately 1.4; shockFluid, Kurganov, vanLeer/vanLeerV, Euler, maxCo=0.2, endTime=4. Passive output changes: writePrecision=16, timePrecision=14; OpenFOAM automatically increased the latter to 15 near t=1.001. No fatal error occurred. A small adaptive Co overshoot reached 0.20243235.

Exact solve command after sourcing Foundation v14:

```bash
foamRun -case /home/aakash/codex_forward_step_3d_20260922/FS-A
```

All mesh/post-processing command arrays and timings are in FS-A/execution.json. No continuation command was needed. The run ended at t=4 after 7,820 steps. The runner recorded 1256.595 seconds; OpenFOAM reported ExecutionTime 1267.00094 seconds and ClockTime 1268 seconds. These distinct timer readings are preserved without reconciliation.

## C. Final physical fields

All 40 saved states are finite with positive p/rho/T; every-step monitored minima are positive. Final internal-cell ranges, normalized units:

| Field | Minimum | Maximum |
|---|---:|---:|
| Mach | 0.019187775 | 3.0242809 |
| p | 0.025400678 | 12.01924 |
| rho | 0.047353458 | 6.5276937 |
| T | 0.73219686 | 2.8176556 |
| speed | 0.032176498 | 3.0758177 |

The large-scale detached compression front, upper-wall Mach stem, downstream reflected shocks and corner expansion remain recognizable. This resemblance is insufficient to accept the transverse-velocity behavior.

## D. 2D versus 3D at t=4

3D values are interpolated between the two central z-cell planes. Relative L2 uses the 2D reference norm; relative L-infinity uses its peak absolute value (componentwise for vector U).

| Field | Relative L2 (%) | Relative L-infinity (%) |
|---|---:|---:|
| Mach | 0.458340 | 17.590533 |
| p | 0.525407 | 1.612093 |
| rho | 0.430499 | 2.544008 |
| T | 0.299059 | 9.702176 |
| speed | 0.461507 | 22.861622 |
| U | 0.830961 | 23.887629 |

Measured lower-front x=0.3125 and upper-stem x=0.6125 match 2D at the 0.0125 grid resolution. The same regional fit gives 63.5746 degrees; this is not one global angle for a curved shock. Local plateau ratios p2/p1=10.82359 and rho2/rho1=3.97499 differ from 2D by +0.0381% and -0.0431%, respectively. These are finite-distance samples, not exact moving-shock jump validation.

Pressure/density profiles at three y levels largely overlap. Peak scalar differences lie in the corner neighbourhood around x=0.63125–0.64375, y=0.20625–0.21875, not simply at a displaced primary front. Excluding the explicitly recorded corner box reduces Mach L2 difference to 0.2684% and speed to 0.3021%; this localization is descriptive and does not waive the corner problem or change acceptance.

## E. Spanwise uniformity and the blocking finding

Maximum relative plane-to-mean L2 variations:

| Field | Maximum relative L2 | Maximum deviation / peak mean |
|---|---:|---:|
| Mach | 3.9232e-12 | 5.3435e-11 |
| p | 1.8883e-11 | 9.5217e-11 |
| rho | 1.5326e-11 | 8.6777e-11 |
| T | 6.9317e-12 | 6.3655e-11 |
| U | 9.2374e-12 | 8.9671e-11 |

These tiny variations do **not** imply Uz=0. At t=4, Uz ranges from -0.304366 to +0.359976. The maximum is 12.0% of inlet speed at approximately (0.64375,0.21875,0.00625), close to the corner. L2(Uz)/L2(U)=0.00371418. About 5.686% of the domain volume has |Uz|>0.01; that counting level is descriptive, not an acceptance band.

The saved history starts with exactly zero Uz, approximately 3.7e-12 at t=0.1, and approximately 6.2e-6 at t=1, then grows rapidly to order 0.1. The map shows a cell-scale alternating pattern near the expansion corner. Roundoff amplification is consistent with this evidence, but the responsible reconstruction/flux/geometry mechanism has not been isolated. This must not be labelled physical three-dimensional instability.

An independent `foamPostProcess -func 'components(U)' -time 4` extraction produced Uz exactly matching the Python vector reader (maximum difference zero). This rules out that reader as the cause. No forcing, clipping, alternate scheme or new CFD run was introduced to hide the result.

## F. Transient conservation

The maximum normalized discrete residual `(M[n]-M[n-1])/dt + sum(phi[n])` is 1.94004e-10. Cumulative defect divided by initial mass is -2.22705e-12. Final inlet/outlet mass fluxes are 0.4200016371 and 0.3937570022 for span 0.1; their approximately 6.249% mismatch is accompanied by storage. Maximum impermeable-wall flux is 1.16823e-17; net periodic-pair flux is at most 1.87093e-17.

At t=4 the stored mass is 0.6324202620, momentum approximately (1.228160652,0.0585959833,-1.893895e-6), and total energy 3.582795666. Histories are provided. Exact momentum/energy flux closure is **not** established: the required shockFluid phiUp/phiEp are local predictor temporaries. Mass closure does not validate the velocity field.

## G. Parameter cases

| Case | Prepared parameters | Expected/actual fluid cells | Run status |
|---|---|---:|---|
| FS-A | M=3,h=0.2,span=0.1,Nz=8 | 129,024 actual | Completed; scientifically BLOCKED |
| FS-B | h=0.15; other defaults | 135,168 expected | Config only; not built/run |
| FS-C | M=2.5; canonical geometry | 129,024 expected | Config only; not built/run |
| FS-D | span=0.2,Nz=16 | 258,048 expected | Config only; not built/run |

There are no invented runtimes, physical ranges or validation outcomes for unrun variants. The campaign runner now also requires an explicitly accepted scientific review before dispatching variants.

## H. Validator and scope

Hard numerical health checks pass: completion, mesh, dimensionality, cell count, periodic topology, unchanged fixed recipe, finite/positive states, finite positive Courant values, supersonic inlet and measured compression jumps. Scientific disposition is separately **BLOCKED_PLANAR_INVARIANCE**. Conservation, Co overshoot, 2D differences and spanwise variation are measurements without invented acceptance bands. The validator now explicitly distinguishes z-uniformity from the zero-Uz planar invariant and preserves a blocked scientific review during reanalysis.

The spec/build/initialize/execute/diagnostics/validate interfaces and fixed recipe are implemented. Geometry, resolution, nominal Mach, pressure, temperature, end time and maxCo propagate through generated dictionaries; unit tests exercise noncanonical inputs. Arbitrary schemes, gas changes, viscosity and arbitrary geometry are outside scope. The family is not ready to register as a verified production capability or connect to an LLM.

## I. Tests

26 unit tests passed, zero failed, zero skipped. Tests include serialization of a blocked review and the counterexample of a z-uniform field with nonzero Uz. One full 3D CFD integration run completed; a separate mesh-only builder-equivalence check passed. FS-B/C/D integrations were withheld for the scientific blocker. No expensive CFD is launched by ordinary test discovery.

## J. Reproducibility and artifacts

See the repository's docs/forward_step_3d.md for CLI usage. Native completed fields and polyMesh remain in the Linux case, and the handoff ZIP includes them with logs, original scripts, module/config/test snapshots, reports, figures and the previously verified 2D package. The ZIP is a **blocked-checkpoint evidence package**, not a successful four-case campaign.

FS-A/figures contains mesh_3d, Mach_midplane, p_midplane, rho_midplane, T_midplane, speed_midplane, spanwise_xy_slices, xz_yz_sections, shock_density_contours, profiles_2d_vs_3d, transient_conservation and spanwise_velocity_blocker PNGs. The mesh view uses actual polyMesh edges; its thin span is visually expanded and labelled. CSVs preserve line profiles, stored totals, mass residuals and Uz history. JSONs preserve metrics, hard checks and the separate scientific blocker.

## K. Remaining issue / stop condition

The required next scientific task is to isolate why the discrete 3D formulation amplifies a zero-Uz perturbation near the step corner, then demonstrate that any justified correction preserves the canonical physical problem and planar solution. That investigation and any changed CFD run require a follow-up decision under the user's stop rule. This session did not launch variants, alter the reference numerics or implement the router/LLM. Formal mesh/time-step convergence, independent uncertainty-quantified validation and exact momentum/energy closure also remain open.
