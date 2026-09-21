"""Explicit provenance for every reasoning step.

Requirement: a deterministic fallback may exist for robustness, but it must
never silently impersonate the LLM.  Every reasoning call in the pipeline
returns one of these records, it is printed in the event stream, and it is
archived with the case evidence.  ``source`` is either the model identifier
that actually answered or the literal ``deterministic_fallback``.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, asdict, field
from typing import Any, Dict, List, Optional


GEMINI = "gemini"
FALLBACK = "deterministic_fallback"


@dataclass
class LLMCallRecord:
    stage: str
    source: str
    model: Optional[str] = None
    ok: bool = True
    error: Optional[str] = None
    latency_s: Optional[float] = None
    attempts: int = 1
    notes: List[str] = field(default_factory=list)

    @property
    def is_llm(self) -> bool:
        return self.source == GEMINI

    @property
    def label(self) -> str:
        """Short label used in the event stream."""
        if self.is_llm:
            return f"LLM:{self.model}"
        return "DETERMINISTIC_FALLBACK"

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["is_llm"] = self.is_llm
        data["label"] = self.label
        return data


class LLMUnavailable(RuntimeError):
    """Raised when the real LLM path is required but could not be used."""


def gemini_model_name() -> str:
    return os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")


def gemini_key_present() -> bool:
    return bool(os.getenv("GEMINI_API_KEY"))
