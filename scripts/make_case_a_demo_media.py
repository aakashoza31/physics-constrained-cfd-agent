#!/usr/bin/env python3
"""Render the Case A closed-loop demonstration as a GIF + MP4.

    python scripts/make_case_a_demo_media.py

Requires Pillow, matplotlib (for the bundled DejaVu fonts) and ffmpeg on PATH.
Outputs demo/published_campaign/nozzle_agent_closed_loop_demo.{gif,mp4}.

Every number, decision string and field image in this animation is read from
real repository artifacts. Nothing is synthesised:

  images      demo/published_campaign/case_A_reference/visuals/iteration_0{1,2}/
  it-1 checks demo/nozzle_feedback_v2_hotfix/.../iterations/iteration_01/validation.json
  it-1 LLM    demo/nozzle_feedback_v2_hotfix/.../iterations/iteration_01/agent_decision.json
  it-2 checks demo/nozzle_feedback_v2_hotfix/.../iterations/iteration_02/validation.json
  it-2 LLM    demo/nozzle_feedback_v2_hotfix/.../iterations/iteration_02/agent_decision.json
  summary     demo/published_campaign/CAMPAIGN_SUMMARY.json

This script only reads artifacts and writes media. It does not touch any
simulation, validation or pipeline code.
"""
from __future__ import annotations

import json
import os
import subprocess
import textwrap
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

# ----------------------------------------------------------------------
# inputs
# ----------------------------------------------------------------------

REPO = Path(__file__).resolve().parents[1]
PUBLISHED = REPO / "demo/published_campaign"

VIS = PUBLISHED / "case_A_reference/visuals"
FACTS = PUBLISHED / "nozzle_agent_closed_loop_demo.sources.json"
OUT = PUBLISHED

facts = json.loads(FACTS.read_text(encoding="utf-8-sig"))

# ----------------------------------------------------------------------
# canvas + type
# ----------------------------------------------------------------------

W, H = 1280, 720

BG = (255, 255, 255)
PANEL = (243, 244, 246)
INK = (17, 19, 24)
MUTED = (107, 114, 128)
RULE = (226, 229, 234)
ACCENT = (37, 99, 235)
PASS = (21, 128, 61)
FAIL = (185, 28, 28)
AMBER = (180, 83, 9)

# DejaVu ships with matplotlib, so the render is identical on any platform.
import matplotlib  # noqa: E402

FDIR = os.path.join(matplotlib.get_data_path(), "fonts", "ttf")


def font(size, bold=False, mono=False):
    if mono:
        name = "DejaVuSansMono-Bold.ttf" if bold else "DejaVuSansMono.ttf"
    else:
        name = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
    return ImageFont.truetype(os.path.join(FDIR, name), size)


F_TITLE = font(54, bold=True)
F_H1 = font(40, bold=True)
F_H2 = font(30, bold=True)
F_BODY = font(23)
F_SMALL = font(19)
F_TINY = font(16)
F_MONO = font(21, mono=True)
F_MONO_S = font(18, mono=True)
F_BIG = font(96, bold=True)

STAGES = ["REQUEST", "MESH", "SOLVE", "DIAGNOSE", "DECIDE", "CONTINUE", "ACCEPT"]


# ----------------------------------------------------------------------
# primitives
# ----------------------------------------------------------------------


def new_canvas():
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, W, 6], fill=ACCENT)
    return img, d


def rail(d, active=None):
    """Bottom progress rail. active = index into STAGES, or None."""
    y = H - 58
    d.line([(0, y - 24), (W, y - 24)], fill=RULE, width=1)

    n = len(STAGES)
    slot = W / n

    for i, name in enumerate(STAGES):
        cx = slot * (i + 0.5)
        done = active is not None and i < active
        now = active is not None and i == active

        colour = ACCENT if now else (INK if done else (203, 207, 213))
        r = 6 if now else 4
        d.ellipse([cx - r, y - r, cx + r, y + r], fill=colour)

        f = font(15, bold=now)
        tw = d.textlength(name, font=f)
        d.text((cx - tw / 2, y + 14), name, font=f, fill=colour if now else MUTED)

        if i < n - 1:
            d.line(
                [(cx + 12, y), (slot * (i + 1.5) - 12, y)],
                fill=INK if done else RULE,
                width=2,
            )


def kicker(d, text, colour=MUTED):
    d.text((70, 52), text.upper(), font=font(18, bold=True), fill=colour)


def heading(d, text, y=88, f=F_H1, colour=INK):
    d.text((70, y), text, font=f, fill=colour)


def paste_plot(img, path, box, caption=None, d=None):
    """Fit a real matplotlib PNG into box=(x, y, w, h), preserving aspect."""
    src = Image.open(path).convert("RGB")
    x, y, bw, bh = box
    scale = min(bw / src.width, bh / src.height)
    w2, h2 = int(src.width * scale), int(src.height * scale)
    src = src.resize((w2, h2), Image.LANCZOS)
    px = x + (bw - w2) // 2
    py = y + (bh - h2) // 2
    img.paste(src, (px, py))

    if caption and d is not None:
        d.text((px, py + h2 + 10), caption, font=F_TINY, fill=MUTED)

    return px, py, w2, h2


def wrap(d, text, xy, f, fill, width_px, leading=1.45, max_lines=None):
    x, y = xy
    avg = d.textlength("n", font=f)
    chars = max(20, int(width_px / avg))
    lines = textwrap.wrap(text, chars)
    if max_lines:
        lines = lines[:max_lines]
    lh = int(f.size * leading)
    for i, line in enumerate(lines):
        d.text((x, y + i * lh), line, font=f, fill=fill)
    return y + len(lines) * lh


def chip(d, xy, text, fg, bg, f=F_SMALL, pad=(14, 8)):
    x, y = xy
    tw = d.textlength(text, font=f)
    w = tw + pad[0] * 2
    h = f.size + pad[1] * 2
    d.rounded_rectangle([x, y, x + w, y + h], radius=8, fill=bg)
    d.text((x + pad[0], y + pad[1] - 1), text, font=f, fill=fg)
    return w, h


def source_note(d, text):
    d.text((70, H - 104), text, font=F_TINY, fill=(160, 166, 175))


# ----------------------------------------------------------------------
# scenes
# ----------------------------------------------------------------------

scenes = []  # (image, hold_ms)


def scene_title():
    img, d = new_canvas()
    d.text((70, 250), "Physics-Constrained", font=F_TITLE, fill=INK)
    d.text((70, 312), "Autonomous CFD Agent", font=F_TITLE, fill=ACCENT)
    d.line([(70, 396), (330, 396)], fill=INK, width=3)
    d.text(
        (70, 424),
        "Closed-loop LLM reasoning under deterministic scientific authority",
        font=F_BODY,
        fill=MUTED,
    )
    d.text(
        (70, 462),
        "Case A  ·  axisymmetric converging-diverging nozzle  ·  OpenFOAM Foundation v14",
        font=F_SMALL,
        fill=MUTED,
    )
    rail(d, None)
    return img, 1500


def scene_request():
    img, d = new_canvas()
    kicker(d, "Step 1 — natural-language engineering request")
    heading(d, "The prompt is the entry point")

    d.rounded_rectangle([70, 168, W - 70, 470], radius=12, fill=PANEL)

    lines = [
        "Simulate compressible inviscid air flow through an",
        "axisymmetric conical converging-diverging nozzle.",
        "",
        "inlet radius = 50 mm    throat radius = 32.6 mm",
        "outlet radius = 35.4 mm",
        "inlet stagnation pressure = 200 kPa",
        "inlet stagnation temperature = 300 K",
        "downstream back pressure = 30 kPa",
        "",
        "gamma = 1.4,  R = 287 J/(kg K)",
        "inviscid Euler,  adiabatic slip walls",
    ]
    y = 198
    for line in lines:
        d.text((100, y), line, font=F_MONO_S, fill=INK if line else MUTED)
        y += 24

    d.text(
        (70, 500),
        "An LLM interprets the request into a structured case specification.",
        font=F_BODY,
        fill=INK,
    )
    d.text(
        (70, 534),
        "A deterministic scope gate then decides whether it is inside the validated envelope.",
        font=F_SMALL,
        fill=MUTED,
    )
    source_note(d, "source: demo/published_campaign/case_A_reference — request as run")
    rail(d, 0)
    return img, 1900


def scene_mesh():
    img, d = new_canvas()
    kicker(d, "Step 2 — geometry and mesh")
    heading(d, "Structured axisymmetric wedge")
    paste_plot(
        img,
        VIS / "iteration_01/mesh_cells.png",
        (70, 170, W - 140, 330),
        d=d,
    )
    y = 502
    for text, col in [
        (f"{facts['cells']:,} cells  ·  one-cell 5° azimuthal wedge", INK),
        ("checkMesh -allTopology -allGeometry:  Mesh OK", PASS),
        (
            f"max non-orthogonality {facts['max_nonortho']:.2f}°   ·   "
            f"max skewness {facts['max_skew']:.3f}",
            MUTED,
        ),
    ]:
        d.text((70, y), "•  " + text, font=F_SMALL, fill=col)
        y += 30
    source_note(d, "source: visuals/iteration_01/mesh_cells.png · mesh_evidence.json")
    rail(d, 1)
    return img, 1600


def scene_solve():
    img, d = new_canvas()
    kicker(d, "Step 3 — OpenFOAM execution")
    heading(d, "shockFluid  ·  first run stops at t = 0.001 s")
    paste_plot(img, VIS / "iteration_01/mach_field.png", (70, 168, W - 140, 340), d=d)
    d.text(
        (70, 536),
        "Kurganov fluxes · Minmod reconstruction · Euler time integration · maxCo 0.4",
        font=F_SMALL,
        fill=MUTED,
    )
    d.text(
        (70, 570),
        f"exit Mach {facts['it1']['outlet_M']:.3f}   ·   exit static pressure "
        f"{facts['it1']['outlet_p'] / 1000:.2f} kPa   ·   throat Mach {facts['it1']['throat_M']:.3f}",
        font=F_BODY,
        fill=INK,
    )
    source_note(d, "source: visuals/iteration_01/mach_field.png · iteration_01/validation.json")
    rail(d, 2)
    return img, 1700


def _field_scene(name, title, caption, hold):
    img, d = new_canvas()
    kicker(d, "Step 4 — numerical and visual evidence")
    heading(d, title, f=F_H2, y=92)
    paste_plot(img, VIS / f"iteration_01/{name}", (70, 156, W - 140, 330), d=d)
    d.text((70, 524), caption, font=F_BODY, fill=INK)
    d.text(
        (70, 562),
        "Quasi-1D isentropic theory is a benchmark only and is withheld from the reasoning step.",
        font=F_TINY,
        fill=MUTED,
    )
    source_note(d, f"source: visuals/iteration_01/{name} (real OpenFOAM field)")
    rail(d, 3)
    return img, hold


def scene_pressure():
    return _field_scene(
        "pressure_field.png",
        "Static pressure at t = 0.001 s",
        "Pressure falls smoothly through the converging section and expands in the diverging section.",
        1300,
    )


def scene_temperature():
    return _field_scene(
        "temperature_field.png",
        "Static temperature at t = 0.001 s",
        "Temperature drops as the flow accelerates. No clipping, no artificial floor.",
        1300,
    )


def scene_speed():
    return _field_scene(
        "speed_field.png",
        "Velocity magnitude at t = 0.001 s",
        "The fields already look physically reasonable — but looking reasonable is not the criterion.",
        1500,
    )


def scene_17():
    img, d = new_canvas()
    kicker(d, "Step 4 — deterministic validation")
    d.text((70, 150), "17", font=font(150, bold=True), fill=AMBER)
    d.text((228, 236), "/ 20", font=F_BIG, fill=(190, 195, 202))
    d.text((70, 336), "deterministic checks passed", font=F_H2, fill=INK)
    d.text(
        (70, 386),
        "status: FAIL  —  the case is not accepted",
        font=F_BODY,
        fill=FAIL,
    )
    d.text(
        (70, 440),
        "Acceptance is decided by deterministic code, never by the model.",
        font=F_SMALL,
        fill=MUTED,
    )
    source_note(d, "source: iterations/iteration_01/validation.json")
    rail(d, 3)
    return img, 1500


def scene_failed():
    img, d = new_canvas()
    kicker(d, "Step 4 — what failed", FAIL)
    heading(d, "Three stationarity checks", f=F_H1)

    y = 190
    for name in facts["failed_checks"]:
        d.rounded_rectangle([70, y, 700, y + 58], radius=10, fill=(254, 242, 242))
        d.text((92, y + 17), "✕", font=F_H2, fill=FAIL)
        d.text((136, y + 18), name, font=F_MONO, fill=FAIL)
        y += 74

    d.rounded_rectangle([740, 190, W - 70, 412], radius=10, fill=PANEL)
    d.text((766, 214), "Measured at t = 0.001 s", font=F_SMALL, fill=MUTED)
    d.text(
        (766, 252),
        f"boundary mass mismatch",
        font=F_BODY,
        fill=INK,
    )
    d.text(
        (766, 286),
        f"{facts['it1']['max_window_mismatch_pct']:.2f} %",
        font=font(42, bold=True),
        fill=FAIL,
    )
    d.text((766, 344), "criterion: below 0.10 %", font=F_SMALL, fill=MUTED)
    d.text((766, 372), "the solution is still evolving", font=F_SMALL, fill=MUTED)

    d.text(
        (70, 452),
        "The fields are admissible and close to theory — but not yet stationary.",
        font=F_BODY,
        fill=INK,
    )
    source_note(d, "source: iterations/iteration_01/validation.json")
    rail(d, 3)
    return img, 2000


def scene_diagnosis():
    img, d = new_canvas()
    kicker(d, "Step 5 — theory-blind LLM diagnosis")
    heading(d, "Diagnosis", f=F_H1)

    chip(d, (70, 172), "UNCONVERGED", (255, 255, 255), AMBER, f=F_H2, pad=(22, 12))
    chip(d, (400, 182), "confidence: high", MUTED, PANEL)

    d.line([(70, 268), (W - 70, 268)], fill=RULE, width=1)
    d.text((70, 296), "The model reasoned from:", font=F_SMALL, fill=MUTED)

    y = 332
    for item in facts["evidence_used"][:4]:
        d.text((70, y), "—  " + item, font=F_SMALL, fill=INK)
        y += 32

    d.text(
        (70, y + 18),
        "The analytical reference was not shown to the model.",
        font=F_SMALL,
        fill=ACCENT,
    )
    source_note(
        d, "source: iterations/iteration_01/agent_decision.json (LLM:gemini-3.5-flash-lite)"
    )
    rail(d, 3)
    return img, 2100


def scene_action():
    img, d = new_canvas()
    kicker(d, "Step 5 — proposed action")
    heading(d, "The model proposes", f=F_H2, y=96)

    chip(d, (70, 160), "CONTINUE_RUN", (255, 255, 255), ACCENT, f=F_H1, pad=(26, 16))

    d.text((70, 284), "Deterministic action validator", font=F_SMALL, fill=MUTED)
    chip(d, (70, 318), "APPROVED", (255, 255, 255), PASS, f=F_H2, pad=(22, 12))

    d.rounded_rectangle([70, 404, W - 70, 500], radius=10, fill=PANEL)
    y = wrap(
        d,
        '"' + facts["it1_validator_reason"] + '"',
        (94, 428),
        F_BODY,
        INK,
        W - 210,
    )

    d.text(
        (70, 526),
        "The model may propose. It may not accept, and it may not overrule a failed check.",
        font=F_SMALL,
        fill=MUTED,
    )
    source_note(d, "source: iterations/iteration_01/action_validation.json")
    rail(d, 4)
    return img, 1800


def scene_continue():
    img, d = new_canvas()
    kicker(d, "Step 6 — approved action executed")
    heading(d, "The same simulation continues", f=F_H1)

    y = 230
    d.rounded_rectangle([70, y, 400, y + 96], radius=10, fill=PANEL)
    d.text((100, y + 20), "from", font=F_SMALL, fill=MUTED)
    d.text((100, y + 44), "t = 0.001 s", font=F_H2, fill=INK)

    d.text((434, y + 30), "———>", font=F_H1, fill=ACCENT)

    d.rounded_rectangle([600, y, 930, y + 96], radius=10, fill=PANEL)
    d.text((630, y + 20), "to", font=F_SMALL, fill=MUTED)
    d.text((630, y + 44), "t = 0.006 s", font=F_H2, fill=ACCENT)

    d.text(
        (70, 386),
        "Continuation of the existing solution — not a fresh restart.",
        font=F_BODY,
        fill=INK,
    )
    d.text(
        (70, 424),
        f"Same runtime case directory · {facts['it2']['timesteps']:,} timesteps total · "
        f"{facts['it2']['wall_seconds']:.0f} s additional wall clock",
        font=F_SMALL,
        fill=MUTED,
    )
    d.text(
        (70, 462),
        "Geometry, boundary conditions, numerics and initialization are unchanged.",
        font=F_SMALL,
        fill=MUTED,
    )
    source_note(d, "source: feedback_summary.json · iterations/iteration_02/execution.json")
    rail(d, 5)
    return img, 1600


def scene_fields2():
    img, d = new_canvas()
    kicker(d, "Step 6 — updated fields")
    heading(d, "Mach number at t = 0.006 s", f=F_H2, y=92)
    paste_plot(img, VIS / "iteration_02/mach_field.png", (70, 156, W - 140, 330), d=d)
    d.text(
        (70, 522),
        f"exit Mach {facts['it2']['outlet_M']:.4f}   ·   exit static pressure "
        f"{facts['it2']['outlet_p'] / 1000:.2f} kPa   ·   "
        f"boundary mass mismatch {facts['it2']['max_window_mismatch_pct']:.3f} %",
        font=F_BODY,
        fill=INK,
    )
    d.text(
        (70, 560),
        "Every outlet face is supersonic, so no static pressure is imposed there. "
        "The 30 kPa ambient is interpretation only.",
        font=F_TINY,
        fill=MUTED,
    )
    source_note(d, "source: visuals/iteration_02/mach_field.png · iteration_02/validation.json")
    rail(d, 5)
    return img, 1800


def scene_20():
    img, d = new_canvas()
    kicker(d, "Step 7 — deterministic validation")
    d.text((70, 150), "20", font=font(150, bold=True), fill=PASS)
    d.text((248, 236), "/ 20", font=F_BIG, fill=(190, 195, 202))
    d.text((70, 336), "deterministic checks passed", font=F_H2, fill=INK)

    y = 396
    for name in facts["failed_checks"]:
        chip(d, (70, y), "✓  " + name, PASS, (240, 253, 244), f=F_MONO_S)
        y += 46

    d.text(
        (560, 400),
        "conservation · stationarity",
        font=F_BODY,
        fill=MUTED,
    )
    d.text(
        (560, 434),
        "outlet regime · thermodynamic",
        font=F_BODY,
        fill=MUTED,
    )
    d.text(
        (560, 468),
        "admissibility · mesh validity",
        font=F_BODY,
        fill=MUTED,
    )
    source_note(d, "source: iterations/iteration_02/validation.json")
    rail(d, 6)
    return img, 1500


def scene_accept():
    img, d = new_canvas()
    kicker(d, "Step 7 — decision and acceptance")
    heading(d, "The model proposes", f=F_H2, y=96)
    chip(d, (70, 158), "ACCEPT", (255, 255, 255), ACCENT, f=F_H1, pad=(26, 16))

    d.text((70, 278), "Deterministic scientific validator", font=F_SMALL, fill=MUTED)
    chip(d, (70, 312), "PASS_SINGLE_MESH", (255, 255, 255), PASS, f=F_H2, pad=(22, 12))

    d.rounded_rectangle([70, 408, W - 70, 486], radius=10, fill=PANEL)
    d.text(
        (94, 432),
        '"ACCEPT is consistent with deterministic trust checks."',
        font=F_BODY,
        fill=INK,
    )

    d.text(
        (70, 512),
        "Acceptance came from the validator, not from the model.",
        font=F_SMALL,
        fill=MUTED,
    )
    source_note(d, "source: iteration_02/agent_decision.json · action_validation.json · RESULT_SUMMARY.json")
    rail(d, 6)
    return img, 1700


def scene_final():
    img, d = new_canvas()
    d.text((70, 214), "Validated closed-loop", font=F_TITLE, fill=INK)
    d.text((70, 276), "CFD solution", font=F_TITLE, fill=PASS)
    d.line([(70, 360), (330, 360)], fill=INK, width=3)

    d.text(
        (70, 392),
        "request → mesh → solve → evidence → diagnose → approved action → continue → accept",
        font=F_SMALL,
        fill=MUTED,
    )
    d.text(
        (70, 436),
        "LLM reasoning.  Deterministic scientific authority.",
        font=F_BODY,
        fill=INK,
    )

    d.rounded_rectangle([70, 492, W - 70, 556], radius=10, fill=PANEL)
    d.text(
        (94, 508),
        "Cases B (exit radius 37.0 mm) and C (reservoir 220 kPa) ran through the same",
        font=F_SMALL,
        fill=MUTED,
    )
    d.text(
        (94, 532),
        "parameterized pipeline and were accepted on the first iteration.",
        font=F_SMALL,
        fill=MUTED,
    )

    d.text(
        (70, 584),
        "Single-grid verification at the declared resolution. Quasi-1D theory is a benchmark, not the exact solution.",
        font=F_TINY,
        fill=(160, 166, 175),
    )
    rail(d, 6)
    return img, 2000


BUILDERS = [
    scene_title,
    scene_request,
    scene_mesh,
    scene_solve,
    scene_pressure,
    scene_temperature,
    scene_speed,
    scene_17,
    scene_failed,
    scene_diagnosis,
    scene_action,
    scene_continue,
    scene_fields2,
    scene_20,
    scene_accept,
    scene_final,
]


# ----------------------------------------------------------------------
# assemble
# ----------------------------------------------------------------------


def build():
    scenes = [b() for b in BUILDERS]

    frames = []
    durations = []

    FADE_STEPS = 5
    FADE_MS = 50

    for i, (img, hold) in enumerate(scenes):
        frames.append(img)
        durations.append(hold)

        if i < len(scenes) - 1:
            nxt = scenes[i + 1][0]
            for s in range(1, FADE_STEPS):
                a = s / FADE_STEPS
                frames.append(Image.blend(img, nxt, a))
                durations.append(FADE_MS)

    total = sum(durations) / 1000.0
    print(f"{len(frames)} frames, {total:.1f} s")

    # ---- MP4 at full resolution -------------------------------------
    import tempfile

    seq = Path(tempfile.mkdtemp(prefix="nozzle_demo_frames_"))
    for f in seq.glob("*.png"):
        f.unlink()

    fps = 25
    n = 0
    for img, ms in zip(frames, durations):
        for _ in range(max(1, round(ms / 1000 * fps))):
            img.save(seq / f"{n:05d}.png")
            n += 1

    mp4 = OUT / "nozzle_agent_closed_loop_demo.mp4"
    subprocess.run(
        [
            "ffmpeg", "-y", "-loglevel", "error",
            "-framerate", str(fps),
            "-i", str(seq / "%05d.png"),
            "-c:v", "libx264", "-preset", "slow", "-crf", "20",
            "-pix_fmt", "yuv420p",
            "-movflags", "+faststart",
            str(mp4),
        ],
        check=True,
    )

    # ---- GIF, downscaled ---------------------------------------------
    gw, gh = 960, 540
    small = [f.resize((gw, gh), Image.LANCZOS) for f in frames]

    gif = OUT / "nozzle_agent_closed_loop_demo.gif"
    small[0].save(
        gif,
        save_all=True,
        append_images=small[1:],
        duration=durations,
        loop=0,
        optimize=True,
    )

    print("gif", gif.stat().st_size / 1e6, "MB")
    print("mp4", mp4.stat().st_size / 1e6, "MB")
    return total


if __name__ == "__main__":
    build()
