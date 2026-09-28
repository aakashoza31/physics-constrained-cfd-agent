#!/usr/bin/env python3
"""Render the Case A closed loop from the LLM's point of view (GIF + MP4).

    python scripts/make_case_a_backend_media.py

Requires Pillow, matplotlib and ffmpeg on PATH.

Every filename, command, number and decision string is taken from the real
repository and the published Case A campaign. Nothing is invented.

Traced entrypoint:  scripts/run_nozzle_feedback.py --case A
  iteration 1 is executed by scripts/run_nozzle_e2e.py as a subprocess
  (_initial_command, run_nozzle_feedback.py:608) with --end-time 0.001

This script only reads artifacts and writes media.
"""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

REPO = Path(__file__).resolve().parents[1]
PUBLISHED = REPO / "demo/published_campaign"
VIS = PUBLISHED / "case_A_reference/visuals"
FACTS = PUBLISHED / "nozzle_agent_closed_loop_demo.sources.json"
OUT = PUBLISHED

facts = json.loads(FACTS.read_text(encoding="utf-8-sig"))

# ----------------------------------------------------------------------

W, H = 1280, 720

BG = (252, 252, 253)
INK = (17, 19, 24)
MUTED = (118, 125, 136)
FAINT = (168, 174, 183)
RULE = (226, 229, 234)
PANEL = (243, 244, 246)

LLM_C = (109, 40, 217)      # violet: reasoning
LLM_BG = (245, 240, 255)
DET_C = (21, 94, 117)       # teal: deterministic
DET_BG = (236, 246, 249)
PASS = (21, 128, 61)
FAIL = (185, 28, 28)
AMBER = (180, 83, 9)
TERM_BG = (24, 27, 33)
TERM_FG = (214, 221, 232)

import matplotlib  # noqa: E402  (bundled DejaVu fonts)

FDIR = os.path.join(matplotlib.get_data_path(), "fonts", "ttf")


def font(size, bold=False, mono=False):
    n = ("DejaVuSansMono-Bold.ttf" if bold else "DejaVuSansMono.ttf") if mono else (
        "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf")
    return ImageFont.truetype(os.path.join(FDIR, n), size)


F_H = font(22, bold=True)
F_LBL = font(13, bold=True)
F_T = font(15)
F_TB = font(15, bold=True)
F_S = font(13)
F_XS = font(11)
F_M = font(13, mono=True)
F_MS = font(12, mono=True)
F_BIG = font(52, bold=True)
F_CARD = font(40, bold=True)

# ----------------------------------------------------------------------
# layout
# ----------------------------------------------------------------------

LX, LW = 28, 300                      # left column
LLM_BOX = (368, 292, 652, 428)        # central LLM node
TX, TW = 800, 452                     # tool column
TY, TH, TG = 118, 44, 7               # tool rows

TOOLS = [
    ("Scope gate", "src/reasoning/nozzle_scope_gate.py"),
    ("Case generator", "src/pipeline/nozzle/build.py"),
    ("Mesh + quality check", "src/pipeline/nozzle/mesh_case.sh"),
    ("Verified initializer", "src/pipeline/nozzle/initialize.py"),
    ("Solver executor", "src/pipeline/nozzle/execute.py"),
    ("Deterministic validator", "src/pipeline/nozzle/validate.py"),
    ("Native snapshot + fields", "export_feedback_snapshot.py · feedback_diagnostics.py"),
    ("Action validator", "src/reasoning/action_validator.py"),
    ("Continuation", "src/pipeline/nozzle/feedback.py"),
]

TERM = (28, 596, 1252, 672)


def tool_rect(i):
    y = TY + i * (TH + TG)
    return TX, y, TX + TW, y + TH


def rr(d, box, radius, fill=None, outline=None, width=1):
    d.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)


def clip_text(d, text, f, maxw):
    if d.textlength(text, font=f) <= maxw:
        return text
    while text and d.textlength(text + "…", font=f) > maxw:
        text = text[:-1]
    return text + "…"


# ----------------------------------------------------------------------
# frame renderer
# ----------------------------------------------------------------------


def render(st):
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)

    # header ----------------------------------------------------------
    d.rectangle([0, 0, W, 4], fill=LLM_C)
    d.text((28, 22), "Physics-Constrained Closed-Loop CFD Agent", font=F_H, fill=INK)
    d.text((28, 52), "Case A · axisymmetric converging-diverging nozzle · OpenFOAM Foundation v14",
           font=F_S, fill=MUTED)

    badge = st.get("iteration")
    if badge:
        txt = f"CFD ITERATION {badge}"
        tw = d.textlength(txt, font=F_LBL)
        rr(d, [W - 28 - tw - 24, 24, W - 28, 50], 6, fill=PANEL)
        d.text((W - 40 - tw, 31), txt, font=F_LBL, fill=INK)

    d.line([(28, 92), (W - 28, 92)], fill=RULE)
    d.text((LX, 100), "LLM  ·  REASONING", font=F_LBL, fill=LLM_C)
    d.text((TX, 100), "DETERMINISTIC  ·  SCIENTIFIC AUTHORITY", font=F_LBL, fill=DET_C)

    # tool column -----------------------------------------------------
    active = st.get("tool")
    for i, (name, path) in enumerate(TOOLS):
        x0, y0, x1, y1 = tool_rect(i)
        on = i == active
        rr(d, [x0, y0, x1, y1], 8,
           fill=DET_BG if on else (250, 251, 252),
           outline=DET_C if on else RULE, width=2 if on else 1)
        d.text((x0 + 12, y0 + 6), name, font=F_TB if on else F_T,
               fill=DET_C if on else INK)
        d.text((x0 + 12, y0 + 25), path, font=F_MS,
               fill=DET_C if on else FAINT)

    # central LLM node ------------------------------------------------
    bx0, by0, bx1, by1 = LLM_BOX
    hot = st.get("llm")
    rr(d, [bx0 - 6, by0 - 6, bx1 + 6, by1 + 6], 16,
       fill=(250, 247, 255) if hot else BG)
    rr(d, [bx0, by0, bx1, by1], 12, fill=LLM_BG,
       outline=LLM_C, width=3 if hot else 2)
    d.text((bx0 + 20, by0 + 16), "LLM", font=font(30, bold=True), fill=LLM_C)
    d.text((bx0 + 20, by0 + 56), "gemini-3.5-flash-lite", font=F_MS, fill=LLM_C)
    stage = st.get("stage", "")
    if stage:
        d.text((bx0 + 20, by0 + 80), stage, font=F_S, fill=INK)
    sub = st.get("stage_sub", "")
    if sub:
        d.text((bx0 + 20, by0 + 100), sub, font=F_XS, fill=MUTED)

    # left panels -----------------------------------------------------
    def panel(y, h, label, lines, colour):
        rr(d, [LX, y, LX + LW, y + h], 8, fill=(255, 255, 255), outline=RULE)
        d.text((LX + 12, y + 8), label, font=F_LBL, fill=colour)
        yy = y + 30
        for line, bold, col in lines:
            f = F_TB if bold else F_S
            d.text((LX + 12, yy), clip_text(d, line, f, LW - 24), font=f, fill=col)
            yy += 19 if not bold else 21

    panel(120, 196, "LLM INPUT", st.get("input", []), LLM_C)
    panel(330, 150, "LLM DECISION", st.get("decision", []), LLM_C)

    # evidence thumbnails ---------------------------------------------
    thumbs = st.get("thumbs")
    if thumbs:
        rr(d, [LX, 494, LX + LW, 578], 8, fill=(255, 255, 255), outline=LLM_C)
        d.text((LX + 12, 500), "EVIDENCE RECEIVED", font=F_LBL, fill=LLM_C)
        tw = (LW - 32) // 5
        for k, name in enumerate(thumbs):
            im = Image.open(VIS / name).convert("RGB")
            th = int(tw / im.width * im.height)
            im = im.resize((tw - 2, th), Image.LANCZOS)
            img.paste(im, (LX + 12 + k * tw, 528))
        d.text((LX + 12, 556), "mesh · Mach · p · T · |U|   (native cell values)",
               font=F_XS, fill=MUTED)

    # arrow -----------------------------------------------------------
    arrow = st.get("arrow")
    if arrow:
        kind, idx, prog, label = arrow
        x0, y0, x1, y1 = tool_rect(idx)
        ty = (y0 + y1) / 2
        ax, ay = LLM_BOX[2] + 4, (LLM_BOX[1] + LLM_BOX[3]) / 2
        bx, by = x0 - 4, ty

        colour = LLM_C if kind == "call" else DET_C
        if kind == "call":
            sx, sy, ex, ey = ax, ay, bx, by
        else:
            sx, sy, ex, ey = bx, by, ax, ay

        d.line([(sx, sy), (ex, ey)], fill=colour, width=2)

        px = sx + (ex - sx) * prog
        py = sy + (ey - sy) * prog
        d.ellipse([px - 5, py - 5, px + 5, py + 5], fill=colour)

        if label:
            f = F_MS
            lw = d.textlength(label, font=f) + 16
            lx = min(max(px - lw / 2, 660), TX - lw - 6)
            rr(d, [lx, py - 26, lx + lw, py - 6], 6, fill=colour)
            d.text((lx + 8, py - 23), label, font=f, fill=(255, 255, 255))

    # tool result -----------------------------------------------------
    res = st.get("result")
    if res is not None and active is not None:
        x0, y0, x1, y1 = tool_rect(active)
        lines, col = res
        h = 16 + 18 * len(lines)
        ry = min(y1 + 6, 720 - 130 - h)
        rr(d, [TX + 14, ry, TX + TW, ry + h], 8, fill=(255, 255, 255), outline=col)
        for k, line in enumerate(lines):
            d.text((TX + 26, ry + 8 + 18 * k),
                   clip_text(d, line, F_S, TW - 40), font=F_S, fill=col)

    # terminal --------------------------------------------------------
    cmds = st.get("terminal")
    if cmds:
        rr(d, TERM, 8, fill=TERM_BG)
        d.text((TERM[0] + 14, TERM[1] + 8), "runtime  ·  WSL Ubuntu-24.04  ·  OpenFOAM v14",
               font=F_XS, fill=(128, 138, 154))
        for k, line in enumerate(cmds[:2]):
            d.text((TERM[0] + 14, TERM[1] + 28 + k * 20), "$ " + line,
                   font=F_M, fill=TERM_FG)

    note = st.get("note")
    if note:
        d.text((28, 686), note, font=F_XS, fill=FAINT)

    return img


# ----------------------------------------------------------------------
# overlays
# ----------------------------------------------------------------------


def overlay_card(base, title, lines, colour, sub=None):
    img = base.copy()
    d = ImageDraw.Draw(img, "RGBA")
    d.rectangle([0, 0, W, H], fill=(255, 255, 255, 190))
    bw, bh = 1000, 306
    x0, y0 = (W - bw) // 2, (H - bh) // 2
    rr(d, [x0, y0, x0 + bw, y0 + bh], 16, fill=(255, 255, 255), outline=colour, width=3)
    d.text((x0 + 44, y0 + 34), title, font=F_CARD, fill=colour)
    yy = y0 + 118
    for line, mono in lines:
        d.text((x0 + 44, yy), line, font=(F_M if mono else F_T), fill=INK)
        yy += 30 if mono else 28
    if sub:
        d.text((x0 + 44, y0 + bh - 46), sub, font=F_S, fill=MUTED)
    return img


def evidence_frame(iteration, image_name, headline, hcol, lines, note):
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, W, 4], fill=DET_C)
    d.text((28, 24), headline, font=font(30, bold=True), fill=hcol)
    d.text((28, 66), f"iteration {iteration} · real OpenFOAM field, native cell values",
           font=F_S, fill=MUTED)

    src = Image.open(VIS / image_name).convert("RGB")
    bw = W - 56
    scale = min(bw / src.width, 330 / src.height)
    im = src.resize((int(src.width * scale), int(src.height * scale)), Image.LANCZOS)
    img.paste(im, (28 + (bw - im.width) // 2, 108))

    yy = 470
    for line, col, bold in lines:
        d.text((28, yy), line, font=(F_TB if bold else F_T), fill=col)
        yy += 30
    d.text((28, 686), note, font=F_XS, fill=FAINT)
    return img


# ----------------------------------------------------------------------
# script
# ----------------------------------------------------------------------

REQ = [
    ("Natural-language request", True, INK),
    ("inlet r = 50 mm, throat 32.6 mm", False, MUTED),
    ("outlet r = 35.4 mm", False, MUTED),
    ("p0 = 200 kPa, T0 = 300 K", False, MUTED),
    ("back pressure = 30 kPa", False, MUTED),
    ("gamma 1.4, R 287, inviscid Euler", False, MUTED),
    ("adiabatic slip walls", False, MUTED),
]

frames, durations = [], []


# Global pacing: authored holds are scaled to land the film in the 30-45 s
# target without changing the relative rhythm. Arrow-travel frames (<=120 ms)
# are left alone so motion stays smooth.
HOLD_SCALE = 0.56


def add(img, ms):
    if ms > 120:
        ms = max(320, round(ms * HOLD_SCALE))
    frames.append(img)
    durations.append(ms)


def travel(st, kind, idx, label, steps=4, ms=45):
    for s in range(1, steps + 1):
        s2 = dict(st)
        s2["arrow"] = (kind, idx, s / steps, label)
        add(render(s2), ms)


def call_tool(base, idx, payload, result, rescol, terminal=None, hold=900,
              result_hold=1100):
    st = dict(base)
    st["tool"] = idx
    st["llm"] = False
    if terminal:
        st["terminal"] = terminal
    travel(st, "call", idx, payload)
    add(render(st), hold)
    st2 = dict(st)
    st2["result"] = (result, rescol)
    add(render(st2), result_hold)
    return st2


def returning(st, idx, label, hold=700):
    travel(st, "ret", idx, label)
    s = dict(st)
    s["llm"] = True
    add(render(s), hold)
    return s


def build():
    # ---------------- intro -------------------------------------------
    intro = {"input": [], "decision": [],
             "note": "traced from scripts/run_nozzle_feedback.py --case A"}
    base_img = render(intro)
    add(overlay_card(base_img,
                     "The LLM operates the CFD stack",
                     [("The model interprets, inspects evidence and proposes actions.", False),
                      ("Deterministic code owns mesh validity, conservation,", False),
                      ("stationarity, action safety and final acceptance.", False)],
                     LLM_C,
                     sub="entrypoint: scripts/run_nozzle_feedback.py --case A"), 2600)
    add(base_img, 700)

    # ---------------- iteration 1 -------------------------------------
    b = {"iteration": 1, "input": REQ, "decision": [], "note":
         "iteration 1 is executed by scripts/run_nozzle_e2e.py (run_nozzle_feedback.py:608, --end-time 0.001)"}

    s = dict(b); s["llm"] = True
    s["stage"] = "case_spec_interpretation"
    s["stage_sub"] = "src/agents/nozzle_case_spec_agent.py"
    s["decision"] = [("Structured CaseSpec emitted", True, INK),
                     ("geometry · reservoir · ambient", False, MUTED),
                     ("ambient NOT imposed at outlet", False, MUTED)]
    add(render(s), 1900)

    s = call_tool(s, 0, "CaseSpec",
                  ["IN_SCOPE", "area ratio 1.1792 · NPR 6.667 · 2112 cells"], PASS)
    s = returning(s, 0, "scope_gate.json", 600)

    s["decision"] = [("Build the OpenFOAM case", True, INK),
                     ("validated recipe, unchanged", False, MUTED)]
    s = call_tool(s, 1, "NozzleCaseSpec",
                  ["blockMeshDict · controlDict · fvSchemes", "0/p · 0/T · 0/U · manifest.json"], DET_C,
                  terminal=["python3 build.py <case> --spec case_spec.json"])
    s = returning(s, 1, "case files", 500)

    s = call_tool(s, 2, "case dir",
                  ["Mesh OK  ·  2112 cells", "max non-orthogonality 9.56°  ·  skewness 0.331"], PASS,
                  terminal=["blockMesh -case <case>",
                            "checkMesh -case <case> -allTopology -allGeometry"])
    s = returning(s, 2, "mesh_evidence.json", 500)

    s["llm"] = True
    s["stage"] = "mesh_evidence_review"
    s["stage_sub"] = "src/agents/nozzle_demo_agents.py"
    s["input"] = [("mesh_evidence.json", True, INK),
                  ("mesh_ok = true", False, MUTED),
                  ("cells 2112 · points 4389", False, MUTED),
                  ("max non-orthogonality 9.56°", False, MUTED)]
    s["decision"] = [("PROCEED_TO_CFD_SETUP", True, LLM_C),
                     ("checkMesh OK is necessary,", False, MUTED),
                     ("never sufficient", False, MUTED)]
    add(render(s), 2000)

    s = call_tool(s, 3, "verified init",
                  ["read-back verified over 2112 cells", "p ∈ [54 134, 191 103] Pa"], PASS,
                  terminal=["python3 initialize.py <case>"])
    s = returning(s, 3, "initialization_verified.json", 500)

    s["decision"] = [("Run the solver to 0.001 s", True, INK),
                     ("declared first horizon", False, MUTED)]
    s = call_tool(s, 4, "run to 0.001 s",
                  ["status COMPLETED · returncode 0", "t = 0.001 s · 16.0 s wall clock"], PASS,
                  terminal=["foamRun -case <case>",
                            "# system/controlDict:  solver shockFluid;  endTime 0.001;"],
                  hold=1100)
    s = returning(s, 4, "execution.json", 500)

    s = call_tool(s, 5, "fields, logs, monitors",
                  ["status FAIL  ·  17 / 20 checks", "steady_mass_balance · monitors_stationary",
                   "fields_stationary"], FAIL,
                  terminal=["python3 validate.py <case>"], result_hold=1500)
    s = returning(s, 5, "validation.json", 400)

    add(evidence_frame(
        1, "iteration_01/mach_field.png",
        "17 / 20 deterministic checks passed", AMBER,
        [("exit Mach 1.5012 · exit p 53.92 kPa · throat Mach 1.0287", INK, False),
         ("boundary mass mismatch 1.35 %   (criterion < 0.10 %)", FAIL, True),
         ("The field looks right. The stationarity criteria say it is not finished.", MUTED, False)],
        "source: iterations/iteration_01/validation.json · visuals/iteration_01/mach_field.png"), 2600)

    s = call_tool(s, 6, "latest time dir",
                  ["feedback_snapshot.csv / .json", "5 field PNGs rendered from native cells",
                   "profile_diagnostics.json"], DET_C,
                  terminal=["python3 export_feedback_snapshot.py <case>"])
    s = returning(s, 6, "evidence + images", 400)

    s["llm"] = True
    s["stage"] = "multimodal visual observation"
    s["stage_sub"] = "src/agents/cfd_visual_observer.py"
    s["thumbs"] = [f"iteration_01/{n}.png" for n in
                   ("mesh_cells", "mach_field", "pressure_field", "temperature_field", "speed_field")]
    s["input"] = [("cfd_evidence.json", True, INK),
                  ("theory-blind payload", False, LLM_C),
                  ("failed checks · stationarity drift", False, MUTED),
                  ("field L2 change · continuity", False, MUTED),
                  ("5 PNGs as image bytes", False, MUTED),
                  ("no analytical target values", False, LLM_C)]
    s["decision"] = [("Flow field is physically plausible", True, INK),
                     ("sonic transition near throat", False, MUTED),
                     ("no qualitative anomalies", False, MUTED)]
    s["result"] = None
    s["terminal"] = None
    add(render(s), 2500)

    s["stage"] = "theory_blind_diagnosis"
    s["stage_sub"] = "src/reasoning/nozzle_diagnosis.py"
    s["decision"] = [("UNCONVERGED", True, AMBER),
                     ("→ CONTINUE_RUN", True, LLM_C),
                     ("confidence high", False, MUTED),
                     ('"still evolving, solver stable"', False, MUTED)]
    add(render(s), 2400)

    s["thumbs"] = None
    s = call_tool(s, 7, "proposed action",
                  ["APPROVED", "CONTINUE_RUN is permitted for a", "healthy evolving solution."], PASS,
                  result_hold=1500)
    s = returning(s, 7, "action_validation.json", 500)

    s["decision"] = [("Execute the approved action", True, INK),
                     ("horizon 0.001 → 0.006 s", False, MUTED)]
    s = call_tool(s, 8, "continue to 0.006 s",
                  ["controlDict rewritten in place", "same case directory, same mesh"], DET_C,
                  terminal=["# startFrom latestTime;  startTime 0.001;  endTime 0.006;"],
                  result_hold=1500)

    add(overlay_card(render(s), "Continuation, not a restart",
                     [("startFrom latestTime  ·  startTime 0.001  ·  endTime 0.006", True),
                      ("", False),
                      ("Same runtime case directory in both iterations:", False),
                      ("~/.cache/nozzle-e2e/20260921T052758Z-case_A_reference/...", True)],
                     DET_C, sub="src/pipeline/nozzle/feedback.py :: configure_continuation_text"), 2600)

    # ---------------- iteration 2 -------------------------------------
    b2 = dict(s)
    b2["iteration"] = 2
    b2["result"] = None
    b2["terminal"] = None
    b2["input"] = [("approved action", True, INK), ("CONTINUE_RUN", False, MUTED)]
    b2["decision"] = [("Resume the same solution", True, INK)]
    b2["note"] = "run_nozzle_feedback.py :: _run_solver → _update_latest_files → _diagnose_iteration"

    s = call_tool(b2, 4, "resume",
                  ["status COMPLETED · returncode 0", "t = 0.006 s · 68.3 s wall · 25,380 steps"], PASS,
                  terminal=["foamRun -case <case>"], hold=1100)
    s = returning(s, 4, "execution.json", 500)

    s = call_tool(s, 5, "fields, logs, monitors",
                  ["status PASS_SINGLE_MESH", "20 / 20 checks", "mass mismatch 0.059 %"], PASS,
                  terminal=["python3 validate.py <case>"], result_hold=1500)
    s = returning(s, 5, "validation.json", 400)

    add(evidence_frame(
        2, "iteration_02/mach_field.png",
        "20 / 20 deterministic checks passed", PASS,
        [("exit Mach 1.5132 · exit p 53.15 kPa · boundary mass mismatch 0.059 %", INK, False),
         ("steady_mass_balance · monitors_stationary · fields_stationary  now pass", PASS, True),
         ("Every outlet face is supersonic, so no static pressure is imposed there.", MUTED, False)],
        "source: iterations/iteration_02/validation.json · visuals/iteration_02/mach_field.png"), 2600)

    s = call_tool(s, 6, "latest time dir",
                  ["feedback_snapshot refreshed", "5 field PNGs · iteration 2"], DET_C,
                  terminal=["python3 export_feedback_snapshot.py <case>"], result_hold=900)
    s = returning(s, 6, "evidence + images", 400)

    s["llm"] = True
    s["stage"] = "theory_blind_diagnosis"
    s["stage_sub"] = "src/reasoning/nozzle_diagnosis.py"
    s["thumbs"] = [f"iteration_02/{n}.png" for n in
                   ("mesh_cells", "mach_field", "pressure_field", "temperature_field", "speed_field")]
    s["input"] = [("cfd_evidence.json", True, INK),
                  ("theory-blind payload", False, LLM_C),
                  ("20 / 20 checks pass", False, MUTED),
                  ("drift < 0.04 % · L2 < 0.14 %", False, MUTED),
                  ("refreshed field images", False, MUTED)]
    s["decision"] = [("ACCEPTABLE", True, PASS),
                     ("→ ACCEPT", True, LLM_C),
                     ("confidence high", False, MUTED),
                     ("all trust criteria satisfied", False, MUTED)]
    s["result"] = None
    s["terminal"] = None
    add(render(s), 2400)

    s["thumbs"] = None
    s = call_tool(s, 7, "proposed ACCEPT",
                  ["APPROVED", "ACCEPT is consistent with", "deterministic trust checks."], PASS,
                  result_hold=1400)
    s = returning(s, 7, "action_validation.json", 500)

    add(overlay_card(render(s), "PASS_SINGLE_MESH",
                     [("Acceptance came from validate.py, not from the model.", False),
                      ("", False),
                      ("The LLM may propose ACCEPT. It cannot grant it:", False),
                      ("_diagnose_iteration overrides an ACCEPT whose", False),
                      ("deterministic status is not PASS_SINGLE_MESH.", False)],
                     PASS, sub="run_nozzle_feedback.py :: feedback_action_gate.json"), 3000)

    # ---------------- closing -----------------------------------------
    fin = dict(s)
    fin["tool"] = None
    fin["llm"] = True
    fin["stage"] = "engineering_summary"
    fin["stage_sub"] = "src/agents/nozzle_demo_agents.py"
    fin["input"] = [("post-hoc quasi-1D comparison", True, INK),
                    ("revealed only now, to the", False, MUTED),
                    ("reporter — never to the", False, MUTED),
                    ("decision loop", False, MUTED)]
    fin["decision"] = [("ENGINEERING_SUMMARY.md", True, INK),
                       ("ACCEPTED after 2 iterations", False, PASS)]
    fin["result"] = None
    fin["terminal"] = None
    fin["note"] = "5 LLM calls · 9 deterministic modules · 2 CFD iterations · acceptance is deterministic"
    add(render(fin), 2200)

    add(overlay_card(render(fin), "LLM reasoning, deterministic authority",
                     [("request → CaseSpec → scope gate → mesh → solver → validator", False),
                      ("→ evidence → visual observation → diagnosis → action gate", False),
                      ("→ continuation → re-validation → ACCEPT → PASS_SINGLE_MESH", False),
                      ("", False),
                      ("5 LLM calls · 9 deterministic modules · 2 CFD iterations", False)],
                     LLM_C, sub="Physics-Constrained Closed-Loop CFD Agent · Case A"), 3200)

    # ---------------- encode ------------------------------------------
    total = sum(durations) / 1000
    print(f"{len(frames)} frames, {total:.1f} s")

    seq = Path(tempfile.mkdtemp(prefix="backend_frames_"))
    fps = 25
    n = 0
    for im, ms in zip(frames, durations):
        for _ in range(max(1, round(ms / 1000 * fps))):
            im.save(seq / f"{n:05d}.png")
            n += 1

    mp4 = OUT / "nozzle_agent_llm_backend.mp4"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-framerate", str(fps),
                    "-i", str(seq / "%05d.png"), "-c:v", "libx264", "-preset", "slow",
                    "-crf", "20", "-pix_fmt", "yuv420p", "-movflags", "+faststart",
                    str(mp4)], check=True)

    gw = 960
    small = [f.resize((gw, int(gw / W * H)), Image.LANCZOS) for f in frames]
    gif = OUT / "nozzle_agent_llm_backend.gif"
    small[0].save(gif, save_all=True, append_images=small[1:],
                  duration=durations, loop=0, optimize=True)

    print("gif", round(gif.stat().st_size / 1e6, 2), "MB")
    print("mp4", round(mp4.stat().st_size / 1e6, 2), "MB")


if __name__ == "__main__":
    build()
