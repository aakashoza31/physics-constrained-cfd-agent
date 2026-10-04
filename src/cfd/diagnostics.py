"""Legacy prototype (CAD->Gmsh path, paper Appendix C "Prototype before the
registered contracts"); not the registered nozzle family; not used for any
reported result except that prototype record.

Prototype CFD diagnostics. Not imported by the registered family runners or by
src/pipeline.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import shlex
import subprocess
from pathlib import Path
from typing import Any


OPENFOAM_DISTRO = os.getenv(
    "OPENFOAM_WSL_DISTRO",
    "Ubuntu-24.04",
)

OPENFOAM_BASHRC = os.getenv(
    "OPENFOAM_BASHRC",
    "/opt/openfoam14/etc/bashrc",
)


DEFAULT_THRESHOLDS = {
    "mass_imbalance_pct_max": 1.0,
    "outlet_mass_flow_relative_range_pct_max": 0.25,
    "outlet_pressure_relative_range_pct_max": 0.50,
    "outlet_temperature_relative_range_pct_max": 0.50,
    "outlet_velocity_relative_range_pct_max": 0.50,
    "minimum_stationarity_samples": 4,
    "stationarity_window_samples": 5,
}


# ============================================================
# PROCESS HELPERS
# ============================================================


def _run_bash(
    command: str,
    timeout_s: int = 180,
) -> subprocess.CompletedProcess[str]:

    if os.name == "nt":
        args = [
            "wsl.exe",
            "-d",
            OPENFOAM_DISTRO,
            "--",
            "bash",
            "-lc",
            command,
        ]
    else:
        args = [
            "bash",
            "-lc",
            command,
        ]

    return subprocess.run(
        args,
        text=True,
        capture_output=True,
        timeout=timeout_s,
        check=False,
    )


def _foam_command(
    case_wsl: str,
    command: str,
    timeout_s: int = 180,
) -> str:

    quoted_case = shlex.quote(
        case_wsl
    )

    quoted_bashrc = shlex.quote(
        OPENFOAM_BASHRC
    )

    full_command = (
        f"source {quoted_bashrc} "
        f"&& cd {quoted_case} "
        f"&& {command}"
    )

    proc = _run_bash(
        full_command,
        timeout_s=timeout_s,
    )

    text = (
        (proc.stdout or "")
        + (
            "\n" + proc.stderr
            if proc.stderr
            else ""
        )
    )

    if proc.returncode != 0:
        raise RuntimeError(
            "OpenFOAM diagnostic command failed.\n"
            f"Command: {command}\n"
            f"Return code: {proc.returncode}\n"
            f"{text[-5000:]}"
        )

    return text


# ============================================================
# FILE HELPERS
# ============================================================


def load_json(
    path: Path,
) -> dict[str, Any]:

    data = json.loads(
        path.read_text(
            encoding="utf-8"
        )
    )

    if not isinstance(
        data,
        dict,
    ):
        raise ValueError(
            f"Invalid JSON structure: {path}"
        )

    return data


# ============================================================
# SAVED TIMES
# ============================================================


def list_saved_times(
    case_wsl: str,
) -> list[float]:

    text = _foam_command(
        case_wsl,
        "foamListTimes",
    )

    times: list[float] = []

    for line in text.splitlines():

        clean = line.strip()

        try:
            value = float(
                clean
            )
        except ValueError:
            continue

        if value >= 0.0:
            times.append(
                value
            )

    return sorted(
        set(times)
    )


def _format_time(
    value: float,
) -> str:

    return f"{value:.12g}"


# ============================================================
# HISTORY PARSING
# ============================================================


_TIME_PATTERN = re.compile(
    r"^Time\s*=\s*([0-9.eE+\-]+)s?\s*$"
)


def _parse_scalar_history(
    text: str,
    value_pattern: str,
) -> list[dict[str, float]]:

    value_regex = re.compile(
        value_pattern
    )

    records: list[
        dict[str, float]
    ] = []

    current_time: float | None = None

    for line in text.splitlines():

        stripped = line.strip()

        time_match = (
            _TIME_PATTERN.match(
                stripped
            )
        )

        if time_match:

            current_time = float(
                time_match.group(1)
            )

            continue

        value_match = (
            value_regex.search(
                stripped
            )
        )

        if (
            value_match
            and current_time
            is not None
        ):

            records.append(
                {
                    "time_s": (
                        current_time
                    ),
                    "value": float(
                        value_match.group(
                            1
                        )
                    ),
                }
            )

    return records


def _parse_vector_history(
    text: str,
    value_pattern: str,
) -> list[dict[str, Any]]:

    value_regex = re.compile(
        value_pattern
    )

    records: list[
        dict[str, Any]
    ] = []

    current_time: float | None = None

    for line in text.splitlines():

        stripped = line.strip()

        time_match = (
            _TIME_PATTERN.match(
                stripped
            )
        )

        if time_match:

            current_time = float(
                time_match.group(1)
            )

            continue

        value_match = (
            value_regex.search(
                stripped
            )
        )

        if (
            value_match
            and current_time
            is not None
        ):

            x = float(
                value_match.group(1)
            )

            y = float(
                value_match.group(2)
            )

            z = float(
                value_match.group(3)
            )

            magnitude = math.sqrt(
                x * x
                + y * y
                + z * z
            )

            records.append(
                {
                    "time_s": (
                        current_time
                    ),
                    "value": [
                        x,
                        y,
                        z,
                    ],
                    "magnitude": (
                        magnitude
                    ),
                }
            )

    return records


# ============================================================
# PATCH METRICS
# ============================================================


def collect_patch_flow_history(
    case_wsl: str,
    patch: str,
    start_time: float,
    end_time: float,
) -> list[dict[str, float]]:

    function_name = (
        f"{patch}FlowRate"
    )

    command = (
        "foamPostProcess "
        f"-time "
        f"'{start_time:.12g}:"
        f"{end_time:.12g}' "
        "-func "
        f"'patchFlowRate("
        f"name={function_name},"
        f"patch={patch})'"
    )

    text = _foam_command(
        case_wsl,
        command,
    )

    pattern = (
        rf"sum\("
        rf"{re.escape(patch)}"
        rf"\)\s+of\s+phi\s*=\s*"
        rf"([0-9.eE+\-]+)"
    )

    return _parse_scalar_history(
        text,
        pattern,
    )


def collect_patch_scalar_average_history(
    case_wsl: str,
    patch: str,
    field: str,
    start_time: float,
    end_time: float,
) -> list[dict[str, float]]:

    function_name = (
        f"{patch}{field}Average"
    )

    command = (
        "foamPostProcess "
        f"-time "
        f"'{start_time:.12g}:"
        f"{end_time:.12g}' "
        "-func "
        f"'patchAverage("
        f"{field},"
        f"name={function_name},"
        f"patch={patch})'"
    )

    text = _foam_command(
        case_wsl,
        command,
    )

    pattern = (
        rf"areaAverage\("
        rf"{re.escape(patch)}"
        rf"\)\s+of\s+"
        rf"{re.escape(field)}"
        rf"\s*=\s*"
        rf"([0-9.eE+\-]+)"
    )

    return _parse_scalar_history(
        text,
        pattern,
    )


def collect_patch_vector_average_history(
    case_wsl: str,
    patch: str,
    field: str,
    start_time: float,
    end_time: float,
) -> list[dict[str, Any]]:

    function_name = (
        f"{patch}{field}Average"
    )

    command = (
        "foamPostProcess "
        f"-time "
        f"'{start_time:.12g}:"
        f"{end_time:.12g}' "
        "-func "
        f"'patchAverage("
        f"{field},"
        f"name={function_name},"
        f"patch={patch})'"
    )

    text = _foam_command(
        case_wsl,
        command,
    )

    number = (
        r"([0-9.eE+\-]+)"
    )

    pattern = (
        rf"areaAverage\("
        rf"{re.escape(patch)}"
        rf"\)\s+of\s+"
        rf"{re.escape(field)}"
        rf"\s*=\s*"
        rf"\(\s*"
        rf"{number}\s+"
        rf"{number}\s+"
        rf"{number}\s*\)"
    )

    return _parse_vector_history(
        text,
        pattern,
    )


# ============================================================
# GLOBAL FIELD EXTREMA
# ============================================================


def collect_global_scalar_extrema(
    case_wsl: str,
    field: str,
) -> dict[str, Any]:

    number = (
        r"[0-9.eE+\-]+"
    )

    results: dict[
        str,
        Any,
    ] = {}

    for operation in (
        "min",
        "max",
    ):

        foam_function = (
            f"cellMin({field})"
            if operation == "min"
            else f"cellMax({field})"
        )

        text = _foam_command(
            case_wsl,
            (
                "foamPostProcess "
                "-latestTime "
                f"-func "
                f"'{foam_function}'"
            ),
        )

        pattern = re.compile(
            rf"{operation}"
            rf"\(all\)\s+of\s+"
            rf"{re.escape(field)}"
            rf"\s*=\s*"
            rf"({number})\s+"
            rf"at location\s*"
            rf"\(\s*"
            rf"({number})\s+"
            rf"({number})\s+"
            rf"({number})\s*\)"
            rf"\s+in cell\s+"
            rf"(\d+)"
        )

        match = pattern.search(
            text
        )

        if not match:
            raise RuntimeError(
                "Could not parse global "
                f"{operation} for "
                f"field '{field}'."
            )

        results[
            operation
        ] = {
            "value": float(
                match.group(1)
            ),
            "location_m": [
                float(
                    match.group(2)
                ),
                float(
                    match.group(3)
                ),
                float(
                    match.group(4)
                ),
            ],
            "cell": int(
                match.group(5)
            ),
        }

    return results


# ============================================================
# MESH
# ============================================================


def collect_mesh_metrics(
    case_wsl: str,
) -> dict[str, Any]:

    text = _foam_command(
        case_wsl,
        "checkMesh -latestTime",
    )

    def grab(
        pattern: str,
        cast=float,
    ) -> Any:

        match = re.search(
            pattern,
            text,
            flags=re.IGNORECASE,
        )

        if not match:
            return None

        return cast(
            match.group(1)
        )

    return {
        "mesh_ok": (
            "Mesh OK." in text
            and "FOAM FATAL"
            not in text
        ),

        "cells": grab(
            r"cells:\s+(\d+)",
            int,
        ),

        "max_aspect_ratio": (
            grab(
                r"Max aspect ratio\s*="
                r"\s*([0-9.eE+\-]+)"
            )
        ),

        "max_non_orthogonality": (
            grab(
                r"Mesh non-orthogonality "
                r"Max:\s*"
                r"([0-9.eE+\-]+)"
            )
        ),

        "average_non_orthogonality": (
            grab(
                r"average:\s*"
                r"([0-9.eE+\-]+)"
            )
        ),

        "max_skewness": grab(
            r"Max skewness\s*="
            r"\s*([0-9.eE+\-]+)"
        ),
    }


# ============================================================
# SOLVER HEALTH
# ============================================================


def collect_solver_health(
    case_wsl: str,
    solver_log: str | None,
) -> dict[str, Any]:

    if not solver_log:

        return {
            "checked": False,
            "failure_detected": False,
            "failure_markers": [],
            "completed_normally": None,
            "log": None,
        }

    quoted = shlex.quote(
        solver_log
    )

    text = _foam_command(
        case_wsl,
        f"cat {quoted}",
    )

    fatal_markers = [
        "FOAM FATAL ERROR",
        "FOAM FATAL IO ERROR",
        (
            "Floating point "
            "exception (core dumped)"
        ),
        "sigFpe::sigHandler",
        "Segmentation fault",
    ]

    detected = [
        marker
        for marker
        in fatal_markers
        if marker in text
    ]

    completed = (
        re.search(
            r"^\s*End\s*$",
            text,
            flags=re.MULTILINE,
        )
        is not None
    )

    return {
        "checked": True,
        "failure_detected": (
            bool(detected)
        ),
        "failure_markers": (
            detected
        ),
        "completed_normally": (
            completed
        ),
        "log": solver_log,
    }


# ============================================================
# STATISTICS
# ============================================================


def _relative_range_pct(
    values: list[float],
) -> float | None:

    if not values:
        return None

    mean_value = (
        sum(values)
        / len(values)
    )

    if abs(
        mean_value
    ) < 1.0e-30:
        return None

    return (
        100.0
        * (
            max(values)
            - min(values)
        )
        / abs(mean_value)
    )


def _relative_drift_pct(
    values: list[float],
) -> float | None:

    if len(values) < 2:
        return None

    first = values[0]
    last = values[-1]

    if abs(
        first
    ) < 1.0e-30:
        return None

    return (
        100.0
        * (
            last - first
        )
        / abs(first)
    )


def summarize_values(
    values: list[float],
) -> dict[str, Any]:

    if not values:

        return {
            "samples": 0,
            "latest": None,
            "minimum": None,
            "maximum": None,
            "mean": None,
            "relative_range_pct": None,
            "relative_drift_pct": None,
        }

    return {
        "samples": len(
            values
        ),
        "latest": values[-1],
        "minimum": min(
            values
        ),
        "maximum": max(
            values
        ),
        "mean": (
            sum(values)
            / len(values)
        ),
        "relative_range_pct": (
            _relative_range_pct(
                values
            )
        ),
        "relative_drift_pct": (
            _relative_drift_pct(
                values
            )
        ),
    }


def summarize_series(
    history: list[
        dict[str, Any]
    ],
    *,
    vector_magnitude: bool = False,
    window_samples: int = 5,
) -> dict[str, Any]:

    if vector_magnitude:

        values = [
            float(
                item[
                    "magnitude"
                ]
            )
            for item
            in history
        ]

    else:

        values = [
            float(
                item[
                    "value"
                ]
            )
            for item
            in history
        ]

    if not values:

        return {
            "samples": 0,
            "window_samples": 0,
            "latest": None,
            "window_min": None,
            "window_max": None,
            "window_mean": None,
            "relative_range_pct": None,
            "relative_drift_pct": None,
        }

    window = values[
        -window_samples:
    ]

    return {
        "samples": len(
            values
        ),
        "window_samples": (
            len(window)
        ),
        "latest": (
            values[-1]
        ),
        "window_min": (
            min(window)
        ),
        "window_max": (
            max(window)
        ),
        "window_mean": (
            sum(window)
            / len(window)
        ),
        "relative_range_pct": (
            _relative_range_pct(
                window
            )
        ),
        "relative_drift_pct": (
            _relative_drift_pct(
                window
            )
        ),
    }


# ============================================================
# PHYSICS HELPERS
# ============================================================


def calculate_mach(
    velocity_mps: float,
    temperature_k: float,
    *,
    gamma: float = 1.4,
    gas_constant: float = 287.0,
) -> float:

    if temperature_k <= 0.0:
        raise ValueError(
            "Temperature must "
            "be positive."
        )

    sound_speed = math.sqrt(
        gamma
        * gas_constant
        * temperature_k
    )

    return (
        velocity_mps
        / sound_speed
    )


def mass_imbalance_pct(
    inlet_mass_flow: float,
    outlet_mass_flow: float,
) -> float:

    inlet = abs(
        inlet_mass_flow
    )

    outlet = abs(
        outlet_mass_flow
    )

    if inlet <= 1.0e-30:
        raise ValueError(
            "Inlet mass flow is zero."
        )

    return (
        100.0
        * abs(
            inlet - outlet
        )
        / inlet
    )


# ============================================================
# VTK CUT-PLANE PARSER
# ============================================================


def _parse_legacy_vtk_surface(
    text: str,
) -> tuple[
    list[tuple[float, float, float]],
    list[list[int]],
    dict[str, list[Any]],
]:

    tokens = text.split()

    i = 0

    while (
        i < len(tokens)
        and tokens[i] != "POINTS"
    ):
        i += 1

    if i >= len(tokens):
        raise RuntimeError(
            "POINTS section not found "
            "in cut-plane VTK."
        )

    n_points = int(
        tokens[i + 1]
    )

    i += 3

    points: list[
        tuple[
            float,
            float,
            float,
        ]
    ] = []

    for _ in range(
        n_points
    ):

        points.append(
            (
                float(tokens[i]),
                float(
                    tokens[i + 1]
                ),
                float(
                    tokens[i + 2]
                ),
            )
        )

        i += 3

    while (
        i < len(tokens)
        and tokens[i]
        != "POLYGONS"
    ):
        i += 1

    if i >= len(tokens):
        raise RuntimeError(
            "POLYGONS section not found "
            "in cut-plane VTK."
        )

    n_polygons = int(
        tokens[i + 1]
    )

    i += 3

    polygons: list[
        list[int]
    ] = []

    for _ in range(
        n_polygons
    ):

        n_vertices = int(
            tokens[i]
        )

        i += 1

        polygon = [
            int(
                tokens[
                    i + j
                ]
            )
            for j
            in range(
                n_vertices
            )
        ]

        i += n_vertices

        polygons.append(
            polygon
        )

    while (
        i < len(tokens)
        and tokens[i] != "FIELD"
    ):
        i += 1

    if i >= len(tokens):
        raise RuntimeError(
            "FIELD section not found "
            "in cut-plane VTK."
        )

    n_fields = int(
        tokens[i + 2]
    )

    i += 3

    fields: dict[
        str,
        list[Any],
    ] = {}

    for _ in range(
        n_fields
    ):

        name = tokens[i]

        components = int(
            tokens[i + 1]
        )

        count = int(
            tokens[i + 2]
        )

        i += 4

        values: list[Any] = []

        for _ in range(
            count
        ):

            if components == 1:

                values.append(
                    float(
                        tokens[i]
                    )
                )

                i += 1

            else:

                vector = tuple(
                    float(
                        tokens[
                            i + j
                        ]
                    )
                    for j
                    in range(
                        components
                    )
                )

                values.append(
                    vector
                )

                i += components

        fields[
            name
        ] = values

    return (
        points,
        polygons,
        fields,
    )


def _triangle_area(
    a: tuple[
        float,
        float,
        float,
    ],
    b: tuple[
        float,
        float,
        float,
    ],
    c: tuple[
        float,
        float,
        float,
    ],
) -> float:

    ab = (
        b[0] - a[0],
        b[1] - a[1],
        b[2] - a[2],
    )

    ac = (
        c[0] - a[0],
        c[1] - a[1],
        c[2] - a[2],
    )

    cross = (
        (
            ab[1] * ac[2]
            - ab[2] * ac[1]
        ),
        (
            ab[2] * ac[0]
            - ab[0] * ac[2]
        ),
        (
            ab[0] * ac[1]
            - ab[1] * ac[0]
        ),
    )

    return (
        0.5
        * math.sqrt(
            sum(
                value * value
                for value
                in cross
            )
        )
    )


def evaluate_cut_plane_vtk(
    vtk_text: str,
    *,
    gamma: float = 1.4,
    gas_constant: float = 287.0,
) -> dict[str, Any]:

    (
        points,
        polygons,
        fields,
    ) = _parse_legacy_vtk_surface(
        vtk_text
    )

    for field in (
        "p",
        "T",
        "U",
    ):

        if field not in fields:
            raise RuntimeError(
                f"Required field '{field}' "
                "not found in throat VTK."
            )

    total_area = 0.0

    p_integral = 0.0
    T_integral = 0.0

    ux_integral = 0.0
    uy_integral = 0.0
    uz_integral = 0.0

    speed_integral = 0.0
    mach_integral = 0.0

    for polygon in polygons:

        if len(
            polygon
        ) < 3:
            continue

        first = polygon[0]

        for j in range(
            1,
            len(polygon) - 1,
        ):

            ids = (
                first,
                polygon[j],
                polygon[j + 1],
            )

            area = _triangle_area(
                points[ids[0]],
                points[ids[1]],
                points[ids[2]],
            )

            if area <= 0.0:
                continue

            p_triangle = (
                sum(
                    float(
                        fields["p"][k]
                    )
                    for k
                    in ids
                )
                / 3.0
            )

            T_triangle = (
                sum(
                    float(
                        fields["T"][k]
                    )
                    for k
                    in ids
                )
                / 3.0
            )

            U_triangle = tuple(
                sum(
                    float(
                        fields["U"][
                            k
                        ][component]
                    )
                    for k
                    in ids
                )
                / 3.0
                for component
                in range(3)
            )

            speed_triangle = (
                math.sqrt(
                    sum(
                        value * value
                        for value
                        in U_triangle
                    )
                )
            )

            mach_vertices = []

            for k in ids:

                U_vertex = (
                    fields["U"][k]
                )

                speed_vertex = (
                    math.sqrt(
                        sum(
                            float(value)
                            * float(value)
                            for value
                            in U_vertex
                        )
                    )
                )

                T_vertex = float(
                    fields["T"][k]
                )

                if T_vertex <= 0.0:
                    raise RuntimeError(
                        "Non-positive "
                        "temperature found "
                        "on throat plane."
                    )

                mach_vertices.append(
                    speed_vertex
                    / math.sqrt(
                        gamma
                        * gas_constant
                        * T_vertex
                    )
                )

            mach_triangle = (
                sum(
                    mach_vertices
                )
                / 3.0
            )

            total_area += (
                area
            )

            p_integral += (
                area
                * p_triangle
            )

            T_integral += (
                area
                * T_triangle
            )

            ux_integral += (
                area
                * U_triangle[0]
            )

            uy_integral += (
                area
                * U_triangle[1]
            )

            uz_integral += (
                area
                * U_triangle[2]
            )

            speed_integral += (
                area
                * speed_triangle
            )

            mach_integral += (
                area
                * mach_triangle
            )

    if total_area <= 0.0:
        raise RuntimeError(
            "Cut-plane area is zero."
        )

    U_average = [
        ux_integral
        / total_area,
        uy_integral
        / total_area,
        uz_integral
        / total_area,
    ]

    return {
        "area_m2": (
            total_area
        ),

        "pressure_pa": (
            p_integral
            / total_area
        ),

        "temperature_k": (
            T_integral
            / total_area
        ),

        "velocity_vector_mps": (
            U_average
        ),

        "speed_mps": (
            speed_integral
            / total_area
        ),

        "mach": (
            mach_integral
            / total_area
        ),

        "surface_points": (
            len(points)
        ),

        "surface_polygons": (
            len(polygons)
        ),
    }


# ============================================================
# THROAT CUT-PLANE GENERATION
# ============================================================


def _cut_plane_function_name(
    x_m: float,
) -> str:

    return (
        "cutPlaneSurface("
        f"point=({x_m:.5f}00),"
        "normal=(100),"
        "fields=(pTU))"
    )


def _cut_plane_output_path(
    x_m: float,
    time_s: float,
) -> str:

    # OpenFOAM normalizes x to five decimal places
    # in the generated function-object directory.

    x_string = (
        f"{x_m:.5f}"
    )

    return (
        "postProcessing/"
        "cutPlaneSurface("
        f"point=({x_string}),"
        "normal=(100),"
        "fields=(pTU))/"
        f"{_format_time(time_s)}/"
        "cutPlane.vtk"
    )


def generate_cut_plane(
    case_wsl: str,
    x_m: float,
    start_time: float,
    end_time: float | None = None,
) -> None:

    if end_time is None:

        time_selector = (
            f"-time "
            f"'{start_time:.12g}'"
        )

    else:

        time_selector = (
            f"-time "
            f"'{start_time:.12g}:"
            f"{end_time:.12g}'"
        )

    command = (
        "foamPostProcess "
        f"{time_selector} "
        "-func "
        "'cutPlaneSurface("
        f"point=({x_m:.12g} 0 0),"
        "normal=(1 0 0),"
        "fields=(p T U))'"
    )

    _foam_command(
        case_wsl,
        command,
        timeout_s=300,
    )


def _discover_cut_plane_vtk(
    case_wsl: str,
    x_m: float,
    time_s: float,
) -> tuple[str, str, float, bool]:

    """
    Discover the best cutPlane.vtk written by OpenFOAM.

    Selection policy:
      1. match the requested x-location using the actual VTK points
      2. prefer an exact output time when it exists
      3. otherwise use the nearest PREVIOUS output time

    A later/future plane is never substituted for a failed-run diagnostic.
    This guarantees that postmortem evidence comes only from solver states
    that actually existed at or before the requested failure time.
    """

    listing = _foam_command(
        case_wsl,
        (
            "find postProcessing "
            "-type f "
            "-name cutPlane.vtk "
            "-print "
            "2>/dev/null "
            "|| true"
        ),
    )

    paths = [
        line.strip()
        for line
        in listing.splitlines()
        if line.strip()
    ]

    if not paths:
        raise RuntimeError(
            "No cutPlane.vtk files were found "
            "under postProcessing."
        )

    target_time = float(
        time_s
    )

    time_tolerance = max(
        1.0e-12,
        abs(target_time)
        * 1.0e-8,
    )

    x_tolerance = max(
        1.0e-8,
        abs(float(x_m))
        * 1.0e-6,
    )

    # Keep only physical cut planes matching the requested x-location.
    #
    # Stored tuple:
    # (
    #     candidate_time,
    #     x_error,
    #     relative_path,
    #     vtk_text,
    # )
    spatial_matches: list[
        tuple[
            float,
            float,
            str,
            str,
        ]
    ] = []

    for relative_path in paths:

        normalized = (
            relative_path
            .replace(
                "\\",
                "/",
            )
        )

        parts = [
            item
            for item
            in normalized.split("/")
            if item
        ]

        if len(parts) < 2:
            continue

        try:
            candidate_time = float(
                parts[-2]
            )

        except ValueError:
            continue

        # --------------------------------------------------------
        # Critical postmortem rule:
        #
        # Never use solver evidence from a time AFTER the
        # requested crash/final state.
        # --------------------------------------------------------

        if (
            candidate_time
            > target_time
            + time_tolerance
        ):
            continue

        try:

            vtk_text = _foam_command(
                case_wsl,
                (
                    "cat "
                    + shlex.quote(
                        relative_path
                    )
                ),
            )

            (
                points,
                _,
                _,
            ) = _parse_legacy_vtk_surface(
                vtk_text
            )

        except Exception:
            continue

        if not points:
            continue

        mean_x = (
            sum(
                point[0]
                for point
                in points
            )
            / len(points)
        )

        x_error = abs(
            mean_x
            - float(x_m)
        )

        if x_error > x_tolerance:
            continue

        spatial_matches.append(
            (
                candidate_time,
                x_error,
                relative_path,
                vtk_text,
            )
        )

    if not spatial_matches:

        raise RuntimeError(
            "Cut-plane VTK files exist, but none "
            "match the requested x-location at or "
            "before the requested time. "
            f"x={x_m:.12g}, "
            f"time={time_s:.12g}"
        )

    # ------------------------------------------------------------
    # Prefer exact requested time.
    # ------------------------------------------------------------

    exact_matches = [
        item
        for item
        in spatial_matches
        if abs(
            item[0]
            - target_time
        ) <= time_tolerance
    ]

    if exact_matches:

        selected = min(
            exact_matches,
            key=lambda item: item[1],
        )

        used_time_fallback = False

    else:

        # --------------------------------------------------------
        # Exact crash-time surface is absent.
        #
        # Select the latest valid PREVIOUS OpenFOAM output.
        # --------------------------------------------------------

        previous_time = max(
            item[0]
            for item
            in spatial_matches
        )

        previous_matches = [
            item
            for item
            in spatial_matches
            if abs(
                item[0]
                - previous_time
            ) <= time_tolerance
        ]

        selected = min(
            previous_matches,
            key=lambda item: item[1],
        )

        used_time_fallback = True

    (
        actual_time,
        _,
        relative_path,
        vtk_text,
    ) = selected

    return (
        relative_path,
        vtk_text,
        float(actual_time),
        used_time_fallback,
    )


def read_cut_plane(
    case_wsl: str,
    x_m: float,
    time_s: float,
) -> dict[str, Any]:

    requested_time = float(
        time_s
    )

    # ------------------------------------------------------------
    # Fast path:
    # exact historical OpenFOAM output naming.
    # ------------------------------------------------------------

    relative_path = (
        _cut_plane_output_path(
            x_m,
            requested_time,
        )
    )

    actual_time = requested_time

    used_time_fallback = False

    try:

        text = _foam_command(
            case_wsl,
            (
                "cat "
                + shlex.quote(
                    relative_path
                )
            ),
        )

    except RuntimeError:

        # --------------------------------------------------------
        # Robust path:
        #
        # 1. tolerate OpenFOAM function-object directory
        #    formatting differences
        #
        # 2. verify actual cut-plane x-coordinate
        #
        # 3. if exact crash-time output is unavailable,
        #    use the nearest PREVIOUS valid cut plane
        #
        # This is essential for solver-failure postmortems.
        # --------------------------------------------------------

        (
            relative_path,
            text,
            actual_time,
            used_time_fallback,
        ) = _discover_cut_plane_vtk(
            case_wsl,
            x_m,
            requested_time,
        )

    state = (
        evaluate_cut_plane_vtk(
            text
        )
    )

    # ------------------------------------------------------------
    # Audit metadata
    #
    # Keep requested solver time separate from the actual VTK
    # state used by diagnostics.
    # ------------------------------------------------------------

    state[
        "requested_time_s"
    ] = requested_time

    state[
        "actual_diagnostic_time_s"
    ] = float(
        actual_time
    )

    state[
        "used_time_fallback"
    ] = bool(
        used_time_fallback
    )

    state[
        "cut_plane_vtk_path"
    ] = relative_path

    return state


# ============================================================
# THROAT GEOMETRY
# ============================================================


def extract_throat_geometry(
    geometry_manifest: dict[
        str,
        Any,
    ],
) -> dict[str, float]:

    verified = (
        geometry_manifest.get(
            "verified_geometry",
            {}
        )
    )

    throat = verified.get(
        "throat",
        {}
    )

    start_x = throat.get(
        "x_start_m"
    )

    center_x = throat.get(
        "x_center_m"
    )

    end_x = throat.get(
        "x_end_m"
    )

    radius = throat.get(
        "radius_m"
    )

    if any(
        value is None
        for value
        in (
            start_x,
            center_x,
            end_x,
            radius,
        )
    ):
        raise ValueError(
            "Geometry manifest does "
            "not contain complete "
            "throat geometry."
        )

    return {
        "x_start_m": float(
            start_x
        ),
        "x_center_m": float(
            center_x
        ),
        "x_end_m": float(
            end_x
        ),
        "radius_m": float(
            radius
        ),
    }


# ============================================================
# SONIC TRANSITION
# ============================================================


def detect_sonic_transition(
    stations: list[
        dict[str, Any]
    ],
) -> dict[str, Any]:

    ordered = sorted(
        stations,
        key=lambda item: (
            item["x_m"]
        ),
    )

    for left, right in zip(
        ordered[:-1],
        ordered[1:],
    ):

        m1 = float(
            left["mach"]
        )

        m2 = float(
            right["mach"]
        )

        if m1 == 1.0:

            return {
                "detected": True,
                "x_m": (
                    left["x_m"]
                ),
                "method": (
                    "exact_sample"
                ),
                "bracket_x_m": [
                    left["x_m"],
                    left["x_m"],
                ],
                "interpolated_state": {
                    "mach": 1.0,
                    "pressure_pa": (
                        left[
                            "pressure_pa"
                        ]
                    ),
                    "temperature_k": (
                        left[
                            "temperature_k"
                        ]
                    ),
                    "speed_mps": (
                        left[
                            "speed_mps"
                        ]
                    ),
                    "velocity_vector_mps": (
                        left[
                            "velocity_vector_mps"
                        ]
                    ),
                },
            }

        crosses = (
            (m1 < 1.0 < m2)
            or
            (m2 < 1.0 < m1)
            or
            m2 == 1.0
        )

        if not crosses:
            continue

        if m2 == 1.0:

            return {
                "detected": True,
                "x_m": (
                    right["x_m"]
                ),
                "method": (
                    "exact_sample"
                ),
                "bracket_x_m": [
                    right["x_m"],
                    right["x_m"],
                ],
                "interpolated_state": {
                    "mach": 1.0,
                    "pressure_pa": (
                        right[
                            "pressure_pa"
                        ]
                    ),
                    "temperature_k": (
                        right[
                            "temperature_k"
                        ]
                    ),
                    "speed_mps": (
                        right[
                            "speed_mps"
                        ]
                    ),
                    "velocity_vector_mps": (
                        right[
                            "velocity_vector_mps"
                        ]
                    ),
                },
            }

        denominator = (
            m2 - m1
        )

        if abs(
            denominator
        ) < 1.0e-12:
            continue

        alpha = (
            (1.0 - m1)
            / denominator
        )

        x1 = float(
            left["x_m"]
        )

        x2 = float(
            right["x_m"]
        )

        sonic_x = (
            x1
            + alpha
            * (
                x2 - x1
            )
        )

        def interp(
            key: str,
        ) -> float:

            a = float(
                left[key]
            )

            b = float(
                right[key]
            )

            return (
                a
                + alpha
                * (
                    b - a
                )
            )

        left_u = left[
            "velocity_vector_mps"
        ]

        right_u = right[
            "velocity_vector_mps"
        ]

        interpolated_u = [
            float(left_u[j])
            + alpha
            * (
                float(right_u[j])
                - float(left_u[j])
            )
            for j
            in range(3)
        ]

        return {
            "detected": True,

            "x_m": sonic_x,

            "method": (
                "linear_interpolation_between_"
                "area_averaged_cut_planes"
            ),

            "bracket_x_m": [
                x1,
                x2,
            ],

            "bracket_mach": [
                m1,
                m2,
            ],

            "interpolation_fraction": (
                alpha
            ),

            "interpolated_state": {
                "mach": 1.0,

                "pressure_pa": (
                    interp(
                        "pressure_pa"
                    )
                ),

                "temperature_k": (
                    interp(
                        "temperature_k"
                    )
                ),

                "speed_mps": (
                    interp(
                        "speed_mps"
                    )
                ),

                "velocity_vector_mps": (
                    interpolated_u
                ),
            },
        }

    return {
        "detected": False,

        "x_m": None,

        "method": None,

        "bracket_x_m": None,

        "interpolated_state": None,

        "note": (
            "No Mach-1 crossing was "
            "detected between the "
            "sampled throat planes."
        ),
    }


# ============================================================
# THROAT DIAGNOSTICS
# ============================================================


def collect_throat_diagnostics(
    case_wsl: str,
    geometry_manifest: dict[
        str,
        Any,
    ],
    saved_times: list[float],
    final_time: float,
    *,
    stationarity_window_samples: int,
) -> dict[str, Any]:

    geometry = (
        extract_throat_geometry(
            geometry_manifest
        )
    )

    start_x = geometry[
        "x_start_m"
    ]

    center_x = geometry[
        "x_center_m"
    ]

    end_x = geometry[
        "x_end_m"
    ]

    radius = geometry[
        "radius_m"
    ]

    theoretical_area = (
        math.pi
        * radius
        * radius
    )

    # --------------------------------------------------------
    # Latest entry / center / exit planes
    # --------------------------------------------------------

    for x_m in (
        start_x,
        center_x,
        end_x,
    ):

        generate_cut_plane(
            case_wsl,
            x_m,
            final_time,
        )

    latest_stations = []

    labels = [
        (
            "start",
            start_x,
        ),
        (
            "center",
            center_x,
        ),
        (
            "end",
            end_x,
        ),
    ]

    latest_by_label = {}

    for label, x_m in labels:

        state = read_cut_plane(
            case_wsl,
            x_m,
            final_time,
        )

        state[
            "x_m"
        ] = x_m

        state[
            "area_error_pct_vs_exact_geometry"
        ] = (
            100.0
            * abs(
                state["area_m2"]
                - theoretical_area
            )
            / theoretical_area
        )

        latest_stations.append(
            state
        )

        latest_by_label[
            label
        ] = state

    sonic_transition = (
        detect_sonic_transition(
            latest_stations
        )
    )

    # --------------------------------------------------------
    # Center-plane recent-time history
    # --------------------------------------------------------

    available_recent = [
        time
        for time
        in saved_times
        if time <= final_time
    ]

    history_times = (
        available_recent[
            -stationarity_window_samples:
        ]
    )

    if not history_times:
        raise RuntimeError(
            "No saved times available "
            "for throat stationarity."
        )

    generate_cut_plane(
        case_wsl,
        center_x,
        history_times[0],
        history_times[-1],
    )

    history = []

    for time_s in history_times:

        state = read_cut_plane(
            case_wsl,
            center_x,
            time_s,
        )

        history.append(
            {
                "time_s": (
                    time_s
                ),

                "pressure_pa": (
                    state[
                        "pressure_pa"
                    ]
                ),

                "temperature_k": (
                    state[
                        "temperature_k"
                    ]
                ),

                "speed_mps": (
                    state[
                        "speed_mps"
                    ]
                ),

                "mach": (
                    state[
                        "mach"
                    ]
                ),
            }
        )

    pressure_values = [
        item[
            "pressure_pa"
        ]
        for item
        in history
    ]

    temperature_values = [
        item[
            "temperature_k"
        ]
        for item
        in history
    ]

    speed_values = [
        item[
            "speed_mps"
        ]
        for item
        in history
    ]

    mach_values = [
        item[
            "mach"
        ]
        for item
        in history
    ]

    return {
        "geometry": {
            **geometry,

            "exact_area_m2": (
                theoretical_area
            ),
        },

        "latest_time_s": (
            final_time
        ),

        "latest_planes": {
            "start": (
                latest_by_label[
                    "start"
                ]
            ),

            "center": (
                latest_by_label[
                    "center"
                ]
            ),

            "end": (
                latest_by_label[
                    "end"
                ]
            ),
        },

        "sonic_transition": (
            sonic_transition
        ),

        "center_stationarity": {
            "times_s": (
                history_times
            ),

            "history": history,

            "pressure": (
                summarize_values(
                    pressure_values
                )
            ),

            "temperature": (
                summarize_values(
                    temperature_values
                )
            ),

            "speed": (
                summarize_values(
                    speed_values
                )
            ),

            "mach": (
                summarize_values(
                    mach_values
                )
            ),
        },

        "interpretation_guardrail": (
            "The sonic transition is detected "
            "from area-averaged CFD cut planes. "
            "The interpolated sonic state is an "
            "estimate between sampled stations "
            "and must not be represented as an "
            "exact CFD root solve."
        ),
    }


# ============================================================
# CLASSIFICATION
# ============================================================


def classify_diagnostics(
    diagnostics: dict[str, Any],
    thresholds: dict[str, Any],
) -> str:

    mesh = diagnostics[
        "mesh"
    ]

    solver = diagnostics[
        "solver"
    ]

    flow = diagnostics[
        "flow"
    ]

    stationarity = diagnostics[
        "stationarity"
    ]

    global_fields = (
        diagnostics.get(
            "global_field_validity",
            {},
        )
    )

    if not mesh.get(
        "mesh_ok",
        False,
    ):
        return "MESH_INVALID"

    if solver.get(
        "failure_detected",
        False,
    ):
        return "NUMERICAL_FAILURE"

    latest_p = flow.get(
        "outlet_pressure_pa"
    )

    latest_T = flow.get(
        "outlet_temperature_k"
    )

    latest_U = flow.get(
        "outlet_velocity_mps"
    )

    required_values = [
        latest_p,
        latest_T,
        latest_U,
    ]

    if any(
        value is None
        or not math.isfinite(
            float(value)
        )
        for value
        in required_values
    ):
        return "NUMERICAL_FAILURE"

    if (
        latest_p <= 0.0
        or latest_T <= 0.0
    ):
        return "NUMERICAL_FAILURE"

    for key in (
        "positive_pressure",
        "positive_temperature",
        "positive_density",
    ):

        if (
            key in global_fields
            and global_fields[key]
            is False
        ):
            return "NUMERICAL_FAILURE"

    if stationarity[
        "passes_all_monitored_metrics"
    ]:
        return (
            "STABLE_NEAR_STATIONARY"
        )

    return "STABLE_UNCONVERGED"


# ============================================================
# COMPLETE DIAGNOSTICS
# ============================================================


def collect_cfd_diagnostics(
    case_wsl: str,
    *,
    start_time: float | None = None,
    end_time: float | None = None,
    solver_log: str | None = None,
    thresholds: dict[str, Any] | None = None,
    geometry_manifest: dict[
        str,
        Any,
    ] | None = None,
) -> dict[str, Any]:

    limits = dict(
        DEFAULT_THRESHOLDS
    )

    if thresholds:
        limits.update(
            thresholds
        )

    times = list_saved_times(
        case_wsl
    )

    if not times:
        raise RuntimeError(
            "No OpenFOAM saved "
            "times found."
        )

    final_time = (
        max(times)
        if end_time is None
        else end_time
    )

    if start_time is None:

        recent_times = [
            value
            for value
            in times
            if value <= final_time
        ]

        count = max(
            int(
                limits[
                    "stationarity_window_samples"
                ]
            ),
            5,
        )

        selected = (
            recent_times[
                -count:
            ]
        )

        if not selected:
            raise RuntimeError(
                "No saved times inside "
                "monitoring window."
            )

        first_time = (
            selected[0]
        )

    else:

        first_time = (
            start_time
        )

    # --------------------------------------------------------
    # Boundary histories
    # --------------------------------------------------------

    inlet_flow_history = (
        collect_patch_flow_history(
            case_wsl,
            "inlet",
            first_time,
            final_time,
        )
    )

    outlet_flow_history = (
        collect_patch_flow_history(
            case_wsl,
            "outlet",
            first_time,
            final_time,
        )
    )

    outlet_p_history = (
        collect_patch_scalar_average_history(
            case_wsl,
            "outlet",
            "p",
            first_time,
            final_time,
        )
    )

    outlet_T_history = (
        collect_patch_scalar_average_history(
            case_wsl,
            "outlet",
            "T",
            first_time,
            final_time,
        )
    )

    outlet_U_history = (
        collect_patch_vector_average_history(
            case_wsl,
            "outlet",
            "U",
            first_time,
            final_time,
        )
    )

    if not all(
        [
            inlet_flow_history,
            outlet_flow_history,
            outlet_p_history,
            outlet_T_history,
            outlet_U_history,
        ]
    ):
        raise RuntimeError(
            "One or more required CFD "
            "histories could not "
            "be extracted."
        )

    latest_inlet_flow = float(
        inlet_flow_history[
            -1
        ][
            "value"
        ]
    )

    latest_outlet_flow = float(
        outlet_flow_history[
            -1
        ][
            "value"
        ]
    )

    latest_p = float(
        outlet_p_history[
            -1
        ][
            "value"
        ]
    )

    latest_T = float(
        outlet_T_history[
            -1
        ][
            "value"
        ]
    )

    latest_U_vector = (
        outlet_U_history[
            -1
        ][
            "value"
        ]
    )

    latest_U = float(
        outlet_U_history[
            -1
        ][
            "magnitude"
        ]
    )

    latest_Mach = (
        calculate_mach(
            latest_U,
            latest_T,
        )
    )

    imbalance = (
        mass_imbalance_pct(
            latest_inlet_flow,
            latest_outlet_flow,
        )
    )

    # --------------------------------------------------------
    # Global fields
    # --------------------------------------------------------

    pressure_extrema = (
        collect_global_scalar_extrema(
            case_wsl,
            "p",
        )
    )

    temperature_extrema = (
        collect_global_scalar_extrema(
            case_wsl,
            "T",
        )
    )

    density_extrema = (
        collect_global_scalar_extrema(
            case_wsl,
            "rho",
        )
    )

    global_field_validity = {
        "pressure": (
            pressure_extrema
        ),

        "temperature": (
            temperature_extrema
        ),

        "density": (
            density_extrema
        ),

        "positive_pressure": (
            pressure_extrema[
                "min"
            ][
                "value"
            ]
            > 0.0
        ),

        "positive_temperature": (
            temperature_extrema[
                "min"
            ][
                "value"
            ]
            > 0.0
        ),

        "positive_density": (
            density_extrema[
                "min"
            ][
                "value"
            ]
            > 0.0
        ),
    }

    # --------------------------------------------------------
    # Outlet stationarity
    # --------------------------------------------------------

    window_samples = int(
        limits[
            "stationarity_window_samples"
        ]
    )

    flow_stats = (
        summarize_series(
            outlet_flow_history,
            window_samples=(
                window_samples
            ),
        )
    )

    p_stats = (
        summarize_series(
            outlet_p_history,
            window_samples=(
                window_samples
            ),
        )
    )

    T_stats = (
        summarize_series(
            outlet_T_history,
            window_samples=(
                window_samples
            ),
        )
    )

    U_stats = (
        summarize_series(
            outlet_U_history,
            vector_magnitude=True,
            window_samples=(
                window_samples
            ),
        )
    )

    minimum_samples = int(
        limits[
            "minimum_stationarity_samples"
        ]
    )

    enough_samples = all(
        item[
            "window_samples"
        ]
        >= minimum_samples
        for item
        in [
            flow_stats,
            p_stats,
            T_stats,
            U_stats,
        ]
    )

    stationarity_checks = {
        "mass_imbalance": (
            imbalance
            <= limits[
                "mass_imbalance_pct_max"
            ]
        ),

        "outlet_mass_flow_stationary": (
            flow_stats[
                "relative_range_pct"
            ]
            is not None
            and flow_stats[
                "relative_range_pct"
            ]
            <= limits[
                "outlet_mass_flow_relative_range_pct_max"
            ]
        ),

        "outlet_pressure_stationary": (
            p_stats[
                "relative_range_pct"
            ]
            is not None
            and p_stats[
                "relative_range_pct"
            ]
            <= limits[
                "outlet_pressure_relative_range_pct_max"
            ]
        ),

        "outlet_temperature_stationary": (
            T_stats[
                "relative_range_pct"
            ]
            is not None
            and T_stats[
                "relative_range_pct"
            ]
            <= limits[
                "outlet_temperature_relative_range_pct_max"
            ]
        ),

        "outlet_velocity_stationary": (
            U_stats[
                "relative_range_pct"
            ]
            is not None
            and U_stats[
                "relative_range_pct"
            ]
            <= limits[
                "outlet_velocity_relative_range_pct_max"
            ]
        ),
    }

    stationarity_passes = (
        enough_samples
        and all(
            stationarity_checks.values()
        )
    )

    # --------------------------------------------------------
    # Throat CFD diagnostics
    # --------------------------------------------------------

    throat_data: (
        dict[str, Any]
        | None
    ) = None

    throat_checked = False

    if geometry_manifest is not None:

        throat_data = (
            collect_throat_diagnostics(
                case_wsl,
                geometry_manifest,
                times,
                final_time,
                stationarity_window_samples=(
                    window_samples
                ),
            )
        )

        throat_checked = True

    # --------------------------------------------------------
    # Final structured diagnostic object
    # --------------------------------------------------------

    diagnostics: dict[
        str,
        Any,
    ] = {
        "case_wsl": (
            case_wsl
        ),

        "monitoring_window": {
            "start_time_s": (
                first_time
            ),

            "end_time_s": (
                final_time
            ),

            "saved_times_available": (
                len(times)
            ),
        },

        "mesh": (
            collect_mesh_metrics(
                case_wsl
            )
        ),

        "solver": (
            collect_solver_health(
                case_wsl,
                solver_log,
            )
        ),

        "flow": {
            "inlet_mass_flow_kg_s": (
                latest_inlet_flow
            ),

            "outlet_mass_flow_kg_s": (
                latest_outlet_flow
            ),

            "mass_imbalance_pct": (
                imbalance
            ),

            "outlet_pressure_pa": (
                latest_p
            ),

            "outlet_temperature_k": (
                latest_T
            ),

            "outlet_velocity_vector_mps": (
                latest_U_vector
            ),

            "outlet_velocity_mps": (
                latest_U
            ),

            "outlet_mach": (
                latest_Mach
            ),
        },

        "global_field_validity": (
            global_field_validity
        ),

        "stationarity": {
            "enough_samples": (
                enough_samples
            ),

            "checks": (
                stationarity_checks
            ),

            "passes_all_monitored_metrics": (
                stationarity_passes
            ),

            "outlet_mass_flow": (
                flow_stats
            ),

            "outlet_pressure": (
                p_stats
            ),

            "outlet_temperature": (
                T_stats
            ),

            "outlet_velocity": (
                U_stats
            ),
        },

        "throat": (
            throat_data
        ),

        "thresholds": (
            limits
        ),

        "coverage": {
            "global_field_validity_checked": (
                True
            ),

            "throat_state_checked": (
                throat_checked
            ),

            "note": (
                "Global pressure, temperature, "
                "and density extrema are checked. "
                "When a geometry manifest is "
                "provided, throat entry, center, "
                "exit, sonic transition, and "
                "recent throat-center history "
                "are also extracted."
            ),
        },
    }

    diagnostics[
        "status"
    ] = classify_diagnostics(
        diagnostics,
        limits,
    )

    return diagnostics


# ============================================================
# SERIALIZATION
# ============================================================


def save_diagnostics(
    diagnostics: dict[
        str,
        Any,
    ],
    output_path: Path,
) -> None:

    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    output_path.write_text(
        json.dumps(
            diagnostics,
            indent=2,
        ),
        encoding="utf-8",
    )


# ============================================================
# COMMAND LINE
# ============================================================


def main() -> None:

    parser = argparse.ArgumentParser(
        description=(
            "Extract deterministic CFD "
            "diagnostics from an "
            "OpenFOAM case."
        )
    )

    parser.add_argument(
        "--case-wsl",
        required=True,
    )

    parser.add_argument(
        "--start-time",
        type=float,
        default=None,
    )

    parser.add_argument(
        "--end-time",
        type=float,
        default=None,
    )

    parser.add_argument(
        "--solver-log",
        default=None,
    )

    parser.add_argument(
        "--geometry-manifest",
        type=Path,
        default=None,
    )

    parser.add_argument(
        "--output",
        type=Path,
        default=Path(
            "cfd_diagnostics.json"
        ),
    )

    args = parser.parse_args()

    geometry_manifest = None

    if (
        args.geometry_manifest
        is not None
    ):

        geometry_manifest = (
            load_json(
                args.geometry_manifest
            )
        )

    diagnostics = (
        collect_cfd_diagnostics(
            case_wsl=(
                args.case_wsl
            ),
            start_time=(
                args.start_time
            ),
            end_time=(
                args.end_time
            ),
            solver_log=(
                args.solver_log
            ),
            geometry_manifest=(
                geometry_manifest
            ),
        )
    )

    save_diagnostics(
        diagnostics,
        args.output,
    )

    fields = diagnostics[
        "global_field_validity"
    ]

    print()
    print("=" * 72)
    print("CFD DIAGNOSTICS")
    print("=" * 72)

    print(
        "Status              :",
        diagnostics[
            "status"
        ],
    )

    print(
        "Mass imbalance      :",
        (
            f"{diagnostics['flow']['mass_imbalance_pct']:.4f} %"
        ),
    )

    print(
        "Outlet Mach         :",
        (
            f"{diagnostics['flow']['outlet_mach']:.6f}"
        ),
    )

    print(
        "Stationarity passed :",
        diagnostics[
            "stationarity"
        ][
            "passes_all_monitored_metrics"
        ],
    )

    print(
        "Pressure range      :",
        (
            f"{fields['pressure']['min']['value']:.3f}"
            " to "
            f"{fields['pressure']['max']['value']:.3f} Pa"
        ),
    )

    print(
        "Temperature range   :",
        (
            f"{fields['temperature']['min']['value']:.3f}"
            " to "
            f"{fields['temperature']['max']['value']:.3f} K"
        ),
    )

    print(
        "Density range       :",
        (
            f"{fields['density']['min']['value']:.6f}"
            " to "
            f"{fields['density']['max']['value']:.6f} kg/m^3"
        ),
    )

    positivity = (
        fields[
            "positive_pressure"
        ]
        and fields[
            "positive_temperature"
        ]
        and fields[
            "positive_density"
        ]
    )

    print(
        "Global positivity   :",
        positivity,
    )

    throat = diagnostics.get(
        "throat"
    )

    if throat is not None:

        start_state = (
            throat[
                "latest_planes"
            ][
                "start"
            ]
        )

        center_state = (
            throat[
                "latest_planes"
            ][
                "center"
            ]
        )

        end_state = (
            throat[
                "latest_planes"
            ][
                "end"
            ]
        )

        sonic = throat[
            "sonic_transition"
        ]

        print(
            "Throat Mach start   :",
            (
                f"{start_state['mach']:.6f}"
            ),
        )

        print(
            "Throat Mach center  :",
            (
                f"{center_state['mach']:.6f}"
            ),
        )

        print(
            "Throat Mach end     :",
            (
                f"{end_state['mach']:.6f}"
            ),
        )

        print(
            "Sonic crossing      :",
            sonic[
                "detected"
            ],
        )

        if sonic[
            "detected"
        ]:

            print(
                "Estimated sonic x   :",
                (
                    f"{sonic['x_m']:.6f} m"
                ),
            )

    print(
        "Saved JSON          :",
        args.output,
    )

    print("=" * 72)


if __name__ == "__main__":
    main()