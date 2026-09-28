# Agent Architecture

## Design principle

The architecture separates **reasoning** from **scientific authority**.

The LLM is the orchestration and diagnostic brain. It interprets the user's engineering request, reviews mesh evidence, examines numerical and visual CFD evidence, forms competing hypotheses, and proposes a high-level action.

Deterministic software remains authoritative for geometry bounds, mesh validity, numerical execution, physical admissibility, conservation, stationarity, action permissions, and final acceptance.

This prevents a plausible-sounding model response from turning a failed CFD state into a successful result.

## End-to-end flow

```text
Natural-language prompt
        |
        v
LLM case interpretation
        |
        v
Deterministic scope gate
        |
        v
Structured wedge mesh generation
        |
        v
blockMesh + checkMesh
        |
        v
LLM mesh review
        |
        v
OpenFOAM setup + verified quasi-1D initialization
        |
        v
shockFluid execution
        |
        +------------------------------+
        |                              |
        v                              v
Deterministic numerical evidence    Native CFD images
        |                              |
        +---------------+--------------+
                        v
               Multimodal LLM reasoning
                        |
                        v
                  Proposed action
                        |
                        v
               Deterministic action gate
                        |
          +-------------+----------------+
          |                              |
          v                              v
approved non-ACCEPT action           approved ACCEPT
          |                              |
          v                              v
Deterministic action executor      Scientific validator
          |                              |
          +----------> new CFD state     v
                                   Engineering report
```

## What the LLM receives

The CFD reasoning stage receives a theory-blind structured evidence packet. It can include:

- solver completion and health information
- Courant behavior and timestep information
- inlet and outlet mass flow
- mass-flow mismatch
- transient continuity
- monitor drift
- full-field L2 change
- thermodynamic admissibility
- boundary anomalies / reverse-flow evidence
- throat and outlet flow features
- mesh quality evidence
- localized axial gradients
- iteration history
- qualitative observations from actual CFD field images

The visual observer receives standardized images generated from the latest OpenFOAM cell values:

- Mach field
- static pressure field
- temperature field
- speed field
- mesh cell-center distribution

Visual evidence is explicitly supporting evidence. Numerical diagnostics outrank image interpretation.

## Feedback actions

The action vocabulary is defined in `src/contracts/agent_decision.py`.

### `ACCEPT`

The LLM proposes that no additional CFD action is needed. The deterministic action validator rejects this proposal if solver health, admissibility, conservation, stationarity, boundary evidence, or required anomaly evidence is not acceptable.

### `CONTINUE_RUN`

Continue a healthy, evolving solution from `latestTime` to a bounded later horizon. The LLM chooses the high-level action; deterministic code edits only the allowed `controlDict` entries and executes the continuation.

### `REQUEST_DIAGNOSTIC`

Ask for a focused view of already measured evidence such as timestep behavior, stationarity, conservation, gradients, mesh evidence, or visuals. This action does not change the physics.

### `REFINE_THROAT`

Request extra structured-mesh resolution around the converging/throat/diverging neighborhood. The deterministic executor maps that request to a bounded cell-count change and refuses refinement above the frozen-reference maximum.

### `REFINE_GRADIENT_REGION`

Request refinement in a named axial region, but only when measured gradient evidence marks that region as a candidate for under-resolution.

### `RESTART_CLEAN`

Discard an untrusted numerical state and regenerate/reinitialize the case. This is allowed only when evidence supports an untrusted numerical state.

### `REPAIR_MESH`

The action contract contains this option for mesh-quality failure handling. The current clean nozzle feedback runner emphasizes refinement, continuation, diagnostic acquisition, and clean restart; unsupported mechanical actions fail closed rather than being improvised.

## Why the loop is scientifically useful

Without the loop, the LLM would mostly be a natural-language tool caller and reviewer. The closed loop makes the LLM evaluate the evolving simulation state:

```text
observe -> diagnose -> propose action -> deterministic gate -> execute -> observe again
```

The demonstrated Case A trajectory is:

```text
0.001 s state
-> 17/20 checks pass
-> LLM: UNCONVERGED / CONTINUE_RUN
-> deterministic gate: APPROVED
-> continue existing CFD state to 0.006 s
-> new numerical evidence + new images
-> LLM: ACCEPTABLE / ACCEPT
-> deterministic gate: APPROVED
-> scientific validator: PASS_SINGLE_MESH
```

Cases B and C terminate after one iteration because their first 0.006 s solutions already satisfy all deterministic criteria. The agent is expected to stop when no intervention is needed.

## Theory separation

Quasi-1D theory is used only where explicitly documented:

- to construct the verified startup field
- for deterministic scope/regime screening
- for post-hoc comparison after the autonomous decision

Analytical target values are stripped from the CFD reasoning packet. A fail-closed guard rejects evidence payloads containing forbidden theory/reference target keys.

## Main implementation files

- `scripts/run_nozzle_feedback.py`: feedback-loop orchestrator
- `scripts/run_nozzle_e2e.py`: shared prompt-to-CFD case runner
- `src/agents/nozzle_case_spec_agent.py`: prompt interpretation
- `src/agents/nozzle_demo_agents.py`: mesh review and report generation
- `src/agents/cfd_visual_observer.py`: multimodal qualitative image review
- `src/agents/theory_blind_cfd_agent.py`: structured CFD reasoning call
- `src/reasoning/nozzle_scope_gate.py`: deterministic domain gate
- `src/reasoning/action_validator.py`: action permissions
- `src/reasoning/reference_evidence_adapter.py`: theory-blind evidence construction
- `src/pipeline/nozzle/feedback.py`: bounded action execution primitives
- `src/pipeline/nozzle/feedback_diagnostics.py`: gradients, images, diagnostic fulfillment
- `src/pipeline/nozzle/validate.py`: deterministic CFD checks and final status
