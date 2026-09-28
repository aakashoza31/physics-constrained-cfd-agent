#!/usr/bin/env bash
# Reproduce cube/drifting_wake. Replay by default; --live re-executes OpenFOAM.
set -euo pipefail
cd "$(dirname "$0")/../../.."
MODE=replay
EXTRA=()
if [[ "${1:-}" == "--live" ]]; then
  MODE=live
  EXTRA+=(--i-want-to-run-cfd)
fi
python3 scripts/run_demo.py --family cube --case drifting_wake --mode "$MODE" "${EXTRA[@]}"
