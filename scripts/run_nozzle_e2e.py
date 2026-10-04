#!/usr/bin/env python3
"""End-to-end LLM-driven nozzle CFD demonstration.

    natural-language engineering request
      -> LLM case interpretation
      -> deterministic scope gate
      -> mesh tool (blockMesh + checkMesh)
      -> LLM inspects mesh evidence and chooses the next step
      -> CFD setup and verified quasi-1D initialization
      -> OpenFOAM execution (shockFluid / foamRun)
      -> deterministic diagnostics
      -> LLM theory-blind diagnosis and proposed action
      -> deterministic action validator
      -> deterministic scientific acceptance
      -> LLM engineering summary

Authority is split exactly as the research principle requires.  The LLM
interprets, inspects and explains.  Deterministic code owns mesh validity,
thermodynamic admissibility, conservation, stationarity, outlet-regime
verification, action safety and final CFD acceptance.  No LLM output can turn a
failed deterministic check into an accepted case.

Usage
-----
    python scripts/run_nozzle_e2e.py --case A
    python scripts/run_nozzle_e2e.py --case B
    python scripts/run_nozzle_e2e.py --case C
    python scripts/run_nozzle_e2e.py --case ALL
    python scripts/run_nozzle_e2e.py --prompt "Simulate ... outlet radius = 37 mm ..."
    python scripts/run_nozzle_e2e.py --prompt-file my_request.txt

All three cases use the same parameterized pipeline.  Nothing is hand-edited
per case.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import sys
import time
from dataclasses import asdict
from pathlib import Path, PurePosixPath
from typing import Any, Dict, List, Optional

_REPO_ROOT = Path(__file__).resolve().parents[1]

if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from src.agents.llm_provenance import LLMCallRecord, LLMUnavailable  # noqa: E402
from src.agents.nozzle_case_spec_agent import interpret_case_request  # noqa: E402
from src.agents.nozzle_demo_agents import (  # noqa: E402
    review_mesh_evidence,
    summarize_case,
)
from src.contracts.problem_spec import (  # noqa: E402
    CFDProblemSpec,
    NozzleFamily,
    NozzleGeometry,
    OperatingConditions,
)
from src.pipeline.foam_runtime import FoamRuntime, FoamRuntimeError  # noqa: E402
from src.pipeline.nozzle.build import build as build_case  # noqa: E402
from src.pipeline.nozzle.spec import NozzleCaseSpec  # noqa: E402
from src.reasoning.nozzle_diagnosis import diagnose  # noqa: E402
from src.reasoning.nozzle_scope_gate import evaluate_scope  # noqa: E402
from src.reasoning.reference_evidence_adapter import (  # noqa: E402
    build_evidence_from_validation,
    withheld_from_agent,
)
from src.reporting import event_stream as ev  # noqa: E402
from src.reporting.event_stream import EventStream  # noqa: E402


PROMPTS = {
    "A": _REPO_ROOT / "examples/nozzle_e2e/PROMPT_A.txt",
    "B": _REPO_ROOT / "examples/nozzle_e2e/PROMPT_B.txt",
    "C": _REPO_ROOT / "examples/nozzle_e2e/PROMPT_C.txt",
}

CASE_LABELS = {
    "A": "case_A_reference",
    "B": "case_B_geometry",
    "C": "case_C_conditions",
}

PIPELINE_DIR = _REPO_ROOT / "src/pipeline/nozzle"


# ----------------------------------------------------------------------
# helpers
# ----------------------------------------------------------------------


def save_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")


def parse_check_mesh(log: str) -> Dict[str, Any]:
    """Extract the deterministic mesh metrics checkMesh actually reported."""
    out: Dict[str, Any] = {"mesh_ok": "Mesh OK" in log}

    patterns = {
        "cells": r"cells:\s+(\d+)",
        "faces": r"faces:\s+(\d+)",
        "points": r"points:\s+(\d+)",
        "max_aspect_ratio": r"Max aspect ratio = ([-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?)",
        "max_non_orthogonality_deg": r"Mesh non-orthogonality Max: ([-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?)",
        "max_skewness": r"Max skewness = ([-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?)",
        "min_volume": r"Min volume = ([-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?)",
    }

    for key, pattern in patterns.items():
        m = re.search(pattern, log)
        if m:
            value = m.group(1)
            out[key] = int(value) if key in {"cells", "faces", "points"} else float(value)

    out["failed_checks"] = re.findall(r"\*\*\*(.+)", log)[:10]

    return out


# mesh_case.sh step name -> the log that step writes
STEP_LOGS = {
    "blockMesh": "log.blockMesh",
    "checkMesh": "log.checkMesh",
    "checkMesh_reports_Mesh_OK": "log.checkMesh",
    "writeCellCentres": "log.centres",
    "writeCellVolumes": "log.volumes",
}

STEP_SUMMARIES = {
    "openfoam_v14_environment": (
        "the OpenFOAM environment inside the mesh shell was not Foundation v14"
    ),
    "blockMesh": "blockMesh did not generate the mesh",
    "checkMesh": "checkMesh did not run to completion",
    "checkMesh_reports_Mesh_OK": (
        "checkMesh -allTopology -allGeometry ran but did not report Mesh OK"
    ),
    "writeCellCentres": (
        "foamPostProcess -func writeCellCentres failed, so the initializer has "
        "no cell centres to work from"
    ),
    "writeCellVolumes": (
        "foamPostProcess -func writeCellVolumes failed, so the validator has no "
        "cell volumes to weight with"
    ),
}


def mesh_step_evidence(steps: Dict[str, Any]) -> Dict[str, Any]:
    """Per-command evidence, so no outcome is attributed to the wrong command."""
    by_name = {
        step["name"]: step["returncode"]
        for step in steps.get("steps", [])
        if isinstance(step, dict) and "name" in step
    }

    def ran_ok(name: str) -> Optional[bool]:
        return None if name not in by_name else by_name[name] == 0

    return {
        "steps": steps.get("steps", []),
        "failed_step": steps.get("failed_step") or None,
        "step_returncodes": by_name,
        "environment_ok": ran_ok("openfoam_v14_environment"),
        "blockMesh_ok": ran_ok("blockMesh"),
        "checkMesh_ran": ran_ok("checkMesh"),
        "cell_centres_written": ran_ok("writeCellCentres"),
        "cell_volumes_written": ran_ok("writeCellVolumes"),
    }


def describe_mesh_failure(
    steps: Dict[str, Any],
    mesh_evidence: Dict[str, Any],
    shell_result: Any,
    logs_dir: Path,
) -> Dict[str, Any]:
    """Attribute a mesh-stage failure to the exact command that produced it."""
    failed_step = steps.get("failed_step") or None

    if not failed_step and not steps:
        # mesh_steps.json never appeared: the shell died before or inside the
        # script, so the shell's own message is the diagnosis.
        shell_text = (
            (shell_result.stderr or "").strip()
            or (shell_result.stdout or "").strip()
            or "no output"
        )

        return {
            "failed_step": "mesh shell",
            "summary": (
                "the mesh shell exited with returncode "
                f"{shell_result.returncode} without producing a step record; "
                f"shell said: {shell_text[-600:]}"
            ),
            "log_name": "",
            "log_tail": "",
            "shell_returncode": shell_result.returncode,
        }

    if not failed_step:
        # Every command returned 0 but the gate still failed: the only way is a
        # checkMesh log without 'Mesh OK'.
        failed_step = "checkMesh_reports_Mesh_OK"

    summary = STEP_SUMMARIES.get(failed_step, f"{failed_step} failed")

    if failed_step == "checkMesh_reports_Mesh_OK":
        complaints = mesh_evidence.get("failed_checks") or []
        if complaints:
            summary += "; checkMesh reported: " + "; ".join(
                c.strip() for c in complaints[:3]
            )

    log_name = STEP_LOGS.get(failed_step, "")
    log_tail = ""

    if log_name and (logs_dir / log_name).exists():
        text = (logs_dir / log_name).read_text(errors="replace").strip()
        log_tail = "\n".join(text.splitlines()[-25:])

    return {
        "failed_step": failed_step,
        "summary": summary,
        "log_name": log_name,
        "log_tail": log_tail,
        "shell_returncode": shell_result.returncode,
    }


def problem_from_spec(spec: NozzleCaseSpec) -> CFDProblemSpec:
    problem = CFDProblemSpec(
        nozzle_family=NozzleFamily.CONICAL,
        geometry=NozzleGeometry(
            inlet_radius_m=spec.inlet_radius_m,
            throat_radius_m=spec.throat_radius_m,
            outlet_radius_m=spec.exit_radius_m,
            inlet_length_m=spec.inlet_straight_m,
            converging_length_m=spec.converging_m,
            throat_length_m=spec.throat_m,
            diverging_length_m=spec.diverging_m,
            outlet_length_m=spec.outlet_straight_m,
        ),
        operating_conditions=OperatingConditions(
            inlet_total_pressure_pa=spec.total_pressure_pa,
            inlet_total_temperature_k=spec.total_temperature_k,
            outlet_static_pressure_pa=spec.ambient_pressure_pa,
        ),
    )
    problem.validate()
    return problem


def record_llm(
    stream: EventStream,
    record: LLMCallRecord,
    message: str,
    data: Optional[Dict[str, Any]] = None,
    status: str = "INFO",
) -> None:
    payload = dict(data or {})
    payload["llm_call"] = record.to_dict()

    stream.emit(
        ev.LLM,
        message,
        data=payload,
        status=status,
        llm_source=record.label,
    )


# ----------------------------------------------------------------------
# the run
# ----------------------------------------------------------------------


class CaseRun:
    def __init__(self, args: argparse.Namespace, label: str, prompt: str) -> None:
        self.args = args
        self.label = label
        self.prompt = prompt
        self.out_dir = Path(args.out).resolve() / label
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self.stream = EventStream(self.out_dir, case_id=label)
        self.llm_calls: List[Dict[str, Any]] = []
        self.result: Dict[str, Any] = {
            "label": label,
            "status": "INCOMPLETE",
            "out_dir": str(self.out_dir),
        }
        self.runtime: Optional[FoamRuntime] = None
        self.case_path: Optional[PurePosixPath] = None

    # ------------------------------------------------------------------

    def finish(self, status: str, message: str = "") -> Dict[str, Any]:
        self.result["status"] = status
        self.result["message"] = message
        self.result["llm_calls"] = self.llm_calls
        self.result["event_summary"] = self.stream.summary()

        save_json(self.out_dir / "case_result.json", self.result)
        save_json(self.out_dir / "llm_calls.json", self.llm_calls)

        return self.result

    def note_llm(self, record: LLMCallRecord) -> None:
        self.llm_calls.append(record.to_dict())

    # ------------------------------------------------------------------

    def run(self) -> Dict[str, Any]:
        s = self.stream
        args = self.args

        s.emit(
            ev.ORCHESTRATOR,
            f"Engineering request received ({len(self.prompt)} characters).",
            data={"prompt_first_line": self.prompt.strip().splitlines()[0]},
        )
        (self.out_dir / "request.txt").write_text(self.prompt, encoding="utf-8")

        # 1. LLM: natural language -> structured case specification ---------
        numerics = {
            "scale": args.scale,
            "end_time_s": args.end_time,
            "max_courant": args.max_courant,
            "wedge_angle_deg": args.wedge_angle,
        }

        try:
            spec, request, record = interpret_case_request(
                self.prompt,
                allow_fallback=args.allow_fallback,
                numerics=numerics,
            )
        except LLMUnavailable as exc:
            s.fail(ev.LLM, str(exc))
            return self.finish("LLM_UNAVAILABLE", str(exc))

        self.note_llm(record)

        record_llm(
            s,
            record,
            (
                f"Case interpreted: exit radius {spec.exit_radius_m:.4f} m, "
                f"p0 {spec.total_pressure_pa:.0f} Pa, "
                f"T0 {spec.total_temperature_k:.0f} K, "
                f"ambient {spec.ambient_pressure_pa:.0f} Pa."
            ),
            data={
                "case_id": spec.case_id,
                "interpretation": request.model_dump(),
            },
        )

        save_json(
            self.out_dir / "case_spec.json",
            {
                "spec": spec.to_dict(),
                "llm_interpretation": request.model_dump(),
                "llm_call": record.to_dict(),
            },
        )

        self.result["case_id"] = spec.case_id
        self.result["spec"] = spec.to_dict()
        self.result["llm_source_case_spec"] = record.label

        # 2. Deterministic scope gate --------------------------------------
        gate = evaluate_scope(spec)
        save_json(self.out_dir / "scope_gate.json", gate.to_dict())
        self.result["scope_gate"] = gate.to_dict()

        if not gate.approved:
            s.fail(
                ev.SCOPE_GATE,
                "REJECT_OUTSIDE_DOMAIN: " + " ".join(gate.reasons),
                data=gate.to_dict(),
            )
            return self.finish("REJECTED_OUT_OF_SCOPE", "; ".join(gate.reasons))

        s.ok(
            ev.SCOPE_GATE,
            (
                "Case is inside the declared registered envelope "
                f"(area ratio {gate.measurements['area_ratio']:.4f}, "
                f"NPR {gate.measurements['nozzle_pressure_ratio']:.3f}, "
                f"{int(gate.measurements['cells'])} cells)."
            ),
            data=gate.to_dict(),
        )

        # 3. Plan-only stops here, before any CFD --------------------------
        if args.plan_only:
            local_case = self.out_dir / "generated_case"

            if local_case.exists():
                import shutil

                shutil.rmtree(local_case)

            build_case(local_case, spec)

            s.ok(
                ev.CFD_SETUP,
                f"OpenFOAM case dictionaries generated locally at {local_case}. "
                "Stopping before CFD (--plan-only).",
                data={
                    "files": sorted(
                        str(p.relative_to(local_case))
                        for p in local_case.rglob("*")
                        if p.is_file()
                    )
                },
            )
            return self.finish("PLAN_ONLY", "No CFD executed.")

        # 4. Runtime preflight ---------------------------------------------
        runtime = FoamRuntime.detect()
        self.runtime = runtime

        if args.distro:
            runtime.distro = args.distro
        if args.bashrc:
            runtime.bashrc = args.bashrc

        try:
            info = runtime.preflight()
        except FoamRuntimeError as exc:
            s.fail(ev.PREFLIGHT, str(exc))
            return self.finish("NO_OPENFOAM", str(exc))

        save_json(self.out_dir / "runtime_preflight.json", info)

        if not info["ok"]:
            s.fail(
                ev.PREFLIGHT,
                f"OpenFOAM Foundation v14 runtime unavailable: {info.get('reason')}",
                data=info,
            )
            return self.finish("NO_OPENFOAM", str(info.get("reason")))

        s.ok(
            ev.PREFLIGHT,
            f"OpenFOAM Foundation v{info['openfoam_version']} runtime ready "
            f"({runtime.mode}, numpy {info['numpy']}).",
            data=info,
        )

        # 5. Mesh tool ------------------------------------------------------
        stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
        root = runtime.make_root(f"{stamp}-{self.label}")
        runtime.stage_code(PIPELINE_DIR)

        spec_path = root / "code/case_spec.json"
        runtime.write_text(spec_path, json.dumps(spec.to_dict(), indent=2))

        safe_case_id = re.sub(r"[^A-Za-z0-9_.-]", "_", spec.case_id)[:64] or "case"

        case_path = root / safe_case_id
        self.case_path = case_path
        self.result["runtime_case"] = str(case_path)

        s.emit(
            ev.MESH_TOOL,
            f"Generating parameterized wedge mesh in {case_path}.",
            data={
                "axial_cells": spec.axial_cells,
                "radial_cells": spec.radial_cells,
                "wedge_angle_deg": spec.wedge_angle_deg,
                "breakpoints_m": spec.axial_breakpoints_m,
                "radii_m": spec.radii_m,
            },
        )

        built = runtime.bash(
            f'cd {shlex.quote(str(root))}/code && '
            f'python3 build.py {shlex.quote(str(case_path))} '
            f'--spec {shlex.quote(str(spec_path))}',
            timeout=300,
        )

        if not built.ok:
            s.fail(ev.MESH_TOOL, f"Case generation failed: {built.stdout}{built.stderr}")
            return self.finish("BUILD_FAILED", built.stdout + built.stderr)

        meshed = runtime.bash(
            f'bash {shlex.quote(str(root))}/code/mesh_case.sh '
            f'{shlex.quote(str(case_path))}',
            timeout=900,
        )

        # Retrieve every log and the per-step record, whether the stage passed
        # or failed. A failed mesh stage is exactly when this evidence matters.
        logs_dir = self.out_dir / "logs"
        logs_dir.mkdir(exist_ok=True)

        for name, local in (
            ("log.blockMesh", "log.blockMesh"),
            ("log.checkMesh", "log.checkMesh"),
            ("log.centres", "log.centres"),
            ("log.volumes", "log.volumes"),
        ):
            runtime.fetch(case_path / name, logs_dir / local)

        steps_fetched = runtime.fetch(
            case_path / "mesh_steps.json", self.out_dir / "mesh_steps.json"
        )

        steps: Dict[str, Any] = {}

        if steps_fetched:
            try:
                steps = json.loads((self.out_dir / "mesh_steps.json").read_text())
            except json.JSONDecodeError:
                steps = {}

        check_log = (
            (logs_dir / "log.checkMesh").read_text(errors="replace")
            if (logs_dir / "log.checkMesh").exists()
            else ""
        )

        mesh_evidence = parse_check_mesh(check_log)
        mesh_evidence["axial_cells"] = sum(spec.axial_cells)
        mesh_evidence["radial_cells"] = spec.radial_cells
        mesh_evidence.update(mesh_step_evidence(steps))

        # The shell's own diagnosis, which is where "unbound variable",
        # "No such file or directory" and "command not found" appear.
        mesh_evidence["shell_returncode"] = meshed.returncode
        mesh_evidence["shell_stderr"] = meshed.stderr.strip()[-2000:]
        mesh_evidence["shell_stdout_tail"] = meshed.stdout.strip()[-2000:]

        save_json(self.out_dir / "mesh_evidence.json", mesh_evidence)

        # One event per command that actually ran, so the stream attributes the
        # outcome to the command rather than to the stage.
        for step in steps.get("steps", []):
            s.emit(
                ev.MESH_TOOL,
                f"{step['name']}: returncode {step['returncode']}",
                status="PASS" if step["returncode"] == 0 else "FAIL",
            )

        # Unchanged in strength: checkMesh must actually report Mesh OK in its
        # own log, AND every command in the mesh sequence must have returned 0.
        mesh_gate_ok = (
            bool(mesh_evidence.get("mesh_ok"))
            and meshed.ok
            and steps_fetched
            and mesh_evidence.get("environment_ok") is True
            and mesh_evidence.get("blockMesh_ok") is True
            and mesh_evidence.get("checkMesh_ran") is True
            and mesh_evidence.get("cell_centres_written") is True
            and mesh_evidence.get("cell_volumes_written") is True
        )

        if not mesh_gate_ok:
            reason = describe_mesh_failure(
                steps, mesh_evidence, meshed, logs_dir
            )

            s.fail(
                ev.MESH_TOOL,
                f"Deterministic mesh gate failed at {reason['failed_step']}: "
                f"{reason['summary']}",
                data={**mesh_evidence, "diagnosis": reason},
            )

            if reason["log_tail"]:
                s.emit(
                    ev.MESH_TOOL,
                    f"Tail of {reason['log_name']}:\n{reason['log_tail']}",
                    status="FAIL",
                )

            return self.finish("MESH_REJECTED", reason["summary"])

        s.ok(
            ev.MESH_TOOL,
            f"checkMesh -allTopology -allGeometry: Mesh OK "
            f"({mesh_evidence.get('cells')} cells, "
            f"max non-orthogonality {mesh_evidence.get('max_non_orthogonality_deg')}).",
            data=mesh_evidence,
        )

        if args.mesh_only:
            s.emit(
                ev.ORCHESTRATOR,
                "Mesh stage verified; stopping before CFD (--mesh-only).",
            )
            return self.finish("MESH_ONLY", "Mesh gate passed.")

        # 6. LLM inspects the mesh evidence --------------------------------
        try:
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
                mesh_evidence,
                allow_fallback=args.allow_fallback,
            )
        except LLMUnavailable as exc:
            s.fail(ev.LLM, str(exc))
            return self.finish("LLM_UNAVAILABLE", str(exc))

        self.note_llm(record)
        save_json(
            self.out_dir / "llm_mesh_review.json",
            {"review": review.model_dump(), "llm_call": record.to_dict()},
        )

        record_llm(
            s,
            record,
            f"Mesh evidence reviewed -> {review.next_action}. {review.assessment}",
            data={"review": review.model_dump()},
        )

        if review.next_action != "PROCEED_TO_CFD_SETUP":
            s.emit(
                ev.ORCHESTRATOR,
                f"Reasoning step requested {review.next_action}; stopping before CFD.",
                status="FAIL",
            )
            return self.finish(
                "STOPPED_BY_REASONING", f"next_action={review.next_action}"
            )

        # 7. CFD setup ------------------------------------------------------
        control = runtime.read_text(case_path / "system/controlDict")
        solver = re.search(r"solver\s+(\w+);", control)

        s.ok(
            ev.CFD_SETUP,
            (
                f"Registered recipe written: {solver.group(1) if solver else 'shockFluid'} "
                f"via foamRun, Kurganov fluxes, Minmod reconstruction, Euler time "
                f"integration, maxCo {spec.max_courant}, endTime {spec.end_time_s} s, "
                "totalPressure/totalTemperature/directionMixed inlet, pressure-free "
                "zeroGradient outlet, adiabatic slip walls."
            ),
            data={
                "solver": "shockFluid",
                "ambient_imposed_at_exit": spec.ambient_imposed_at_exit,
                "end_time_s": spec.end_time_s,
                "max_courant": spec.max_courant,
            },
        )

        # 8. Verified initialization ---------------------------------------
        s.emit(ev.INITIALIZER, "Writing explicit per-cell quasi-1D initial state.")

        init = runtime.bash(
            f'cd {shlex.quote(str(root))}/code && '
            f'python3 initialize.py {shlex.quote(str(case_path))}',
            timeout=900,
        )

        runtime.fetch(
            case_path / "initialization_verified.json",
            self.out_dir / "initialization_verified.json",
        )

        if not init.ok:
            s.fail(
                ev.INITIALIZER,
                f"Initialization rejected: {init.stdout}{init.stderr}",
            )
            return self.finish("INIT_FAILED", init.stdout + init.stderr)

        init_record = json.loads(
            (self.out_dir / "initialization_verified.json").read_text()
        )

        s.ok(
            ev.INITIALIZER,
            (
                f"Read-back verified over {init_record['cells']} cells; "
                f"p in [{init_record['p_min']:.1f}, {init_record['p_max']:.1f}] Pa "
                f"spans the quasi-1D range required for this specification."
            ),
            data=init_record,
        )

        # 9. Execution ------------------------------------------------------
        s.emit(
            ev.EXECUTOR,
            f"Running foamRun/shockFluid to {spec.end_time_s} s "
            f"(bounded, serial).",
        )

        # execute.py enforces the wall-clock bound itself (the frozen
        # reference's REFERENCE_WALL_LIMIT_S), so the bound survives the
        # streaming call and terminates the solver's own process group rather
        # than only this side of the pipe.
        executed = runtime.bash(
            f'cd {shlex.quote(str(root))}/code && '
            f'REFERENCE_WALL_LIMIT_S={float(args.solver_timeout)} '
            f'python3 -u execute.py {shlex.quote(str(case_path))} --events',
            timeout=None,
            stream_prefix="[EXECUTOR]",
        )

        runtime.fetch(case_path / "execution.json", self.out_dir / "execution.json")

        execution: Dict[str, Any] = {}

        if (self.out_dir / "execution.json").exists():
            execution = json.loads((self.out_dir / "execution.json").read_text())

        runtime.fetch_tail(
            case_path / "log.foamRun", self.out_dir / "logs/log.foamRun.tail"
        )

        if not executed.ok or execution.get("status") != "COMPLETED":
            s.fail(
                ev.EXECUTOR,
                f"Solver did not complete: status={execution.get('status')} "
                f"returncode={execution.get('returncode')}.",
                data=execution,
            )
            return self.finish(
                "SOLVER_FAILED", f"status={execution.get('status')}"
            )

        s.ok(
            ev.EXECUTOR,
            (
                f"Solver completed to {execution['last_observed_time']} s in "
                f"{execution['wall_seconds']:.0f} s wall clock."
            ),
            data=execution,
        )

        # 10. Deterministic diagnostics ------------------------------------
        s.emit(ev.DIAGNOSTICS, "Recomputing all deterministic checks from native fields, logs and monitors.")

        validated = runtime.bash(
            f'cd {shlex.quote(str(root))}/code && '
            f'python3 validate.py {shlex.quote(str(case_path))}',
            timeout=1800,
        )

        got = runtime.fetch(
            case_path / "validation.json", self.out_dir / "validation.json"
        )
        runtime.fetch(
            case_path / "axial_profile.csv", self.out_dir / "axial_profile.csv"
        )

        if not got:
            s.fail(
                ev.DIAGNOSTICS,
                f"Validator produced no report: {validated.stdout}{validated.stderr}",
            )
            return self.finish("DIAGNOSTICS_FAILED", validated.stdout)

        validation = json.loads((self.out_dir / "validation.json").read_text())
        checks: Dict[str, bool] = validation["checks"]
        failed = [k for k, v in checks.items() if not v]

        s.emit(
            ev.DIAGNOSTICS,
            f"{len(checks) - len(failed)}/{len(checks)} deterministic checks passed."
            + (f" Failed: {', '.join(failed)}." if failed else ""),
            status="PASS" if not failed else "FAIL",
            data={"checks": checks},
        )

        # 11. Theory-blind evidence + LLM diagnosis -------------------------
        evidence = build_evidence_from_validation(
            validation,
            mesh_report=mesh_evidence,
            execution=execution,
            iteration=1,
            case_id=spec.case_id,
        )

        save_json(self.out_dir / "cfd_evidence.json", evidence.to_dict())

        problem = problem_from_spec(spec)

        try:
            decision, action_validation, record = diagnose(
                problem, evidence, allow_fallback=args.allow_fallback
            )
        except LLMUnavailable as exc:
            s.fail(ev.LLM, str(exc))
            return self.finish("LLM_UNAVAILABLE", str(exc))

        self.note_llm(record)

        save_json(
            self.out_dir / "agent_decision.json",
            {"decision": decision.to_dict(), "llm_call": record.to_dict()},
        )
        save_json(
            self.out_dir / "action_validation.json", asdict(action_validation)
        )

        record_llm(
            s,
            record,
            (
                f"Theory-blind diagnosis: {decision.diagnosis.value} -> "
                f"{decision.action.value}. {decision.reasoning_summary[:160]}"
            ),
            data={"decision": decision.to_dict()},
        )

        # 12. Deterministic action validator --------------------------------
        s.emit(
            ev.ACTION_VALIDATOR,
            (
                f"Proposed action {decision.action.value} "
                + ("APPROVED" if action_validation.approved else "REJECTED")
                + ": "
                + " ".join(action_validation.reasons)
            ),
            status="PASS" if action_validation.approved else "FAIL",
            data=asdict(action_validation),
        )

        # 13. Deterministic scientific acceptance ---------------------------
        accepted = validation["status"] == "PASS_SINGLE_MESH" and not failed

        acceptance = {
            "case_id": spec.case_id,
            "deterministic_status": validation["status"],
            "accepted": accepted,
            "failed_checks": failed,
            "authority": "deterministic validator (src/pipeline/nozzle/validate.py)",
            "llm_proposed_action": decision.action.value,
            "llm_action_approved_by_validator": action_validation.approved,
            "note": (
                "Acceptance is decided by the deterministic checks alone. The "
                "reasoning model's proposed action is recorded but has no "
                "acceptance authority. This is single-grid verification at the "
                "declared resolution; grid, timestep, wedge-angle and startup "
                "sensitivity remain properties of the frozen canonical "
                "reference campaign."
            ),
        }

        save_json(self.out_dir / "acceptance.json", acceptance)
        self.result["acceptance"] = acceptance
        self.result["validation_status"] = validation["status"]

        s.emit(
            ev.SCIENTIFIC_VALIDATOR,
            (
                f"Deterministic verdict: {validation['status']}"
                + ("" if accepted else f" (failed: {', '.join(failed)})")
            ),
            status="PASS" if accepted else "FAIL",
            data=acceptance,
        )

        # 14. Reporter: post-hoc comparison revealed here only ---------------
        final = validation["final"]

        report_payload = {
            "case_id": spec.case_id,
            "description": spec.description,
            "deterministic_verdict": validation["status"],
            "failed_checks": failed,
            "specification": spec.to_dict(),
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
                "min_downstream_slab_mach": validation["min_downstream_slab_Mach"],
                "cells": mesh_evidence.get("cells"),
                "wall_seconds": execution.get("wall_seconds"),
            },
            "llm_decision": decision.to_dict(),
            "llm_action_approved": action_validation.approved,
        }

        withheld = withheld_from_agent(validation)
        report_payload["post_hoc_quasi_1d_comparison"] = withheld.get("theory", {})
        report_payload["post_hoc_quasi_1d_error_pct"] = withheld.get(
            "theory_error_pct", {}
        )

        try:
            summary, record = summarize_case(
                report_payload, allow_fallback=args.allow_fallback
            )
        except LLMUnavailable as exc:
            s.fail(ev.LLM, str(exc))
            return self.finish("LLM_UNAVAILABLE", str(exc))

        self.note_llm(record)

        (self.out_dir / "ENGINEERING_SUMMARY.md").write_text(
            summary + "\n", encoding="utf-8"
        )
        save_json(self.out_dir / "report_payload.json", report_payload)

        s.emit(
            ev.REPORTER,
            f"Engineering summary written to {self.out_dir / 'ENGINEERING_SUMMARY.md'}.",
            status="PASS",
            llm_source=record.label,
            data={"llm_call": record.to_dict()},
        )

        s.emit(
            ev.ORCHESTRATOR,
            f"Runtime case preserved at {case_path} (delete manually when done).",
        )

        return self.finish(
            "ACCEPTED" if accepted else "REJECTED_BY_VALIDATOR",
            validation["status"],
        )


# ----------------------------------------------------------------------


def load_prompt(args: argparse.Namespace, case: Optional[str]) -> str:
    if args.prompt:
        return args.prompt

    if args.prompt_file:
        return Path(args.prompt_file).read_text(encoding="utf-8")

    if case:
        return PROMPTS[case].read_text(encoding="utf-8")

    raise SystemExit("Supply --case, --prompt or --prompt-file.")


def main() -> int:
    ap = argparse.ArgumentParser(
        description="End-to-end LLM-driven nozzle CFD demonstration."
    )
    ap.add_argument(
        "--case",
        choices=["A", "B", "C", "ALL"],
        help="Run one of the three demonstration cases, or all three.",
    )
    ap.add_argument("--prompt", help="Natural-language engineering request.")
    ap.add_argument("--prompt-file", help="File holding the engineering request.")
    ap.add_argument("--out", default=str(_REPO_ROOT / "demo/nozzle_e2e"))

    ap.add_argument("--scale", type=float, default=1.0)
    ap.add_argument("--end-time", type=float, default=0.006)
    ap.add_argument("--max-courant", type=float, default=0.4)
    ap.add_argument("--wedge-angle", type=float, default=5.0)

    ap.add_argument(
        "--allow-fallback",
        action="store_true",
        help=(
            "Permit the deterministic parser/diagnosis when the LLM is "
            "unavailable. Every such step is recorded as "
            "deterministic_fallback and is never presented as the model."
        ),
    )
    ap.add_argument(
        "--plan-only",
        action="store_true",
        help="Interpret, scope-gate and generate the OpenFOAM case, then stop.",
    )
    ap.add_argument(
        "--mesh-only",
        action="store_true",
        help=(
            "Run as far as the deterministic mesh gate and stop. Use this to "
            "diagnose the mesh stage in seconds instead of minutes."
        ),
    )
    ap.add_argument("--distro", help="Override the WSL distribution name.")
    ap.add_argument("--bashrc", help="Override the OpenFOAM bashrc path.")
    ap.add_argument("--solver-timeout", type=float, default=7200.0)

    args = ap.parse_args()

    cases: List[Optional[str]]

    if args.case == "ALL":
        cases = ["A", "B", "C"]
    elif args.case:
        cases = [args.case]
    else:
        cases = [None]

    results = []

    for case in cases:
        prompt = load_prompt(args, case)
        label = CASE_LABELS.get(case or "", "case_from_prompt")

        print()
        print("=" * 78)
        print(f"  NOZZLE E2E  |  {label}")
        print("=" * 78)

        run = CaseRun(args, label, prompt)

        try:
            results.append(run.run())
        except FoamRuntimeError as exc:
            run.stream.fail(ev.ORCHESTRATOR, f"Runtime error: {exc}")
            results.append(run.finish("RUNTIME_ERROR", str(exc)))
        except Exception as exc:  # noqa: BLE001
            run.stream.fail(ev.ORCHESTRATOR, f"Unhandled error: {exc}")
            results.append(run.finish("ERROR", str(exc)))

    campaign = {
        "generated": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "cases": [
            {
                "label": r["label"],
                "case_id": r.get("case_id"),
                "status": r["status"],
                "validation_status": r.get("validation_status"),
                "llm_sources": r.get("event_summary", {}).get("llm_sources", []),
            }
            for r in results
        ],
        "note": (
            "All cases used the same parameterized pipeline derived from the "
            "frozen canonical reference. Acceptance is deterministic."
        ),
    }

    save_json(Path(args.out).resolve() / "CAMPAIGN_SUMMARY.json", campaign)

    print()
    print("=" * 78)

    for row in campaign["cases"]:
        print(f"  {row['label']:<22} {row['status']:<26} {row['validation_status'] or ''}")

    print("=" * 78)

    return (
        0
        if all(
            r["status"] in {"ACCEPTED", "PLAN_ONLY", "MESH_ONLY"}
            for r in results
        )
        else 1
    )


if __name__ == "__main__":
    raise SystemExit(main())
