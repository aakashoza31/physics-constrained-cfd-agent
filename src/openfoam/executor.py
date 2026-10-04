"""Legacy prototype (CAD->Gmsh path, paper Appendix C "Prototype before the
registered contracts"); not the registered nozzle family; not used for any
reported result except that prototype record.

WSL/OpenFOAM command runner of the prototype. Not imported by the registered
family runners (scripts/run_nozzle_feedback.py, scripts/run_nozzle_e2e.py,
scripts/run_forward_step_2d.py) or by src/pipeline; only the other prototype
modules in src/openfoam use it.
"""
from __future__ import annotations

import json
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


# ============================================================
# PATH / PROCESS HELPERS
# ============================================================


def windows_path_to_wsl(
    path: Path,
) -> str:
    """
    Convert a normal Windows path such as:

        C:\\Users\\...\\case

    into:

        /mnt/c/Users/.../case

    The current project executes OpenFOAM through WSL.
    """

    resolved = path.resolve()

    drive = (
        resolved.drive
        .rstrip(":")
        .lower()
    )

    if not drive:
        raise ValueError(
            "Expected a Windows drive path for "
            f"OpenFOAM WSL execution, got: {resolved}"
        )

    tail = (
        resolved
        .as_posix()
        .split(
            ":",
            1,
        )[-1]
    )

    return (
        f"/mnt/{drive}{tail}"
    )


def _run_wsl_bash(
    command: str,
    timeout: int,
) -> subprocess.CompletedProcess[str]:
    """
    Execute one deterministic OpenFOAM/WSL command.

    Python owns the return code. This avoids relying on shell
    bookkeeping across the Windows/WSL boundary.
    """

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
            timeout=timeout,
            check=False,
        )

    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout or ""
        stderr = exc.stderr or ""

        if isinstance(
            stdout,
            bytes,
        ):
            stdout = stdout.decode(
                errors="replace"
            )

        if isinstance(
            stderr,
            bytes,
        ):
            stderr = stderr.decode(
                errors="replace"
            )

        if stderr:
            stderr += "\n"

        stderr += (
            f"Command timed out after "
            f"{timeout} seconds."
        )

        return subprocess.CompletedProcess(
            args=args,
            returncode=124,
            stdout=stdout,
            stderr=stderr,
        )


def _combined_output(
    proc: subprocess.CompletedProcess[str],
) -> str:
    body = (
        proc.stdout
        or ""
    )

    if proc.stderr:
        if (
            body
            and not body.endswith(
                "\n"
            )
        ):
            body += "\n"

        body += proc.stderr

    return body


def _write_log(
    case_dir: Path,
    name: str,
    proc: subprocess.CompletedProcess[str],
) -> str:
    body = _combined_output(
        proc
    )

    (
        case_dir
        / name
    ).write_text(
        body,
        encoding="utf-8",
    )

    return body


# ============================================================
# LOG PARSERS
# ============================================================


def parse_checkmesh(
    text: str,
) -> dict[str, Any]:
    def grab(
        pattern: str,
        cast=float,
    ):
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
            and "FOAM FATAL" not in text
        ),
        "fatal_error": (
            "FOAM FATAL" in text
        ),
        "cells": grab(
            r"cells:\s+(\d+)",
            int,
        ),
        "points": grab(
            r"points:\s+(\d+)",
            int,
        ),
        "faces": grab(
            r"faces:\s+(\d+)",
            int,
        ),
        "max_aspect_ratio": grab(
            r"Max aspect ratio\s*=\s*"
            r"([0-9.eE+\-]+)"
        ),
        "max_non_orthogonality": grab(
            r"Mesh non-orthogonality Max:"
            r"\s*([0-9.eE+\-]+)"
        ),
        "average_non_orthogonality": grab(
            r"average:\s*([0-9.eE+\-]+)"
        ),
        "max_skewness": grab(
            r"Max skewness\s*=\s*"
            r"([0-9.eE+\-]+)"
        ),
    }


def parse_solver_log(
    text: str,
) -> dict[str, Any]:
    times = [
        float(
            item
        )
        for item in re.findall(
            r"^Time =\s*"
            r"([0-9.eE+\-]+)",
            text,
            flags=re.MULTILINE,
        )
    ]

    residuals = [
        float(
            item
        )
        for item in re.findall(
            r"Initial residual =\s*"
            r"([0-9.eE+\-]+)",
            text,
        )
    ]

    courant_matches = re.findall(
        r"Courant Number mean:\s*"
        r"([0-9.eE+\-]+)"
        r"\s*max:\s*"
        r"([0-9.eE+\-]+)",
        text,
        flags=re.IGNORECASE,
    )

    max_courant_seen = None

    if courant_matches:
        max_courant_seen = max(
            float(
                pair[1]
            )
            for pair in courant_matches
        )

    execution_times = [
        float(
            item
        )
        for item in re.findall(
            r"ExecutionTime\s*=\s*"
            r"([0-9.eE+\-]+)\s*s",
            text,
        )
    ]

    completed = (
        text.rstrip().endswith("End")
        and "FOAM FATAL" not in text
        and "sigFpe::sigHandler" not in text
        and "Floating point exception (core dumped)" not in text
    )

    return {
        "completed": completed,
        "fatal_error": (
            "FOAM FATAL" in text
        ),
        "last_time": (
            times[-1]
            if times
            else None
        ),
        "time_steps_reported": (
            len(
                times
            )
        ),
        "initial_residual_max": (
            max(
                residuals
            )
            if residuals
            else None
        ),
        "initial_residual_last": (
            residuals[-1]
            if residuals
            else None
        ),
        "max_courant_seen": (
            max_courant_seen
        ),
        "execution_time_s": (
            execution_times[-1]
            if execution_times
            else None
        ),
    }



# ============================================================
# PARALLEL EXECUTION HELPERS
# ============================================================


def _normalize_mpi_ranks(
    mpi_ranks: int | None,
) -> int:
    """
    Resolve requested MPI ranks.

    Explicit argument wins. Otherwise OPENFOAM_MPI_RANKS can be used.
    Serial execution remains the compatibility default.
    """

    if mpi_ranks is None:
        raw = os.getenv(
            "OPENFOAM_MPI_RANKS",
            "1",
        )

        try:
            mpi_ranks = int(raw)
        except ValueError as exc:
            raise ValueError(
                "OPENFOAM_MPI_RANKS must be an integer."
            ) from exc

    ranks = int(mpi_ranks)

    if ranks < 1:
        raise ValueError(
            "mpi_ranks must be >= 1."
        )

    return ranks


def _decompose_par_dict_text(
    mpi_ranks: int,
) -> str:
    ranks = _normalize_mpi_ranks(
        mpi_ranks
    )

    if ranks == 1:
        raise ValueError(
            "decomposeParDict is only needed "
            "for mpi_ranks > 1."
        )

    return f"""FoamFile
{{
    format      ascii;
    class       dictionary;
    object      decomposeParDict;
}}

numberOfSubdomains {ranks};

method          scotch;
"""


def _write_decompose_par_dict(
    case_dir: Path,
    mpi_ranks: int,
) -> Path | None:
    ranks = _normalize_mpi_ranks(
        mpi_ranks
    )

    if ranks == 1:
        return None

    path = (
        case_dir
        / "system"
        / "decomposeParDict"
    )

    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    path.write_text(
        _decompose_par_dict_text(
            ranks
        ),
        encoding="utf-8",
    )

    return path


def _solver_launch_command(
    *,
    mpi_ranks: int,
    solver_timeout_s: int,
) -> str:
    """
    Build the solver command executed inside WSL.

    GNU timeout runs *inside* WSL so timeout handling terminates
    the Linux solver/MPI job rather than merely killing wsl.exe
    on the Windows side.
    """

    ranks = _normalize_mpi_ranks(
        mpi_ranks
    )

    timeout_s = max(
        1,
        int(solver_timeout_s),
    )

    if ranks == 1:
        application = "foamRun"
    else:
        application = (
            f"mpirun -np {ranks} "
            "foamRun -parallel"
        )

    return (
        "timeout "
        "--signal=TERM "
        "--kill-after=20s "
        f"{timeout_s}s "
        f"{application}"
    )


def _solver_timed_out(
    return_code: int,
) -> bool:
    return int(return_code) == 124


# ============================================================
# PREFLIGHT
# ============================================================


def check_openfoam_environment(
    timeout: int = 30,
    mpi_ranks: int | None = None,
) -> dict[str, Any]:
    """
    Verify WSL/OpenFOAM tools before touching the generated case.

    For mpi_ranks > 1, parallel decomposition, reconstruction and
    OpenMPI are checked as part of the same preflight.
    """

    ranks = _normalize_mpi_ranks(
        mpi_ranks
    )

    bashrc = shlex.quote(
        OPENFOAM_BASHRC
    )

    tools = [
        "gmshToFoam",
        "checkMesh",
        "setFields",
        "foamRun",
        "timeout",
    ]

    if ranks > 1:
        tools.extend(
            [
                "decomposePar",
                "reconstructPar",
                "mpirun",
            ]
        )

    checks = " ".join(
        f"&& command -v {tool}"
        for tool in tools
    )

    command = (
        f'test -f {bashrc} '
        f'&& . {bashrc} '
        f'{checks}'
    )

    proc = _run_wsl_bash(
        command=command,
        timeout=timeout,
    )

    return {
        "ok": (
            proc.returncode
            == 0
        ),
        "return_code": (
            proc.returncode
        ),
        "distro": (
            OPENFOAM_DISTRO
        ),
        "bashrc": (
            OPENFOAM_BASHRC
        ),
        "mpi_ranks": ranks,
        "parallel": (
            ranks > 1
        ),
        "stdout": (
            proc.stdout
            or ""
        ),
        "stderr": (
            proc.stderr
            or ""
        ),
    }


# ============================================================
# OPENFOAM EXECUTION
# ============================================================


def run_openfoam_case(
    case_dir: Path,
    *,
    run_solver: bool = True,
    stage_timeout_s: int = 120,
    conversion_timeout_s: int = 120,
    checkmesh_timeout_s: int = 120,
    solver_timeout_s: int = 900,
    mpi_ranks: int | None = None,
) -> dict[str, Any]:
    """
    Execute an already generated OpenFOAM case through WSL.

    Physics and numerics are defined by the case dictionaries.
    mpi_ranks controls only execution parallelism:

        1      -> serial foamRun
        >1     -> decomposePar + MPI foamRun + reconstructPar

    A solver wall-clock timeout is reported separately from a
    numerical solver failure.
    """

    case_dir = (
        case_dir
        .resolve()
    )

    ranks = _normalize_mpi_ranks(
        mpi_ranks
    )

    parallel = (
        ranks > 1
    )

    if not case_dir.exists():
        raise FileNotFoundError(
            f"OpenFOAM case does not exist: "
            f"{case_dir}"
        )

    mesh_file = (
        case_dir
        / "mesh.msh"
    )

    native_poly_mesh = (
        case_dir
        / "constant"
        / "polyMesh"
    )

    required_native_mesh_files = (
        "points",
        "faces",
        "owner",
        "neighbour",
        "boundary",
    )

    has_native_poly_mesh = (
        native_poly_mesh.is_dir()
        and all(
            (
                native_poly_mesh
                / name
            ).exists()
            for name
            in required_native_mesh_files
        )
    )

    using_native_poly_mesh = (
        (not mesh_file.exists())
        and has_native_poly_mesh
    )

    if (
        not mesh_file.exists()
        and not has_native_poly_mesh
    ):
        raise FileNotFoundError(
            "OpenFOAM case has neither mesh.msh nor "
            "a complete constant/polyMesh: "
            f"{case_dir}"
        )

    # Write decomposition policy before staging the case into WSL.
    _write_decompose_par_dict(
        case_dir,
        ranks,
    )

    # --------------------------------------------------------
    # 1. PREFLIGHT
    # --------------------------------------------------------

    preflight = (
        check_openfoam_environment(
            mpi_ranks=ranks,
        )
    )

    if not preflight[
        "ok"
    ]:
        summary = {
            "status": (
                "openfoam_environment_failed"
            ),
            "preflight": (
                preflight
            ),
            "run_solver_requested": (
                run_solver
            ),
            "execution_mode": {
                "parallel": parallel,
                "mpi_ranks": ranks,
            },
        }

        _save_summary(
            case_dir,
            summary,
        )

        raise RuntimeError(
            "OpenFOAM/WSL preflight failed. "
            "See openfoam_execution_summary.json."
        )

    # --------------------------------------------------------
    # WSL PATHS
    # --------------------------------------------------------

    case_wsl = (
        windows_path_to_wsl(
            case_dir
        )
    )

    runtime_name = (
        "physics_constrained_cfd_"
        "openfoam_runtime"
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

    bashrc = shlex.quote(
        OPENFOAM_BASHRC
    )

    # --------------------------------------------------------
    # 2. STAGE INTO LINUX FILESYSTEM
    # --------------------------------------------------------

    stage_script = (
        f'rm -rf "{runtime_expr}" '
        f'&& mkdir -p "{runtime_expr}" '
        f'&& cp -r '
        f'{quoted_case_source} '
        f'"{runtime_expr}/"'
    )

    stage = _run_wsl_bash(
        command=stage_script,
        timeout=stage_timeout_s,
    )

    stage_log = _write_log(
        case_dir,
        "log.stageToWSL",
        stage,
    )

    rc_stage = (
        stage.returncode
    )

    # Defaults for later stages.
    rc_convert = 99
    rc_wall_fix = 99
    rc_check = 99
    rc_initialize = 99
    rc_decompose = (
        99
        if parallel
        else 0
    )
    rc_solver = 99
    rc_reconstruct = (
        99
        if parallel
        else 0
    )
    rc_sync = 99

    conversion_log = ""
    wall_fix_log = ""
    check_log = ""
    initialize_log = ""
    decompose_log = ""
    solver_log = ""
    reconstruct_log = ""
    sync_log = ""

    # --------------------------------------------------------
    # 3. GMSH -> OPENFOAM
    # --------------------------------------------------------

    if rc_stage == 0:
        convert_command = (
            f'. {bashrc} '
            f'&& cd "{runtime_expr}" '
            '&& if [ -f mesh.msh ]; then '
            'echo "Mesh source: mesh.msh"; '
            'gmshToFoam mesh.msh; '
            'elif [ -d constant/polyMesh ]; then '
            'echo "Mesh source: existing constant/polyMesh"; '
            'echo "gmshToFoam skipped for native OpenFOAM continuation"; '
            'else '
            'echo "No valid mesh source found" >&2; '
            'exit 42; '
            'fi'
        )

        convert = _run_wsl_bash(
            command=convert_command,
            timeout=conversion_timeout_s,
        )

        rc_convert = (
            convert.returncode
        )

        conversion_log = _write_log(
            case_dir,
            "log.gmshToFoam",
            convert,
        )

    # --------------------------------------------------------
    # 4. WALL PATCH TYPE FIX
    # --------------------------------------------------------

    if rc_convert == 0:
        wall_fix_command = (
            f'cd "{runtime_expr}" '
            "&& "
            "sed -i "
            "'/^[[:space:]]*walls[[:space:]]*$/,"
            "/^[[:space:]]*}/ "
            "s/^[[:space:]]*type[[:space:]]*patch;/"
            "        type            wall;/' "
            "constant/polyMesh/boundary "
            "&& "
            "grep -A6 "
            "'^[[:space:]]*walls[[:space:]]*$' "
            "constant/polyMesh/boundary"
        )

        wall_fix = _run_wsl_bash(
            command=wall_fix_command,
            timeout=30,
        )

        rc_wall_fix = (
            wall_fix.returncode
        )

        wall_fix_log = _write_log(
            case_dir,
            "log.wallPatchFix",
            wall_fix,
        )

    # --------------------------------------------------------
    # 5. CHECKMESH
    # --------------------------------------------------------

    if (
        rc_convert == 0
        and rc_wall_fix == 0
    ):
        check_command = (
            f'. {bashrc} '
            f'&& cd "{runtime_expr}" '
            '&& checkMesh'
        )

        check = _run_wsl_bash(
            command=check_command,
            timeout=checkmesh_timeout_s,
        )

        rc_check = (
            check.returncode
        )

        check_log = _write_log(
            case_dir,
            "log.checkMesh",
            check,
        )

    check_metrics = (
        parse_checkmesh(
            check_log
        )
    )

    check_passed = (
        rc_check == 0
        and bool(
            check_metrics[
                "mesh_ok"
            ]
        )
    )

    # --------------------------------------------------------
    # 6A. OPTIONAL SETFIELDS INITIALIZATION
    # --------------------------------------------------------
    #
    # Run setFields in the undecomposed case first.  Parallel
    # decomposition then receives the initialized latest state.
    # --------------------------------------------------------

    if (
        check_passed
        and run_solver
    ):
        initialize_command = (
            f'. {bashrc} '
            f'&& cd "{runtime_expr}" '
            '&& if [ -f system/setFieldsDict ]; '
            'then echo "Applying setFields initialization"; '
            'setFields; '
            'else echo "No setFields initialization requested"; '
            'fi'
        )

        initialize = _run_wsl_bash(
            command=initialize_command,
            timeout=stage_timeout_s,
        )

        rc_initialize = (
            initialize.returncode
        )

        initialize_log = _write_log(
            case_dir,
            "log.setFields",
            initialize,
        )

    elif check_passed:
        rc_initialize = 0

    # --------------------------------------------------------
    # 6B. MPI DOMAIN DECOMPOSITION
    # --------------------------------------------------------

    if (
        check_passed
        and run_solver
        and rc_initialize == 0
        and parallel
    ):
        decompose_command = (
            f'. {bashrc} '
            f'&& cd "{runtime_expr}" '
            '&& rm -rf processor* processors '
            '&& decomposePar -force -latestTime'
        )

        decompose = _run_wsl_bash(
            command=decompose_command,
            timeout=max(
                stage_timeout_s,
                180,
            ),
        )

        rc_decompose = (
            decompose.returncode
        )

        decompose_log = _write_log(
            case_dir,
            "log.decomposePar",
            decompose,
        )

    # --------------------------------------------------------
    # 6C. SOLVER
    # --------------------------------------------------------

    prep_ok = (
        check_passed
        and rc_initialize == 0
        and (
            (not parallel)
            or rc_decompose == 0
        )
    )

    if (
        prep_ok
        and run_solver
    ):
        solver_command = (
            f'. {bashrc} '
            f'&& cd "{runtime_expr}" '
            '&& '
            + _solver_launch_command(
                mpi_ranks=ranks,
                solver_timeout_s=(
                    solver_timeout_s
                ),
            )
        )

        # Inner GNU timeout owns Linux-side termination.
        # The larger outer guard only protects against a broken WSL shell.
        solver = _run_wsl_bash(
            command=solver_command,
            timeout=(
                max(
                    1,
                    int(solver_timeout_s),
                )
                + 60
            ),
        )

        rc_solver = (
            solver.returncode
        )

        solver_log = _write_log(
            case_dir,
            "log.foamRun",
            solver,
        )

    elif check_passed and not run_solver:
        rc_solver = 0

    # --------------------------------------------------------
    # 6D. RECONSTRUCT PARALLEL RESULTS
    # --------------------------------------------------------
    #
    # Reconstruct new written times even after a timeout/failure.
    # That preserves the latest valid solver state for diagnostics.
    # --------------------------------------------------------

    if (
        parallel
        and run_solver
        and rc_decompose == 0
    ):
        reconstruct_command = (
            f'. {bashrc} '
            f'&& cd "{runtime_expr}" '
            '&& reconstructPar -newTimes'
        )

        reconstruct = _run_wsl_bash(
            command=reconstruct_command,
            timeout=max(
                stage_timeout_s,
                300,
            ),
        )

        rc_reconstruct = (
            reconstruct.returncode
        )

        reconstruct_log = _write_log(
            case_dir,
            "log.reconstructPar",
            reconstruct,
        )

    # --------------------------------------------------------
    # 7. COPY RUNTIME CASE BACK TO WINDOWS
    # --------------------------------------------------------

    if rc_stage == 0:
        sync_command = (
            f'cp -r '
            f'"{runtime_expr}/." '
            f'{quoted_case_destination}'
        )

        sync = _run_wsl_bash(
            command=sync_command,
            timeout=stage_timeout_s,
        )

        rc_sync = (
            sync.returncode
        )

        sync_log = _write_log(
            case_dir,
            "log.syncFromWSL",
            sync,
        )

    # --------------------------------------------------------
    # 8. SUMMARY
    # --------------------------------------------------------

    solver_metrics = (
        parse_solver_log(
            solver_log
        )
        if run_solver
        else {
            "completed": False,
            "skipped": True,
        }
    )

    timed_out = (
        run_solver
        and _solver_timed_out(
            rc_solver
        )
    )

    solver_metrics[
        "timed_out"
    ] = bool(
        timed_out
    )

    solver_metrics[
        "return_code"
    ] = rc_solver

    solver_metrics[
        "parallel"
    ] = parallel

    solver_metrics[
        "mpi_ranks"
    ] = ranks

    conversion_ok = (
        rc_convert == 0
        and "FOAM FATAL"
        not in conversion_log
    )

    wall_patch_ok = (
        rc_wall_fix == 0
        and (
            using_native_poly_mesh
            or "type            wall;"
            in wall_fix_log
        )
    )

    parallel_ok = (
        (
            not parallel
        )
        or (
            rc_decompose == 0
            and rc_reconstruct == 0
        )
    )

    solver_ok = (
        (
            not run_solver
        )
        or (
            rc_solver == 0
            and bool(
                solver_metrics.get(
                    "completed",
                    False,
                )
            )
        )
    )

    overall_ok = all(
        [
            rc_stage == 0,
            conversion_ok,
            wall_patch_ok,
            check_passed,
            rc_initialize == 0,
            parallel_ok,
            solver_ok,
            rc_sync == 0,
        ]
    )

    if overall_ok:
        status = (
            "solver_completed"
            if run_solver
            else "mesh_check_completed"
        )

    elif not check_passed:
        status = (
            "mesh_validation_failed"
        )

    elif timed_out:
        status = (
            "solver_timed_out"
        )

    elif (
        parallel
        and rc_decompose != 0
    ):
        status = (
            "parallel_decomposition_failed"
        )

    elif (
        parallel
        and rc_reconstruct != 0
    ):
        status = (
            "parallel_reconstruction_failed"
        )

    elif run_solver:
        status = (
            "solver_failed_or_incomplete"
        )

    else:
        status = (
            "execution_failed"
        )

    summary = {
        "status": status,
        "overall_ok": (
            overall_ok
        ),
        "run_solver_requested": (
            run_solver
        ),
        "execution_mode": {
            "parallel": parallel,
            "mpi_ranks": ranks,
        },
        "openfoam": {
            "distro": (
                OPENFOAM_DISTRO
            ),
            "bashrc": (
                OPENFOAM_BASHRC
            ),
            "runtime_case": (
                f"$HOME/{runtime_name}"
            ),
        },
        "return_codes": {
            "stage": (
                rc_stage
            ),
            "gmshToFoam": (
                rc_convert
            ),
            "wall_patch_fix": (
                rc_wall_fix
            ),
            "checkMesh": (
                rc_check
            ),
            "setFields": (
                rc_initialize
            ),
            "decomposePar": (
                rc_decompose
            ),
            "foamRun": (
                rc_solver
            ),
            "reconstructPar": (
                rc_reconstruct
            ),
            "sync_back": (
                rc_sync
            ),
        },
        "conversion_ok": (
            conversion_ok
        ),
        "wall_patch_ok": (
            wall_patch_ok
        ),
        "check_mesh": (
            check_metrics
        ),
        "solver": (
            solver_metrics
        ),
        "logs": {
            "stage": (
                "log.stageToWSL"
            ),
            "gmshToFoam": (
                "log.gmshToFoam"
            ),
            "wall_patch_fix": (
                "log.wallPatchFix"
            ),
            "checkMesh": (
                "log.checkMesh"
            ),
            "setFields": (
                "log.setFields"
                if run_solver
                else None
            ),
            "decomposePar": (
                "log.decomposePar"
                if parallel
                else None
            ),
            "foamRun": (
                "log.foamRun"
                if run_solver
                else None
            ),
            "reconstructPar": (
                "log.reconstructPar"
                if parallel
                else None
            ),
            "sync_back": (
                "log.syncFromWSL"
            ),
        },
        "tails": {
            "stage": (
                stage_log[
                    -1500:
                ]
            ),
            "gmshToFoam": (
                conversion_log[
                    -1500:
                ]
            ),
            "wall_patch_fix": (
                wall_fix_log[
                    -1500:
                ]
            ),
            "checkMesh": (
                check_log[
                    -2000:
                ]
            ),
            "setFields": (
                initialize_log[
                    -1500:
                ]
            ),
            "decomposePar": (
                decompose_log[
                    -2000:
                ]
            ),
            "foamRun": (
                solver_log[
                    -3000:
                ]
            ),
            "reconstructPar": (
                reconstruct_log[
                    -2000:
                ]
            ),
            "sync_back": (
                sync_log[
                    -1500:
                ]
            ),
        },
    }

    _save_summary(
        case_dir,
        summary,
    )

    status_text = (
        f"stage={rc_stage}\n"
        f"convert={rc_convert}\n"
        f"wallPatchFix={rc_wall_fix}\n"
        f"checkMesh={rc_check}\n"
        f"setFields={rc_initialize}\n"
        f"decomposePar={rc_decompose}\n"
        f"solver={rc_solver}\n"
        f"reconstructPar={rc_reconstruct}\n"
        f"sync={rc_sync}\n"
        f"parallel={parallel}\n"
        f"mpiRanks={ranks}\n"
        f"timedOut={timed_out}\n"
    )

    (
        case_dir
        / "openfoam_status.txt"
    ).write_text(
        status_text,
        encoding="utf-8",
    )

    return summary


# ============================================================
# SUMMARY
# ============================================================


def _save_summary(
    case_dir: Path,
    summary: dict[str, Any],
) -> None:
    (
        case_dir
        / "openfoam_execution_summary.json"
    ).write_text(
        json.dumps(
            summary,
            indent=2,
        ),
        encoding="utf-8",
    )

