#!/usr/bin/env python3
"""Shared fixtures for the 2D forward-step tests.

These build the synthetic OpenFOAM-shaped case from ``synthetic.py``. Nothing
here runs OpenFOAM: ordinary test discovery must never launch a simulation.
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from src.pipeline.forward_step_2d.collect_evidence import collect
from tests.forward_step_2d.synthetic import make_case


@pytest.fixture(scope="session")
def synthetic_run():
    """A complete synthetic run: (root, case, evidence index)."""
    root = Path(tempfile.mkdtemp())
    case = make_case(root)
    index = collect(case, root / "out")
    return root, case, index


@pytest.fixture
def synthetic_diagnostics(synthetic_run):
    """A healthy diagnostics document, fresh per test so it can be mutated."""
    root, _, _ = synthetic_run
    return json.loads((root / "out/diagnostics.json").read_text())
