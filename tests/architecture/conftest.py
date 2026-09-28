#!/usr/bin/env python3
"""Fixtures for the architecture tests. No OpenFOAM, no LLM, no CFD."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from src.families.forward_step_2d_adapter import ForwardStep2DAdapter
from src.pipeline.forward_step_2d.collect_evidence import collect
from src.pipeline.forward_step_2d.spec import ForwardStep2DSpec
from tests.forward_step_2d.synthetic import make_case


@pytest.fixture(scope="session")
def fs_run():
    """(root, case, out) for the synthetic run. Nothing here runs OpenFOAM."""
    root = Path(tempfile.mkdtemp())
    case = make_case(root)
    out = root / "out"
    collect(case, out)
    return root, case, out


@pytest.fixture(scope="session")
def fs_synthetic(fs_run):
    _, case, out = fs_run
    diagnostics = json.loads((out / "diagnostics.json").read_text())
    validation = json.loads((out / "validation.json").read_text())
    spec = ForwardStep2DSpec.load(case / "spec.json")
    return spec, diagnostics, validation


@pytest.fixture(scope="session")
def fs_out_dir(fs_run):
    return fs_run[2]


@pytest.fixture
def fs_adapter():
    return ForwardStep2DAdapter()


@pytest.fixture
def fs_spec(fs_synthetic):
    return fs_synthetic[0]


@pytest.fixture
def fs_evidence(fs_synthetic, fs_adapter):
    _, diagnostics, validation = fs_synthetic
    return fs_adapter.wrap_evidence(json.loads(json.dumps(diagnostics)),
                                    json.loads(json.dumps(validation)))
