#!/usr/bin/env bash
set -eo pipefail
source "${FOAM_BASHRC:-/opt/openfoam14/etc/bashrc}"
set -u
case="$(realpath "$1")"
blockMesh -case "$case" > "$case/log.blockMesh" 2>&1
checkMesh -case "$case" -allTopology -allGeometry > "$case/log.checkMesh" 2>&1
grep -q 'Mesh OK' "$case/log.checkMesh"
foamPostProcess -case "$case" -func writeCellCentres -time 0 > "$case/log.centres" 2>&1
foamPostProcess -case "$case" -func writeCellVolumes -time 0 > "$case/log.volumes" 2>&1
python3 "$(dirname "$0")/initialize.py" "$case" > "$case/log.initialize" 2>&1
python3 "$(dirname "$0")/execute.py" "$case"
