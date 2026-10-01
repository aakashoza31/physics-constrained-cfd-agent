#!/usr/bin/env python3
"""Agent-loop architecture diagram for the CFD Forge paper.

Stage call counts and proposal rulings are read from data/agent_stats.json
(scripts/scan_agent_sessions.py); nothing else in the figure is data.
"""
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch

ROOT = Path(__file__).resolve().parents[1]
st = json.loads((ROOT / "data/agent_stats.json").read_text())
calls = st["model_calls_by_stage"]
rul = st["rulings"]
appr = sum(v for k, v in rul.items() if k.endswith("APPROVED"))
refu = sum(v for k, v in rul.items() if k.endswith("REJECTED"))

LLM, DET, TOOL, INK, INK2 = "#dbe8fb", "#fde3d6", "#e3f4ea", "#0b0b0b", "#52514e"
EDGE = {"llm": "#2a78d6", "det": "#eb6834", "tool": "#1baf7a", "io": INK2}
FILL = {"llm": LLM, "det": DET, "tool": TOOL, "io": "#f3f2ef"}
plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 7})

fig, ax = plt.subplots(figsize=(6.5, 3.5))
ax.set_xlim(-0.5, 100.5); ax.set_ylim(3, 54); ax.axis("off")
lanes = [(41, 53, "Language model (gemini-3.5-flash-lite, schema-constrained JSON): proposes", "llm", 45.5),
         (23, 35, "Deterministic layer: decides admissibility and acceptance", "det", 28),
         (5, 17, "Registered tools: execute", "tool", 10)]
for y0, y1, lab, k, _ in lanes:
    ax.add_patch(plt.Rectangle((-0.5, y0), 101, y1 - y0, fc=FILL[k], ec="none", alpha=0.35))
    if k == "tool":
        ax.text(0.5, y0 + 0.5, lab, fontsize=6.3, color=EDGE[k], fontweight="bold", va="bottom")
    else:
        ax.text(0.5, y1 - 0.4, lab, fontsize=6.3, color=EDGE[k], fontweight="bold", va="top")
YL, YD, YT = 45.5, 28, 10

B = {}
def box(key, x, y, text, kind, w=13.4, h=6.6):
    ax.add_patch(FancyBboxPatch((x - w / 2, y - h / 2), w, h, boxstyle="round,pad=0.2,rounding_size=0.8",
                                fc=FILL[kind], ec=EDGE[kind], lw=0.9))
    ax.text(x, y, text, ha="center", va="center", fontsize=5.2, linespacing=1.12)
    B[key] = (x, y, w, h)

def arrow(a, b, side_a="r", side_b="l", text=None, color=INK2, rad=0.0, tx=None, ty=None, ha="center"):
    def pt(k, s):
        x, y, w, h = B[k]
        return {"r": (x + w / 2 + 0.3, y), "l": (x - w / 2 - 0.3, y), "t": (x, y + h / 2 + 0.3),
                "b": (x, y - h / 2 - 0.3)}[s]
    p, q = pt(a, side_a), pt(b, side_b)
    ax.annotate("", xy=q, xytext=p, arrowprops=dict(arrowstyle="-|>", lw=0.8, color=color,
                                                    shrinkA=0, shrinkB=0, mutation_scale=7,
                                                    connectionstyle=f"arc3,rad={rad}"))
    if text:
        ax.text(tx, ty, text, fontsize=5.4, color=color, ha=ha, va="center", linespacing=1.05)

box("req", 6, YD, "Engineering\nrequest\n(text)", "io", w=10.5)
box("interp", 20, YL, f"Interpretation\n→ case spec\n({calls['interpretation']} calls)", "llm")
box("scope", 20, YD, "Scope gate\n(family\nenvelope)", "det")
box("build", 35, YT, "Case builder\nmesh dicts,\n0/, system/", "tool")
box("mreview", 35, YL, f"Mesh review\n(nozzle;\n{calls['mesh review']} calls)", "llm")
box("mgate", 35, YD, "Mesh gate\n(checkMesh\nrecord)", "det")
box("run", 50, YT, "OpenFOAM\nfoamRun\n(v14)", "tool")
box("evid", 50, YD, "Evidence packet\n(theory- and\nreference-blind)", "det")
box("obs", 50, YL, f"Field images\n(advisory;\n{calls['field observation']} calls)", "llm")
box("diag", 65, YL, f"Diagnosis +\none action\n({calls['diagnosis']} calls)", "llm")
box("aval", 65, YD, f"Action validator\n{appr} approved\n{refu} refused", "det")
box("act", 65, YT, "Execute action\n(continue, extend,\nrefine)", "tool")
box("sval", 80, YD, "Scientific\nvalidator\n(contract)", "det")
box("verdict", 94, YD, "ACCEPT\nREJECT\nINCONCLUSIVE", "io", w=11.5)
box("report", 94, YL, f"Engineering\nsummary\n({calls['summary']} calls)", "llm", w=11.5)

arrow("req", "scope")
arrow("req", "interp", "t", "l", rad=-0.3)
arrow("interp", "scope", "b", "t")
arrow("scope", "build", "b", "l", rad=0.3, text="admissible", tx=20.3, ty=17.5, ha="right")
arrow("build", "mgate", "t", "b")
arrow("mgate", "mreview", "t", "b", color=EDGE["llm"])
arrow("mgate", "run", "r", "l", text="proceed", tx=43.6, ty=19.6, ha="left")
arrow("run", "evid", "t", "b")
arrow("evid", "obs", "t", "b", color=EDGE["llm"])
arrow("evid", "diag", "r", "l", rad=0.2, color=EDGE["llm"])
arrow("diag", "aval", "b", "t", text="proposal", tx=66, ty=37.8, ha="left")
arrow("aval", "act", "b", "t", text="approved\ncorrection", tx=66, ty=19.6, ha="left")
arrow("act", "run", "l", "r", text="re-run", tx=57.5, ty=14.7)
arrow("aval", "sval", "r", "l", text="ACCEPT", tx=72.5, ty=33.3)
arrow("sval", "verdict", "r", "l")
arrow("verdict", "report", "t", "b", color=EDGE["llm"])
ax.text(84, 21.5, "binding verdict;\nthe model cannot\noverride it", ha="center", va="top", fontsize=5.4,
        color=EDGE["det"])
fig.savefig(ROOT / "figures/fig_agent_loop.pdf", bbox_inches="tight")
fig.savefig(ROOT / "figures/fig_agent_loop.png", bbox_inches="tight", dpi=220)
print("ok", appr, refu)
