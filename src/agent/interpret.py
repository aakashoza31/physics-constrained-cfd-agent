#!/usr/bin/env python3
"""Request interpretation: natural language in, a structured proposal out.

This is a MODEL activity, and it is bounded on both sides. The interpreter reads
a free-text engineering request and produces a ProblemStatement: the family it
proposes, the geometry parameters it believes were stated, and the operating
conditions. Every one of those is a proposal that deterministic code re-checks.

The default interpreter is deterministic keyword matching over the family
register, so the pipeline runs with no API key and produces the same answer
twice. An LLM interpreter can be substituted through `set_interpreter`; its
output is validated against the same schema and carries the same non-binding
status. A model cannot introduce a family that is not registered, cannot invent a
parameter name the family does not declare, and cannot mark its own proposal
admissible.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from src.families import capabilities as caps

INTERPRETER_VERSION = "request-interpreter/1.0.0"

#: Parameter names each family understands, with the units they are read in.
PARAMETER_VOCABULARY: Dict[str, Dict[str, str]] = {
    "nozzle": {"throat_radius": "m", "exit_radius": "m", "inlet_radius": "m",
               "length": "m", "chamber_pressure": "Pa", "back_pressure": "Pa",
               "chamber_temperature": "K"},
    "forward_step_2d": {"step_height": "-", "length": "-", "height": "-",
                        "step_x": "-", "mach": "-", "end_time": "-",
                        "nx": "-", "ny": "-"},
    "cube": {"cube_height": "m", "velocity": "m/s", "end_time": "s"},
    "airfoil": {"chord": "m", "alpha_deg": "deg", "reynolds": "-"},
}

#: Words that suggest a family. Deliberately small and inspectable.
_KEYWORDS: Dict[str, tuple] = {
    "nozzle": ("nozzle", "converging", "diverging", "throat", "rocket", "de laval",
               "delaval"),
    "forward_step_2d": ("forward step", "forward-facing", "forward facing step",
                        "woodward", "colella", "step in a wind tunnel"),
    "cube": ("cube", "surface-mounted", "surface mounted", "wall-mounted",
             "bluff body"),
    "airfoil": ("airfoil", "aerofoil", "naca", "aerofoil section", "wing section"),
}

_NUMBER = r"([-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?)"


@dataclass
class ProblemStatement:
    """What the interpreter believes the user asked for. All of it a proposal."""

    prompt: str
    proposed_family: Optional[str] = None
    parameters: Dict[str, float] = field(default_factory=dict)
    operating_conditions: Dict[str, float] = field(default_factory=dict)
    geometry_source: str = "parametric"
    confidence_note: str = ""
    keyword_hits: Dict[str, List[str]] = field(default_factory=dict)
    interpreter: str = "deterministic_keyword"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "interpreter_version": INTERPRETER_VERSION,
            "interpreter": self.interpreter,
            "prompt": self.prompt,
            "proposed_family": self.proposed_family,
            "parameters": dict(self.parameters),
            "operating_conditions": dict(self.operating_conditions),
            "geometry_source": self.geometry_source,
            "keyword_hits": {k: list(v) for k, v in self.keyword_hits.items()},
            "confidence_note": self.confidence_note,
            "binding": False,
            "note": ("an interpretation is a PROPOSAL; family compatibility and "
                     "geometry admissibility are decided by deterministic code"),
        }


def _find_parameters(text: str, family: Optional[str]) -> Dict[str, float]:
    """Pull declared parameter names out of the text. Nothing else is read."""
    if not family or family not in PARAMETER_VOCABULARY:
        return {}
    found: Dict[str, float] = {}
    lowered = text.lower()
    for name in PARAMETER_VOCABULARY[family]:
        spoken = name.replace("_", "[ _-]?")
        for pattern in (rf"{spoken}\s*(?:=|of|is|:)?\s*{_NUMBER}",
                        rf"{_NUMBER}\s*(?:m|mm|k|pa)?\s*{spoken}"):
            match = re.search(pattern, lowered)
            if match:
                try:
                    found[name] = float(match.group(1))
                except ValueError:
                    continue
                break
    return found


def deterministic_interpret(prompt: str, *,
                            geometry_source: str = "parametric") -> ProblemStatement:
    """Keyword interpretation over the register. No API key, reproducible."""
    lowered = prompt.lower()
    hits = {
        family: [word for word in words if word in lowered]
        for family, words in _KEYWORDS.items()
    }
    hits = {k: v for k, v in hits.items() if v}
    ranked = sorted(hits.items(), key=lambda kv: (-len(kv[1]), kv[0]))
    proposed = ranked[0][0] if ranked else None
    note = "no registered family keyword appeared in the request"
    if len(ranked) > 1:
        note = (f"several families matched ({[k for k, _ in ranked]}); the "
                "strongest keyword match is proposed and the matcher decides")
    elif ranked:
        note = f"matched on {hits[proposed]}"
    return ProblemStatement(
        prompt=prompt,
        proposed_family=proposed,
        parameters=_find_parameters(prompt, proposed),
        geometry_source=geometry_source,
        keyword_hits=hits,
        confidence_note=note,
    )


_INTERPRETER: Callable[..., ProblemStatement] = deterministic_interpret


def set_interpreter(func: Callable[..., ProblemStatement]) -> None:
    """Substitute an LLM interpreter. Its output stays non-binding."""
    global _INTERPRETER
    _INTERPRETER = func


def interpret(prompt: str, *, geometry_source: str = "parametric") -> ProblemStatement:
    statement = _INTERPRETER(prompt, geometry_source=geometry_source)
    # A model may not invent a family. Unknown proposals are dropped here, before
    # anything downstream can act on them.
    if statement.proposed_family and statement.proposed_family not in caps.TABLE:
        statement.confidence_note += (
            f" | proposed family {statement.proposed_family!r} is not registered "
            "and was discarded"
        )
        statement.proposed_family = None
    return statement
