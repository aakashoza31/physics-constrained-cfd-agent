#!/usr/bin/env bash
# Mesh generation and geometric verification only.
#
# Transcription of the mesh half of validation/canonical_reference/run_case.sh
# (frozen authority). The commands, their order and their flags are unchanged:
#
#     blockMesh
#     checkMesh -allTopology -allGeometry
#     grep -q 'Mesh OK'
#     foamPostProcess -func writeCellCentres -time 0
#     foamPostProcess -func writeCellVolumes -time 0
#
# The deterministic gate is unchanged and is NOT bypassed: checkMesh must
# actually report "Mesh OK" in its own log, and every step must return 0, or
# this script exits non-zero.
#
# What changed is only the reporting. The canonical script relies on `set -e`,
# so any failing step aborts the shell with no indication of WHICH command
# failed; the caller then had to guess, and guessed "checkMesh". Each step is
# now run explicitly, its return code recorded, and the whole record written to
# <case>/mesh_steps.json so the failure is attributed to the exact command.
#
# `set -u` is deliberately not enabled here: an unbound-variable abort in a
# diagnostic script destroys the diagnosis. Variables are guarded individually.

set -o pipefail

if [ -z "${1:-}" ]; then
  echo 'mesh_case.sh: no case directory supplied' >&2
  exit 64
fi

# Only source the OpenFOAM environment when the caller has not already done so.
# Re-sourcing etc/bashrc tears down and rebuilds the environment, which is an
# unnecessary hazard when the parent shell is already configured.
if [ -z "${WM_PROJECT_VERSION:-}" ]; then
  # shellcheck disable=SC1090
  . "${FOAM_BASHRC:-/opt/openfoam14/etc/bashrc}"
fi

case_dir="$(realpath "$1" 2>/dev/null)"

if [ -z "$case_dir" ] || [ ! -d "$case_dir" ]; then
  echo "mesh_case.sh: case directory does not exist: $1" >&2
  exit 66
fi

steps_json="$case_dir/mesh_steps.json"
entries=""
failed_step=""
failed_rc=0

record() {
  local name="$1" rc="$2" log="$3"

  if [ -n "$entries" ]; then
    entries="$entries,"
  fi

  entries="$entries
    {\"name\": \"$name\", \"returncode\": $rc, \"log\": \"$log\"}"

  if [ "$rc" -eq 0 ]; then
    printf '[MESH TOOL] step %-28s ok\n' "$name"
  else
    printf '[MESH TOOL] step %-28s FAILED rc=%s\n' "$name" "$rc"
  fi
}

write_steps() {
  printf '{\n  "case": "%s",\n  "openfoam_version": "%s",\n  "failed_step": "%s",\n  "returncode": %s,\n  "steps": [%s\n  ]\n}\n' \
    "$case_dir" "${WM_PROJECT_VERSION:-}" "$failed_step" "$failed_rc" "$entries" \
    > "$steps_json"
}

run_step() {
  local name="$1" log="$2"
  shift 2

  if [ -n "$failed_step" ]; then
    return 0
  fi

  "$@" > "$log" 2>&1
  local rc=$?

  record "$name" "$rc" "$log"

  if [ "$rc" -ne 0 ]; then
    failed_step="$name"
    failed_rc="$rc"
  fi

  return 0
}

# The environment check the caller's preflight already performed
# deterministically. Recorded as a step rather than aborting silently.
if [ "${WM_PROJECT_VERSION:-}" != "14" ]; then
  record "openfoam_v14_environment" 2 ""
  failed_step="openfoam_v14_environment"
  failed_rc=2
  write_steps
  echo "mesh_case.sh: Foundation OpenFOAM 14 required, WM_PROJECT_VERSION='${WM_PROJECT_VERSION:-}'" >&2
  exit 2
fi

record "openfoam_v14_environment" 0 ""

run_step blockMesh "$case_dir/log.blockMesh" \
  blockMesh -case "$case_dir"

run_step checkMesh "$case_dir/log.checkMesh" \
  checkMesh -case "$case_dir" -allTopology -allGeometry

# The deterministic mesh gate. Unchanged in strength: the literal string must be
# present in checkMesh's own output.
if [ -z "$failed_step" ]; then
  if grep -q 'Mesh OK' "$case_dir/log.checkMesh"; then
    record "checkMesh_reports_Mesh_OK" 0 "$case_dir/log.checkMesh"
  else
    record "checkMesh_reports_Mesh_OK" 1 "$case_dir/log.checkMesh"
    failed_step="checkMesh_reports_Mesh_OK"
    failed_rc=1
  fi
fi

run_step writeCellCentres "$case_dir/log.centres" \
  foamPostProcess -case "$case_dir" -func writeCellCentres -time 0

run_step writeCellVolumes "$case_dir/log.volumes" \
  foamPostProcess -case "$case_dir" -func writeCellVolumes -time 0

write_steps

if [ -n "$failed_step" ]; then
  echo "mesh_case.sh: failed at $failed_step (rc=$failed_rc)" >&2
  tail -n 30 "$case_dir/log.$(
    case "$failed_step" in
      blockMesh) echo blockMesh ;;
      checkMesh|checkMesh_reports_Mesh_OK) echo checkMesh ;;
      writeCellCentres) echo centres ;;
      writeCellVolumes) echo volumes ;;
      *) echo blockMesh ;;
    esac
  )" 2>/dev/null >&2
  exit 1
fi

exit 0
