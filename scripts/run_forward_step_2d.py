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
from src.reasoning.forward_step_mesh_study import (  # noqa: E402
    assess_sensitivity,
    grid_record,
    refine,
)
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


#: Per-run documents that a resume would otherwise overwrite. They are the
#: record of what the agent decided last time, including a refused action, and
#: that record is development provenance in its own right.
HISTORY_FILES = (
    "agent_result.json",
    "provenance.json",
    "events.jsonl",
    "events.log",
    "SCIENTIFIC_SUMMARY.md",
    "report_payload.json",
)


def archive_prior_run(out: Path) -> Optional[Path]:
    """Copy a previous run's top-level documents aside before resuming.

    EventStream truncates events.jsonl and events.log when it opens, and
    finish() rewrites agent_result.json, so a resume into the same directory
    would erase the history it is supposed to continue. Per-iteration evidence
    is never touched: iteration_NN directories are additive and the resumed
    run numbers past them.
    """
    import shutil

    existing = [name for name in HISTORY_FILES if (out / name).is_file()]
    if not existing:
        return None

    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    archive = out / "history" / f"pre_resume_{stamp}"
    archive.mkdir(parents=True, exist_ok=True)
    for name in existing:
        shutil.copy2(out / name, archive / name)
    return archive


class ForwardStepRun:
    def __init__(self, args: argparse.Namespace, request: str) -> None:
        self.args = args
        self.request = request
        self.out = Path(args.out).resolve()
        self.out.mkdir(parents=True, exist_ok=True)

        # Resume bookkeeping, settled before the event stream opens because
        # opening it truncates the previous run's logs.
        self.resume_case: Optional[str] = getattr(args, "resume_case", None)
        self.history_archive: Optional[Path] = None
        self.iteration_offset = 0
        self.prior_iterations: List[Dict[str, Any]] = []
        if self.resume_case:
            self.history_archive = archive_prior_run(self.out)
            self.iteration_offset = len(
                [d for d in self.out.glob("iteration_*") if d.is_dir()]
            )
            prior = self.out / "provenance.json"
            if prior.is_file():
                try:
                    self.prior_iterations = json.loads(prior.read_text()).get(
                        "iterations", []
                    )
                except json.JSONDecodeError:
                    self.prior_iterations = []

        self.stream = EventStream(self.out, case_id="forward_step_2d")
        self.llm_calls: List[Dict[str, Any]] = []
        self.provenance: Dict[str, Any] = {
            "family": "forward_step_2d",
            "request": request,
            "started": time.strftime("%Y-%m-%dT%H:%M:%S"),
            # Carried forward so the resumed run's provenance holds the whole
            # history, including the iteration whose action was refused.
            "iterations": list(self.prior_iterations),
        }
        if self.resume_case:
            self.provenance["resume"] = {
                "resumed_case": self.resume_case,
                "solver_restarted_from_zero": False,
                "prior_iterations_preserved": len(self.prior_iterations),
                "iteration_numbering_continues_from": self.iteration_offset,
                "history_archive": (
                    str(self.history_archive) if self.history_archive else None
                ),
            }
        self.runtime: Optional[FoamRuntime] = None
        self.result: Dict[str, Any] = {"status": "INCOMPLETE"}
        #: One entry per grid level of the mesh-refinement study.
        self.study_levels: List[Dict[str, Any]] = []

    # ------------------------------------------------------------------

    def _earliest_recorded_end_time(self) -> Optional[float]:
        """The smallest execution horizon any preserved iteration recorded."""
        horizons = [
            float(entry["spec"]["end_time"])
            for entry in self.prior_iterations
            if isinstance(entry.get("spec"), dict)
            and entry["spec"].get("end_time") is not None
        ]
        return min(horizons) if horizons else None

    def note_llm(self, record: LLMCallRecord) -> None:
        self.llm_calls.append(record.to_dict())

    def finish(self, status: str, message: str = "") -> Dict[str, Any]:
        self.result["status"] = status
        self.result["message"] = message
        self.provenance["llm_calls"] = self.llm_calls
        self.provenance["final_status"] = status
        if self.study_levels:
            self.provenance["mesh_study"] = {
                "levels": self.study_levels,
                "intervention_history": [
                    {
                        "iteration": entry.get("iteration"),
                        "refinement_level": entry.get("refinement_level"),
                        "cells": entry.get("cells"),
                        "action": entry.get("llm_action"),
                        "approved": entry.get("action_approved"),
                        "validation_status": entry.get("validation_status"),
                        "mesh_sensitivity_status": entry.get(
                            "mesh_sensitivity_status"
                        ),
                    }
                    for entry in self.provenance.get("iterations", [])
                ],
            }
        self.provenance["event_summary"] = self.stream.summary()
        save_json(self.out / "agent_result.json", self.result)
        save_json(self.out / "provenance.json", self.provenance)
        return self.result

    # ------------------------------------------------------------------

    def run(self) -> Dict[str, Any]:
        if self.resume_case:
            return self.resume()
        return self.run_from_request()

    # ------------------------------------------------------------------

    def resume(self) -> Dict[str, Any]:
        """Continue an existing solved case under the current semantics.

        Nothing is re-solved. The case keeps the fields it already has, the
        loop numbers past the iterations already recorded, and the first pass
        collects evidence from the existing solution rather than invoking the
        solver: the point of a resume is that the calculation so far is
        evidence, not something to redo.
        """
        s = self.stream
        args = self.args
        case = PurePosixPath(self.resume_case)

        s.emit(
            ev.ORCHESTRATOR,
            f"Resuming an existing case at {case}. The solver will not be "
            "restarted from t = 0 and no existing field is rewritten.",
        )
        if self.history_archive:
            s.ok(
                ev.ORCHESTRATOR,
                f"Previous run documents archived to {self.history_archive.name}; "
                f"{self.iteration_offset} recorded iteration(s) preserved.",
            )

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
        if not info["ok"]:
            s.fail(ev.PREFLIGHT, f"Runtime unavailable: {info.get('reason')}")
            return self.finish("NO_OPENFOAM", str(info.get("reason")))
        save_json(self.out / "runtime_preflight.json", info)
        self.provenance["runtime"] = info
        s.ok(
            ev.PREFLIGHT,
            f"OpenFOAM Foundation v{info['openfoam_version']} ready "
            f"({runtime.mode}, numpy {info['numpy']}).",
        )

        present = runtime.bash(
            f"test -d {shlex.quote(str(case))} && "
            f"test -f {shlex.quote(str(case))}/spec.json && "
            f"test -f {shlex.quote(str(case))}/log.foamRun && echo PRESENT",
            foam=False,
            timeout=120,
        )
        if "PRESENT" not in present.stdout:
            message = (
                f"No solved case at {case}. A runtime cache is not permanent "
                "evidence; if it has been cleared the run cannot be resumed "
                "and would have to be reproduced from the request."
            )
            s.fail(ev.ORCHESTRATOR, message)
            return self.finish("RESUME_CASE_NOT_FOUND", message)

        spec_text = runtime.bash(
            f"cat {shlex.quote(str(case))}/spec.json", foam=False, timeout=120
        )
        spec = ForwardStep2DSpec.from_dict(json.loads(spec_text.stdout))

        # A case written before the horizons were separated carries only the
        # end_time it had last been extended to, so the horizon the user
        # actually asked the FIRST execution to run to is not in spec.json.
        # It is in the run's own provenance, and recovering it is what keeps
        # "for the initial CFD execution, use 0.5" visible after the loop has
        # moved on. Without this the resumed record would claim the request
        # asked for whatever the last extension happened to set.
        recovered = self._earliest_recorded_end_time()
        if recovered is not None and recovered < spec.initial_execution_end_time:
            spec = spec.with_changes(initial_execution_end_time=recovered)
            s.ok(
                ev.ORCHESTRATOR,
                f"Recovered the original initial execution horizon t = "
                f"{recovered:g} from the preserved run provenance.",
            )

        if args.final_target_end_time is not None:
            spec = spec.with_changes(
                final_target_end_time=float(args.final_target_end_time)
            )
        # Write the resolved horizons back so the case carries the semantics
        # the resumed loop is reasoning with.
        runtime.write_text(case / "spec.json", json.dumps(spec.to_dict(), indent=2))

        s.ok(
            ev.ORCHESTRATOR,
            f"Recovered specification: Mach {spec.mach:g}, {spec.cells} cells, "
            f"initial execution horizon t = {spec.initial_execution_end_time:g}, "
            f"current horizon t = {spec.end_time:g}, final target "
            f"t = {spec.final_target_end_time:g}.",
            data=spec.to_dict(),
        )
        self.provenance["spec"] = spec.to_dict()
        self.result["runtime_case"] = str(case)

        # A fresh code root: the resumed loop must run the CORRECTED pipeline,
        # not whatever was staged beside the case when it was first solved.
        stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
        root = runtime.make_root(f"{stamp}-forward-step-2d-resume")
        code = root / "code"
        runtime.bash(
            f"mkdir -p {shlex.quote(str(code))}/pipeline/forward_step_2d "
            f"{shlex.quote(str(code))}/pipeline/forward_step/template",
            foam=False,
            timeout=120,
        )
        self._stage_tree(runtime, code)
        s.ok(ev.ORCHESTRATOR, "Corrected pipeline staged for the resumed loop.")

        return self._iterate(runtime, root, code, case, spec, resumed=True)

    # ------------------------------------------------------------------

    def run_from_request(self) -> Dict[str, Any]:
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

        case = self.build_and_mesh(runtime, root, code, spec)
        if case is None:
            return self.result
        self.provenance["runtime_case"] = str(case)
        self.result["runtime_case"] = str(case)

        # 6. iterate ----------------------------------------------------
        return self._iterate(runtime, root, code, case, spec, resumed=False)

    # ------------------------------------------------------------------

    def build_and_mesh(
        self,
        runtime: FoamRuntime,
        root: PurePosixPath,
        code: PurePosixPath,
        spec: ForwardStep2DSpec,
    ) -> Optional[PurePosixPath]:
        """Generate and mesh one grid. Returns its case path, or None on refusal.

        Every grid goes through the same gate: blockMesh, checkMesh, two
        solution directions, cell centres and volumes. A refined grid is not
        exempt, so a refinement that produced an invalid mesh is reported as a
        mesh rejection rather than being carried into the study as a result.
        """
        s = self.stream
        level = spec.refinement_level
        # Each grid gets its own case directory: an existing grid's fields and
        # logs are never overwritten by the next one.
        case = root / (f"case_L{level}" if level else "case")
        suffix = f"_L{level}" if level else ""

        spec_path = code / f"spec{suffix}.json"
        runtime.write_text(spec_path, json.dumps(spec.to_dict(), indent=2))

        built = runtime.bash(
            f"cd {shlex.quote(str(code))} && "
            f"python3 -m pipeline.forward_step_2d.build {shlex.quote(str(case))} "
            f"--spec {shlex.quote(str(spec_path))}",
            timeout=300,
        )
        if not built.ok:
            s.fail(ev.CFD_SETUP, f"Case generation failed: {built.stdout}{built.stderr}")
            self.finish("BUILD_FAILED", built.stdout + built.stderr)
            return None

        s.ok(
            ev.CFD_SETUP,
            f"Grid level {level} generated: {spec.cells} cells, blocks "
            f"{spec.block_cells}, dx {spec.dx:.4g}, dy {spec.dy:.4g}. Trusted "
            "recipe copied unchanged (Kurganov, vanLeer/vanLeerV, Euler, "
            "shockFluid).",
        )

        meshed = runtime.bash(
            f"bash {shlex.quote(str(code))}/pipeline/forward_step_2d/mesh_case.sh "
            f"{shlex.quote(str(case))}",
            timeout=900,
        )
        logs = self.out / "logs"
        logs.mkdir(parents=True, exist_ok=True)
        for name in ("log.blockMesh", "log.checkMesh", "log.centres", "log.volumes"):
            runtime.fetch(case / name, logs / f"{name}{suffix}")
        steps_path = self.out / f"mesh_steps{suffix}.json"
        runtime.fetch(case / "mesh_steps.json", steps_path)

        steps = {}
        if steps_path.exists():
            steps = json.loads(steps_path.read_text())
        for step in steps.get("steps", []):
            s.emit(
                ev.MESH_TOOL,
                f"level {level} {step['name']}: returncode {step['returncode']}",
                status="PASS" if step["returncode"] == 0 else "FAIL",
            )

        if not meshed.ok:
            failed = steps.get("failed_step") or "mesh shell"
            detail = (meshed.stderr or meshed.stdout or "")[-800:]
            s.fail(ev.MESH_TOOL, f"Mesh gate failed at {failed}: {detail}")
            self.finish("MESH_REJECTED", f"level {level} failed at {failed}")
            return None

        s.ok(
            ev.MESH_TOOL,
            f"level {level} checkMesh: Mesh OK, 2 solution directions.",
        )
        return case

    # ------------------------------------------------------------------

    def _iterate(
        self,
        runtime: FoamRuntime,
        root: PurePosixPath,
        code: PurePosixPath,
        case: PurePosixPath,
        spec: ForwardStep2DSpec,
        *,
        resumed: bool,
    ) -> Dict[str, Any]:
        """The bounded closed loop, entered fresh or on an existing solution."""
        s = self.stream
        args = self.args

        logs = self.out / "logs"
        logs.mkdir(parents=True, exist_ok=True)

        current = spec
        # The case the last solver execution ran on. A continuation is only
        # meaningful within one mesh: OpenFOAM's latestTime restart reads
        # fields written on the grid it is restarting into, so a new mesh must
        # be a fresh solve from the physical initial condition. Comparing this
        # against the case about to run is what keeps that impossible to get
        # wrong by accident.
        last_executed_case: Optional[PurePosixPath] = None

        # A resumed run numbers past the iterations already on record, so
        # iteration_03 follows iteration_02 instead of overwriting it.
        iteration = self.iteration_offset
        limit = self.iteration_offset + args.max_iterations
        pending_action: Optional[str] = None
        pending_changes: Dict[str, Any] = {}

        # On a resume the solution at hand is already the product of a solver
        # run: re-executing it would redo work the case has done. The first
        # pass therefore goes straight to evidence collection.
        skip_execution = resumed

        while iteration < limit:
            iteration += 1
            # Continuation ONLY when this exact case has already been solved.
            append = last_executed_case == case

            if skip_execution:
                skip_execution = False
                s.emit(
                    ev.EXECUTOR,
                    f"Iteration {iteration}: no solver execution. The case is "
                    "already solved to its current horizon; its existing "
                    "fields are re-read as evidence.",
                )
            else:
                s.emit(
                    ev.EXECUTOR,
                    f"Iteration {iteration}: foamRun -case (shockFluid) on "
                    f"grid level {current.refinement_level} "
                    f"({current.cells} cells) to t = {current.end_time:g}"
                    + (
                        " (continuation)"
                        if append
                        else " (fresh solve from the physical initial condition)"
                    ),
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
                del executed  # status is read from execution.json, not stdout
                last_executed_case = case
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
                f"hard checks {validation.get('hard_checks_status')}; "
                f"disposition {validation['status']}; {len(images)} field images."
                + (
                    f" Failed: {', '.join(validation['failed_checks'])}."
                    if validation["failed_checks"]
                    else ""
                ),
                status="PASS" if not validation["failed_checks"] else "FAIL",
            )

            acceptance = validation.get("final_acceptance", {})
            if not acceptance.get("final_acceptable", True):
                s.emit(
                    ev.SCIENTIFIC_VALIDATOR,
                    "Current state is healthy but not finally acceptable: "
                    f"t = {acceptance.get('final_time')} of the required "
                    f"t = {acceptance.get('final_target_end_time')}.",
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

            # mesh-refinement study ------------------------------------
            #
            # One record per grid level, replaced rather than appended when
            # the same level is re-measured (an extended horizon on the same
            # mesh is still one grid). The cross-grid verdict is deterministic
            # and is computed before the model is consulted, so the model
            # reads it as evidence rather than supplying it.
            self.study_levels = [
                entry
                for entry in self.study_levels
                if entry["refinement_level"] != current.refinement_level
            ] + [grid_record(current, diagnostics, validation)]
            self.study_levels.sort(key=lambda entry: entry["refinement_level"])

            sensitivity = assess_sensitivity(
                self.study_levels,
                tolerance=args.sensitivity_tolerance,
                requested=current.sensitivity_assessment_requested,
            )
            save_json(iteration_out / "mesh_sensitivity.json", sensitivity)
            save_json(self.out / "MESH_SENSITIVITY.json", sensitivity)
            self.result["mesh_sensitivity_status"] = sensitivity["status"]

            if current.sensitivity_assessment_requested:
                s.emit(
                    ev.SCIENTIFIC_VALIDATOR,
                    f"Numerical sensitivity: {sensitivity['status']} "
                    f"({sensitivity['grids']} grid(s)). {sensitivity['reason']}",
                    status="PASS" if sensitivity["satisfied"] else "....",
                    data={"latest_comparison": sensitivity["latest_comparison"]},
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
                    sensitivity=sensitivity,
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
                    "hard_checks_status": validation.get("hard_checks_status"),
                    "refinement_level": current.refinement_level,
                    "cells": current.cells,
                    "dx": current.dx,
                    "dy": current.dy,
                    "runtime_case": str(case),
                    "solver_continuation": append,
                    "mesh_sensitivity_status": sensitivity["status"],
                    "final_acceptance": validation.get("final_acceptance"),
                    "failed_checks": validation["failed_checks"],
                    "images": sorted(images),
                    "visual_status": visual.get("status"),
                    "llm_diagnosis": decision.diagnosis,
                    "llm_action": decision.action,
                    # Whether the model's restatement of the two horizons
                    # matched the deterministic evidence. A mismatch is not
                    # corrected here - the gate rules regardless - but it is
                    # recorded, because a model that misreads the horizons is
                    # exactly what stalled this loop once.
                    "llm_horizon_reading": {
                        "current_horizon_reached": decision.current_horizon_reached,
                        "final_target_reached": decision.final_target_reached,
                        "agrees_with_evidence": (
                            decision.current_horizon_reached
                            == bool(diagnostics.get("reached_requested_end_time"))
                            and decision.final_target_reached
                            == bool(acceptance.get("reached_final_target"))
                        ),
                    },
                    "action_approved": action_gate.approved,
                    "action_reasons": action_gate.reasons,
                    "solver_executed_this_iteration": last.get(
                        "last_observed_time"
                    ),
                    "continuation": bool(last.get("continuation")),
                }
            )

            accepted = (
                validation["status"] == "PASS_2D_FORWARD_STEP"
                and decision.action == ForwardStepAction.ACCEPT.value
                and action_gate.approved
                and (
                    sensitivity["satisfied"]
                    or not current.sensitivity_assessment_requested
                )
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

            if pending_action == ForwardStepAction.REFINE_MESH.value:
                # The refinement itself comes from the registered operation,
                # not from the gate's payload and not from the model: the
                # orchestrator re-derives it so there is one place where a
                # mesh change can be defined.
                try:
                    current = refine(current)
                except ValueError as exc:
                    s.fail(ev.ORCHESTRATOR, f"Refinement refused: {exc}")
                    self._summarize(
                        spec, diagnostics, validation, decision, iteration_out
                    )
                    return self.finish("STOPPED_REFINEMENT_REFUSED", str(exc))

                s.emit(
                    ev.ORCHESTRATOR,
                    f"Approved REFINE_MESH: building grid level "
                    f"{current.refinement_level} with {current.cells} cells "
                    f"(dx {current.dx:.4g}, dy {current.dy:.4g}). A new mesh is "
                    "a new solve from the physical initial condition; the "
                    "previous grid's case and evidence are left untouched.",
                    data={"spec": current.to_dict()},
                )
                refined_case = self.build_and_mesh(runtime, root, code, current)
                if refined_case is None:
                    # build_and_mesh has already recorded the refusal. A grid
                    # that failed its own mesh gate is not a refinement result.
                    return self.result
                case = refined_case
                self.result["runtime_case"] = str(case)
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
            f"{args.max_iterations} iteration(s) in this run "
            f"(through iteration {iteration}) without deterministic acceptance",
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
            "hard_checks_status": validation.get("hard_checks_status"),
            "final_acceptance": validation.get("final_acceptance"),
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
    source.add_argument(
        "--resume-case",
        help=(
            "Runtime case directory of an already-solved run. The loop "
            "continues that solution under the current semantics instead of "
            "starting a new case: nothing is re-solved from t = 0, existing "
            "iteration evidence is preserved, and the previous run's "
            "documents are archived under <out>/history/ before the resumed "
            "run writes its own."
        ),
    )
    ap.add_argument(
        "--final-target-end-time",
        type=float,
        default=None,
        help=(
            "Override the final scientific horizon of the resumed or "
            "requested case. Unset keeps what the specification carries."
        ),
    )

    ap.add_argument("--out", default=str(_REPO_ROOT / "demo/forward_step_2d"))
    ap.add_argument("--max-iterations", type=int, default=4)
    ap.add_argument("--max-end-time", type=float, default=12.0)
    ap.add_argument(
        "--sensitivity-tolerance",
        type=float,
        default=None,
        help=(
            "Cross-grid acceptance criterion: the largest relative change a "
            "registered quantity may show between consecutive grids. NO "
            "DEFAULT EXISTS. This repository contains no scientifically "
            "justified cross-grid tolerance and none is invented; without "
            "this flag the study measures and reports the comparison and the "
            "verdict is withheld as SENSITIVITY_CRITERION_NOT_REGISTERED."
        ),
    )
    ap.add_argument("--solver-timeout", type=float, default=7200.0)
    ap.add_argument("--reference", default=None, help="Trusted reference .npz.")
    ap.add_argument("--plan-only", action="store_true")
    ap.add_argument("--distro")
    ap.add_argument("--bashrc")

    args = ap.parse_args()
    if args.resume_case:
        # The request that produced the case is already recorded beside it.
        # Re-reading it keeps the resumed run's provenance tied to the same
        # engineering ask rather than to an empty string.
        prior = Path(args.out) / "request.txt"
        request = (
            prior.read_text(encoding="utf-8")
            if prior.is_file()
            else f"Resume of the existing case at {args.resume_case}."
        )
    elif args.request:
        request = args.request
    else:
        request = Path(args.request_file).read_text(encoding="utf-8")

    print()
    print("=" * 78)
    print(
        "  2D FORWARD-STEP AUTONOMOUS CFD AGENT"
        + ("   (RESUMING AN EXISTING SOLUTION)" if args.resume_case else "")
    )
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
