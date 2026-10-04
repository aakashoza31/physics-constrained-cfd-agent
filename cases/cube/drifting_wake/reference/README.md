# Reference data — cube/drifting_wake

Compact series extracted from the archived run, committed so that a replay works
from a clone:

- `force_history.json`
- `force_statistics.json`
- `lateral_mode.json`

The archived run is in the Zenodo archive (DOI to be added on release) under `CFD_Verification_Package_20260929/03_cube` (originally `handoff/CFD_Agent_Handoff_20260924_1610/family3_baseline_compact`); it is not in this repository. Its inventory and digests are in `manifests/large_assets.json`. Replay does not need them: the deterministic record a replay re-evaluates is `../expected_result.json`, and any series it needs is in this directory.
