"""Deterministic scientific authority. The LLM never decides anything here."""
from src.authority.boundary import (  # noqa: F401
    AUTHORITY_DECIDES,
    LLM_MAY,
    AuthorityTrace,
    AuthorityViolation,
    Decision,
    assert_authority_owns,
    assert_llm_may,
    final_decision,
)
