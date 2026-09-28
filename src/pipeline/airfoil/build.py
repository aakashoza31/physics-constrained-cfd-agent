#!/usr/bin/env python3
"""Case generation and initialisation for Family 3.

Writes the OpenFOAM case from the FROZEN recipe. Every dictionary value below is
taken from src/families/airfoil/recipe.py; nothing is chosen here. Incidence
enters only through the freestream vector.

The mesh is NOT generated: the converted registered NASA grid is placed as
``<case>/<grid>.msh`` for gmshToFoam, and the case refuses to build if the
converted mesh is absent.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

from src.families.airfoil.recipe import (
    BOUNDARY_CONDITIONS,
    NUMERICS,
    RECIPE,
    SST_COEFFICIENTS,
)
from src.families.airfoil.spec import AirfoilSpec, NUT_INF
from src.pipeline.airfoil import p3d

HEADER = """/*--------------------------------*- C++ -*----------------------------------*\\
| GENERATED from the FROZEN Family-3 recipe (src/families/airfoil/recipe.py).  |
| Do not hand-edit: the generator is the provenance.                           |
\\*---------------------------------------------------------------------------*/
FoamFile
{{
    format      ascii;
    class       {cls};
    location    "{loc}";
    object      {obj};
}}

"""

WALL = p3d.PATCH_AIRFOIL
FARFIELD = p3d.PATCH_FARFIELD
EMPTY_PATCH = "frontAndBack"

#: Files whose byte-identity is the evidence that the numerical recipe was not
#: edited to obtain a result.
FIXED_RECIPE_FILES = ("system/fvSchemes", "system/fvSolution",
                      "constant/momentumTransport", "constant/physicalProperties")


def _field(cls: str, obj: str, dimensions: str, internal: str,
           boundary: Dict[str, str]) -> str:
    text = HEADER.format(cls=cls, loc="0", obj=obj)
    text += f"dimensions      {dimensions};\n\n"
    text += f"internalField   uniform {internal};\n\nboundaryField\n{{\n"
    for patch, body in boundary.items():
        text += f"    {patch}\n    {{\n"
        for line in body.strip().splitlines():
            text += f"        {line.strip()}\n"
        text += "    }\n"
    text += "}\n"
    return text


def initial_fields(spec: AirfoilSpec) -> Dict[str, str]:
    """0/ fields. Uniform freestream, zero gauge pressure, positive k and omega."""
    ux, uy, uz = spec.freestream
    fs = f"({ux:.12g} {uy:.12g} {uz:.12g})"

    return {
        "0/U": _field(
            "volVectorField", "U", "[0 1 -1 0 0 0 0]", fs,
            {
                WALL: "type            noSlip;",
                FARFIELD: f"type            freestreamVelocity;\nfreestreamValue uniform {fs};",
                EMPTY_PATCH: "type            empty;",
            },
        ),
        "0/p": _field(
            "volScalarField", "p", "[0 2 -2 0 0 0 0]", "0",
            {
                WALL: "type            zeroGradient;",
                FARFIELD: "type            freestreamPressure;\nfreestreamValue uniform 0;",
                EMPTY_PATCH: "type            empty;",
            },
        ),
        "0/k": _field(
            "volScalarField", "k", "[0 2 -2 0 0 0 0]", f"{spec.k_inf:.12g}",
            {
                WALL: "type            fixedValue;\nvalue           uniform 0;",
                FARFIELD: (
                    "type            inletOutlet;\n"
                    f"inletValue      uniform {spec.k_inf:.12g};\n"
                    f"value           uniform {spec.k_inf:.12g};"
                ),
                EMPTY_PATCH: "type            empty;",
            },
        ),
        "0/omega": _field(
            "volScalarField", "omega", "[0 0 -1 0 0 0 0]", f"{spec.omega_inf:.12g}",
            {
                WALL: (
                    "type            omegaWallFunction;\n"
                    "blended         false;\n"
                    f"beta1           {BOUNDARY_CONDITIONS['wall']['omegaWallFunction_beta1']};\n"
                    f"value           uniform {spec.omega_inf:.12g};"
                ),
                FARFIELD: (
                    "type            inletOutlet;\n"
                    f"inletValue      uniform {spec.omega_inf:.12g};\n"
                    f"value           uniform {spec.omega_inf:.12g};"
                ),
                EMPTY_PATCH: "type            empty;",
            },
        ),
        "0/nut": _field(
            "volScalarField", "nut", "[0 2 -1 0 0 0 0]", f"{NUT_INF:.12g}",
            {
                WALL: (
                    "type            nutLowReWallFunction;\n"
                    "value           uniform 0;"
                ),
                FARFIELD: (
                    "type            calculated;\n"
                    f"value           uniform {NUT_INF:.12g};"
                ),
                EMPTY_PATCH: "type            empty;",
            },
        ),
    }


def constant_files(spec: AirfoilSpec) -> Dict[str, str]:
    coeffs = "\n".join(
        f"        {k:<14}{'true' if v is True else 'false' if v is False else f'{v:.12g}'};"
        for k, v in SST_COEFFICIENTS.items()
    )
    return {
        "constant/physicalProperties": (
            HEADER.format(cls="dictionary", loc="constant", obj="physicalProperties")
            + "viscosityModel  constant;\n\n"
            + f"nu              [0 2 -1 0 0 0 0] {spec.nu:.12g};\n\n"
            + f"// rho = {spec.rho:g} kg/m^3, incompressible and isothermal:\n"
            + "// Mach and temperature are not solved in this family.\n"
        ),
        "constant/momentumTransport": (
            HEADER.format(cls="dictionary", loc="constant", obj="momentumTransport")
            + "simulationType  RAS;\n\nRAS\n{\n"
            + "    model           kOmegaSST;   // native Foundation v14\n"
            + "    turbulence      on;\n"
            + "    printCoeffs     on;\n\n"
            + "    // Native v14 coefficients, stated explicitly. NOT an SSTm\n"
            + "    // emulation; no transition model, curvature correction or\n"
            + "    // sustaining source is present.\n"
            + "    kOmegaSSTCoeffs\n    {\n" + coeffs + "\n    }\n}\n"
        ),
    }


def system_files(spec: AirfoilSpec) -> Dict[str, str]:
    n = NUMERICS
    return {
        "system/controlDict": (
            HEADER.format(cls="dictionary", loc="system", obj="controlDict")
            + "solver          incompressibleFluid;\n\n"
            + "startFrom       startTime;\nstartTime       0;\n"
            + "stopAt          endTime;\n"
            + f"endTime         {spec.end_iterations};\n"
            + "deltaT          1;\nwriteControl    timeStep;\n"
            + f"writeInterval   {spec.end_iterations};\n"
            + "purgeWrite      0;\nwriteFormat     ascii;\nwritePrecision  10;\n"
            + "runTimeModifiable false;\n"
        ),
        "system/fvSchemes": (
            HEADER.format(cls="dictionary", loc="system", obj="fvSchemes")
            + "ddtSchemes\n{\n    default         steadyState;\n}\n\n"
            + f"gradSchemes\n{{\n    default         {n['gradSchemes_default']};\n}}\n\n"
            + "divSchemes\n{\n    default         none;\n"
            + f"    div(phi,U)      {n['divScheme_U']};\n"
            + f"    div(phi,k)      {n['divScheme_k']};\n"
            + f"    div(phi,omega)  {n['divScheme_omega']};\n"
            + "    div((nuEff*dev2(T(grad(U))))) Gauss linear;\n}\n\n"
            + f"laplacianSchemes\n{{\n    default         {n['laplacianSchemes_default']};\n}}\n\n"
            + f"interpolationSchemes\n{{\n    default         {n['interpolationSchemes_default']};\n}}\n\n"
            + f"snGradSchemes\n{{\n    default         {n['snGradSchemes_default']};\n}}\n"
        ),
        "system/fvSolution": (
            HEADER.format(cls="dictionary", loc="system", obj="fvSolution")
            + "solvers\n{\n    p\n    {\n        solver          GAMG;\n"
            + "        smoother        GaussSeidel;\n        tolerance       1e-08;\n"
            + "        relTol          0.01;\n    }\n\n"
            + '    "(U|k|omega)"\n    {\n        solver          smoothSolver;\n'
            + "        smoother        symGaussSeidel;\n        tolerance       1e-09;\n"
            + "        relTol          0.01;\n    }\n}\n\n"
            + "SIMPLE\n{\n    nNonOrthogonalCorrectors 0;\n"
            + "    consistent      yes;\n    residualControl\n    {\n    }\n}\n\n"
            + "relaxationFactors\n{\n    fields\n    {\n"
            + f"        p               {n['relaxation_p']};\n    }}\n    equations\n    {{\n"
            + f"        U               {n['relaxation_U']};\n"
            + f"        k               {n['relaxation_k']};\n"
            + f"        omega           {n['relaxation_omega']};\n    }}\n}}\n"
        ),
    }


def build(spec: AirfoilSpec, destination, converted_mesh=None) -> Path:
    """Write the case. Refuses without the converted registered mesh."""
    destination = Path(destination)
    if destination.exists() and any(destination.iterdir()):
        raise FileExistsError(f"{destination} already exists and is not empty")
    if converted_mesh is None:
        raise FileNotFoundError(
            "airfoil: no converted registered mesh was supplied. Run the zero-CFD "
            "mesh audit first; this family never generates or substitutes geometry."
        )
    converted_mesh = Path(converted_mesh)
    if not converted_mesh.exists():
        raise FileNotFoundError(f"converted mesh {converted_mesh} is absent")

    for rel in ("0", "constant", "system"):
        (destination / rel).mkdir(parents=True, exist_ok=True)
    for rel, text in {**initial_fields(spec), **constant_files(spec),
                      **system_files(spec)}.items():
        (destination / rel).write_text(text, encoding="ascii")

    target = destination / converted_mesh.name
    target.write_bytes(converted_mesh.read_bytes())
    (destination / "spec.json").write_text(
        json.dumps(spec.to_dict(), indent=2), encoding="ascii"
    )
    (destination / "recipe.json").write_text(
        json.dumps(RECIPE.to_dict(), indent=2, default=str), encoding="ascii"
    )
    (destination / "MESH_CONVERSION.txt").write_text(
        "Converted registered NASA grid. Toolchain:\n"
        f"  {p3d.CONVERSION_TOOLCHAIN}\n\n"
        "Stage B, on the OpenFOAM runtime:\n"
        f"  gmshToFoam {converted_mesh.name}\n"
        "  (rewrite boundary: front/back -> empty, merged as 'frontAndBack')\n"
        "  checkMesh -allTopology -allGeometry\n",
        encoding="ascii",
    )
    return destination


def recipe_fingerprint(case) -> Dict[str, str]:
    """SHA256 of the frozen numerical files, as written."""
    import hashlib

    case = Path(case)
    out: Dict[str, str] = {}
    for rel in FIXED_RECIPE_FILES:
        path = case / rel
        if path.exists():
            out[rel] = hashlib.sha256(path.read_bytes()).hexdigest()
    return out
