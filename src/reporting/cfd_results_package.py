from __future__ import annotations

import html
import json
import math
import os
import shutil
from pathlib import Path
from typing import Any


# ================================================================
# SMALL HELPERS
# ================================================================

def _jsonable(
    value: Any,
) -> Any:

    if hasattr(
        value,
        "to_dict",
    ):

        return value.to_dict()

    if hasattr(
        value,
        "model_dump",
    ):

        return value.model_dump()

    return value


def _save_json(
    path: Path,
    value: Any,
) -> None:

    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    path.write_text(
        json.dumps(
            _jsonable(value),
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )


def _deep_get(
    data: Any,
    *keys: str,
) -> Any:

    current = data

    for key in keys:

        if not isinstance(
            current,
            dict,
        ):

            return None

        current = current.get(
            key
        )

        if current is None:
            return None

    return current


def _fmt(
    value: Any,
    digits: int = 4,
) -> str:

    if value is None:
        return "Not measured"

    if isinstance(
        value,
        bool,
    ):
        return (
            "Yes"
            if value
            else "No"
        )

    if isinstance(
        value,
        (int, float),
    ):

        try:

            number = float(
                value
            )

            if not math.isfinite(
                number
            ):
                return str(value)

            if abs(
                number
            ) >= 1.0e5:

                return (
                    f"{number:,.3f}"
                )

            return (
                f"{number:.{digits}f}"
            )

        except Exception:
            pass

    return str(
        value
    )


def _flatten_scalars(
    obj: Any,
    prefix: str = "",
) -> list[
    tuple[
        str,
        Any,
    ]
]:

    rows = []

    if isinstance(
        obj,
        dict,
    ):

        for key, value in (
            obj.items()
        ):

            child = (
                f"{prefix}.{key}"
                if prefix
                else str(
                    key
                )
            )

            rows.extend(
                _flatten_scalars(
                    value,
                    child,
                )
            )

        return rows

    if isinstance(
        obj,
        list,
    ):

        if all(
            not isinstance(
                item,
                (
                    dict,
                    list,
                ),
            )
            for item in obj
        ):

            rows.append(
                (
                    prefix,
                    obj,
                )
            )

        return rows

    rows.append(
        (
            prefix,
            obj,
        )
    )

    return rows


# ================================================================
# VTK VISUALIZATION
# ================================================================

def create_standardized_cfd_images(
    *,
    primary_vtk: Path,
    output_dir: Path,
    gamma: float = 1.4,
    gas_constant: float = 287.0,
) -> dict[
    str,
    str,
]:

    """
    Produce standardized evidence images for the final run.

    Images:
      pressure.png
      mach.png
      velocity_magnitude.png
      mesh.png

    These are supporting evidence. Numerical diagnostics remain
    authoritative for acceptance/rejection.
    """

    primary_vtk = Path(
        primary_vtk
    )

    output_dir = Path(
        output_dir
    )

    output_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    if not primary_vtk.exists():

        raise FileNotFoundError(
            f"VTK field does not exist: "
            f"{primary_vtk}"
        )

    import numpy as np
    import pyvista as pv

    grid = pv.read(
        str(
            primary_vtk
        )
    )

    # Use one coordinate representation for all images.
    if (
        len(
            grid.cell_data
        )
        > 0
    ):

        data = (
            grid
            .cell_data_to_point_data()
        )

    else:

        data = grid.copy()


    available = set(
        data.point_data.keys()
    )


    # ------------------------------------------------------------
    # Derived velocity magnitude
    # ------------------------------------------------------------

    if "U" in available:

        U = np.asarray(
            data.point_data[
                "U"
            ]
        )

        if (
            U.ndim == 2
            and U.shape[1] >= 3
        ):

            speed = np.linalg.norm(
                U[:, :3],
                axis=1,
            )

            data.point_data[
                "VelocityMagnitude"
            ] = speed


    # ------------------------------------------------------------
    # Derived Mach
    # ------------------------------------------------------------

    if (
        "VelocityMagnitude"
        in data.point_data
        and "T"
        in available
    ):

        T = np.asarray(
            data.point_data[
                "T"
            ]
        ).reshape(
            -1
        )

        speed = np.asarray(
            data.point_data[
                "VelocityMagnitude"
            ]
        ).reshape(
            -1
        )

        valid_T = np.maximum(
            T,
            1.0e-12,
        )

        sound_speed = np.sqrt(
            gamma
            * gas_constant
            * valid_T
        )

        data.point_data[
            "Mach"
        ] = (
            speed
            / sound_speed
        )


    # ------------------------------------------------------------
    # Fixed center slice
    #
    # Nozzle axis = x.
    # z=midplane gives a longitudinal x-y slice.
    # ------------------------------------------------------------

    center = data.center

    sliced = data.slice(
        normal=(
            0.0,
            0.0,
            1.0,
        ),
        origin=center,
    )


    images: dict[
        str,
        str,
    ] = {}


    def render_scalar(
        field: str,
        filename: str,
        title: str,
    ) -> None:

        if (
            field
            not in sliced.point_data
        ):

            return

        target = (
            output_dir
            / filename
        )

        plotter = pv.Plotter(
            off_screen=True,
            window_size=(
                1500,
                850,
            ),
        )

        plotter.add_mesh(
            sliced,
            scalars=field,
            show_edges=False,
            scalar_bar_args={
                "title": title,
            },
        )

        plotter.view_xy()

        plotter.camera.parallel_projection = (
            True
        )

        plotter.add_text(
            title,
            position="upper_left",
            font_size=16,
        )

        plotter.screenshot(
            str(
                target
            )
        )

        plotter.close()

        images[
            field
        ] = str(
            target
        )


    render_scalar(
        "p",
        "pressure.png",
        "Pressure [Pa]",
    )

    render_scalar(
        "Mach",
        "mach.png",
        "Mach number",
    )

    render_scalar(
        "VelocityMagnitude",
        "velocity_magnitude.png",
        "Velocity magnitude [m/s]",
    )


    # ------------------------------------------------------------
    # Mesh image
    # ------------------------------------------------------------

    mesh_target = (
        output_dir
        / "mesh.png"
    )

    mesh_plotter = pv.Plotter(
        off_screen=True,
        window_size=(
            1500,
            850,
        ),
    )

    mesh_plotter.add_mesh(
        sliced,
        style="wireframe",
    )

    mesh_plotter.view_xy()

    mesh_plotter.camera.parallel_projection = (
        True
    )

    mesh_plotter.add_text(
        "Final CFD mesh: center slice",
        position="upper_left",
        font_size=16,
    )

    mesh_plotter.screenshot(
        str(
            mesh_target
        )
    )

    mesh_plotter.close()

    images[
        "mesh"
    ] = str(
        mesh_target
    )


    return images


# ================================================================
# HUMAN-READABLE REPORT
# ================================================================

def _build_markdown_report(
    *,
    run_name: str,
    problem_spec: dict[
        str,
        Any,
    ],
    diagnostics: dict[
        str,
        Any,
    ],
    decision: dict[
        str,
        Any,
    ] | None,
    images: dict[
        str,
        str,
    ],
) -> str:

    status = diagnostics.get(
        "status"
    )

    mass_imbalance = (
        _deep_get(
            diagnostics,
            "flow",
            "mass_imbalance_pct",
        )
    )

    if mass_imbalance is None:

        mass_imbalance = (
            _deep_get(
                diagnostics,
                "conservation",
                "mass_imbalance_percent",
            )
        )


    stationarity = (
        _deep_get(
            diagnostics,
            "stationarity",
            "passes_stationarity",
        )
    )

    if stationarity is None:

        stationarity = (
            _deep_get(
                diagnostics,
                "stationarity",
                "passes_all_monitored_metrics",
            )
        )


    mesh_cells = (
        _deep_get(
            diagnostics,
            "mesh",
            "cells",
        )
    )

    if mesh_cells is None:

        mesh_cells = (
            _deep_get(
                diagnostics,
                "mesh_quality",
                "cells",
            )
        )


    p_min = (
        _deep_get(
            diagnostics,
            "global_field_validity",
            "pressure_min_pa",
        )
    )

    p_max = (
        _deep_get(
            diagnostics,
            "global_field_validity",
            "pressure_max_pa",
        )
    )

    T_min = (
        _deep_get(
            diagnostics,
            "global_field_validity",
            "temperature_min_k",
        )
    )

    T_max = (
        _deep_get(
            diagnostics,
            "global_field_validity",
            "temperature_max_k",
        )
    )


    diagnosis = None
    action = None
    confidence = None
    reasoning = None

    if isinstance(
        decision,
        dict,
    ):

        inner = decision.get(
            "decision",
            decision,
        )

        if isinstance(
            inner,
            dict,
        ):

            diagnosis = inner.get(
                "diagnosis"
            )

            action = inner.get(
                "action"
            )

            confidence = inner.get(
                "confidence"
            )

            reasoning = inner.get(
                "reasoning_summary"
            )


    lines = [
        f"# Autonomous CFD Results: {run_name}",
        "",
        "## Executive summary",
        "",
        f"- CFD status: **{_fmt(status)}**",
        f"- Final agent diagnosis: **{_fmt(diagnosis)}**",
        f"- Final agent action: **{_fmt(action)}**",
        f"- Agent confidence: **{_fmt(confidence)}**",
        f"- Mass-flow imbalance: **{_fmt(mass_imbalance)} %**",
        f"- Stationarity passed: **{_fmt(stationarity)}**",
        f"- Mesh cells: **{_fmt(mesh_cells, 0)}**",
        "",
    ]


    if reasoning:

        lines.extend(
            [
                "### Agent interpretation",
                "",
                str(
                    reasoning
                ),
                "",
            ]
        )


    lines.extend(
        [
            "## Problem specification",
            "",
            "```json",
            json.dumps(
                problem_spec,
                indent=2,
                default=str,
            ),
            "```",
            "",
            "## Key physical-field diagnostics",
            "",
            "| Quantity | Value |",
            "|---|---:|",
            (
                f"| Global pressure minimum | "
                f"{_fmt(p_min)} Pa |"
            ),
            (
                f"| Global pressure maximum | "
                f"{_fmt(p_max)} Pa |"
            ),
            (
                f"| Global temperature minimum | "
                f"{_fmt(T_min)} K |"
            ),
            (
                f"| Global temperature maximum | "
                f"{_fmt(T_max)} K |"
            ),
            (
                f"| Mass-flow imbalance | "
                f"{_fmt(mass_imbalance)} % |"
            ),
            (
                f"| Stationarity passed | "
                f"{_fmt(stationarity)} |"
            ),
            "",
            "## CFD evidence",
            "",
            (
                "The numerical diagnostics determine whether the "
                "solution is trustworthy. The images below are "
                "supporting evidence used to inspect flow structure, "
                "localized gradients, and mesh resolution."
            ),
            "",
        ]
    )


    image_order = [
        (
            "p",
            "Pressure field",
        ),
        (
            "Mach",
            "Mach-number field",
        ),
        (
            "VelocityMagnitude",
            "Velocity-magnitude field",
        ),
        (
            "mesh",
            "Final CFD mesh",
        ),
    ]


    for key, title in image_order:

        path = images.get(
            key
        )

        if not path:
            continue

        relative = (
            Path(
                path
            ).name
        )

        lines.extend(
            [
                f"### {title}",
                "",
                (
                    f"![{title}]"
                    f"(images/{relative})"
                ),
                "",
            ]
        )


    lines.extend(
        [
            "## Complete deterministic diagnostics",
            "",
            (
                "The compact table below records every scalar "
                "diagnostic stored by the CFD diagnostics subsystem."
            ),
            "",
            "| Diagnostic | Value |",
            "|---|---|",
        ]
    )


    for key, value in (
        _flatten_scalars(
            diagnostics
        )
    ):

        if not key:
            continue

        rendered = _fmt(
            value
        ).replace(
            "|",
            "\\|",
        )

        lines.append(
            f"| `{key}` | {rendered} |"
        )


    lines.extend(
        [
            "",
            "## Interpretation notes",
            "",
            (
                "- Solver completion alone is not treated as "
                "evidence of CFD convergence."
            ),
            (
                "- Mesh quality passing alone is not treated as "
                "evidence of adequate physical resolution."
            ),
            (
                "- Analytical theory, when available, should be "
                "reported separately as post-hoc validation rather "
                "than silently used as CFD evidence."
            ),
            (
                "- Full machine-readable evidence and the agent "
                "decision are stored beside this report."
            ),
            "",
        ]
    )


    return "\n".join(
        lines
    )


def _markdown_to_simple_html(
    markdown_text: str,
    title: str,
    image_names: list[
        str,
    ],
) -> str:

    # Deliberately dependency-free HTML summary.
    escaped = html.escape(
        markdown_text
    )

    image_html = "\n".join(
        (
            '<div class="figure">'
            f'<img src="images/{html.escape(name)}">'
            f'<p>{html.escape(name)}</p>'
            "</div>"
        )
        for name in image_names
    )

    return f"""<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>{html.escape(title)}</title>
<style>
body {{
    font-family: Segoe UI, Arial, sans-serif;
    max-width: 1150px;
    margin: 40px auto;
    padding: 0 28px;
    line-height: 1.5;
}}
h1 {{
    margin-bottom: 6px;
}}
pre {{
    white-space: pre-wrap;
    background: #f4f4f4;
    padding: 18px;
    border-radius: 8px;
}}
.figure {{
    margin: 28px 0;
}}
.figure img {{
    width: 100%;
    border: 1px solid #ddd;
}}
.figure p {{
    font-size: 0.9rem;
}}
</style>
</head>
<body>
<h1>{html.escape(title)}</h1>
{image_html}
<h2>Complete report</h2>
<pre>{escaped}</pre>
</body>
</html>
"""


# ================================================================
# FINAL PACKAGE CREATION
# ================================================================

def create_final_results_package(
    *,
    run_name: str,
    output_dir: Path,
    problem_spec: Any,
    diagnostics: dict[
        str,
        Any,
    ],
    decision: Any = None,
    primary_vtk: Path | None = None,
    final_mesh: Path | None = None,
    gamma: float = 1.4,
    gas_constant: float = 287.0,
    open_folder: bool = False,
) -> dict[
    str,
    Any,
]:

    """
    Build the final results package.

    The directory contains:

      CFD_REPORT.md
      CFD_REPORT.html
      problem_spec.json
      cfd_diagnostics.json
      agent_decision.json
      final_mesh.*
      final_field.vtk
      images/
          pressure.png
          mach.png
          velocity_magnitude.png
          mesh.png
      package_manifest.json

    On Windows, the results folder is opened in the file browser only when
    open_folder=True (default False).
    """

    output_dir = Path(
        output_dir
    ).resolve()

    output_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    images_dir = (
        output_dir
        / "images"
    )

    images_dir.mkdir(
        parents=True,
        exist_ok=True,
    )


    problem_dict = _jsonable(
        problem_spec
    )

    decision_dict = (
        _jsonable(
            decision
        )
        if decision is not None
        else None
    )


    _save_json(
        output_dir
        / "problem_spec.json",
        problem_dict,
    )

    _save_json(
        output_dir
        / "cfd_diagnostics.json",
        diagnostics,
    )

    if decision_dict is not None:

        _save_json(
            output_dir
            / "agent_decision.json",
            decision_dict,
        )


    copied_vtk = None

    if (
        primary_vtk is not None
        and Path(
            primary_vtk
        ).exists()
    ):

        copied_vtk = (
            output_dir
            / "final_field.vtk"
        )

        shutil.copy2(
            Path(
                primary_vtk
            ),
            copied_vtk,
        )


    copied_mesh = None

    if (
        final_mesh is not None
        and Path(
            final_mesh
        ).exists()
    ):

        final_mesh = Path(
            final_mesh
        )

        copied_mesh = (
            output_dir
            / (
                "final_mesh"
                + final_mesh.suffix
            )
        )

        shutil.copy2(
            final_mesh,
            copied_mesh,
        )


    images = {}

    visualization_error = None

    if copied_vtk is not None:

        try:

            images = (
                create_standardized_cfd_images(
                    primary_vtk=(
                        copied_vtk
                    ),
                    output_dir=(
                        images_dir
                    ),
                    gamma=gamma,
                    gas_constant=(
                        gas_constant
                    ),
                )
            )

        except Exception as exc:

            visualization_error = (
                f"{type(exc).__name__}: "
                f"{exc}"
            )


    markdown = (
        _build_markdown_report(
            run_name=run_name,
            problem_spec=(
                problem_dict
            ),
            diagnostics=(
                diagnostics
            ),
            decision=(
                decision_dict
            ),
            images=images,
        )
    )


    markdown_path = (
        output_dir
        / "CFD_REPORT.md"
    )

    markdown_path.write_text(
        markdown,
        encoding="utf-8",
    )


    html_path = (
        output_dir
        / "CFD_REPORT.html"
    )

    image_names = [
        Path(
            value
        ).name
        for value in images.values()
    ]

    html_path.write_text(
        _markdown_to_simple_html(
            markdown,
            (
                f"Autonomous CFD Results: "
                f"{run_name}"
            ),
            image_names,
        ),
        encoding="utf-8",
    )


    manifest = {
        "run_name": run_name,
        "results_directory": str(
            output_dir
        ),
        "report_markdown": str(
            markdown_path
        ),
        "report_html": str(
            html_path
        ),
        "primary_vtk": (
            str(
                copied_vtk
            )
            if copied_vtk
            else None
        ),
        "final_mesh": (
            str(
                copied_mesh
            )
            if copied_mesh
            else None
        ),
        "images": images,
        "visualization_error": (
            visualization_error
        ),
    }


    _save_json(
        output_dir
        / "package_manifest.json",
        manifest,
    )


    print()
    print("=" * 72)
    print("FINAL CFD RESULTS PACKAGE")
    print("=" * 72)

    print(
        "Results folder :",
        output_dir,
    )

    print(
        "Report         :",
        html_path,
    )

    print(
        "Images created :",
        len(
            images
        ),
    )

    if visualization_error:

        print(
            "Visualization warning:",
            visualization_error,
        )


    if (
        open_folder
        and os.name == "nt"
    ):

        os.startfile(
            str(
                output_dir
            )
        )


    return manifest
