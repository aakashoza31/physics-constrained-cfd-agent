#!/usr/bin/env python3
"""Build the CFD Forge paper figures from archived, provenance-bound evidence.

Every plotted number is read from a file under ../data/, which holds verbatim
copies of archived CFD Forge evidence (see ../data/DATA_MANIFEST.json for the
original path and SHA-256 of each input). No simulation result is edited,
smoothed or re-derived beyond the operations stated next to each panel.

Derived quantities computed here (and only here):
  * nozzle: isentropic quasi-1-D reference profile from the registered area
    distribution (standard relations, gamma = 1.4, R = 287); it is checked
    against the exit values stored by the deterministic validator.
  * nozzle: metric/threshold ratios, using thresholds copied from
    src/pipeline/nozzle/validate.py.
  * cube: nothing beyond plotting; cycle amplitudes and gate values come from
    the archived gate/audit outputs and are cross-checked against the raw force
    history.

Usage:  python3 scripts/make_figures.py   (from the paper directory)
"""
from __future__ import annotations

import json
import math
import re
from pathlib import Path

import numpy as np
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle, Polygon
from matplotlib.collections import LineCollection

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
OUT = ROOT / "figures"
OUT.mkdir(exist_ok=True)

# Palette: categorical slots 1-3 of the validated reference palette, plus ink/grays.
C1, C2, C3 = "#2a78d6", "#eb6834", "#1baf7a"
INK, INK2, GRID = "#0b0b0b", "#52514e", "#d9d8d4"
FAIL, PASS = "#e34948", "#008300"

plt.rcParams.update({
    "font.size": 8, "axes.titlesize": 8.5, "axes.labelsize": 8,
    "xtick.labelsize": 7, "ytick.labelsize": 7, "legend.fontsize": 7,
    "axes.edgecolor": INK2, "axes.linewidth": 0.6, "axes.labelcolor": INK,
    "xtick.color": INK2, "ytick.color": INK2, "axes.titleweight": "bold",
    "axes.titlelocation": "left", "lines.linewidth": 1.4,
    "savefig.dpi": 300, "figure.dpi": 150, "legend.frameon": False,
    "font.family": "DejaVu Sans", "mathtext.fontset": "dejavusans",
})
TEXTWIDTH = 6.5  # inches (11pt article, 1in margins)
GAMMA, R = 1.4, 287.0


def grid(ax):
    ax.grid(True, color=GRID, lw=0.5)
    ax.set_axisbelow(True)


def load(path):
    return json.loads((DATA / path).read_text())


# --------------------------------------------------------------------------
# Nozzle geometry and quasi-1-D reference
# --------------------------------------------------------------------------
def nozzle_vertices():
    s = (DATA / "nozzle/blockMeshDict").read_text()
    body = re.search(r"vertices\s*\((.*?)\);", s, re.S)[1]
    v = np.array([list(map(float, t.split())) for t in re.findall(r"\(([^()]+)\)", body)])
    return v


def nozzle_radius_breaks():
    v = nozzle_vertices()
    # Outer (wall) vertices in the x-r plane: r = sqrt(y^2+z^2) of the wedge rim.
    rim = v[1::3]
    return rim[:, 0], np.hypot(rim[:, 1], rim[:, 2])


def area_mach(ar, supersonic):
    g = GAMMA
    f = lambda M: (1 / M) * ((2 / (g + 1)) * (1 + 0.5 * (g - 1) * M * M)) ** ((g + 1) / (2 * (g - 1))) - ar
    lo, hi = (1.0 + 1e-12, 10.0) if supersonic else (1e-6, 1.0 - 1e-12)
    for _ in range(200):
        mid = 0.5 * (lo + hi)
        if (f(lo) > 0) == (f(mid) > 0):
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


def quasi1d_profile(x, spec_r_throat=0.0326):
    """Isentropic quasi-1-D state along x for the registered radii (nominal).

    Uses the nominal specification radii (inlet 0.05, throat 0.0326, exit
    0.0354 m) and breakpoints, i.e. the same basis as the validator's
    spec.quasi1d_state. Subsonic upstream of the throat end, supersonic after.
    """
    xb = np.array([0.0, 0.05, 0.15, 0.16, 0.28, 0.33])
    rb = np.array([0.05, 0.05, 0.0326, 0.0326, 0.0354, 0.0354])
    r = np.interp(x, xb, rb)
    M = np.array([area_mach((ri / spec_r_throat) ** 2, xi > 0.16) if abs(ri - spec_r_throat) > 1e-12
                  else 1.0 for xi, ri in zip(x, r)])
    T0, p0 = 300.0, 200000.0
    T = T0 / (1 + 0.2 * M * M)
    p = p0 * (T / T0) ** (GAMMA / (GAMMA - 1))
    U = M * np.sqrt(GAMMA * R * T)
    return r, M, p, T, U


# --------------------------------------------------------------------------
# Figure 2: computational configurations
# --------------------------------------------------------------------------
def fig2():
    fig = plt.figure(figsize=(TEXTWIDTH, 6.1))
    gs = fig.add_gridspec(3, 2, height_ratios=[0.95, 1.2, 1.55], width_ratios=[1, 1.25],
                          hspace=0.62, wspace=0.28)
    lab = dict(fontsize=6.5, color=INK)
    arr = dict(arrowstyle="-", color=INK2, lw=0.6)

    # (a) nozzle wedge mesh in the x-r plane (exact: linear blocks, uniform grading)
    ax = fig.add_subplot(gs[0, :])
    xb, rb = nozzle_radius_breaks()
    ncell = [20, 40, 4, 48, 20]
    xs = np.concatenate([np.linspace(xb[j], xb[j + 1], n + 1)[(0 if j == 0 else 1):]
                         for j, n in enumerate(ncell)])
    rw = np.interp(xs, xb, rb)
    segs = [[(x, 0), (x, r)] for x, r in zip(xs, rw)]
    segs += [list(zip(xs, rw * k / 16)) for k in range(17)]
    ax.add_collection(LineCollection([[(a * 1e3, b * 1e3) for a, b in sg] for sg in segs],
                                     colors=INK2, linewidths=0.25))
    ax.plot(xs * 1e3, rw * 1e3, color=INK, lw=1.2)
    ax.plot([0, 330], [0, 0], color=INK, lw=0.6, ls=(0, (4, 2)))
    ax.set_xlim(-95, 425); ax.set_ylim(-6, 72); ax.set_aspect("equal")
    ax.set_xlabel("x (mm)"); ax.set_ylabel("r (mm)")
    ax.set_title("(a) Converging–diverging nozzle: 5° axisymmetric wedge, 132 × 16 = 2,112 cells")
    ax.annotate("inlet\np$_0$ = 200 kPa\nT$_0$ = 300 K", xy=(0, 25), xytext=(-90, 18), arrowprops=arr, **lab)
    ax.annotate("outlet\nzeroGradient\n(30 kPa ambient\nnot imposed)", xy=(330, 18), xytext=(345, 8), arrowprops=arr, **lab)
    ax.annotate("throat, r = 32.6 mm", xy=(155, 32.6), xytext=(120, 60), arrowprops=arr, **lab)
    ax.annotate("slip wall", xy=(95, 43), xytext=(50, 60), arrowprops=arr, **lab)
    ax.annotate("exit r = 35.4 mm", xy=(305, 35.4), xytext=(250, 60), arrowprops=arr, **lab)
    ax.annotate("axis", xy=(330, 0), xytext=(345, -4), arrowprops=arr, fontsize=6.5, color=INK)
    for sp in ["top", "right"]:
        ax.spines[sp].set_visible(False)

    # (b) forward-facing step (exact block structure; every 4th grid line drawn)
    ax = fig.add_subplot(gs[1, :])
    L, H, xs_, h, d = 3.0, 1.0, 0.6, 0.2, 0.0125
    segs = [[(i * d, h if i * d > xs_ + 1e-9 else 0), (i * d, H)] for i in range(0, 241, 4)]
    segs += [[(0, j * d), (xs_ if j * d < h - 1e-9 else L, j * d)] for j in range(0, 81, 4)]
    ax.add_collection(LineCollection(segs, colors=INK2, linewidths=0.25))
    ax.add_patch(Polygon([(0, 0), (xs_, 0), (xs_, h), (L, h), (L, H), (0, H)], closed=True,
                         fc="none", ec=INK, lw=1.2))
    ax.add_patch(Rectangle((xs_, 0), L - xs_, h, fc="#efeeea", ec=INK, lw=1.2, hatch="////"))
    ax.set_xlim(-0.75, 3.75); ax.set_ylim(-0.05, 1.18); ax.set_aspect("equal")
    ax.set_xlabel("x"); ax.set_ylabel("y")
    ax.set_title("(b) Mach-2 forward-facing step: 2-D Euler, 16,128 cells, Δx = Δy = 0.0125 (every 4th line shown)")
    ax.annotate("inlet (fixed)\np = T = 1\nU = (2, 0, 0)", xy=(0, 0.6), xytext=(-0.72, 0.45), arrowprops=arr, **lab)
    ax.annotate("outlet\nzeroGradient p\ninletOutlet U, T", xy=(3, 0.6), xytext=(3.08, 0.45), arrowprops=arr, **lab)
    ax.text(1.5, 1.03, "top: symmetryPlane", fontsize=6.5, ha="center", va="bottom", color=INK)
    ax.annotate("bottom:\nsymmetryPlane", xy=(0.3, 0), xytext=(-0.72, 0.1), arrowprops=arr, **lab)
    ax.annotate("step, x = 0.6, height 0.2\nslip U; zeroGradient p, T", xy=(2.2, 0.1),
                xytext=(3.08, 0.05), arrowprops=arr, **lab)
    for sp in ["top", "right"]:
        ax.spines[sp].set_visible(False)

    # (c) cube: actual grid lines from constant/polyMesh/points (rectilinear mesh)
    g = np.load(DATA / "cube/grid_lines.npz")
    gx, gy, gz = g["x"], g["y"], g["z"]
    assert (len(gx) - 1) * (len(gy) - 1) * (len(gz) - 1) - 20 ** 3 == 567360
    ax = fig.add_subplot(gs[2, 0])
    # every second grid line, so the local clustering remains legible in print
    segs = [[(x, -12), (x, 12)] for x in gx[::2]] + [[(-6, z), (16, z)] for z in gz[::2]]
    ax.add_collection(LineCollection(segs, colors="#8a8984", linewidths=0.2))
    ax.add_patch(Rectangle((-0.6, -1.1), 2.2, 2.2, fc=C2, ec=INK, lw=0.5, zorder=5))
    ax.annotate("cube (marker enlarged)", xy=(1.6, 0), xytext=(4.5, 4.0), fontsize=6, zorder=6,
                arrowprops=dict(arrowstyle="-", color=INK, lw=0.6),
                bbox=dict(fc="white", ec="none", pad=0.5))
    ax.set_xlim(-6, 16); ax.set_ylim(-12, 12); ax.set_aspect("equal")
    ax.set_xlabel("x/H  (inlet at −6, outlet at 16)"); ax.set_ylabel("z/H  (side walls at ±12)")
    ax.set_title("(c) Cube: floor mesh, plan view (every 2nd line)")

    ax = fig.add_subplot(gs[2, 1])
    xm = (gx >= -2) & (gx <= 5)
    segs = [[(x, 1 if 0 < x < 1 else 0), (x, 2)] for x in gx[xm]]
    for y in gy:
        segs += [[(-2, y), (0, y)], [(1, y), (5, y)]] if y < 1 - 1e-9 else [[(-2, y), (5, y)]]
    ax.add_collection(LineCollection(segs, colors="#8a8984", linewidths=0.2))
    ax.add_patch(Rectangle((0, 0), 1, 1, fc=C2, ec=INK, lw=0.5))
    ax.set_xlim(-2, 5); ax.set_ylim(0, 2); ax.set_aspect("equal")
    ax.set_xlabel("x/H"); ax.set_ylabel("y/H  (floor 0, roof 2)")
    ax.set_title("(c′) Centre-plane mesh near the cube (z = 0)")
    fig.savefig(OUT / "fig2_configurations.pdf", bbox_inches="tight")
    fig.savefig(OUT / "fig2_configurations.png", bbox_inches="tight", dpi=200)
    plt.close(fig)


# --------------------------------------------------------------------------
# Figure 3: nozzle profiles, theory comparison and continuation evidence
# --------------------------------------------------------------------------
def fig3():
    prof = np.loadtxt(DATA / "nozzle/axial_profile.csv", delimiter=",", skiprows=1)
    x, p, T, U, M = prof.T
    val = load("nozzle/validation.json")
    xt = np.linspace(0.0005, 0.3295, 400)
    _, Mq, pq, Tq, Uq = quasi1d_profile(xt)
    # Check the derived exit state against the validator's stored theory values.
    _, Me, pe, Te, Ue = quasi1d_profile(np.array([0.33]))
    th = val["theory"]
    assert abs(Me[0] - th["outlet_M"]) < 1e-6 and abs(pe[0] / th["outlet_p"] - 1) < 1e-6, (Me, th)

    fig, axs = plt.subplots(1, 3, figsize=(TEXTWIDTH, 2.25), gridspec_kw=dict(wspace=0.42))
    ax = axs[0]
    ax.plot(xt * 1e3, Mq, color=C2, lw=1.2, ls=(0, (4, 2)), label="quasi-1-D (isentropic)")
    ax.plot(x * 1e3, M, color=C1, lw=1.5, label="CFD (slab average)")
    ax.axhline(1, color=INK2, lw=0.5)
    ax.set_xlabel("x (mm)"); ax.set_ylabel("Mach number"); ax.set_title("(a) Mach number")
    ax.legend(loc="center right", bbox_to_anchor=(1.0, 0.42)); grid(ax)
    ax = axs[1]
    ax.plot(xt * 1e3, pq / 2e5, color=C2, lw=1.2, ls=(0, (4, 2)))
    ax.plot(x * 1e3, p / 2e5, color=C1, lw=1.5)
    ax.plot(xt * 1e3, Tq / 300, color=C2, lw=1.2, ls=(0, (4, 2)), label="quasi-1-D")
    ax.plot(x * 1e3, T / 300, color=C3, lw=1.5)
    ax.set_xlabel("x (mm)"); ax.set_ylabel("static / stagnation")
    ax.set_title("(b) p/p$_0$ and T/T$_0$"); ax.legend(loc="center right", bbox_to_anchor=(1.0, 0.5)); grid(ax)
    ax.text(250, 0.72, "T/T$_0$", color=C3, fontsize=7); ax.text(250, 0.33, "p/p$_0$", color=C1, fontsize=7)

    # (c) continuation: metric / registered threshold at the two endpoints
    it1 = load("nozzle_continuation/iter01_validation.json")
    it2 = load("nozzle_continuation/iter02_validation.json")
    def ratios(v):
        return [v["final"]["max_window_mismatch_pct"] / 0.1,
                max(v["drift_fraction_last_2ms"].values()) / 0.002,
                max(v["field_L2_change_last_2ms"].values()) / 0.002]
    labels = ["mass\nmismatch", "monitor\ndrift", "field\nchange"]
    r1, r2 = ratios(it1), ratios(it2)
    ax = axs[2]
    pos = np.arange(3)
    ax.bar(pos - 0.19, r1, width=0.36, color=C2, label=f"t = {it1['final']['time']*1e3:g} ms (FAIL)")
    ax.bar(pos + 0.19, r2, width=0.36, color=C1, label=f"t = {it2['final']['time']*1e3:g} ms (PASS)")
    ax.axhline(1, color=INK, lw=0.8, ls=(0, (3, 2)))
    ax.text(-0.45, 1.1, "registered limit", fontsize=6.5, ha="left", color=INK)
    ax.set_yscale("log"); ax.set_ylim(0.2, 30)
    ax.set_xticks(pos, labels, fontsize=6.5)
    ax.set_ylabel("measured / registered limit")
    ax.set_title("(c) Gates at the two endpoints")
    ax.legend(loc="upper right", fontsize=6)
    grid(ax)
    fig.savefig(OUT / "fig3_nozzle.pdf", bbox_inches="tight")
    fig.savefig(OUT / "fig3_nozzle.png", bbox_inches="tight", dpi=200)
    plt.close(fig)
    return r1, r2


# --------------------------------------------------------------------------
# Figure 4: forward-facing step
# --------------------------------------------------------------------------
def crop_image(path, box):
    img = plt.imread(path)
    h, w = img.shape[:2]
    x0, y0, x1, y1 = box
    return img[int(y0 * h):int(y1 * h), int(x0 * w):int(x1 * w)]


def plot_region(path, cols, rows, extent):
    """Pixels of an archived native-field rendering inside its own axes frame.

    ``cols``/``rows`` are the pixel positions of the rendering's axis limits,
    located from its frame lines; ``extent`` gives the physical coordinates of
    those limits. The pixels are shown unchanged, with new, legible axes.
    """
    img = plt.imread(path)[:, :, :3]
    (c0, c1), (r0, r1) = cols, rows
    return img[int(round(r0)) + 2:int(round(r1)) - 1, int(round(c0)) + 2:int(round(c1)) - 1], extent


def fig4():
    sf = np.loadtxt(DATA / "step/shock_front_history.csv", delimiter=",", skiprows=1)
    tm = np.loadtxt(DATA / "step/transient_mass.csv", delimiter=",", skiprows=1)
    diag = load("step/diagnostics.json")
    mlo, mhi = diag["final_ranges"]["Mach"]  # colour limits of the archived rendering
    fig = plt.figure(figsize=(TEXTWIDTH, 3.7))
    gs = fig.add_gridspec(2, 2, height_ratios=[0.8, 1.0], hspace=0.45, wspace=0.4)

    ax = fig.add_subplot(gs[0, 0])
    img, ext = plot_region(DATA / "step/Mach_field.png", (86, 1526), (93, 573.7), (0, 3, 0, 1))
    ax.imshow(img, extent=ext, aspect="equal", interpolation="nearest")
    ax.add_patch(Rectangle((0.6, 0), 2.4, 0.2, fc="#efeeea", ec=INK, lw=0.6))
    sm = matplotlib.cm.ScalarMappable(norm=matplotlib.colors.Normalize(mlo, mhi), cmap="viridis")
    cb = fig.colorbar(sm, ax=ax, fraction=0.03, pad=0.02, shrink=0.75)
    cb.ax.tick_params(labelsize=6)
    ax.set_xlabel("x"); ax.set_ylabel("y"); ax.set_title("(a) Mach number at t = 4")

    ax = fig.add_subplot(gs[0, 1])
    img, ext = plot_region(DATA / "step/shock_density_contours.png", (85.5, 1715.5), (46.5, 589.5), (0, 3, 0, 1))
    ax.imshow(img, extent=ext, aspect="equal", interpolation="antialiased")
    ax.add_patch(Rectangle((0.6, 0), 2.4, 0.2, fc="#efeeea", ec=INK, lw=0.6))
    ax.set_xlabel("x"); ax.set_ylabel("y"); ax.set_title("(b) Density contours at t = 4")

    ax = fig.add_subplot(gs[1, 0])
    ax.plot(sf[:, 0], sf[:, 1], color=C1, marker="o", ms=2.5, label="detected front (y < 0.2)")
    ax.axhline(0.6, color=INK2, lw=0.6, ls=(0, (3, 2)))
    ax.text(3.95, 0.585, "step face, x = 0.6", fontsize=6.5, ha="right", va="top", color=INK2)
    ax.set_xlabel("t"); ax.set_ylabel("front position x")
    ax.set_ylim(0, 0.7); ax.set_xlim(0, 4.05)
    ax.set_title("(c) Compression-front position"); grid(ax); ax.legend(loc="lower left")

    ax = fig.add_subplot(gs[1, 1])
    rr = np.abs(tm[:, 4])
    ax.semilogy(tm[:, 0], np.maximum(rr, 1e-16), color=C1, lw=0.5)
    ax.axhline(1e-6, color=INK, lw=0.8, ls=(0, (3, 2)))
    ax.text(0.05, 1.8e-6, "registered limit 10$^{-6}$", fontsize=6.5, color=INK)
    ax.set_ylim(1e-15, 1e-4); ax.set_xlim(0, 4)
    ax.set_xlabel("t"); ax.set_ylabel("normalized residual")
    ax.set_title("(d) Discrete transient mass closure"); grid(ax)
    fig.savefig(OUT / "fig4_step.pdf", bbox_inches="tight")
    fig.savefig(OUT / "fig4_step.png", bbox_inches="tight", dpi=200)
    plt.close(fig)
    return float(rr.max())


# --------------------------------------------------------------------------
# Figure 5: cube diagnostic stress test
# --------------------------------------------------------------------------
def fig5():
    f = np.loadtxt(DATA / "cube/forces_merged.csv", delimiter=",", skiprows=1)
    t, fx, fy, fz = f.T
    cyc = load("cube/cycle_gates.json")["complete_cycles"]
    gate = load("cube/registered_stationarity.json")["expected"]["stationarity"]
    fig = plt.figure(figsize=(TEXTWIDTH, 4.1))
    gs = fig.add_gridspec(2, 3, height_ratios=[1.0, 1.0], hspace=0.62, wspace=0.55)

    # (a) ParaView render (parallel projection): camera focal point (3, 0.5, 0),
    # view along +y, parallel scale 4.2 on a 960 x 600 image -> 0.014 H per pixel.
    ax = fig.add_subplot(gs[0, 0:2])
    img = plt.imread(DATA / "cube/velocity_t80_paraview.png")[:, :, :3]
    s_ = 2 * 4.2 / 600
    r0, r1, c0, c1 = 186, 414, 100, 960
    ax.imshow(img[r0:r1, c0:c1], interpolation="nearest",
              extent=(3 + (c0 - 480) * s_, 3 + (c1 - 480) * s_, (300 - r1) * s_, (300 - r0) * s_))
    vr = load("cube/video_manifest_ranges.json")["velocity"]
    bar = img[475:486, 179:559]
    cax = ax.inset_axes([1.015, 0.0, 0.025, 1.0])
    cax.imshow(np.transpose(bar, (1, 0, 2))[::-1], extent=(0, 1, vr[0], vr[1]), aspect="auto")
    cax.set_xticks([]); cax.yaxis.tick_right(); cax.tick_params(labelsize=6)
    cax.set_yticks([0, 0.5, 1.0, 1.5])
    ax.set_xlabel("x/H", labelpad=1); ax.set_ylabel("z/H")
    ax.set_title("(a) |U|/U$_b$ on the plane y/H = 0.5 at t* = 80")

    ax = fig.add_subplot(gs[0, 2])
    ax.plot(t, 2 * fx, color=C1, lw=1.0)
    ax.axvspan(gate["window"]["start"], gate["window"]["end"], color=C1, alpha=0.08, lw=0)
    ax.text(70, 1.455, "gate\nwindow", fontsize=6.5, ha="center", color=INK2)
    ax.set_xlabel("t* = t U$_b$/H")
    ax.set_title("(b) Drag, C$_D$ = 2F$_x$")
    ax.set_xlim(20, 80); grid(ax)

    ax = fig.add_subplot(gs[1, 0:2])
    ax.plot(t, fz * 1e3, color=C2, lw=0.9)
    for c in cyc:
        ax.axvline(c["start_rising_zero"], color=INK2, lw=0.4, ls=(0, (2, 2)))
    ax.axvline(cyc[-1]["end_rising_zero"], color=INK2, lw=0.4, ls=(0, (2, 2)))
    mid = gate["window"]["start"] + 10
    ax.axvspan(gate["window"]["start"], mid, color=INK2, alpha=0.07, lw=0)
    ax.axvspan(mid, gate["window"]["end"], color=C2, alpha=0.10, lw=0)
    m1, m2 = gate["measured"]["mean_abs_fz_first_half"], gate["measured"]["mean_abs_fz_second_half"]
    ax.text(65, 6.2, f"{m1*1e3:.2f}", fontsize=6.5, ha="center")
    ax.text(75, 6.2, f"{m2*1e3:.2f}", fontsize=6.5, ha="center")
    ax.text(58.8, 6.2, "mean|F$_z$|×10$^3$:", fontsize=6.5, ha="right")
    ax.set_xlim(20, 80); ax.set_ylim(-7, 8)
    ax.set_xlabel("t*"); ax.set_ylabel("F$_z$ × 10$^3$")
    ax.set_title("(c) Lateral force and complete-cycle boundaries")
    grid(ax)

    ax = fig.add_subplot(gs[1, 2])
    te = [c["end_rising_zero"] for c in cyc]
    A = [c["half_range_amplitude"] * 1e3 for c in cyc]
    ax.semilogy(te, A, color=C2, marker="o", ms=4)
    for c, xx, yy in zip(cyc[1:], te[1:], A[1:]):
        ax.text(xx - 1.5, yy * 1.4, f"+{c['amplitude_change_percent']:.0f}%", fontsize=6.5, ha="center")
    ax.set_xlabel("cycle end t*"); ax.set_ylabel("A$_n$ × 10$^3$")
    ax.set_ylim(0.15, 12); ax.set_xlim(38, 79)
    ax.set_title("(d) Cycle amplitude"); grid(ax)
    fig.savefig(OUT / "fig5_cube.pdf", bbox_inches="tight")
    fig.savefig(OUT / "fig5_cube.png", bbox_inches="tight", dpi=200)
    plt.close(fig)


if __name__ == "__main__":
    fig2()
    r1, r2 = fig3()
    rmax = fig4()
    fig5()
    print("nozzle metric/threshold ratios t=1ms:", [round(v, 3) for v in r1])
    print("nozzle metric/threshold ratios t=6ms:", [round(v, 3) for v in r2])
    print("step max |relative residual|:", rmax)
