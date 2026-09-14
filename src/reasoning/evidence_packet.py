from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict

from src.contracts.cfd_evidence import CFDEvidence
from src.contracts.problem_spec import CFDProblemSpec


FORBIDDEN_THEORY_KEYS = {
    "theory",
    "analytical",
    "analytical_solution",
    "isentropic",
    "theoretical",
    "theoretical_exit_mach",
    "theoretical_pressure",
    "theoretical_temperature",
    "theoretical_velocity",
    "theoretical_mass_flow",
}


def _contains_forbidden_theory_key(obj: Any) -> bool:
    if isinstance(obj, dict):
        for key, value in obj.items():
            key_lower = str(key).lower()

            if any(token in key_lower for token in FORBIDDEN_THEORY_KEYS):
                return True

            if _contains_forbidden_theory_key(value):
                return True

    elif isinstance(obj, (list, tuple)):
        return any(_contains_forbidden_theory_key(v) for v in obj)

    return False


def assert_theory_blind_payload(payload: Dict[str, Any]) -> None:
    if _contains_forbidden_theory_key(payload):
        raise ValueError(
            "Theory/reference information was detected in the autonomous "
            "reasoning payload. Analytical/reference solutions must remain "
            "outside the agent decision loop."
        )


def build_reasoning_packet(
    problem: CFDProblemSpec,
    evidence: CFDEvidence,
    *,
    policy_path: str = "configs/cfd_reasoning_policy_v2.yaml",
) -> Dict[str, Any]:

    problem.validate()

    policy_file = Path(policy_path)

    if not policy_file.exists():
        raise FileNotFoundError(
            f"CFD reasoning policy not found: {policy_file}"
        )

    packet = {
        "task": (
            "Diagnose the current CFD state and choose the safest justified "
            "next action using only the supplied CFD evidence and expert policy."
        ),
        "problem": problem.to_dict(),
        "evidence": evidence.to_dict(),
        "policy_path": str(policy_file),
        "important_instruction": (
            "Analytical theory and reference-solution targets are intentionally "
            "withheld. Do not infer or invent them."
        ),
    }

    assert_theory_blind_payload(
        {
            "problem": packet["problem"],
            "evidence": packet["evidence"],
        }
    )

    return packet


def reasoning_packet_to_json(
    problem: CFDProblemSpec,
    evidence: CFDEvidence,
    *,
    policy_path: str = "configs/cfd_reasoning_policy_v2.yaml",
) -> str:

    packet = build_reasoning_packet(
        problem,
        evidence,
        policy_path=policy_path,
    )

    return json.dumps(packet, indent=2)
