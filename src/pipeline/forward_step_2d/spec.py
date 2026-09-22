#!/usr/bin/env python3
"""Structured specification for the trusted 2D forward-facing-step family.

PROVENANCE
----------
The scientific anchor is the OpenFOAM Foundation v14 tutorial
``$FOAM_TUTORIALS/shockFluid/forwardStep``, vendored read-only at
``src/pipeline/forward_step/template/``.  That template is the 2D tutorial case
(16,128 cells, one empty z layer, Kurganov + vanLeer/vanLeerV, Euler,
maxCo 0.2, endTime 4).  This package never writes into it.

This module is adapted from ``src/pipeline/forward_step/spec.py``, which was
written for the exploratory periodic 3D extrusion.  The spanwise cell count and
the cyclic span boundary condition are removed: this family is physically 2D and
the span is a single empty layer, which is a property of the family rather than
a free parameter.

SCOPE
-----
Supersonic inviscid compressible Euler over a forward-facing step, normalized
ideal gas, Foundation v14 ``shockFluid``.  The numerical recipe (fluxes,
reconstruction, time integration, thermophysical model) is fixed by the
template and is not a specification field, so it cannot be varied to make a
case pass.
"""
from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any, Dict, List, Tuple

FAMILY = "forward_step_2d"
PHYSICS = "inviscid_euler"

# Normalized gas of the canonical tutorial: molWeight 11640.3, Cp 2.5, hf 0.
# Reproduced here for diagnostics only; the solver reads the template.
R_SPECIFIC = 8314.46261815324 / 11640.3
CP = 2.5
GAMMA = CP / (CP - R_SPECIFIC)

# Canonical tutorial resolution. nx counts cells across the full channel length
# at the upper level; ny counts cells across the full channel height.
CANONICAL_NX = 240
CANONICAL_NY = 80
CANONICAL_CELLS = 16128

# Deterministic bound on agent-requested resolution. The canonical mesh is
# 16,128 cells; this cap keeps an approved REFINE_MESH action from producing a
# case that cannot finish in a reasonable wall time. It is an engineering
# guard, not a physical criterion.
MAX_CELLS = 200_000


@dataclass(frozen=True)
class ForwardStep2DSpec:
    """One scope-checked 2D forward-step case."""

    # geometry
    length: float = 3.0
    height: float = 1.0
    step_x: float = 0.6
    step_height: float = 0.2
    span: float = 0.1

    # resolution (one empty layer in z is implied by the family)
    nx: int = CANONICAL_NX
    ny: int = CANONICAL_NY

    # inflow state
    mach: float = 3.0
    pressure: float = 1.0
    temperature: float = 1.0

    # run control
    end_time: float = 4.0
    max_co: float = 0.2
    write_interval: float = 0.1

    # fixed family identity
    family: str = FAMILY
    physics: str = PHYSICS

    # ------------------------------------------------------------------

    def __post_init__(self) -> None:
        for key in [
            "length", "height", "step_x", "step_height", "span",
            "mach", "pressure", "temperature",
            "end_time", "max_co", "write_interval",
        ]:
            value = getattr(self, key)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"{key} must be a number")
            if not math.isfinite(value) or value <= 0:
                raise ValueError(f"{key} must be finite and positive, got {value}")

        for key in ["nx", "ny"]:
            value = getattr(self, key)
            if type(value) is not int or value < 2:
                raise ValueError(f"{key} must be an integer >= 2, got {value!r}")

        if not self.step_x < self.length:
            raise ValueError("step_x must lie strictly inside the channel length")
        if not self.step_height < self.height:
            raise ValueError("step_height must lie strictly below the channel height")

        if self.mach <= 1:
            raise ValueError(
                "This family is validated for supersonic inflow only (Mach > 1)"
            )
        if self.max_co > 0.2:
            raise ValueError(
                "max_co above the trusted 0.2 recipe is outside the validated family"
            )
        if self.write_interval > self.end_time:
            raise ValueError("write_interval must not exceed end_time")

        if self.family != FAMILY or self.physics != PHYSICS:
            raise ValueError(
                "Only the 2D inviscid-Euler forward-step family is supported"
            )

        a, b = self.splits
        if not (1 <= a < self.nx):
            raise ValueError(
                "Resolution must allocate at least one cell each side of the step face"
            )
        if not (1 <= b < self.ny):
            raise ValueError(
                "Resolution must allocate at least one cell above and below the step"
            )
        if self.cells > MAX_CELLS:
            raise ValueError(
                f"Requested {self.cells} cells exceeds the {MAX_CELLS} bound for this family"
            )

    # ------------------------------------------------------------------
    # derived geometry
    # ------------------------------------------------------------------

    @property
    def splits(self) -> Tuple[int, int]:
        """(cells upstream of the step face, cells below the step top)."""
        return (
            round(self.nx * self.step_x / self.length),
            round(self.ny * self.step_height / self.height),
        )

    @property
    def cells(self) -> int:
        """Fluid cells. The solid block behind and below the step is absent."""
        a, b = self.splits
        return a * self.ny + (self.nx - a) * (self.ny - b)

    @property
    def block_cells(self) -> List[int]:
        a, b = self.splits
        return [a * b, a * (self.ny - b), (self.nx - a) * (self.ny - b)]

    @property
    def dx(self) -> float:
        return self.step_x / self.splits[0]

    @property
    def dy(self) -> float:
        return self.step_height / self.splits[1]

    @property
    def velocity(self) -> float:
        """Axial inflow speed.

        Preserves the tutorial's U = 3 exactly at T = 1 and nominal Mach 3. The
        rounded molecular weight makes the realized Mach differ by ~3 ppm; that
        difference is reported by diagnostics rather than hidden here.
        """
        return self.mach * math.sqrt(self.temperature)

    @property
    def realized_mach(self) -> float:
        return self.velocity / math.sqrt(GAMMA * R_SPECIFIC * self.temperature)

    @property
    def is_canonical(self) -> bool:
        """True when this spec reproduces the trusted tutorial case exactly."""
        return self.to_dict() == ForwardStep2DSpec().to_dict()

    # ------------------------------------------------------------------
    # serialization
    # ------------------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ForwardStep2DSpec":
        if not isinstance(data, dict):
            raise ValueError("Specification must be a mapping")
        unknown = set(data) - {f.name for f in fields(cls)}
        if unknown:
            raise ValueError(
                "Unsupported specification keys: " + ", ".join(sorted(unknown))
            )
        return cls(**data)

    @classmethod
    def load(cls, path) -> "ForwardStep2DSpec":
        path = Path(path)
        if path.suffix.lower() == ".json":
            data = json.loads(path.read_text(encoding="utf-8-sig"))
        else:
            import yaml

            data = yaml.safe_load(path.read_text(encoding="utf-8-sig"))
        return cls.from_dict(data)

    def with_changes(self, **changes: Any) -> "ForwardStep2DSpec":
        """A new validated spec. Used by approved bounded actions."""
        return ForwardStep2DSpec.from_dict({**self.to_dict(), **changes})


CANONICAL_SPEC = ForwardStep2DSpec()
