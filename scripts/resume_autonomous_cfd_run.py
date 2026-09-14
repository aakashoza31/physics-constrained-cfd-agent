from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.run_autonomous_cfd import (
    configure_continuation,
    enum_value,
    latest_positive_time,
    print_decision,
    produce_images,
    resolve_openfoam_runtime_case,
    save_iteration,
    save_json,
)
from src.agents.cfd_visual_observer import observe_cfd_images
from src.agents.theory_blind_cfd_agent import diagnose_theory_blind
from src.cfd.diagnostics import collect_cfd_diagnostics
from src.contracts.problem_spec import (
    CFDProblemSpec,
    NozzleFamily,
    NozzleGeometry,
    OperatingConditions,
)
from src.openfoam.executor import windows_path_to_wsl
from src.openfoam.stability_supervisor import run_supervised_openfoam_case
from src.openfoam.visualization import prepare_openfoam_visualization
from src.reasoning.diagnostics_adapter import adapt_raw_diagnostics
from src.reasoning.paper_safety_gate import apply_decision_safety_gate
from src.reporting.cfd_results_package import create_final_results_package


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def reconstruct_problem(path: Path) -> CFDProblemSpec:
    raw = load_json(path)
    problem = CFDProblemSpec(
        nozzle_family=NozzleFamily(raw["nozzle_family"]),
        geometry=NozzleGeometry(**raw["geometry"]),
        operating_conditions=OperatingConditions(**raw["operating_conditions"]),
        engineering_objective=raw.get(
            "engineering_objective",
            "Obtain a numerically trustworthy compressible-Euler CFD solution.",
        ),
        physics_model=raw.get("physics_model", "compressible_euler"),
        geometry_class=raw.get(
            "geometry_class",
            "axisymmetric_converging_diverging_nozzle",
        ),
    )
    problem.validate()
    return problem


def load_saved_history(iterations_dir: Path) -> tuple[list[dict[str, Any]], int, float | None, str | None]:
    history: list[dict[str, Any]] = []
    last_iteration = 0
    last_time: float | None = None
    last_action: str | None = None

    for path in sorted(iterations_dir.glob("iteration_*.json")):
        record = load_json(path)
        iteration = int(record.get("iteration", 0))
        decision = record.get("decision", {})
        validation = record.get("deterministic_validation", {})
        visual = record.get("visual_observation", {})

        history.append(
            {
                "iteration": iteration,
                "decision": decision,
                "diagnostics": record.get("diagnostics", {}),
                "physical_time_s": record.get("physical_time_s"),
                "visual_observation": visual,
                "deterministic_validation": validation,
            }
        )

        if iteration >= last_iteration:
            last_iteration = iteration
            raw_time = record.get("physical_time_s")
            last_time = float(raw_time) if raw_time is not None else None
            last_action = str(decision.get("action")) if isinstance(decision, dict) else None

    return history, last_iteration, last_time, last_action


def wsl_dir_exists(path: str) -> bool:
    distro = os.getenv("OPENFOAM_WSL_DISTRO", "Ubuntu-24.04")
    proc = subprocess.run(
        ["wsl.exe", "-d", distro, "--", "bash", "-lc", f'test -d {json.dumps(path)}'],
        text=True,
        capture_output=True,
        check=False,
    )
    return proc.returncode == 0


def stage_for_diagnostics(openfoam_dir: Path) -> str:
    distro = os.getenv("OPENFOAM_WSL_DISTRO", "Ubuntu-24.04")
    source = windows_path_to_wsl(openfoam_dir)
    runtime_expr = "$HOME/physics_constrained_cfd_resume_runtime"
    script = (
        f'rm -rf "{runtime_expr}" && mkdir -p "{runtime_expr}" '
        f'&& cp -r {json.dumps(source + "/.")} "{runtime_expr}/" '
        f'&& printf "%s" "{runtime_expr}"'
    )
    proc = subprocess.run(
        ["wsl.exe", "-d", distro, "--", "bash", "-lc", script],
        text=True,
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError("Could not stage existing case for diagnostics:\n" + (proc.stderr or ""))
    resolved = proc.stdout.strip()
    if not resolved.startswith("/"):
        raise RuntimeError(f"Unexpected staged WSL path: {resolved!r}")
    return resolved


def runtime_case_for_existing(openfoam_dir: Path, execution: dict[str, Any]) -> str:
    try:
        candidate = resolve_openfoam_runtime_case(execution)
        if wsl_dir_exists(candidate):
            return candidate
    except Exception:
        pass
    return stage_for_diagnostics(openfoam_dir)


def load_or_make_visual_observation(
    *,
    iteration_dir: Path,
    images: dict[str, str],
    diagnostics: dict[str, Any],
) -> dict[str, Any]:
    cached = iteration_dir / "visual_observation.json"
    if cached.exists():
        print("Reusing existing multimodal visual observation for this iteration.")
        return load_json(cached)

    visual = observe_cfd_images(
        image_paths=images,
        numerical_context={
            "status": diagnostics.get("status"),
            "mass_imbalance_pct": diagnostics.get("flow", {}).get("mass_imbalance_pct"),
            "stationarity": diagnostics.get("stationarity", {}),
        },
    )
    save_json(cached, visual)
    return visual


def process_existing_state(
    *,
    run_root: Path,
    iteration: int,
    execution: dict[str, Any],
    problem: CFDProblemSpec,
    manifest: dict[str, Any],
    mesh_context: dict[str, Any],
    history: list[dict[str, Any]],
) -> tuple[str, float, dict[str, Any], dict[str, Any], dict[str, str], Any, Any, dict[str, Any]]:
    openfoam_dir = run_root / "openfoam"
    iterations_dir = run_root / "iterations"
    iteration_dir = iterations_dir / f"iteration_{iteration:02d}"
    iteration_dir.mkdir(parents=True, exist_ok=True)

    latest = latest_positive_time(openfoam_dir)
    if latest is None:
        raise RuntimeError("No positive saved OpenFOAM time exists to resume from.")

    case_wsl = runtime_case_for_existing(openfoam_dir, execution)
    solver_log_wsl = windows_path_to_wsl(openfoam_dir / "log.foamRun")

    print()
    print("=" * 76)
    print(f"RECOVERING AUTONOMOUS CFD ITERATION {iteration}")
    print("=" * 76)
    print("Existing physical time:", latest)
    print("No geometry regeneration: YES")
    print("No remeshing: YES")
    print("No CFD restart: YES")
    print()
    print("Collecting FULL available CFD history after quota interruption...")

    diagnostics = collect_cfd_diagnostics(
        case_wsl=case_wsl,
        solver_log=solver_log_wsl,
        geometry_manifest=manifest,
    )

    visualization = prepare_openfoam_visualization(
        case_dir=openfoam_dir,
        timeout_s=600,
        open_in_gmsh=False,
        create_demo_assets=True,
    )

    images = produce_images(
        visualization=visualization,
        output_dir=iteration_dir / "images",
    )

    visual_observation = load_or_make_visual_observation(
        iteration_dir=iteration_dir,
        images=images,
        diagnostics=diagnostics,
    )

    evidence = adapt_raw_diagnostics(
        diagnostics,
        problem,
        mesh_context=mesh_context,
        visual_paths=images,
        iteration=iteration,
        case_id=run_root.name,
    )

    history_for_call = history + [
        {
            "iteration": iteration,
            "visual_observation": visual_observation,
            "theory_used_by_agent": False,
            "execution_provenance": {
                "current_state_origin": "same_mesh_latestTime_continuation",
                "geometry_regenerated": False,
                "mesh_changed": False,
                "solution_mapped_to_new_mesh": False,
                "field_mapping_performed": False,
                "instruction": (
                    "These are deterministic execution facts. "
                    "Do not infer that a proposed mesh-refinement "
                    "action was executed unless mesh_changed is true."
                ),
            },
        },
        {
            "resume_context": (
                "This continuation path uses the SAME OpenFOAM mesh "
                "and saved solution. No geometry regeneration, "
                "remeshing, mapFields operation, or field mapping "
                "has occurred."
            )
        },
    ]

    decision, validation = diagnose_theory_blind(
        problem,
        evidence,
        history=history_for_call,
    )

    action = enum_value(decision.action)
    diagnostic_followup = None

    if action == "REQUEST_DIAGNOSTIC":
        diagnostic_followup = {
            "requested_diagnostic": decision.requested_diagnostic,
            "response": (
                "Full available temporal, boundary, global-extrema, throat, mesh, and visual evidence "
                "has already been recollected after resume."
            ),
        }
        decision, validation = diagnose_theory_blind(
            problem,
            evidence,
            history=history_for_call + [diagnostic_followup],
        )
        action = enum_value(decision.action)

    raw_agent_action = action
    action, paper_safety_gate = apply_decision_safety_gate(
        requested_action=action,
        diagnostics=diagnostics,
        history=history,
    )
    if paper_safety_gate.get("overridden"):
        print()
        print("PAPER SAFETY GATE: OVERRIDE")
        print("Raw agent action :", raw_agent_action)
        print("Effective action :", action)
        print("Reason           :", paper_safety_gate.get("reason"))

    print_decision(decision=decision, validation=validation)

    record = {
        "iteration": iteration,
        "physical_time_s": latest,
        "execution": execution,
        "diagnostics": diagnostics,
        "visualization": visualization,
        "standardized_images": images,
        "visual_observation": visual_observation,
        "decision": decision.to_dict(),
        "raw_agent_action": raw_agent_action,
        "effective_action": action,
        "paper_safety_gate": paper_safety_gate,
        "deterministic_validation": {
            "approved": validation.approved,
            "reasons": validation.reasons,
        },
        "diagnostic_followup": diagnostic_followup,
        "theory_used_by_agent": False,
        "resumed_after_external_quota_interrupt": True,
    }

    save_iteration(
        output_dir=iterations_dir,
        iteration=iteration,
        record=record,
    )

    return (
        action,
        latest,
        diagnostics,
        visualization,
        images,
        decision,
        validation,
        visual_observation,
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Resume an existing autonomous CFD run after an external LLM/API interruption."
    )
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--max-total-iterations", type=int, default=8)
    parser.add_argument("--increment", type=float, default=1.0e-4)
    parser.add_argument("--solver-timeout", type=int, default=1200)
    args = parser.parse_args()

    run_root = args.run_root.resolve()
    openfoam_dir = run_root / "openfoam"
    iterations_dir = run_root / "iterations"
    final_dir = run_root / "final"

    required = [
        run_root / "agent" / "problem_spec.json",
        run_root / "geometry" / "geometry_manifest.json",
        run_root / "mesh" / "best_mesh_metrics.json",
        openfoam_dir / "openfoam_execution_summary.json",
    ]
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        raise FileNotFoundError("Resume prerequisites missing:\n" + "\n".join(missing))

    print("=" * 76)
    print("AUTONOMOUS CFD RESUME")
    print("=" * 76)
    print("Run:", run_root)
    print("Gemini model:", os.getenv("GEMINI_MODEL", "<default>"))
    print("Increment:", args.increment)
    print("Maximum total iterations:", args.max_total_iterations)

    problem = reconstruct_problem(run_root / "agent" / "problem_spec.json")
    manifest = load_json(run_root / "geometry" / "geometry_manifest.json")
    mesh_context = load_json(run_root / "mesh" / "best_mesh_metrics.json")

    history, last_saved_iteration, last_saved_time, last_saved_action = load_saved_history(iterations_dir)
    latest = latest_positive_time(openfoam_dir)
    if latest is None:
        raise RuntimeError("Existing OpenFOAM case has no saved positive time.")

    execution = load_json(openfoam_dir / "openfoam_execution_summary.json")

    print("Last fully saved autonomous iteration:", last_saved_iteration)
    print("Last fully saved physical time:", last_saved_time)
    print("Current CFD physical time:", latest)

    final_diagnostics: dict[str, Any] | None = None
    final_visualization: dict[str, Any] | None = None
    final_images: dict[str, str] = {}
    final_decision: Any = None
    terminal_reason: str | None = None
    resume_trace: list[dict[str, Any]] = []

    # If CFD advanced beyond the last fully saved reasoning record, recover that unsaved state first.
    if last_saved_time is None or latest > last_saved_time + 1.0e-14:
        iteration = last_saved_iteration + 1
        (
            action,
            latest,
            final_diagnostics,
            final_visualization,
            final_images,
            final_decision,
            validation,
            visual,
        ) = process_existing_state(
            run_root=run_root,
            iteration=iteration,
            execution=execution,
            problem=problem,
            manifest=manifest,
            mesh_context=mesh_context,
            history=history,
        )
        history.append(
            {
                "iteration": iteration,
                "decision": final_decision.to_dict(),
                "raw_agent_action": enum_value(
                    final_decision.action
                ),
                "effective_action": action,
                "executed_action": action,
                "diagnostics": final_diagnostics or {},
                "physical_time_s": latest,
                "visual_observation": visual,
                "deterministic_validation": {
                    "approved": validation.approved,
                    "reasons": validation.reasons,
                },
                "execution_provenance": {
                    "geometry_regenerated": False,
                    "mesh_changed": False,
                    "solution_mapped_to_new_mesh": False,
                },
            }
        )
        resume_trace.append({"iteration": iteration, "physical_time_s": latest, "action": action})
        last_saved_iteration = iteration
        last_saved_action = action
    else:
        action = last_saved_action or "CONTINUE_RUN"
        if history:
            saved_diagnostics = history[-1].get("diagnostics", {})
            raw_saved_action = action
            action, saved_gate = apply_decision_safety_gate(
                requested_action=action,
                diagnostics=saved_diagnostics,
                history=history[:-1],
            )
            if saved_gate.get("overridden"):
                print()
                print("PAPER SAFETY GATE: RECOVERED SAVED DECISION")
                print("Raw saved action :", raw_saved_action)
                print("Effective action :", action)
                print("Reason           :", saved_gate.get("reason"))

    while last_saved_iteration < args.max_total_iterations:
        if action == "ACCEPT":
            terminal_reason = "Agent accepted the CFD result after deterministic validation."
            break

        if action != "CONTINUE_RUN":
            terminal_reason = (
                f"Agent requested {action}. Continuation-only recovery stopped safely so that "
                "a different corrective action is not silently substituted."
            )
            break

        current_time = latest_positive_time(openfoam_dir)
        if current_time is None:
            raise RuntimeError("Cannot continue because no saved CFD time exists.")

        configure_continuation(
            case_dir=openfoam_dir,
            current_time=current_time,
            duration_s=args.increment,
        )

        next_iteration = last_saved_iteration + 1
        print()
        print("=" * 76)
        print(f"AUTONOMOUS CFD CONTINUATION ITERATION {next_iteration}")
        print("=" * 76)
        print("Continuing SAME OpenFOAM case from latestTime.")

        execution = run_supervised_openfoam_case(
            openfoam_dir,
            run_solver=True,
            solver_timeout_s=args.solver_timeout,
        )
        print("OpenFOAM status:", execution.get("status"))

        (
            action,
            latest,
            final_diagnostics,
            final_visualization,
            final_images,
            final_decision,
            validation,
            visual,
        ) = process_existing_state(
            run_root=run_root,
            iteration=next_iteration,
            execution=execution,
            problem=problem,
            manifest=manifest,
            mesh_context=mesh_context,
            history=history,
        )

        history.append(
            {
                "iteration": next_iteration,
                "decision": final_decision.to_dict(),
                "raw_agent_action": enum_value(
                    final_decision.action
                ),
                "effective_action": action,
                "executed_action": action,
                "diagnostics": final_diagnostics or {},
                "physical_time_s": latest,
                "visual_observation": visual,
                "deterministic_validation": {
                    "approved": validation.approved,
                    "reasons": validation.reasons,
                },
                "execution_provenance": {
                    "geometry_regenerated": False,
                    "mesh_changed": False,
                    "solution_mapped_to_new_mesh": False,
                },
            }
        )
        resume_trace.append({"iteration": next_iteration, "physical_time_s": latest, "action": action})
        last_saved_iteration = next_iteration

    if terminal_reason is None:
        if action == "ACCEPT":
            terminal_reason = "Agent accepted the CFD result after deterministic validation."
        elif last_saved_iteration >= args.max_total_iterations:
            terminal_reason = "MAX_AUTONOMOUS_ITERATIONS_REACHED_UNCONVERGED"
        else:
            terminal_reason = f"Stopped with action {action}."

    if final_diagnostics is not None:
        primary_vtk = None
        if isinstance(final_visualization, dict):
            raw = final_visualization.get("primary_vtk")
            if raw:
                candidate = Path(str(raw))
                if candidate.exists():
                    primary_vtk = candidate

        package = create_final_results_package(
            run_name=run_root.name,
            output_dir=final_dir,
            problem_spec=problem,
            diagnostics=final_diagnostics,
            decision=final_decision,
            primary_vtk=primary_vtk,
            final_mesh=run_root / "mesh" / "best_mesh.msh",
            gamma=1.4,
            gas_constant=287.0,
            open_folder=True,
        )
    else:
        package = None

    save_json(
        run_root / "RESUME_TRACE.json",
        {
            "model": os.getenv("GEMINI_MODEL"),
            "terminal_reason": terminal_reason,
            "iterations": resume_trace,
            "final_package": package,
            "theory_used_by_agent": False,
        },
    )

    print()
    print("=" * 76)
    print("AUTONOMOUS CFD RESUME COMPLETE")
    print("=" * 76)
    print("Terminal reason:", terminal_reason)
    print("Final report:", final_dir / "CFD_REPORT.html")
    print("Resume trace:", run_root / "RESUME_TRACE.json")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

