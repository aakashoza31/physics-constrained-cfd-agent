#!/usr/bin/env bash
# Reproduce airfoil/mesh_rejection by replaying the archived evidence. Live execution is
# refused for this family.
set -euo pipefail
cd "$(dirname "$0")/../../.."
python3 scripts/run_demo.py --family airfoil --case mesh_rejection --mode replay
