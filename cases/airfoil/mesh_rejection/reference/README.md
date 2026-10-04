# Reference data — airfoil/mesh_rejection

Compact series extracted from the archived run, committed so that a replay works
from a clone:

- `corrected_diagnosis.json`
- `independent_cell_geometry_audit.json`

The raw mesh-qualification outputs (`outputs/airfoil_mesh`) are not distributed, because this family is not part of the CFD Forge paper; their inventory and digests are in `manifests/large_assets.json`. Replay does not need them: the deterministic record a replay re-evaluates is `../expected_result.json`, and any series it needs is in this directory.
