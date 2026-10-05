#!/usr/bin/env bash
# Reproduce forward_step/step_height_010. Replay by default; --live re-executes OpenFOAM.
set -euo pipefail
cd "$(dirname "$0")/../../.."
MODE=replay
EXTRA=()
if [[ "${1:-}" == "--live" ]]; then
  MODE=live
  EXTRA+=(--i-want-to-run-cfd)
fi
python3 scripts/run_demo.py --family forward_step --case step_height_010 --mode "$MODE" "${EXTRA[@]}"
