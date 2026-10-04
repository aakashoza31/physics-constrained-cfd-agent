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

"CANONICAL" IN THIS MODULE
--------------------------
``CANONICAL_*``, ``CANONICAL_SPEC`` and ``is_canonical`` refer to the Mach-3
OpenFOAM tutorial specification reproduced by the default spec. They do not
refer to the paper's canonical agent run, which is the Mach-2 case
(cases/forward_step/mach20_canonical).

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
from typing import Any, Dict, List, Optional, Tuple

FAMILY = "forward_step_2d"
PHYSICS = "inviscid_euler"

# Normalized gas of the canonical tutorial: molWeight 11640.3, Cp 2.5, hf 0.
# Reproduced here for diagnostics only; the solver reads the template.
R_SPECIFIC = 8314.46261815324 / 11640.3
CP = 2.5
GAMMA = CP / (CP - R_SPECIFIC)

# Tutorial-specification (Mach 3) resolution. nx counts cells across the full channel length
# at the upper level; ny counts cells across the full channel height.
CANONICAL_NX = 240
CANONICAL_NY = 80
CANONICAL_CELLS = 16128

# Deterministic bound on agent-requested resolution. The canonical mesh is
# 16,128 cells; this cap keeps an approved REFINE_MESH action from producing a
# case that cannot finish in a reasonable wall time. It is an engineering
# guard, not a physical criterion.
MAX_CELLS = 200_000

# The registered reference horizon for this family. This is not a number
# invented to force iteration: it is the endTime of the vendored tutorial
# controlDict at src/pipeline/forward_step/template/system/controlDict, the
# same horizon the canonical case is solved to and the horizon every piece of
# reference evidence for this family is stated at. A run that stops short of it
# is a partial realization of the registered benchmark, whatever its numerical
# health. It applies only when the request does not state a final horizon of
# its own.
FAMILY_REFERENCE_HORIZON = 4.0


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

    # Run control.
    #
    # THREE HORIZONS, DELIBERATELY DISTINCT. Conflating them is what made a
    # healthy iterative run stop early: an instruction to run the FIRST
    # execution to t = 0.5 was read as a statement that 0.5 was the whole
    # scientific ambition, so the workflow had nothing left to aim at.
    #
    #   end_time
    #       The horizon of the NEXT solver execution, and the value written to
    #       controlDict. An approved EXTEND_END_TIME advances it.
    #   initial_execution_end_time
    #       What end_time was when the case was first built. Immutable
    #       provenance: it records what the user asked the first run to do and
    #       survives every extension.
    #   final_target_end_time
    #       The horizon final scientific acceptance requires. Defaults to the
    #       registered family reference horizon; a request that names its own
    #       final horizon overrides it.
    end_time: float = 4.0
    max_co: float = 0.2
    write_interval: float = 0.1

    # Resolved in __post_init__ when left unset, so an older spec.json that
    # predates this distinction still loads and is interpreted the same way a
    # request without an explicit final horizon would be.
    final_target_end_time: Optional[float] = None
    initial_execution_end_time: Optional[float] = None

    # Mesh-refinement study state. refinement_level counts how many registered
    # refinements produced this grid, so level 0 is whatever the request asked
    # for. sensitivity_assessment_requested records that the request asked for
    # a resolution assessment, which a single healthy grid cannot supply; it
    # does not name an action, because the evidence decides that.
    refinement_level: int = 0
    sensitivity_assessment_requested: bool = False

    # fixed family identity
    family: str = FAMILY
    physics: str = PHYSICS

    # ------------------------------------------------------------------

    def __post_init__(self) -> None:
        # Resolve the two derived horizons before anything is validated. The
        # dataclass is frozen, so this is the one place they may be written.
        if self.final_target_end_time is None:
            # An unstated final target means the request qualified only an
            # execution horizon ("for the initial run, use 0.5"), so the
            # registered family horizon is what acceptance aims at. The max()
            # keeps the invariant end_time <= final_target for a request that
            # asks to run PAST the family horizon: clamping that back to 4
            # would silently shorten what was asked for, and the scope gate,
            # not this constructor, is where an out-of-envelope horizon is
            # refused. A request naming its own final horizon sets this field
            # explicitly and neither branch applies.
            object.__setattr__(
                self,
                "final_target_end_time",
                float(max(FAMILY_REFERENCE_HORIZON, self.end_time)),
            )
        if self.initial_execution_end_time is None:
            object.__setattr__(
                self, "initial_execution_end_time", float(self.end_time)
            )

        for key in [
            "length", "height", "step_x", "step_height", "span",
            "mach", "pressure", "temperature",
            "end_time", "max_co", "write_interval",
            "final_target_end_time", "initial_execution_end_time",
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

        if type(self.refinement_level) is not int or self.refinement_level < 0:
            raise ValueError("refinement_level must be a non-negative integer")

        if not self.step_x < self.length:
            raise ValueError("step_x must lie strictly inside the channel length")
        if not self.step_height < self.height:
            raise ValueError("step_height must lie strictly below the channel height")

        if self.mach <= 1:
            raise ValueError(
                "This family is registered for supersonic inflow only (Mach > 1)"
            )
        if self.max_co > 0.2:
            raise ValueError(
                "max_co above the trusted 0.2 recipe is outside the registered family"
            )
        if self.write_interval > self.end_time:
            raise ValueError("write_interval must not exceed end_time")

        if self.end_time > self.final_target_end_time + 1e-12:
            raise ValueError(
                f"end_time {self.end_time:g} exceeds the final target horizon "
                f"{self.final_target_end_time:g}. The execution horizon advances "
                "toward the final target, never past it; state a larger final "
                "target if that is what is wanted."
            )
        if self.initial_execution_end_time > self.end_time + 1e-12:
            raise ValueError(
                "initial_execution_end_time must not exceed the current "
                "end_time; the execution horizon only advances."
            )

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
        """True when this spec reproduces the Mach-3 tutorial specification exactly.

        This is not the paper's canonical agent run (Mach 2).
        """
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
        """A new spec, re-checked on construction. Used by approved bounded actions."""
        return ForwardStep2DSpec.from_dict({**self.to_dict(), **changes})


CANONICAL_SPEC = ForwardStep2DSpec()
