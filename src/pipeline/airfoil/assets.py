#!/usr/bin/env python3
"""Registered external assets for Family 3. Fails closed, always.

An asset is a file this family may not invent: a NASA structured grid, or a
published reference dataset. Two rules govern every one of them.

  1. NEVER SUBSTITUTE. If a registered asset is absent, the family refuses. It
     does not fall back to a similar grid, a regenerated geometry, or a
     digitised curve.
  2. NEVER INVENT A HASH. A SHA256 is a property of a specific file. This module
     cannot know the digest of a NASA download it has never seen, so the
     expected digests are NOT hard-coded here. They are recorded once, at
     install time, into a lockfile that is then committed:

         configs/families/airfoil/assets.lock.json

     From that moment the digest is authoritative and a mismatch fails closed.
     Before that moment the family is not executable, which is the correct
     state: an unregistered asset is an unregistered scientific input.

The lockfile is the registration mechanism. `scripts/airfoil_assets.py register`
writes it; `... verify` re-checks it; nothing else may edit it programmatically.
"""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

FAMILY = "airfoil"

#: Where registered asset files are expected to live. Overridable for tests and
#: for a shared read-only asset store.
ASSET_ROOT_ENV = "CFD_AGENT_ASSET_ROOT"
DEFAULT_ASSET_SUBDIR = Path("assets") / "families" / "airfoil"

LOCKFILE = Path("configs") / "families" / "airfoil" / "assets.lock.json"

_CHUNK = 1 << 20


class AssetError(RuntimeError):
    """A registered asset is missing, unregistered, or does not match."""


@dataclass(frozen=True)
class Asset:
    """One registered external file."""

    key: str
    filename: str
    #: What the file is and why this family needs it.
    role: str
    #: Where it came from. A provenance string, not a download instruction.
    source: str
    #: Free-form expectations recorded for the audit (dimensions, cell counts).
    expected: Dict[str, Any] = field(default_factory=dict)
    #: True when the family cannot run at all without it.
    required: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "key": self.key,
            "filename": self.filename,
            "role": self.role,
            "source": self.source,
            "expected": dict(self.expected),
            "required": self.required,
        }


# ----------------------------------------------------------------------
# The register. Filenames and expectations are as specified by the reviewer;
# digests are deliberately absent (see the module docstring).
# ----------------------------------------------------------------------
#: Current TMR location. The collection migrated off the old
#: turbmodels.larc.nasa.gov hostname, so the canonical provenance string is the
#: new one; the legacy host is recorded only as history.
TMR_HOST = "https://tmbwg.github.io/turbmodels"
TMR_PAGE = f"{TMR_HOST}/naca0012_val.html"
TMR_GRIDS = f"{TMR_HOST}/naca0012_grids.html"
TMR_LEGACY_HOST = "https://turbmodels.larc.nasa.gov"
TMR_HOST_NOTE = (
    f"canonical provenance host is {TMR_HOST}; {TMR_LEGACY_HOST} is the legacy "
    "location and is not used as the canonical string"
)

# -- ACTIVE F3 mesh path: NASA TMR Numerical Analysis FAMILY II --------
#: The canonical F3 mesh hierarchy. NASA's unstructured hexahedral CGNS
#: representation of the Family II structured C-grids is authoritative for the
#: in-plane coordinates and connectivity.
FAMILY2_COARSE = "familyII_coarse_hex_cgns"
FAMILY2_MEDIUM = "familyII_medium_hex_cgns"
FAMILY2_FINE = "familyII_fine_hex_cgns"
#: Optional cross-check only: the matching Family II PLOT3D files may be used to
#: verify coordinates and indexing independently. They are never solved on and
#: never substitute for the CGNS topology.
FAMILY2_COARSE_P2D = "familyII_coarse_p2dfmt"
FAMILY2_MEDIUM_P2D = "familyII_medium_p2dfmt"
FAMILY2_FINE_P2D = "familyII_fine_p2dfmt"

MESH_CANONICAL = "mesh_canonical"
MESH_SENSITIVITY = "mesh_sensitivity"
MESH_CGNS_HEX = "mesh_cgns_hex"
REF_LADSON_FORCES = "ref_ladson_forces"
REF_CFL3D_FORCES = "ref_cfl3d_forces"
REF_CFL3D_CP = "ref_cfl3d_cp"
REF_CFL3D_CF = "ref_cfl3d_cf"

#: Family II retrieval provenance. The grid page lists the files but carries no
#: per-file anchor: NASA distributes them inside one archive, so the archive is
#: the retrieval unit and is recorded as such. No direct per-file URL is invented.
FAMILY2_PAGE = f"{TMR_HOST}/naca0012numerics_grids.html"
FAMILY2_ARCHIVE = "NACA0012numerics_grids.zip"
FAMILY2_RETRIEVAL = (
    f"listed on {FAMILY2_PAGE}; NASA distributes the Family II grids inside "
    f"{FAMILY2_ARCHIVE}, from which the individual level is extracted. Digests are "
    "recorded in the lockfile at install time from the bytes actually retrieved."
)
FAMILY2_REGENERATION_NOTE = (
    "NASA states all grids were re-generated with the corrected airfoil shape as "
    "of 2014-06-23"
)


def _family2(key: str, filename: str, level: str, ni: int, nj: int,
             surface_points: int, *, cgns: bool = True) -> "Asset":
    """One Family II level. Cell counts are the identity (ni-1)(nj-1)."""
    cells = (ni - 1) * (nj - 1)
    return Asset(
        key=key,
        filename=filename,
        role=(
            f"ACTIVE canonical F3 mesh, {level} level: NASA TMR NACA0012 Numerical "
            f"Analysis Family II {ni}x{nj} C-grid, "
            + ("unstructured hexahedral CGNS -- authoritative for in-plane "
               "coordinates and connectivity"
               if cgns else
               "PLOT3D form, permitted ONLY as an independent cross-check of "
               "coordinates and indexing")
        ),
        source=FAMILY2_RETRIEVAL,
        expected={
            "family": "NASA TMR NACA0012 Numerical Analysis Family II",
            "level": level,
            "structured_dimensions_ni_nj": [ni, nj],
            "cgns_dimensions": [2, ni, nj] if cgns else None,
            "cells": cells,
            "cells_identity": f"({ni}-1)*({nj}-1) = {cells}",
            "airfoil_surface_points": surface_points,
            "spanwise_planes": 2 if cgns else 1,
            "spanwise_cells": 1 if cgns else None,
            "format": ("CGNS/HDF5, unstructured, single base / single zone, HEXA_8"
                       if cgns else "formatted PLOT3D, 2-D structured"),
            "reader_dependency": "h5py>=3.0" if cgns else None,
            "farfield_chords_approx": 500,
            "trailing_edge": "sharp; Family II TE spacing 1.25e-5 c",
            "regeneration_note": FAMILY2_REGENERATION_NOTE,
            "archive": FAMILY2_ARCHIVE,
            "chord_m": 1.0,
        },
        required=cgns,
    )


REGISTER: Dict[str, Asset] = {
    FAMILY2_COARSE: _family2(FAMILY2_COARSE, "n0012familyII.6.hex.cgns.gz",
                             "coarse", 225, 65, 129),
    FAMILY2_MEDIUM: _family2(FAMILY2_MEDIUM, "n0012familyII.5.hex.cgns.gz",
                             "medium", 449, 129, 257),
    FAMILY2_FINE: _family2(FAMILY2_FINE, "n0012familyII.4.hex.cgns.gz",
                           "fine", 897, 257, 513),
    FAMILY2_COARSE_P2D: _family2(FAMILY2_COARSE_P2D, "n0012familyII.6.p2dfmt.gz",
                                 "coarse", 225, 65, 129, cgns=False),
    FAMILY2_MEDIUM_P2D: _family2(FAMILY2_MEDIUM_P2D, "n0012familyII.5.p2dfmt.gz",
                                 "medium", 449, 129, 257, cgns=False),
    FAMILY2_FINE_P2D: _family2(FAMILY2_FINE_P2D, "n0012familyII.4.p2dfmt.gz",
                               "fine", 897, 257, 513, cgns=False),
    MESH_CANONICAL: Asset(
        key=MESH_CANONICAL,
        filename="n0012_897-257.p3dfmt.gz",
        role=(
            "canonical NASA structured C-grid for the 2DN00 NACA0012 validation "
            "case; the registered scientific mesh asset"
        ),
        source=f"NASA Turbulence Modeling Resource grid page: {TMR_GRIDS}",
        expected={
            "topology": "structured C-grid, single block, 3-D formatted Plot3D",
            "dimensions_ni_nj_nk": [2, 897, 257],
            "dimension_meaning": (
                "ni = 2 spanwise planes (two identical x-z planes separated by "
                "y = 1); nj = C-wrap; nk = radial"
            ),
            # (2-1)*(897-1)*(257-1) = 229376. Asserted, not assumed: see tests.
            "cells_2d": 229376,
            "cells_converted": 229376,
            "spanwise_layers": 1,
            "farfield_chords_approx": 500,
            "trailing_edge": "NASA modified sharp trailing edge",
            "chord_m": 1.0,
        },
        required=False,
    ),
    MESH_SENSITIVITY: Asset(
        key=MESH_SENSITIVITY,
        filename="n0012_449-129.p3dfmt.gz",
        role="coarser NASA grid of the same family, for the grid-sensitivity demonstration",
        source=f"NASA Turbulence Modeling Resource grid page: {TMR_GRIDS}",
        expected={
            "topology": "structured C-grid, single block, 3-D formatted Plot3D",
            "dimensions_ni_nj_nk": [2, 449, 129],
            "dimension_meaning": (
                "ni = 2 spanwise planes (two identical x-z planes separated by "
                "y = 1); nj = C-wrap; nk = radial"
            ),
            # (2-1)*(449-1)*(129-1) = 57344.
            "cells_2d": 57344,
            "cells_converted": 57344,
            "spanwise_layers": 1,
            "farfield_chords_approx": 500,
            "trailing_edge": "NASA modified sharp trailing edge",
            "chord_m": 1.0,
        },
        required=False,
    ),
    MESH_CGNS_HEX: Asset(
        key=MESH_CGNS_HEX,
        filename="n0012_449-129_hex.cgns.gz",
        role=(
            "INDEPENDENT TOPOLOGY AUTHORITY: the NASA TMR unstructured hexahedral "
            "CGNS representation of the 449x129 NACA0012 grid. Used to qualify our "
            "own Plot3D conversion -- to prove the geometries OpenFOAM flagged are "
            "inherent to the NASA source rather than conversion-induced. It is "
            "never solved on and never substitutes for the registered Plot3D grid."
        ),
        source=f"NASA Turbulence Modeling Resource grid page: {TMR_GRIDS}",
        expected={
            "format": "CGNS, unstructured, single base / single zone",
            "container": "CGNS/HDF5 (a legacy ADF container is refused, not parsed)",
            "element_type": "HEXA_8",
            "corresponds_to": "n0012_449-129.p3dfmt.gz",
            "cells": 57344,
            "reader_dependency": "h5py>=3.0",
        },
        required=False,
    ),
    REF_LADSON_FORCES: Asset(
        key=REF_LADSON_FORCES,
        filename="CLCD_Ladson_expdata.dat",
        role=(
            "EXPERIMENTAL force reference: Ladson tripped force data, as published "
            "by TMR. This is the only experimental gate in this family. Ladson "
            "PRESSURE data is NOT a pressure gate for this setup and is "
            "deliberately not registered as an acceptance asset."
        ),
        source=(
            "Ladson, C.L., NASA TM-4074 (1988); tabulated on the NASA TMR NACA0012 "
            f"validation page: {TMR_PAGE}"
        ),
        expected={
            "format": "native TMR whitespace-delimited .dat",
            "quantities": ["alpha_deg", "CL", "CD"],
            "condition": "tripped, Re_c = 6e6",
            "datasets": "one or more grit/trip conditions, separated by title lines",
            "note": (
                "the experimental incidence offset is PRESERVED; CFD alpha is never "
                "tuned to force agreement"
            ),
        },
    ),
    REF_CFL3D_FORCES: Asset(
        key=REF_CFL3D_FORCES,
        filename="n0012clcd_cfl3d_sst.dat",
        role="supporting CFD reference: NASA CFL3D SST lift/drag",
        source=f"NASA TMR NACA0012 validation page: {TMR_PAGE}",
        expected={
            "format": "native TMR whitespace-delimited .dat",
            "quantities": ["alpha_deg", "CL", "CD"],
            "code": "CFL3D",
            "model": "SST",
        },
    ),
    REF_CFL3D_CP: Asset(
        key=REF_CFL3D_CP,
        filename="n0012cp_cfl3d_sst.dat",
        role=(
            "supporting quantitative CFD reference curve: NASA CFL3D SST surface "
            "pressure at zero incidence; the registered Cp comparison target"
        ),
        source=f"NASA TMR NACA0012 validation page: {TMR_PAGE}",
        expected={
            "format": "native TMR whitespace-delimited .dat",
            "quantities": ["x_over_c", "Cp"],
            "alpha_deg": 0.0,
            "surfaces": (
                "taken from zone/title labels when present; an unlabelled single "
                "curve is applied to both surfaces and that transformation is "
                "recorded in the derived artifact"
            ),
        },
    ),
    REF_CFL3D_CF: Asset(
        key=REF_CFL3D_CF,
        filename="n0012cf_cfl3d_sst.dat",
        role=(
            "supporting CFD evidence only: NASA CFL3D SST skin friction at zero "
            "incidence. Supporting, because no experimental Cf is supplied here; "
            "it is reported, never used as an acceptance gate."
        ),
        source=f"NASA TMR NACA0012 validation page: {TMR_PAGE}",
        expected={
            "format": "native TMR whitespace-delimited .dat",
            "quantities": ["x_over_c", "Cf"],
            "alpha_deg": 0.0,
        },
        required=False,
    ),
}

#: OPTIONAL SUPPORTING INFRASTRUCTURE as of the Gmsh hierarchy decision. The
#: NASA exact-mesh reproduction and the CGNS topology authority are no longer
#: execution assets for the active F3 family: the canonical meshes are generated
#: by the preregistered Gmsh hierarchy. Nothing is deleted and all provenance
#: code remains; these simply no longer block F3 readiness.
#: The ACTIVE canonical mesh hierarchy, coarse -> fine.
FAMILY2_KEYS = (FAMILY2_COARSE, FAMILY2_MEDIUM, FAMILY2_FINE)
FAMILY2_CROSSCHECK_KEYS = (FAMILY2_COARSE_P2D, FAMILY2_MEDIUM_P2D,
                           FAMILY2_FINE_P2D)
FAMILY2_LEVEL_KEYS = {"coarse": FAMILY2_COARSE, "medium": FAMILY2_MEDIUM,
                      "fine": FAMILY2_FINE}
FAMILY2_LEVEL_CROSSCHECK_KEYS = {"coarse": FAMILY2_COARSE_P2D,
                                 "medium": FAMILY2_MEDIUM_P2D,
                                 "fine": FAMILY2_FINE_P2D}

#: Superseded by the Family II hierarchy. Preserved as archived evidence: the
#: 2DN00 Plot3D grids and the single-level CGNS authority that qualified them.
OPTIONAL_SUPPORTING_KEYS = (MESH_CANONICAL, MESH_SENSITIVITY, MESH_CGNS_HEX,
                            *FAMILY2_CROSSCHECK_KEYS)

MESH_KEYS = (MESH_CANONICAL, MESH_SENSITIVITY)
#: Registered meshes that are AUTHORITIES, not meshes we solve on.
AUTHORITY_KEYS = (MESH_CGNS_HEX,)
REFERENCE_KEYS = (REF_LADSON_FORCES, REF_CFL3D_FORCES, REF_CFL3D_CP, REF_CFL3D_CF)


# ----------------------------------------------------------------------
def asset_root(repo_root: Optional[Path] = None) -> Path:
    override = os.environ.get(ASSET_ROOT_ENV)
    if override:
        return Path(override)
    root = Path(repo_root) if repo_root else Path(__file__).resolve().parents[3]
    return root / DEFAULT_ASSET_SUBDIR


def lockfile_path(repo_root: Optional[Path] = None) -> Path:
    root = Path(repo_root) if repo_root else Path(__file__).resolve().parents[3]
    return root / LOCKFILE


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as fh:
        for chunk in iter(lambda: fh.read(_CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_lock(repo_root: Optional[Path] = None) -> Dict[str, Any]:
    path = lockfile_path(repo_root)
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def registered_digest(key: str, repo_root: Optional[Path] = None) -> Optional[str]:
    entry = (load_lock(repo_root).get("assets") or {}).get(key) or {}
    digest = entry.get("sha256")
    return str(digest) if digest else None


def asset_path(key: str, repo_root: Optional[Path] = None) -> Path:
    if key not in REGISTER:
        raise AssetError(f"{key!r} is not a registered airfoil asset")
    return asset_root(repo_root) / REGISTER[key].filename


# ----------------------------------------------------------------------
def check_asset(key: str, repo_root: Optional[Path] = None) -> Dict[str, Any]:
    """Status of one asset. Never raises; the caller decides how to fail."""
    asset = REGISTER[key]
    path = asset_path(key, repo_root)
    expected = registered_digest(key, repo_root)
    present = path.exists()

    status: Dict[str, Any] = {
        "key": key,
        "filename": asset.filename,
        "required": asset.required,
        "path": str(path),
        "present": present,
        "registered_sha256": expected,
        "actual_sha256": None,
        "bytes": None,
        "ok": False,
        "reason": "",
    }
    if not present:
        status["reason"] = (
            f"registered asset {asset.filename!r} is absent from {path.parent}"
        )
        return status
    status["bytes"] = path.stat().st_size
    if expected is None:
        status["reason"] = (
            f"{asset.filename!r} is present but its SHA256 is not registered in "
            f"{LOCKFILE.as_posix()}; run 'scripts/airfoil_assets.py register' once "
            "and commit the lockfile"
        )
        return status
    actual = sha256_of(path)
    status["actual_sha256"] = actual
    if actual != expected:
        status["reason"] = (
            f"SHA256 mismatch for {asset.filename!r}: registered {expected}, "
            f"found {actual}. Refusing: this is not the registered asset."
        )
        return status
    status["ok"] = True
    status["reason"] = "present and matches the registered digest"
    return status


def audit_assets(repo_root: Optional[Path] = None) -> Dict[str, Any]:
    statuses = [check_asset(k, repo_root) for k in REGISTER]
    missing_required = [
        s["key"] for s in statuses if s["required"] and not s["present"]
    ]
    unregistered = [
        s["key"] for s in statuses
        if s["present"] and s["registered_sha256"] is None
    ]
    mismatched = [
        s["key"] for s in statuses
        if s["present"] and s["registered_sha256"] and not s["ok"]
    ]
    return {
        "family": FAMILY,
        "asset_root": str(asset_root(repo_root)),
        "lockfile": str(lockfile_path(repo_root)),
        "lockfile_present": lockfile_path(repo_root).exists(),
        "statuses": statuses,
        "missing_required": missing_required,
        "unregistered": unregistered,
        "mismatched": mismatched,
        "all_required_ok": not (missing_required or unregistered or mismatched),
    }


def require(key: str, repo_root: Optional[Path] = None) -> Path:
    """Return the asset path or raise AssetError. This is the fail-closed gate."""
    status = check_asset(key, repo_root)
    if not status["ok"]:
        raise AssetError(
            f"{FAMILY}: {status['reason']}\n"
            "This family never substitutes another mesh or reference dataset. "
            "Install the registered asset and register its digest."
        )
    return Path(status["path"])


def require_all(repo_root: Optional[Path] = None) -> Dict[str, Path]:
    audit = audit_assets(repo_root)
    if not audit["all_required_ok"]:
        parts: List[str] = []
        for status in audit["statuses"]:
            if status["required"] and not status["ok"]:
                parts.append(f"  - {status['key']}: {status['reason']}")
        raise AssetError(
            f"{FAMILY}: registered assets are not in order.\n" + "\n".join(parts)
        )
    return {
        k: Path(asset_path(k, repo_root)) for k in REGISTER
        if check_asset(k, repo_root)["ok"]
    }


def write_lock(
    entries: Dict[str, Dict[str, Any]],
    *,
    repo_root: Optional[Path] = None,
    toolchain: str = "",
) -> Path:
    """Write the lockfile. Called only by scripts/airfoil_assets.py register."""
    import time

    path = lockfile_path(repo_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "family": FAMILY,
        "registered_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "toolchain": toolchain,
        "note": (
            "SHA256 digests of registered external assets. Written once at install "
            "time and committed. A mismatch fails closed; nothing substitutes."
        ),
        "assets": entries,
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8")
    return path


def required_assets_report() -> List[Dict[str, Any]]:
    """What a human must download, in order. Printed before any long work."""
    return [REGISTER[k].to_dict() for k in REGISTER]
