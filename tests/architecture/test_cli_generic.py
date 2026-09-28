#!/usr/bin/env python3
"""The shared CLI must contain no family-specific code."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.families import registry

CLI = Path(__file__).resolve().parents[2] / "scripts/run_family.py"

FAMILY_SPECIFIC_SYMBOLS = (
    "ForwardStep2DSpec",
    "forward_step_2d.spec",
    "NozzleCaseSpec",
    "AirfoilSpec",
    "BackwardStepSpec",
    "diagnostics.json",
    "validation.json",
)


@pytest.mark.parametrize("symbol", FAMILY_SPECIFIC_SYMBOLS)
def test_cli_has_no_family_specific_symbol(symbol):
    assert symbol not in CLI.read_text(), (
        f"{symbol!r} in scripts/run_family.py makes the shared CLI "
        "family-specific; route it through adapter.load_spec / load_evidence"
    )


def test_cli_loads_only_through_the_adapter_hooks():
    text = CLI.read_text()
    assert "adapter.load_spec(" in text
    assert "adapter.load_evidence(" in text


def test_every_inspectable_adapter_implements_both_hooks():
    registry.install_standing_register()
    for record in registry.all_families():
        if not record.inspectable:
            continue
        adapter = registry.adapter(record.name)
        for hook in ("load_spec", "load_evidence"):
            assert callable(getattr(adapter, hook, None)), (
                f"{record.name} does not implement {hook}"
            )


def test_forward_step_load_spec_and_load_evidence_round_trip(
    fs_adapter, fs_spec, tmp_path
):
    (tmp_path / "spec.json").write_text(json.dumps(fs_spec.to_dict()))
    assert fs_adapter.load_spec(tmp_path / "spec.json").to_dict() == fs_spec.to_dict()


def test_forward_step_load_evidence_reads_an_output_directory(
    fs_adapter, fs_synthetic, tmp_path
):
    _, diagnostics, validation = fs_synthetic
    (tmp_path / "diagnostics.json").write_text(json.dumps(diagnostics))
    (tmp_path / "validation.json").write_text(json.dumps(validation))
    evidence = fs_adapter.load_evidence(tmp_path)
    assert evidence["family"] == "forward_step_2d"
    assert evidence["raw_diagnostics"] == diagnostics
    assert evidence["raw_validation"] == validation


def test_forward_step_load_evidence_says_what_is_missing(fs_adapter, tmp_path):
    with pytest.raises(FileNotFoundError) as exc:
        fs_adapter.load_evidence(tmp_path)
    assert "diagnostics.json" in str(exc.value)


@pytest.mark.parametrize("family", ["airfoil", "backward_step"])
def test_pending_family_load_spec_cannot_conjure_a_spec(family, tmp_path):
    """Either the recipe is unregistered (refuse), or there is simply no file."""
    registry.install_standing_register()
    adapter = registry.adapter(family)
    with pytest.raises((NotImplementedError, FileNotFoundError, OSError)) as exc:
        adapter.load_spec(tmp_path / "spec.json")
    if isinstance(exc.value, NotImplementedError):
        assert "unregistered" in str(exc.value)
