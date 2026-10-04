#!/usr/bin/env python3
"""Append-only provenance ledger.

One JSONL record per stage, written once and never rewritten. decide_once and
run_loop record their stages here, and the legacy ablation harness in src/eval
passes one ledger per mode. The paper's controller comparison
(paper/cfd_forge/scripts/controller_comparison.py) writes its own records and
does not read this ledger.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

# The stages a run may record. A stage name outside this set is a programming
# error, not a data value, so it raises.
STAGES = (
    "run_start",
    "request",
    "routing",
    "llm_call",
    "scope_gate",
    "case_build",
    "case_change",
    "solver_execution",
    "evidence",
    "diagnosis",
    "proposed_action",
    "deterministic_ruling",
    "region_selection",
    "mesh_refinement",
    "validation",
    "fault_injection",
    "final_decision",
    "run_end",
)


def _jsonable(obj: Any) -> Any:
    if obj is None or isinstance(obj, (bool, int, float, str)):
        return obj
    if isinstance(obj, dict):
        return {str(k): _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [_jsonable(v) for v in obj]
    for attr in ("to_dict", "as_dict", "_asdict"):
        fn = getattr(obj, attr, None)
        if callable(fn):
            try:
                return _jsonable(fn())
            except Exception:  # pragma: no cover - defensive
                break
    if hasattr(obj, "__dataclass_fields__"):
        return {k: _jsonable(getattr(obj, k)) for k in obj.__dataclass_fields__}
    return repr(obj)


@dataclass
class Ledger:
    """Append-only JSONL writer. Best-effort: a write failure never aborts a run."""

    path: Optional[Path] = None
    run_id: str = ""
    mode: str = "full_constrained_agent"
    _seq: int = 0
    _mirror: List[Dict[str, Any]] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self._mirror is None:
            self._mirror = []
        if not self.run_id:
            self.run_id = f"run-{int(time.time() * 1000):x}-{os.getpid():x}"
        if self.path is not None:
            self.path = Path(self.path)
            self.path.parent.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    def record(self, stage: str, payload: Any = None, **fields: Any) -> Dict[str, Any]:
        if stage not in STAGES:
            raise ValueError(f"unknown ledger stage {stage!r}")
        self._seq += 1
        row: Dict[str, Any] = {
            "seq": self._seq,
            "run_id": self.run_id,
            "mode": self.mode,
            "wall": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()),
            "stage": stage,
        }
        if payload is not None:
            row["payload"] = _jsonable(payload)
        for key, value in fields.items():
            row[key] = _jsonable(value)
        self._mirror.append(row)
        if self.path is not None:
            try:
                with self.path.open("a", encoding="utf-8") as fh:
                    fh.write(json.dumps(row, sort_keys=True) + "\n")
            except OSError:
                pass
        return row

    # ------------------------------------------------------------------
    @property
    def rows(self) -> List[Dict[str, Any]]:
        return list(self._mirror)

    def stages(self) -> List[str]:
        return [r["stage"] for r in self._mirror]

    def of_stage(self, stage: str) -> List[Dict[str, Any]]:
        return [r for r in self._mirror if r["stage"] == stage]

    @classmethod
    def read(cls, path: Path) -> List[Dict[str, Any]]:
        rows: List[Dict[str, Any]] = []
        for line in Path(path).read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                rows.append(json.loads(line))
        return rows
