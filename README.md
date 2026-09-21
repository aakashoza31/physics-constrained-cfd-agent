# Physics-Constrained CFD Agent

Physics-constrained autonomous CFD research prototype coupling multimodal
LLM reasoning with deterministic scientific and numerical validation.

## Level-1 validation case

The current validated reference problem is an axisymmetric conical
converging-diverging nozzle with compressible inviscid air flow.

Physics envelope:

- calorically perfect air
- gamma = 1.4
- R = 287 J/(kg K)
- Euler / inviscid flow
- adiabatic slip walls
- OpenFOAM Foundation v14
- axisymmetric converging-diverging nozzle
- theory-blind LLM CFD diagnosis

The LLM proposes interpretations and actions. It does not have final
authority over CFD correctness or convergence.

Deterministic Python logic evaluates solver health, positivity,
conservation, stationarity, mesh quality, provenance, boundary behavior,
and action permissions before an action can reach OpenFOAM.

## User workflow

First install the Python dependencies:

    python -m pip install -r requirements.txt

Check the environment:

    python .\scripts\check_environment.py

Start the Level-1 interface:

    python .\run_level1.py

The program asks the user to paste the canonical Level-1 engineering
prompt.

The prompt is supplied separately at:

    examples\level1_nozzle\LEVEL1_PROMPT.txt

The program does not silently insert the validation prompt.

The current Level-1 interface intentionally rejects unrelated engineering
prompts because this repository snapshot is scoped to the canonical
validation problem actually studied.

## Scientific loop

User prompt
-> engineering interpretation
-> geometry
-> mesh
-> deterministic mesh validation
-> OpenFOAM
-> numerical diagnostics
-> CFD visualizations
-> multimodal LLM reasoning
-> proposed scientific action
-> deterministic Python validator
-> approved action only
-> OpenFOAM continuation / diagnostic / safe stop
-> post-hoc analytical comparison

## Validated autonomous trajectory

The canonical Test-A case was autonomously continued through:

    1.000 ms
    -> Gemini: UNCONVERGED / CONTINUE_RUN
    -> deterministic validator: APPROVED

    1.100 ms
    -> Gemini: UNCONVERGED / CONTINUE_RUN
    -> deterministic validator: APPROVED

    1.200 ms
    -> strict convergence criterion remained marginally unsatisfied
    -> no false ACCEPT

No human boundary-condition edit, remeshing, or restart occurred during
these continuation iterations.

## Level-1 result at 1.2 ms

Exit Mach:

    CFD       1.48790
    Theory    1.50440
    Error    -1.10 %

Exit pressure:

    CFD       54.725 kPa
    Theory    54.134 kPa
    Error    +1.09 %

Exit temperature:

    CFD       208.172 K
    Theory    206.520 K
    Error    +0.80 %

Exit velocity:

    CFD       430.319 m/s
    Theory    433.361 m/s
    Error    -0.70 %

The configured boundary mass-flow mismatch criterion was 1.0 percent.

The final measured mismatch was approximately 1.077 percent.

Therefore the autonomous system correctly withheld a fully converged
steady-state ACCEPT decision.

## Theory-blind reasoning

The analytical exit targets are not supplied to the CFD reasoning agent.

Quasi-1D theory is used only where explicitly documented, including the
validated initialization strategy and post-hoc verification.

The analytical exit comparison is revealed after the autonomous agent
decision.

## LLM backend

The validated initial implementation uses Gemini.

The CFD physics, numerical policy, diagnostics, action validation, and
scientific authority are intentionally separate from the LLM.

A provider abstraction for alternative multimodal models
is planned so that changing the reasoning model does not change the
deterministic CFD validation rules.

## Reference environment

The current validated development environment is:

- Windows
- Python 3.13
- WSL2
- Ubuntu 24.04
- OpenFOAM Foundation v14
- Gmsh 4.15.x

API credentials must be supplied through environment variables.

Example:

    $env:GEMINI_API_KEY = "your-key"
    $env:GEMINI_MODEL = "gemini-3.5-flash-lite"

Never commit API keys.

## Current reproducibility status

The repository contains the cleaned scientific code required by the
Level-1 workflow and the canonical prompt interface.

The successful Test-A replay and autonomous continuation constitute the
current validated reference trajectory.

Fresh prompt-to-CFD execution is still being hardened and should
currently be treated as experimental rather than universally reliable.

## Scope

This repository demonstrates a physics-constrained autonomous CFD
research prototype.

It is not a universal CFD agent and is not claimed as a replacement for
commercial CFD software.

The current canonical nozzle result is strong preliminary Level-1
verification, not a claim of fully converged steady-state validation.

## One-command Level-1 reproduction

For the canonical Level-1 experiment, run:

    python .\run_level1.py

If `GEMINI_API_KEY` is not already configured, the program securely asks
for the user's own Gemini API key using hidden terminal input. The key is
kept only in process memory for that run and is not written to the
repository.

The program then runs the OpenFOAM/Gemini production preflight and asks
the user to paste the canonical prompt supplied at:

    examples\level1_nozzle\LEVEL1_PROMPT.txt

After pasting the complete prompt, type:

    END

on a new line.

The intended reviewer workflow is therefore:

    git clone <repository>
    cd physics-constrained-cfd-agent
    python -m pip install -r requirements.txt
    python .\run_level1.py

The user supplies their own API credential. No API credential is stored
in this repository.
