> **HISTORICAL / SUPERSEDED — not the active F3 family.**
> The active F3 family is the surface-mounted cube (`cases/cube/drifting_wake`).
> NACA0012 is supplementary S1: `MESH_REJECTED / CFD_NOT_RUN`, decided by
> in-plane stretching. The corrected scientific record is
> `cases/airfoil/mesh_rejection/reference/corrected_diagnosis.json`; anything in
> this document that blames the NASA grid for skewness, cell orientation or
> in-plane validity is a pre-audit artefact of our own converter.

# F3 surface-distribution recipe v2 — result and diagnosis

Recipe v1 is archived unchanged under `outputs/airfoil_mesh/v1/`. The active
recipe is v2, whose reports live under `outputs/airfoil_mesh/v2/` and whose
readiness gate is computed from those three reports.

## What v2 changed

Only the surface distribution, partitioned at x/c = 0.98: truncated cosine from
the leading edge to the partition, then a geometric progression in surface arc
length from the partition to the trailing edge, prescribed to start at the
trailing edge with the fan's own circumferential spacing.

Everything else is bit-identical to v1: farfield, wake sizing, first wall-layer
heights, nominal layer counts, wall-normal progression, the 0.02c envelope, the
fan sector counts, the spanwise extrusion, the Gmsh settings and seed, and every
mesh-quality threshold.

## v2 did what it was specified to do

| level | prescribed δ_TE | realized δ_TE | rel. error | realized fan interval | δ_TE / fan | partition ratio |
|---|---|---|---|---|---|---|
| coarse | 2.38310000e-7 | 2.38310000e-7 | 1.57e-9 | 2.48511170e-7 | 0.95895 | 1.47967 |
| medium | 1.05915556e-7 | 1.05915556e-7 | 2.16e-9 | 1.12112831e-7 | 0.94472 | 1.52373 |
| fine   | 4.70735802e-8 | 4.70735806e-8 | 7.04e-9 | 5.08325399e-8 | 0.92605 | 1.55890 |

All seven v2 construction checks pass on all three levels. v1's failure mode —
a 159.57:1 mismatch between the surface interval and the fan interval at the
wall — is closed: the ratio is now ~0.95.

## v2 still fails the frozen quality gates, and worse than v1

| metric | gate | v1 coarse → fine | v2 coarse → fine |
|---|---|---|---|
| max skewness | ≤ 2 | 2.861 → 8.651 | 275.2 → 791.7 |
| min interpolation weight | ≥ 0.10 | 4.33e-3 → 4.49e-3 | 7.51e-5 → 3.11e-5 |
| min face-volume ratio | ≥ 0.10 | 3.26e-3 → 3.38e-3 | 7.51e-5 → 3.11e-5 |
| max non-orthogonality | ≤ 65° | 56.9 → 61.7 (passed) | 86.9 → 85.9 (now fails) |
| max in-plane stretching | ≤ 10,000 | 1537 (passed) | 5146 → 14,002 (fails at fine) |

## Why — the mismatch was relocated, not removed

The worst cells are no longer at the trailing-edge apex. On the coarse level they
sit at (1.002289, −0.017042), i.e. **r = 0.017195 from the trailing edge**, inside
the 0.02c boundary-layer envelope, between two unstructured prisms
(`at_bl_outer_interface: false`).

Measured there: 39 prism triangles inside a 2e-4 box, the smallest six being
needles that fan from a single outer node onto the boundary-layer front, with one
short edge of 2.39e-7 … 4.79e-7 and two long edges of ~2.82e-4.

The mechanism, and the numbers behind it:

* the boundary-layer field transports the wall-parallel node spacing radially
  outward unchanged, so the BL front near the trailing edge now carries the
  prescribed δ_TE spacing (2.4e-7 coarse) instead of v1's 3.8e-5;
* the outer sizing field asks for 4.06e-3 at that location
  (`background_size(0.0172) = 0.002 + 0.12 × 0.0172`);
* the unstructured mesher bridges the two by fanning needle triangles.

Spacing mismatch at the BL outer front, behind the trailing edge:

| level | δ_TE (front spacing) | outer target size | ratio | v1 ratio |
|---|---|---|---|---|
| coarse | 2.383100e-7 | 4.400000e-3 | 18,463 | 117 |
| medium | 1.059156e-7 | 2.933333e-3 | 27,695 | 175 |
| fine   | 4.707358e-8 | 1.955556e-3 | 41,543 | 263 |

The ratio now GROWS with refinement (because δ_TE carries r⁻² while the target
size carries r⁻¹), which is why skewness rises monotonically 275 → 487 → 792.
v1's failing ratio was level-invariant; v2's is level-amplifying.

## What was not done

No undocumented local change was made. Specifically: the first wall layer was not
locally thickened, no trailing-edge transition block was introduced, fan sectors
were not reduced, no threshold was relaxed, and no sizing, wake or farfield
parameter was touched. Closing this gap requires an explicit, versioned decision
about a currently frozen parameter — the options all lie in the wall-parallel
coarsening of the BL front behind the trailing edge, or in the δ_TE ∝ r⁻² law, or
in a local outer size field keyed to the BL front spacing near the trailing edge.

## checkMesh

`checkMesh -allTopology -allGeometry` was NOT run for these v2 meshes: OpenFOAM
Foundation v14 is not installed in the environment that generated them
(`FoamRuntime.preflight()` reports `checkMesh` missing). The three reports
therefore carry `raw_openfoam_check_mesh: {}` rather than a fabricated one. Run
it locally with `--with-openfoam`; the deterministic F3 qualification above is
independent of it and is what the readiness gate reads.
