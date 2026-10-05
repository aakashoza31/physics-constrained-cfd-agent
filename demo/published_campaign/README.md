# Published Three-Case Campaign Summary

`CAMPAIGN_SUMMARY.json` is a compact, machine-independent record of the closed-loop nozzle campaign.

It captures the research-relevant behavior:

- Case A: first state is not stationary, the model proposes `CONTINUE_RUN`, the approved action is executed, second state passes and is accepted.
- Case B: changed exit geometry passes on the first iteration.
- Case C: changed reservoir pressure passes on the first iteration.
- numerical evidence and multimodal visual observation are present in the feedback path.
- final acceptance remains deterministic.

## Mapping to the paper's session ledger

These summaries were extracted (`scripts/publish_existing_campaign.py`) from three
archived nozzle sessions of 21 September 2026 (paper, session ledger):

| Here | Ledger | Archived session (Zenodo, same relative path) | Proposals in that session | Outcome |
|---|---|---|---|---|
| Case A | N6 | `demo/nozzle_feedback_v2_hotfix/case_A_reference` | `CONTINUE_RUN` (initial run), `CONTINUE_RUN`, `ACCEPT` at 6 ms | `PASS_SINGLE_MESH` -> `ACCEPT` |
| Case B | N7 | `demo/nozzle_feedback_final/case_B_geometry` (repeat of N2) | `ACCEPT`, `ACCEPT` | `PASS_SINGLE_MESH` -> `ACCEPT` |
| Case C | N8 | `demo/nozzle_feedback_final/case_C_conditions` (repeat of N3) | `ACCEPT`, `ACCEPT` | `PASS_SINGLE_MESH` -> `ACCEPT` |

The `trace` in these files lists only the feedback-loop iterations. The first
proposal of each session (the decision on the initial run, recorded in that
session's `initial_e2e_agent_decision.json`) is not repeated here, so Case A shows
one `CONTINUE_RUN` and Cases B and C show one `ACCEPT`.

Raw OpenFOAM runtime directories, full logs and machine-specific paths are not
committed here. Model-provider labels were stripped from these summaries; the
full session records, including the model identifiers of every call, are in the
Zenodo archive (https://doi.org/10.5281/zenodo.23148676) under the paths above.

Running `scripts/run_repro_campaign.ps1` (or `.sh`) re-runs the campaign and writes
a new local evidence tree under `demo/runs/`; model outputs may differ from the
archived ones.
