#!/usr/bin/env python3
"""The documentation must not promise what the code refuses to do."""
from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import List

import pytest

_ROOT = Path(__file__).resolve().parents[2]

REQUIRED_DOCS = ("architecture.md", "scientific_authority.md",
                 "family_protocol.md", "cad_and_step_input.md",
                 "reproducibility.md", "results.md", "limitations.md",
                 "adding_a_family.md")

CONTROLLER_COMPARISON = "evidence/controller_comparison/20261001T213031Z"

#: A path on one developer's machine or session sandbox.
MACHINE_PATH = re.compile(r"/home/[a-z]+/|C:(\\){1,2}Users|C:(\\){1,2}Backup")

#: Placeholder user names used in docstrings and test fixtures to illustrate a
#: path translation. They name no real machine.
PLACEHOLDER = re.compile(r"/home/(someone|user|u)/|C:(\\){1,2}Users(\\){1,2}(\.\.\.|example\b|x\\)|C:(\\){1,2}Users(?![\\\w])")

#: The ablation's NOT_RUN marker, but not CFD_NOT_RUN (a mesh-rejection status).
ABLATION_NOT_RUN = re.compile(r"(?<![A-Za-z_])NOT_RUN\b")

#: Committed material scanned for machine paths. paper/cfd_forge/data holds the
#: archived provenance records, whose recorded source paths are intentional.
SCANNED = ("README.md", "docs", "evidence", "cases", "demo", "configs",
           "evaluation", "scripts", "paper", "src", "tests", "manifests")
EXCLUDED = ("paper/cfd_forge/data/",)
TEXT_SUFFIXES = {".md", ".py", ".json", ".jsonl", ".yaml", ".yml", ".txt",
                 ".sh", ".ps1", ".tex", ".bib", ".csv", ".toml", ".cfg", ""}


def _committed_files() -> List[Path]:
    try:
        out = subprocess.run(
            ["git", "ls-files", "-co", "--exclude-standard", "--", *SCANNED],
            cwd=_ROOT, capture_output=True, text=True, timeout=60, check=True)
        names = out.stdout.splitlines()
    except (OSError, subprocess.SubprocessError):
        names = [str(p.relative_to(_ROOT)).replace("\\", "/")
                 for top in SCANNED for p in
                 ([_ROOT / top] if (_ROOT / top).is_file()
                  else (_ROOT / top).rglob("*"))
                 if p.is_file()]
    files = []
    for name in names:
        if any(name.startswith(prefix) for prefix in EXCLUDED):
            continue
        path = _ROOT / name
        if path.resolve() == Path(__file__).resolve():
            continue                      # the patterns themselves live here
        if path.suffix.lower() in TEXT_SUFFIXES and path.is_file():
            files.append(path)
    return files


@pytest.mark.parametrize("name", REQUIRED_DOCS)
def test_every_required_document_exists_and_has_content(name):
    path = _ROOT / "docs" / name
    assert path.exists(), f"docs/{name} is missing"
    assert len(path.read_text(encoding="utf-8").split()) > 120


def test_the_readme_names_the_project_and_the_comparison_evidence():
    text = (_ROOT / "README.md").read_text(encoding="utf-8")
    assert "CFD Forge" in text
    assert CONTROLLER_COMPARISON in text
    assert (_ROOT / CONTROLLER_COMPARISON).is_dir()


def test_the_evaluation_readme_does_not_claim_the_comparison_was_not_run():
    text = (_ROOT / "evaluation" / "README.md").read_text(encoding="utf-8")
    assert "controller_comparison" in text
    for sentence in re.split(r"(?<=[.!?])\s+", text):
        lowered = sentence.lower()
        unrun = (ABLATION_NOT_RUN.search(sentence)
                 or re.search(r"\b(not (yet )?(been )?run|never run|unrun)\b", lowered))
        if unrun:
            assert "comparison" not in lowered and "paper" not in lowered, (
                f"evaluation/README.md says the comparison was not run: {sentence!r}")


def test_no_document_marks_an_experiment_not_run():
    hits = []
    for path in sorted((_ROOT / "docs").rglob("*.md")):
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if ABLATION_NOT_RUN.search(line):
                hits.append(f"{path.relative_to(_ROOT)}:{n}: {line.strip()}")
    assert not hits, "NOT_RUN (other than CFD_NOT_RUN) in docs/:\n" + "\n".join(hits)


def test_the_readme_states_what_is_not_claimed():
    text = (_ROOT / "README.md").read_text(encoding="utf-8").lower()
    assert "does **not** claim" in text or "does not claim" in text
    assert "cfd_not_run" in text
    assert "no family accepts step" in text


def test_the_readme_does_not_present_the_cube_as_a_success():
    text = (_ROOT / "README.md").read_text(encoding="utf-8")
    assert "not a validated benchmark claim" in text
    assert "no turbulent validation claim" in text
    assert "outside the agent loop" in text
    assert "registered retrospectively" in text


def test_no_machine_paths_in_committed_files():
    """A reader clones this; nothing may point at one developer's disk."""
    suspects = []
    for path in _committed_files():
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for n, line in enumerate(text.splitlines(), 1):
            if MACHINE_PATH.search(line) and not PLACEHOLDER.search(line):
                suspects.append(f"{path.relative_to(_ROOT)}:{n}: {line.strip()[:160]}")
    assert not suspects, "machine-specific paths:\n" + "\n".join(suspects)
