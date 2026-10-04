"""Legacy prototype (CAD->Gmsh path, paper Appendix C "Prototype before the
registered contracts"); not the registered nozzle family; not used for any
reported result except that prototype record.

Prototype run supervisor. Not imported by the registered family runners or by
src/pipeline.
"""
from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from typing import Any

from src.openfoam.executor import (
    run_openfoam_case,
)


def _positive_times(
    case_dir: Path,
) -> list[float]:

    result: list[float] = []

    for item in case_dir.iterdir():

        if not item.is_dir():
            continue

        try:
            value = float(
                item.name
            )
        except ValueError:
            continue

        if value > 0.0:
            result.append(
                value
            )

    return sorted(
        result
    )


def _read_scalar(
    path: Path,
    key: str,
) -> float:

    text = path.read_text(
        encoding="utf-8",
    )

    match = re.search(
        rf"(?m)^\s*{re.escape(key)}"
        rf"\s+([0-9.eE+\-]+)\s*;",
        text,
    )

    if match is None:
        raise RuntimeError(
            f"Could not read {key} "
            f"from {path}."
        )

    return float(
        match.group(1)
    )


def _patch_control(
    case_dir: Path,
    *,
    start_from: str,
    end_time: float,
    initial_dt: float,
    max_dt: float,
    max_co: float,
) -> None:

    path = (
        case_dir
        / "system"
        / "controlDict"
    )

    text = path.read_text(
        encoding="utf-8",
    )

    entries = {
        "startFrom": start_from,
        "endTime": f"{end_time:.12g}",
        "deltaT": f"{initial_dt:.12g}",
        "maxDeltaT": f"{max_dt:.12g}",
        "maxCo": f"{max_co:.12g}",
    }

    for key, value in entries.items():

        pattern = (
            rf"(?m)^\s*"
            rf"{re.escape(key)}"
            rf"\s+[^;]+;"
        )

        text, count = re.subn(
            pattern,
            f"{key:<16}{value};",
            text,
            count=1,
        )

        if count != 1:
            raise RuntimeError(
                f"Could not patch {key} "
                "in controlDict."
            )

    path.write_text(
        text,
        encoding="utf-8",
    )


def _restore(
    source: Path,
    destination: Path,
) -> None:

    if destination.exists():
        shutil.rmtree(
            destination
        )

    shutil.copytree(
        source,
        destination,
    )


def _same_failure_time(
    a: float | None,
    b: float | None,
) -> bool:

    if a is None or b is None:
        return False

    a = float(a)
    b = float(b)

    tolerance = max(
        5.0e-6,
        0.02 * max(abs(a), abs(b)),
    )

    return abs(a - b) <= tolerance



def _is_wall_clock_timeout(
    summary: dict[str, Any],
) -> bool:
    return bool(
        summary.get(
            "status"
        ) == "solver_timed_out"
        or summary.get(
            "solver",
            {},
        ).get(
            "timed_out",
            False,
        )
    )


def _return_wall_clock_timeout(
    *,
    case_dir: Path,
    supervisor: dict[str, Any],
    summary: dict[str, Any],
    phase: str,
) -> dict[str, Any]:
    """
    A healthy-but-slow run must not trigger timestep reduction.

    Reducing dt after a wall-clock timeout makes the next attempt slower
    and confounds numerical-stability diagnosis.
    """

    supervisor[
        "result"
    ] = "WALL_CLOCK_TIMEOUT"

    supervisor[
        "timeout_phase"
    ] = phase

    supervisor[
        "recommended_recovery_class"
    ] = (
        "CONTINUE_SAME_NUMERICS_OR_EXTEND_WALL_CLOCK"
    )

    summary[
        "stability_supervisor"
    ] = supervisor

    _save_supervisor(
        case_dir,
        supervisor,
    )

    return summary


def _save_supervisor(
    case_dir: Path,
    payload: dict[str, Any],
) -> None:

    (
        case_dir
        / "stability_supervisor_summary.json"
    ).write_text(
        json.dumps(
            payload,
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )


def run_supervised_openfoam_case(
    case_dir: Path,
    *,
    run_solver: bool = True,
    solver_timeout_s: int = 900,
    **kwargs,
) -> dict[str, Any]:

    case_dir = (
        Path(case_dir)
        .resolve()
    )

    if not run_solver:
        return run_openfoam_case(
            case_dir=case_dir,
            run_solver=False,
            solver_timeout_s=(
                solver_timeout_s
            ),
            **kwargs,
        )

    control = (
        case_dir
        / "system"
        / "controlDict"
    )

    target_end = (
        _read_scalar(
            control,
            "endTime",
        )
    )

    has_setfields = (
        case_dir
        / "system"
        / "setFieldsDict"
    ).exists()

    existing_times = (
        _positive_times(
            case_dir
        )
    )

    supervisor: dict[str, Any] = {
        "mode": None,
        "attempts": [],
        "target_end_time": target_end,
    }

    # ========================================================
    # FRESH CASE
    # ========================================================

    if (
        has_setfields
        and not existing_times
    ):

        supervisor[
            "mode"
        ] = "controlled_startup_then_continuation"

        clean_checkpoint = (
            case_dir.parent
            / (
                case_dir.name
                + "_clean_checkpoint"
            )
        )

        startup_checkpoint = (
            case_dir.parent
            / (
                case_dir.name
                + "_startup_checkpoint"
            )
        )

        if clean_checkpoint.exists():
            shutil.rmtree(
                clean_checkpoint
            )

        shutil.copytree(
            case_dir,
            clean_checkpoint,
        )

        startup_end = min(
            target_end,
            max(
                2.0e-5,
                min(
                    1.0e-4,
                    0.20
                    * target_end,
                ),
            ),
        )

        startup_schedules = [
            (0.03, 2.0e-8),
            (0.015, 1.0e-8),
            (0.0075, 5.0e-9),
        ]

        startup_summary = None
        successful_startup_schedule = None

        for index, (
            max_co,
            max_dt,
        ) in enumerate(
            startup_schedules,
            start=1,
        ):

            _restore(
                clean_checkpoint,
                case_dir,
            )

            _patch_control(
                case_dir,
                start_from="startTime",
                end_time=startup_end,
                initial_dt=1.0e-9,
                max_dt=max_dt,
                max_co=max_co,
            )

            print()
            print(
                f"STABILITY SUPERVISOR STARTUP "
                f"{index}/{len(startup_schedules)}"
            )

            print(
                "maxCo:",
                max_co,
                "maxDeltaT:",
                max_dt,
            )

            summary = (
                run_openfoam_case(
                    case_dir=case_dir,
                    run_solver=True,
                    solver_timeout_s=(
                        solver_timeout_s
                    ),
                    **kwargs,
                )
            )

            supervisor[
                "attempts"
            ].append(
                {
                    "phase": "startup",
                    "attempt": index,
                    "max_co": max_co,
                    "max_dt": max_dt,
                    "status": summary.get(
                        "status"
                    ),
                    "last_time": (
                        summary
                        .get(
                            "solver",
                            {},
                        )
                        .get(
                            "last_time"
                        )
                    ),
                }
            )

            if _is_wall_clock_timeout(
                summary
            ):
                return _return_wall_clock_timeout(
                    case_dir=case_dir,
                    supervisor=supervisor,
                    summary=summary,
                    phase="startup",
                )

            if summary.get(
                "overall_ok",
                False,
            ):

                startup_summary = (
                    summary
                )

                successful_startup_schedule = (
                    max_co,
                    max_dt,
                )

                break

        if startup_summary is None:

            supervisor[
                "result"
            ] = "STARTUP_FAILED"

            _save_supervisor(
                case_dir,
                supervisor,
            )

            return summary

        if startup_checkpoint.exists():
            shutil.rmtree(
                startup_checkpoint
            )

        shutil.copytree(
            case_dir,
            startup_checkpoint,
        )

        if (
            startup_end
            >= target_end
        ):

            supervisor[
                "result"
            ] = "COMPLETED"

            startup_summary[
                "stability_supervisor"
            ] = supervisor

            _save_supervisor(
                case_dir,
                supervisor,
            )

            return startup_summary

        assert successful_startup_schedule is not None

        safe_max_co, safe_max_dt = (
            successful_startup_schedule
        )

        # Reliability-first continuation:
        # continue with the settings that actually survived startup.
        # If that fails, perform ONE rollback/reduction experiment.
        continuation_schedules = [
            (safe_max_co, safe_max_dt),
            (
                0.5 * safe_max_co,
                0.5 * safe_max_dt,
            ),
        ]

        final_summary = None
        continuation_failure_times: list[float | None] = []

        for index, (
            max_co,
            max_dt,
        ) in enumerate(
            continuation_schedules,
            start=1,
        ):

            _restore(
                startup_checkpoint,
                case_dir,
            )

            setfields = (
                case_dir
                / "system"
                / "setFieldsDict"
            )

            if setfields.exists():
                setfields.unlink()

            _patch_control(
                case_dir,
                start_from="latestTime",
                end_time=target_end,
                initial_dt=min(
                    1.0e-8,
                    max_dt,
                ),
                max_dt=max_dt,
                max_co=max_co,
            )

            print()
            print(
                f"STABILITY SUPERVISOR CONTINUATION "
                f"{index}/{len(continuation_schedules)}"
            )

            print(
                "maxCo:",
                max_co,
                "maxDeltaT:",
                max_dt,
            )

            summary = (
                run_openfoam_case(
                    case_dir=case_dir,
                    run_solver=True,
                    solver_timeout_s=(
                        solver_timeout_s
                    ),
                    **kwargs,
                )
            )

            supervisor[
                "attempts"
            ].append(
                {
                    "phase": "continuation",
                    "attempt": index,
                    "max_co": max_co,
                    "max_dt": max_dt,
                    "status": summary.get(
                        "status"
                    ),
                    "last_time": (
                        summary
                        .get(
                            "solver",
                            {},
                        )
                        .get(
                            "last_time"
                        )
                    ),
                }
            )

            final_summary = (
                summary
            )

            if _is_wall_clock_timeout(
                summary
            ):
                return _return_wall_clock_timeout(
                    case_dir=case_dir,
                    supervisor=supervisor,
                    summary=summary,
                    phase="continuation",
                )

            if not summary.get(
                "overall_ok",
                False,
            ):
                continuation_failure_times.append(
                    summary
                    .get("solver", {})
                    .get("last_time")
                )

            if summary.get(
                "overall_ok",
                False,
            ):
                break

        assert (
            final_summary
            is not None
        )

        if final_summary.get(
            "overall_ok",
            False,
        ):
            supervisor["result"] = "COMPLETED"

        elif (
            len(continuation_failure_times) >= 2
            and _same_failure_time(
                continuation_failure_times[-2],
                continuation_failure_times[-1],
            )
        ):
            supervisor[
                "result"
            ] = "TIMESTEP_REDUCTION_NOT_EFFECTIVE"
            supervisor[
                "recommended_recovery_class"
            ] = "SOLVER_OR_STARTUP_BACKEND_CHANGE"

        else:
            supervisor["result"] = "CONTINUATION_FAILED"

        final_summary[
            "stability_supervisor"
        ] = supervisor

        _save_supervisor(
            case_dir,
            supervisor,
        )

        return final_summary

    # ========================================================
    # EXISTING / CONTINUATION CASE
    # ========================================================

    supervisor[
        "mode"
    ] = "continuation_recovery"

    checkpoint = (
        case_dir.parent
        / (
            case_dir.name
            + "_continuation_checkpoint"
        )
    )

    if checkpoint.exists():
        shutil.rmtree(
            checkpoint
        )

    shutil.copytree(
        case_dir,
        checkpoint,
    )

    try:
        base_max_co = (
            _read_scalar(
                control,
                "maxCo",
            )
        )
    except Exception:
        base_max_co = 0.03

    try:
        base_max_dt = (
            _read_scalar(
                control,
                "maxDeltaT",
            )
        )
    except Exception:
        base_max_dt = 2.0e-8

    schedules = [
        (base_max_co, base_max_dt),
        (0.5 * base_max_co, 0.5 * base_max_dt),
    ]

    final_summary = None
    recovery_failure_times: list[float | None] = []

    for index, (
        max_co,
        max_dt,
    ) in enumerate(
        schedules,
        start=1,
    ):

        _restore(
            checkpoint,
            case_dir,
        )

        setfields = (
            case_dir
            / "system"
            / "setFieldsDict"
        )

        if setfields.exists():
            setfields.unlink()

        _patch_control(
            case_dir,
            start_from="latestTime",
            end_time=target_end,
            initial_dt=min(
                1.0e-8,
                max_dt,
            ),
            max_dt=max_dt,
            max_co=max_co,
        )

        print()
        print(
            f"STABILITY RECOVERY "
            f"{index}/{len(schedules)}"
        )

        summary = run_openfoam_case(
            case_dir=case_dir,
            run_solver=True,
            solver_timeout_s=(
                solver_timeout_s
            ),
            **kwargs,
        )

        supervisor[
            "attempts"
        ].append(
            {
                "phase": "recovery",
                "attempt": index,
                "max_co": max_co,
                "max_dt": max_dt,
                "status": summary.get(
                    "status"
                ),
                "last_time": (
                    summary
                    .get(
                        "solver",
                        {},
                    )
                    .get(
                        "last_time"
                    )
                ),
            }
        )

        final_summary = summary

        if _is_wall_clock_timeout(
            summary
        ):
            return _return_wall_clock_timeout(
                case_dir=case_dir,
                supervisor=supervisor,
                summary=summary,
                phase="recovery",
            )

        if not summary.get(
            "overall_ok",
            False,
        ):
            recovery_failure_times.append(
                summary
                .get("solver", {})
                .get("last_time")
            )

        if summary.get(
            "overall_ok",
            False,
        ):
            break

    assert (
        final_summary
        is not None
    )

    if final_summary.get(
        "overall_ok",
        False,
    ):
        supervisor["result"] = "COMPLETED"

    elif (
        len(recovery_failure_times) >= 2
        and _same_failure_time(
            recovery_failure_times[-2],
            recovery_failure_times[-1],
        )
    ):
        supervisor[
            "result"
        ] = "TIMESTEP_REDUCTION_NOT_EFFECTIVE"
        supervisor[
            "recommended_recovery_class"
        ] = "SOLVER_OR_STARTUP_BACKEND_CHANGE"

    else:
        supervisor["result"] = "RECOVERY_FAILED"

    final_summary[
        "stability_supervisor"
    ] = supervisor

    _save_supervisor(
        case_dir,
        supervisor,
    )

    return final_summary
