"""Provenance records for the model-backed reasoning stages.

Requirement: a deterministic fallback may exist for robustness, but it must
never silently impersonate the LLM.  The family runners' text stages
(interpretation, mesh review, diagnosis, summary) return an ``LLMCallRecord``,
which the runners print in the event stream and archive with the case
evidence.  ``source`` is the provider label ``"gemini"`` or the literal
``"deterministic_fallback"``; it is not a model identifier.  The model
identifier requested is stored in ``model`` (``None`` for a fallback), and the
version string reported by the SDK, when available, in ``model_version``.

The field observer (``cfd_visual_observer``) does not return an
``LLMCallRecord``; it writes its own observation record, which includes the
``model`` identifier it used.

``gemini_model_name()`` is the single source of the model identifier: the
``GEMINI_MODEL`` environment variable, else the shared default.  Callers read
it at request time.

``attempts`` counts model calls made for one record.  It is 2 when the nozzle
diagnosis repair call ran, in which case ``refused_first_decision`` holds the
first, refused decision and its validator reasons.
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
    # Optional audit fields.  Omitted from to_dict() when None so records
    # without them keep the same shape as the archived records.
    model_version: Optional[str] = None
    refused_first_decision: Optional[Dict[str, Any]] = None

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
        for optional_key in ("model_version", "refused_first_decision"):
            if data.get(optional_key) is None:
                data.pop(optional_key, None)
        data["is_llm"] = self.is_llm
        data["label"] = self.label
        return data


class LLMUnavailable(RuntimeError):
    """Raised when the real LLM path is required but could not be used."""


DEFAULT_GEMINI_MODEL = "gemini-3.5-flash-lite"


def gemini_model_name() -> str:
    """Model identifier for a Gemini request, read at call time."""
    return os.getenv("GEMINI_MODEL", DEFAULT_GEMINI_MODEL)


def gemini_key_present() -> bool:
    return bool(os.getenv("GEMINI_API_KEY"))
