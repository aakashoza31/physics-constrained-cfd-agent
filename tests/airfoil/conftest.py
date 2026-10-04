#!/usr/bin/env python3
"""Fixtures for the airfoil family (not part of the CFD Forge paper). No OpenFOAM, no CFD, no network."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.pipeline.airfoil import assets as A
from src.pipeline.airfoil import p3d
from tests.airfoil.synthetic_cgns import write_cgns_hex
from tests.airfoil.synthetic_cgrid import write_plot3d


@pytest.fixture
def fake_repo(tmp_path, monkeypatch):
    """A repo root with an asset directory, initially empty."""
    root = tmp_path / "repo"
    (root / "configs/families/airfoil").mkdir(parents=True)
    store = root / A.DEFAULT_ASSET_SUBDIR
    store.mkdir(parents=True)
    monkeypatch.setenv(A.ASSET_ROOT_ENV, str(store))
    return root


def _install(root: Path, key: str) -> Path:
    """Install a stand-in file for one registered asset."""
    asset = A.REGISTER[key]
    path = root / A.DEFAULT_ASSET_SUBDIR / asset.filename
    if key in A.FAMILY2_KEYS:
        # A Family-II-SHAPED synthetic grid, small enough for a test but built
        # from the same frozen analytic geometry, with two spanwise planes at
        # NASA's own span. Not a NASA file, and never presented as one.
        from tests.airfoil.synthetic_family2 import write as write_family2
        write_family2(path, n_per_side=16, n_radial=6)
    elif key in A.FAMILY2_CROSSCHECK_KEYS:
        # The PLOT3D cross-check counterpart: a minimal formatted 2-D grid.
        import gzip
        with gzip.open(path, "wt") as fh:
            fh.write("2 2\n0.0 1.0 0.0 1.0\n0.0 0.0 1.0 1.0\n")
    elif key in A.MESH_KEYS:
        n_wake, n_surface, nj = (12, 40, 17) if key == A.MESH_CANONICAL else (8, 24, 11)
        # NASA 2 x I x J layout, not a 2-D surrogate.
        write_plot3d(path, n_wake=n_wake, n_surface=n_surface, nj=nj, span=1.0)
    elif key == A.MESH_CGNS_HEX:
        # The independent authority for the SENSITIVITY grid: the same geometry,
        # written as unstructured hexes, so a clean comparison must succeed.
        source = root / A.DEFAULT_ASSET_SUBDIR / A.REGISTER[A.MESH_SENSITIVITY].filename
        if not source.exists():
            write_plot3d(source, n_wake=8, n_surface=24, nj=11, span=1.0)
        mesh = p3d.convert(p3d.read_plot3d(source), span=1.0)
        pytest.importorskip("h5py")       # CGNS files are HDF5 containers
        write_cgns_hex(path, mesh.points, mesh.hexes)
    elif key == A.REF_LADSON_FORCES:
        # Native TMR .dat shape: title lines plus whitespace numeric columns.
        path.write_text(
            'variables = "alpha" "cl" "cd"\n'
            'zone t="Ladson 80 grit"\n'
            "  -0.14   -0.0145   0.00819\n"
            "   1.04    0.1109   0.00823\n"
            'zone t="Ladson 120 grit"\n'
            "  -0.14   -0.0139   0.00806\n"
            "   1.04    0.1116   0.00812\n",
            encoding="utf-8",
        )
    elif key == A.REF_CFL3D_FORCES:
        path.write_text(
            "# CFL3D SST NACA0012\n"
            "   0.0    0.0       0.00819\n"
            "  10.0    1.0909    0.01231\n",
            encoding="utf-8",
        )
    elif key == A.REF_CFL3D_CP:
        rows = ['variables = "x/c" "cp"', 'zone t="upper surface"']
        for n in range(11):
            x = n / 10.0
            rows.append(f"  {x:.4f}   {1.0 - 4.0 * x * (1.0 - x):.6f}")
        rows.append('zone t="lower surface"')
        for n in range(11):
            x = n / 10.0
            rows.append(f"  {x:.4f}   {1.0 - 4.0 * x * (1.0 - x):.6f}")
        path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    elif key == A.REF_CFL3D_CF:
        # Deliberately UNLABELLED: exercises the recorded both-surfaces path.
        rows = ["# CFL3D SST cf, alpha = 0"]
        for n in range(11):
            rows.append(f"  {n / 10.0:.4f}   0.004000")
        path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    return path


@pytest.fixture
def installed_assets(fake_repo):
    """All registered assets present, with a written lockfile."""
    entries = {}
    for key in A.REGISTER:
        path = _install(fake_repo, key)
        entries[key] = {
            "filename": A.REGISTER[key].filename,
            "sha256": A.sha256_of(path),
            "bytes": path.stat().st_size,
            "source": A.REGISTER[key].source,
            "role": A.REGISTER[key].role,
            "expected": A.REGISTER[key].expected,
        }
    A.write_lock(entries, repo_root=fake_repo, toolchain="test")
    return fake_repo


@pytest.fixture
def install_one(fake_repo):
    def _f(key: str) -> Path:
        return _install(fake_repo, key)
    return _f


@pytest.fixture
def qualified_evidence():
    """Evidence that passes every hard check and every reference check.

    Numbers here are TEST INPUTS, not scientific results: they exist to prove the
    validator's arithmetic and its thresholds, and none of them is a claim about
    a NACA0012.
    """
    cp = [[n / 10.0, 1.0 - 4.0 * (n / 10.0) * (1.0 - n / 10.0)] for n in range(11)]
    return {
        "family": "airfoil",
        "mesh": {"audit_status": "MESH_AUDIT_PASSED", "cells": 229376},
        "solver": {
            "completed": True,
            "qualification_window": 500,
            "final_window_initial_residuals": {
                "U": 4.0e-7, "k": 5.0e-7, "omega": 6.0e-7, "p": 8.0e-6,
            },
            "normalised_flux_imbalance": 2.0e-6,
            "nan_detected": False,
            "inf_detected": False,
            "k_positive": True,
            "omega_positive": True,
            "nut_finite_nonnegative": True,
            "persistent_bounding": False,
        },
        "quantitative": {
            "CL": 0.0004,
            "CD": 0.00820,
            "CD_series_statistics": {"relative_variation": 0.0005, "range": 4e-6},
            "CL_series_statistics": {"range": 2.0e-5},
            "surface_distributions_stable": True,
            "cp": {"upper": cp, "lower": cp},
            "cp_rmse": {
                "upper": {"rmse": 0.01, "n_reference_points": 11, "n_matched": 11,
                          "unmatched_x_over_c": []},
                "lower": {"rmse": 0.012, "n_reference_points": 11, "n_matched": 11,
                          "unmatched_x_over_c": []},
            },
            "yplus": {
                "fraction_below_threshold": 0.995,
                "max_yplus": 1.4,
                "max_yplus_location": {"x_over_c": 0.001, "surface": "upper"},
                "exceedance_regions": [{"x_over_c": 0.001, "yplus": 1.4}],
                "by_surface": {},
            },
        },
        "references": {
            "ladson_drag": [
                {"dataset": "ladson_80grit", "CD_at_zero_incidence": 0.00819},
                {"dataset": "ladson_120grit", "CD_at_zero_incidence": 0.00806},
            ],
        },
        "grid_sensitivity": {
            "CD_relative_change": 0.008,
            "cp_rmse_between_grids": 0.006,
            "canonical_cells": 229376,
            "sensitivity_cells": 57344,
        },
        "provenance": {
            "assets_ok": True,
            "recipe_unchanged": True,
            "second_order_schemes": True,
        },
    }
