#!/usr/bin/env python3
"""Real-mesh, field-evolution and agent-statistics figures for the CFD Forge paper.

Inputs (all under ../data, listed with SHA-256 in data/DATA_MANIFEST.json):
  nozzle/blockMeshDict        archived wedge mesh definition (hash-matched to the
                              native case); blockMesh with linear edges and
                              uniform grading reproduces its vertices exactly
  gmsh/gmsh_surface.npz       surface triangles of the archived Gmsh mesh from the
                              prototype CAD->Gmsh nozzle campaign (best_mesh.msh)
  step/step_mesh_poly.npz     front-patch cell polygons of the native 16,128-cell
                              step polyMesh (faces/owner/neighbour/boundary hashes
                              identical to the Mach-2 agent case)
  cube/cube_mesh_only.npz     cube and nearby-floor boundary faces of the native
                              567,360-cell polyMesh
  frames/*.png                ParaView renders of native fields from the
                              field-evolution pipeline (fixed colour ranges,
                              camera recorded in the video manifests)
  agent_stats.json            counts from scripts/scan_agent_sessions.py
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.collections import LineCollection, PolyCollection
from mpl_toolkits.mplot3d.art3d import Poly3DCollection

ROOT = Path(__file__).resolve().parents[1]
DATA, OUT = ROOT / "data", ROOT / "figures"
OUT.mkdir(exist_ok=True)
C1, C2, C3 = "#2a78d6", "#eb6834", "#1baf7a"
INK, INK2, GRID = "#0b0b0b", "#52514e", "#d9d8d4"
plt.rcParams.update({
    "font.size": 8, "axes.titlesize": 8.5, "axes.labelsize": 8, "xtick.labelsize": 7,
    "ytick.labelsize": 7, "legend.fontsize": 7, "axes.edgecolor": INK2, "axes.linewidth": 0.6,
    "xtick.color": INK2, "ytick.color": INK2, "axes.titleweight": "bold",
    "axes.titlelocation": "left", "savefig.dpi": 300, "legend.frameon": False,
    "font.family": "DejaVu Sans", "mathtext.fontset": "dejavusans"})
W = 6.5


# ----------------------------------------------------------------------
# ParaView frame helper: crop by recorded camera, rebuild axes and colourbar
# ----------------------------------------------------------------------
def frame_panel(ax, png, manifest, xlim, ylim, field, cax=None, label=None, ticks=None, mirror=False):
    """Show the pixels of a recorded parallel-projection ParaView frame.

    The camera (focal point, parallel scale) and image size map pixels to
    physical coordinates; the frame's own colour bar strip (rows 475-486,
    columns 179-559, identical in every render) supplies the exact colour map,
    and the manifest's fixed colour range gives its limits.
    """
    img = plt.imread(png)[:, :, :3]
    h, w = img.shape[:2]
    cam = json.loads(Path(manifest).read_text())["camera"]
    s = 2 * cam["parallel_scale"] / h
    fp = cam["focal_point"]
    up = cam["view_up"]
    # horizontal axis is x for every render used here; vertical is y (2-D) or z (cube slice)
    cx, cy = fp[0], (fp[2] if up == [0, 0, 1] else fp[1])
    c0 = int(round((xlim[0] - cx) / s + w / 2)); c1 = int(round((xlim[1] - cx) / s + w / 2))
    r0 = int(round(h / 2 - (ylim[1] - cy) / s)); r1 = int(round(h / 2 - (ylim[0] - cy) / s))
    ext = ((c0 - w / 2) * s + cx, (c1 - w / 2) * s + cx, (h / 2 - r1) * s + cy, (h / 2 - r0) * s + cy)
    ax.imshow(img[r0:r1, c0:c1], extent=ext, interpolation="nearest", aspect="equal")
    if mirror:  # axisymmetric case: show the reflection about the axis r = 0
        ax.imshow(img[r0:r1, c0:c1][::-1], extent=(ext[0], ext[1], -ext[3], -ext[2]),
                  interpolation="nearest", aspect="equal")
        ax.axhline(0, color="white", lw=0.4, ls=(0, (4, 3)), alpha=0.7)
    ax.set_xlim(*xlim); ax.set_ylim(-ylim[1] if mirror else ylim[0], ylim[1])
    if cax is not None:
        lo, hi = json.loads(Path(manifest).read_text())["fixed_color_ranges"][field]
        bar = img[475:486, 179:559]
        cax.imshow(bar, extent=(lo, hi, 0, 1), aspect="auto")
        cax.set_yticks([]); cax.tick_params(labelsize=6, pad=1)
        if ticks is not None:
            cax.set_xticks(ticks)
        if label:
            cax.set_xlabel(label, fontsize=7, labelpad=1)


# ----------------------------------------------------------------------
# meshes
# ----------------------------------------------------------------------
def nozzle_wedge_mesh():
    s = (DATA / "nozzle/blockMeshDict").read_text()
    body = re.search(r"vertices\s*\((.*?)\);", s, re.S)[1]
    v = np.array([list(map(float, t.split())) for t in re.findall(r"\(([^()]+)\)", body)])
    rim = v[1::3]
    xb, rb = rim[:, 0], np.hypot(rim[:, 1], rim[:, 2])
    half = np.arctan2(abs(rim[0, 2]), rim[0, 1])
    ncell = [20, 40, 4, 48, 20]
    xs = np.concatenate([np.linspace(xb[j], xb[j + 1], n + 1)[(0 if j == 0 else 1):] for j, n in enumerate(ncell)])
    rw = np.interp(xs, xb, rb)
    return xs, rw, half


def fig_meshes():
    """Two figures: nozzle meshes (blockMesh wedge, prototype Gmsh) and step/cube meshes."""
    # ---------------- nozzle ----------------
    fig = plt.figure(figsize=(W, 3.6))
    gs = fig.add_gridspec(2, 1, height_ratios=[0.52, 1.0], hspace=0.6)
    ax = fig.add_subplot(gs[0])
    xs, rw, half = nozzle_wedge_mesh()
    quads = []
    for i in range(len(xs) - 1):
        for k in range(16):
            quads.append([(xs[i] * 1e3, rw[i] * k / 16 * 1e3), (xs[i + 1] * 1e3, rw[i + 1] * k / 16 * 1e3),
                          (xs[i + 1] * 1e3, rw[i + 1] * (k + 1) / 16 * 1e3), (xs[i] * 1e3, rw[i] * (k + 1) / 16 * 1e3)])
    ax.add_collection(PolyCollection(quads, facecolor="#eef3fa", edgecolor=INK2, linewidths=0.3))
    ax.plot(xs * 1e3, rw * 1e3, color=INK, lw=0.9)
    ax.set_xlim(xs[0] * 1e3 - 2, xs[-1] * 1e3 + 2); ax.set_ylim(0, rw.max() * 1e3 * 1.05)
    ax.set_aspect("equal")
    ax.set_xlabel("x (mm)", labelpad=1); ax.set_ylabel("r (mm)", labelpad=1)
    ax.set_title(f"(a) Agent nozzle case: {len(xs) - 1} × 16 = {(len(xs) - 1) * 16:,} cells "
                 f"on a {np.degrees(2 * half):.0f}° wedge (blockMesh, x–r plane)")
    ax = fig.add_subplot(gs[1])
    g = np.load(DATA / "gmsh/gmsh_surface.npz")
    X = g["X"] * 1e3
    tris = np.concatenate([g[f"tri_{k}"] for k in (1, 2, 4, 5, 6)])
    tris = tris[X[tris][:, :, 1].mean(1) <= 1e-9]   # back half of the wall (y <= 0)
    # orthographic side view along +y: the back half projects one-to-one onto x-z
    shade = 0.75 + 0.25 * (-X[tris][:, :, 1].mean(1) / 50.0)
    ax.add_collection(PolyCollection(X[tris][:, :, [0, 2]], facecolors=plt.cm.Oranges(0.05 + 0.12 * shade),
                                     edgecolor=INK2, linewidths=0.15))
    ax.set_xlim(-2, 332); ax.set_ylim(-52, 52); ax.set_aspect("equal")
    ax.set_xlabel("x (mm)", labelpad=1); ax.set_ylabel("z (mm)", labelpad=1)
    ax.set_title(f"(b) Prototype CAD→Gmsh nozzle: {int(g['ntet']):,} tetrahedra "
                 "(wall surface triangles, back half, side view)")
    fig.savefig(OUT / "fig_mesh_nozzle.pdf", bbox_inches="tight")
    fig.savefig(OUT / "fig_mesh_nozzle.png", bbox_inches="tight", dpi=200)
    plt.close(fig)

    # ---------------- step and cube ----------------
    fig = plt.figure(figsize=(W, 5.0))
    gs = fig.add_gridspec(2, 2, height_ratios=[1.0, 1.15], hspace=0.38, wspace=0.18)
    P = np.load(DATA / "step/step_mesh_poly.npz")["poly"]
    ax = fig.add_subplot(gs[0, 0])
    xv = np.unique(np.round(P[..., 0][np.isfinite(P[..., 0])], 6))
    yv = np.unique(np.round(P[..., 1][np.isfinite(P[..., 1])], 6))
    segs = []
    for x in xv[::4]:
        segs.append([(x, 0.2 if 0.6 < x < 3 else 0), (x, 1)])
    for y in yv[::4]:
        segs.append([(0, y), (0.6 if y < 0.2 else 3, y)])
    ax.add_collection(LineCollection(segs, colors=INK2, linewidths=0.3))
    ax.add_patch(plt.Rectangle((0.6, 0), 2.4, 0.2, fc="#efeeea", ec=INK, lw=0.6))
    ax.add_patch(plt.Rectangle((0.45, 0.1), 0.3, 0.2, fc="none", ec=C2, lw=1.0))
    ax.set_xlim(0, 3); ax.set_ylim(0, 1); ax.set_aspect("equal")
    ax.set_xlabel("x", labelpad=1); ax.set_ylabel("y", labelpad=1)
    ax.set_title(f"(c) Step: {len(P):,} cells (every 4th line)")
    ax = fig.add_subplot(gs[0, 1])
    ax.add_collection(PolyCollection(P, facecolor="none", edgecolor=INK2, linewidths=0.35))
    ax.add_patch(plt.Rectangle((0.6, 0), 2.4, 0.2, fc="#efeeea", ec=INK, lw=0.8))
    ax.set_xlim(0.45, 0.75); ax.set_ylim(0.1, 0.3); ax.set_aspect("equal")
    ax.set_xlabel("x", labelpad=1)
    dx = float(np.median(np.diff(xv)))
    ax.set_title(f"(d) Step corner, every cell (Δx = Δy = {dx:.4g})")
    for sp in ax.spines.values():
        sp.set_edgecolor(C2)

    d = np.load(DATA / "cube/cube_mesh_only.npz")
    ax = fig.add_subplot(gs[1, 0], projection="3d")
    floor = d["patch_floor"]; cube = d["patch_cube"]
    def swap(q):  # (x, y, z) -> plot (x, z, y) so the wall-normal y is vertical
        return q[..., [0, 2, 1]]
    faces = np.concatenate([swap(floor), swap(cube)])
    fc = ["#eeeeea"] * len(floor) + [C2] * len(cube)
    ax.add_collection3d(Poly3DCollection(faces, facecolors=fc, edgecolor=INK2, linewidth=0.1))
    ax.set_xlim(-2, 5); ax.set_ylim(-2.5, 2.5); ax.set_zlim(0, 1.2)
    ax.set_box_aspect((7, 5, 1.2), zoom=1.35)
    ax.view_init(elev=32, azim=-55)
    ax.set_axis_off()
    ax.set_title("(e) Cube and floor surface mesh, −2 ≤ x/H ≤ 5", pad=0)

    ax = fig.add_subplot(gs[1, 1])
    lo, hi = d["lo"], d["hi"]
    m = np.isclose(lo[:, 1], 0.5, atol=1e-4)
    rects = [[(a[0], a[2]), (b[0], a[2]), (b[0], b[2]), (a[0], b[2])] for a, b in zip(lo[m], hi[m])]
    ax.add_collection(PolyCollection(rects, facecolor="none", edgecolor=INK2, linewidths=0.12))
    ax.add_patch(plt.Rectangle((0, -0.5), 1, 1, fc=C2, ec=INK, lw=0.5))
    ax.set_xlim(-2, 6); ax.set_ylim(-2.5, 2.5); ax.set_aspect("equal")
    ax.set_xlabel("x/H", labelpad=1); ax.set_ylabel("z/H", labelpad=1)
    ax.set_title(f"(f) Cube: cell layer at y/H = 0.5 ({int(m.sum()):,} cells)")
    fig.savefig(OUT / "fig_mesh_step_cube.pdf", bbox_inches="tight")
    fig.savefig(OUT / "fig_mesh_step_cube.png", bbox_inches="tight", dpi=200)
    plt.close(fig)


# ----------------------------------------------------------------------
# field evolution from recorded renders
# ----------------------------------------------------------------------
def fig_nozzle_fields():
    man = DATA / "frames/nozzle_video_manifest.json"
    fig = plt.figure(figsize=(W, 4.6))
    gs = fig.add_gridspec(3, 1, hspace=0.12)
    spec = [("mach", "nozzle_mach_t0.006.png", "Mach", 1),
            ("pressure", "nozzle_p_t0.006.png", "p (kPa)", 1e-3),
            ("temperature", "nozzle_T_t0.006.png", "T (K)", 1)]
    for j, (field, png, lab, scale) in enumerate(spec):
        ax = fig.add_subplot(gs[j])
        frame_panel(ax, DATA / "frames" / png, man, (0, 0.33), (0, 0.052), field, mirror=True)
        cax = ax.inset_axes([1.015, 0.0, 0.022, 1.0])
        lo, hi = json.loads(man.read_text())["fixed_color_ranges"][field]
        bar = plt.imread(DATA / "frames" / png)[475:486, 179:559, :3]
        cax.imshow(np.transpose(bar, (1, 0, 2))[::-1], extent=(0, 1, lo * scale, hi * scale), aspect="auto")
        cax.set_xticks([]); cax.yaxis.tick_right(); cax.tick_params(labelsize=6, pad=1)
        cax.set_ylabel(lab, fontsize=7, labelpad=2); cax.yaxis.set_label_position("right")
        ax.set_xticks([0, 0.05, 0.1, 0.15, 0.2, 0.25, 0.3]); ax.set_yticks([-0.05, 0, 0.05])
        ax.tick_params(labelsize=6)
        ax.set_ylabel("r (m)", fontsize=7, labelpad=1)
        if j < 2: ax.set_xticklabels([])
        else: ax.set_xlabel("x (m)", fontsize=7, labelpad=1)
    fig.savefig(OUT / "fig_nozzle_fields.pdf", bbox_inches="tight")
    fig.savefig(OUT / "fig_nozzle_fields.png", bbox_inches="tight", dpi=200)
    plt.close(fig)


def fig_step_evolution():
    man = DATA / "frames/step_video_manifest.json"
    fig = plt.figure(figsize=(W, 2.3))
    gs = fig.add_gridspec(3, 2, height_ratios=[1, 1, 0.1], hspace=0.45, wspace=0.08)
    for k, t in enumerate(["0.5", "1", "2", "4"]):
        ax = fig.add_subplot(gs[k // 2, k % 2])
        frame_panel(ax, DATA / f"frames/step_mach_t{t}.png", man, (0, 3), (0, 1), "mach")
        ax.add_patch(plt.Rectangle((0.6, 0), 2.4, 0.2, fc="#3a3a3a", ec="none", zorder=3))  # solid step
        ax.text(0.03, 0.85, f"t = {t}", fontsize=7, color="white", transform=ax.transAxes,
                bbox=dict(fc="#00000066", ec="none", pad=1))
        ax.set_xticks([0, 1, 2, 3]); ax.set_yticks([0, 1]); ax.tick_params(labelsize=6)
        if k % 2: ax.set_yticklabels([])
        if k < 2: ax.set_xticklabels([])
    cax = fig.add_subplot(gs[2, :])
    img = plt.imread(DATA / "frames/step_mach_t4.png")[:, :, :3]
    lo, hi = json.loads(man.read_text())["fixed_color_ranges"]["mach"]
    cax.imshow(img[475:486, 179:559], extent=(lo, hi, 0, 1), aspect="auto")
    cax.set_yticks([]); cax.tick_params(labelsize=6); cax.set_xlabel("Mach number", fontsize=7, labelpad=1)
    pos = cax.get_position(); cax.set_position([pos.x0 + pos.width * 0.3, pos.y0, pos.width * 0.4, pos.height])
    fig.savefig(OUT / "fig_step_evolution.pdf", bbox_inches="tight")
    fig.savefig(OUT / "fig_step_evolution.png", bbox_inches="tight", dpi=200)
    plt.close(fig)


def fig_cube_wake():
    man = DATA / "frames/cube_video_manifest.json"
    fig = plt.figure(figsize=(W, 1.75))
    gs = fig.add_gridspec(2, 4, height_ratios=[1, 0.1], hspace=0.6, wspace=0.08)
    for k, t in enumerate(["20", "40", "60", "80"]):
        ax = fig.add_subplot(gs[0, k])
        frame_panel(ax, DATA / f"frames/cube_Uz_t{t}.png", man, (-1.5, 6.5), (-1.7, 1.7), "wake")
        ax.set_title(f"t* = {t}", fontsize=7.5)
        ax.tick_params(labelsize=6); ax.set_xticks([0, 3, 6]); ax.set_yticks([-1, 0, 1])
        if k: ax.set_yticklabels([])
        else: ax.set_ylabel("z/H", fontsize=7)
        ax.set_xlabel("x/H", fontsize=7, labelpad=0)
    cax = fig.add_subplot(gs[1, 1:3])
    img = plt.imread(DATA / "frames/cube_Uz_t80.png")[:, :, :3]
    lo, hi = json.loads(man.read_text())["fixed_color_ranges"]["wake"]
    cax.imshow(img[475:486, 179:559], extent=(lo, hi, 0, 1), aspect="auto")
    cax.set_yticks([]); cax.tick_params(labelsize=6)
    cax.set_xlabel("lateral velocity $U_z/U_b$ on y/H = 0.5", fontsize=7, labelpad=1)
    fig.savefig(OUT / "fig_cube_wake.pdf", bbox_inches="tight")
    fig.savefig(OUT / "fig_cube_wake.png", bbox_inches="tight", dpi=200)
    plt.close(fig)


# ----------------------------------------------------------------------
# agent statistics
# ----------------------------------------------------------------------
def fig_agent_stats():
    st = json.loads((DATA / "agent_stats.json").read_text())
    calls = st["model_calls_by_stage"]
    order = ["interpretation", "mesh review", "diagnosis", "field observation", "summary"]
    fig, axs = plt.subplots(1, 2, figsize=(W, 1.9), gridspec_kw=dict(wspace=0.55, width_ratios=[1, 1.1]))
    ax = axs[0]
    vals = [calls.get(k, 0) for k in order]
    failed = calls.get("field observation (failed)", 0)
    y = np.arange(len(order))[::-1]
    ax.barh(y, vals, color=C1, height=0.6)
    ax.barh(y[3], failed, color=C2, height=0.6)
    for yy, v in zip(y, vals):
        ax.text(v + 0.4, yy, str(v), va="center", fontsize=7)
    ax.text(failed / 2, y[3], f"{failed} failed", va="center", ha="center", fontsize=6, color="white")
    ax.set_yticks(y, order); ax.set_xlim(0, 27)
    ax.set_xlabel("model calls")
    ax.set_title(f"(a) {sum(vals)} model calls in {st['n_sessions']} sessions")
    ax.grid(axis="x", color=GRID, lw=0.5); ax.set_axisbelow(True)
    ax = axs[1]
    acts = ["ACCEPT", "CONTINUE_RUN", "EXTEND_END_TIME", "FAIL_SAFELY", "REFINE_MESH"]
    ok = [st["rulings"].get(f"{a}|APPROVED", 0) for a in acts]
    no = [st["rulings"].get(f"{a}|REJECTED", 0) for a in acts]
    y = np.arange(len(acts))[::-1]
    ax.barh(y, ok, color=C1, height=0.6, label="approved")
    ax.barh(y, no, left=ok, color=C2, height=0.6, label="refused by validator")
    for yy, a, b in zip(y, ok, no):
        ax.text(a + b + 0.3, yy, f"{a}" + (f" + {b}" if b else ""), va="center", fontsize=7)
    ax.set_yticks(y, acts, fontsize=6.5); ax.set_xlim(0, 13.5)
    ax.set_xlabel("proposals")
    ax.set_title(f"(b) {sum(ok)+sum(no)} action proposals, {sum(no)} refused")
    ax.legend(loc="lower right")
    ax.grid(axis="x", color=GRID, lw=0.5); ax.set_axisbelow(True)
    fig.savefig(OUT / "fig_agent_stats.pdf", bbox_inches="tight")
    fig.savefig(OUT / "fig_agent_stats.png", bbox_inches="tight", dpi=200)
    plt.close(fig)


if __name__ == "__main__":
    fig_meshes()
    fig_nozzle_fields()
    fig_step_evolution()
    fig_cube_wake()
    fig_agent_stats()
    print("ok")
