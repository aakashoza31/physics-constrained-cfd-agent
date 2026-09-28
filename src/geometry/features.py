#!/usr/bin/env python3
"""Geometry characterization: the features a family router is allowed to see.

Two sources, one vocabulary:

  * PARAMETRIC -- the geometry the request itself describes (a throat radius, a
    step height, a cube side). This is what the working families use, and the
    features are exact because the geometry is generated from them.
  * STEP -- a CAD part. Features are extracted only if a CAD kernel is present
    AND a family declares STEP support. Neither holds today, so the extraction
    returns UNSUPPORTED with a reason, and never a fabricated bounding box.

`GeometryFeatures.characteristic_dimension` is what normalises an incoming
geometry against a family's envelope; it is None when unknown, and a None is
never silently replaced by a default.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional

from src.geometry import step_reader

FEATURES_VERSION = "geometry-features/1.0.0"

PARAMETRIC = "parametric"
STEP = "step"

SUPPORTED = "FEATURES_EXTRACTED"
UNSUPPORTED = "UNSUPPORTED_GEOMETRY"


@dataclass
class GeometryFeatures:
    """What the router may know about the geometry, and where it came from."""

    source: str
    status: str
    #: Free-form but named dimensions, in metres unless the family says otherwise.
    dimensions: Dict[str, float] = field(default_factory=dict)
    #: The single length a family normalises against, when it is known.
    characteristic_dimension: Optional[float] = None
    characteristic_name: str = ""
    topology: Dict[str, Any] = field(default_factory=dict)
    provenance: Dict[str, Any] = field(default_factory=dict)
    reason: str = ""

    @property
    def usable(self) -> bool:
        return self.status == SUPPORTED

    def to_dict(self) -> Dict[str, Any]:
        return {
            "features_version": FEATURES_VERSION,
            "source": self.source,
            "status": self.status,
            "usable": self.usable,
            "dimensions": dict(self.dimensions),
            "characteristic_dimension": self.characteristic_dimension,
            "characteristic_name": self.characteristic_name,
            "topology": dict(self.topology),
            "provenance": dict(self.provenance),
            "reason": self.reason,
        }


def from_parameters(dimensions: Dict[str, float], *,
                    characteristic_name: str = "") -> GeometryFeatures:
    """Features of a geometry the request described. Exact by construction."""
    clean = {k: float(v) for k, v in dimensions.items()
             if isinstance(v, (int, float)) and not isinstance(v, bool)}
    characteristic = clean.get(characteristic_name) if characteristic_name else None
    return GeometryFeatures(
        source=PARAMETRIC,
        status=SUPPORTED,
        dimensions=clean,
        characteristic_dimension=characteristic,
        characteristic_name=characteristic_name,
        provenance={"origin": "request parameters; geometry is generated from "
                              "these values, so the features are exact"},
    )


def from_step(path: Path) -> GeometryFeatures:
    """Characterise a STEP part. Returns UNSUPPORTED while no backend exists."""
    step = step_reader.read_step(Path(path))
    info = step.to_dict()
    if step.status != step_reader.OK:
        return GeometryFeatures(
            source=STEP, status=UNSUPPORTED, provenance=info,
            reason=f"the STEP file could not be read: {step.status}. {step.note}",
        )
    if not step.readable_geometry:
        return GeometryFeatures(
            source=STEP, status=UNSUPPORTED, provenance=info,
            topology={"entity_counts": step.entity_counts},
            reason=(
                "no CAD kernel is installed, so no solid can be loaded and no "
                "bounding box, characteristic dimension or feature can be "
                "measured. Nothing is estimated from the entity histogram."
            ),
        )
    # A kernel is present, but no family declares STEP support, so extraction is
    # still refused rather than half-performed.
    return GeometryFeatures(
        source=STEP, status=UNSUPPORTED, provenance=info,
        topology={"entity_counts": step.entity_counts},
        reason=(
            "a CAD kernel is importable, but no registered family declares STEP "
            "input, so feature extraction is not attempted. Implementing it "
            "requires a family to advertise step: true and to mesh the result."
        ),
    )
