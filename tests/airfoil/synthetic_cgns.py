#!/usr/bin/env python3
"""Write a synthetic CGNS/HDF5 unstructured hex file, and corrupted variants.

TEST FIXTURE ONLY. These are not NASA files and contain no airfoil: they exist to
prove that the qualification comparison detects each specific defect.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

HEXA_8 = 17
QUAD_4 = 7


def _node(parent, name: str, label: str, data=None, dtype: str = "MT"):
    grp = parent.create_group(name)
    grp.attrs.create("label", np.bytes_(label.ljust(33, "\x00")[:33]))
    grp.attrs.create("name", np.bytes_(name.ljust(33, "\x00")[:33]))
    grp.attrs.create("type", np.bytes_(dtype.ljust(3, "\x00")[:3]))
    grp.attrs.create("flags", np.array([1], dtype="int32"))
    if data is not None:
        grp.create_dataset(" data", data=data)
    return grp


def write_cgns_hex(
    path: Path,
    points: Sequence[Tuple[float, float, float]],
    hexes: Sequence[Sequence[int]],
    *,
    nasa_axes: bool = True,
    boundary: Optional[Dict[str, Sequence[Sequence[int]]]] = None,
    gzipped: bool = True,
    zone_type: str = "Unstructured",
) -> Path:
    """Write points/hexes given in OPENFOAM axes, stored in NASA axes.

    The reader applies NASA (x,y,z) -> OpenFOAM (x,z,y); this inverts it so a
    round trip returns exactly what was handed in.
    """
    import gzip
    import io
    import shutil
    import tempfile

    import pytest

    h5py = pytest.importorskip("h5py")

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = path.with_suffix("") if path.suffix == ".gz" else path

    with h5py.File(raw, "w") as fh:
        fh.attrs.create("label", np.bytes_("Root Node of HDF5 File".ljust(33, "\x00")))
        fh.attrs.create("name", np.bytes_("HDF5 MotherNode".ljust(33, "\x00")))
        fh.attrs.create("type", np.bytes_("MT\x00"))
        _node(fh, "CGNSLibraryVersion", "CGNSLibraryVersion_t",
              np.array([4.0], dtype="float32"), "R4")
        base = _node(fh, "Base", "CGNSBase_t", np.array([[3, 3]], dtype="int32"), "I4")
        zone = _node(base, "Zone", "Zone_t",
                     np.array([[len(points), len(hexes), 0]], dtype="int32"), "I4")
        _node(zone, "ZoneType", "ZoneType_t",
              np.frombuffer(zone_type.encode("ascii"), dtype="S1"), "C1")
        grid = _node(zone, "GridCoordinates", "GridCoordinates_t")

        ofx = np.array([p[0] for p in points], dtype="float64")
        ofy = np.array([p[1] for p in points], dtype="float64")
        ofz = np.array([p[2] for p in points], dtype="float64")
        if nasa_axes:
            nx, ny, nz = ofx, ofz, ofy       # inverse of the reader's transform
        else:
            nx, ny, nz = ofx, ofy, ofz
        for name, arr in (("CoordinateX", nx), ("CoordinateY", ny),
                          ("CoordinateZ", nz)):
            _node(grid, name, "DataArray_t", arr, "R8")

        conn = np.array([v + 1 for h in hexes for v in h], dtype="int32")
        elements = _node(zone, "Hexes", "Elements_t",
                         np.array([HEXA_8, 0], dtype="int32"), "I4")
        _node(elements, "ElementConnectivity", "DataArray_t", conn, "I4")
        _node(elements, "ElementRange", "IndexRange_t",
              np.array([1, len(hexes)], dtype="int32"), "I4")

        for bname, faces in (boundary or {}).items():
            bconn = np.array([v + 1 for f in faces for v in f], dtype="int32")
            section = _node(zone, bname, "Elements_t",
                            np.array([QUAD_4, 0], dtype="int32"), "I4")
            _node(section, "ElementConnectivity", "DataArray_t", bconn, "I4")

    if gzipped:
        with open(raw, "rb") as src, gzip.open(path, "wb") as dst:
            shutil.copyfileobj(src, dst)
        raw.unlink()
    return path


def write_adf_lookalike(path: Path) -> Path:
    """A non-HDF5 'CGNS' file, to prove the reader refuses instead of guessing."""
    import gzip

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = b"ADF Database Version A02000" + b"\x00" * 64
    if path.suffix == ".gz":
        with gzip.open(path, "wb") as fh:
            fh.write(payload)
    else:
        path.write_bytes(payload)
    return path
