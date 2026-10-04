#!/usr/bin/env python3
"""Generate a 2D forward-step OpenFOAM case from the trusted template.

PROVENANCE
----------
Adapted from ``src/pipeline/forward_step/build.py``. Two things change:

1. The mesh is genuinely 2D. The z direction carries exactly one cell and the
   spanwise boundaries stay ``empty`` via ``defaultPatch``. The 3D builder
   rewrote those patches into a matched cyclic pair; that rewrite is removed,
   and with it the ``0/`` field patch surgery it required.
2. Flux monitors cover the five real patches only. ``surfaceFieldValue`` is not
   meaningful on an empty patch.

What is deliberately NOT parameterized: fvSchemes, fvSolution,
physicalProperties and momentumTransport are copied byte-for-byte from the
template and are hashed into the case so the validator can prove the trusted
numerical recipe was not altered.
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
from pathlib import Path
from typing import Dict

from .spec import ForwardStep2DSpec

# Read-only anchor. This package never writes inside it.
TEMPLATE = Path(__file__).resolve().parents[1] / "forward_step" / "template"

FIXED_RECIPE_FILES = [
    "system/fvSchemes",
    "system/fvSolution",
    "constant/physicalProperties",
    "constant/momentumTransport",
]

FLUX_PATCHES = ["inlet", "outlet", "bottom", "top", "obstacle"]


def initial_state(spec: ForwardStep2DSpec) -> Dict[str, object]:
    """Uniform startup, exactly as the canonical tutorial does it."""
    return {
        "p": spec.pressure,
        "T": spec.temperature,
        "U": (spec.velocity, 0.0, 0.0),
    }


def mesh_dictionary(spec: ForwardStep2DSpec) -> str:
    """Three-block 2D blockMeshDict with empty spanwise default patches."""
    a, b = spec.splits
    L, H, x, h, w = (
        spec.length,
        spec.height,
        spec.step_x,
        spec.step_height,
        spec.span,
    )

    xy = [(0, 0), (x, 0), (0, h), (x, h), (L, h), (0, H), (x, H), (L, H)]
    vertices = "\n".join(
        f"    ({xx:.16g} {yy:.16g} {zz:.16g})"
        for zz in (-w / 2, w / 2)
        for xx, yy in xy
    )

    return f"""FoamFile {{ format ascii; class dictionary; object blockMeshDict; }}
vertices
(
{vertices}
);

blocks
(
    hex (0 1 3 2 8 9 11 10) ({a} {b} 1) simpleGrading (1 1 1)
    hex (2 3 6 5 10 11 14 13) ({a} {spec.ny - b} 1) simpleGrading (1 1 1)
    hex (3 4 7 6 11 12 15 14) ({spec.nx - a} {spec.ny - b} 1) simpleGrading (1 1 1)
);

defaultPatch
{{
    type empty;
}}

boundary
(
    inlet
    {{
        type patch;
        faces ((0 8 10 2) (2 10 13 5));
    }}
    outlet
    {{
        type patch;
        faces ((4 7 15 12));
    }}
    bottom
    {{
        type symmetryPlane;
        faces ((0 1 9 8));
    }}
    top
    {{
        type symmetryPlane;
        faces ((5 13 14 6) (6 14 15 7));
    }}
    obstacle
    {{
        type patch;
        faces ((1 3 11 9) (3 4 12 11));
    }}
);
"""


def monitors() -> str:
    """Per-timestep domain mass, field minima and every real boundary flux.

    These are what make the transient discrete balance dM/dt + sum(phi)
    computable after the run; they add no physics.
    """
    common = (
        'libs ("libfieldFunctionObjects.so"); writeFields false; '
        "writeControl timeStep; writeInterval 1; log false;"
    )

    text = "\nfunctions\n{\n"
    text += (
        f"    mass {{ type volFieldValue; cellZone all; operation volIntegrate; "
        f"fields (rho); {common} }}\n"
    )
    text += (
        f"    minima {{ type volFieldValue; cellZone all; operation min; "
        f"fields (rho p T); {common} }}\n"
    )
    for patch in FLUX_PATCHES:
        text += (
            f"    flux_{patch} {{ type surfaceFieldValue; patch {patch}; "
            f"operation sum; fields (phi); {common} }}\n"
        )
    return text + "}\n"


def build(spec: ForwardStep2DSpec, destination) -> Path:
    """Materialize a runnable case directory. Refuses to overwrite."""
    dest = Path(destination)
    if dest.exists():
        raise FileExistsError(f"Existing case preserved: {dest}")

    shutil.copytree(TEMPLATE, dest)

    (dest / "system/blockMeshDict").write_text(mesh_dictionary(spec))

    state = initial_state(spec)
    for name in ("p", "T", "U"):
        path = dest / "0" / name
        text = path.read_text()
        if name == "U":
            value = "(" + " ".join(f"{v:.16g}" for v in state["U"]) + ")"
        else:
            value = f"{float(state[name]):.16g}"
        # Only the uniform values change. Patch types stay as the tutorial
        # wrote them, including the empty spanwise defaultFaces.
        text, count = re.subn(
            r"(\b(?:internalField|value|inletValue)\s+uniform)\s+[^;]+;",
            lambda m: m[1] + " " + value + ";",
            text,
        )
        if count == 0:
            raise ValueError(f"No uniform entries were rewritten in 0/{name}")
        path.write_text(text)

    control = dest / "system/controlDict"
    text = control.read_text()
    for key, value in {
        "endTime": f"{spec.end_time:.12g}",
        "maxCo": f"{spec.max_co:.12g}",
        "writeInterval": f"{spec.write_interval:.12g}",
        "writePrecision": "16",
        "timePrecision": "14",
    }.items():
        text, count = re.subn(rf"\b{key}\s+[^;]+;", f"{key} {value};", text)
        if count == 0:
            raise ValueError(f"controlDict has no {key} entry to set")
    control.write_text(text + monitors())

    (dest / "spec.json").write_text(json.dumps(spec.to_dict(), indent=2))

    # Provenance keys are POSIX-relative, always. str(Path) renders a
    # backslash separator on Windows, which would make the same template
    # produce a different hash document per platform and break any comparison
    # against the canonical representation. as_posix() is the serialization
    # boundary; the hashed BYTES are untouched.
    hashes = {
        f.relative_to(TEMPLATE).as_posix(): hashlib.sha256(f.read_bytes()).hexdigest()
        for f in sorted(TEMPLATE.rglob("*"))
        if f.is_file()
    }
    (dest / "template_hashes.json").write_text(json.dumps(hashes, indent=2))

    return dest


def fixed_recipe_unchanged(case) -> bool:
    """True when the trusted numerical recipe files are byte-identical."""
    case = Path(case)
    return all(
        (case / f).read_bytes() == (TEMPLATE / f).read_bytes()
        for f in FIXED_RECIPE_FILES
    )


def main() -> int:
    """CLI used by the orchestrator inside the OpenFOAM runtime."""
    import argparse

    ap = argparse.ArgumentParser(
        description="Generate a 2D forward-step case from a checked spec."
    )
    ap.add_argument("case", type=Path)
    ap.add_argument("--spec", type=Path, required=True)
    args = ap.parse_args()

    spec = ForwardStep2DSpec.from_dict(
        json.loads(args.spec.read_text(encoding="utf-8-sig"))
    )
    build(spec, args.case)

    print(
        json.dumps(
            {
                "case": str(args.case),
                "cells": spec.cells,
                "block_cells": spec.block_cells,
                "nx": spec.nx,
                "ny": spec.ny,
                "dx": spec.dx,
                "dy": spec.dy,
                "end_time": spec.end_time,
                "max_co": spec.max_co,
                "inlet_velocity": spec.velocity,
                "realized_inlet_Mach": spec.realized_mach,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
