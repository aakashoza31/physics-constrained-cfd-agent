"""3-D extruded forward-step development family; experimental; not part of the CFD Forge paper.

Deterministic periodic forward-step Euler family with no LLM dependencies. The
template/ directory in this package is shared with the registered 2-D family
(src/pipeline/forward_step_2d), which reads it read-only.
"""
from .spec import ForwardStep3DSpec
from .build import build
from .execute import execute

__all__ = ['ForwardStep3DSpec', 'build', 'execute']
