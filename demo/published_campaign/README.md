# Published Three-Case Campaign Summary

`CAMPAIGN_SUMMARY.json` is a compact, machine-independent record of the demonstrated closed-loop campaign.

It captures the research-relevant behavior:

- Case A: first state is not stationary, LLM proposes `CONTINUE_RUN`, the approved action is executed, second state passes and is accepted.
- Case B: changed exit geometry passes on the first iteration.
- Case C: changed reservoir pressure passes on the first iteration.
- numerical evidence and multimodal visual observation are present in the feedback path.
- final acceptance remains deterministic.

Raw OpenFOAM runtime directories, full logs, model-provider labels, and machine-specific paths are not committed here. Running `scripts/run_repro_campaign.ps1` regenerates the full local evidence tree under `demo/runs/`.
