#!/usr/bin/env bash
# Reproduce nozzle/condition_variation. Replay by default; --live re-executes OpenFOAM.
set -euo pipefail
cd "$(dirname "$0")/../../.."
MODE=replay
EXTRA=()
if [[ "${1:-}" == "--live" ]]; then
  MODE=live
  EXTRA+=(--i-want-to-run-cfd)
fi
python3 scripts/run_demo.py --family nozzle --case condition_variation --mode "$MODE" "${EXTRA[@]}"
