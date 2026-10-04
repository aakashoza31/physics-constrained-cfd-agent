"""Theory-blind Gemini diagnosis for the registered nozzle family.

``diagnose_theory_blind`` builds the theory-blind reasoning packet
(``src/reasoning/evidence_packet.py``), asks Gemini for one structured
``AgentDecision`` at temperature 0, and runs the deterministic action
validator on the proposal.  The model proposes; the validator decides.

Repair call.  With ``allow_one_repair_attempt=True`` (the default), a proposal
that the action validator refuses triggers exactly one further model call on
the same packet, extended with the refused decision, the validator reasons and
an instruction to reconsider the same measurements.  The second decision and
its validation are returned.  So that this second call is auditable, the
optional ``audit`` dict passed by the caller is filled with ``attempts``
(1 or 2), the ``model`` identifier used, the response ``model_version`` when
the SDK reports one, and, when the repair path ran, ``refused_first_decision``
(the first decision and its validator reasons).
``src/reasoning/nozzle_diagnosis.py`` copies these into the ``LLMCallRecord``
(``attempts=2`` and ``refused_first_decision``); its latency is the total over
both calls.  The archived nozzle record for N4 iteration 2 predates this
change: its repair call happened but was not recorded (``attempts=1``, no first
decision), as disclosed in the paper.

The model identifier is read at request time from
``llm_provenance.gemini_model_name()`` (``GEMINI_MODEL`` or the shared
default).  Every packet sent to the model, including the history and the
repair packet, passes ``assert_theory_blind_payload``.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from google import genai
from google.genai import types
from pydantic import BaseModel

from src.contracts.agent_decision import (
    AgentAction,
    AgentDecision,
    CompetingHypothesis,
    Diagnosis,
)

from src.contracts.cfd_evidence import (
    CFDEvidence,
)

from src.contracts.problem_spec import (
    CFDProblemSpec,
)

from src.reasoning.action_validator import (
    ActionValidationResult,
    validate_agent_action,
)

from src.reasoning.evidence_packet import (
    assert_theory_blind_payload,
    build_reasoning_packet,
)

from src.agents.llm_provenance import (
    gemini_model_name,
)


_REPO_ROOT = Path(__file__).resolve().parents[2]

# Repository-relative policy path; this string is what the packet records.
POLICY_PATH_RELATIVE = "configs/cfd_reasoning_policy_v2.yaml"

# Resolved against the repository root so the agent does not depend on the
# current working directory.
POLICY_PATH = _REPO_ROOT / POLICY_PATH_RELATIVE


class HypothesisSchema(BaseModel):
    hypothesis: str
    evidence_for: List[str]
    evidence_against: List[str]


class TheoryBlindDecisionSchema(BaseModel):
    diagnosis: Diagnosis

    evidence_used: List[str]

    competing_hypotheses: List[
        HypothesisSchema
    ]

    reasoning_summary: str

    action: AgentAction

    target_region: Optional[str] = None

    requested_diagnostic: Optional[str] = None

    confidence: str


def _load_policy_text() -> str:

    if not POLICY_PATH.exists():
        raise FileNotFoundError(
            f"Policy file not found: {POLICY_PATH}"
        )

    raw = POLICY_PATH.read_text(
        encoding="utf-8-sig"
    )

    # Validate YAML now so malformed policy cannot
    # silently reach the model.
    parsed = yaml.safe_load(raw)

    if not isinstance(parsed, dict):
        raise ValueError(
            "CFD policy must contain a YAML mapping."
        )

    return raw


def _system_instruction(
    policy_text: str,
) -> str:

    # Known inaccuracy, kept unchanged so that model behaviour stays
    # comparable with the archived runs: rule 10 says the proposed action is
    # "verified by another CFD calculation".  In the implemented loop the
    # action is checked by the deterministic action validator and, after any
    # executed action, by the deterministic scientific validator; no separate
    # verification calculation is run.  Reword this rule in a future,
    # separately versioned prompt.
    return f"""
You are the CFD reasoning component of a physics-constrained
autonomous scientific-simulation agent.

You are NOT the numerical solver.

OpenFOAM solves the governing equations.
Deterministic Python code measures CFD and mesh evidence.
You interpret the evidence and choose one permitted high-level action.

CRITICAL RULES

1. Use only the supplied problem specification, deterministic CFD
   evidence, and CFD expert policy.

2. Analytical theory, analytical reference values, benchmark targets,
   or hidden expected answers are intentionally unavailable.

3. Never invent CFD measurements.

4. Do not infer quantitative facts from an image path or filename.

5. Distinguish:
   - insufficient run time,
   - local mesh under-resolution,
   - mesh-quality failure,
   - boundary anomaly,
   - inherited-state instability,
   - generic numerical failure,
   - physically valid strong gradients.

6. Mesh refinement requires evidence connecting an important
   flow feature to inadequate local resolution.

7. checkMesh PASS does not prove adequate resolution.

8. Solver completion does not prove stationarity.

9. If evidence is insufficient to distinguish hypotheses,
   REQUEST_DIAGNOSTIC.

10. Your proposed action is only a hypothesis. It will be checked
    by deterministic Python guardrails and then verified by another
    CFD calculation.

11. Keep reasoning_summary concise and engineering-focused.
    Do not provide hidden chain-of-thought.

12. Return only the structured response requested by the schema.

CFD EXPERT POLICY
=================

{policy_text}
"""


def _load_client() -> genai.Client:

    api_key = os.getenv(
        "GEMINI_API_KEY"
    )

    if not api_key:
        raise RuntimeError(
            "GEMINI_API_KEY is not set."
        )

    return genai.Client(
        api_key=api_key
    )


def _convert(
    raw: TheoryBlindDecisionSchema,
) -> AgentDecision:

    decision = AgentDecision(
        diagnosis=raw.diagnosis,

        evidence_used=[
            item.strip()
            for item
            in raw.evidence_used
            if item.strip()
        ],

        competing_hypotheses=[
            CompetingHypothesis(
                hypothesis=(
                    item.hypothesis.strip()
                ),

                evidence_for=[
                    value.strip()
                    for value
                    in item.evidence_for
                    if value.strip()
                ],

                evidence_against=[
                    value.strip()
                    for value
                    in item.evidence_against
                    if value.strip()
                ],
            )
            for item
            in raw.competing_hypotheses
        ],

        reasoning_summary=(
            raw.reasoning_summary.strip()
        ),

        action=raw.action,

        target_region=(
            raw.target_region.strip()
            if (
                raw.target_region
                and raw.target_region.strip()
            )
            else None
        ),

        requested_diagnostic=(
            raw.requested_diagnostic.strip()
            if (
                raw.requested_diagnostic
                and raw.requested_diagnostic.strip()
            )
            else None
        ),

        confidence=(
            raw.confidence.strip().lower()
        ),
    )

    decision.validate()

    return decision


def diagnose_theory_blind(
    problem: CFDProblemSpec,
    evidence: CFDEvidence,
    *,
    history: Optional[List[dict[str, Any]]] = None,
    allow_one_repair_attempt: bool = True,
    audit: Optional[Dict[str, Any]] = None,
) -> tuple[
    AgentDecision,
    ActionValidationResult,
]:
    """Return the (possibly repaired) decision and its action validation.

    If ``audit`` is a dict it is filled in place with ``attempts``,
    ``model``, ``model_version`` (when reported by the SDK) and, when the
    repair call ran, ``refused_first_decision``; see the module docstring.
    """

    if audit is None:
        audit = {}

    model_name = gemini_model_name()

    audit["model"] = model_name
    audit["attempts"] = 0

    packet = build_reasoning_packet(
        problem,
        evidence,
        policy_path=POLICY_PATH_RELATIVE,
    )

    if history:
        packet[
            "previous_iterations"
        ] = history

        packet[
            "history_instruction"
        ] = (
            "Compare the current CFD state with previous iterations. "
            "Do not repeat the same corrective action indefinitely when "
            "the new evidence fails to improve or contradicts the prior "
            "hypothesis."
        )

    packet[
        "allowed_diagnoses"
    ] = [
        item.value
        for item
        in Diagnosis
    ]

    packet[
        "allowed_actions"
    ] = [
        item.value
        for item
        in AgentAction
    ]

    packet[
        "visual_note"
    ] = (
        "Image paths may be present in evidence, but this text-only "
        "reasoning stage has not been given image pixels. Do not infer "
        "visual observations from filenames."
    )

    client = _load_client()

    policy_text = (
        _load_policy_text()
    )

    def call_model(
        active_packet: dict[
            str,
            Any,
        ],
    ) -> TheoryBlindDecisionSchema:

        # Fail closed if any reference-bearing key reached the final packet
        # (history and repair fields included).
        assert_theory_blind_payload(
            active_packet
        )

        audit["attempts"] = (
            int(audit.get("attempts", 0)) + 1
        )

        response = (
            client.models.generate_content(
                model=model_name,

                contents=json.dumps(
                    active_packet,
                    indent=2,
                ),

                config=types.GenerateContentConfig(
                    system_instruction=(
                        _system_instruction(
                            policy_text
                        )
                    ),

                    response_mime_type=(
                        "application/json"
                    ),

                    response_schema=(
                        TheoryBlindDecisionSchema
                    ),

                    temperature=0,
                ),
            )
        )

        model_version = getattr(
            response,
            "model_version",
            None,
        )

        if model_version:
            audit["model_version"] = str(
                model_version
            )

        if not response.text:
            raise RuntimeError(
                "Gemini returned an empty theory-blind CFD response."
            )

        return (
            TheoryBlindDecisionSchema
            .model_validate_json(
                response.text
            )
        )

    raw = call_model(
        packet
    )

    decision = _convert(
        raw
    )

    validation = (
        validate_agent_action(
            evidence,
            decision,
        )
    )

    if (
        validation.approved
        or not allow_one_repair_attempt
    ):
        return (
            decision,
            validation,
        )

    audit["refused_first_decision"] = {
        "decision": decision.to_dict(),
        "validator_approved": validation.approved,
        "validator_reasons": list(
            validation.reasons
        ),
    }

    repair_packet = dict(
        packet
    )

    repair_packet[
        "previous_rejected_decision"
    ] = {
        "diagnosis": (
            decision.diagnosis.value
        ),

        "action": (
            decision.action.value
        ),

        "target_region": (
            decision.target_region
        ),

        "validator_reasons": (
            validation.reasons
        ),
    }

    repair_packet[
        "instruction"
    ] = (
        "Your previous action was rejected by deterministic CFD "
        "guardrails. Reconsider the SAME measurements without inventing "
        "new evidence. If the available evidence cannot justify a safe "
        "action, use INSUFFICIENT_EVIDENCE with REQUEST_DIAGNOSTIC."
    )

    raw = call_model(
        repair_packet
    )

    decision = _convert(
        raw
    )

    validation = (
        validate_agent_action(
            evidence,
            decision,
        )
    )

    return (
        decision,
        validation,
    )
