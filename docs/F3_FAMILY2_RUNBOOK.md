# F3 canonical mesh: NASA TMR Family II — status and runbook

The active F3 mesh path is NASA's Family II unstructured hexahedral CGNS
hierarchy. The custom Gmsh generator (v1 and v2) is untouched, and its meshes and
failed reports remain archived evidence under `outputs/airfoil_mesh/v1/` and
`outputs/airfoil_mesh/v2/`. Active reports go to
`outputs/airfoil_mesh/nasa_familyII/`.

| level | asset | structured | cells | NASA surface points |
|---|---|---|---|---|
| coarse | `n0012familyII.6.hex.cgns.gz` | 225 × 65 | 14,336 | 129 |
| medium | `n0012familyII.5.hex.cgns.gz` | 449 × 129 | 57,344 | 257 |
| fine | `n0012familyII.4.hex.cgns.gz` | 897 × 257 | 229,376 | 513 |

Cell counts are re-derived as `(ni−1)(nj−1)`, never transcribed.

## Two steps cannot run in the cloud session

1. **Downloading the assets.** `turbmodels.larc.nasa.gov` and `tmbwg.github.io`
   are both refused by the organization's egress policy (HTTP 403 to CONNECT,
   recorded by the agent proxy) from the cloud container *and* from the desktop
   workspace. Nothing was routed around it and no digest was invented.
2. **`checkMesh`.** OpenFOAM Foundation v14 is not installed where this session
   runs: `FoamRuntime.preflight()` reports `blockMesh`, `checkMesh`,
   `foamPostProcess` and `foamRun` missing. No `checkMesh` metric is reported
   for the real grids, and the reports carry an empty
   `raw_openfoam_check_mesh` rather than a fabricated one.

Everything else is implemented and exercised end to end against a
Family-II-shaped synthetic grid carrying the real coarse cell count (14,336):
convert 0.6 s, qualify 3.7 s.

## Local commands

```powershell
cd "C:\Backup from one drive\Desktop\Research\physics-constrained-cfd-agent-e2e"
python -m pip install "h5py>=3.0"

# 1. Fetch NASA's archive and extract the three Family II CGNS levels
#    (page: https://turbmodels.larc.nasa.gov/naca0012numerics_grids.html
#     archive: NACA0012numerics_grids.zip)
#    Put these three files in assets\families\airfoil\ :
#       n0012familyII.6.hex.cgns.gz
#       n0012familyII.5.hex.cgns.gz
#       n0012familyII.4.hex.cgns.gz
#    Optionally the three .p2dfmt.gz counterparts for the coordinate cross-check.

# 2. See exactly what is expected where, then record the digests of the bytes
#    you actually downloaded
python scripts\airfoil_assets.py report
python scripts\airfoil_assets.py register
python scripts\airfoil_assets.py verify

# 3. Convert, cross-check, run real checkMesh, and qualify all three levels
python scripts\qualify_family2_meshes.py --with-openfoam
```

Exit codes: `0` all three qualify, `2` a registered asset is missing or its
digest is unregistered, `3` at least one level is not qualified, `4` h5py absent.

Reports per level land in `outputs\airfoil_mesh\nasa_familyII\<level>\`:
`n0012_familyII_<level>.msh`, `generation.json` (conversion + cross-checks),
`checkMesh.log` (raw, verbatim) and `qualification.json` (deterministic verdict).

## What the conversion does, and does not do

Changes exactly one thing: the spanwise separation, from NASA's supplied span to
`b = 0.01 c`, keeping exactly one spanwise cell. In-plane coordinates are copied
through by value and the hex connectivity is NASA's, in NASA's order; both are
verified bit-for-bit afterwards. Patches are assigned from the topology —
`airfoil` → wall, `farfield` → patch, `frontAndBack` → empty — and the joined
C-grid wake never appears as a boundary face because both its sides are cells.
Nothing is regenerated, smoothed, projected, optimised or remeshed.

## Gates

The frozen gates are applied by `mesh_checks.apply_frozen_gates`, the same
function and the same module constants the archived Gmsh path used: 65°
non-orthogonality, skewness 2, interpolation weight 0.10, face-volume ratio 0.10,
in-plane stretching 10,000, positive volumes/areas, face pyramid/tet validity, no
genuine concavity, strict quad convexity and positive bilinear Jacobian. On top
of them the Family II path adds one connected fluid region, patch membership,
exact source preservation, orientation, and NASA's surface against the frozen
corrected TMR sharp-TE formula (chord, TE closure, ordinate discrepancy,
reflection, farfield extent).

NASA provenance is not a waiver: a failing gate fails. If Foundation `checkMesh`
flags a determinant or apparent concavity, the existing geometric diagnosis in
`mesh_qualification.py` runs against NASA's own connectivity and the raw report
is preserved beside the deterministic verdict; nothing is auto-waived. If our
conversion is at fault, the conversion gets fixed. If the native NASA grid
genuinely violates the contract, that is reported and the grid is left alone.

F3 remains non-routable: the `mesh_hierarchy_qualified` gate is computed from the
three Family II reports, so it cannot be closed by hand.
