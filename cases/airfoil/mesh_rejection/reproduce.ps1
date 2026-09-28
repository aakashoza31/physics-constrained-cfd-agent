# Reproduce airfoil/mesh_rejection. Replay by default; -Live re-executes OpenFOAM.
param([switch]$Live)
Set-Location (Join-Path $PSScriptRoot "..\..\..")
$mode = if ($Live) { "live" } else { "replay" }
$extra = if ($Live) { @("--i-want-to-run-cfd") } else { @() }
python scripts/run_demo.py --family airfoil --case mesh_rejection --mode $mode @extra
