#!/usr/bin/env python3
"""Standalone 2D forward-facing-step autonomous CFD agent.

    natural-language request
      -> LLM interpretation            src/agents/forward_step_spec_agent.py
      -> deterministic scope gate      src/reasoning/forward_step_scope_gate.py
      -> case construction             src/pipeline/forward_step_2d/build.py
      -> blockMesh + checkMesh         src/pipeline/forward_step_2d/mesh_case.sh
      -> bounded shockFluid execution  src/pipeline/forward_step_2d/execute.py
      -> transient diagnostics         src/pipeline/forward_step_2d/diagnostics.py
      -> native field images           src/pipeline/forward_step_2d/plots.py
      -> multimodal observation        src/agents/cfd_visual_observer.py
      -> reference-blind LLM diagnosis src/reasoning/forward_step_diagnosis.py
      -> deterministic action gate     src/reasoning/forward_step_actions.py
      -> approved action executed, loop
      -> deterministic validator       src/pipeline/forward_step_2d/validate.py
      -> LLM scientific summary

AUTHORITY
---------
The Python orchestration layer executes every tool. The LLM never invokes
OpenFOAM and never edits a dictionary: it interprets the request, reads
evidence and proposes one action from a bounded set. A deterministic validator
decides whether that action may run, and a separate deterministic validator
decides acceptance.

Usage
-----
    python scripts/run_forward_step_2d.py --request "..."
    python scripts/run_forward_step_2d.py --request-file request.txt
    python scripts/run_forward_step_2d.py --request "..." --plan-only
"""
from __future__ import annotations

import argparse
import json
import shlex
import sys
import time
from pathlib import Path, PurePosixPath
from typing import Any, Dict, List, Optional

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from src.agents.forward_step_spec_agent import interpret_request  # noqa: E402
from src.agents.llm_provenance import LLMCallRecord, LLMUnavailable  # noqa: E402
from src.pipeline.foam_runtime import FoamRuntime, FoamRuntimeError  # noqa: E402
from src.pipeline.forward_step_2d.build import build as build_case  # noqa: E402
from src.pipeline.forward_step_2d.spec import ForwardStep2DSpec  # noqa: E402
from src.reasoning.forward_step_actions import ForwardStepAction  # noqa: E402
from src.reasoning.forward_step_diagnosis import diagnose  # noqa: E402
from src.reasoning.forward_step_scope_gate import evaluate_scope  # noqa: E402
from src.reporting import event_stream as ev  # noqa: E402
from src.reporting.event_stream import EventStream  # noqa: E402

PIPELINE_DIR = _REPO_ROOT / "src/pipeline/forward_step_2d"
TEMPLATE_DIR = _REPO_ROOT / "src/pipeline/forward_step/template"

#: Figures handed to the multimodal observer and the diagnosis payload. These
#: are flow-field and mesh images: things a reader can look at and judge.
FIELD_IMAGE_KEYS = [
    "Mach_field",
    "p_field",
    "rho_field",
    "T_field",
    "speed_field",
    "mesh_cells",
    "shock_density_contours",
    "shock_front_history",
]

#: Figures archived into the run directory. This is a superset: the transient
#: conservation plot is evidence a reader of the handoff needs, but it is a
#: numerical audit trace rather than a flow image, so it is archived without
#: being added to what the observer is asked to interpret. The first live run
#: produced nine figures and returned eight, because this list did not exist.
ARCHIVE_IMAGE_KEYS = FIELD_IMAGE_KEYS + ["transient_conservation"]


def fetch_binary(runtime: FoamRuntime, remote: PurePosixPath, local: Path) -> bool:
    """Copy a binary runtime file (a PNG) to the host.

    FoamRuntime.fetch is a text-mode `cat`, which corrupts binary payloads, so
    the bytes are base64-encoded inside the runtime and decoded here. This is
    implemented in the forward-step runner rather than by extending the shared
    nozzle runtime module.
    """
    result = runtime.bash(
        f"test -f {shlex.quote(str(remote))} && base64 -w0 -- {shlex.quote(str(remote))}",
        foam=False,
        timeout=300,
    )
    if not result.ok or not result.stdout.strip():
        return False
    import base64

    try:
        payload = base64.b64decode(result.stdout.strip(), validate=True)
    except Exception:  # noqa: BLE001
        return False
    local.parent.mkdir(parents=True, exist_ok=True)
    local.write_bytes(payload)
    return True


def save_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")


class ForwardStepRun:
    def __init__(self, args: argparse.Namespace, request: str) -> None:
        self.args = args
        self.request = request
        self.out = Path(args.out).resolve()
        self.out.mkdir(parents=True, exist_ok=True)
        self.stream = EventStream(self.out, case_id="forward_step_2d")
        self.llm_calls: List[Dict[str, Any]] = []
        self.provenance: Dict[str, Any] = {
            "family": "forward_step_2d",
            "request": request,
            "started": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "iterations": [],
        }
        self.runtime: Optional[FoamRuntime] = None
        self.result: Dict[str, Any] = {"status": "INCOMPLETE"}

    # ------------------------------------------------------------------

    def note_llm(self, record: LLMCallRecord) -> None:
        self.llm_calls.append(record.to_dict())

    def finish(self, status: str, message: str = "") -> Dict[str, Any]:
        self.result["status"] = status
        self.result["message"] = message
        self.provenance["llm_calls"] = self.llm_calls
        self.provenance["final_status"] = status
        self.provenance["event_summary"] = self.stream.summary()
        save_json(self.out / "agent_result.json", self.result)
        save_json(self.out / "provenance.json", self.provenance)
        return self.result

    # ------------------------------------------------------------------

    def run(self) -> Dict[str, Any]:
        s = self.stream
        args = self.args

        s.emit(
            ev.ORCHESTRATOR,
            f"Engineering request received ({len(self.request)} characters).",
        )
        (self.out / "request.txt").write_text(self.request, encoding="utf-8")

        # 1. LLM interpretation -----------------------------------------
        try:
            spec, raw, spec_prov, record = interpret_request(
                self.request, allow_fallback=False
            )
        except LLMUnavailable as exc:
            s.fail(ev.LLM, str(exc))
            return self.finish("LLM_UNAVAILABLE", str(exc))

        self.note_llm(record)
        save_json(
            self.out / "llm_interpretation.json",
            {
                "raw": raw.model_dump(),
                "spec": spec.to_dict() if spec else None,
                "field_provenance": spec_prov,
                "llm_call": record.to_dict(),
            },
        )
        self.provenance["llm_interpretation"] = raw.model_dump()
        self.provenance["field_provenance"] = spec_prov

        # Reporting objectives are questions about the finished run. They are
        # recorded and answered by the reporting stage; they are never an
        # input to the deterministic scope gate, which rules on simulation
        # requirements only.
        objectives = list(getattr(raw, "reporting_objectives", []) or [])
        self.result["reporting_objectives"] = objectives
        self.provenance["reporting_objectives"] = objectives
        if objectives:
            s.emit(
                ev.ORCHESTRATOR,
                f"{len(objectives)} reporting objective(s) recorded for the "
                "final summary; these do not affect case setup or the scope "
                "gate.",
                data={"reporting_objectives": objectives},
            )

        if raw.requests_unsupported_physics:
            s.fail(
                ev.LLM,
                "Interpretation flags unsupported physics: "
                + "; ".join(raw.unsupported_notes or ["unspecified"]),
                llm_source=record.label,
            )

        if spec is None:
            reason = spec_prov.get("construction_error", "invalid specification")
            s.fail(ev.SCOPE_GATE, f"REJECT_UNSUPPORTED: {reason}")
            return self.finish("REJECTED_UNSUPPORTED", reason)

        s.emit(
            ev.LLM,
            f"Interpreted: Mach {spec.mach:g}, step height {spec.step_height:g}, "
            f"step at x = {spec.step_x:g}, {spec.cells} cells, "
            f"end time {spec.end_time:g}.",
            llm_source=record.label,
            data={"stated": spec_prov.get("stated_by_user")},
        )

        # 2. deterministic scope gate -----------------------------------
        gate = evaluate_scope(spec, self.request)
        save_json(self.out / "scope_gate.json", gate.to_dict())
        self.provenance["scope_gate"] = gate.to_dict()
        self.provenance["spec"] = spec.to_dict()

        if not gate.approved:
            s.fail(
                ev.SCOPE_GATE,
                "REJECT_UNSUPPORTED: " + " ".join(gate.reasons),
                data=gate.to_dict(),
            )
            return self.finish("REJECTED_UNSUPPORTED", "; ".join(gate.reasons))

        s.ok(
            ev.SCOPE_GATE,
            f"In scope: Mach {spec.mach:g}, step/height "
            f"{gate.measurements['step_height_fraction']:.3f}, "
            f"{spec.cells} cells, dx/dy {gate.measurements['cell_aspect_ratio']:.3f}.",
            data=gate.to_dict(),
        )
        for question in gate.clarification_needed:
            s.emit(ev.SCOPE_GATE, "Clarification noted: " + question)

        if args.plan_only:
            local = self.out / "generated_case"
            if local.exists():
                import shutil

                shutil.rmtree(local)
            build_case(spec, local)
            s.ok(
                ev.CFD_SETUP,
                f"Case generated locally at {local}. Stopping before CFD (--plan-only).",
            )
            return self.finish("PLAN_ONLY", "No CFD executed.")

        # 3. runtime preflight ------------------------------------------
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

        save_json(self.out / "runtime_preflight.json", info)
        self.provenance["runtime"] = info

        if not info["ok"]:
            s.fail(ev.PREFLIGHT, f"Runtime unavailable: {info.get('reason')}", data=info)
            return self.finish("NO_OPENFOAM", str(info.get("reason")))

        s.ok(
            ev.PREFLIGHT,
            f"OpenFOAM Foundation v{info['openfoam_version']} ready "
            f"({runtime.mode}, numpy {info['numpy']}).",
        )

        # 4. stage code and build ---------------------------------------
        stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
        root = runtime.make_root(f"{stamp}-forward-step-2d")
        code = root / "code"

        runtime.bash(
            f"mkdir -p {shlex.quote(str(code))}/pipeline/forward_step_2d "
            f"{shlex.quote(str(code))}/pipeline/forward_step/template",
            foam=False,
            timeout=120,
        )
        self._stage_tree(runtime, code)

        spec_path = code / "spec.json"
        runtime.write_text(spec_path, json.dumps(spec.to_dict(), indent=2))

        case = root / "case"
        self.provenance["runtime_case"] = str(case)
        self.result["runtime_case"] = str(case)

        built = runtime.bash(
            f"cd {shlex.quote(str(code))} && "
            f"python3 -m pipeline.forward_step_2d.build {shlex.quote(str(case))} "
            f"--spec {shlex.quote(str(spec_path))}",
            timeout=300,
        )
        if not built.ok:
            s.fail(ev.CFD_SETUP, f"Case generation failed: {built.stdout}{built.stderr}")
            return self.finish("BUILD_FAILED", built.stdout + built.stderr)

        s.ok(
            ev.CFD_SETUP,
            f"Case generated: {spec.cells} cells, blocks {spec.block_cells}, "
            f"dx {spec.dx:.4g}, dy {spec.dy:.4g}. Trusted recipe copied unchanged "
            "(Kurganov, vanLeer/vanLeerV, Euler, shockFluid).",
        )

        # 5. mesh -------------------------------------------------------
        meshed = runtime.bash(
            f"bash {shlex.quote(str(code))}/pipeline/forward_step_2d/mesh_case.sh "
            f"{shlex.quote(str(case))}",
            timeout=900,
        )
        logs = self.out / "logs"
        logs.mkdir(exist_ok=True)
        for name in ("log.blockMesh", "log.checkMesh", "log.centres", "log.volumes"):
            runtime.fetch(case / name, logs / name)
        runtime.fetch(case / "mesh_steps.json", self.out / "mesh_steps.json")

        steps = {}
        if (self.out / "mesh_steps.json").exists():
            steps = json.loads((self.out / "mesh_steps.json").read_text())
        for step in steps.get("steps", []):
            s.emit(
                ev.MESH_TOOL,
                f"{step['name']}: returncode {step['returncode']}",
                status="PASS" if step["returncode"] == 0 else "FAIL",
            )

        if not meshed.ok:
            failed = steps.get("failed_step") or "mesh shell"
            detail = (meshed.stderr or meshed.stdout or "")[-800:]
            s.fail(ev.MESH_TOOL, f"Mesh gate failed at {failed}: {detail}")
            return self.finish("MESH_REJECTED", f"failed at {failed}")

        s.ok(ev.MESH_TOOL, "checkMesh: Mesh OK, 2 solution directions.")

        # 6. iterate ----------------------------------------------------
        current = spec
        iteration = 0
        pending_action: Optional[str] = None
        pending_changes: Dict[str, Any] = {}

        while iteration < args.max_iterations:
            iteration += 1
            append = iteration > 1

            s.emit(
                ev.EXECUTOR,
                f"Iteration {iteration}: foamRun -case (shockFluid) to "
                f"t = {current.end_time:g}"
                + (" (continuation)" if append else ""),
            )

            executed = runtime.bash(
                f"cd {shlex.quote(str(code))} && "
                f"FORWARD_STEP_WALL_LIMIT_S={float(args.solver_timeout)} "
                f"python3 -u -m pipeline.forward_step_2d.execute "
                f"{shlex.quote(str(case))} --events"
                + (" --append" if append else ""),
                timeout=None,
                stream_prefix="[EXECUTOR]",
            )
            runtime.fetch(case / "execution.json", self.out / "execution.json")
            runtime.fetch_tail(case / "log.foamRun", logs / "log.foamRun.tail")
            # The head carries the startup banner and any pre-time-loop
            # dictionary error, so both ends of the log come back.
            runtime.fetch_head(case / "log.foamRun", logs / "log.foamRun.head")

            execution = []
            if (self.out / "execution.json").exists():
                execution = json.loads((self.out / "execution.json").read_text())
            last = execution[-1] if execution else {}

            s.emit(
                ev.EXECUTOR,
                f"Solver status {last.get('status')} at t = "
                f"{last.get('last_observed_time')} after "
                f"{last.get('wall_seconds', 0):.0f} s.",
                status="PASS" if last.get("status") == "COMPLETED" else "FAIL",
            )

            # evidence -------------------------------------------------
            iteration_out = self.out / f"iteration_{iteration:02d}"
            s.emit(ev.DIAGNOSTICS, "Collecting transient diagnostics and field images.")

            collected = runtime.bash(
                f"cd {shlex.quote(str(code))} && "
                f"python3 -m pipeline.forward_step_2d.collect_evidence "
                f"{shlex.quote(str(case))} {shlex.quote(str(root / f'evidence_{iteration:02d}'))}"
                + (
                    f" --reference {shlex.quote(args.reference)}"
                    if args.reference
                    else ""
                ),
                timeout=1800,
            )

            remote_evidence = root / f"evidence_{iteration:02d}"
            iteration_out.mkdir(parents=True, exist_ok=True)
            for name in (
                "diagnostics.json",
                "validation.json",
                "evidence_index.json",
                "transient_mass.csv",
                "stored_totals.csv",
                "shock_front_history.csv",
            ):
                runtime.fetch(remote_evidence / name, iteration_out / name)

            if not (iteration_out / "diagnostics.json").exists():
                s.fail(
                    ev.DIAGNOSTICS,
                    f"Evidence collection produced nothing: {collected.stdout}{collected.stderr}",
                )
                return self.finish("DIAGNOSTICS_FAILED", collected.stdout)

            diagnostics = json.loads((iteration_out / "diagnostics.json").read_text())
            validation = json.loads((iteration_out / "validation.json").read_text())
            index = (
                json.loads((iteration_out / "evidence_index.json").read_text())
                if (iteration_out / "evidence_index.json").exists()
                else {}
            )

            images: Dict[str, str] = {}
            figures_dir = iteration_out / "figures"
            figures_dir.mkdir(exist_ok=True)
            for key in ARCHIVE_IMAGE_KEYS:
                remote = index.get("figures", {}).get(key)
                if not remote:
                    continue
                local = figures_dir / f"{key}.png"
                if fetch_binary(runtime, PurePosixPath(remote), local):
                    if key in FIELD_IMAGE_KEYS:
                        images[key] = str(local)

            s.emit(
                ev.DIAGNOSTICS,
                f"{len(validation['hard_checks']) - len(validation['failed_checks'])}"
                f"/{len(validation['hard_checks'])} hard checks passed; "
                f"status {validation['status']}; {len(images)} field images."
                + (
                    f" Failed: {', '.join(validation['failed_checks'])}."
                    if validation["failed_checks"]
                    else ""
                ),
                status="PASS" if not validation["failed_checks"] else "FAIL",
            )

            # multimodal observation -----------------------------------
            visual: Dict[str, Any] = {"status": "not_attempted"}
            if images:
                from src.agents.cfd_visual_observer import observe_cfd_images

                visual = observe_cfd_images(
                    image_paths=images,
                    numerical_context={
                        "family": "forward_step_2d",
                        "iteration": iteration,
                        "deterministic_status": validation["status"],
                        "failed_checks": validation["failed_checks"],
                        "final_time": diagnostics["final_time"],
                        "requested_end_time": diagnostics["requested_end_time"],
                        "field_ranges": diagnostics["final_ranges"],
                        "note": (
                            "Transient benchmark. No reference or analytical "
                            "target values are included."
                        ),
                    },
                )
                save_json(iteration_out / "visual_observation.json", visual)
                s.emit(
                    ev.LLM,
                    f"Multimodal observation: {visual.get('status')}",
                    llm_source="LLM:multimodal-visual-observer",
                )

            # reference-blind diagnosis --------------------------------
            try:
                decision, action_gate, record, payload = diagnose(
                    current,
                    diagnostics,
                    validation,
                    images=images,
                    visual_observation=visual,
                    max_end_time=args.max_end_time,
                    iterations_used=iteration,
                    max_iterations=args.max_iterations,
                )
            except LLMUnavailable as exc:
                s.fail(ev.LLM, str(exc))
                return self.finish("LLM_UNAVAILABLE", str(exc))

            self.note_llm(record)
            save_json(iteration_out / "llm_evidence_payload.json", payload)
            save_json(
                iteration_out / "agent_decision.json",
                {"decision": decision.model_dump(), "llm_call": record.to_dict()},
            )
            save_json(iteration_out / "action_validation.json", action_gate.to_dict())

            s.emit(
                ev.LLM,
                f"Diagnosis {decision.diagnosis} -> {decision.action} "
                f"({decision.confidence}). {decision.reasoning_summary[:180]}",
                llm_source=record.label,
            )
            s.emit(
                ev.ACTION_VALIDATOR,
                f"{decision.action} "
                + ("APPROVED" if action_gate.approved else "REJECTED")
                + ": "
                + " ".join(action_gate.reasons),
                status="PASS" if action_gate.approved else "FAIL",
            )

            self.provenance["iterations"].append(
                {
                    "iteration": iteration,
                    "spec": current.to_dict(),
                    "execution": last,
                    "validation_status": validation["status"],
                    "failed_checks": validation["failed_checks"],
                    "images": sorted(images),
                    "visual_status": visual.get("status"),
                    "llm_diagnosis": decision.diagnosis,
                    "llm_action": decision.action,
                    "action_approved": action_gate.approved,
                    "action_reasons": action_gate.reasons,
                }
            )

            accepted = (
                validation["status"] == "PASS_2D_FORWARD_STEP"
                and decision.action == ForwardStepAction.ACCEPT.value
                and action_gate.approved
            )

            s.emit(
                ev.SCIENTIFIC_VALIDATOR,
                f"Deterministic verdict: {validation['status']}",
                status="PASS" if validation["status"] == "PASS_2D_FORWARD_STEP" else "FAIL",
            )

            if accepted:
                self.result["validation_status"] = validation["status"]
                self._summarize(spec, diagnostics, validation, decision, iteration_out)
                return self.finish("ACCEPTED", validation["status"])

            if not action_gate.approved:
                self._summarize(spec, diagnostics, validation, decision, iteration_out)
                return self.finish(
                    "STOPPED_ACTION_REFUSED",
                    f"{decision.action} refused: {' '.join(action_gate.reasons)}",
                )

            if decision.action in {
                ForwardStepAction.REJECT_UNSUPPORTED.value,
                ForwardStepAction.FAIL_SAFELY.value,
                ForwardStepAction.REQUEST_CLARIFICATION.value,
            }:
                self._summarize(spec, diagnostics, validation, decision, iteration_out)
                return self.finish(f"STOPPED_{decision.action}", decision.reasoning_summary)

            # execute the approved action ------------------------------
            pending_action = decision.action
            pending_changes = action_gate.resulting_changes

            if pending_action == ForwardStepAction.CONTINUE_RUN.value:
                s.emit(
                    ev.ORCHESTRATOR,
                    f"Approved CONTINUE_RUN: resuming from latestTime toward "
                    f"t = {current.end_time:g}.",
                )
                runtime.bash(
                    f"cd {shlex.quote(str(case))} && "
                    "sed -i 's/^startFrom .*/startFrom       latestTime;/' system/controlDict",
                    foam=False,
                    timeout=120,
                )
                continue

            if pending_action in {
                ForwardStepAction.EXTEND_END_TIME.value,
                ForwardStepAction.REDUCE_MAX_CO.value,
            }:
                current = current.with_changes(**{
                    k: v for k, v in pending_changes.items()
                    if k in {"end_time", "max_co"}
                })
                s.emit(
                    ev.ORCHESTRATOR,
                    f"Approved {pending_action}: {pending_changes}.",
                )
                runtime.write_text(
                    case / "spec.json", json.dumps(current.to_dict(), indent=2)
                )
                for key, entry in (("end_time", "endTime"), ("max_co", "maxCo")):
                    if key in pending_changes:
                        runtime.bash(
                            f"cd {shlex.quote(str(case))} && "
                            f"sed -i 's/^{entry} .*/{entry} {pending_changes[key]:.12g};/' "
                            "system/controlDict",
                            foam=False,
                            timeout=120,
                        )
                runtime.bash(
                    f"cd {shlex.quote(str(case))} && "
                    "sed -i 's/^startFrom .*/startFrom       latestTime;/' system/controlDict",
                    foam=False,
                    timeout=120,
                )
                continue

            s.emit(
                ev.ORCHESTRATOR,
                f"Approved action {pending_action} requires a rebuild, which this "
                "standalone runner does not perform in-loop; stopping with evidence "
                "preserved.",
                status="FAIL",
            )
            self._summarize(spec, diagnostics, validation, decision, iteration_out)
            return self.finish("STOPPED_REBUILD_REQUIRED", pending_action)

        return self.finish(
            "ITERATION_BUDGET_EXHAUSTED",
            f"{args.max_iterations} iterations without deterministic acceptance",
        )

    # ------------------------------------------------------------------

    def _stage_tree(self, runtime: FoamRuntime, code: PurePosixPath) -> None:
        """Copy the package and the read-only template into the runtime."""
        source = runtime.to_runtime_path(PIPELINE_DIR)
        template = runtime.to_runtime_path(TEMPLATE_DIR)
        target = code / "pipeline/forward_step_2d"
        template_target = code / "pipeline/forward_step/template"

        result = runtime.bash(
            f"cp -- {shlex.quote(source)}/*.py {shlex.quote(source)}/*.sh "
            f"{shlex.quote(str(target))}/ && "
            f"cp -r -- {shlex.quote(template)}/* {shlex.quote(str(template_target))}/ && "
            f"sed -i 's/\\r$//' {shlex.quote(str(target))}/*.py {shlex.quote(str(target))}/*.sh && "
            f"chmod +x {shlex.quote(str(target))}/*.sh && "
            f"touch {shlex.quote(str(code))}/pipeline/__init__.py "
            f"{shlex.quote(str(code))}/pipeline/forward_step/__init__.py && "
            f"ls {shlex.quote(str(target))}",
            foam=False,
            timeout=180,
        )
        if not result.ok:
            raise FoamRuntimeError(
                f"Could not stage pipeline code: {result.stderr or result.stdout}"
            )

    def _summarize(self, spec, diagnostics, validation, decision, iteration_out) -> None:
        """Final LLM scientific summary. Reference material is revealed here only."""
        from src.agents.nozzle_demo_agents import summarize_case

        payload = {
            "family": "2D forward-facing step, inviscid compressible Euler",
            "solver": "OpenFOAM Foundation v14 shockFluid via foamRun",
            "specification": spec.to_dict(),
            "deterministic_verdict": validation["status"],
            "failed_checks": validation["failed_checks"],
            "measured": {
                "final_time": diagnostics["final_time"],
                "cells": diagnostics["cells"],
                "steps": diagnostics["steps"],
                "runtime_seconds": diagnostics["runtime_seconds"],
                "field_ranges": diagnostics["final_ranges"],
                "courant": diagnostics["Co"],
                "transient_conservation": diagnostics["mass"],
                "compression_structure": diagnostics.get("shock", {}),
            },
            "llm_decision": decision.model_dump(),
            "reference_comparison": validation.get("reference_comparison"),
            "scope_note": (
                "Registered 2D forward-step Euler family only. Transient "
                "benchmark: no steady state is claimed. No mesh-independence, "
                "no experimental validation, no 3D claim."
            ),
        }
        try:
            summary, record = summarize_case(payload, allow_fallback=True)
            self.note_llm(record)
            (self.out / "SCIENTIFIC_SUMMARY.md").write_text(summary + "\n", encoding="utf-8")
            self.stream.emit(
                ev.REPORTER,
                "Scientific summary written.",
                status="PASS",
                llm_source=record.label,
            )
        except Exception as exc:  # noqa: BLE001
            self.stream.emit(ev.REPORTER, f"Summary unavailable: {exc}", status="FAIL")
        save_json(self.out / "report_payload.json", payload)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    source = ap.add_mutually_exclusive_group(required=True)
    source.add_argument("--request", help="Natural-language engineering request.")
    source.add_argument("--request-file", help="File holding the request.")

    ap.add_argument("--out", default=str(_REPO_ROOT / "demo/forward_step_2d"))
    ap.add_argument("--max-iterations", type=int, default=4)
    ap.add_argument("--max-end-time", type=float, default=12.0)
    ap.add_argument("--solver-timeout", type=float, default=7200.0)
    ap.add_argument("--reference", default=None, help="Trusted reference .npz.")
    ap.add_argument("--plan-only", action="store_true")
    ap.add_argument("--distro")
    ap.add_argument("--bashrc")

    args = ap.parse_args()
    request = (
        args.request
        if args.request
        else Path(args.request_file).read_text(encoding="utf-8")
    )

    print()
    print("=" * 78)
    print("  2D FORWARD-STEP AUTONOMOUS CFD AGENT")
    print("=" * 78)

    run = ForwardStepRun(args, request)
    try:
        result = run.run()
    except FoamRuntimeError as exc:
        run.stream.fail(ev.ORCHESTRATOR, f"Runtime error: {exc}")
        result = run.finish("RUNTIME_ERROR", str(exc))
    except Exception as exc:  # noqa: BLE001
        run.stream.fail(ev.ORCHESTRATOR, f"Unhandled error: {exc}")
        result = run.finish("ERROR", str(exc))

    print()
    print("=" * 78)
    print(f"  {result['status']}   {result.get('message', '')}")
    print("=" * 78)
    return 0 if result["status"] in {"ACCEPTED", "PLAN_ONLY"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
