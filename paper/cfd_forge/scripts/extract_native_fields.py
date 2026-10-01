#!/usr/bin/env python3
"""Extract real mesh geometry and field values from native OpenFOAM cases.

Read-only. Needs only Python 3 + NumPy, so it runs inside WSL next to the
native cases. It writes compact .npz files that scripts/make_mesh_field_figures.py
turns into the paper figures. Nothing is interpolated or smoothed: 2-D cases
store the actual cell polygons of the front patch with the cell values; the
cube stores the actual grid coordinates, boundary-face polygons, and the cell
values of the cells whose extent contains the requested plane.

Usage (WSL):
  python3 extract_native_fields.py --out "/mnt/c/Backup from one drive/Desktop/Research/physics-constrained-cfd-agent/paper/cfd_forge/data/native" \
      --nozzle /home/aakash/.cache/nozzle-e2e/20260921T041731Z-case_A_reference/conical_nozzle_200kpa_30kpa \
      --step   /home/aakash/.cache/nozzle-e2e/20260922T193651Z-forward-step-2d/case \
      --cube   /home/aakash/family3_cube_sst_literature_audit_t4_retry2
Any subset of --nozzle/--step/--cube may be given.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import re
from pathlib import Path

import numpy as np


# ----------------------------------------------------------------------
# minimal OpenFOAM ASCII reader
# ----------------------------------------------------------------------
def _text(path: Path) -> str:
    if path.exists():
        return path.read_text(errors="replace")
    gz = path.with_name(path.name + ".gz")
    if gz.exists():
        return gzip.open(gz, "rt", errors="replace").read()
    raise FileNotFoundError(path)


def _strip(s: str) -> str:
    s = re.sub(r"/\*.*?\*/", "", s, flags=re.S)
    return re.sub(r"//[^\n]*", "", s)


def _list_block(s: str, start: int = 0):
    """Return (count, body) of the first top-level 'N\n(' list after start."""
    m = re.compile(r"\n\s*(\d+)\s*\n?\s*\(").search(s, start)
    if not m:
        raise ValueError("no list found")
    n = int(m[1])
    i = m.end()
    depth, j = 1, i
    while depth:
        c = s[j]
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
        j += 1
    return n, s[i:j - 1]


def read_points(case: Path) -> np.ndarray:
    n, body = _list_block(_strip(_text(case / "constant/polyMesh/points")))
    a = np.array(body.replace("(", " ").replace(")", " ").split(), float).reshape(-1, 3)
    assert len(a) == n
    return a


def read_faces(case: Path):
    n, body = _list_block(_strip(_text(case / "constant/polyMesh/faces")))
    faces = [list(map(int, f.split())) for f in re.findall(r"\d+\s*\(([^)]*)\)", body)]
    assert len(faces) == n
    return faces


def read_labels(case: Path, name: str) -> np.ndarray:
    n, body = _list_block(_strip(_text(case / f"constant/polyMesh/{name}")))
    a = np.array(body.split(), int)
    assert len(a) == n
    return a


def read_boundary(case: Path) -> dict:
    s = _strip(_text(case / "constant/polyMesh/boundary"))
    out = {}
    for name, body in re.findall(r"(\w+)\s*\{([^{}]*)\}", s):
        if name == "FoamFile":
            continue
        n = re.search(r"nFaces\s+(\d+)", body)
        st = re.search(r"startFace\s+(\d+)", body)
        ty = re.search(r"\btype\s+(\w+)", body)
        if n and st:
            out[name] = dict(n=int(n[1]), start=int(st[1]), type=ty[1] if ty else "")
    return out


def read_field(path: Path, ncells: int) -> np.ndarray:
    s = _strip(_text(path))
    m = re.search(r"internalField\s+uniform\s+([^;]+);", s)
    if m:
        v = np.array(m[1].replace("(", " ").replace(")", " ").split(), float)
        return np.tile(v, (ncells, 1)) if v.size > 1 else np.full(ncells, v[0])
    i = s.index("internalField")
    n, body = _list_block(s, i)
    v = np.array(body.replace("(", " ").replace(")", " ").split(), float)
    return v.reshape(n, -1) if v.size != n else v


def times(case: Path):
    out = []
    for d in case.iterdir():
        try:
            out.append((float(d.name), d))
        except ValueError:
            pass
    return sorted(out)


def sha(path: Path) -> str:
    p = path if path.exists() else path.with_name(path.name + ".gz")
    return hashlib.sha256(p.read_bytes()).hexdigest()


# ----------------------------------------------------------------------
# 2-D cases: one polygon per cell from the front (min-z) planar patch
# ----------------------------------------------------------------------
def planar_extract(case: Path, patch_types=("wedge", "empty"), fields=("p", "T", "U", "rho"),
                   max_times=None):
    pts, faces = read_points(case), read_faces(case)
    owner = read_labels(case, "owner")
    ncells = int(owner.max()) + 1
    nb = read_labels(case, "neighbour")
    ncells = max(ncells, int(nb.max()) + 1)
    bnd = read_boundary(case)
    wedges = [n for n, b in bnd.items() if b["type"] == "wedge"]
    empties = [n for n, b in bnd.items() if b["type"] == "empty" and b["n"] >= ncells]
    def faces_of(n):
        b = bnd[n]
        return list(range(b["start"], b["start"] + b["n"]))
    if wedges:
        # one wedge patch holds exactly one face per cell; take the -z one
        zmean = {n: np.mean([pts[faces[f]][:, 2].mean() for f in faces_of(n)]) for n in wedges}
        keep = faces_of(min(zmean, key=zmean.get))
        radial = True
    elif empties:
        cand = faces_of(empties[0])
        zc = np.array([pts[faces[f]][:, 2].mean() for f in cand])
        keep = [f for f, z in zip(cand, zc) if z < np.median(zc)]
        radial = False
    else:
        raise ValueError("no wedge or empty patch: not a 2-D case")
    if len(keep) != ncells:
        raise ValueError(f"front patch has {len(keep)} faces for {ncells} cells")
    cells = owner[keep]
    order = np.argsort(cells)
    cells = cells[order]
    keep = [keep[i] for i in order]
    nv = max(len(faces[f]) for f in keep)
    poly = np.full((len(keep), nv, 2), np.nan)
    for i, f in enumerate(keep):
        q = pts[faces[f]]
        xy = np.c_[q[:, 0], np.hypot(q[:, 1], q[:, 2])] if radial else q[:, :2]
        poly[i, :len(xy)] = xy
    out = {"cells": cells, "poly": poly, "ncells": ncells, "radial": radial}
    tl = [t for t in times(case) if t[0] >= 0]
    if max_times:
        idx = np.unique(np.linspace(0, len(tl) - 1, max_times).round().astype(int))
        tl = [tl[i] for i in idx]
    tv = []
    for t, d in tl:
        ok = all((d / f).exists() or (d / (f + ".gz")).exists() for f in fields if f != "rho")
        if not ok:
            continue
        tv.append(t)
        for f in fields:
            if (d / f).exists() or (d / (f + ".gz")).exists():
                v = read_field(d / f, ncells)
                out[f"{f}@{t:g}"] = v[cells] if v.ndim == 1 else v[cells]
    out["times"] = np.array(tv)
    hashes = {f"constant/polyMesh/{n}": sha(case / "constant/polyMesh" / n)
              for n in ("points", "faces", "owner", "neighbour", "boundary")}
    return out, hashes


# ----------------------------------------------------------------------
# cube: grid lines, boundary faces, plane cuts through actual cells
# ----------------------------------------------------------------------
def cube_extract(case: Path, cut_times=(20, 30, 40, 50, 60, 70, 80)):
    pts, faces = read_points(case), read_faces(case)
    owner, nb = read_labels(case, "owner"), read_labels(case, "neighbour")
    ncells = int(max(owner.max(), nb.max())) + 1
    bnd = read_boundary(case)
    # per-cell bounding box from its faces (rectilinear mesh)
    lo = np.full((ncells, 3), np.inf)
    hi = np.full((ncells, 3), -np.inf)
    if len({len(f) for f in faces}) == 1:
        fa = pts[np.array(faces)]
        fmin, fmax = fa.min(1), fa.max(1)
    else:
        fmin = np.array([pts[f].min(0) for f in faces])
        fmax = np.array([pts[f].max(0) for f in faces])
    for lab in (owner, ):
        np.minimum.at(lo, lab, fmin[:len(lab)])
        np.maximum.at(hi, lab, fmax[:len(lab)])
    np.minimum.at(lo, nb, fmin[:len(nb)])
    np.maximum.at(hi, nb, fmax[:len(nb)])
    out = {"lo": lo.astype(np.float32), "hi": hi.astype(np.float32)}
    for name in ("cube", "floor"):
        b = bnd[name]
        sel = range(b["start"], b["start"] + b["n"])
        quads = np.array([pts[faces[f]] for f in sel])
        if name == "floor":
            c = quads.mean(1)
            m = (c[:, 0] > -2) & (c[:, 0] < 5) & (np.abs(c[:, 2]) < 2.5)
            quads = quads[m]
        out[f"patch_{name}"] = quads.astype(np.float32)
    planes = {"y0p5": (1, 0.5), "z0": (2, 0.0)}
    for key, (ax, val) in planes.items():
        # the plane is a grid plane; take the single cell layer that starts on it
        m = np.isclose(lo[:, ax], val, atol=1e-4)
        out[f"cut_{key}_cells"] = np.nonzero(m)[0]
    tv = []
    for t, d in times(case):
        if not any(abs(t - c) < 1e-9 for c in cut_times):
            continue
        if not (d / "U").exists() and not (d / "U.gz").exists():
            continue
        U = read_field(d / "U", ncells)
        tv.append(t)
        for key in planes:
            out[f"U_{key}@{t:g}"] = U[out[f"cut_{key}_cells"]].astype(np.float32)
    out["times"] = np.array(tv)
    hashes = {f"constant/polyMesh/{n}": sha(case / "constant/polyMesh" / n)
              for n in ("points", "faces", "owner", "neighbour", "boundary")}
    return out, hashes


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--nozzle", type=Path)
    ap.add_argument("--step", type=Path)
    ap.add_argument("--cube", type=Path)
    ap.add_argument("--step-ref", type=Path, help="optional manual Mach-3 tutorial reproduction")
    ap.add_argument("--planar", action="append", default=[],
                    help="extra 2-D case as NAME=PATH (repeatable)")
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    manifest = {}
    jobs = [("nozzle", a.nozzle, lambda c: planar_extract(c, fields=("p", "T", "U"))),
            ("step", a.step, lambda c: planar_extract(c)),
            ("step_ref", a.step_ref, lambda c: planar_extract(c)),
            ("cube", a.cube, cube_extract)]
    for item in a.planar:
        n, p = item.split("=", 1)
        jobs.append((n, Path(p), lambda c: planar_extract(c)))
    for name, case, fn in jobs:
        if not case:
            continue
        print(f"extracting {name} from {case} ...", flush=True)
        data, hashes = fn(case)
        np.savez_compressed(a.out / f"{name}.npz", **data)
        manifest[name] = {"case": str(case), "times": [float(t) for t in data["times"]],
                          "mesh_sha256": hashes}
        print(f"  {name}: times {manifest[name]['times'][:3]} ... {manifest[name]['times'][-2:]}")
    old = a.out / "EXTRACT_MANIFEST.json"
    prev = json.loads(old.read_text()) if old.exists() else {}
    prev.update(manifest)
    old.write_text(json.dumps(prev, indent=2))
    print("done:", a.out)


if __name__ == "__main__":
    main()
