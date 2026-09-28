# Reproduce nozzle/canonical_reference. Replay by default; -Live re-executes OpenFOAM.
param([switch]$Live)
Set-Location (Join-Path $PSScriptRoot "..\..\..")
$mode = if ($Live) { "live" } else { "replay" }
$extra = if ($Live) { @("--i-want-to-run-cfd") } else { @() }
python scripts/run_demo.py --family nozzle --case canonical_reference --mode $mode @extra
