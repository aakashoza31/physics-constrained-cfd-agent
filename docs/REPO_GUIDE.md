# Repository Guide

This guide explains what the major files do for the two registered families of the CFD Forge paper (nozzle and 2-D forward-facing step), the cube diagnostic study and the paper scripts. Code that is present but not part of the paper (the 3-D forward step, the airfoil mesh study, the backward-facing step and the CAD→Gmsh prototype) is listed at the end.

## Top level

| Path | Role |
| --- | --- |
| `README.md` | Main project overview, results, architecture, quickstart, and scope. |
| `requirements.txt` | Host Python dependencies; `google-genai` is required for the agent runs. Versions used during development are in `requirements.txt.pinned`. |
| `CITATION.cff`, `.zenodo.json` | Citation and archive metadata. |
| `.env.example` | Environment variables used for the LLM (`GEMINI_API_KEY`, `GEMINI_MODEL`) and the OpenFOAM/ParaView runtime (`OPENFOAM_WSL_DISTRO`, `OPENFOAM_BASHRC`, `CFD_WSL_DISTRO`). It contains no secret. |
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
| `configs/forward_step/` | Configurations of the experimental 3-D forward step (not part of the paper). |

## Natural-language examples

| Path | Role |
| --- | --- |
| `examples/nozzle_e2e/PROMPT_A.txt` | Natural-language canonical request. |
| `examples/nozzle_e2e/PROMPT_B.txt` | Natural-language geometry-transfer request. |
| `examples/nozzle_e2e/PROMPT_C.txt` | Natural-language operating-condition-transfer request. |
| `examples/nozzle_e2e/PROMPT_TEMPLATE.txt` | Copy/edit template for a nearby nozzle request. |
| `examples/forward_step_2d/*.txt` | Requests of the forward-facing-step sessions (`CASE_B_MACH20.txt` is the Mach-2 canonical request; `REQUEST_MESH_SENSITIVITY.txt` the sensitivity request). |

## User-facing scripts

| Path | Role |
| --- | --- |
| `scripts/check_environment.py` | Checks host Python dependencies, WSL/OpenFOAM availability, and whether an API key is configured. |
| `scripts/run_nozzle_e2e.py` | Shared prompt-to-mesh-to-CFD pipeline. Performs one CFD reasoning/acceptance pass. Used by the feedback runner for the initial iteration. |
| `scripts/run_nozzle_feedback.py` | Main closed-loop multimodal agent. Repeats CFD reasoning and executes approved actions until acceptance or a bounded stop. |
| `scripts/run_forward_step_2d.py` | Closed-loop agent runner of the 2-D forward-facing-step family (request interpretation, scope gate, build, solve, diagnosis, action validation, scientific validation). |
| `scripts/reanalyse_forward_step_2d.py` | Deterministic reanalysis of a completed step run without a new solve. |
| `scripts/run_demo.py`, `scripts/run_agent.py` | Registered-case replay/dry-run/live CLI and prompt CLI; their default deterministic backend is a no-key demo mode, not the paper's configuration. |
| `scripts/run_repro_campaign.ps1` | Reruns the nozzle A/B/C campaign on Windows/WSL with OpenFOAM Foundation v14. |
| `scripts/run_repro_campaign.sh` | Linux-host counterpart for the same campaign. |
| `scripts/build_nozzle_campaign_summary.py` | Reads A/B/C `feedback_summary.json` files and creates one sanitized combined summary. |

## Core contracts

| Path | Role |
| --- | --- |
| `src/contracts/problem_spec.py` | General engineering problem/geometry/operating-condition data structures. |
| `src/contracts/cfd_evidence.py` | Typed evidence packet consumed by the CFD reasoning layer. |
| `src/contracts/agent_decision.py` | Nozzle diagnosis/action vocabulary (`AgentAction`: `ACCEPT`, `CONTINUE_RUN`, `REQUEST_DIAGNOSTIC`, `REFINE_THROAT`, `REFINE_GRADIENT_REGION`, `REPAIR_MESH`, `RESTART_CLEAN`, `REJECT_OUTSIDE_DOMAIN`). |

## LLM-facing agents

| Path | Role |
| --- | --- |
| `src/agents/nozzle_case_spec_agent.py` | Parses a natural-language nozzle request into a parameterized case specification. |
| `src/agents/nozzle_demo_agents.py` | LLM mesh review and final engineering-summary helpers used by the nozzle runners. |
| `src/agents/forward_step_spec_agent.py` | Parses a natural-language forward-step request into a `ForwardStep2DSpec`; unstated fields are filled from family defaults. |
| `src/agents/theory_blind_cfd_agent.py` | Sends theory-blind numerical/visual evidence to the LLM and requests a structured diagnosis/action. |
| `src/agents/cfd_visual_observer.py` | Sends standardized CFD field images to the multimodal model for qualitative observation only. |
| `src/agents/llm_provenance.py` | Records whether a reasoning result came from the LLM or an explicitly enabled deterministic fallback. |
| `src/agents/cfd_request_agent.py`, `mesh_adaptation_agent.py`, `mesh_planner_agent.py`, `nozzle_design_agent.py`, `openfoam_setup_agent.py` | Legacy agents of the CAD→Gmsh prototype; not part of the paper's registered path. |

## Deterministic reasoning and safety

| Path | Role |
| --- | --- |
| `src/reasoning/nozzle_scope_gate.py` | Rejects case specifications outside the declared physics/parameter envelope before CFD runs. |
| `src/reasoning/reference_evidence_adapter.py` | Converts deterministic CFD validation output into the theory-blind evidence packet. |
| `src/reasoning/evidence_packet.py` | Fail-closed theory/reference leakage guard for autonomous reasoning payloads. |
| `src/reasoning/nozzle_diagnosis.py` | Wrapper around the theory-blind CFD reasoning call plus explicit provenance/fallback behavior. |
| `src/reasoning/action_validator.py` | Deterministically approves/rejects each proposed nozzle action. |
| `src/reasoning/forward_step_scope_gate.py` | 14-check scope gate of the step family. |
| `src/reasoning/forward_step_diagnosis.py` | Reference-blind diagnosis call of the step family. |
| `src/reasoning/forward_step_actions.py` | Step action vocabulary (`ForwardStepAction`: `ACCEPT`, `CONTINUE_RUN`, `EXTEND_END_TIME`, `REDUCE_MAX_CO`, `REFINE_MESH`, `REBUILD_FROM_VALIDATED_SPEC`, `REQUEST_CLARIFICATION`, `REJECT_UNSUPPORTED`, `FAIL_SAFELY`) and its action validator. |
| `src/reasoning/forward_step_mesh_study.py` | Bounded mesh-refinement policy of the step family. |
| `src/reasoning/diagnostics_adapter.py` | Adapter used by earlier/general diagnostics flow. |
| `src/reasoning/initialization_policy_adapter.py` | Adapter for initialization-policy evidence. |
| `src/reasoning/paper_safety_gate.py` | Earlier safety gate retained for history; the nozzle path relies on the explicit action validator and scope gate. |

## OpenFOAM runtime and family pipelines

| Path | Role |
| --- | --- |
| `src/pipeline/foam_runtime.py` | Bridges the host process to either WSL2 or native Linux OpenFOAM, performs preflight, stages code, and copies evidence. |
| `src/pipeline/nozzle/spec.py` | Parameterized nozzle geometry, thermodynamics, mesh resolution, and manifest logic. |
| `src/pipeline/nozzle/build.py` | Writes the OpenFOAM case using the registered numerical recipe. |
| `src/pipeline/nozzle/initialize.py` | Creates and verifies the explicit per-cell quasi-1D startup state. |
| `src/pipeline/nozzle/execute.py` | Bounded serial `foamRun`/`shockFluid` execution and progress monitoring. |
| `src/pipeline/nozzle/validate.py` | Recomputes deterministic scientific acceptance checks from fields/logs/monitors. |
| `src/pipeline/nozzle/foamio.py` | Reads/writes OpenFOAM field and dictionary data used by the pipeline. |
| `src/pipeline/nozzle/mesh_case.sh` | Runtime shell sequence for `blockMesh`, `checkMesh`, cell centers, and cell volumes. |
| `src/pipeline/nozzle/run_case.sh` | Runtime shell entry used by the case execution path. |
| `src/pipeline/nozzle/feedback.py` | Mechanical implementations of approved feedback actions such as continuation and bounded refinement. |
| `src/pipeline/nozzle/export_feedback_snapshot.py` | Exports latest native OpenFOAM cell values into a compact snapshot for diagnostics/visualization. |
| `src/pipeline/nozzle/feedback_diagnostics.py` | Gradient localization, native field-image generation, diagnostic-request fulfillment, and evidence augmentation. |
| `src/pipeline/forward_step_2d/spec.py` | Parameterized 2-D step geometry, mesh and solver settings. |
| `src/pipeline/forward_step_2d/build.py`, `execute.py`, `mesh_case.sh` | Case writing, mesh generation and bounded `foamRun`/`shockFluid` execution. |
| `src/pipeline/forward_step_2d/collect_evidence.py`, `diagnostics.py`, `regions.py` | Evidence extraction, storage-aware mass closure and compression-front diagnostics. |
| `src/pipeline/forward_step_2d/validate.py` | 17 hard checks and 3 compression checks; returns `PASS_2D_FORWARD_STEP` or a failure status. |
| `src/pipeline/forward_step_2d/reanalyse.py` | Deterministic reanalysis of a completed run. |

## Orchestrator, families and evaluation

| Path | Role |
| --- | --- |
| `src/orchestrator/loop.py` | `decide_once`/`run_loop`: the four decisions (`ACCEPT`, `CORRECT_AND_RERUN`, `REJECT`, `INCONCLUSIVE`). |
| `src/orchestrator/modes.py`, `ledger.py` | Experiment modes (full agent, recipe baseline, gates off, no diagnosis loop) and the decision ledger. |
| `src/families/` | Family adapters, capability declarations (`capabilities.py`), registry and the cube stationarity gate (`cube/stationarity.py`). |
| `src/router/route.py` | Family routing. |
| `src/eval/harness.py`, `faults.py` | Evidence-level evaluation harness and fault injection. |
| `src/authority/boundary.py` | Agent/authority boundary and the terminal replay/dry-run trace. |

## Reporting

| Path | Role |
| --- | --- |
| `src/reporting/event_stream.py` | Emits/archives stage-by-stage events such as ORCHESTRATOR, MESH TOOL, EXECUTOR, LLM, ACTION VALIDATOR, and SCIENTIFIC VALIDATOR. |
| `src/reporting/cfd_results_package.py` | Results packaging helper retained from the CAD→Gmsh prototype. |
| `src/reporting/field_video.py`, `paraview_field_video.py` | Field-evolution videos from native fields (`docs/field_evolution_video.md`). |
| `src/reporting/report_builder.py`, `visuals.py`, `paraview_contours.py` | Report, plots and contours of `run_demo.py` runs. |

## CAD→Gmsh prototype modules (not part of the paper)

Not part of the CFD Forge paper; retained from the earlier CAD→Gmsh prototype whose record the paper describes. They are not used by the registered nozzle or step path.

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
| `tests/nozzle_e2e/test_foam_runtime.py` | WSL/Linux runtime bridge behavior. |
| `tests/nozzle_e2e/test_evidence_adapter.py` | Theory-blind evidence construction and action-validation inputs. |
| `tests/nozzle_e2e/test_event_stream.py` | Event-stream behavior. |
| `tests/nozzle_e2e/test_orchestrator.py` | End-to-end orchestration invariants. |
| `tests/nozzle_e2e/test_feedback_loop.py` | Closed-loop action executor and iteration logic. |
| `tests/nozzle_e2e/test_feedback_diagnostics.py` | Restart-aware diagnostics, images/evidence safety, and feedback-specific behavior. |
| `tests/nozzle_e2e/test_canonical_equivalence.py` | Protects the parameterized pipeline against accidental changes to the frozen canonical numerical recipe. |
| `tests/forward_step_2d/` | Step family: request interpretation, fatal-error detection, horizon semantics, mesh sensitivity, reanalysis, restart-aware conservation. |
| `tests/architecture/` | Orchestrator, router, registry, parity and evaluation-harness tests. |
| `tests/consolidated/` | Replay, CLI, documentation and cube-rejection tests. |

## Frozen reference campaign

`validation/canonical_reference/` is the LLM-free nozzle reference refinement campaign (`docs/REFERENCE_VALIDATION.md`). It contains the canonical case builder, initializer, solver executor, validator, sensitivity-study scripts, result JSON/CSV files, and reference figures.

Important files:

| Path | Role |
| --- | --- |
| `validation/canonical_reference/README.md` | Full reference-campaign explanation and reproduction instructions. |
| `build.py` | Writes the canonical OpenFOAM case. |
| `initialize.py` | Writes the canonical startup fields. |
| `execute.py` | Runs the canonical bounded OpenFOAM solver. |
| `validate.py` | Computes the canonical acceptance metrics. |
| `run_case.sh`, `run_sensitivity.sh`, `Allrun`, `RunReference.ps1` | Reproduction wrappers. |
| `test_validation.py` | Reference-campaign regression tests. |
| `results/` | Compact numerical results from the reference campaign. |
| `figures/` | Reference plots. |

## Paper, evidence and cases

| Path | Role |
| --- | --- |
| `paper/cfd_forge/main.tex` | Manuscript source. |
| `paper/cfd_forge/data/` | Archived figure data with SHA-256 inventory (`DATA_MANIFEST.json`) and the session ledger (`session_ledger.json`). |
| `paper/cfd_forge/scripts/make_figures.py`, `make_mesh_field_figures.py`, `make_agent_loop_figure.py` | Paper figures from archived data. |
| `paper/cfd_forge/scripts/controller_comparison.py` | Controller comparison (needs the Zenodo session archive and a key). |
| `paper/cfd_forge/scripts/cube_llm_diagnosis.py` | LLM diagnosis of the archived cube evidence. |
| `evidence/controller_comparison/20261001T213031Z/` | Archived controller-comparison run. |
| `evidence/cube/drifting_wake/llm_diagnosis/` | The three cube diagnosis calls. |
| `evidence/` | Pre-generated artifact directories of representative cases. |
| `cases/` | Registered cases: `case.yaml`, `expected_result.json`, `README.md`, `reproduce.*`. |
| `demo/published_campaign/CAMPAIGN_SUMMARY.json` | Sanitized compact nozzle A/B/C result summary with no machine paths or API credentials. |
| `demo/published_campaign/README.md` | Explains what the summary contains and which raw runtime artifacts are omitted. |

The full agent session records are in the Zenodo session archive (DOI to be added on release).

## Present but not part of the paper

| Path | Status |
| --- | --- |
| `src/pipeline/forward_step/`, `scripts/run_forward_step.py`, `configs/forward_step/`, `tests/forward_step/` | 3-D forward step; experimental (`docs/forward_step_3d.md`). |
| `src/pipeline/airfoil/`, `src/families/airfoil/`, `cases/airfoil/`, `tests/airfoil/` | NACA0012 airfoil mesh study; `CFD_NOT_RUN`. |
| `src/families/backward_step/` | Backward-facing step; declared, not implemented. |
| `src/cad/`, `src/meshing/`, `src/openfoam/`, `src/cfd/`, legacy `src/agents/` modules | CAD→Gmsh prototype stack. |
