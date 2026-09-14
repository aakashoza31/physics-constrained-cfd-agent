# Architecture

The central architecture separates LLM inference from scientific
authority.

Flow:

Engineering prompt
-> supported-domain validation
-> geometry generation
-> mesh generation
-> deterministic mesh checks
-> OpenFOAM execution
-> numerical diagnostics
-> visual CFD evidence
-> multimodal LLM interpretation
-> proposed action
-> deterministic scientific validator
-> approved action
-> next CFD state

The LLM may propose actions such as CONTINUE_RUN, REQUEST_DIAGNOSTIC,
REFINE_REGION, or other allowed actions.

The validator determines whether the proposed action is scientifically
and numerically permissible.

The LLM therefore does not directly control OpenFOAM.
