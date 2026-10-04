"""Legacy prototype (CAD->Gmsh path, paper Appendix C "Prototype before the
registered contracts"); not the registered nozzle family; not used for any
reported result except that prototype record.

Prototype fluid-model case builder. Not imported by the registered family
runners or by src/pipeline.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from src.openfoam.production_euler_builder import export_openfoam_msh22
from src.openfoam.regime_policy import (
    GAMMA_AIR,
    R_AIR,
    NozzleRegime,
    build_regime_initialization_states,
)


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _header(foam_class: str, location: str, object_name: str) -> str:
    return f"""/*--------------------------------*- C++ -*----------------------------------*\\
| =========                 |                                                 |
| \\\\      /  F ield         | OpenFOAM: The Open Source CFD Toolbox           |
|  \\\\    /   O peration     | Version:  14                                    |
|   \\\\  /    A nd           |                                                 |
|    \\\\/     M anipulation  |                                                 |
\\*---------------------------------------------------------------------------*/
FoamFile
{{
    format      ascii;
    class       {foam_class};
    location    "{location}";
    object      {object_name};
}}
// ************************************************************************* //
"""


def _conditions(cfd_request: dict[str, Any]) -> tuple[float, float, float]:
    physics = cfd_request.get("physics", {})
    fluid = str(physics.get("fluid", "")).strip().lower()
    regime = str(physics.get("flow_regime", "")).strip().lower()

    if fluid not in {"air", "dry air"}:
        raise ValueError("Pressure-based Euler backend supports air only.")
    if regime != "compressible":
        raise ValueError("Pressure-based Euler backend requires compressible flow.")

    turbulence = physics.get("turbulence_model")
    if turbulence is not None and str(turbulence).strip().lower() not in {
        "", "none", "null", "laminar"
    }:
        raise ValueError("Pressure-based Euler backend is laminar/inviscid only.")

    bc = physics.get("boundary_conditions", {})
    if str(bc.get("inlet_pressure_type", "")).strip().lower() != "total_pressure":
        raise ValueError("Inlet pressure must be total_pressure.")
    if str(bc.get("inlet_temperature_type", "")).strip().lower() != "total_temperature":
        raise ValueError("Inlet temperature must be total_temperature.")
    if str(bc.get("wall_velocity_condition", "")).strip().lower() != "slip":
        raise ValueError("Pressure-based Euler backend requires slip walls.")
    if str(bc.get("wall_thermal_condition", "")).strip().lower() != "adiabatic":
        raise ValueError("Pressure-based Euler backend requires adiabatic walls.")

    p0 = float(bc["inlet_pressure_pa"])
    t0 = float(bc["inlet_temperature_k"])
    pb = float(bc["outlet_pressure_pa"])

    if p0 <= 0 or t0 <= 0 or pb <= 0 or pb >= p0:
        raise ValueError("Require positive p0/T0/pb with pb < p0.")

    return p0, t0, pb


def _validate_setup_plan(setup_plan: Any | None) -> None:
    if setup_plan is None:
        return

    solver = str(getattr(setup_plan, "solver", ""))
    mode = str(getattr(setup_plan, "simulation_mode", ""))
    treatment = str(getattr(setup_plan, "turbulence_treatment", "")).lower()

    if solver != "fluid":
        raise ValueError("Pressure-based Euler backend requires solver='fluid'.")
    if mode != "transient":
        raise ValueError("Pressure-based Euler backend requires transient operation.")
    if treatment not in {"laminar", "none"}:
        raise ValueError("Pressure-based Euler backend requires laminar treatment.")


def _write_initial_fields(
    *, case_dir: Path, policy: Any, states: list[dict[str, float]],
    p0: float, t0: float, pb: float,
) -> None:
    first = states[0]
    last = states[-1]
    p_initial = float(first["pressure_pa"])
    t_initial = float(first["temperature_k"])
    u_initial = float(first["velocity_m_s"])
    u_exit = float(last["velocity_m_s"])

    if policy.regime == NozzleRegime.SUPERSONIC_EXIT:
        p_outlet = """
    outlet
    {
        type            zeroGradient;
    }
"""
        u_outlet = """
    outlet
    {
        type            zeroGradient;
    }
"""
    else:
        p_outlet = f"""
    outlet
    {{
        type            fixedValue;
        value           uniform {pb:.12g};
    }}
"""
        u_outlet = f"""
    outlet
    {{
        type            pressureInletOutletVelocity;
        value           uniform ({u_exit:.12g} 0 0);
    }}
"""

    _write(
        case_dir / "0" / "p",
        _header("volScalarField", "0", "p")
        + f"""
dimensions      [pressure];

internalField   uniform {p_initial:.12g};

boundaryField
{{
    inlet
    {{
        type            totalPressure;
        value           uniform {p_initial:.12g};
        p0              uniform {p0:.12g};
        rho             none;
        psi             psi;
        gamma           {GAMMA_AIR:.12g};
    }}
{p_outlet}
    walls
    {{
        type            zeroGradient;
    }}

    #includeEtc "caseDicts/setConstraintTypes"
}}
""",
    )

    _write(
        case_dir / "0" / "T",
        _header("volScalarField", "0", "T")
        + f"""
dimensions      [temperature];

internalField   uniform {t_initial:.12g};

boundaryField
{{
    inlet
    {{
        type            totalTemperature;
        value           uniform {t_initial:.12g};
        T0              uniform {t0:.12g};
        rho             none;
        gamma           {GAMMA_AIR:.12g};
    }}

    outlet
    {{
        type            zeroGradient;
    }}

    walls
    {{
        type            zeroGradient;
    }}

    #includeEtc "caseDicts/setConstraintTypes"
}}
""",
    )

    _write(
        case_dir / "0" / "U",
        _header("volVectorField", "0", "U")
        + f"""
dimensions      [velocity];

internalField   uniform ({u_initial:.12g} 0 0);

boundaryField
{{
    inlet
    {{
        type            pressureDirectedInletOutletVelocity;
        phi             phi;
        rho             rho;
        inletDirection  uniform (1 0 0);
        value           uniform ({u_initial:.12g} 0 0);
    }}
{u_outlet}
    walls
    {{
        type            slip;
    }}

    #includeEtc "caseDicts/setConstraintTypes"
}}
""",
    )


def _write_setfields(
    *, case_dir: Path, geometry_manifest: dict[str, Any],
    states: list[dict[str, float]],
) -> None:
    profile = geometry_manifest["generic_profile"]
    max_radius = max(float(item["radius_m"]) for item in profile)
    extent = 1.25 * max_radius + 1.0e-6
    first = states[0]

    chunks: list[str] = []
    for state in states:
        chunks.append(
            f"""
    boxToCell
    {{
        box
        (
            {float(state['x0_m']):.12g}
            {-extent:.12g}
            {-extent:.12g}
        )
        (
            {float(state['x1_m']):.12g}
            {extent:.12g}
            {extent:.12g}
        );

        fieldValues
        (
            volScalarFieldValue p {float(state['pressure_pa']):.12g}
            volVectorFieldValue U ({float(state['velocity_m_s']):.12g} 0 0)
            volScalarFieldValue T {float(state['temperature_k']):.12g}
        );
    }}
"""
        )

    _write(
        case_dir / "system" / "setFieldsDict",
        _header("dictionary", "system", "setFieldsDict")
        + f"""
defaultFieldValues
(
    volScalarFieldValue p {float(first['pressure_pa']):.12g}
    volVectorFieldValue U ({float(first['velocity_m_s']):.12g} 0 0)
    volScalarFieldValue T {float(first['temperature_k']):.12g}
);

regions
(
{''.join(chunks)}
);
""",
    )


def build_pressure_based_fluid_case(
    *, case_dir: Path, best_mesh_path: Path,
    geometry_manifest: dict[str, Any], cfd_request: dict[str, Any],
    setup_plan: Any | None = None, end_time_s: float = 5.0e-4,
) -> Path:
    """Build the OpenFOAM Foundation v14 pressure-based `fluid` Euler case.

    The spatial/pressure numerics follow the Foundation v14 `fluid/nacaAirfoil`
    transonic tutorial. Transport is deliberately set to mu=0 so this remains
    an Euler/slip-wall comparison with the shockFluid backend.
    """

    case_dir = Path(case_dir).resolve()
    best_mesh_path = Path(best_mesh_path).resolve()
    p0, t0, pb = _conditions(cfd_request)
    _validate_setup_plan(setup_plan)

    if case_dir.exists():
        shutil.rmtree(case_dir)
    (case_dir / "0").mkdir(parents=True)
    (case_dir / "constant").mkdir()
    (case_dir / "system").mkdir()

    mesh_file = export_openfoam_msh22(
        best_mesh_path=best_mesh_path,
        output_path=case_dir / "mesh.msh",
    )

    policy, states = build_regime_initialization_states(
        geometry_manifest=geometry_manifest,
        inlet_total_pressure_pa=p0,
        inlet_total_temperature_k=t0,
        outlet_back_pressure_pa=pb,
        axial_regions=96,
    )

    # Pressure-based fluid solver control.  Conservative values are kept
    # identical to the successful shockFluid startup envelope.
    _write(
        case_dir / "system" / "controlDict",
        _header("dictionary", "system", "controlDict")
        + f"""
solver          fluid;

startFrom       startTime;
startTime       0;

stopAt          endTime;
endTime         {end_time_s:.12g};

deltaT          1e-09;

adjustTimeStep  yes;
maxCo           0.03;
maxDeltaT       2e-08;

writeControl    runTime;
writeInterval   1e-05;

purgeWrite      0;
writeFormat     ascii;
writePrecision  9;
writeCompression off;
timeFormat      general;
timePrecision   12;
runTimeModifiable true;
""",
    )

    # Foundation v14 tutorials/fluid/nacaAirfoil based discretisation.
    _write(
        case_dir / "system" / "fvSchemes",
        _header("dictionary", "system", "fvSchemes")
        + """
ddtSchemes
{
    default         Euler;
}

gradSchemes
{
    default         Gauss linear;
}

divSchemes
{
    default                         none;
    div(phi,U)                      Gauss limitedLinearV 1;
    div(phi,e)                      Gauss limitedLinear 1;
    div(phid,p)                     Gauss limitedLinear 1;
    div(phi,K)                      Gauss limitedLinear 1;
    div(phi,(p|rho))                Gauss limitedLinear 1;
    div(((rho*nuEff)*dev2(T(grad(U))))) Gauss linear;
}

laplacianSchemes
{
    default         Gauss linear limited corrected 0.5;
}

interpolationSchemes
{
    default         linear;
}

snGradSchemes
{
    default         corrected;
}
""",
    )

    _write(
        case_dir / "system" / "fvSolution",
        _header("dictionary", "system", "fvSolution")
        + """
solvers
{
    "rho.*"
    {
        solver          diagonal;
    }

    "p.*"
    {
        solver          PBiCGStab;
        preconditioner  DILU;
        tolerance       1e-12;
        relTol          0;
    }

    "(U|e).*"
    {
        $p;
        tolerance       1e-9;
    }
}

PIMPLE
{
    nOuterCorrectors         1;
    nCorrectors              2;
    nNonOrthogonalCorrectors 0;
    transonic                yes;
}

relaxationFactors
{
    equations
    {
        ".*"            1;
    }
}
""",
    )

    cp = GAMMA_AIR * R_AIR / (GAMMA_AIR - 1.0)
    _write(
        case_dir / "constant" / "physicalProperties",
        _header("dictionary", "constant", "physicalProperties")
        + f"""
thermoType
{{
    type            hePsiThermo;
    mixture         pureMixture;
    transport       const;
    thermo          hConst;
    equationOfState perfectGas;
    specie          specie;
    energy          sensibleInternalEnergy;
}}

mixture
{{
    specie
    {{
        molWeight       28.97025;
    }}

    thermodynamics
    {{
        Cp              {cp:.12g};
        hf              0;
    }}

    transport
    {{
        mu              0;
        Pr              1;
    }}
}}
""",
    )

    _write(
        case_dir / "constant" / "momentumTransport",
        _header("dictionary", "constant", "momentumTransport")
        + """
simulationType laminar;
""",
    )

    _write_initial_fields(
        case_dir=case_dir,
        policy=policy,
        states=states,
        p0=p0,
        t0=t0,
        pb=pb,
    )
    _write_setfields(
        case_dir=case_dir,
        geometry_manifest=geometry_manifest,
        states=states,
    )

    metadata = {
        "backend": "pressure_based_fluid_euler_nozzle_v1",
        "solver": "fluid",
        "openfoam_distribution": "Foundation v14",
        "regime_policy": policy.to_dict(),
        "physics": {
            "fluid": "air",
            "gamma": GAMMA_AIR,
            "R_j_kg_k": R_AIR,
            "mu_pa_s": 0.0,
            "turbulence_model": None,
            "walls": "slip_adiabatic",
            "inlet_total_pressure_pa": p0,
            "inlet_total_temperature_k": t0,
            "requested_back_pressure_pa": pb,
            "back_pressure_directly_imposed_at_exit": (
                policy.regime != NozzleRegime.SUPERSONIC_EXIT
            ),
        },
        "initialization": {
            "method": "regime_consistent_quasi_1d_piecewise_setFields",
            "axial_regions": len(states),
            "theory_assisted": True,
            "theory_used_by_reasoning_agent": False,
        },
        "numerics": {
            "formulation": "pressure_based_transonic_PIMPLE",
            "transonic": True,
            "time_scheme": "Euler",
            "initial_delta_t_s": 1.0e-9,
            "max_delta_t_s": 2.0e-8,
            "max_courant": 0.03,
            "end_time_s": end_time_s,
            "source_template": "OpenFOAM-14 tutorials/fluid/nacaAirfoil",
        },
        "mesh_file": str(mesh_file),
    }

    _write(
        case_dir / "production_case_manifest.json",
        json.dumps(metadata, indent=2),
    )
    _write(
        case_dir / "regime_policy.json",
        json.dumps(
            {
                "kernel_version": "regime-aware-nozzle-v1",
                "policy": policy.to_dict(),
                "initialization": {
                    "regions": len(states),
                    "theory_assisted": True,
                    "theory_used_by_reasoning_agent": False,
                },
                "numerical_startup": {
                    "initial_delta_t_s": 1.0e-9,
                    "max_delta_t_s": 2.0e-8,
                    "max_courant": 0.03,
                },
            },
            indent=2,
        ),
    )

    print("Deterministic nozzle regime:", policy.regime.value)
    print("Pressure-based backend: fluid / transonic PIMPLE")
    print("Outlet pressure BC:", policy.outlet_pressure_bc)
    print("Initialization:", policy.initialization_mode)

    return case_dir
