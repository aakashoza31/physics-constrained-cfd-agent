#!/usr/bin/env bash
# Full canonical per-case sequence.
# Transcription of validation/canonical_reference/run_case.sh (frozen authority).
# The orchestrator normally calls mesh_case.sh, initialize.py and execute.py
# separately so that each event in the stream corresponds to one real action;
# this script is the equivalent single-command path.
set -eo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
bash "$here/mesh_case.sh" "$1"
source "${FOAM_BASHRC:-/opt/openfoam14/etc/bashrc}"
set -u
case="$(realpath "$1")"
python3 "$here/initialize.py" "$case" > "$case/log.initialize" 2>&1
python3 "$here/execute.py" "$case" --events
