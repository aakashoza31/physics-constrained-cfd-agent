"""Theory-blind reasoning packet for the nozzle diagnosis call.

``build_reasoning_packet`` assembles the problem specification, the
deterministic CFD evidence and the policy path into the packet sent to the
model.  ``assert_theory_blind_payload`` is the fail-closed leak guard: it
raises if any dictionary key in the payload contains a theory- or
reference-bearing token.  ``theory_blind_cfd_agent`` applies it to every final
packet, including history and the repair packet.
"""
from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict


_REPO_ROOT = Path(__file__).resolve().parents[2]

DEFAULT_POLICY_PATH = "configs/cfd_reasoning_policy_v2.yaml"

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

# Additional reference-bearing key tokens checked by the leak guard only.
# They are deliberately not added to FORBIDDEN_THEORY_KEYS, which
# src/pipeline/nozzle/feedback_diagnostics.py also uses to strip keys from
# the evidence; extending that set would change the evidence the model sees.
FORBIDDEN_REFERENCE_KEYS = {
    "quasi1d",
    "quasi_1d",
    "reference",
    "expected",
    "benchmark",
}

_GUARD_TOKENS = FORBIDDEN_THEORY_KEYS | FORBIDDEN_REFERENCE_KEYS


def _contains_forbidden_theory_key(obj: Any) -> bool:
    if isinstance(obj, dict):
        for key, value in obj.items():
            key_lower = str(key).lower()

            if any(token in key_lower for token in _GUARD_TOKENS):
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
    policy_path: str = DEFAULT_POLICY_PATH,
) -> Dict[str, Any]:

    problem.validate()

    # A relative policy path is resolved against the repository root, not the
    # current working directory.  The packet records the path as given, so the
    # packet content does not depend on where the repository is installed.
    policy_file = Path(policy_path)

    resolved_policy = (
        policy_file
        if policy_file.is_absolute()
        else _REPO_ROOT / policy_file
    )

    if not resolved_policy.exists():
        raise FileNotFoundError(
            f"CFD reasoning policy not found: {resolved_policy}"
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
    policy_path: str = DEFAULT_POLICY_PATH,
) -> str:

    packet = build_reasoning_packet(
        problem,
        evidence,
        policy_path=policy_path,
    )

    return json.dumps(packet, indent=2)
