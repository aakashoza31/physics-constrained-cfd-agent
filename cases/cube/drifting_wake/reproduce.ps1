# Reproduce cube/drifting_wake by replaying the archived evidence. Live execution is
# refused for this family.
Set-Location (Join-Path $PSScriptRoot "..\..\..")
python scripts/run_demo.py --family cube --case drifting_wake --mode replay
