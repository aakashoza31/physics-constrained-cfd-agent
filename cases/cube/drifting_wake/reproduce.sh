#!/usr/bin/env bash
# Reproduce cube/drifting_wake by replaying the archived evidence. Live execution is
# refused for this family.
set -euo pipefail
cd "$(dirname "$0")/../../.."
python3 scripts/run_demo.py --family cube --case drifting_wake --mode replay
