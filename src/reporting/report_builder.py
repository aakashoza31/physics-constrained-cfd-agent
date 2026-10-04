#!/usr/bin/env python3
"""One deterministic report builder, shared by every family.

Given a finished `AgentRun`, it writes the standard artifact directory:

    report/{report.md,report.json}
    evidence/{convergence,conservation,validation,stationarity}.json
    diagnostics/{llm_trace,proposed_actions,authority_trace}.json
    plots/*.png
    contours/*.png
    video/simulation.mp4
    provenance.json
    final_decision.json

Two rules keep it honest. Only fields that APPLY to the family are written --
there is no `stationarity.json` full of nulls for a steady case. And anything
that could not be produced is written as an explicit `NOT_AVAILABLE` record
naming what was missing, never as an empty file that reads like a result.
"""
from __future__ import annotations

import json
import platform
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

REPORT_VERSION = "report-builder/1.0.0"

NOT_AVAILABLE = "NOT_AVAILABLE"

#: Which evidence documents each family can actually produce.
EVIDENCE_APPLICABILITY: Dict[str, Dict[str, bool]] = {
    "nozzle": {"convergence": True, "conservation": True, "validation": True,
               "stationarity": True},
    # The forward step is a transient family: its contract has no
    # stationarity criterion, so no stationarity document is written for it.
    "forward_step_2d": {"convergence": True, "conservation": True,
                        "validation": True, "stationarity": False},
    "cube": {"convergence": True, "conservation": False, "validation": False,
             "stationarity": True},
    "airfoil": {"convergence": False, "conservation": False,
                "validation": False, "stationarity": False},
}


#: The repository root, used to keep every emitted path portable.
REPO_ROOT = Path(__file__).resolve().parents[2]


def relativise(value: Any, root: Optional[Path] = None) -> Any:
    """Rewrite absolute paths inside the repository as repo-relative ones.

    An artifact directory is evidence a reviewer reads and may re-publish. A
    path like `/home/someone/work/repo/cases/...` tells them nothing useful and
    leaks the machine it was produced on, so every path under the repository is
    emitted relative to it. Paths genuinely outside the repository (a scratch
    output directory a user chose) are left alone -- they are the user's own
    choice and rewriting them would be a lie about where the file is.
    """
    root = str(root or REPO_ROOT)
    if isinstance(value, str):
        return value.replace(root + "/", "").replace(root + "\\", "").replace(
            root, ".")
    if isinstance(value, dict):
        return {k: relativise(v, root) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [relativise(v, root) for v in value]
    if isinstance(value, Path):
        return relativise(str(value), root)
    return value


def _write(path: Path, payload: Any) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = relativise(payload)
    if isinstance(payload, str):
        path.write_text(payload, encoding="utf-8")
    else:
        path.write_text(json.dumps(payload, indent=2, default=str) + "\n",
                        encoding="utf-8")
    return path


def _git_commit() -> str:
    try:
        out = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True,
                             text=True, timeout=10)
        return out.stdout.strip() or NOT_AVAILABLE
    except Exception:                              # noqa: BLE001
        return NOT_AVAILABLE


def provenance(run: Any) -> Dict[str, Any]:
    """Everything needed to say where this result came from."""
    artifacts = run.artifacts or {}
    return {
        "report_version": REPORT_VERSION,
        "generated_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "prompt": run.prompt,
        "mode": run.mode,
        "family": run.family,
        "case": run.case,
        "solver_invoked": bool(artifacts.get("solver_invoked", False)),
        "solver": artifacts.get("contract", {}).get("capabilities", {}).get("solver"),
        "evidence_root": artifacts.get("evidence_root"),
        "case_directory": (artifacts.get("case") or {}).get("case_dir"),
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "git_commit": _git_commit(),
        "pipeline_stages": [s.name for s in run.stages],
        "note": ("a replay reads archived evidence and re-derives the decision; "
                 "it never implies that a solver was executed"),
    }


def _evidence_documents(run: Any) -> Dict[str, Dict[str, Any]]:
    """Pull the four evidence documents out of the authority trace."""
    trace = run.trace.to_dict()
    gates = {g["question"]: g for g in trace["gates"]}
    family = run.family or ""
    applicable = EVIDENCE_APPLICABILITY.get(family, {})
    documents: Dict[str, Dict[str, Any]] = {}
    for name, question in (("convergence", "convergence"),
                           ("conservation", "conservation"),
                           ("validation", "validation"),
                           ("stationarity", "stationarity")):
        if not applicable.get(name, False):
            continue
        gate = gates.get(question)
        if gate is None:
            documents[name] = {
                "status": NOT_AVAILABLE,
                "reason": (f"the {name} gate was not evaluated in this run "
                           f"(mode: {run.mode})"),
            }
            continue
        documents[name] = {
            "question": question,
            "passed": gate["passed"],
            "measured": gate["measured"],
            "threshold": gate["threshold"],
            "detail": gate["detail"],
            "decided_by": gate["decided_by"],
        }
    # The cube carries its full stationarity record, not just the gate.
    if "stationarity" in documents and run.artifacts.get("stationarity"):
        documents["stationarity"]["full_assessment"] = run.artifacts["stationarity"]
    return documents


def _diagnostics(run: Any) -> Dict[str, Any]:
    trace = run.trace.to_dict()
    proposals = trace["llm_proposals"]
    return {
        "llm_trace": {
            "proposals": proposals,
            "count": len(proposals),
            "note": ("every entry is a PROPOSAL. None of them decided anything; "
                     "the verdict comes from the authority trace."),
        },
        "proposed_actions": {
            "actions": [p for p in proposals
                        if p["activity"] == "propose_bounded_action"],
            "note": ("an action outside the family's registered vocabulary is "
                     "refused by the action validator, not executed"),
        },
        "authority_trace": trace,
    }


def _report_markdown(run: Any, docs: Dict[str, Dict[str, Any]],
                     prov: Dict[str, Any], plots: List[str],
                     contours: List[str], video: Optional[str]) -> str:
    decision = run.decision.to_dict() if run.decision else {}
    artifacts = run.artifacts or {}
    contract = (artifacts.get("contract") or {}).get("capabilities", {})
    geometry = artifacts.get("geometry") or {}
    trace = run.trace.to_dict()

    def table(rows: List[tuple]) -> str:
        out = ["| Field | Value |", "|---|---|"]
        out += [f"| {k} | {v} |" for k, v in rows]
        return "\n".join(out)

    gate_rows = "\n".join(
        f"| `{g['question']}` | {'PASS' if g['passed'] else ('FAIL' if g['passed'] is False else 'UNRESOLVED')} "
        f"| {json.dumps(g['threshold'], default=str)[:80]} | {json.dumps(g['measured'], default=str)[:110]} |"
        for g in trace["gates"]
    )
    proposal_rows = "\n".join(
        f"| {p['activity']} | {json.dumps(p['content'], default=str)[:120]} | "
        f"{p.get('accepted_by_authority')} |"
        for p in trace["llm_proposals"]
    ) or "| (none recorded) | | |"

    evidence_rows = "\n".join(
        f"| {name} | {'PASS' if d.get('passed') else ('FAIL' if d.get('passed') is False else d.get('status', 'UNRESOLVED'))} "
        f"| {json.dumps(d.get('detail', d.get('reason', '')), default=str)[:110]} |"
        for name, d in docs.items()
    ) or "| (not applicable to this family) | | |"

    media = []
    for name in plots:
        media.append(f"- plot: `plots/{name}`")
    for name in contours:
        media.append(f"- contour: `contours/{name}`")
    if video:
        media.append(f"- field movie: [{video}](../video/{video})")
    media_block = "\n".join(media) or "- none produced for this run"

    return f"""# Engineering report — {run.family or 'unrouted'} / {run.case or 'ad hoc'}

**Decision: `{decision.get('verdict', 'NONE')}`** — {decision.get('reason', '')}

## 1. Request

> {run.prompt}

{table([
    ("Interpreted family", run.family or "none"),
    ("Case", run.case or "n/a"),
    ("Mode", run.mode),
    ("Geometry source", geometry.get("source", "n/a")),
    ("Geometry status", geometry.get("status", "n/a")),
    ("Solver invoked", prov["solver_invoked"]),
])}

## 2. Physics and model

{table([
    ("Family status", contract.get("status", "n/a")),
    ("Model", (contract.get("physics") or {}).get("model", "n/a")),
    ("Dimensionality", (contract.get("physics") or {}).get("dimensionality", "n/a")),
    ("Compressible", (contract.get("physics") or {}).get("compressible", "n/a")),
    ("Turbulent", (contract.get("physics") or {}).get("turbulent", "n/a")),
    ("Transient", (contract.get("physics") or {}).get("transient", "n/a")),
    ("Solver", contract.get("solver", "n/a")),
    ("Characteristic dimension", contract.get("characteristic_dimension", "n/a")),
])}

## 3. Deterministic gates

Every row below was decided by code. No model output appears in this table.

| Gate | Result | Threshold | Measured |
|---|---|---|---|
{gate_rows}

## 4. Evidence

| Document | Result | Detail |
|---|---|---|
{evidence_rows}

## 5. Model contributions (non-binding)

| Activity | Content | Accepted by authority |
|---|---|---|
{proposal_rows}

## 6. Media

{media_block}

## 7. Provenance

```json
{json.dumps(prov, indent=2, default=str)}
```

---
Generated by `{REPORT_VERSION}`. The verdict is computed from the deterministic
gates alone; a language model cannot change it.
"""


@dataclass
class ReportPaths:
    root: Path
    report_md: Path
    report_json: Path
    final_decision: Path
    provenance: Path
    plots: List[str]
    contours: List[str]
    video: Optional[str]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "root": str(self.root),
            "report_md": str(self.report_md),
            "report_json": str(self.report_json),
            "final_decision": str(self.final_decision),
            "provenance": str(self.provenance),
            "plots": list(self.plots),
            "contours": list(self.contours),
            "video": self.video,
        }


def build(run: Any, out_dir: Path, *, make_media: bool = True) -> ReportPaths:
    """Write the complete artifact directory for one run."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    docs = _evidence_documents(run)
    for name, payload in docs.items():
        _write(out / "evidence" / f"{name}.json", payload)
    if not docs:
        _write(out / "evidence" / "README.md",
               "No evidence document applies to this family and mode.\n")

    for name, payload in _diagnostics(run).items():
        _write(out / "diagnostics" / f"{name}.json", payload)

    plots: List[str] = []
    contours: List[str] = []
    video: Optional[str] = None
    visualization = {"status": "VISUALIZATION_INCOMPLETE", "reason": "Media generation disabled"}
    history = None
    media_errors = []
    if make_media:
        from src.reporting import visuals
        from src.reporting.field_video import make_field_video
        def attempt(name, action, fallback):
            try:
                return action()
            except Exception as exc:  # reporting must never lose the authority's verdict
                media_errors.append({"stage": name, "reason": f"{type(exc).__name__}: {exc}"})
                return fallback
        plots = attempt("plots", lambda: visuals.make_plots(run, out / "plots"), [])
        contours = attempt("contours", lambda: visuals.make_contours(run, out / "contours"), [])
        visualization = attempt("field_video", lambda: make_field_video(run, out / "video"),
                                {"status": "VISUALIZATION_INCOMPLETE", "reason": "Field renderer raised an exception"})
        video = "summary_evolution.mp4" if visualization["status"] == "RENDERED" else None
        if video:
            # Reuse the genuine final rendered fields if the initial static-contour
            # stage had no standalone renderer or only compact evidence available.
            import shutil
            for name in visualization.get("fields_rendered", []):
                frame = out / "video" / "frames" / name / f"{visualization['frame_count']-1:05d}.png"
                if frame.exists():
                    (out / "contours").mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(frame, out / "contours" / f"{name}.png")
                    if f"{name}.png" not in contours:
                        contours.append(f"{name}.png")
            _write(out / "contours" / "contours_status.json", {
                "status": "RENDERED", "written": contours,
                "source": "final actual field-video frame", "time": visualization.get("rendered_solver_times", [None])[-1]})
        history = attempt("history", lambda: visuals.make_history_video(run, out / "video"), None)

    if media_errors:
        visualization.update(status="VISUALIZATION_INCOMPLETE", stage_errors=media_errors)
    _write(out / "video" / "video_manifest.json", visualization)

    _write(out / "video" / "visualization_status.json", visualization)

    prov = relativise(provenance(run))
    _write(out / "provenance.json", prov)
    decision = run.decision.to_dict() if run.decision else {"verdict": "NONE"}
    _write(out / "final_decision.json", decision)

    report_json = {
        "report_version": REPORT_VERSION,
        "decision": decision,
        "run": run.to_dict(),
        "evidence": docs,
        "media": {"plots": plots, "contours": contours, "video": video, "history": history,
                  "field_videos": visualization.get("output_files", [])},
        "visualization": visualization,
        "artifact_complete": visualization["status"] in ("RENDERED", "VIDEO_NOT_AVAILABLE_CFD_NOT_RUN"),
        "provenance": prov,
    }
    report_json_path = _write(out / "report" / "report.json", report_json)
    report_md_path = _write(out / "report" / "report.md",
                            _report_markdown(run, docs, prov, plots, contours,
                                             video))
    with report_md_path.open("a", encoding="utf-8") as handle:
        handle.write("\nVisualization status: **" + visualization["status"] + "**\n\n")
        handle.write(visualization.get("reason", "") + "\n\n")
        for name in visualization.get("output_files", []):
            handle.write(f"- [{name}](../video/{name})\n")
        handle.write("- [Video manifest](../video/video_manifest.json)\n")
        if history:
            handle.write(f"- [History animation (not a flow field)](../video/{history})\n")
    return ReportPaths(root=out, report_md=report_md_path,
                       report_json=report_json_path,
                       final_decision=out / "final_decision.json",
                       provenance=out / "provenance.json",
                       plots=plots, contours=contours, video=video)
