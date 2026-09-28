# Reference data — forward_step/iterative_correction

Compact series extracted from the archived run, committed so that a replay works
from a clone:

- (none: this case needs no extracted series)

The full archived evidence for this case is `demo/forward_step_2d/case_H_iterative_short_run`, which is
gitignored because of its size; its inventory and digests are in
`manifests/large_assets.json`. Replay does not require it: the deterministic
record a replay re-evaluates is `../expected_result.json`, and any series it
needs is in this directory.
