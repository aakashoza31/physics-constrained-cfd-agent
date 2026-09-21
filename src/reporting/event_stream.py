"""Real event stream for the end-to-end nozzle demonstration.

Every event is emitted at the call site of an action that actually happened.
Nothing in this module generates an event on a timer, and nothing replays a
recorded trajectory: if an event appears, the corresponding tool call, solver
step, deterministic check or LLM request was just made.

The stream is written twice:
  - stdout, tagged, for screen recording
  - <run_dir>/events.jsonl, one JSON object per line, for machine checking

LLM participation is recorded explicitly.  Every event produced by a reasoning
step carries ``llm_source``, which is either the model identifier actually
called or ``deterministic_fallback``.  A fallback can therefore never be
mistaken for the model in either the printed stream or the archived record.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional


ORCHESTRATOR = "ORCHESTRATOR"
SCOPE_GATE = "SCOPE GATE"
MESH_TOOL = "MESH TOOL"
CFD_SETUP = "CFD SETUP"
INITIALIZER = "INITIALIZER"
EXECUTOR = "EXECUTOR"
DIAGNOSTICS = "DIAGNOSTICS"
LLM = "LLM"
ACTION_VALIDATOR = "ACTION VALIDATOR"
SCIENTIFIC_VALIDATOR = "SCIENTIFIC VALIDATOR"
REPORTER = "REPORTER"
PREFLIGHT = "PREFLIGHT"

TAGS = [
    ORCHESTRATOR,
    SCOPE_GATE,
    PREFLIGHT,
    MESH_TOOL,
    CFD_SETUP,
    INITIALIZER,
    EXECUTOR,
    DIAGNOSTICS,
    LLM,
    ACTION_VALIDATOR,
    SCIENTIFIC_VALIDATOR,
    REPORTER,
]


@dataclass
class EventStream:
    run_dir: Path
    case_id: str = ""
    echo: bool = True
    events: List[Dict[str, Any]] = field(default_factory=list)
    _t0: float = field(default_factory=time.monotonic)

    def __post_init__(self) -> None:
        self.run_dir = Path(self.run_dir)
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.path = self.run_dir / "events.jsonl"
        self.log_path = self.run_dir / "events.log"
        self.path.write_text("", encoding="utf-8")
        self.log_path.write_text("", encoding="utf-8")

    # ------------------------------------------------------------------

    def emit(
        self,
        tag: str,
        message: str,
        *,
        data: Optional[Dict[str, Any]] = None,
        status: str = "INFO",
        llm_source: Optional[str] = None,
    ) -> Dict[str, Any]:
        if tag not in TAGS:
            raise ValueError(f"Unknown event tag: {tag}")

        event = {
            "t_s": round(time.monotonic() - self._t0, 3),
            "wall": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "case_id": self.case_id,
            "tag": tag,
            "status": status,
            "message": message,
        }

        if llm_source is not None:
            event["llm_source"] = llm_source

        if data:
            event["data"] = data

        self.events.append(event)

        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event) + "\n")

        line = self.format(event)

        with self.log_path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")

        if self.echo:
            print(line, flush=True)

        return event

    # Convenience wrappers -------------------------------------------------

    def ok(self, tag: str, message: str, **kwargs) -> Dict[str, Any]:
        return self.emit(tag, message, status="PASS", **kwargs)

    def fail(self, tag: str, message: str, **kwargs) -> Dict[str, Any]:
        return self.emit(tag, message, status="FAIL", **kwargs)

    # ------------------------------------------------------------------

    @staticmethod
    def format(event: Dict[str, Any]) -> str:
        tag = f"[{event['tag']}]".ljust(24)
        stamp = f"{event['t_s']:8.2f}s"
        status = event.get("status", "INFO")
        marker = {
            "PASS": "PASS",
            "FAIL": "FAIL",
            "INFO": "....",
        }.get(status, status)

        suffix = ""

        if "llm_source" in event:
            suffix = f"   <{event['llm_source']}>"

        return f"{stamp}  {tag} {marker}  {event['message']}{suffix}"

    # ------------------------------------------------------------------

    def summary(self) -> Dict[str, Any]:
        return {
            "case_id": self.case_id,
            "event_count": len(self.events),
            "failures": [e for e in self.events if e.get("status") == "FAIL"],
            "llm_sources": sorted(
                {
                    e["llm_source"]
                    for e in self.events
                    if "llm_source" in e
                }
            ),
        }
