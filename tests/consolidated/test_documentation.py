#!/usr/bin/env python3
"""The documentation must not promise what the code refuses to do."""
from __future__ import annotations

from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]

REQUIRED_DOCS = ("paper_overview.md", "architecture.md", "scientific_authority.md",
                 "family_protocol.md", "cad_and_step_input.md",
                 "reproducibility.md", "results.md", "limitations.md",
                 "adding_a_family.md")


@pytest.mark.parametrize("name", REQUIRED_DOCS)
def test_every_required_document_exists_and_has_content(name):
    path = _ROOT / "docs" / name
    assert path.exists(), f"docs/{name} is missing"
    assert len(path.read_text(encoding="utf-8").split()) > 120


def test_the_manuscript_outline_has_every_required_section():
    text = (_ROOT / "paper" / "manuscript_outline.md").read_text()
    for section in ("Abstract", "Introduction", "Related work", "Method",
                    "Scientific authority", "Family registration protocol",
                    "Experiments", "Evaluation", "Results",
                    "Failure and rejection analysis", "Limitations",
                    "Discussion", "Conclusion"):
        assert section.lower() in text.lower(), section


def test_unrun_experiments_are_marked_not_run():
    text = (_ROOT / "paper" / "manuscript_outline.md").read_text()
    assert "NOT_RUN" in text
    assert "NOT_RUN" in (_ROOT / "evaluation" / "README.md").read_text()


def test_the_readme_states_what_is_not_claimed():
    text = (_ROOT / "README.md").read_text().lower()
    assert "does **not** claim" in text or "does not claim" in text
    assert "cfd_not_run" in text
    assert "no family accepts step" in text


def test_the_readme_does_not_present_the_cube_as_a_success():
    text = (_ROOT / "README.md").read_text()
    assert "RUNTIME REJECTED" in text
    assert "rejected" in text.lower()


def test_no_absolute_local_paths_in_the_new_sources():
    """A reviewer clones this; nothing may point at one developer's disk."""
    suspects = []
    for pattern in ("src/agent", "src/authority", "src/geometry",
                    "src/orchestration", "src/reporting", "src/evaluation",
                    "src/families/capabilities.py", "src/families/cube"):
        base = _ROOT / pattern
        files = [base] if base.is_file() else list(base.rglob("*.py"))
        for path in files:
            text = path.read_text(encoding="utf-8")
            for needle in ("C:\\\\", "C:/", "/home/claude", "/Users/"):
                if needle in text:
                    suspects.append(f"{path.relative_to(_ROOT)}: {needle}")
    assert not suspects, f"hard-coded paths: {suspects}"


def test_scripts_carry_no_absolute_local_paths():
    suspects = []
    for name in ("run_agent.py", "run_demo.py", "run_evaluation.py",
                 "build_case_library.py"):
        text = (_ROOT / "scripts" / name).read_text(encoding="utf-8")
        for needle in ("C:\\\\", "C:/", "/home/claude", "/Users/"):
            if needle in text:
                suspects.append(f"{name}: {needle}")
    assert not suspects, f"hard-coded paths: {suspects}"
