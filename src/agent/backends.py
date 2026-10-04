#!/usr/bin/env python3
"""Agent backends: who does the interpreting and the diagnosing.

Three backends, one contract. Whichever answers, the answer is a PROPOSAL and
the deterministic gates still decide.

  deterministic  keyword interpretation and recipe-driven diagnosis. No API key,
                 reproducible, and the default. Documentation must never call a
                 deterministic run an LLM run.
  gemini         a real model call through the repository's existing LLM
                 infrastructure (`src/agents/llm_provenance.py`, `google.genai`).
                 Credentials come from GEMINI_API_KEY; nothing is stored in git.
  replay         no model call. Recorded model responses are NOT replayed by
                 this backend: it behaves like the deterministic backend
                 (keyword interpretation; the diagnosis proposal comes from
                 the family recipe), and in pipeline replay mode the archived
                 proposals are read from the case evidence by
                 `src/orchestration/replay.py`, not by this backend.

What a model may return is bounded by schema, not by trust: an interpretation
names a registered family or none, and a diagnosis names an action from the
family's registered vocabulary. Anything else is dropped with a reason, and the
drop is recorded. A model cannot change a threshold, and it cannot reach the
verdict -- `src/authority/boundary.py` enforces both.

Scope note: the generic `gemini` backend here is a simplified demonstration
path. It sends a plain prompt with no system instruction, no response schema
and no theory-blind evidence packet, and it is not the path used for the
paper's runs. Those runs go through the family runners
(`scripts/run_nozzle_feedback.py`, `scripts/run_nozzle_e2e.py`,
`scripts/run_forward_step_2d.py`), which use `src/agents/` and
`src/reasoning/` with structured schemas and deterministic action validators.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from src.families import capabilities as caps

BACKENDS_VERSION = "agent-backends/1.0.0"
PROMPT_SCHEMA_VERSION = "agent-prompts/1.0.0"

DETERMINISTIC = "deterministic"
GEMINI = "gemini"
REPLAY = "replay"
BACKENDS = (DETERMINISTIC, GEMINI, REPLAY)

DEFAULT_TEMPERATURE = 0.0


class BackendUnavailable(RuntimeError):
    """The requested backend cannot run here. Never silently downgraded."""


@dataclass
class ModelCall:
    """Everything needed to audit one model contribution."""

    stage: str
    backend: str
    provider: str = ""
    model: str = ""
    temperature: Optional[float] = None
    prompt_schema_version: str = PROMPT_SCHEMA_VERSION
    prompt: str = ""
    raw_response: Any = None
    parsed: Dict[str, Any] = field(default_factory=dict)
    proposed_action: Optional[str] = None
    action_in_vocabulary: Optional[bool] = None
    authority_accepted: Optional[bool] = None
    latency_s: Optional[float] = None
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    cost_usd: Optional[float] = None
    error: str = ""
    dropped: List[str] = field(default_factory=list)

    @property
    def is_llm(self) -> bool:
        return self.backend == GEMINI and not self.error

    def to_dict(self) -> Dict[str, Any]:
        data = {k: getattr(self, k) for k in self.__dataclass_fields__}
        data["is_llm"] = self.is_llm
        data["binding"] = False
        data["label"] = (f"LLM:{self.model}" if self.is_llm
                         else f"{self.backend.upper()}")
        return data


@dataclass
class AgentBackend:
    """One backend, and the record of everything it was asked."""

    name: str
    calls: List[ModelCall] = field(default_factory=list)

    # -- interpretation -------------------------------------------------
    def interpret(self, prompt: str, *, geometry_source: str = "parametric"):
        from src.agent.interpret import ProblemStatement, deterministic_interpret

        if self.name != GEMINI:
            statement = deterministic_interpret(
                prompt, geometry_source=geometry_source)
            statement.interpreter = self.name
            self.calls.append(ModelCall(
                stage="interpretation", backend=self.name,
                prompt=prompt, parsed=statement.to_dict(),
                raw_response=None))
            return statement

        call = ModelCall(stage="interpretation", backend=GEMINI, prompt=prompt)
        try:
            parsed = _gemini_json(_interpretation_prompt(prompt), call)
        except BackendUnavailable:
            raise
        except Exception as exc:                     # noqa: BLE001 - recorded
            call.error = f"{type(exc).__name__}: {exc}"
            self.calls.append(call)
            raise BackendUnavailable(
                f"the model interpretation failed and is not silently replaced "
                f"by the deterministic one: {call.error}") from exc

        family = parsed.get("family")
        if family is not None and caps.resolve(str(family)) not in caps.TABLE:
            call.dropped.append(
                f"proposed family {family!r} is not registered; discarded")
            family = None
        parameters = {k: float(v) for k, v in (parsed.get("parameters") or {}).items()
                      if isinstance(v, (int, float)) and not isinstance(v, bool)}
        call.parsed = {"family": family, "parameters": parameters,
                       "reasoning": parsed.get("reasoning", "")}
        self.calls.append(call)

        statement = ProblemStatement(
            prompt=prompt,
            proposed_family=caps.resolve(str(family)) if family else None,
            parameters=parameters,
            geometry_source=geometry_source,
            confidence_note=str(parsed.get("reasoning", ""))[:400],
            interpreter=f"{GEMINI}:{call.model}",
        )
        return statement

    # -- diagnosis ------------------------------------------------------
    def diagnose(self, family: str, evidence: Dict[str, Any]) -> ModelCall:
        """Diagnose CFD evidence. The action must be in the registered vocabulary."""
        allowed = list(caps.capabilities(family).allowed_actions)
        if self.name != GEMINI:
            call = ModelCall(stage="diagnosis", backend=self.name,
                             parsed={"note": ("deterministic backend: the family "
                                              "recipe supplies the proposal")},
                             proposed_action=None, action_in_vocabulary=None)
            self.calls.append(call)
            return call

        call = ModelCall(stage="diagnosis", backend=GEMINI,
                         prompt="<cfd evidence diagnosis>")
        try:
            parsed = _gemini_json(_diagnosis_prompt(family, evidence, allowed), call)
        except BackendUnavailable:
            raise
        except Exception as exc:                     # noqa: BLE001 - recorded
            call.error = f"{type(exc).__name__}: {exc}"
            self.calls.append(call)
            return call

        action = parsed.get("action")
        call.parsed = {"diagnosis": parsed.get("diagnosis", ""),
                       "evidence_used": parsed.get("evidence_used", []),
                       "action": action}
        call.proposed_action = str(action) if action else None
        call.action_in_vocabulary = bool(action in allowed)
        if action and not call.action_in_vocabulary:
            call.dropped.append(
                f"action {action!r} is outside the registered vocabulary "
                f"{allowed}; refused")
            call.proposed_action = None
        self.calls.append(call)
        return call

    def to_dict(self) -> Dict[str, Any]:
        return {
            "backends_version": BACKENDS_VERSION,
            "backend": self.name,
            "calls": [c.to_dict() for c in self.calls],
            "llm_calls": sum(1 for c in self.calls if c.is_llm),
            "note": ("a backend proposes; deterministic authority decides. No "
                     "model output here altered a threshold or a verdict."),
        }


# ----------------------------------------------------------------------
def _interpretation_prompt(prompt: str) -> str:
    families = json.dumps(
        {name: {"physics": cap.physics.to_dict(),
                "characteristic_dimension": cap.characteristic_dimension,
                "routable": cap.routable}
         for name, cap in caps.TABLE.items()}, indent=1)
    return f"""You are interpreting an engineering CFD request.

Registered families (you may ONLY name one of these keys, or null):
{families}

Return STRICT JSON: {{"family": <key or null>, "parameters": {{<name>: <number>}},
"reasoning": "<one sentence>"}}

Rules: never invent a family. Never invent a numeric value that is not stated in
the request. If no family fits, return null and say why in one sentence.

REQUEST:
{prompt}
"""


def _diagnosis_prompt(family: str, evidence: Dict[str, Any],
                      allowed: List[str]) -> str:
    return f"""You are diagnosing CFD evidence for the registered family {family!r}.

You may propose exactly one action from this closed vocabulary: {allowed}

Return STRICT JSON: {{"diagnosis": "<short>", "evidence_used": ["<field>", ...],
"action": "<one of the vocabulary>"}}

Rules: your diagnosis is a PROPOSAL. Deterministic gates decide acceptance and
you cannot change a threshold. Base every statement on a field that appears in
the evidence below. Do not assert convergence or validation yourself.

EVIDENCE:
{json.dumps(evidence, indent=1, default=str)[:12000]}
"""


def _gemini_json(prompt: str, call: ModelCall) -> Dict[str, Any]:
    """One real model call. Credentials from the environment, never from git."""
    from src.agents import llm_provenance

    if not llm_provenance.gemini_key_present():
        raise BackendUnavailable(
            "GEMINI_API_KEY is not set. The gemini backend is not silently "
            "replaced by the deterministic one: export the key, or run with "
            "--agent-backend deterministic and do not call the result an LLM run.")
    try:
        from google import genai
        from google.genai import types
    except ImportError as exc:
        raise BackendUnavailable(
            f"the google-genai client is not installed: {exc}") from exc

    model = llm_provenance.gemini_model_name()
    temperature = float(os.getenv("AGENT_TEMPERATURE", DEFAULT_TEMPERATURE))
    call.provider = "google"
    call.model = model
    call.temperature = temperature

    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    started = time.time()
    response = client.models.generate_content(
        model=model,
        contents=prompt,
        config=types.GenerateContentConfig(
            temperature=temperature,
            response_mime_type="application/json",
        ),
    )
    call.latency_s = round(time.time() - started, 3)
    text = getattr(response, "text", "") or ""
    call.raw_response = text[:8000]
    usage = getattr(response, "usage_metadata", None)
    if usage is not None:
        call.input_tokens = getattr(usage, "prompt_token_count", None)
        call.output_tokens = getattr(usage, "candidates_token_count", None)
    return json.loads(text)


def make(name: str) -> AgentBackend:
    if name not in BACKENDS:
        raise ValueError(f"backend must be one of {BACKENDS}; got {name!r}")
    if name == GEMINI:
        from src.agents import llm_provenance
        if not llm_provenance.gemini_key_present():
            raise BackendUnavailable(
                "GEMINI_API_KEY is not set, so the gemini backend cannot run. "
                "Use --agent-backend deterministic for a no-key run; that is a "
                "deterministic run and must not be described as an LLM run.")
    return AgentBackend(name=name)
