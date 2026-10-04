#!/usr/bin/env python3
"""Agent-loop architecture diagram for the CFD Forge paper.

Stage call counts and proposal rulings are read from data/agent_stats.json
(produced by the recount in scripts/recount_agent_calls.py); nothing else in the
figure is data. Output: figures/fig_agent_loop.pdf and .png.

Usage:  python3 scripts/make_agent_loop_figure.py   (from paper/cfd_forge/)
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

fig, ax = plt.subplots(figsize=(6.5, 3.9))
ax.set_xlim(-7, 100.5); ax.set_ylim(1, 62); ax.axis("off")
# lanes: (bottom, top, title, kind); boxes sit below a title strip
lanes = [(43, 61, "Language model\nproposes", "llm"),
         (22, 40, "Deterministic layer\ndecides", "det"),
         (1.5, 19, "Registered tools\nexecute", "tool")]
for y0, y1, lab, k in lanes:
    ax.add_patch(plt.Rectangle((-7, y0), 107.5, y1 - y0, fc=FILL[k], ec="none", alpha=0.35))
    ax.text(-4.2, (y0 + y1) / 2, lab, fontsize=6.0, color=EDGE[k], fontweight="bold", va="center",
            ha="center", rotation=90, linespacing=1.15)
YL, YD, YT = 50, 29, 8.5

B = {}
def box(key, x, y, text, kind, w=12.4, h=7.4):
    ax.add_patch(FancyBboxPatch((x - w / 2, y - h / 2), w, h, boxstyle="round,pad=0.2,rounding_size=0.8",
                                fc=FILL[kind], ec=EDGE[kind], lw=0.9, zorder=3))
    ax.text(x, y, text, ha="center", va="center", fontsize=4.9, linespacing=1.12, zorder=4)
    B[key] = (x, y, w, h)

def P(k, s, off=0.0):
    x, y, w, h = B[k]
    return {"r": (x + w / 2 + 0.25, y + off), "l": (x - w / 2 - 0.25, y + off),
            "t": (x + off, y + h / 2 + 0.25), "b": (x + off, y - h / 2 - 0.25)}[s]

def path(pts, color=INK2, text=None, tx=None, ty=None, ha="left"):
    xs, ys = zip(*pts)
    ax.plot(xs[:-1] + (xs[-1],), ys[:-1] + (ys[-1],), color=color, lw=0.8, zorder=2,
            solid_capstyle="butt", solid_joinstyle="miter")
    ax.annotate("", xy=pts[-1], xytext=pts[-2], arrowprops=dict(arrowstyle="-|>", lw=0.8, color=color,
                shrinkA=0, shrinkB=0, mutation_scale=7), zorder=2)
    if text:
        ax.text(tx, ty, text, fontsize=5.3, color=color, ha=ha, va="center", linespacing=1.05, zorder=5,
                bbox=dict(fc="white", ec="none", pad=0.6, alpha=0.9))

box("req", 6, YD, "Engineering\nrequest\n(text)", "io", w=10.5)
box("interp", 20, YL, f"Interpretation\n→ case spec\n({calls['interpretation']} calls)", "llm")
box("scope", 20, YD, "Scope gate\n(family\nenvelope)", "det")
box("build", 20, YT, "Case builder\nmesh dicts,\n0/, system/", "tool")
box("mreview", 35, YL, f"Mesh review\n(nozzle;\n{calls['mesh review']} calls)", "llm")
box("mgate", 35, YD, "Mesh gate\n(checkMesh\nrecord)", "det")
box("run", 50, YT, "OpenFOAM\nfoamRun\n(v14)", "tool")
box("evid", 50, YD, "Evidence packet\n(theory- and\nreference-blind)", "det")
box("obs", 50, YL, f"Field images\n(advisory;\n{calls['field observation']} calls)", "llm")
box("diag", 65, YL, f"Diagnosis +\none action\n({calls['diagnosis']} calls)", "llm")
box("aval", 65, YD, f"Action validator\n{appr} approved\n{refu} refused", "det")
box("act", 65, YT, "Execute action\n(continue,\nextend, refine)", "tool")
box("sval", 80, YD, "Scientific\nvalidator\n(contract)", "det")
box("verdict", 94, YD, "ACCEPT\nREJECT\nINCONCLUSIVE", "io", w=12.0)
box("report", 94, YL, f"Engineering\nsummary\n({calls['summary']} calls)", "llm", w=12.0)

L = EDGE["llm"]
# request -> interpretation (elbow up), interpretation -> scope gate (down)
x0, y0 = P("req", "t"); x1, y1 = P("interp", "l")
path([(x0, y0), (x0, y1), (x1, y1)])
path([P("interp", "b"), P("scope", "t")])
# scope -> case builder (down), builder -> mesh gate (elbow), mesh gate <-> mesh review
path([P("scope", "b"), P("build", "t")], text="admissible", tx=20.9, ty=16.6)
xb, yb = P("build", "r"); xm, ym = P("mgate", "b")
path([(xb, yb), (xm, yb), (xm, ym)])
path([P("mgate", "t"), P("mreview", "b")], color=L)
# mesh gate -> OpenFOAM (elbow right/down/right)
xg, yg = P("mgate", "r"); xr, yr = P("run", "l")
xmid = 42.5
path([(xg, yg), (xmid, yg), (xmid, yr), (xr, yr)], text="proceed", tx=xmid + 0.7, ty=16.6)
# OpenFOAM -> evidence -> field images; evidence -> diagnosis (elbow)
path([P("run", "t"), P("evid", "b")])
path([P("evid", "t"), P("obs", "b")], color=L)
xe, ye = P("evid", "r"); xd, yd = P("diag", "l")
xm2 = 57.5
path([(xe, ye), (xm2, ye), (xm2, yd), (xd, yd)], color=L)
# diagnosis -> action validator -> execute -> re-run
path([P("diag", "b"), P("aval", "t")], text="proposal", tx=65.9, ty=41.5)
path([P("aval", "b"), P("act", "t")], text="approved\ncorrection", tx=65.9, ty=19.6)
path([P("act", "l"), P("run", "r")], text="re-run", tx=57.5, ty=YT - 5.6, ha="center")
# accept path
path([P("aval", "r"), P("sval", "l")], text="ACCEPT\nproposal", tx=72.6, ty=YD + 5.6, ha="center")
path([P("sval", "r"), P("verdict", "l")])
path([P("verdict", "t"), P("report", "b")], color=L)
ax.text(87, 12.5, "binding verdict;\nthe model cannot\noverride it", ha="center", va="center", fontsize=5.4,
        color=EDGE["det"])
fig.savefig(ROOT / "figures/fig_agent_loop.pdf", bbox_inches="tight")
fig.savefig(ROOT / "figures/fig_agent_loop.png", bbox_inches="tight", dpi=220)
print("ok", appr, refu)
