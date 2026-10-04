#!/usr/bin/env python3
"""Native-field figures for the 2D forward-step family.

PROVENANCE
----------
Adapted from ``src/pipeline/forward_step/plots.py``. The 3D-only figures
(spanwise slices, x-z / y-z sections, the 3D mesh view) are removed. The mesh
figure now draws the real polyMesh boundary edges in the plane.

Every pixel comes from native OpenFOAM cell values or native polyMesh
points/faces. No analytical or reference field is drawn, and no ParaView or
PyVista dependency is introduced; this mirrors how the nozzle family produces
its visual evidence.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Dict

import numpy as np
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.collections import LineCollection  # noqa: E402
from matplotlib.patches import Rectangle  # noqa: E402

FIELDS = [
    ("Mach", "Mach number"),
    ("p", "pressure"),
    ("rho", "density"),
    ("T", "temperature"),
    ("speed", "velocity magnitude"),
]


def cell_edges(spec):
    """Block-wise cell edges, matching how blockMesh divides each block."""
    a, b = spec.splits
    x = np.r_[
        np.linspace(0, spec.step_x, a + 1),
        np.linspace(spec.step_x, spec.length, spec.nx - a + 1)[1:],
    ]
    y = np.r_[
        np.linspace(0, spec.step_height, b + 1),
        np.linspace(spec.step_height, spec.height, spec.ny - b + 1)[1:],
    ]
    return x, y


def native_boundary_edges(case) -> np.ndarray:
    """Exterior mesh edges straight from polyMesh points/faces/boundary."""
    mesh = Path(case) / "constant/polyMesh"
    text = (mesh / "points").read_text()
    m = re.search(r"\n\s*(\d+)\s*\n\(\s*(.*?)\n\)", text, re.S)
    if not m:
        raise ValueError("Unsupported points file")
    points = np.fromstring(
        m[2].replace("(", " ").replace(")", " "), sep=" "
    ).reshape(-1, 3)
    if len(points) != int(m[1]):
        raise ValueError("Point count mismatch")

    faces = [
        np.fromstring(v, sep=" ", dtype=int)
        for v in re.findall(r"^\d+\(([^\n]*)\)", (mesh / "faces").read_text(), re.M)
    ]

    boundary = (mesh / "boundary").read_text()
    pairs = set()
    for body in re.findall(r"\{([^{}]+)\}", boundary, re.S):
        start = re.search(r"startFace\s+(\d+);", body)
        count = re.search(r"nFaces\s+(\d+);", body)
        if not start or not count:
            continue
        for face in faces[int(start[1]) : int(start[1]) + int(count[1])]:
            for i, j in zip(face, np.roll(face, -1)):
                pairs.add(tuple(sorted((int(i), int(j)))))

    segments = points[np.array(sorted(pairs))]
    # Collapse to the plane; the span carries a single cell.
    return segments[:, :, :2]


def _decorate(ax, spec):
    ax.add_patch(
        Rectangle(
            (spec.step_x, 0),
            spec.length - spec.step_x,
            spec.step_height,
            facecolor="white",
            edgecolor="none",
            zorder=3,
        )
    )
    ax.plot(
        [0, spec.step_x, spec.step_x, spec.length],
        [0, 0, spec.step_height, spec.step_height],
        "k",
        lw=1.2,
        zorder=4,
    )
    ax.set(
        xlim=(0, spec.length),
        ylim=(0, spec.height),
        xlabel="x (normalized)",
        ylabel="y (normalized)",
    )
    ax.set_aspect("equal")


def make_plots(case, out, spec, layout, data: Dict[str, np.ndarray]) -> Dict[str, str]:
    """Write field and mesh figures. Returns {label: path}."""
    out = Path(out)
    figures = out / "figures"
    figures.mkdir(parents=True, exist_ok=True)

    xe, ye = cell_edges(spec)
    plt.rcParams.update({"font.size": 11, "figure.dpi": 145})

    time_label = f"t = {spec.end_time:g}"
    produced: Dict[str, str] = {}

    for key, title in FIELDS:
        fig, ax = plt.subplots(figsize=(12, 4.6), layout="constrained")
        plane = layout.plane(data[key])
        mesh = ax.pcolormesh(xe, ye, plane, shading="flat", cmap="viridis")
        _decorate(ax, spec)
        ax.set_title(f"{Path(case).name}: {title}, {time_label}")
        fig.colorbar(mesh, ax=ax, label=key)
        path = figures / f"{key}_field.png"
        fig.savefig(path)
        plt.close(fig)
        produced[f"{key}_field"] = str(path)

    # Density contours: the clearest view of the shock system.
    fig, ax = plt.subplots(figsize=(12, 4.6), layout="constrained")
    rho = layout.plane(data["rho"])
    finite = rho[np.isfinite(rho)]
    if finite.size:
        levels = np.linspace(
            float(np.percentile(finite, 2)), float(np.percentile(finite, 98)), 30
        )
        ax.contour(layout.x, layout.y, rho, levels=levels, colors="#28495b", linewidths=0.6)
    _decorate(ax, spec)
    ax.set_title(f"{Path(case).name}: native density contours, {time_label}")
    path = figures / "shock_density_contours.png"
    fig.savefig(path)
    plt.close(fig)
    produced["shock_density_contours"] = str(path)

    # Mesh, drawn from the actual polyMesh.
    try:
        segments = native_boundary_edges(case)
        fig, ax = plt.subplots(figsize=(12, 4.6), layout="constrained")
        ax.add_collection(
            LineCollection(segments, colors="#426a82", linewidths=0.35, alpha=0.9)
        )
        _decorate(ax, spec)
        ax.set_title(
            f"{Path(case).name}: native polyMesh boundary edges, "
            f"{spec.cells} cells"
        )
        path = figures / "mesh_cells.png"
        fig.savefig(path)
        plt.close(fig)
        produced["mesh_cells"] = str(path)
    except (ValueError, FileNotFoundError, OSError) as exc:
        produced["mesh_cells_error"] = f"{type(exc).__name__}: {exc}"

    # Transient evidence: conservation and shock-front travel.
    balance_path = out / "transient_mass.csv"
    if balance_path.exists():
        balance = np.loadtxt(balance_path, delimiter=",", skiprows=1, ndmin=2)
        if balance.size:
            fig, axes = plt.subplots(2, 1, figsize=(10, 7), layout="constrained")
            axes[0].plot(balance[:, 0], balance[:, 4])
            axes[0].set(xlabel="time", ylabel="relative discrete mass residual")
            axes[1].plot(balance[:, 0], balance[:, 5])
            axes[1].set(xlabel="time", ylabel="cumulative mass defect")
            # Mark restart seams. A reader comparing these figures against the
            # residual statistics needs to see where one solver execution
            # ended and the next began, because no residual is defined there.
            if balance.shape[1] > 6:
                for seam in balance[balance[:, 6] == 1, 0]:
                    for ax in axes:
                        ax.axvline(
                            seam, color="0.4", linestyle="--", linewidth=1
                        )
                if (balance[:, 6] == 1).any():
                    axes[0].legend(
                        [axes[0].lines[0], axes[0].lines[-1]],
                        ["within-segment residual", "restart boundary"],
                        loc="upper left",
                        fontsize=9,
                    )
            path = figures / "transient_conservation.png"
            fig.savefig(path)
            plt.close(fig)
            produced["transient_conservation"] = str(path)

    front_path = out / "shock_front_history.csv"
    if front_path.exists():
        front = np.loadtxt(front_path, delimiter=",", skiprows=1, ndmin=2)
        if front.size and np.isfinite(front[:, 1:]).any():
            fig, ax = plt.subplots(figsize=(10, 4.2), layout="constrained")
            ax.plot(front[:, 0], front[:, 1], label="lower front x")
            # Only (time, position) pairs are plotted. A single-argument plot
            # would draw a series against its own index, stretching the time
            # axis to the sample count (0-40) instead of the solved interval
            # (0-4) and making the front history appear truncated.
            if front.shape[1] > 2:
                ax.plot(front[:, 0], front[:, 2], label="upper stem x")
            ax.set(xlabel="time", ylabel="x position (normalized)")
            ax.legend()
            ax.set_title("Measured compression-front position over time")
            path = figures / "shock_front_history.png"
            fig.savefig(path)
            plt.close(fig)
            produced["shock_front_history"] = str(path)

    return produced
