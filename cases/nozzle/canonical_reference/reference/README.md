# Reference data — nozzle/canonical_reference

Compact series extracted from the archived run, committed so that a replay works
from a clone:

- (none: this case needs no extracted series)

The full archived evidence for this case is `demo/nozzle_e2e/case_A_reference`, which is
gitignored because of its size; its inventory and digests are in
`manifests/large_assets.json`. Replay does not require it: the deterministic
record a replay re-evaluates is `../expected_result.json`, and any series it
needs is in this directory.
