# Reproduce nozzle/geometry_variation. Replay by default; -Live re-executes OpenFOAM.
param([switch]$Live)
Set-Location (Join-Path $PSScriptRoot "..\..\..")
$mode = if ($Live) { "live" } else { "replay" }
$extra = if ($Live) { @("--i-want-to-run-cfd") } else { @() }
python scripts/run_demo.py --family nozzle --case geometry_variation --mode $mode @extra
