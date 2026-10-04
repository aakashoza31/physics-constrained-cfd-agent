#!/usr/bin/env python3
"""Gemini diagnosis of the archived surface-mounted-cube evidence.

Purpose
-------
The cube campaign was executed manually, outside the agent loop. This script
applies the agent's diagnosis stage to its archived evidence: the model sees
the measured solver-health and force-history evidence, but NOT the registered
gate verdict or its thresholds, and proposes a diagnosis and one action. The
proposal is then ruled on deterministically with the registered stationarity
gate (src/families/cube/stationarity.py, cube-stationarity/1.0.0).

No CFD is run and no archived evidence is modified. Every call is recorded,
including token usage, latency, the exact packet, the system instruction and
the raw response. Report all repeats, not a selected one.

Usage (repository root, in an environment with google-genai and a key):
    set GEMINI_API_KEY=...            (PowerShell: $env:GEMINI_API_KEY="...")
    set GEMINI_MODEL=gemini-3.5-flash-lite
    python paper/cfd_forge/scripts/cube_llm_diagnosis.py --repeats 3 \
        [--logs <archive>/CFD_Verification_Package_20260929/03_cube/logs]

The solver logs come from the verification package in the session archive on
Zenodo (DOI to be added on release); give their location with --logs or the
environment variable CFD_FORGE_CUBE_LOGS. Without them the packet records
"logs not available to this script" in place of the solver-health block.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import os
import re
import sys
import time
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import List, Optional

from pydantic import BaseModel

REPO = Path(__file__).resolve().parents[3]
FORCES = REPO / "cases/cube/drifting_wake/reference/force_history.json"
GATE = REPO / "src/families/cube/stationarity.py"
OUT = REPO / "evidence/cube/drifting_wake/llm_diagnosis"
# Solver logs of the cube run: 03_cube/logs/ of the verification package
# CFD_Verification_Package_20260929/, which is part of the session archive on
# Zenodo (DOI to be added on release). Set with --logs or CFD_FORGE_CUBE_LOGS;
# the default is a copy of the package placed next to the repository.
DEFAULT_LOGS = Path(os.environ.get(
    "CFD_FORGE_CUBE_LOGS", REPO.parent / "CFD_Verification_Package_20260929/03_cube/logs"))


class CubeDiagnosis(str, Enum):
    DEVELOPED_STATIONARY = "DEVELOPED_STATIONARY"
    STILL_DEVELOPING = "STILL_DEVELOPING"
    NUMERICALLY_UNHEALTHY = "NUMERICALLY_UNHEALTHY"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


class CubeAction(str, Enum):
    ACCEPT = "ACCEPT"
    CONTINUE_RUN = "CONTINUE_RUN"
    REQUEST_DIAGNOSTIC = "REQUEST_DIAGNOSTIC"
    FAIL_SAFELY = "FAIL_SAFELY"


class Hypothesis(BaseModel):
    hypothesis: str
    evidence_for: List[str]
    evidence_against: List[str]


class CubeDecision(BaseModel):
    diagnosis: CubeDiagnosis
    evidence_used: List[str]
    competing_hypotheses: List[Hypothesis]
    reasoning_summary: str
    action: CubeAction
    requested_diagnostic: Optional[str] = None
    confidence: str


SYSTEM = """
You are the CFD reasoning component of a physics-constrained autonomous
simulation agent. You are NOT the solver: OpenFOAM solved the equations and
deterministic code measured the evidence you are given. Interpret that
evidence and choose exactly one permitted action.

Rules:
1. Use only the supplied evidence. Never invent measurements.
2. Solver completion and small residuals do not prove that a flow is
   statistically developed.
3. Consider every force component, not only the drag.
4. Distinguish a numerically unhealthy run, a healthy run that is still
   developing, and a developed statistically stationary flow.
5. Permitted actions: ACCEPT (the flow is developed and may be certified),
   CONTINUE_RUN (healthy but still developing), REQUEST_DIAGNOSTIC (the
   evidence cannot separate the hypotheses; name the diagnostic), FAIL_SAFELY
   (stop and preserve evidence).
6. Your action is a proposal. Deterministic checks decide admissibility and
   acceptance.
7. Keep reasoning_summary concise and engineering-focused. Return only the
   structured response.
""".strip()


def load_gate():
    spec = importlib.util.spec_from_file_location("cube_stationarity", GATE)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["cube_stationarity"] = mod
    spec.loader.exec_module(mod)
    return mod


def trend(t, v):
    n = len(v)
    tm, vm = sum(t) / n, sum(v) / n
    den = sum((a - tm) ** 2 for a in t)
    return sum((a - tm) * (b - vm) for a, b in zip(t, v)) / den if den else 0.0


def block_stats(samples, lo, hi):
    rows = [s for s in samples if lo <= s["t"] < hi]
    out = {"t_window": [lo, hi], "samples": len(rows)}
    for k in ("fx", "fy", "fz"):
        v = [r[k] for r in rows]
        t = [r["t"] for r in rows]
        m = sum(v) / len(v)
        sd = math.sqrt(sum((x - m) ** 2 for x in v) / len(v))
        out[k] = {"mean": m, "std": sd, "min": min(v), "max": max(v),
                  "linear_trend_per_time": trend(t, v),
                  "mean_abs": sum(abs(x) for x in v) / len(v)}
    return out


def lateral_peaks(samples):
    """Largest |Fz| in each half-cycle between sign changes (|Fz| > 1e-4)."""
    peaks, cur = [], None
    for s in samples:
        sign = s["fz"] >= 0
        if cur is None or sign != cur["sign"]:
            if cur and abs(cur["fz"]) > 1e-4:
                peaks.append({"t": round(cur["t"], 3), "fz": cur["fz"]})
            cur = {"sign": sign, "t": s["t"], "fz": s["fz"]}
        elif abs(s["fz"]) > abs(cur["fz"]):
            cur.update(t=s["t"], fz=s["fz"])
    if cur and abs(cur["fz"]) > 1e-4:
        peaks.append({"t": round(cur["t"], 3), "fz": cur["fz"], "half_cycle_incomplete": True})
    return peaks


def solver_health(log_dir: Path):
    if not log_dir.is_dir():
        return {"status": "logs not available to this script"}
    co, cont, warn, ended = [], [], 0, []
    for f in sorted(log_dir.glob("log.foamRun.*")):
        if f.name.endswith(".err"):
            continue
        s = f.read_text(errors="replace")
        co += [float(x) for x in re.findall(r"Courant Number mean: \S+ max: (\S+)", s)]
        cont += [abs(float(x)) for x in re.findall(r"global = ([-\deE.+]+)", s)]
        warn += len(re.findall(r"FOAM Warning|FOAM FATAL|bounding", s))
        ended.append(bool(re.search(r"^End\s*$", s, re.M)))
    return {"segments": len(ended), "all_segments_ended_normally": all(ended),
            "max_courant": max(co) if co else None,
            "max_abs_global_continuity_error": max(cont) if cont else None,
            "warning_or_fatal_or_bounding_messages": warn}


def build_packet(samples, log_dir):
    return {
        "case": {
            "description": "3-D incompressible URANS (k-omega SST) flow over a wall-mounted cube "
                           "in a channel of height 2H, Re_H = 40,000; forces are pressure + viscous "
                           "force on the cube with rho = Ub = H = 1 (drag coefficient = 2 Fx).",
            "mesh": "567,360 hexahedra; checkMesh: Mesh OK (non-orthogonality 0, max aspect ratio 18.4)",
            "time_record": f"force history t* = {samples[0]['t']:.2f} to {samples[-1]['t']:.2f}",
            "components": "fx streamwise (drag), fy vertical, fz lateral (spanwise)",
        },
        "solver_health": solver_health(log_dir),
        "force_block_statistics": [block_stats(samples, a, a + 10) for a in range(20, 80, 10)],
        "lateral_force_half_cycle_extrema": lateral_peaks(samples),
        "note": "No acceptance verdict or threshold is included in this packet.",
    }


def validate(decision: CubeDecision, gate_result: dict):
    status = gate_result["status"]
    if decision.action == CubeAction.ACCEPT:
        if status == "STATIONARY":
            return {"approved": True, "reason": "ACCEPT consistent with the registered stationarity gate."}
        return {"approved": False,
                "reason": f"ACCEPT refused: registered stationarity gate returned {status} "
                          f"(failures: {gate_result.get('failures')})."}
    if decision.action == CubeAction.CONTINUE_RUN:
        return {"approved": True, "executed": False,
                "reason": "CONTINUE_RUN permitted for a healthy, still-developing run; not executed "
                          "here because the cube campaign was run outside the agent loop."}
    return {"approved": True, "executed": False, "reason": f"{decision.action.value} permitted."}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repeats", type=int, default=3)
    ap.add_argument("--logs", type=Path, default=DEFAULT_LOGS,
                    help="03_cube/logs of CFD_Verification_Package_20260929 (session archive, Zenodo); "
                         "default: $CFD_FORGE_CUBE_LOGS or ../CFD_Verification_Package_20260929/03_cube/logs")
    args = ap.parse_args()

    from google import genai
    from google.genai import types

    model = os.environ.get("GEMINI_MODEL", "gemini-3.5-flash-lite")
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        sys.exit("GEMINI_API_KEY is not set.")
    client = genai.Client(api_key=key)

    samples = json.loads(FORCES.read_text())["samples"]
    gate_result = load_gate().assess(samples).to_dict()
    packet = build_packet(samples, args.logs)
    OUT.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    (OUT / f"{stamp}_packet.json").write_text(json.dumps(packet, indent=2))

    runs = []
    for i in range(args.repeats):
        t0 = time.time()
        resp = client.models.generate_content(
            model=model,
            contents=json.dumps(packet, indent=2),
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM,
                response_mime_type="application/json",
                response_schema=CubeDecision,
                temperature=0,
            ),
        )
        latency = time.time() - t0
        decision = CubeDecision.model_validate_json(resp.text)
        um = getattr(resp, "usage_metadata", None)
        usage = {k: getattr(um, k, None) for k in
                 ("prompt_token_count", "candidates_token_count", "total_token_count")} if um else None
        rec = {
            "stage": "cube_evidence_diagnosis", "source": "gemini", "model": model,
            "is_llm": True, "repeat": i + 1, "latency_s": round(latency, 3), "usage": usage,
            "system_instruction_sha256": hashlib.sha256(SYSTEM.encode()).hexdigest(),
            "packet_sha256": hashlib.sha256(json.dumps(packet, sort_keys=True).encode()).hexdigest(),
            "raw_response": resp.text, "decision": decision.model_dump(mode="json"),
            "action_validation": validate(decision, gate_result),
            "registered_gate": gate_result,
            "solver_invoked": False,
            "note": "Diagnosis of archived evidence; the cube was executed manually.",
        }
        (OUT / f"{stamp}_run{i + 1:02d}.json").write_text(json.dumps(rec, indent=2))
        runs.append(rec)
        print(f"run {i + 1}: {decision.diagnosis.value} -> {decision.action.value} "
              f"| validator: {'APPROVED' if rec['action_validation']['approved'] else 'REFUSED'} "
              f"| {latency:.1f}s | tokens {usage}")
    (OUT / f"{stamp}_summary.json").write_text(json.dumps({
        "model": model, "repeats": len(runs),
        "decisions": [(r["decision"]["diagnosis"], r["decision"]["action"],
                       r["action_validation"]["approved"]) for r in runs],
        "gate_status": gate_result["status"]}, indent=2))
    print(f"records written to {OUT}")


if __name__ == "__main__":
    main()
