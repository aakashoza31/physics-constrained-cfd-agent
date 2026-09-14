from __future__ import annotations

import json
import math
import shlex
import subprocess
from pathlib import Path
from typing import Any

import gmsh
import numpy as np

from src.openfoam.executor import (
    OPENFOAM_BASHRC,
    OPENFOAM_DISTRO,
    windows_path_to_wsl,
)


def _run_wsl_bash(
    command: str,
    timeout_s: int,
) -> subprocess.CompletedProcess[str]:
    args = [
        "wsl.exe",
        "-d",
        OPENFOAM_DISTRO,
        "--",
        "bash",
        "-lc",
        command,
    ]

    try:
        return subprocess.run(
            args,
            text=True,
            capture_output=True,
            timeout=timeout_s,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout or ""
        stderr = exc.stderr or ""

        if isinstance(stdout, bytes):
            stdout = stdout.decode(errors="replace")
        if isinstance(stderr, bytes):
            stderr = stderr.decode(errors="replace")

        return subprocess.CompletedProcess(
            args=args,
            returncode=124,
            stdout=stdout,
            stderr=(
                stderr
                + "\n"
                + f"Command timed out after {timeout_s} seconds."
            ),
        )


def _combined_output(
    proc: subprocess.CompletedProcess[str],
) -> str:
    body = proc.stdout or ""

    if proc.stderr:
        if body and not body.endswith("\n"):
            body += "\n"
        body += proc.stderr

    return body


def _write_json(
    path: Path,
    payload: dict[str, Any],
) -> None:
    path.write_text(
        json.dumps(
            payload,
            indent=2,
        ),
        encoding="utf-8",
    )


def _numeric_time_dirs(
    case_dir: Path,
    *,
    positive_only: bool,
) -> list[Path]:
    values: list[tuple[float, Path]] = []

    for item in case_dir.iterdir():
        if not item.is_dir():
            continue

        try:
            value = float(item.name)
        except ValueError:
            continue

        if positive_only and value <= 0.0:
            continue

        values.append((value, item))

    values.sort(key=lambda pair: pair[0])
    return [item for _, item in values]


def _latest_numeric_time_dir(
    case_dir: Path,
) -> Path | None:
    dirs = _numeric_time_dirs(
        case_dir,
        positive_only=True,
    )
    return dirs[-1] if dirs else None


def _available_latest_fields(
    case_dir: Path,
) -> list[str]:
    latest_dir = _latest_numeric_time_dir(
        case_dir
    )

    if latest_dir is None:
        return []

    ignored = {
        "uniform",
        "polyMesh",
    }

    return sorted(
        item.name
        for item in latest_dir.iterdir()
        if item.is_file()
        and item.name not in ignored
    )


def _vtk_frame_sort_key(
    path: Path,
) -> tuple[float, str]:
    suffix = path.stem.rsplit("_", 1)[-1]

    try:
        return (
            float(suffix),
            path.name,
        )
    except ValueError:
        return (
            math.inf,
            path.name,
        )


def _volume_vtk_frames(
    vtk_dir: Path,
) -> list[Path]:
    if not vtk_dir.exists():
        return []

    frames = list(
        vtk_dir.glob("*.vtk")
    )

    return sorted(
        frames,
        key=_vtk_frame_sort_key,
    )


def preview_vtk_in_gmsh(
    vtk_path: Path,
) -> dict[str, Any]:
    if not vtk_path.exists():
        return {
            "opened": False,
            "reason": "VTK file does not exist.",
        }

    gmsh.initialize()

    try:
        gmsh.open(str(vtk_path))

        view_tags = list(
            gmsh.view.getTags()
        )

        print()
        print("=" * 60)
        print("OPENFOAM VTK OPENED IN GMSH")
        print("=" * 60)
        print(f"VTK: {vtk_path}")
        print(f"Loaded result views: {view_tags}")
        print("Close the Gmsh window when finished.")
        print("=" * 60)

        gmsh.fltk.run()

        return {
            "opened": True,
            "view_tags": view_tags,
        }

    except Exception as exc:
        return {
            "opened": False,
            "reason": (
                f"{type(exc).__name__}: {exc}"
            ),
        }

    finally:
        gmsh.finalize()


_FIELD_SPECS: dict[str, dict[str, str]] = {
    "p": {
        "source": "p",
        "display": "Pressure",
        "units": "Pa",
        "filename": "pressure",
    },
    "U_mag": {
        "source": "U",
        "display": "Velocity magnitude",
        "units": "m/s",
        "filename": "velocity_magnitude",
    },
    "T": {
        "source": "T",
        "display": "Temperature",
        "units": "K",
        "filename": "temperature",
    },
    "rho": {
        "source": "rho",
        "display": "Density",
        "units": "kg/m^3",
        "filename": "density",
    },
}


def _load_slice_for_field(
    vtk_path: Path,
    field_key: str,
):
    import pyvista as pv

    spec = _FIELD_SPECS[field_key]
    source = spec["source"]

    mesh = pv.read(str(vtk_path))

    if source not in mesh.point_data:
        if source in mesh.cell_data:
            mesh = mesh.cell_data_to_point_data(
                pass_cell_data=True
            )
        else:
            raise KeyError(
                f"Field '{source}' is not present in {vtk_path.name}."
            )

    if field_key == "U_mag":
        u = np.asarray(
            mesh.point_data["U"]
        )

        if u.ndim != 2 or u.shape[1] < 3:
            raise ValueError(
                "OpenFOAM U field is not a 3-component vector."
            )

        mesh.point_data["U_magnitude"] = (
            np.linalg.norm(
                u[:, :3],
                axis=1,
            )
        )
        scalar_name = "U_magnitude"
    else:
        scalar_name = source

    section = mesh.slice(
        normal=(0.0, 0.0, 1.0)
    )

    if scalar_name not in section.point_data:
        raise KeyError(
            f"Scalar '{scalar_name}' did not survive the center slice."
        )

    return (
        section,
        scalar_name,
    )


def _finite_range(
    arrays: list[np.ndarray],
) -> tuple[float, float]:
    mins: list[float] = []
    maxs: list[float] = []

    for array in arrays:
        values = np.asarray(array).reshape(-1)
        values = values[np.isfinite(values)]

        if values.size:
            mins.append(float(values.min()))
            maxs.append(float(values.max()))

    if not mins:
        return (0.0, 1.0)

    low = min(mins)
    high = max(maxs)

    if math.isclose(low, high):
        pad = (
            abs(low) * 1e-6
            if low != 0.0
            else 1.0
        )
        low -= pad
        high += pad

    return (
        low,
        high,
    )


def _render_slice_image(
    section,
    scalar_name: str,
    *,
    title: str,
    units: str,
    output_path: Path,
    clim: tuple[float, float] | None = None,
) -> None:
    import pyvista as pv

    plotter = pv.Plotter(
        off_screen=True,
        window_size=(1200, 700),
    )

    try:
        plotter.add_mesh(
            section,
            scalars=scalar_name,
            show_edges=False,
            clim=clim,
            scalar_bar_args={
                "title": (
                    f"{title} [{units}]"
                    if units
                    else title
                ),
            },
        )

        plotter.add_text(
            title,
            position="upper_left",
            font_size=14,
        )

        plotter.view_xy()
        plotter.reset_camera()

        plotter.show(
            screenshot=str(output_path)
        )

    finally:
        plotter.close()


def _render_animation_gif(
    vtk_frames: list[Path],
    field_key: str,
    output_path: Path,
) -> dict[str, Any]:
    from PIL import Image
    import pyvista as pv

    spec = _FIELD_SPECS[field_key]

    prepared: list[
        tuple[Any, str, np.ndarray]
    ] = []

    for vtk_path in vtk_frames:
        section, scalar_name = (
            _load_slice_for_field(
                vtk_path,
                field_key,
            )
        )

        values = np.asarray(
            section.point_data[
                scalar_name
            ]
        )

        prepared.append(
            (
                section,
                scalar_name,
                values,
            )
        )

    if len(prepared) < 2:
        return {
            "created": False,
            "reason": (
                "At least two retained CFD time states are "
                "required for an animation."
            ),
            "frame_count": len(prepared),
            "path": None,
        }

    clim = _finite_range(
        [
            values
            for _, _, values
            in prepared
        ]
    )

    images: list[Image.Image] = []

    for index, (
        section,
        scalar_name,
        _values,
    ) in enumerate(prepared, start=1):
        plotter = pv.Plotter(
            off_screen=True,
            window_size=(1200, 700),
        )

        try:
            plotter.add_mesh(
                section,
                scalars=scalar_name,
                show_edges=False,
                clim=clim,
                scalar_bar_args={
                    "title": (
                        f"{spec['display']} "
                        f"[{spec['units']}]"
                    ),
                },
            )

            plotter.add_text(
                (
                    f"{spec['display']}   "
                    f"frame {index}/{len(prepared)}"
                ),
                position="upper_left",
                font_size=14,
            )

            plotter.view_xy()
            plotter.reset_camera()

            image = plotter.screenshot(
                return_img=True
            )

            images.append(
                Image.fromarray(
                    image
                ).convert("RGB")
            )

        finally:
            plotter.close()

    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    images[0].save(
        output_path,
        save_all=True,
        append_images=images[1:],
        duration=180,
        loop=0,
        optimize=False,
    )

    return {
        "created": True,
        "reason": "ok",
        "frame_count": len(images),
        "path": str(output_path),
        "scalar_range": [
            clim[0],
            clim[1],
        ],
    }


def _create_pyvista_demo_assets(
    *,
    volume_frames: list[Path],
    output_dir: Path,
) -> dict[str, Any]:
    output_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    try:
        import pyvista  # noqa: F401
        from PIL import Image  # noqa: F401
    except Exception as exc:
        return {
            "ok": False,
            "reason": (
                "PyVista/Pillow unavailable: "
                f"{type(exc).__name__}: {exc}"
            ),
            "static_images": {},
            "animations": {},
        }

    if not volume_frames:
        return {
            "ok": False,
            "reason": "No internal-volume VTK frames were found.",
            "static_images": {},
            "animations": {},
        }

    latest_vtk = volume_frames[-1]

    static_images: dict[
        str,
        str | None,
    ] = {}

    static_errors: dict[
        str,
        str,
    ] = {}

    for field_key, spec in _FIELD_SPECS.items():
        output_path = (
            output_dir
            / f"{spec['filename']}_latest.png"
        )

        try:
            section, scalar_name = (
                _load_slice_for_field(
                    latest_vtk,
                    field_key,
                )
            )

            _render_slice_image(
                section,
                scalar_name,
                title=spec["display"],
                units=spec["units"],
                output_path=output_path,
            )

            static_images[field_key] = (
                str(output_path)
            )

        except Exception as exc:
            static_images[field_key] = None
            static_errors[field_key] = (
                f"{type(exc).__name__}: {exc}"
            )

    animations: dict[
        str,
        dict[str, Any],
    ] = {}

    for field_key in (
        "p",
        "U_mag",
    ):
        spec = _FIELD_SPECS[
            field_key
        ]

        gif_path = (
            output_dir
            / f"{spec['filename']}_transient.gif"
        )

        try:
            animations[field_key] = (
                _render_animation_gif(
                    volume_frames,
                    field_key,
                    gif_path,
                )
            )
        except Exception as exc:
            animations[field_key] = {
                "created": False,
                "reason": (
                    f"{type(exc).__name__}: {exc}"
                ),
                "frame_count": 0,
                "path": None,
            }

    created_static = sum(
        path is not None
        for path
        in static_images.values()
    )

    created_gifs = sum(
        bool(
            info.get(
                "created",
                False,
            )
        )
        for info
        in animations.values()
    )

    return {
        "ok": (
            created_static > 0
        ),
        "reason": (
            "ok"
            if created_static > 0
            else "No static PyVista plots were created."
        ),
        "vtk_frame_count": (
            len(volume_frames)
        ),
        "static_images": (
            static_images
        ),
        "static_errors": (
            static_errors
        ),
        "animations": (
            animations
        ),
        "created_static_count": (
            created_static
        ),
        "created_animation_count": (
            created_gifs
        ),
    }


def prepare_openfoam_visualization(
    *,
    case_dir: Path,
    timeout_s: int = 300,
    open_in_gmsh: bool = False,
    create_demo_assets: bool = True,
) -> dict[str, Any]:
    """
    Post-process an already-computed OpenFOAM case.

    The case is staged into a clean WSL path because OpenFOAM v14
    rejects the user's Windows project path when it contains spaces.

    This function:
      1. stages the completed case into WSL,
      2. exports ALL retained CFD time states using foamToVTK,
      3. copies VTK files back to Windows,
      4. creates static PyVista CFD plots,
      5. creates transient pressure/velocity GIFs.

    It never reruns the solver and never modifies CFD fields.
    """

    case_dir = case_dir.resolve()

    if not case_dir.exists():
        raise FileNotFoundError(
            f"OpenFOAM case not found: {case_dir}"
        )

    poly_mesh = (
        case_dir
        / "constant"
        / "polyMesh"
    )

    if not poly_mesh.exists():
        raise FileNotFoundError(
            "OpenFOAM polyMesh is missing: "
            f"{poly_mesh}"
        )

    latest_dir = (
        _latest_numeric_time_dir(
            case_dir
        )
    )

    if latest_dir is None:
        raise RuntimeError(
            "No positive OpenFOAM result time directory was found."
        )

    fields = (
        _available_latest_fields(
            case_dir
        )
    )

    retained_times = [
        item.name
        for item in _numeric_time_dirs(
            case_dir,
            positive_only=False,
        )
    ]

    foam_marker = (
        case_dir
        / (
            case_dir.name
            + ".foam"
        )
    )

    foam_marker.write_text(
        "",
        encoding="utf-8",
    )

    case_wsl = (
        windows_path_to_wsl(
            case_dir
        )
    )

    runtime_name = (
        "physics_constrained_cfd_"
        "visualization_runtime"
    )

    runtime_expr = (
        f"$HOME/{runtime_name}"
    )

    quoted_case_source = (
        shlex.quote(
            case_wsl
            + "/."
        )
    )

    quoted_case_destination = (
        shlex.quote(
            case_wsl
            + "/"
        )
    )

    bashrc = (
        shlex.quote(
            OPENFOAM_BASHRC
        )
    )

    stage_command = (
        f'rm -rf "{runtime_expr}" '
        f'&& mkdir -p "{runtime_expr}" '
        f'&& cp -r '
        f'{quoted_case_source} '
        f'"{runtime_expr}/"'
    )

    stage_proc = (
        _run_wsl_bash(
            command=stage_command,
            timeout_s=timeout_s,
        )
    )

    (
        case_dir
        / "log.visualizationStageToWSL"
    ).write_text(
        _combined_output(
            stage_proc
        ),
        encoding="utf-8",
    )

    vtk_proc = None
    vtk_log = ""

    if stage_proc.returncode == 0:
        vtk_command = (
            f'. {bashrc} '
            f'&& cd "{runtime_expr}" '
            '&& rm -rf VTK '
            '&& foamToVTK '
            '-ascii'
        )

        vtk_proc = (
            _run_wsl_bash(
                command=vtk_command,
                timeout_s=timeout_s,
            )
        )

        vtk_log = (
            _combined_output(
                vtk_proc
            )
        )

    (
        case_dir
        / "log.foamToVTK"
    ).write_text(
        vtk_log,
        encoding="utf-8",
    )

    sync_proc = None
    sync_log = ""

    if (
        vtk_proc is not None
        and vtk_proc.returncode == 0
    ):
        sync_command = (
            f'rm -rf '
            f'{shlex.quote(case_wsl + "/VTK")} '
            f'&& cp -r '
            f'"{runtime_expr}/VTK" '
            f'{quoted_case_destination}'
        )

        sync_proc = (
            _run_wsl_bash(
                command=sync_command,
                timeout_s=timeout_s,
            )
        )

        sync_log = (
            _combined_output(
                sync_proc
            )
        )

    (
        case_dir
        / "log.visualizationSyncFromWSL"
    ).write_text(
        sync_log,
        encoding="utf-8",
    )

    vtk_dir = (
        case_dir
        / "VTK"
    )

    vtk_files = (
        sorted(
            vtk_dir.rglob("*.vtk")
        )
        if vtk_dir.exists()
        else []
    )

    volume_frames = (
        _volume_vtk_frames(
            vtk_dir
        )
    )

    primary_vtk = (
        volume_frames[-1]
        if volume_frames
        else None
    )

    vtk_return_code = (
        vtk_proc.returncode
        if vtk_proc is not None
        else None
    )

    sync_return_code = (
        sync_proc.returncode
        if sync_proc is not None
        else None
    )

    vtk_export_ok = (
        stage_proc.returncode == 0
        and vtk_return_code == 0
        and sync_return_code == 0
        and primary_vtk is not None
    )

    demo_assets: dict[
        str,
        Any,
    ] | None = None

    if (
        vtk_export_ok
        and create_demo_assets
    ):
        demo_assets = (
            _create_pyvista_demo_assets(
                volume_frames=volume_frames,
                output_dir=(
                    case_dir
                    / "demo_visuals"
                ),
            )
        )

    preview_result: dict[
        str,
        Any,
    ] | None = None

    if (
        vtk_export_ok
        and open_in_gmsh
        and primary_vtk is not None
    ):
        preview_result = (
            preview_vtk_in_gmsh(
                primary_vtk
            )
        )

    recommended_fields = [
        name
        for name in (
            "p",
            "U",
            "T",
            "rho",
            "k",
            "omega",
        )
        if name in fields
    ]

    result = {
        "status": (
            "visualization_ready"
            if vtk_export_ok
            else "vtk_export_failed"
        ),
        "case_dir": str(case_dir),
        "latest_time": latest_dir.name,
        "retained_openfoam_times": (
            retained_times
        ),
        "latest_fields": fields,
        "recommended_demo_fields": (
            recommended_fields
        ),
        "paraview_case_file": str(
            foam_marker
        ),
        "wsl_runtime": (
            f"$HOME/{runtime_name}"
        ),
        "stage_return_code": (
            stage_proc.returncode
        ),
        "vtk_export_ok": (
            vtk_export_ok
        ),
        "vtk_return_code": (
            vtk_return_code
        ),
        "sync_return_code": (
            sync_return_code
        ),
        "vtk_log": str(
            case_dir
            / "log.foamToVTK"
        ),
        "vtk_directory": str(
            vtk_dir
        ),
        "vtk_files": [
            str(path)
            for path in vtk_files
        ],
        "volume_vtk_frames": [
            str(path)
            for path in volume_frames
        ],
        "volume_vtk_frame_count": (
            len(volume_frames)
        ),
        "primary_vtk": (
            str(primary_vtk)
            if primary_vtk is not None
            else None
        ),
        "demo_assets": (
            demo_assets
        ),
        "gmsh_preview": (
            preview_result
        ),
    }

    _write_json(
        case_dir
        / "visualization_summary.json",
        result,
    )

    return result

