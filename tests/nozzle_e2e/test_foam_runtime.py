"""The execution bridge: path mapping, command plumbing and preflight.

These tests exercise the bridge itself with harmless commands. They never
simulate OpenFOAM: if Foundation v14 is absent, preflight must say so clearly
rather than pretend.
"""
from __future__ import annotations

import platform
import shutil
import sys
from pathlib import Path, PurePosixPath

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from src.pipeline.foam_runtime import (  # noqa: E402
    FoamRuntime,
    FoamRuntimeError,
)


def test_windows_paths_map_onto_the_wsl_mount():
    runtime = FoamRuntime(mode="wsl")

    assert (
        runtime.to_runtime_path(r"C:\Users\aakash\Desktop\repo")
        == "/mnt/c/Users/aakash/Desktop/repo"
    )
    assert (
        runtime.to_runtime_path(r"D:\Research\physics-constrained-cfd-agent")
        == "/mnt/d/Research/physics-constrained-cfd-agent"
    )


def test_unmappable_paths_are_refused_rather_than_guessed():
    runtime = FoamRuntime(mode="wsl")

    with pytest.raises(FoamRuntimeError):
        runtime.to_runtime_path("/home/aakash/repo")


def test_wsl_invocation_matches_the_repository_probe_pattern():
    runtime = FoamRuntime(mode="wsl", distro="Ubuntu-24.04")

    argv = runtime._argv("echo hello")

    assert argv[:5] == ["wsl.exe", "-d", "Ubuntu-24.04", "--", "bash"]
    assert argv[5] == "-lc"


@pytest.mark.skipif(platform.system() == "Windows" or shutil.which("bash") is None, reason="native Linux bash test")
def test_local_command_plumbing(tmp_path):
    runtime = FoamRuntime(mode="linux")

    result = runtime.bash("echo plumbing-ok", foam=False, timeout=60)

    assert result.ok
    assert "plumbing-ok" in result.stdout


@pytest.mark.skipif(platform.system() == "Windows" or shutil.which("bash") is None, reason="native Linux bash test")
def test_write_read_and_fetch_round_trip(tmp_path):
    runtime = FoamRuntime(mode="linux")

    remote = PurePosixPath(tmp_path / "note.json")
    runtime.write_text(remote, '{"value": 42}')

    assert '"value": 42' in runtime.read_text(remote)

    local = tmp_path / "fetched.json"

    assert runtime.fetch(remote, local) is True
    assert '"value": 42' in local.read_text()

    assert runtime.fetch(PurePosixPath(tmp_path / "missing.json"), local) is False


@pytest.mark.skipif(platform.system() == "Windows" or shutil.which("bash") is None, reason="native Linux bash test")
def test_preflight_reports_a_missing_installation_honestly():
    runtime = FoamRuntime(mode="linux")

    info = runtime.preflight()

    assert set(
        ["mode", "openfoam_version", "numpy", "missing_tools", "ok"]
    ) <= set(info)

    if not info["ok"]:
        assert info["reason"]
        assert "14" in info["reason"] or "missing utilities" in info["reason"]
