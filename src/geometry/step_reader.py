#!/usr/bin/env python3
"""STEP/CAD reader abstraction. It refuses cleanly rather than pretending.

There is no STEP-to-mesh path in this system. This module exists so that a STEP
file entering the public CLI is handled the way every other unsupported input is
handled: classified, refused, and reported as UNSUPPORTED -- before any mesh is
built and before any solver is launched.

What it does do, with no CAD kernel installed:

  * confirm the file exists and is a readable ISO-10303-21 STEP part file;
  * read the header (FILE_NAME, FILE_DESCRIPTION, FILE_SCHEMA) and the entity
    histogram, which is plain text parsing and needs no kernel;
  * report the backends it would need, and that none is present.

It never invents a bounding box, a characteristic dimension or a feature list.
If a CAD kernel is installed later, `BACKENDS` is where it is declared; until a
backend actually returns geometry, `read_step` reports NO_BACKEND and the agent
returns INCONCLUSIVE / UNSUPPORTED_GEOMETRY.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

READER_VERSION = "step-reader/1.0.0"

#: Status codes this module can return. All of them are honest outcomes.
OK = "STEP_HEADER_READ"
NOT_A_STEP_FILE = "NOT_A_STEP_FILE"
FILE_MISSING = "FILE_MISSING"
NO_BACKEND = "NO_CAD_BACKEND"

#: CAD kernels this reader would use, in preference order. None is bundled.
BACKENDS: Tuple[Tuple[str, str], ...] = (
    ("OCP", "pip install cadquery-ocp   (OpenCASCADE via OCP)"),
    ("OCC", "conda install -c conda-forge pythonocc-core"),
    ("cadquery", "pip install cadquery"),
)

_STEP_MAGIC = "ISO-10303-21"
_ENTITY = re.compile(r"=\s*([A-Z_0-9]+)\s*\(")


def available_backends() -> List[str]:
    """CAD kernels importable right now. Usually empty, and that is reported."""
    found: List[str] = []
    for module, _hint in BACKENDS:
        try:
            __import__(module)
        except Exception:      # noqa: BLE001 - absence is the normal case
            continue
        found.append(module)
    return found


@dataclass
class StepFile:
    """What could be learned about a STEP file without a CAD kernel."""

    path: Path
    status: str
    schema: str = ""
    name: str = ""
    description: str = ""
    entity_counts: Dict[str, int] = field(default_factory=dict)
    bytes: int = 0
    backends_present: List[str] = field(default_factory=list)
    note: str = ""

    #: Set only when a backend actually loaded a solid and returned geometry.
    #: An importable CAD kernel is NOT geometry: nothing in this repository
    #: calls one, so this stays False and the public answer stays UNSUPPORTED.
    geometry: Optional[Dict[str, Any]] = None
    extracted_by: str = ""

    @property
    def readable_geometry(self) -> bool:
        """True only when geometry was ACTUALLY extracted. Never faked.

        Presence of an importable kernel says nothing: it is a package on the
        path, not a loaded solid. This property answers the only question that
        matters downstream -- did something produce real geometry -- so an
        environment that happens to have OCP, OCC or cadquery installed behaves
        exactly like one that does not.
        """
        return self.status == OK and self.geometry is not None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "reader_version": READER_VERSION,
            "path": str(self.path),
            "status": self.status,
            "schema": self.schema,
            "name": self.name,
            "description": self.description,
            "bytes": self.bytes,
            "entity_counts": dict(self.entity_counts),
            "backends_present": list(self.backends_present),
            "backends_supported": [b for b, _ in BACKENDS],
            "geometry_extracted": self.readable_geometry,
            "geometry": self.geometry,
            "extracted_by": self.extracted_by,
            "note": self.note,
        }


def read_step(path: Path, *, max_entities: int = 200_000) -> StepFile:
    """Read what is readable. Returns a status; never raises on bad input."""
    path = Path(path)
    backends = available_backends()
    if not path.exists():
        return StepFile(path=path, status=FILE_MISSING,
                        backends_present=backends,
                        note="the STEP file does not exist at that path")
    raw = path.read_bytes()
    head = raw[:4096].decode("latin-1", "replace")
    if _STEP_MAGIC not in head:
        return StepFile(path=path, status=NOT_A_STEP_FILE, bytes=len(raw),
                        backends_present=backends,
                        note=("the file does not begin with an ISO-10303-21 "
                              "header, so it is not a STEP part file"))

    text = raw.decode("latin-1", "replace")
    schema = ""
    match = re.search(r"FILE_SCHEMA\s*\(\s*\(\s*'([^']*)'", text)
    if match:
        schema = match.group(1)
    name = ""
    match = re.search(r"FILE_NAME\s*\(\s*'([^']*)'", text)
    if match:
        name = match.group(1)
    description = ""
    match = re.search(r"FILE_DESCRIPTION\s*\(\s*\(\s*'([^']*)'", text)
    if match:
        description = match.group(1)

    counts: Dict[str, int] = {}
    for n, entity in enumerate(_ENTITY.finditer(text)):
        if n >= max_entities:
            break
        counts[entity.group(1)] = counts.get(entity.group(1), 0) + 1

    note = (
        "header and entity histogram read as text. No solid, bounding box or "
        "feature was extracted and none is guessed"
        + (". No CAD kernel is installed." if not backends else
           f". A CAD kernel is importable ({', '.join(backends)}), but no "
           "registered family declares STEP support, so no extraction is "
           "attempted and an importable kernel alone is not geometry.")
    )
    return StepFile(path=path, status=OK, schema=schema, name=name,
                    description=description, entity_counts=counts,
                    bytes=len(raw), backends_present=backends, note=note)
