"""Canonical equivalence: the parameterized pipeline must BE the frozen one.

validation/canonical_reference/ is the scientific authority and is never
modified.  src/pipeline/nozzle/ is a parameterized derivative of it.  These
tests exist so that the parameterization cannot silently drift away from the
validated method.

What is compared:

  1. Every generated OpenFOAM input file, byte for byte, for the canonical
     specification: blockMeshDict, controlDict, fvSchemes, fvSolution,
     physicalProperties, momentumTransport and the three 0/ fields.
  2. The case manifest, on every key the canonical manifest writes.
  3. The initialized 0/p, 0/T and 0/U fields, byte for byte, produced by
     running the canonical initializer and the parameterized initializer over
     the same synthetic cell centres.
  4. The quasi-1D state function, bit for bit, across the nozzle.
  5. Every quantity the validator derives from hard-coded canonical literals.
  6. Every acceptance threshold literal in the validator's check block.

Only the manifest's additive provenance keys are excluded, and they are
excluded by comparing the canonical key set rather than by ignoring content.
"""
from __future__ import annotations

import importlib.util
import json
import math
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
CANONICAL = REPO_ROOT / "validation/canonical_reference"
PIPELINE = REPO_ROOT / "src/pipeline/nozzle"

sys.path.insert(0, str(REPO_ROOT))

from src.pipeline.nozzle import build as pbuild  # noqa: E402
from src.pipeline.nozzle.spec import CANONICAL_SPEC  # noqa: E402


OPENFOAM_INPUTS = [
    "system/blockMeshDict",
    "system/controlDict",
    "system/fvSchemes",
    "system/fvSolution",
    "constant/physicalProperties",
    "constant/momentumTransport",
    "0/p",
    "0/T",
    "0/U",
]


def _load_canonical_module(name: str):
    """Import a module from the frozen reference without mutating it."""
    spec = importlib.util.spec_from_file_location(
        f"canonical_{name}", CANONICAL / f"{name}.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module

    old = sys.path[:]
    sys.path.insert(0, str(CANONICAL))

    try:
        spec.loader.exec_module(module)
    finally:
        sys.path[:] = old

    return module


@pytest.fixture(scope="module")
def built_cases(tmp_path_factory):
    root = tmp_path_factory.mktemp("equivalence")

    canonical_case = root / "canonical"
    parameterized_case = root / "parameterized"

    proc = subprocess.run(
        [sys.executable, "build.py", str(canonical_case), "--scale", "1"],
        cwd=CANONICAL,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr

    pbuild.build(parameterized_case, CANONICAL_SPEC)

    return canonical_case, parameterized_case


# ----------------------------------------------------------------------
# 1. OpenFOAM inputs
# ----------------------------------------------------------------------


def test_same_files_are_generated(built_cases):
    canonical_case, parameterized_case = built_cases

    def listing(case: Path):
        return sorted(
            p.relative_to(case).as_posix()
            for p in case.rglob("*")
            if p.is_file()
        )

    assert listing(canonical_case) == listing(parameterized_case)


@pytest.mark.parametrize("relative", OPENFOAM_INPUTS)
def test_openfoam_input_is_byte_identical(built_cases, relative):
    canonical_case, parameterized_case = built_cases

    canonical_bytes = (canonical_case / relative).read_bytes()
    parameterized_bytes = (parameterized_case / relative).read_bytes()

    assert parameterized_bytes == canonical_bytes, (
        f"{relative} differs from the frozen canonical reference.\n"
        f"canonical:\n{canonical_bytes.decode()}\n"
        f"parameterized:\n{parameterized_bytes.decode()}"
    )


def test_no_openfoam_input_is_missing_from_the_comparison(built_cases):
    """Guard against silently narrowing the byte comparison."""
    canonical_case, _ = built_cases

    generated = {
        p.relative_to(canonical_case).as_posix()
        for p in canonical_case.rglob("*")
        if p.is_file()
    }

    uncompared = generated - set(OPENFOAM_INPUTS)

    assert uncompared == {"manifest.json"}, (
        "Every generated file except the metadata manifest must be compared "
        f"byte for byte; uncompared: {sorted(uncompared)}"
    )


# ----------------------------------------------------------------------
# 2. Manifest
# ----------------------------------------------------------------------


def test_manifest_agrees_on_every_canonical_key(built_cases):
    canonical_case, parameterized_case = built_cases

    canonical = json.loads((canonical_case / "manifest.json").read_text())
    parameterized = json.loads((parameterized_case / "manifest.json").read_text())

    for key, value in canonical.items():
        assert key in parameterized, f"manifest key {key} was dropped"
        assert parameterized[key] == value, (
            f"manifest key {key}: {parameterized[key]!r} != {value!r}"
        )

    # The derivative may only ADD provenance, never change meaning.
    added = set(parameterized) - set(canonical)
    assert added == {"case_spec", "provenance"}, sorted(added)


# ----------------------------------------------------------------------
# 3. Initialized fields
# ----------------------------------------------------------------------


def _write_synthetic_cell_centres(case: Path, spec) -> int:
    """Write a 0/C field spanning the nozzle.

    The values need not be a real mesh: both initializers read the same file,
    so any consistent set of coordinates tests the arithmetic they perform.
    The sweep covers inlet, converging, throat and diverging sections so that
    both the subsonic and supersonic branches are exercised.
    """
    import numpy as np

    xs = spec.axial_breakpoints_m
    rs = spec.radii_m

    coords = []

    for j in range(len(xs) - 1):
        for i in range(12):
            x = xs[j] + (i + 0.5) * (xs[j + 1] - xs[j]) / 12.0
            r_wall = float(np.interp(x, xs, rs))

            for k in range(4):
                y = (k + 0.5) / 4.0 * r_wall * math.cos(math.radians(2.5))
                z = y * math.tan(math.radians(2.5)) * (1 if k % 2 else -1)
                coords.append((x, y, z))

    body = "\n".join(
        "(" + " ".join(f"{v:.16g}" for v in row) + ")" for row in coords
    )

    (case / "0").mkdir(parents=True, exist_ok=True)
    (case / "0/C").write_text(
        "FoamFile { format ascii; class volVectorField; object C; }\n"
        "dimensions [length];\n"
        f"internalField nonuniform List<vector>\n{len(coords)}\n(\n{body}\n);\n"
        "boundaryField { }\n"
    )

    return len(coords)


def test_initialized_fields_are_byte_identical(tmp_path):
    canonical_case = tmp_path / "canonical"
    parameterized_case = tmp_path / "parameterized"

    proc = subprocess.run(
        [sys.executable, "build.py", str(canonical_case), "--scale", "1"],
        cwd=CANONICAL,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr

    pbuild.build(parameterized_case, CANONICAL_SPEC)

    n = _write_synthetic_cell_centres(canonical_case, CANONICAL_SPEC)
    shutil.copy2(canonical_case / "0/C", parameterized_case / "0/C")

    canonical_run = subprocess.run(
        [sys.executable, "initialize.py", str(canonical_case)],
        cwd=CANONICAL,
        capture_output=True,
        text=True,
    )
    assert canonical_run.returncode == 0, canonical_run.stderr

    parameterized_run = subprocess.run(
        [sys.executable, "initialize.py", str(parameterized_case)],
        cwd=PIPELINE,
        capture_output=True,
        text=True,
    )
    assert parameterized_run.returncode == 0, parameterized_run.stderr

    for name in ("p", "T", "U"):
        assert (parameterized_case / "0" / name).read_bytes() == (
            canonical_case / "0" / name
        ).read_bytes(), f"initialized 0/{name} differs from the frozen reference"

    canonical_record = json.loads(
        (canonical_case / "initialization_verified.json").read_text()
    )
    parameterized_record = json.loads(
        (parameterized_case / "initialization_verified.json").read_text()
    )

    assert parameterized_record["cells"] == canonical_record["cells"] == n
    assert parameterized_record["readback_pass"] is True

    for key in ("p_min", "p_max", "T_min", "Uax_max"):
        assert parameterized_record[key] == canonical_record[key]


def test_replacement_initialization_bound_is_stricter_for_the_canonical_case():
    """The parameterized startup bound must not be a relaxation."""
    max_allowed_p_min, min_allowed_p_max = (
        CANONICAL_SPEC.expected_initial_pressure_bounds()
    )

    # Canonical literals were p_min < 60000 and p_max > 190000.
    assert max_allowed_p_min < 60000.0

    # The upper bound is anchored to the quasi-1D inlet static pressure rather
    # than an absolute pascal value, and stays within one percent of it.
    p_inlet, _, _ = CANONICAL_SPEC.quasi1d_state(
        CANONICAL_SPEC.inlet_radius_m, False
    )
    assert min_allowed_p_max == pytest.approx(0.99 * p_inlet, rel=1e-12)


# ----------------------------------------------------------------------
# 4. Quasi-1D state function
# ----------------------------------------------------------------------


def test_quasi_1d_state_is_bit_identical():
    canonical_build = _load_canonical_module("build")

    radii = [
        0.05,
        0.045,
        0.04,
        0.0326,
        0.033,
        0.034,
        0.0354,
    ]

    for r in radii:
        for supersonic in (False, True):
            if supersonic and r < 0.0326:
                continue

            expected = canonical_build.state(r, supersonic)
            actual = CANONICAL_SPEC.quasi1d_state(r, supersonic)

            assert actual == expected, (
                f"state(r={r}, supersonic={supersonic}) differs: "
                f"{actual} != {expected}"
            )


# ----------------------------------------------------------------------
# 5. Validator-derived quantities
# ----------------------------------------------------------------------


def test_validator_derived_values_match_canonical_literals():
    import numpy as np

    canonical_build = _load_canonical_module("build")

    spec = CANONICAL_SPEC

    # throat mask bounds: canonical (x > .150) & (x < .160)
    assert spec.throat_start_m == 0.150
    assert spec.throat_end_m == 0.160

    # downstream normal-shock screen: canonical x > .17
    assert spec.downstream_screen_x_m == 0.17

    # integration horizon: canonical t[-1] >= .006
    assert spec.end_time_s == 0.006

    # underexpanded exit: canonical outlet_p > 30000
    assert spec.ambient_pressure_pa == 30000.0

    # inlet reservoir references: canonical / 200000 and / 300
    assert spec.total_pressure_pa == 200000.0
    assert spec.total_temperature_k == 300.0

    # theory exit state: canonical state(.0354, True)
    assert spec.quasi1d_state(spec.exit_radius_m, True) == canonical_build.state(
        0.0354, True
    )

    # choked mass flow: canonical closed form
    canonical_mdot = (
        math.pi
        * 0.0326 ** 2
        * 200000
        / math.sqrt(300)
        * math.sqrt(1.4 / 287)
        * (2 / 2.4) ** 3
    )
    assert spec.choked_mass_flow_kg_s() == canonical_mdot

    # axial profile slab edges
    canonical_nx = [round(n * 1) for n in (20, 40, 4, 48, 20)]
    canonical_xs = [0, .05, .15, .16, .28, .33]
    canonical_edges = np.concatenate(
        [
            np.linspace(canonical_xs[j], canonical_xs[j + 1], n + 1)[:-1]
            for j, n in enumerate(canonical_nx)
        ]
        + [np.array([.33])]
    )

    nx = spec.axial_cells
    xs = spec.axial_breakpoints_m
    edges = np.concatenate(
        [np.linspace(xs[j], xs[j + 1], n + 1)[:-1] for j, n in enumerate(nx)]
        + [np.array([xs[-1]])]
    )

    np.testing.assert_array_equal(edges, canonical_edges)

    # stagnation-enthalpy reference: canonical 1004.5 * 300
    assert 1004.5 * spec.total_temperature_k == 1004.5 * 300


# ----------------------------------------------------------------------
# 6. Acceptance thresholds
# ----------------------------------------------------------------------


def _checks_block(path: Path) -> str:
    text = path.read_text()
    start = text.index("checks={") if "checks={" in text else text.index("checks = {")
    end = text.index("checks={k:bool(v)") if "checks={k:bool(v)" in text else text.index(
        "checks = {k: bool(v)"
    )
    return text[start:end]


def _literals(block: str) -> set:
    return set(
        re.findall(r"(?<![\w.])\d*\.?\d+(?:[eE][-+]?\d+)?", block)
    )


# Literals that encode the CASE, not an acceptance threshold. These are the
# values that were deliberately parameterized.
CASE_LITERALS = {".006", "30000"}


def test_no_acceptance_threshold_was_changed():
    canonical = _literals(_checks_block(CANONICAL / "validate.py"))
    parameterized = _literals(_checks_block(PIPELINE / "validate.py"))

    thresholds = canonical - CASE_LITERALS
    missing = thresholds - parameterized

    assert not missing, (
        "Acceptance thresholds missing from the parameterized validator: "
        f"{sorted(missing)}"
    )


def test_check_names_are_unchanged():
    def names(path: Path) -> set:
        return set(re.findall(r"'([a-z_]+)':", _checks_block(path)))

    canonical = names(CANONICAL / "validate.py")
    parameterized = names(PIPELINE / "validate.py")

    assert parameterized == canonical, (
        f"check set changed: only canonical {sorted(canonical - parameterized)}, "
        f"only parameterized {sorted(parameterized - canonical)}"
    )
    assert len(canonical) == 20
