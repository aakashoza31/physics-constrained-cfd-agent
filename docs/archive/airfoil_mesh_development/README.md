# Airfoil mesh development — historical archive

> **HISTORICAL / SUPERSEDED — not the active F3 family.**

Three mesh generations were attempted for a NACA0012 family and all three were
rejected. The work is preserved because the negative result is part of the
paper, and because one of the diagnoses turned out to be wrong in a way worth
recording.

| Document | What it is |
|---|---|
| `F3_MESH_RECIPE_V2.md` | the custom Gmsh generator, v1 and v2, and why both failed |
| `F3_FAMILY2_RUNBOOK.md` | the switch to NASA TMR Family II CGNS grids |

## What is still true

The final status: **`MESH_REJECTED / CFD_NOT_RUN`**. No flow solver was ever
launched for this family.

## What these documents get wrong

They attribute the Family II rejection to skewness, cell orientation and
in-plane validity. An independent cell-geometry audit showed those were
artefacts of our own converter and diagnostics:

* the axis transform `(x,y,z)_NASA -> (x,z,y)_OpenFOAM` reverses handedness;
* the corrected vertex permutation is `P = (3, 7, 6, 2, 0, 4, 5, 1)`;
* the in-plane checker read `cell[:4]`, a side face, not the flow-plane quad;
* the Python skewness metric is not Foundation-v14 skewness.

Foundation-v14 `checkMesh` reports skewness 0.857 / 0.820 / 0.728 — all passing.
The decisive genuine failure is **in-plane stretching**: 31,734,384 / 36,320,937
/ 38,855,541 against a frozen limit of 10,000.

The authoritative record is `cases/airfoil/mesh_rejection/` and its
`reference/corrected_diagnosis.json`.
