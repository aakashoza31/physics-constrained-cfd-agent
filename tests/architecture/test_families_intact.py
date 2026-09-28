#!/usr/bin/env python3
"""The existing frozen families must be untouched by this refactor."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def test_legacy_forward_step_runner_default_path_is_unchanged():
    """No orchestrator import and no new default flag in the legacy runner."""
    text = (REPO / "scripts/run_forward_step_2d.py").read_text()
    assert "src.orchestrator" not in text
    assert "src.families" not in text
    assert "class ForwardStepRun" in text


def test_legacy_nozzle_runner_is_unchanged():
    text = (REPO / "scripts/run_nozzle_feedback.py").read_text()
    assert "src.orchestrator" not in text
    assert "src.families" not in text


def test_frozen_family_modules_carry_no_new_imports():
    for rel in (
        "src/pipeline/forward_step_2d/validate.py",
        "src/pipeline/forward_step_2d/diagnostics.py",
        "src/pipeline/forward_step_2d/spec.py",
        "src/pipeline/forward_step_2d/build.py",
        "src/reasoning/forward_step_actions.py",
        "src/reasoning/forward_step_scope_gate.py",
    ):
        text = (REPO / rel).read_text()
        assert "src.orchestrator" not in text, rel
        assert "src.families" not in text, rel


def test_the_only_new_file_inside_a_frozen_family_package_is_additive():
    """regions.py is new; it must not be imported by any frozen module."""
    for path in (REPO / "src/pipeline/forward_step_2d").glob("*.py"):
        if path.name == "regions.py":
            continue
        assert "regions" not in path.read_text(), path.name


def test_existing_family_test_suites_still_pass():
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/forward_step_2d", "-q",
         "--no-header", "-p", "no:cacheprovider"],
        cwd=REPO, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stdout[-4000:] + result.stderr[-2000:]
