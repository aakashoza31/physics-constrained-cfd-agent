#!/usr/bin/env bash
set -eo pipefail
cd "$(dirname "$0")"
root="$1"
python3 build.py "$root/time_half" --scale 1 --co 0.2
bash run_case.sh "$root/time_half"
python3 validate.py "$root/time_half"
python3 build.py "$root/angle_half" --scale 1 --angle 2.5
bash run_case.sh "$root/angle_half"
python3 validate.py "$root/angle_half"
python3 build.py "$root/startup_perturbed" --scale 1 --perturb 0.02
bash run_case.sh "$root/startup_perturbed"
python3 validate.py "$root/startup_perturbed"
