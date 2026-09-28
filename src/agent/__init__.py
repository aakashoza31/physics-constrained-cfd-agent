"""The agent side of the system: interpret, route, diagnose, explain.

Everything here PROPOSES. Nothing here decides. The decision lives in
src/authority.
"""
from src.agent.pipeline import STAGES, AgentRun, run_pipeline  # noqa: F401
