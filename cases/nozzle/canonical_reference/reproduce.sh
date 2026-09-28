#!/usr/bin/env bash
# Reproduce nozzle/canonical_reference. Replay by default; --live re-executes OpenFOAM.
set -euo pipefail
cd "$(dirname "$0")/../../.."
MODE=replay
EXTRA=()
if [[ "${1:-}" == "--live" ]]; then
  MODE=live
  EXTRA+=(--i-want-to-run-cfd)
fi
python3 scripts/run_demo.py --family nozzle --case canonical_reference --mode "$MODE" "${EXTRA[@]}"
