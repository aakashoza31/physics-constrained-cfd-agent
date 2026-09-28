# Reference data — airfoil/mesh_rejection

Compact series extracted from the archived run, committed so that a replay works
from a clone:

- `corrected_diagnosis.json`
- `independent_cell_geometry_audit.json`

The full archived evidence for this case is `outputs/airfoil_mesh`, which is
gitignored because of its size; its inventory and digests are in
`manifests/large_assets.json`. Replay does not require it: the deterministic
record a replay re-evaluates is `../expected_result.json`, and any series it
needs is in this directory.
