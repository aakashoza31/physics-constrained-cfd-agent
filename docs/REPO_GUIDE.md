# Repository Guide

This guide explains what each major file in the clean three-case repository does.

## Top level

| Path | Role |
| --- | --- |
| `README.md` | Main project overview, results, architecture, quickstart, and scope. |
| `requirements.txt` | Host Python dependencies for orchestration, LLM calls, tests, and visualization. |
| `.env.example` | Names of environment variables used for the LLM and OpenFOAM runtime. It contains no secret. |
| `.gitignore` | Excludes virtual environments, caches, raw runtime cases, logs, and generated demo runs. |

## Configuration

| Path | Role |
| --- | --- |
| `configs/cfd_reasoning_policy_v2.yaml` | Structured policy supplied to the CFD reasoning layer. Defines reasoning expectations without replacing deterministic checks. |
| `configs/nozzles/case_A_reference.yaml` | Human-readable canonical Case A declaration. |
| `configs/nozzles/case_B_geometry.yaml` | Case B declaration with the larger exit radius. |
| `configs/nozzles/case_C_conditions.yaml` | Case C declaration with the higher reservoir pressure. |
| `configs/nozzles/case_template.yaml` | Documented template for nearby cases. |
| `configs/nozzles/README.md` | Short explanation of the case configuration files. |

## Natural-language examples

| Path | Role |
| --- | --- |
| `examples/nozzle_e2e/PROMPT_A.txt` | Natural-language canonical request. |
| `examples/nozzle_e2e/PROMPT_B.txt` | Natural-language geometry-transfer request. |
| `examples/nozzle_e2e/PROMPT_C.txt` | Natural-language operating-condition-transfer request. |
| `examples/nozzle_e2e/PROMPT_TEMPLATE.txt` | Copy/edit template for a nearby nozzle request. |

## User-facing scripts

| Path | Role |
| --- | --- |
| `scripts/check_environment.py` | Checks host Python dependencies, WSL/OpenFOAM availability, and whether an API key is configured. |
| `scripts/run_nozzle_e2e.py` | Shared prompt-to-mesh-to-CFD pipeline. Performs one CFD reasoning/acceptance pass. Used by the feedback runner for the initial iteration. |
| `scripts/run_nozzle_feedback.py` | Main closed-loop multimodal agent. Repeats CFD reasoning and executes approved actions until acceptance or a bounded stop. |
| `scripts/run_repro_campaign.ps1` | Reproduces the demonstrated A/B/C campaign on the validated Windows/WSL environment. |
| `scripts/run_repro_campaign.sh` | Linux-host counterpart for the same campaign. |
| `scripts/build_nozzle_campaign_summary.py` | Reads A/B/C `feedback_summary.json` files and creates one sanitized combined summary. |

## Core contracts

| Path | Role |
| --- | --- |
| `src/contracts/problem_spec.py` | General engineering problem/geometry/operating-condition data structures. |
| `src/contracts/cfd_evidence.py` | Typed evidence packet consumed by the CFD reasoning layer. |
| `src/contracts/agent_decision.py` | Diagnosis/action vocabulary such as `ACCEPT`, `CONTINUE_RUN`, refinement, diagnostic request, and clean restart. |

## LLM-facing agents

| Path | Role |
| --- | --- |
| `src/agents/nozzle_case_spec_agent.py` | Parses a natural-language nozzle request into a parameterized case specification. |
| `src/agents/nozzle_demo_agents.py` | LLM mesh review and final engineering-summary helpers used by the current demo pipeline. |
| `src/agents/theory_blind_cfd_agent.py` | Sends theory-blind numerical/visual evidence to the LLM and requests a structured diagnosis/action. |
| `src/agents/cfd_visual_observer.py` | Sends standardized CFD field images to the multimodal model for qualitative observation only. |
| `src/agents/llm_provenance.py` | Records whether a reasoning result came from the LLM or an explicitly enabled deterministic fallback. |
| `src/agents/cfd_request_agent.py` | Earlier/general request-interpreter abstraction retained for research reuse. |
| `src/agents/mesh_adaptation_agent.py` | Earlier/general mesh-adaptation reasoning component retained for research reuse. |
| `src/agents/mesh_planner_agent.py` | Earlier/general mesh-planning abstraction retained for research reuse. |
| `src/agents/nozzle_design_agent.py` | Earlier/general nozzle-design reasoning component retained for reuse. |
| `src/agents/openfoam_setup_agent.py` | Earlier/general OpenFOAM setup reasoning abstraction retained for reuse. |

## Deterministic reasoning and safety

| Path | Role |
| --- | --- |
| `src/reasoning/nozzle_scope_gate.py` | Rejects case specifications outside the declared physics/parameter envelope before CFD runs. |
| `src/reasoning/reference_evidence_adapter.py` | Converts deterministic CFD validation output into the theory-blind evidence packet. |
| `src/reasoning/evidence_packet.py` | Fail-closed theory/reference leakage guard for autonomous reasoning payloads. |
| `src/reasoning/nozzle_diagnosis.py` | Wrapper around the theory-blind CFD reasoning call plus explicit provenance/fallback behavior. |
| `src/reasoning/action_validator.py` | Deterministically approves/rejects each proposed LLM action. |
| `src/reasoning/diagnostics_adapter.py` | Adapter used by earlier/general diagnostics flow. |
| `src/reasoning/initialization_policy_adapter.py` | Adapter for initialization-policy evidence. |
| `src/reasoning/paper_safety_gate.py` | Earlier/general safety gate retained for research history/reuse; the clean nozzle path relies on the explicit action validator and scope gate. |

## OpenFOAM runtime and nozzle pipeline

| Path | Role |
| --- | --- |
| `src/pipeline/foam_runtime.py` | Bridges the host process to either WSL2 or native Linux OpenFOAM, performs preflight, stages code, and copies evidence. |
| `src/pipeline/nozzle/spec.py` | Parameterized nozzle geometry, thermodynamics, mesh resolution, and manifest logic. |
| `src/pipeline/nozzle/build.py` | Writes the OpenFOAM case using the validated numerical recipe. |
| `src/pipeline/nozzle/initialize.py` | Creates and verifies the explicit per-cell quasi-1D startup state. |
| `src/pipeline/nozzle/execute.py` | Bounded serial `foamRun`/`shockFluid` execution and progress monitoring. |
| `src/pipeline/nozzle/validate.py` | Recomputes deterministic scientific acceptance checks from fields/logs/monitors. |
| `src/pipeline/nozzle/foamio.py` | Reads/writes OpenFOAM field and dictionary data used by the pipeline. |
| `src/pipeline/nozzle/mesh_case.sh` | Runtime shell sequence for `blockMesh`, `checkMesh`, cell centers, and cell volumes. |
| `src/pipeline/nozzle/run_case.sh` | Runtime shell entry used by the case execution path. |
| `src/pipeline/nozzle/feedback.py` | Mechanical implementations of approved feedback actions such as continuation and bounded refinement. |
| `src/pipeline/nozzle/export_feedback_snapshot.py` | Exports latest native OpenFOAM cell values into a compact snapshot for diagnostics/visualization. |
| `src/pipeline/nozzle/feedback_diagnostics.py` | Gradient localization, native field-image generation, diagnostic-request fulfillment, and evidence augmentation. |

## Reporting

| Path | Role |
| --- | --- |
| `src/reporting/event_stream.py` | Emits/archives stage-by-stage events such as ORCHESTRATOR, MESH TOOL, EXECUTOR, LLM, ACTION VALIDATOR, and SCIENTIFIC VALIDATOR. |
| `src/reporting/cfd_results_package.py` | General results packaging helper retained from the wider research prototype. |

## Earlier reusable CFD/geometry modules

These are retained because the repository grew from a broader autonomous-meshing/CFD prototype. They are not the authoritative implementation of the current A/B/C nozzle path.

| Path | Role |
| --- | --- |
| `src/cad/nozzle_generator.py` | General nozzle CAD generation helper. |
| `src/geometry/nozzle_analyzer.py` | General nozzle geometry analysis helper. |
| `src/meshing/nozzle_mesher.py` | General meshing helper from the wider prototype. |
| `src/openfoam/executor.py` | Earlier/general OpenFOAM execution abstraction. |
| `src/openfoam/fluid_euler_builder.py` | Earlier Euler-case builder. |
| `src/openfoam/production_euler_builder.py` | Earlier production-case builder. |
| `src/openfoam/regime_aware_builder.py` | Earlier regime-aware setup builder. |
| `src/openfoam/regime_policy.py` | Earlier regime-policy helper. |
| `src/openfoam/stability_supervisor.py` | Earlier stability-supervision logic. |
| `src/openfoam/visualization.py` | Earlier visualization helper. |
| `src/cfd/diagnostics.py` | General diagnostics utilities. |

## Tests

| Path | Role |
| --- | --- |
| `tests/nozzle_e2e/conftest.py` | Shared test fixtures. |
| `tests/nozzle_e2e/test_spec.py` | Nozzle-specification and thermodynamic checks. |
| `tests/nozzle_e2e/test_scope_gate.py` | In-scope/out-of-scope behavior. |
| `tests/nozzle_e2e/test_case_spec_agent.py` | Prompt interpretation behavior. |
| `tests/nozzle_e2e/test_mesh_stage.py` | Mesh-stage command/evidence handling. |
| `tests/nozzle_e2e/test_foam_runtime.py` | WSL/Linux runtime bridge behavior. |
| `tests/nozzle_e2e/test_evidence_adapter.py` | Theory-blind evidence construction and action-validation inputs. |
| `tests/nozzle_e2e/test_event_stream.py` | Event-stream behavior. |
| `tests/nozzle_e2e/test_orchestrator.py` | End-to-end orchestration invariants. |
| `tests/nozzle_e2e/test_feedback_loop.py` | Closed-loop action executor and iteration logic. |
| `tests/nozzle_e2e/test_feedback_diagnostics.py` | Restart-aware diagnostics, images/evidence safety, and feedback-specific behavior. |
| `tests/nozzle_e2e/test_canonical_equivalence.py` | Protects the parameterized pipeline against accidental changes to the frozen canonical numerical recipe. |

## Frozen reference campaign

`validation/canonical_reference/` is the scientific anchor. It contains the validated canonical case builder, initializer, solver executor, validator, sensitivity-study scripts, result JSON/CSV files, and reference figures.

Important files:

| Path | Role |
| --- | --- |
| `validation/canonical_reference/README.md` | Full reference-campaign explanation and reproduction instructions. |
| `build.py` | Writes the canonical OpenFOAM case. |
| `initialize.py` | Writes the canonical startup fields. |
| `execute.py` | Runs the canonical bounded OpenFOAM solver. |
| `validate.py` | Computes the canonical acceptance metrics. |
| `run_case.sh`, `run_sensitivity.sh`, `Allrun`, `RunReference.ps1` | Reproduction wrappers. |
| `test_validation.py` | Reference validation regression tests. |
| `results/` | Compact numerical results from the reference campaign. |
| `figures/` | Reference plots. |

## Public result summary

| Path | Role |
| --- | --- |
| `demo/published_campaign/CAMPAIGN_SUMMARY.json` | Sanitized compact A/B/C result summary with no machine paths or API credentials. |
| `demo/published_campaign/README.md` | Explains what the summary proves and what raw runtime artifacts are intentionally omitted. |
