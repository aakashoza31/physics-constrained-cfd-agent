# Reproducibility guide

What can be reproduced, and how:

| What | Needs | Section |
|---|---|---|
| Registered-case replay | Python only | 0 |
| Paper figures | Python only | 0 |
| Controller comparison | Zenodo data archive (DOI 10.5281/zenodo.23148676), `GEMINI_API_KEY` | 0 |
| Nozzle and forward-step agent runs | `GEMINI_API_KEY`, OpenFOAM Foundation v14 | 1-7 |

**Model outputs are not reproducible exactly.** Temperature 0 does not make the
provider deterministic (in the cube diagnosis, one of three identical calls gave a
different diagnosis), and the historical agent sessions ran from uncommitted
development trees. A rerun reproduces the workflow, the artifacts and the
deterministic checks, not the exact model outputs or the historical execution
byte for byte.

## 0. Without a solver

```bash
# replay a registered case: re-derives the deterministic decision, no solver, no key
python scripts/run_demo.py --list
python scripts/run_demo.py --family nozzle --case canonical_reference --mode replay

# paper figures from archived data (writes paper/cfd_forge/figures/)
python paper/cfd_forge/scripts/make_figures.py
python paper/cfd_forge/scripts/make_mesh_field_figures.py
python paper/cfd_forge/scripts/make_agent_loop_figure.py

# controller comparison (needs the Zenodo session archive and a key)
python paper/cfd_forge/scripts/controller_comparison.py --demo-root <session-archive>/demo \
    --cube-logs <session-archive>/CFD_Verification_Package_20260929/03_cube/logs
```

The archived controller-comparison run is
`evidence/controller_comparison/20261001T213031Z/`. The native OpenFOAM case
files of every run in the paper (initial or restart state, final state, mesh,
settings and logs) are in `native_cases/` of the Zenodo data archive; see its
`native_cases/README.md`. The default backend of
`scripts/run_demo.py` and `scripts/run_agent.py` is a deterministic, no-key demo
mode; it is not the configuration of the paper's agent runs.

## 1. Clone and create a Python environment

Windows PowerShell:

```powershell
git clone https://github.com/aakashoza31/physics-constrained-cfd-agent
cd physics-constrained-cfd-agent
py -3.13 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Linux:

```bash
git clone https://github.com/aakashoza31/physics-constrained-cfd-agent
cd physics-constrained-cfd-agent
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

The host environment needs the Python packages because it runs the orchestration, LLM calls, evidence processing, tests, and image generation. `google-genai` is required for the agent runs.

## 2. Install / expose OpenFOAM Foundation v14

The paper's runs used OpenFOAM Foundation v14, build `14-7b05503f98a8`, in WSL 2 (Ubuntu 24.04) on Windows, with:

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

OpenFOAM Foundation v14 is the only runtime the results are claimed for. Other OpenFOAM distributions/releases are not assumed interchangeable.

The WSL distribution is read from `OPENFOAM_WSL_DISTRO` (default `Ubuntu-24.04`) and the bashrc from `OPENFOAM_BASHRC`. Field-evolution videos launch ParaView through `CFD_WSL_DISTRO` (see `docs/field_evolution_video.md`). On a native Linux host, the same pipeline detects Linux automatically and uses the configured `OPENFOAM_BASHRC` path.

## 3. Configure the LLM backend

The agent runs use the Google Gemini API through the `google-genai` SDK, configured by environment variables. All stages read the model from `GEMINI_MODEL` through `src/agents/llm_provenance.py` (default `gemini-3.5-flash-lite`, the model of the paper's text calls). In the archived step sessions the field observer still had its own default and used `gemini-3.6-flash`; the released observer records the model it uses.

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

## 5. Rerun the nozzle campaign (Windows/WSL)

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\run_repro_campaign.ps1
```

Outputs go to:

```text
demo/runs/nozzle_feedback/
```

The script (`scripts/run_repro_campaign.ps1`; `scripts/run_repro_campaign.sh` on Linux) runs the Case A continuation demonstration, B and C, and creates:

```text
demo/runs/nozzle_feedback/CAMPAIGN_SUMMARY.json
```

## 6. Manual per-case commands

### Case A continuation run (feedback demonstration)

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

The canonical Case A run (session N1) and Cases B and C (N2, N3) were single executions to 6 ms with this runner:

```powershell
python .\scripts\run_nozzle_e2e.py --case A
python .\scripts\run_nozzle_e2e.py --case B
python .\scripts\run_nozzle_e2e.py --case C
```

Natural-language examples:

```powershell
python .\scripts\run_nozzle_e2e.py --prompt-file .\examples\nozzle_e2e\PROMPT_B.txt
```

The corrective loop is demonstrated with `run_nozzle_feedback.py`.

## Forward-facing step

```bash
python scripts/run_forward_step_2d.py --request-file examples/forward_step_2d/CASE_B_MACH20.txt
python scripts/run_forward_step_2d.py --request "..." --plan-only
```

Request files for the paper's step sessions are in `examples/forward_step_2d/`.
Outputs go to `demo/forward_step_2d/` unless `--out` is given. The same
`GEMINI_API_KEY`, `GEMINI_MODEL` and OpenFOAM settings apply.

## Action vocabularies

| Family | Actions | Defined in |
|---|---|---|
| nozzle | `ACCEPT`, `CONTINUE_RUN`, `REQUEST_DIAGNOSTIC`, `REFINE_THROAT`, `REFINE_GRADIENT_REGION`, `REPAIR_MESH`, `RESTART_CLEAN`, `REJECT_OUTSIDE_DOMAIN` | `src/contracts/agent_decision.py` |
| forward step | `ACCEPT`, `CONTINUE_RUN`, `EXTEND_END_TIME`, `REDUCE_MAX_CO`, `REFINE_MESH`, `REBUILD_FROM_VALIDATED_SPEC`, `REQUEST_CLARIFICATION`, `REJECT_UNSUPPORTED`, `FAIL_SAFELY` | `src/reasoning/forward_step_actions.py` |


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

## 10. Archived behaviour

The archived sessions recorded:

```text
A (continuation run, N6): CONTINUE_RUN, CONTINUE_RUN, ACCEPT; 1 ms FAIL -> 6 ms PASS_SINGLE_MESH
A (canonical run, N1):    ACCEPT, single execution to 6 ms, PASS_SINGLE_MESH
B:                        ACCEPT, 1 CFD iteration, PASS_SINGLE_MESH
C:                        ACCEPT, 1 CFD iteration, PASS_SINGLE_MESH
```

A rerun should reach the same deterministic verdicts for the same CFD states, but
the model's proposals, and therefore the number of iterations, can differ
because model outputs are not reproducible exactly. Wall-clock time is
machine-dependent.
