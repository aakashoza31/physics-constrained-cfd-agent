# Reproducibility

The public Level-1 interface is:

    python .\run_level1.py

The program waits for the user to paste the supplied canonical
engineering prompt.

The supplied prompt is located at:

    examples\level1_nozzle\LEVEL1_PROMPT.txt

The prompt is intentionally not silently loaded by the program.

Before running:

    python .\scripts\check_environment.py

Python dependencies are pinned in:

    requirements.txt

Large solver outputs, VTK files, transient OpenFOAM result directories,
API credentials, virtual environments, and temporary run artifacts are
excluded from Git.

Every scientific claim should distinguish between:

1. the validated Test-A reference trajectory,
2. live LLM reasoning replay on saved CFD evidence,
3. experimental fully fresh prompt-to-CFD execution.
