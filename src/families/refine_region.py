#!/usr/bin/env python3
"""Bounded local mesh refinement: the REFINE_REGION architecture.

The division of authority is the whole point of this module.

    The LLM may propose exactly one thing: the action name ``REFINE_REGION``,
    optionally naming a region from a CLOSED vocabulary the family declares.
    It may not name cells, coordinates, refinement factors, levels, or any
    mesh dictionary entry, and it may not edit a dictionary.

    Deterministic family code owns everything else: whether under-resolution
    exists, which cells the named region corresponds to, how many levels are
    applied, whether the resulting cell count is admissible, and whether the
    refined mesh passes checkMesh.

``RefineRegionPolicy`` holds the bounds. They are architectural limits on how
much a single corrective action may change a case -- not scientific
thresholds -- so they are registered here rather than left TODO. The question
"is this region actually under-resolved?" IS scientific, and every family
leaves that threshold as TODO until its reference registers one.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

from src.families.base import CRITERION_NOT_REGISTERED, ActionRuling

ACTION = "REFINE_REGION"

#: Verdicts the deterministic under-resolution detector may return.
UNDER_RESOLVED = "UNDER_RESOLVED"
ADEQUATELY_RESOLVED = "ADEQUATELY_RESOLVED"
NOT_ESTABLISHED = "UNDER_RESOLUTION_NOT_ESTABLISHED"


@dataclass(frozen=True)
class RefineRegionPolicy:
    """Architectural bounds on one local-refinement action.

    These cap how far a single bounded corrective action may move a case. They
    are not acceptance criteria and they are not tuned against results.
    """

    #: Maximum refinement levels applied cumulatively by this action type.
    max_levels: int = 2
    #: One level halves cell size in each refined direction.
    levels_per_action: int = 1
    #: A region may not cover more than this fraction of the domain, otherwise
    #: it is a global refinement wearing a local name.
    max_region_fraction: float = 0.35
    #: A region must contain at least this fraction, otherwise it is noise.
    min_region_fraction: float = 0.002
    #: Hard ceiling on total cells after refinement.
    max_total_cells: int = 200_000
    #: Ceiling on the multiplicative growth of one action.
    max_cell_growth_factor: float = 4.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "max_levels": self.max_levels,
            "levels_per_action": self.levels_per_action,
            "max_region_fraction": self.max_region_fraction,
            "min_region_fraction": self.min_region_fraction,
            "max_total_cells": self.max_total_cells,
            "max_cell_growth_factor": self.max_cell_growth_factor,
            "authority": "architectural_bound_not_scientific_threshold",
        }


@dataclass(frozen=True)
class RegionSelection:
    """A region chosen by DETERMINISTIC code, never by the LLM."""

    name: str
    #: Axis-aligned selection box in domain coordinates.
    box_min: Tuple[float, float, float]
    box_max: Tuple[float, float, float]
    #: Cells inside the box, as counted by the family.
    cell_count: int
    #: Total cells in the current mesh.
    total_cells: int
    #: Levels this action would apply.
    levels: int
    #: How the box was derived -- an audit string, e.g. which measured
    #: quantity located it. Must not be empty.
    derivation: str = ""
    measurements: Dict[str, Any] = field(default_factory=dict)

    @property
    def fraction(self) -> float:
        return self.cell_count / self.total_cells if self.total_cells else 0.0

    @property
    def projected_cells(self) -> int:
        """Cells after refinement, for a 2D (x,y) split of the selected cells."""
        multiplier = 4 ** self.levels
        return int(self.total_cells - self.cell_count + self.cell_count * multiplier)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "box_min": list(self.box_min),
            "box_max": list(self.box_max),
            "cell_count": self.cell_count,
            "total_cells": self.total_cells,
            "fraction": self.fraction,
            "levels": self.levels,
            "projected_cells": self.projected_cells,
            "derivation": self.derivation,
            "measurements": dict(self.measurements),
            "authority": "deterministic",
        }


# ----------------------------------------------------------------------
def rule_on_region_request(
    *,
    region_hint: Optional[str],
    vocabulary: Sequence[str],
    selection: Optional[RegionSelection],
    resolution_verdict: str,
    policy: RefineRegionPolicy,
    levels_already_applied: int,
) -> ActionRuling:
    """Decide whether one proposed REFINE_REGION may execute. Fails closed.

    ``resolution_verdict`` is the family's deterministic answer to "is this
    region under-resolved?". When the family has no registered criterion it
    passes NOT_ESTABLISHED and the action is refused -- a refusal, not a
    guess.
    """
    reasons: List[str] = []

    # 1. The hint must come from the closed vocabulary, if one was given.
    if region_hint is not None and region_hint not in vocabulary:
        return ActionRuling(
            False,
            ACTION,
            [
                f"region hint {region_hint!r} is not in this family's closed "
                f"vocabulary {tuple(vocabulary)}; the LLM may not name an "
                "arbitrary region."
            ],
        )

    # 2. The deterministic detector must have found a region.
    if selection is None:
        return ActionRuling(
            False,
            ACTION,
            ["the deterministic region detector selected no region"],
        )
    if not selection.derivation:
        return ActionRuling(
            False,
            ACTION,
            ["region selection carries no derivation; refusing an unaudited region"],
        )

    # 3. Under-resolution must be established, deterministically.
    if resolution_verdict == NOT_ESTABLISHED:
        return ActionRuling(
            False,
            ACTION,
            [
                f"{CRITERION_NOT_REGISTERED}: this family has no registered "
                "under-resolution criterion, so local refinement cannot be "
                "justified from evidence. Refusing rather than inventing a "
                "threshold."
            ],
            {"resolution_verdict": resolution_verdict},
        )
    if resolution_verdict == ADEQUATELY_RESOLVED:
        return ActionRuling(
            False,
            ACTION,
            ["the deterministic detector reports the region is adequately resolved"],
            {"resolution_verdict": resolution_verdict},
        )
    if resolution_verdict != UNDER_RESOLVED:
        return ActionRuling(
            False, ACTION, [f"unknown resolution verdict {resolution_verdict!r}"]
        )

    # 4. Architectural bounds.
    if levels_already_applied + selection.levels > policy.max_levels:
        reasons.append(
            f"refinement level cap reached: {levels_already_applied} applied, "
            f"{selection.levels} requested, cap {policy.max_levels}"
        )
    if selection.fraction > policy.max_region_fraction:
        reasons.append(
            f"region covers {selection.fraction:.3f} of the domain, above the "
            f"{policy.max_region_fraction} local-refinement bound; that is a "
            "global refinement, which is a different registered action"
        )
    if selection.fraction < policy.min_region_fraction:
        reasons.append(
            f"region covers only {selection.fraction:.5f} of the domain, below "
            f"the {policy.min_region_fraction} floor"
        )
    if selection.projected_cells > policy.max_total_cells:
        reasons.append(
            f"refinement would give {selection.projected_cells} cells, above the "
            f"{policy.max_total_cells} family ceiling"
        )
    growth = (
        selection.projected_cells / selection.total_cells
        if selection.total_cells
        else float("inf")
    )
    if growth > policy.max_cell_growth_factor:
        reasons.append(
            f"refinement would grow the mesh {growth:.2f}x, above the "
            f"{policy.max_cell_growth_factor}x single-action bound"
        )

    if reasons:
        return ActionRuling(False, ACTION, reasons, {"region": selection.to_dict()})

    return ActionRuling(
        True,
        ACTION,
        [
            f"region {selection.name!r} selected deterministically "
            f"({selection.derivation}); {selection.cell_count} cells "
            f"({selection.fraction:.3f} of domain) refined {selection.levels} level(s); "
            f"{selection.total_cells} -> {selection.projected_cells} cells"
        ],
        {
            "region": selection.to_dict(),
            "policy": policy.to_dict(),
            "resolution_verdict": resolution_verdict,
        },
    )


# ----------------------------------------------------------------------
# OpenFOAM dictionary emission. Mechanical text generation from a region the
# deterministic layer already chose -- no scientific content, and the LLM never
# reaches this code.
# ----------------------------------------------------------------------
_HEADER = """/*--------------------------------*- C++ -*----------------------------------*\\
| GENERATED by src/families/refine_region.py -- do not edit by hand.          |
| Region chosen deterministically; no LLM-authored values appear below.       |
\\*---------------------------------------------------------------------------*/
FoamFile
{{
    format      ascii;
    class       dictionary;
    object      {obj};
}}

"""


def topo_set_dict(selection: RegionSelection, set_name: str = "refineRegion") -> str:
    """A topoSetDict selecting the region's cells by bounding box."""
    x0, y0, z0 = selection.box_min
    x1, y1, z1 = selection.box_max
    return _HEADER.format(obj="topoSetDict") + (
        "actions\n(\n"
        "    {\n"
        f"        name    {set_name};\n"
        "        type    cellSet;\n"
        "        action  new;\n"
        "        source  boxToCell;\n"
        f"        box     ({x0:.12g} {y0:.12g} {z0:.12g}) "
        f"({x1:.12g} {y1:.12g} {z1:.12g});\n"
        "    }\n"
        ");\n"
    )


def refine_mesh_dict(
    set_name: str = "refineRegion",
    *,
    directions: Sequence[str] = ("tan1", "tan2"),
) -> str:
    """A refineMeshDict splitting the selected set in the given directions.

    Two directions keep a 2D family planar: the empty direction is never split.
    """
    coords = " ".join(directions)
    return _HEADER.format(obj="refineMeshDict") + (
        f"set             {set_name};\n"
        "coordinateSystem global;\n"
        "globalCoeffs\n{\n"
        "    tan1 (1 0 0);\n"
        "    tan2 (0 1 0);\n"
        "}\n"
        f"directions      ( {coords} );\n"
        "useHexTopology  true;\n"
        "geometricCut    false;\n"
        "writeMesh       false;\n"
    )
