#!/usr/bin/env python3
"""Provenance path keys must be POSIX on every platform.

str(PurePath) uses the host separator, so on Windows a hash document keyed with
str() gains backslashes and stops comparing equal to the canonical
representation. The hashed bytes are unaffected; only serialization was wrong.
"""
from __future__ import annotations

import ast
import json
from pathlib import Path, PureWindowsPath

import pytest

REPO = Path(__file__).resolve().parents[2]

SERIALIZING_MODULES = (
    "src/pipeline/forward_step_2d/build.py",
    "src/pipeline/forward_step/build.py",
    "src/pipeline/forward_step_2d/collect_evidence.py",
)


@pytest.mark.parametrize("rel", SERIALIZING_MODULES)
def test_no_str_of_a_relative_to_call_survives(rel):
    """str(x.relative_to(y)) is the defect; as_posix() is the fix."""
    tree = ast.parse((REPO / rel).read_text())
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "str"
            and node.args
            and isinstance(node.args[0], ast.Call)
            and isinstance(node.args[0].func, ast.Attribute)
            and node.args[0].func.attr == "relative_to"
        ):
            pytest.fail(
                f"{rel}:{node.lineno} serializes a relative path with str(); "
                "use .relative_to(...).as_posix()"
            )


@pytest.mark.parametrize("rel", SERIALIZING_MODULES)
def test_each_module_uses_as_posix(rel):
    assert "as_posix()" in (REPO / rel).read_text()


def test_windows_style_relative_path_renders_with_forward_slashes():
    """The property the fix relies on, asserted directly."""
    p = PureWindowsPath("system") / "fvSchemes"
    assert str(p) == "system\\fvSchemes"
    assert p.as_posix() == "system/fvSchemes"


def test_template_hash_keys_are_posix(tmp_path):
    from src.pipeline.forward_step_2d.build import build
    from src.pipeline.forward_step_2d.spec import CANONICAL_SPEC

    case = build(CANONICAL_SPEC, tmp_path / "case")
    hashes = json.loads((case / "template_hashes.json").read_text())
    assert hashes, "hash document is empty"
    assert not any("\\" in k for k in hashes), (
        f"backslash in hash keys: {[k for k in hashes if chr(92) in k]}"
    )
    assert "system/fvSchemes" in hashes
    for key in hashes:
        assert not key.startswith("/") and ".." not in key


def test_evidence_index_data_files_are_posix(fs_out_dir):
    """data_files is provenance too, and had the identical defect."""
    import json as _json

    index = _json.loads((fs_out_dir / "evidence_index.json").read_text())
    assert index["data_files"], "no data files recorded"
    assert not any("\\" in f for f in index["data_files"])
