#!/usr/bin/env bash
# Reproduce airfoil/mesh_rejection. Replay by default; --live re-executes OpenFOAM.
set -euo pipefail
cd "$(dirname "$0")/../../.."
MODE=replay
EXTRA=()
if [[ "${1:-}" == "--live" ]]; then
  MODE=live
  EXTRA+=(--i-want-to-run-cfd)
fi
python3 scripts/run_demo.py --family airfoil --case mesh_rejection --mode "$MODE" "${EXTRA[@]}"
