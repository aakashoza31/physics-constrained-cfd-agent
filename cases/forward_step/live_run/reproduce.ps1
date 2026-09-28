# Reproduce forward_step/live_run. Replay by default; -Live re-executes OpenFOAM.
param([switch]$Live)
Set-Location (Join-Path $PSScriptRoot "..\..\..")
$mode = if ($Live) { "live" } else { "replay" }
$extra = if ($Live) { @("--i-want-to-run-cfd") } else { @() }
python scripts/run_demo.py --family forward_step --case live_run --mode $mode @extra
