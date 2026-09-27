#!/usr/bin/env python3
"""Experiment modes.

Every paper experiment is a switch on the ONE orchestrator, never a separate
script. That is the point: an ablation that ran different code would not be an
ablation of this system.
"""
from __future__ import annotations

from dataclasses import dataclass

#: The system as proposed.
FULL = "full_constrained_agent"
#: No LLM at all: the frozen recipe drives actions from evidence.
RECIPE_BASELINE = "parameterized_recipe_baseline"
#: Deterministic gates present but not authoritative: the LLM's proposal is
#: executed and the LLM's own verdict is taken as the decision.
GATES_OFF = "gates_off"
#: One shot: no diagnosis, no corrective action, no rerun.
NO_DIAGNOSIS = "no_diagnosis_loop"

MODES = (FULL, RECIPE_BASELINE, GATES_OFF, NO_DIAGNOSIS)


@dataclass(frozen=True)
class Mode:
    """Resolved behaviour flags for one experiment mode."""

    name: str
    use_llm_diagnosis: bool
    gates_authoritative: bool
    allow_corrective_actions: bool
    max_iterations: int

    @property
    def is_ablation(self) -> bool:
        return self.name != FULL


def resolve(name: str, *, max_iterations: int = 4) -> Mode:
    if name not in MODES:
        raise ValueError(f"unknown mode {name!r}; expected one of {MODES}")
    if name == FULL:
        return Mode(name, True, True, True, max_iterations)
    if name == RECIPE_BASELINE:
        return Mode(name, False, True, True, max_iterations)
    if name == GATES_OFF:
        return Mode(name, True, False, True, max_iterations)
    return Mode(NO_DIAGNOSIS, False, True, False, 1)
