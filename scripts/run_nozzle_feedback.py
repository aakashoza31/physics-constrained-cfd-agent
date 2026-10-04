#!/usr/bin/env python3
"""Closed-loop LLM CFD agent for the registered internal-nozzle family.

Loop:
  solve -> deterministic diagnostics -> native-field images -> LLM reasoning
  -> deterministic action guard -> execute approved action -> repeat.

The LLM selects the high-level action.  Deterministic code owns mesh validity,
thermodynamic admissibility, conservation/stationarity checks, action bounds,
OpenFOAM edits, and final acceptance.
"""
from __future__ import annotations

import argparse
import json
import re
import shlex
import shutil
import subprocess
import sys
import time
from dataclasses import asdict
from pathlib import Path, PurePosixPath
from typing import Any, Dict, List, Optional, Tuple

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scripts.run_nozzle_e2e import (  # noqa: E402
    CASE_LABELS,
    mesh_step_evidence,
    parse_check_mesh,
    problem_from_spec,
    save_json,
)
from src.agents.llm_provenance import LLMUnavailable  # noqa: E402
from src.agents.nozzle_demo_agents import review_mesh_evidence, summarize_case  # noqa: E402
from src.contracts.agent_decision import AgentAction  # noqa: E402
from src.pipeline.foam_runtime import FoamRuntime, FoamRuntimeError  # noqa: E402
from src.pipeline.nozzle.feedback import (  # noqa: E402
    configure_continuation_text,
    manifest_with_end_time,
    refined_spec,
)
from src.pipeline.nozzle.feedback_diagnostics import (  # noqa: E402
    analyze_axial_profile,
    augment_evidence,
    fulfill_diagnostic_request,
    render_native_field_images,
)
from src.pipeline.nozzle.spec import NozzleCaseSpec  # noqa: E402
from src.reasoning.evidence_packet import assert_theory_blind_payload  # noqa: E402
from src.reasoning.nozzle_diagnosis import diagnose  # noqa: E402
from src.reasoning.nozzle_scope_gate import evaluate_scope  # noqa: E402
from src.reasoning.reference_evidence_adapter import (  # noqa: E402
    build_evidence_from_validation,
    withheld_from_agent,
)


DEFAULT_TARGET_END_TIME = 0.006
DEFAULT_MAX_END_TIME = 0.020
DEFAULT_DEMO_FIRST_END_TIME = 0.001


def emit(tag: str, message: str) -> None:
    stamp = time.strftime("%H:%M:%S")
    print(f"[{stamp}] [{tag}] {message}", flush=True)


def _read_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _failed_checks(validation: Dict[str, Any], *, hide_theory: bool = False) -> List[str]:
    return [
        k
        for k, v in validation.get("checks", {}).items()
        if not v and not (hide_theory and k == "theory_consistency")
    ]


def _snapshot_iteration(case_out: Path, iteration: int) -> Path:
    target = case_out / "iterations" / f"iteration_{iteration:02d}"
    target.mkdir(parents=True, exist_ok=True)
    names = [
        "execution.json",
        "validation.json",
        "cfd_evidence.json",
        "agent_decision.json",
        "action_validation.json",
        "feedback_action_gate.json",
        "acceptance.json",
        "axial_profile.csv",
        "mesh_evidence.json",
        "llm_mesh_review.json",
        "feedback_snapshot.csv",
        "feedback_snapshot.json",
        "profile_diagnostics.json",
        "visual_observation.json",
        "diagnostic_bundle.json",
        "ENGINEERING_SUMMARY.md",
        "report_payload.json",
    ]
    for name in names:
        src = case_out / name
        if src.exists():
            shutil.copy2(src, target / name)
    log = case_out / "logs" / "log.foamRun.tail"
    if log.exists():
        shutil.copy2(log, target / "log.foamRun.tail")
    visuals = case_out / "visuals" / f"iteration_{iteration:02d}"
    if visuals.exists():
        shutil.copytree(visuals, target / "visuals", dirs_exist_ok=True)
    return target


def _history_item(
    iteration: int,
    validation: Dict[str, Any],
    decision_record: Dict[str, Any],
    action_validation: Dict[str, Any],
    *,
    visual_status: Optional[str] = None,
    profile_diagnostics: Optional[Dict[str, Any]] = None,
    note: Optional[str] = None,
) -> Dict[str, Any]:
    final = validation.get("final", {})
    item: Dict[str, Any] = {
        "iteration": iteration,
        "deterministic_status": validation.get("status"),
        "failed_checks": _failed_checks(validation, hide_theory=True),
        "time_integration": {
            "monitor_last_time_s": validation.get("monitor_last_time_s"),
            "requested_end_time_s": validation.get("requested_end_time_s"),
            "final_dt_s": validation.get("final_dt"),
            "median_dt_last_100_s": validation.get("median_dt_last_100"),
        },
        "stationarity": {
            "monitor_drift": validation.get("drift_fraction_last_2ms", {}),
            "field_l2": validation.get("field_L2_change_last_2ms", {}),
        },
        "measured": {
            "outlet_p": final.get("outlet_p"),
            "outlet_M": final.get("outlet_M"),
            "outlet_mdot": final.get("outlet_mdot"),
            "throat_M": final.get("throat_M"),
            "max_window_mismatch_pct": final.get("max_window_mismatch_pct"),
        },
        "decision": decision_record.get("decision", {}),
        "action_validation": action_validation,
        "visual_status": visual_status,
    }
    if profile_diagnostics:
        item["gradient_localization"] = {
            "strongest_gradient_region": profile_diagnostics.get(
                "strongest_gradient_region"
            ),
            "candidate_underresolved_regions": profile_diagnostics.get(
                "candidate_underresolved_regions", []
            ),
        }
    if note:
        item["note"] = note
    return item


def _runtime(args: argparse.Namespace) -> FoamRuntime:
    runtime = FoamRuntime.detect()
    if args.distro:
        runtime.distro = args.distro
    if args.bashrc:
        runtime.bashrc = args.bashrc
    info = runtime.preflight()
    if not info.get("ok"):
        raise FoamRuntimeError(str(info.get("reason") or info))
    return runtime


def _update_latest_files(
    runtime: FoamRuntime,
    case_path: PurePosixPath,
    case_out: Path,
    *,
    partial: bool = False,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    runtime.fetch(case_path / "execution.json", case_out / "execution.json")
    runtime.fetch_tail(case_path / "log.foamRun", case_out / "logs/log.foamRun.tail")
    execution = _read_json(case_out / "execution.json")

    root = case_path.parent
    partial_arg = " --partial" if partial else ""
    validated = runtime.bash(
        f"cd {shlex.quote(str(root))}/code && "
        f"python3 validate.py {shlex.quote(str(case_path))}{partial_arg}",
        timeout=1800,
    )
    got = runtime.fetch(case_path / "validation.json", case_out / "validation.json")
    runtime.fetch(case_path / "axial_profile.csv", case_out / "axial_profile.csv")
    if not got:
        raise RuntimeError(
            "validator produced no report: " + validated.stdout + validated.stderr
        )
    return execution, _read_json(case_out / "validation.json")


def _run_solver(
    runtime: FoamRuntime,
    case_path: PurePosixPath,
    case_out: Path,
    solver_timeout: float,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    root = case_path.parent
    emit("EXECUTOR", f"Running feedback CFD iteration in {case_path}")
    result = runtime.bash(
        f"cd {shlex.quote(str(root))}/code && "
        f"REFERENCE_WALL_LIMIT_S={float(solver_timeout)} "
        f"python3 -u execute.py {shlex.quote(str(case_path))} --events",
        timeout=None,
        stream_prefix="[EXECUTOR]",
    )

    # Completed runs receive authoritative full validation.  A bounded timeout
    # can still produce useful saved states, so partial validation is allowed to
    # feed the reasoning loop rather than being rhetorically erased.
    execution_path = case_path / "execution.json"
    if not runtime.fetch(execution_path, case_out / "execution.json"):
        raise RuntimeError("feedback executor produced no execution.json")
    execution = _read_json(case_out / "execution.json")
    completed = bool(result.ok and execution.get("status") == "COMPLETED")
    return _update_latest_files(
        runtime,
        case_path,
        case_out,
        partial=not completed,
    )


def _mesh_new_case(
    runtime: FoamRuntime,
    root: PurePosixPath,
    spec: NozzleCaseSpec,
    case_path: PurePosixPath,
    case_out: Path,
    *,
    allow_fallback: bool,
) -> Dict[str, Any]:
    spec_path = root / "code/feedback_case_spec.json"
    runtime.write_text(spec_path, json.dumps(spec.to_dict(), indent=2))

    built = runtime.bash(
        f"cd {shlex.quote(str(root))}/code && "
        f"python3 build.py {shlex.quote(str(case_path))} --spec {shlex.quote(str(spec_path))}",
        timeout=300,
    )
    if not built.ok:
        raise RuntimeError(f"feedback case generation failed: {built.stdout}{built.stderr}")

    meshed = runtime.bash(
        f"bash {shlex.quote(str(root))}/code/mesh_case.sh {shlex.quote(str(case_path))}",
        timeout=900,
    )

    logs_dir = case_out / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    runtime.fetch(case_path / "log.checkMesh", logs_dir / "log.checkMesh")
    runtime.fetch(case_path / "log.blockMesh", logs_dir / "log.blockMesh")
    runtime.fetch(case_path / "mesh_steps.json", case_out / "mesh_steps.json")

    steps = (
        _read_json(case_out / "mesh_steps.json")
        if (case_out / "mesh_steps.json").exists()
        else {}
    )
    check_log = (
        (logs_dir / "log.checkMesh").read_text(errors="replace")
        if (logs_dir / "log.checkMesh").exists()
        else ""
    )
    mesh = parse_check_mesh(check_log)
    mesh["axial_cells"] = sum(spec.axial_cells)
    mesh["radial_cells"] = spec.radial_cells
    mesh.update(mesh_step_evidence(steps))
    mesh["shell_returncode"] = meshed.returncode
    mesh["shell_stderr"] = meshed.stderr.strip()[-2000:]
    save_json(case_out / "mesh_evidence.json", mesh)

    mesh_gate_ok = (
        meshed.ok
        and bool(mesh.get("mesh_ok"))
        and mesh.get("environment_ok") is True
        and mesh.get("blockMesh_ok") is True
        and mesh.get("checkMesh_ran") is True
        and mesh.get("cell_centres_written") is True
        and mesh.get("cell_volumes_written") is True
    )
    if not mesh_gate_ok:
        raise RuntimeError("feedback mesh failed deterministic mesh gate")

    review, record = review_mesh_evidence(
        {
            "case_id": spec.case_id,
            "geometry_m": {
                "inlet_radius": spec.inlet_radius_m,
                "throat_radius": spec.throat_radius_m,
                "exit_radius": spec.exit_radius_m,
            },
            "reservoir": {
                "total_pressure_pa": spec.total_pressure_pa,
                "total_temperature_k": spec.total_temperature_k,
            },
        },
        mesh,
        allow_fallback=allow_fallback,
    )
    save_json(
        case_out / "llm_mesh_review.json",
        {"review": review.model_dump(), "llm_call": record.to_dict()},
    )
    emit("LLM MESH REVIEW", f"{review.next_action}: {review.assessment}")
    if review.next_action != "PROCEED_TO_CFD_SETUP":
        raise RuntimeError(f"LLM mesh review requested {review.next_action}")

    init = runtime.bash(
        f"cd {shlex.quote(str(root))}/code && "
        f"python3 initialize.py {shlex.quote(str(case_path))}",
        timeout=900,
    )
    runtime.fetch(
        case_path / "initialization_verified.json",
        case_out / "initialization_verified.json",
    )
    if not init.ok:
        raise RuntimeError(f"feedback initialization failed: {init.stdout}{init.stderr}")
    return mesh


def _continue_case(
    runtime: FoamRuntime,
    case_path: PurePosixPath,
    current_spec: NozzleCaseSpec,
    current_time: float,
    next_end_time: float,
) -> NozzleCaseSpec:
    control_path = case_path / "system/controlDict"
    manifest_path = case_path / "manifest.json"
    control = runtime.read_text(control_path)
    manifest = json.loads(runtime.read_text(manifest_path))

    runtime.write_text(
        control_path,
        configure_continuation_text(
            control,
            current_time=current_time,
            end_time=next_end_time,
        ),
    )
    runtime.write_text(
        manifest_path,
        json.dumps(manifest_with_end_time(manifest, next_end_time), indent=2),
    )
    return NozzleCaseSpec.from_dict(
        {**current_spec.to_dict(), "end_time_s": float(next_end_time)}
    )


def _acquire_feedback_evidence(
    *,
    runtime: FoamRuntime,
    case_path: PurePosixPath,
    spec: NozzleCaseSpec,
    validation: Dict[str, Any],
    execution: Dict[str, Any],
    mesh: Dict[str, Any],
    case_out: Path,
    iteration: int,
    diagnostic_request: Optional[str],
    require_visuals: bool,
) -> Tuple[Any, Dict[str, Any]]:
    root = case_path.parent
    exported = runtime.bash(
        f"cd {shlex.quote(str(root))}/code && "
        f"python3 export_feedback_snapshot.py {shlex.quote(str(case_path))}",
        timeout=300,
    )
    if not exported.ok:
        raise RuntimeError(
            "could not export native feedback snapshot: "
            + exported.stdout
            + exported.stderr
        )

    snapshot_csv = case_out / "feedback_snapshot.csv"
    snapshot_json = case_out / "feedback_snapshot.json"
    if not runtime.fetch(case_path / "feedback_snapshot.csv", snapshot_csv):
        raise RuntimeError("feedback_snapshot.csv was not produced")
    if not runtime.fetch(case_path / "feedback_snapshot.json", snapshot_json):
        raise RuntimeError("feedback_snapshot.json was not produced")

    profile_path = case_out / "axial_profile.csv"
    profile_diag = analyze_axial_profile(
        profile_path,
        spec,
        mesh_cells=mesh.get("cells"),
    )
    save_json(case_out / "profile_diagnostics.json", profile_diag)

    visual_dir = case_out / "visuals" / f"iteration_{iteration:02d}"
    image_paths = render_native_field_images(snapshot_csv, visual_dir)
    usable_images = {
        k: v for k, v in image_paths.items() if k != "error" and Path(v).exists()
    }

    numerical_context = {
        "iteration": iteration,
        "deterministic_status": validation.get("status"),
        "failed_checks": _failed_checks(validation, hide_theory=True),
        "stationarity": validation.get("drift_fraction_last_2ms", {}),
        "field_l2": validation.get("field_L2_change_last_2ms", {}),
        "max_transient_continuity_pct": validation.get(
            "max_transient_continuity_pct"
        ),
        "profile_diagnostics": profile_diag,
        "note": "No analytical target values are included.",
    }
    from src.agents.cfd_visual_observer import observe_cfd_images

    visual_observation = observe_cfd_images(
        image_paths=usable_images,
        numerical_context=numerical_context,
    )
    save_json(case_out / "visual_observation.json", visual_observation)

    if require_visuals:
        if not usable_images:
            raise RuntimeError(
                "visual evidence was required but native-field PNGs were not created: "
                + str(image_paths)
            )
        if visual_observation.get("status") != "visual_observation_complete":
            raise RuntimeError(
                "visual evidence was required but the multimodal observer failed: "
                + str(visual_observation)
            )

    diagnostic_result = None
    if diagnostic_request:
        diagnostic_result = fulfill_diagnostic_request(
            diagnostic_request,
            validation=validation,
            execution=execution,
            mesh=mesh,
            profile_diagnostics=profile_diag,
            visual_observation=visual_observation,
        )

    evidence = build_evidence_from_validation(
        validation,
        mesh_report=mesh,
        execution=execution,
        iteration=iteration,
        case_id=spec.case_id,
    )
    evidence = augment_evidence(
        evidence,
        profile_diagnostics=profile_diag,
        image_paths=usable_images,
        visual_observation=visual_observation,
        diagnostic_request=diagnostic_request,
        diagnostic_result=diagnostic_result,
    )
    assert_theory_blind_payload(evidence.to_dict())
    save_json(case_out / "cfd_evidence.json", evidence.to_dict())

    bundle = {
        "iteration": iteration,
        "native_snapshot": _read_json(snapshot_json),
        "profile_diagnostics": profile_diag,
        "images": usable_images,
        "visual_observation": visual_observation,
        "diagnostic_request": diagnostic_request,
        "diagnostic_result": diagnostic_result,
        "theory_blind": True,
    }
    save_json(case_out / "diagnostic_bundle.json", bundle)
    return evidence, bundle


def _diagnose_iteration(
    *,
    runtime: FoamRuntime,
    case_path: PurePosixPath,
    iteration: int,
    spec: NozzleCaseSpec,
    validation: Dict[str, Any],
    execution: Dict[str, Any],
    mesh: Dict[str, Any],
    case_out: Path,
    history: List[Dict[str, Any]],
    allow_fallback: bool,
    require_visuals: bool,
    diagnostic_request: Optional[str] = None,
) -> Tuple[Any, Any, Dict[str, Any], Dict[str, Any]]:
    evidence, bundle = _acquire_feedback_evidence(
        runtime=runtime,
        case_path=case_path,
        spec=spec,
        validation=validation,
        execution=execution,
        mesh=mesh,
        case_out=case_out,
        iteration=iteration,
        diagnostic_request=diagnostic_request,
        require_visuals=require_visuals,
    )

    decision, action_validation, record = diagnose(
        problem_from_spec(spec),
        evidence,
        history=history,
        allow_fallback=allow_fallback,
    )
    decision_record = {"decision": decision.to_dict(), "llm_call": record.to_dict()}
    save_json(case_out / "agent_decision.json", decision_record)
    save_json(case_out / "action_validation.json", asdict(action_validation))

    scientific_accept_ok = validation.get("status") == "PASS_SINGLE_MESH"
    feedback_approved = bool(action_validation.approved)
    feedback_reasons = list(action_validation.reasons)
    if decision.action == AgentAction.ACCEPT and not scientific_accept_ok:
        feedback_approved = False
        feedback_reasons.append(
            "Final deterministic acceptance is not available because these checks "
            "still fail: " + ", ".join(_failed_checks(validation))
        )

    feedback_gate = {
        "approved": feedback_approved,
        "reasons": feedback_reasons,
        "generic_action_validator_approved": action_validation.approved,
        "scientific_acceptance_status": validation.get("status"),
    }
    save_json(case_out / "feedback_action_gate.json", feedback_gate)

    emit(
        "LLM CFD REASONING",
        f"iteration {iteration}: {decision.diagnosis.value} -> {decision.action.value}; "
        f"{decision.reasoning_summary[:260]}",
    )
    emit(
        "ACTION VALIDATOR",
        ("APPROVED" if feedback_approved else "REJECTED")
        + ": "
        + " ".join(feedback_reasons),
    )
    return decision, action_validation, decision_record, bundle


def _write_final_report(
    *,
    spec: NozzleCaseSpec,
    validation: Dict[str, Any],
    execution: Dict[str, Any],
    mesh: Dict[str, Any],
    decision: Any,
    action_validation: Any,
    case_out: Path,
    allow_fallback: bool,
    iterations: int,
) -> None:
    final = validation["final"]
    payload = {
        "case_id": spec.case_id,
        "description": spec.description,
        "deterministic_verdict": validation["status"],
        "failed_checks": _failed_checks(validation),
        "specification": spec.to_dict(),
        "feedback_iterations": iterations,
        "measured": {
            "exit_mach": final["outlet_M"],
            "exit_static_pressure_pa": final["outlet_p"],
            "exit_static_temperature_k": final["outlet_T"],
            "exit_velocity_m_s": final["outlet_U"],
            "exit_mass_flow_kg_s": final["outlet_mdot"],
            "inlet_mass_flow_kg_s": final["inlet_mdot"],
            "throat_mach": final["throat_M"],
            "minimum_outlet_normal_mach": final["outlet_normal_M_min"],
            "max_window_mass_mismatch_pct": final["max_window_mismatch_pct"],
            "max_transient_continuity_pct": validation[
                "max_transient_continuity_pct"
            ],
            "cells": mesh.get("cells"),
            "wall_seconds_last_iteration": execution.get("wall_seconds"),
        },
        "llm_decision": decision.to_dict(),
        "llm_action_approved": action_validation.approved,
    }
    withheld = withheld_from_agent(validation)
    payload["post_hoc_quasi_1d_comparison"] = withheld.get("theory", {})
    payload["post_hoc_quasi_1d_error_pct"] = withheld.get("theory_error_pct", {})
    summary, record = summarize_case(payload, allow_fallback=allow_fallback)
    (case_out / "ENGINEERING_SUMMARY.md").write_text(summary + "\n", encoding="utf-8")
    save_json(case_out / "report_payload.json", payload)
    save_json(case_out / "final_report_llm_call.json", record.to_dict())


def _initial_command(
    args: argparse.Namespace,
    case: Optional[str],
    first_end_time: float,
    out_root: Path,
) -> List[str]:
    cmd = [
        sys.executable,
        str(_REPO_ROOT / "scripts/run_nozzle_e2e.py"),
    ]
    if case is not None:
        cmd += ["--case", case]
    elif args.prompt is not None:
        cmd += ["--prompt", args.prompt]
    elif args.prompt_file is not None:
        cmd += ["--prompt-file", str(Path(args.prompt_file).resolve())]
    else:
        raise ValueError("Supply --case, --prompt or --prompt-file.")

    cmd += [
        "--out",
        str(out_root),
        "--end-time",
        str(first_end_time),
        "--scale",
        str(args.scale),
        "--max-courant",
        str(args.max_courant),
        "--wedge-angle",
        str(args.wedge_angle),
        "--solver-timeout",
        str(args.solver_timeout),
    ]
    if args.distro:
        cmd += ["--distro", args.distro]
    if args.bashrc:
        cmd += ["--bashrc", args.bashrc]
    if args.allow_fallback:
        cmd += ["--allow-fallback"]
    return cmd


def _next_continue_horizon(
    current_time: float,
    *,
    target_end: float,
    increment: float,
    max_end: float,
) -> Optional[float]:
    candidate = current_time + increment
    if current_time < target_end - 1e-12:
        candidate = max(candidate, target_end)
    candidate = min(candidate, max_end)
    return candidate if candidate > current_time + 1e-12 else None


def run_case(args: argparse.Namespace, case: Optional[str]) -> Dict[str, Any]:
    label = CASE_LABELS[case] if case is not None else "case_from_prompt"
    out_root = Path(args.out).resolve()
    case_out = out_root / label
    case_out.mkdir(parents=True, exist_ok=True)

    first_end = args.feedback_first_end_time if args.feedback_demo else args.end_time
    if args.feedback_demo and not args.end_time > first_end:
        raise ValueError(
            "feedback demo requires --end-time greater than --feedback-first-end-time"
        )

    emit("FEEDBACK LOOP", f"{label}: launching CFD iteration 1 to {first_end:g} s")
    subprocess.run(_initial_command(args, case, first_end, out_root), check=False)
    result_path = case_out / "case_result.json"
    if not result_path.exists():
        raise RuntimeError("initial E2E runner produced no case_result.json")
    result = _read_json(result_path)

    hard_failures = {
        "LLM_UNAVAILABLE",
        "NO_OPENFOAM",
        "BUILD_FAILED",
        "MESH_REJECTED",
        "INIT_FAILED",
        "DIAGNOSTICS_FAILED",
        "ERROR",
        "RUNTIME_ERROR",
    }
    if result.get("status") in hard_failures:
        return {
            "label": label,
            "status": result.get("status"),
            "iterations": 1,
            "message": result.get("message", ""),
        }

    # Preserve the E2E decision as provenance, then re-diagnose iteration 1
    # using the richer closed-loop numerical + visual evidence packet.
    for name in ("agent_decision.json", "action_validation.json", "cfd_evidence.json"):
        src = case_out / name
        if src.exists():
            shutil.copy2(src, case_out / f"initial_e2e_{name}")

    validation = _read_json(case_out / "validation.json")
    current_spec = NozzleCaseSpec.from_dict(result["spec"])
    runtime_case = result.get("runtime_case")
    if not runtime_case:
        raise RuntimeError("initial runner did not preserve runtime_case")
    case_path = PurePosixPath(runtime_case)
    root = case_path.parent
    mesh = _read_json(case_out / "mesh_evidence.json")
    execution = _read_json(case_out / "execution.json")
    runtime = _runtime(args)

    history: List[Dict[str, Any]] = []
    feedback_trace: List[Dict[str, Any]] = []
    iteration = 1
    diagnostic_requests_on_state = 0

    decision, action_validation_obj, decision_record, bundle = _diagnose_iteration(
        runtime=runtime,
        case_path=case_path,
        iteration=iteration,
        spec=current_spec,
        validation=validation,
        execution=execution,
        mesh=mesh,
        case_out=case_out,
        history=history,
        allow_fallback=args.allow_fallback,
        require_visuals=args.require_visuals,
    )

    while True:
        action = decision.action.value
        generic_approved = bool(action_validation_obj.approved)
        scientific_pass = validation.get("status") == "PASS_SINGLE_MESH"
        feedback_approved = generic_approved and not (
            action == AgentAction.ACCEPT.value and not scientific_pass
        )

        action_validation = asdict(action_validation_obj)
        feedback_trace.append(
            {
                "iteration": iteration,
                "action": action,
                "approved": feedback_approved,
                "deterministic_status": validation.get("status"),
                "failed_checks": _failed_checks(validation),
                "visual_status": bundle.get("visual_observation", {}).get("status"),
                "runtime_case": str(case_path),
            }
        )
        _snapshot_iteration(case_out, iteration)

        accepted = scientific_pass and action == AgentAction.ACCEPT.value and feedback_approved
        if accepted:
            acceptance = {
                "case_id": current_spec.case_id,
                "accepted": True,
                "deterministic_status": validation["status"],
                "llm_proposed_action": action,
                "llm_action_approved_by_validator": True,
                "iterations": iteration,
                "authority": "deterministic validator + approved LLM termination decision",
            }
            save_json(case_out / "acceptance.json", acceptance)
            _write_final_report(
                spec=current_spec,
                validation=validation,
                execution=execution,
                mesh=mesh,
                decision=decision,
                action_validation=action_validation_obj,
                case_out=case_out,
                allow_fallback=args.allow_fallback,
                iterations=iteration,
            )
            emit("SCIENTIFIC VALIDATOR", f"PASS_SINGLE_MESH after {iteration} CFD iteration(s)")
            summary = {
                "label": label,
                "status": "ACCEPTED",
                "iterations": iteration,
                "trace": feedback_trace,
                "runtime_case": str(case_path),
            }
            save_json(case_out / "feedback_summary.json", summary)
            return summary

        # If the LLM tried to ACCEPT before deterministic science passed,
        # explicitly return the rejection to the model and let it reconsider.
        if action == AgentAction.ACCEPT.value and not scientific_pass:
            if diagnostic_requests_on_state >= args.max_diagnostic_requests:
                summary = {
                    "label": label,
                    "status": "ACCEPT_REPEATEDLY_BLOCKED_BY_SCIENCE",
                    "iterations": iteration,
                    "trace": feedback_trace,
                }
                save_json(case_out / "feedback_summary.json", summary)
                return summary
            diagnostic_requests_on_state += 1
            note = (
                "Your ACCEPT proposal was blocked by the final deterministic "
                "validator. Failed checks: " + ", ".join(_failed_checks(validation))
                + ". Reassess and choose a corrective action; do not ACCEPT until "
                "the deterministic checks pass."
            )
            history.append(
                _history_item(
                    iteration,
                    validation,
                    decision_record,
                    action_validation,
                    visual_status=bundle.get("visual_observation", {}).get("status"),
                    profile_diagnostics=bundle.get("profile_diagnostics"),
                    note=note,
                )
            )
            decision, action_validation_obj, decision_record, bundle = _diagnose_iteration(
                runtime=runtime,
                case_path=case_path,
                iteration=iteration,
                spec=current_spec,
                validation=validation,
                execution=execution,
                mesh=mesh,
                case_out=case_out,
                history=history,
                allow_fallback=args.allow_fallback,
                require_visuals=args.require_visuals,
                diagnostic_request=note,
            )
            continue

        if not feedback_approved:
            summary = {
                "label": label,
                "status": "ACTION_REJECTED",
                "iterations": iteration,
                "trace": feedback_trace,
            }
            save_json(case_out / "feedback_summary.json", summary)
            return summary

        # REQUEST_DIAGNOSTIC acquires and returns focused measured evidence on
        # the same CFD state.  It does not consume a CFD iteration.
        if action == AgentAction.REQUEST_DIAGNOSTIC.value:
            if diagnostic_requests_on_state >= args.max_diagnostic_requests:
                summary = {
                    "label": label,
                    "status": "DIAGNOSTIC_BUDGET_EXHAUSTED",
                    "iterations": iteration,
                    "trace": feedback_trace,
                }
                save_json(case_out / "feedback_summary.json", summary)
                return summary
            diagnostic_requests_on_state += 1
            request = decision.requested_diagnostic or "standard CFD diagnostic bundle"
            emit("DIAGNOSTIC TOOL", f"fulfilling LLM request: {request}")
            history.append(
                _history_item(
                    iteration,
                    validation,
                    decision_record,
                    action_validation,
                    visual_status=bundle.get("visual_observation", {}).get("status"),
                    profile_diagnostics=bundle.get("profile_diagnostics"),
                    note=f"LLM requested additional diagnostic: {request}",
                )
            )
            decision, action_validation_obj, decision_record, bundle = _diagnose_iteration(
                runtime=runtime,
                case_path=case_path,
                iteration=iteration,
                spec=current_spec,
                validation=validation,
                execution=execution,
                mesh=mesh,
                case_out=case_out,
                history=history,
                allow_fallback=args.allow_fallback,
                require_visuals=args.require_visuals,
                diagnostic_request=request,
            )
            continue

        if action == AgentAction.REJECT_OUTSIDE_DOMAIN.value:
            summary = {
                "label": label,
                "status": "REJECTED_OUTSIDE_DOMAIN",
                "iterations": iteration,
                "trace": feedback_trace,
            }
            save_json(case_out / "feedback_summary.json", summary)
            return summary

        if iteration >= args.max_iterations:
            summary = {
                "label": label,
                "status": "MAX_ITERATIONS_REACHED",
                "iterations": iteration,
                "trace": feedback_trace,
            }
            save_json(case_out / "feedback_summary.json", summary)
            return summary

        previous_action = action
        decision_dict = decision.to_dict()
        history.append(
            _history_item(
                iteration,
                validation,
                decision_record,
                action_validation,
                visual_status=bundle.get("visual_observation", {}).get("status"),
                profile_diagnostics=bundle.get("profile_diagnostics"),
            )
        )
        iteration += 1
        diagnostic_requests_on_state = 0
        emit("ACTION EXECUTOR", f"CFD iteration {iteration}: executing approved {previous_action}")

        if previous_action == AgentAction.CONTINUE_RUN.value:
            current_time = float(execution.get("last_observed_time") or 0.0)
            next_end = _next_continue_horizon(
                current_time,
                target_end=args.end_time,
                increment=args.feedback_increment,
                max_end=args.max_end_time,
            )
            if next_end is None:
                summary = {
                    "label": label,
                    "status": "PHYSICAL_TIME_BUDGET_EXHAUSTED",
                    "iterations": iteration - 1,
                    "trace": feedback_trace,
                }
                save_json(case_out / "feedback_summary.json", summary)
                return summary
            current_spec = _continue_case(
                runtime, case_path, current_spec, current_time, next_end
            )
            gate = evaluate_scope(current_spec)
            if not gate.approved:
                raise RuntimeError(
                    "continuation left registered scope: " + "; ".join(gate.reasons)
                )
            emit(
                "ACTION EXECUTOR",
                f"continuing latestTime {current_time:g} -> {next_end:g} s",
            )

        elif previous_action == AgentAction.RESTART_CLEAN.value:
            safe_id = re.sub(r"[^A-Za-z0-9_.-]", "_", current_spec.case_id)
            case_path = root / f"{safe_id}_restart_{iteration:02d}"
            runtime.bash(
                f"rm -rf -- {shlex.quote(str(case_path))}", foam=False, timeout=120
            )
            mesh = _mesh_new_case(
                runtime,
                root,
                current_spec,
                case_path,
                case_out,
                allow_fallback=args.allow_fallback,
            )
            emit("ACTION EXECUTOR", "clean rebuild + verified initialization completed")

        elif previous_action in {
            AgentAction.REFINE_THROAT.value,
            AgentAction.REFINE_GRADIENT_REGION.value,
        }:
            current_spec, refinement = refined_spec(
                current_spec,
                previous_action,
                decision_dict.get("target_region"),
            )
            gate = evaluate_scope(current_spec)
            if not gate.approved:
                raise RuntimeError(
                    "refined case left registered scope: " + "; ".join(gate.reasons)
                )
            save_json(
                case_out / f"refinement_iteration_{iteration:02d}.json", refinement
            )
            safe_id = re.sub(r"[^A-Za-z0-9_.-]", "_", current_spec.case_id)
            case_path = root / f"{safe_id}_refined_{iteration:02d}"
            runtime.bash(
                f"rm -rf -- {shlex.quote(str(case_path))}", foam=False, timeout=120
            )
            mesh = _mesh_new_case(
                runtime,
                root,
                current_spec,
                case_path,
                case_out,
                allow_fallback=args.allow_fallback,
            )
            emit(
                "ACTION EXECUTOR",
                "deterministic mesh refinement applied: "
                f"{refinement['applied_region']} -> "
                f"{refinement['total_cells_after']} cells",
            )

        elif previous_action == AgentAction.REPAIR_MESH.value:
            # Invalid topology/geometry is intentionally not auto-repaired in
            # this registered family.  The mesh gate fails closed before CFD.
            summary = {
                "label": label,
                "status": "MESH_REPAIR_OUTSIDE_AUTOMATED_SCOPE",
                "iterations": iteration - 1,
                "trace": feedback_trace,
            }
            save_json(case_out / "feedback_summary.json", summary)
            return summary

        else:
            summary = {
                "label": label,
                "status": f"UNEXECUTED_ACTION_{previous_action}",
                "iterations": iteration - 1,
                "trace": feedback_trace,
            }
            save_json(case_out / "feedback_summary.json", summary)
            return summary

        execution, validation = _run_solver(
            runtime, case_path, case_out, args.solver_timeout
        )
        decision, action_validation_obj, decision_record, bundle = _diagnose_iteration(
            runtime=runtime,
            case_path=case_path,
            iteration=iteration,
            spec=current_spec,
            validation=validation,
            execution=execution,
            mesh=mesh,
            case_out=case_out,
            history=history,
            allow_fallback=args.allow_fallback,
            require_visuals=args.require_visuals,
        )


def main() -> int:
    ap = argparse.ArgumentParser(description="Closed-loop LLM CFD feedback runner.")
    source = ap.add_mutually_exclusive_group(required=True)
    source.add_argument("--case", choices=["A", "B", "C", "ALL"])
    source.add_argument("--prompt", help="Natural-language engineering request.")
    source.add_argument("--prompt-file", help="File holding the engineering request.")
    ap.add_argument("--out", default=str(_REPO_ROOT / "demo/nozzle_feedback"))
    ap.add_argument("--end-time", type=float, default=DEFAULT_TARGET_END_TIME)
    ap.add_argument("--max-end-time", type=float, default=DEFAULT_MAX_END_TIME)
    ap.add_argument(
        "--feedback-demo",
        action="store_true",
        help=(
            "Start from an intentionally incomplete first physical-time window "
            "so the real feedback loop must evaluate and act."
        ),
    )
    ap.add_argument(
        "--feedback-first-end-time", type=float, default=DEFAULT_DEMO_FIRST_END_TIME
    )
    ap.add_argument("--feedback-increment", type=float, default=0.005)
    ap.add_argument("--max-iterations", type=int, default=4)
    ap.add_argument("--max-diagnostic-requests", type=int, default=2)
    ap.add_argument("--require-visuals", action="store_true")
    ap.add_argument("--scale", type=float, default=1.0)
    ap.add_argument("--max-courant", type=float, default=0.4)
    ap.add_argument("--wedge-angle", type=float, default=5.0)
    ap.add_argument("--solver-timeout", type=float, default=7200.0)
    ap.add_argument("--distro")
    ap.add_argument("--bashrc")
    ap.add_argument("--allow-fallback", action="store_true")
    args = ap.parse_args()

    if args.max_iterations < 1 or args.max_iterations > 6:
        raise SystemExit("--max-iterations must be between 1 and 6")
    if args.max_diagnostic_requests < 0 or args.max_diagnostic_requests > 3:
        raise SystemExit("--max-diagnostic-requests must be between 0 and 3")
    if not (0.001 <= args.end_time <= 0.02):
        raise SystemExit("--end-time must remain inside the registered [0.001, 0.02] s envelope")
    if not (args.end_time <= args.max_end_time <= 0.02):
        raise SystemExit("--max-end-time must be >= --end-time and <= 0.02 s")
    if args.feedback_increment <= 0:
        raise SystemExit("--feedback-increment must be positive")
    if args.feedback_demo and not (
        0.001 <= args.feedback_first_end_time < args.end_time
    ):
        raise SystemExit(
            "feedback demo first horizon must be >=0.001 s and below target end time"
        )

    if args.case == "ALL":
        cases: List[Optional[str]] = ["A", "B", "C"]
    elif args.case:
        cases = [args.case]
    else:
        cases = [None]

    results = []
    for case in cases:
        label = CASE_LABELS[case] if case is not None else "case_from_prompt"
        print("\n" + "=" * 78)
        print(f"  CLOSED-LOOP NOZZLE AGENT | {label}")
        print("=" * 78)
        try:
            results.append(run_case(args, case))
        except (FoamRuntimeError, LLMUnavailable, RuntimeError, ValueError) as exc:
            emit("FEEDBACK LOOP", f"{label} failed closed: {exc}")
            results.append(
                {
                    "label": label,
                    "status": "ERROR",
                    "message": str(exc),
                }
            )

    campaign = {
        "generated": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "closed_loop": True,
        "visual_evidence_enabled": True,
        "cases": results,
        "principle": (
            "LLM reasoning and action selection over numerical + visual CFD "
            "evidence; deterministic scientific authority and bounded action execution."
        ),
    }
    save_json(Path(args.out).resolve() / "FEEDBACK_CAMPAIGN_SUMMARY.json", campaign)

    print("\n" + "=" * 78)
    for result in results:
        print(
            f"  {result['label']:<22} {result['status']:<32} "
            f"iterations={result.get('iterations', '-')}"
        )
    print("=" * 78)
    return 0 if all(r.get("status") == "ACCEPTED" for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
