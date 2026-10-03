# CFD Forge paper: outstanding gaps (state 2026-10-01)

Scope freeze applies: none of these items requires a new CFD case. Only item 1
needs any data movement at all, and none needs a new solver run.

| # | Gap | Affects | Why it matters | Likely source | Existing evidence enough? | New CFD? | Priority |
|---|-----|---------|----------------|---------------|---------------------------|----------|----------|
| 1 | Field panels are re-axed copies of archived renderings, not renders made directly from native fields | Fig. 4a,b (step Mach, density at t=4); Fig. 5a (cube \|U\| at t*=80) | The pixels are real native-field renders (Mach colour limits confirmed from the colourbar ticks), but a reviewer-grade figure should be rendered straight from the fields | WSL: `/home/aakash/.cache/nozzle-e2e/20260922T193651Z-forward-step-2d/case/4/`; `/home/aakash/family3_cube_sst_literature_audit_t4_retry2/80/` | Yes, once copied to Windows (the copy command was sent in chat) | No | Medium (2026-10-01: accepted for the arXiv draft; captions state renders are archived ParaView images of native fields, re-axed from the recorded camera; TODO removed. Optional native re-render via scripts/extract_native_fields.py) |
| 2 | No nozzle contour panel | Fig. 3 (optional) | Profiles already carry the validation; a Mach contour would make it easier to read | Same WSL nozzle case, `0.006/` | Yes | No | RESOLVED 2026-10-01: Fig. nozzle_fields (Mach, p, T at 6 ms) |
| 3 | Page count: 16 pages including ~2.5 pages of references, in generic `article` 11 pt | Whole paper | The target conference's page limit and template are not recorded anywhere I could find | Prof. Amir / venue call | n/a | No | High |
| 4 | Four new references added (Kurganov–Tadmor 2000, Woodward–Colella 1984, Menter 1994, Martinuzzi–Tropea 1993); bibliographic details were written from knowledge, not retrieved | References [20–23] | RESOLVED 2026-10-01: all 23 references checked against Crossref/arXiv/NTRS; every DOI/arXiv ID resolves to the cited paper. Corrected chen2026optmeta (vol. 16, no. 5), added dong2025 issue 3 and Toolformer pages. Celik 2008 author list could not be confirmed from Crossref (no author metadata) | Publisher pages | Done | No | Low |
| 5 | Registered cube gate and paper criterion were inconsistent in the Overleaf draft | Sec. 3.3 (corrected) | The draft called the 10% complete-cycle test "the registered criterion". The registered gate (`src/families/cube/stationarity.py`, `cube-stationarity/1.0.0`) is the half-window mean \|Fz\| ratio ≤ 1.25 (measured 2.10). The 10% cycle test (measured +112.96%) comes from the separate read-only audit `outputs/family3_cube_reference/audit_t80/`. The text now states both and labels them separately. **Please have Prof. Amir confirm this framing.** | Code + audit | Yes | No | High |
| 6 | Docstring of `src/families/cube/stationarity.py` is wrong | Code only (not the paper) | It says the run "misses the drift bound by more than an order of magnitude" and misses the growth bound "by a factor of about six". Measured values: drift 0.075% vs 2% (**passes**); growth 2.10 vs 1.25 (factor 1.68). The gate logic and verdict are correct; only the comment is wrong. Left unchanged here (code is outside the paper-only scope). | Repo | n/a | No | Medium |
| 7 | Nozzle runs: canonical vs continuation | Secs. 2.3, 3.1, 4.1, Table 4 | The handoff described one run with a continuation. The archives show two real runs: canonical `20260921T041731Z` (single execution to 6 ms, accepted first time; the field-video source) and continuation run `20260921T052758Z` (1 ms FAIL → Gemini CONTINUE_RUN → 6 ms PASS). The paper now attributes each result to the correct run. | `demo/nozzle_e2e/`, `demo/nozzle_feedback_v2_hotfix/` in the e2e worktree | Yes | No | Done (please confirm) |
| 8 | Multimodal observer model id not recorded | Sec. 3.4 | Step runs label it only `LLM:multimodal-visual-observer`; the code default is `gemini-3.6-flash` unless `GEMINI_MODEL` was set. The paper says "Gemini multimodal observer, model id not recorded". | `src/agents/cfd_visual_observer.py`, run environment | Partially | No | Low |
| 9 | Cube boundary conditions taken from the predecessor pilot's `initial_BC_audit.json`, not from `0/` files of the continuation (which has no `0/`) | Table 1 | The handoff says the 12 initialization files were byte-matched to the predecessor, but I did not re-verify this | WSL predecessor `family3_cube_sst_20260922/cube_pilot/0/` | Probably | No | Medium |
| 10 | Unified pipeline vs historical runners | Secs. 2, 3.4 | The archived nozzle/step runs were executed by the family runners (`scripts/run_nozzle_e2e.py`, `scripts/run_forward_step_2d.py`) with their own action and scientific validators; the unified `src/authority` layer re-derives the verdicts in replay (`solver_invoked:false`). The paper describes validators generically, which is accurate, but it does not claim the unified live path launched these runs. Decide whether to state this explicitly. | Provenance JSONs | Yes | No | Medium |
| 11 | Ablation (LLM vs fixed rule vs LLM-only acceptance) not run | Secs. 3.4, 4.4, 5 | Stated as a limitation; no performance claim is made | Future work | n/a | Replay-only evaluation possible | Out of scope |
| 12 | Grid/time-step independence per case not established | Sec. 5 | Stated as a limitation (runs are `PASS_SINGLE_MESH`) | Future compute | n/a | Yes (deferred per Prof. Amir) | Out of scope |
| 13 | Cube experimental comparison is poor | Sec. 5 | Audit RMSE vs ERCOFTAC centre-line profiles is 0.34–0.68 U_b; stated as a limitation, no validation claimed | `audit_t80/FINAL_ASSESSMENT.md` §10 | Yes | No | Done |

## Added after the full repository read (local clone = `origin/main` at `7aecd4d`, last fetched 2026-09-28 03:38 UTC; GitHub itself is private and not reachable from this session)
| # | Item | Status |
|---|------|--------|
| 14 | The frozen LLM-free nozzle reference campaign (`validation/canonical_reference/results/`, `study.json` = `FINAL_REFERENCE`): 4 meshes up to 13,200 cells plus 3 controls. The agent's canonical run is **bit-identical** to reference mesh 1. | Added to Sec. 3.1, Sec. 4.1 and a new mesh table |
| 15 | Step recipe provenance: manual reproduction of the Foundation v14 Mach-3 `forwardStep` tutorial (`Codex/.../outputs/forward_step_reference/`; this is **outside the repo**) | One sentence in Sec. 3.2; consider committing that package or a digest of it |
| 16 | `mesh_sensitivity` (`case_I`): model ACCEPT **refused** by the action validator (no registered cross-grid tolerance) → `STOPPED_ACTION_REFUSED` | Added to Sec. 4.4 and Table 5; it is the paper's only direct example of the validator overruling the model |
| 17 | `docs/results.md` says `step_height_030_extended` is "the same geometry with the horizon extended". The event logs show both case F and case G ran to t = 4; case G moves the step to x = 1.0 (15,360 cells). | Repo doc inconsistency; the paper does not use the "extended horizon" wording. Fix the doc and consider renaming the case. |
| 18 | `live_run` (`live_run_01`): the archived REJECT came from `no_fatal_error`. A later reanalysis (`REANALYSIS.json`, log excerpt only) finds no fatal signature and returns PASS. The registered verdict remains REJECT. | Not used in the paper; decide whether the case library should record the reanalysis |
| 19 | Repo docs call the nozzle "compressible Euler, 2-D"; it is an axisymmetric 5° wedge | Paper says axisymmetric; align the docs |

## TODO markers in `main.tex`
- Sec. 5.4: cube Gemini diagnosis pending (`scripts/cube_llm_diagnosis.py --repeats 3`, run on the laptop with the key).
- (Fig. 4 TODO removed 2026-10-01; see item 1.)
- (Fig. 5a has the same limitation; its caption states the source honestly but carries no TODO. Add one if preferred.)

## Things deliberately NOT changed
- Abstract, Introduction, Sections 2.1–2.4, Figure 1, title, authors.
- All historical verdicts: nozzle ACCEPT, step ACCEPT, cube REJECT (STILL_DEVELOPING).

## Added 2026-10-01 (figures for the arXiv draft)
- New figures, all from archived data: fig_agent_loop (architecture; counts from agent_stats.json), fig_agent_stats, fig_mesh_nozzle (exact blockMesh wedge + prototype Gmsh surface), fig_mesh_step_cube (native polyMesh), fig_nozzle_fields, fig_step_evolution, fig_cube_wake. fig2_configurations is no longer used in main.tex.
- New paragraph on the prototype CAD->Gmsh run (Sec. 5.2) from data/prototype and data/gmsh records. It states only what those records show; the Gmsh path is not claimed as validated.
- Cube "wake" field = `U_Z` (ParaView Calculator in src/reporting/paraview_field_video.py, lines 195-201); labelled U_z/U_b with U_b = 1. Verified 2026-10-01.

## Amir review, 2026-10-01: status
- Point 1 (cube): DONE. 3 LLM calls reported (2 STILL_DEVELOPING/CONTINUE_RUN, 1 NUMERICALLY_UNHEALTHY/FAIL_SAFELY).
- Point 2 (controller comparison): OPEN. Needs a run with the API key (harness: src/eval/harness.py, evaluation/README.md).
- Point 3 (novelty): DONE in draft. Intro rewritten; Table tab:related; PolyJarvis named as closest precedent. The table entries come from model-summarized readings of the papers (arXiv was reached only through a summarizing fetch tool). SPOT-CHECK every row against the PDFs before submission, especially Foam-Agent v3 (journal version) and ChatCFD success definition.
- Lab citations: DONE (PolyJarvis v3, Jadhav JED 2026, NAMD-Agent, MeshDQN, Adsorb-Agent). Polymer-Agent (JCIM 2026) not added.
- Point 4 (reproducibility): DONE in draft (Appendix B). Model named exactly (user decision). Session ledger, hardware, OpenFOAM build, MPI ranks, commits, dates, budgets, counting method.
  * COUNTS CORRECTED: events-only count (82 calls / 23 proposals) missed nozzle feedback-loop iterations. Recount from all call records: 97 calls (16 interp, 8 mesh, 28 diag, 23 field obs [5 failed HTTP 503], 22 summaries), 28 proposals (14 ACCEPT, 5 CONTINUE_RUN, 4 EXTEND, 3 FAIL_SAFELY, 1 REFINE_MESH, 1 REQUEST_DIAGNOSTIC), 25 approved / 3 refused. Ledger made additive (74 text calls) by scripts/reconcile_session_ledger.py.
  * Field observer: same GEMINI_MODEL env var, identifier not written to its record. 5/23 failures = provider 503, not schema/usefulness failures.
  * USER ACTION before posting: make GitHub repo public; deposit the e2e demo session archive (physics-constrained-cfd-agent-e2e/demo, most of it is NOT in git) + CFD_Verification_Package on Zenodo; then put the DOI into the Code and Data Availability section.
- Point 5 (claims/definitions): DONE in draft. Four decisions defined (incl. CORRECT_AND_RERUN); refused action vs rejected solution; case_I now INCONCLUSIVE (was "recorded as a rejection", wrong); mass-closure construction + "not accuracy"; 'validated' wording; threshold registration dates; all sessions are development cases; cube gate registered 28 Sep AFTER cube data (23-24 Sep) - disclosed.
  * New finding reported: live_run_01 FAIL_SAFELY was caused by a validator false positive (sigFpe banner); the LLM followed the wrong check; deterministic reanalysis later PASS.
- Point 6 (length/figures): MOSTLY DONE. Fig. 1 caption says schematic + cube offline. Cube wake figure removed (frames visually identical). Verbatim spec and diagnosis-trace figures moved to Appendix B (Model Records); setup table moved to Appendix A. Float placement relaxed and large figures shrunk: 29 pages total, main text ends p.20. Open: abstract numbers (after point 2), further prose cuts if Amir wants.
- Note: stationarity.py docstring says the cube "misses the drift bound by more than an order of magnitude" - false (drift 0.075%, passes). Fix the docstring in the repo; the paper is correct.

## Full read of Overleaf PDF v2, 2026-10-01
- Overleaf still had the OLD fig_agent_loop.pdf and fig_agent_stats.pdf (82 calls / 23 proposals), contradicting the text (97 / 28). Re-upload both.
- Fixed: "15 runs" -> 16 runs (8 nozzle + 8 step; ledger N1-N8, S1-S8); dangling "That integration..." sentence after the related-work rewrite; model name in Fig. 11/12 now matches the text; Table 5 last verdict marked INCONCLUSIVE; step/cube mesh figure moved to Appendix A (removed a half-empty page); Appendix B figures placed in-line.
- Before release: cube_llm_diagnosis.py and the paper scripts live on paper/results-draft-20260930, not on main. Merge them before making the repo public, because the paper cites that path.
