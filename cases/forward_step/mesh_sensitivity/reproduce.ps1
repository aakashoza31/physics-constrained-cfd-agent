# Reproduce forward_step/mesh_sensitivity. Replay by default; -Live re-executes OpenFOAM.
param([switch]$Live)
Set-Location (Join-Path $PSScriptRoot "..\..\..")
$mode = if ($Live) { "live" } else { "replay" }
$extra = if ($Live) { @("--i-want-to-run-cfd") } else { @() }
python scripts/run_demo.py --family forward_step --case mesh_sensitivity --mode $mode @extra
