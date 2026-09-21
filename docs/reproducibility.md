# Reproducibility Guide

## 1. Clone and create a Python environment

Windows PowerShell:

```powershell
git clone <YOUR_REPOSITORY_URL>
cd physics-constrained-cfd-agent
py -3.13 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Linux:

```bash
git clone <YOUR_REPOSITORY_URL>
cd physics-constrained-cfd-agent
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

The host environment needs the Python packages because it runs the orchestration, LLM calls, evidence processing, tests, and image generation.

## 2. Install / expose OpenFOAM Foundation v14

The validated Windows configuration uses WSL2 Ubuntu 24.04 with:

```text
/opt/openfoam14/etc/bashrc
```

Inside WSL, these commands must work after sourcing the bashrc:

```bash
source /opt/openfoam14/etc/bashrc
foamRun -help >/dev/null
blockMesh -help >/dev/null
checkMesh -help >/dev/null
foamPostProcess -help >/dev/null
python3 -c "import numpy; print(numpy.__version__)"
```

OpenFOAM Foundation v14 is the validated runtime. Other OpenFOAM distributions/releases are not assumed interchangeable.

On a native Linux host, the same pipeline detects Linux automatically and uses the configured `OPENFOAM_BASHRC` path.

## 3. Configure the LLM backend

The current implementation uses Gemini through environment variables.

PowerShell:

```powershell
$env:GEMINI_API_KEY = "YOUR_API_KEY"
$env:GEMINI_MODEL = "gemini-3.5-flash-lite"
```

Bash:

```bash
export GEMINI_API_KEY="YOUR_API_KEY"
export GEMINI_MODEL="gemini-3.5-flash-lite"
```

Do not commit API keys.

`.env.example` documents the variable names; this repository does not automatically load a `.env` file.

## 4. Check the environment

```powershell
python .\scripts\check_environment.py
```

or:

```bash
python scripts/check_environment.py
```

## 5. Reproduce the demonstrated Windows/WSL campaign

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\run_repro_campaign.ps1
```

Outputs go to:

```text
demo/runs/nozzle_feedback/
```

The script runs A, B, C and creates:

```text
demo/runs/nozzle_feedback/CAMPAIGN_SUMMARY.json
```

## 6. Manual per-case commands

### Case A feedback demonstration

```powershell
python .\scripts\run_nozzle_feedback.py `
    --case A `
    --out .\demo\runs\nozzle_feedback `
    --feedback-demo `
    --feedback-first-end-time 0.001 `
    --end-time 0.006 `
    --max-end-time 0.020 `
    --feedback-increment 0.005 `
    --max-iterations 4 `
    --max-diagnostic-requests 2 `
    --require-visuals
```

### Case B

```powershell
python .\scripts\run_nozzle_feedback.py `
    --case B `
    --out .\demo\runs\nozzle_feedback `
    --end-time 0.006 `
    --max-end-time 0.020 `
    --feedback-increment 0.005 `
    --max-iterations 4 `
    --max-diagnostic-requests 2 `
    --require-visuals
```

### Case C

Use the Case B command with `--case C`.

## 7. One-pass parameterized pipeline

For debugging or non-feedback comparison:

```powershell
python .\scripts\run_nozzle_e2e.py --case A
python .\scripts\run_nozzle_e2e.py --case B
python .\scripts\run_nozzle_e2e.py --case C
```

Natural-language examples:

```powershell
python .\scripts\run_nozzle_e2e.py --prompt-file .\examples\nozzle_e2e\PROMPT_B.txt
```

The closed-loop research claim should be demonstrated with `run_nozzle_feedback.py`, not only the one-pass runner.


## Custom closed-loop prompt

After editing `examples/nozzle_e2e/PROMPT_TEMPLATE.txt` within the documented scope:

```powershell
python .\scripts\run_nozzle_feedback.py `
    --prompt-file .\examples\nozzle_e2e\PROMPT_TEMPLATE.txt `
    --out .\demo\runs\custom_nozzle `
    --end-time 0.006 `
    --max-end-time 0.020 `
    --feedback-increment 0.005 `
    --max-iterations 4 `
    --max-diagnostic-requests 2 `
    --require-visuals
```

The scope gate will reject parameter combinations outside the declared domain before CFD is trusted.

## 8. Rebuild a sanitized campaign summary

```powershell
python .\scripts\build_nozzle_campaign_summary.py `
    --root .\demo\runs\nozzle_feedback `
    --out .\demo\runs\nozzle_feedback\CAMPAIGN_SUMMARY.json
```

The summary intentionally excludes machine-specific runtime paths and model-provider labels.

## 9. Run tests

```powershell
python -m pytest -q
python .\validation\canonical_reference\test_validation.py
```

The canonical-equivalence tests protect the scientific recipe from accidental changes.

## 10. Expected qualitative behavior

A successful reproduction should show:

```text
A: CONTINUE_RUN -> ACCEPT, 2 CFD iterations, PASS_SINGLE_MESH
B: ACCEPT, 1 CFD iteration, PASS_SINGLE_MESH
C: ACCEPT, 1 CFD iteration, PASS_SINGLE_MESH
```

Exact wall-clock time is machine-dependent.
