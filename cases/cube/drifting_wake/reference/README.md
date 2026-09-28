# Reference data — cube/drifting_wake

Compact series extracted from the archived run, committed so that a replay works
from a clone:

- `force_history.json`
- `force_statistics.json`
- `lateral_mode.json`

The full archived evidence for this case is `handoff/CFD_Agent_Handoff_20260924_1610/family3_baseline_compact`, which is
gitignored because of its size; its inventory and digests are in
`manifests/large_assets.json`. Replay does not require it: the deterministic
record a replay re-evaluates is `../expected_result.json`, and any series it
needs is in this directory.
