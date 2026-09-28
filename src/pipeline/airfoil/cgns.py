#!/usr/bin/env python3
"""Reader for the NASA TMR unstructured hexahedral CGNS mesh.

This is the INDEPENDENT TOPOLOGY AUTHORITY for Family 3 mesh qualification: the
same 449x129 NACA0012 grid published by NASA as unstructured hexes, used to check
our own Plot3D conversion rather than to replace it.

DEPENDENCY POLICY
  Modern CGNS files are HDF5 containers, so this module reads them with ``h5py``
  and nothing else. If ``h5py`` is absent, or the file turns out to be a legacy
  ADF container, the reader RAISES with the exact package needed. It never falls
  back to a hand-rolled partial parser: a mis-read authority is worse than no
  authority.

WHAT IS RETURNED
  An ``UnstructuredHexMesh`` in OpenFOAM axes -- the NASA -> OpenFOAM transform
  documented in p3d.AXIS_MAP is applied once, here, and recorded. Everything
  downstream compares geometry, never file ordering or node IDs.
"""
from __future__ import annotations

import gzip
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

READER_VERSION = "airfoil-cgns-reader/1.1.2"

#: The one dependency. Reported verbatim when missing.
REQUIRED_PACKAGE = "h5py"
REQUIRED_PACKAGE_SPEC = "h5py>=3.0"
INSTALL_HINT = "pip install 'h5py>=3.0'"

#: CGNS element type for a linear 8-node hexahedron (ElementType_t enum).
HEXA_8 = 17
#: Linear 4-node quadrilateral, used for boundary element sections.
QUAD_4 = 7

#: HDF5 magic. A CGNS file that is not HDF5 is a legacy ADF container.
_HDF5_MAGIC = b"\x89HDF\r\n\x1a\n"


class CgnsError(RuntimeError):
    """The CGNS authority could not be read. Never a silent partial parse."""


class CgnsDependencyMissing(CgnsError):
    """The required CGNS/HDF5 package is not installed."""


def require_h5py():
    try:
        import h5py  # noqa: F401
    except ImportError as exc:
        raise CgnsDependencyMissing(
            "reading the NASA unstructured hexahedral CGNS authority requires "
            f"{REQUIRED_PACKAGE_SPEC}, which is not installed.\n"
            f"    install with:  {INSTALL_HINT}\n"
            "No partial CGNS parser is substituted: an unreliable read of the "
            "topology authority would be worse than having none."
        ) from exc
    import h5py

    return h5py


@dataclass
class UnstructuredHexMesh:
    """Coordinates and hex connectivity, already in OpenFOAM axes."""

    points: List[Tuple[float, float, float]]
    hexes: List[Tuple[int, ...]]
    #: Boundary name -> list of quad faces (point indices).
    boundary: Dict[str, List[Tuple[int, ...]]] = field(default_factory=dict)
    provenance: Dict[str, Any] = field(default_factory=dict)

    @property
    def n_points(self) -> int:
        return len(self.points)

    @property
    def n_cells(self) -> int:
        return len(self.hexes)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "points": self.n_points,
            "cells": self.n_cells,
            "boundary": {k: len(v) for k, v in self.boundary.items()},
            "provenance": dict(self.provenance),
        }


def _is_hdf5(path: Path) -> bool:
    with open(path, "rb") as fh:
        return fh.read(8) == _HDF5_MAGIC


def _decompress(path: Path, workdir: Path) -> Path:
    path = Path(path)
    if path.suffix != ".gz":
        return path
    target = Path(workdir) / path.stem
    with gzip.open(path, "rb") as src, open(target, "wb") as dst:
        shutil.copyfileobj(src, dst)
    return target




def _convert_adf_to_hdf5(source: Path, target: Path) -> Dict[str, Any]:
    """Convert a legacy ADF CGNS container to a temporary HDF5 read-copy.

    The registered NASA asset itself is never modified.  This is a container-
    format conversion only: CGNS coordinates/connectivity remain the authority.
    The conversion is performed with the official ``cgnsconvert -h`` tool.

    On Windows we invoke the tool inside the project's WSL distro because that
    is also where OpenFOAM runs.  Set ``CFD_WSL_DISTRO`` to override the default.
    """
    source = Path(source).resolve()
    target = Path(target).resolve()

    native = shutil.which("cgnsconvert")
    if native:
        proc = subprocess.run(
            [native, "-h", str(source), str(target)],
            capture_output=True, text=True, timeout=120, check=False,
        )
        tool = native
        bridge = "native"
    else:
        wsl = shutil.which("wsl.exe") or shutil.which("wsl")
        if not wsl:
            raise CgnsError(
                "legacy ADF CGNS input requires the official cgnsconvert tool. "
                "Neither cgnsconvert nor WSL is available. Install CGNS conversion "
                "tools (Ubuntu package: cgns-convert), then retry."
            )
        distro = os.environ.get("CFD_WSL_DISTRO", "Ubuntu-24.04")

        def wslpath(p: Path) -> str:
            # Avoid passing a Windows path through the WSL `wslpath` command.
            # On some Windows/WSL argument paths, backslashes are stripped before
            # `wslpath` sees them (e.g. C:\\Users -> C:Users), which makes the
            # conversion fail.  For ordinary drive-letter paths the WSL mapping
            # is deterministic: C:\\foo\\bar -> /mnt/c/foo/bar.
            raw = str(Path(p).resolve())
            m = re.match(r"^([A-Za-z]):[\\/](.*)$", raw)
            if m:
                drive = m.group(1).lower()
                rest = m.group(2).replace("\\", "/")
                return f"/mnt/{drive}/{rest}"

            # Fallback for unusual paths (e.g. UNC).  Put the value in an
            # environment variable so the shell never reinterprets backslashes.
            env = os.environ.copy()
            env["CGNS_WIN_PATH"] = raw
            r = subprocess.run(
                [
                    wsl, "-d", distro, "bash", "-lc",
                    'wslpath -a "$(printf %s "$CGNS_WIN_PATH")"',
                ],
                capture_output=True, text=True, timeout=30, check=False, env=env,
            )
            if r.returncode != 0 or not r.stdout.strip():
                raise CgnsError(
                    f"could not translate Windows path through WSL ({distro}): "
                    f"{r.stderr.strip() or r.stdout.strip()}"
                )
            return r.stdout.strip()

        probe = subprocess.run(
            [wsl, "-d", distro, "bash", "-lc", "command -v cgnsconvert"],
            capture_output=True, text=True, timeout=30, check=False,
        )
        if probe.returncode != 0 or not probe.stdout.strip():
            raise CgnsError(
                f"legacy ADF CGNS input detected, but cgnsconvert is not installed "
                f"in WSL distro {distro!r}. Install it with:\n"
                f"    wsl -d {distro} sudo apt-get update\n"
                f"    wsl -d {distro} sudo apt-get install -y cgns-convert\n"
                "Then rerun the same qualification command. The registered NASA "
                "asset will remain untouched."
            )

        src_wsl = wslpath(source)
        dst_wsl = wslpath(target)
        proc = subprocess.run(
            [wsl, "-d", distro, "cgnsconvert", "-h", src_wsl, dst_wsl],
            capture_output=True, text=True, timeout=120, check=False,
        )
        tool = probe.stdout.strip()
        bridge = f"WSL:{distro}"

    if proc.returncode != 0:
        raise CgnsError(
            "cgnsconvert failed while converting the registered NASA ADF CGNS "
            f"asset to a temporary HDF5 read-copy (rc={proc.returncode}).\n"
            f"stdout: {proc.stdout.strip()}\n"
            f"stderr: {proc.stderr.strip()}"
        )
    if not target.exists() or not _is_hdf5(target):
        raise CgnsError(
            "cgnsconvert returned success but did not produce a valid HDF5 CGNS "
            "read-copy. The registered source asset was not modified."
        )

    return {
        "source_container": "CGNS/ADF",
        "read_container": "CGNS/HDF5",
        "conversion": "cgnsconvert -h",
        "tool": tool,
        "bridge": bridge,
        "registered_source_modified": False,
    }


def _node_label(node) -> str:
    raw = node.attrs.get("label")
    if raw is None:
        return ""
    if isinstance(raw, bytes):
        return raw.decode("ascii", "replace").strip("\x00")
    return str(raw).strip("\x00")


def _data(node):
    """The ' data' child CGNS/HDF5 stores a node's array in."""
    return node[" data"][()] if " data" in node else None


def _children(node, label: str) -> List[Tuple[str, Any]]:
    out = []
    for name in node:
        if name.startswith(" "):
            continue
        child = node[name]
        if hasattr(child, "attrs") and _node_label(child) == label:
            out.append((name, child))
    return out


def read_cgns_hex(
    path: Path,
    *,
    expected_cells: Optional[int] = None,
    apply_axis_transform: bool = True,
) -> UnstructuredHexMesh:
    """Read a single-base, single-zone unstructured CGNS hex mesh. Fails closed."""
    h5py = require_h5py()
    path = Path(path)

    with tempfile.TemporaryDirectory() as tmp:
        plain = _decompress(path, Path(tmp))
        container_conversion = None
        if not _is_hdf5(plain):
            # NASA's published Family-II .hex.cgns assets are legacy ADF.
            # Preserve the registered bytes and convert only a temporary read-copy.
            hdf5_copy = Path(tmp) / f"{plain.name}.hdf5.cgns"
            container_conversion = _convert_adf_to_hdf5(plain, hdf5_copy)
            plain = hdf5_copy

        with h5py.File(plain, "r") as fh:
            bases = _children(fh, "CGNSBase_t")
            if len(bases) != 1:
                raise CgnsError(
                    f"{path.name}: found {len(bases)} CGNSBase_t node(s); this "
                    "reader accepts exactly one. Refusing to choose."
                )
            base_name, base = bases[0]
            zones = _children(base, "Zone_t")
            if len(zones) != 1:
                raise CgnsError(
                    f"{path.name}: found {len(zones)} Zone_t node(s); this reader "
                    "accepts exactly one unstructured zone. Refusing to choose."
                )
            zone_name, zone = zones[0]

            zone_type = _children(zone, "ZoneType_t")
            kind = ""
            if zone_type:
                raw = _data(zone_type[0][1])
                if raw is not None:
                    kind = bytes(bytearray(raw)).decode("ascii", "replace").strip("\x00")
            if kind and kind != "Unstructured":
                raise CgnsError(
                    f"{path.name}: ZoneType is {kind!r}; the registered authority is "
                    "the UNSTRUCTURED hexahedral representation."
                )

            size = _data(zone)
            if size is None:
                raise CgnsError(f"{path.name}: Zone_t has no size data")

            # CGNS defines unstructured Zone_t size as three scalar values:
            #   [VertexSize, CellSize, VertexSizeBoundary]
            # with IndexDimension = 1.  After ADF -> HDF5 conversion, different
            # CGNS tool versions may expose the 2-D node data as shape (1, 3)
            # or (3, 1).  The previous reader assumed only (1, 3), causing an
            # IndexError on NASA Family-II files converted by cgnsconvert.
            # Flattening is representation-agnostic here because an unstructured
            # zone is required and therefore these are exactly the three values
            # in CGNS order.
            size_flat = size.reshape(-1)
            if len(size_flat) != 3:
                raise CgnsError(
                    f"{path.name}: unstructured Zone_t size has shape "
                    f"{getattr(size, 'shape', None)!r} ({len(size_flat)} values); "
                    "expected exactly [VertexSize, CellSize, VertexSizeBoundary]."
                )
            n_points_declared = int(size_flat[0])
            n_cells_declared = int(size_flat[1])

            grids = _children(zone, "GridCoordinates_t")
            if not grids:
                raise CgnsError(f"{path.name}: no GridCoordinates_t node")
            grid = grids[0][1]
            coords: Dict[str, Any] = {}
            for name, node in _children(grid, "DataArray_t"):
                arr = _data(node)
                if arr is not None:
                    coords[name] = arr.reshape(-1)
            missing = [c for c in ("CoordinateX", "CoordinateY", "CoordinateZ")
                       if c not in coords]
            if missing:
                raise CgnsError(f"{path.name}: grid coordinates missing {missing}")

            nasa_x = coords["CoordinateX"]
            nasa_y = coords["CoordinateY"]
            nasa_z = coords["CoordinateZ"]
            if apply_axis_transform:
                # NASA (x, y, z) -> OpenFOAM (x, z, y): spanwise NASA y becomes
                # the OpenFOAM empty direction. Same transform as p3d.AXIS_MAP.
                points = [
                    (float(a), float(c), float(b))
                    for a, b, c in zip(nasa_x, nasa_y, nasa_z)
                ]
            else:
                points = [
                    (float(a), float(b), float(c))
                    for a, b, c in zip(nasa_x, nasa_y, nasa_z)
                ]

            hexes: List[Tuple[int, ...]] = []
            boundary: Dict[str, List[Tuple[int, ...]]] = {}
            sections: List[Dict[str, Any]] = []
            for name, node in _children(zone, "Elements_t"):
                meta = _data(node)
                if meta is None:
                    continue
                meta_flat = meta.reshape(-1)
                if len(meta_flat) < 1:
                    continue
                # As with Zone_t, cgnsconvert may transpose the HDF5 storage
                # dimensions.  Elements_t's first scalar is ElementType_t; use
                # a flat view rather than assuming a particular array shape.
                element_type = int(meta_flat[0])
                conn_nodes = _children(node, "DataArray_t")
                conn = None
                for cname, cnode in conn_nodes:
                    if cname == "ElementConnectivity":
                        conn = _data(cnode)
                if conn is None:
                    continue
                conn = conn.reshape(-1)
                if element_type == HEXA_8:
                    block = [tuple(int(v) - 1 for v in conn[i:i + 8])
                             for i in range(0, len(conn), 8)]
                    hexes.extend(block)
                    sections.append({"name": name, "type": "HEXA_8",
                                     "count": len(block)})
                elif element_type == QUAD_4:
                    block = [tuple(int(v) - 1 for v in conn[i:i + 4])
                             for i in range(0, len(conn), 4)]
                    boundary[name] = block
                    sections.append({"name": name, "type": "QUAD_4",
                                     "count": len(block)})
                else:
                    sections.append({"name": name, "type": f"enum_{element_type}",
                                     "count": None, "ignored": True})

    if not hexes:
        raise CgnsError(
            f"{path.name}: no HEXA_8 element section found. The registered "
            "authority is the unstructured HEXAHEDRAL representation."
        )
    if len(points) != n_points_declared:
        raise CgnsError(
            f"{path.name}: Zone_t declares {n_points_declared} vertices but "
            f"{len(points)} coordinate tuples were read. Refusing the source."
        )
    if len(hexes) != n_cells_declared:
        raise CgnsError(
            f"{path.name}: Zone_t declares {n_cells_declared} cells but "
            f"{len(hexes)} HEXA_8 cells were read. Refusing the source."
        )
    if expected_cells is not None and len(hexes) != expected_cells:
        raise CgnsError(
            f"{path.name}: {len(hexes)} hexahedra, expected {expected_cells}. "
            "Refusing: this is not the registered representation of that grid."
        )

    return UnstructuredHexMesh(
        points=points,
        hexes=hexes,
        boundary=boundary,
        provenance={
            "reader_version": READER_VERSION,
            "container": "CGNS/HDF5",
            "source_container": (
                container_conversion["source_container"]
                if container_conversion else "CGNS/HDF5"
            ),
            "container_conversion": container_conversion,
            "dependency": REQUIRED_PACKAGE_SPEC,
            "base": base_name,
            "zone": zone_name,
            "zone_type": kind or "unspecified",
            "declared_points": n_points_declared,
            "declared_cells": n_cells_declared,
            "read_points": len(points),
            "read_cells": len(hexes),
            "element_sections": sections,
            "boundary_sections": {k: len(v) for k, v in boundary.items()},
            "axis_transform_applied": apply_axis_transform,
            "axis_transform": "NASA (x,y,z) -> OpenFOAM (x,z,y)",
        },
    )


def dependency_status() -> Dict[str, Any]:
    """Whether the CGNS authority is readable here. Reported, never assumed."""
    try:
        h5py = require_h5py()
    except CgnsDependencyMissing as exc:
        return {
            "available": False,
            "package": REQUIRED_PACKAGE_SPEC,
            "install": INSTALL_HINT,
            "reason": str(exc).splitlines()[0],
        }
    return {
        "available": True,
        "package": REQUIRED_PACKAGE_SPEC,
        "version": getattr(h5py, "__version__", "unknown"),
        "install": INSTALL_HINT,
    }
