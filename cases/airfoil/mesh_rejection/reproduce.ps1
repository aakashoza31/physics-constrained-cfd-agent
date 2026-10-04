# Reproduce airfoil/mesh_rejection by replaying the archived evidence. Live execution is
# refused for this family.
Set-Location (Join-Path $PSScriptRoot "..\..\..")
python scripts/run_demo.py --family airfoil --case mesh_rejection --mode replay
