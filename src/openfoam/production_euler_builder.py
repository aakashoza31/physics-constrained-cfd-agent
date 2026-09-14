from __future__ import annotations

import json
import math
import shutil
from pathlib import Path
from typing import Any

import gmsh


GAMMA = 1.4
R_AIR = 287.0


# =====================================================================
# FILE HELPERS
# =====================================================================

def _write(
    path: Path,
    text: str,
) -> None:

    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    path.write_text(
        text,
        encoding="utf-8",
    )


def _foam_header(
    foam_class: str,
    location: str,
    object_name: str,
) -> str:

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


# =====================================================================
# REQUEST VALIDATION
# =====================================================================

def _physics(
    cfd_request: dict[str, Any],
) -> tuple[
    float,
    float,
    float,
]:

    physics = cfd_request.get(
        "physics",
        {},
    )

    fluid = str(
        physics.get(
            "fluid",
            "",
        )
    ).strip().lower()

    if fluid not in {
        "air",
        "dry air",
    }:

        raise ValueError(
            "Production Euler backend currently supports air only."
        )


    regime = str(
        physics.get(
            "flow_regime",
            "",
        )
    ).strip().lower()

    if regime != "compressible":

        raise ValueError(
            "Production backend requires compressible flow."
        )


    turbulence = physics.get(
        "turbulence_model"
    )

    if (
        turbulence is not None
        and str(
            turbulence
        ).strip().lower()
        not in {
            "",
            "none",
            "null",
            "laminar",
        }
    ):

        raise ValueError(
            "Validated Euler pipeline does not use a turbulence model."
        )


    bc = physics.get(
        "boundary_conditions",
        {},
    )


    if (
        str(
            bc.get(
                "inlet_pressure_type",
                "",
            )
        ).strip().lower()
        != "total_pressure"
    ):

        raise ValueError(
            "Inlet pressure must be total_pressure."
        )


    if (
        str(
            bc.get(
                "inlet_temperature_type",
                "",
            )
        ).strip().lower()
        != "total_temperature"
    ):

        raise ValueError(
            "Inlet temperature must be total_temperature."
        )


    if (
        str(
            bc.get(
                "outlet_pressure_type",
                "",
            )
        ).strip().lower()
        != "static_pressure"
    ):

        raise ValueError(
            "Outlet pressure must be static_pressure."
        )


    if (
        str(
            bc.get(
                "wall_velocity_condition",
                "",
            )
        ).strip().lower()
        != "slip"
    ):

        raise ValueError(
            "Validated Euler pipeline requires slip walls."
        )


    if (
        str(
            bc.get(
                "wall_thermal_condition",
                "",
            )
        ).strip().lower()
        != "adiabatic"
    ):

        raise ValueError(
            "Validated Euler pipeline requires adiabatic walls."
        )


    p0 = float(
        bc[
            "inlet_pressure_pa"
        ]
    )

    T0 = float(
        bc[
            "inlet_temperature_k"
        ]
    )

    pout = float(
        bc[
            "outlet_pressure_pa"
        ]
    )


    if (
        p0 <= 0.0
        or T0 <= 0.0
        or pout <= 0.0
    ):

        raise ValueError(
            "Pressure and temperature inputs must be positive."
        )


    if pout >= p0:

        raise ValueError(
            "Outlet static pressure must be below inlet total pressure."
        )


    return (
        p0,
        T0,
        pout,
    )


# =====================================================================
# QUASI-1D STARTUP FIELD
#
# This is INITIALIZATION ONLY.
#
# It is deliberately separated from the agent evidence.
# No analytical target is inserted into the reasoning packet.
# =====================================================================

def area_mach_ratio(
    mach: float,
    gamma: float = GAMMA,
) -> float:

    term = (
        2.0
        / (
            gamma + 1.0
        )
        * (
            1.0
            + (
                gamma - 1.0
            )
            * 0.5
            * mach**2
        )
    )

    exponent = (
        (
            gamma + 1.0
        )
        / (
            2.0
            * (
                gamma - 1.0
            )
        )
    )

    return (
        (1.0 / mach)
        * term**exponent
    )


def solve_mach(
    area_ratio: float,
    *,
    supersonic: bool,
) -> float:

    if area_ratio <= 1.0 + 1.0e-9:
        return 1.0


    if supersonic:

        lo = 1.000001
        hi = 8.0

        for _ in range(
            100
        ):

            mid = 0.5 * (
                lo + hi
            )

            value = (
                area_mach_ratio(
                    mid
                )
            )

            if value < area_ratio:
                lo = mid
            else:
                hi = mid

    else:

        lo = 1.0e-5
        hi = 0.999999

        for _ in range(
            100
        ):

            mid = 0.5 * (
                lo + hi
            )

            value = (
                area_mach_ratio(
                    mid
                )
            )

            if value > area_ratio:
                lo = mid
            else:
                hi = mid


    return 0.5 * (
        lo + hi
    )


def quasi_1d_state(
    *,
    radius_m: float,
    throat_radius_m: float,
    p0_pa: float,
    T0_k: float,
    supersonic: bool,
    gamma: float = GAMMA,
    gas_constant: float = R_AIR,
) -> dict[str, float]:

    area_ratio = (
        radius_m
        / throat_radius_m
    ) ** 2

    mach = solve_mach(
        area_ratio,
        supersonic=(
            supersonic
        ),
    )

    temperature = (
        T0_k
        / (
            1.0
            + 0.5
            * (
                gamma - 1.0
            )
            * mach**2
        )
    )

    pressure = (
        p0_pa
        * (
            temperature
            / T0_k
        )
        ** (
            gamma
            / (
                gamma - 1.0
            )
        )
    )

    speed_of_sound = math.sqrt(
        gamma
        * gas_constant
        * temperature
    )

    velocity = (
        mach
        * speed_of_sound
    )

    return {
        "mach": mach,
        "pressure_pa": pressure,
        "temperature_k": temperature,
        "velocity_m_s": velocity,
    }


def _profile(
    manifest: dict[str, Any],
) -> list[
    tuple[
        float,
        float,
    ]
]:

    raw = manifest.get(
        "generic_profile",
        [],
    )

    profile = [
        (
            float(
                item["x_m"]
            ),
            float(
                item["radius_m"]
            ),
        )
        for item in raw
    ]

    if len(
        profile
    ) < 4:

        raise ValueError(
            "Geometry manifest does not contain a valid nozzle profile."
        )

    profile.sort(
        key=lambda item: item[0]
    )

    return profile


def _radius_at(
    profile: list[
        tuple[
            float,
            float,
        ]
    ],
    x: float,
) -> float:

    if x <= profile[0][0]:
        return profile[0][1]

    if x >= profile[-1][0]:
        return profile[-1][1]


    for (
        x0,
        r0,
    ), (
        x1,
        r1,
    ) in zip(
        profile[:-1],
        profile[1:],
    ):

        if (
            x0
            <= x
            <= x1
        ):

            if abs(
                x1 - x0
            ) < 1.0e-15:

                return min(
                    r0,
                    r1,
                )

            alpha = (
                (x - x0)
                / (
                    x1 - x0
                )
            )

            return (
                r0
                + alpha
                * (
                    r1 - r0
                )
            )


    return profile[-1][1]


def build_initialization_states(
    *,
    geometry_manifest: dict[str, Any],
    p0_pa: float,
    T0_k: float,
    axial_regions: int = 80,
) -> list[
    dict[
        str,
        float,
    ]
]:

    profile = _profile(
        geometry_manifest
    )

    verified = (
        geometry_manifest[
            "verified_geometry"
        ]
    )

    throat = (
        verified[
            "throat"
        ]
    )

    throat_radius = float(
        throat[
            "radius_m"
        ]
    )

    throat_start = float(
        throat[
            "x_start_m"
        ]
    )

    throat_end = float(
        throat[
            "x_end_m"
        ]
    )

    xmin = float(
        profile[0][0]
    )

    xmax = float(
        profile[-1][0]
    )

    dx = (
        xmax - xmin
    ) / axial_regions


    states = []

    for i in range(
        axial_regions
    ):

        x0 = (
            xmin
            + i * dx
        )

        x1 = (
            xmin
            + (
                i + 1
            )
            * dx
        )

        xc = 0.5 * (
            x0 + x1
        )

        radius = _radius_at(
            profile,
            xc,
        )


        if (
            throat_start
            <= xc
            <= throat_end
        ):

            mach_state = (
                quasi_1d_state(
                    radius_m=(
                        throat_radius
                    ),
                    throat_radius_m=(
                        throat_radius
                    ),
                    p0_pa=p0_pa,
                    T0_k=T0_k,
                    supersonic=False,
                )
            )

        else:

            mach_state = (
                quasi_1d_state(
                    radius_m=radius,
                    throat_radius_m=(
                        throat_radius
                    ),
                    p0_pa=p0_pa,
                    T0_k=T0_k,
                    supersonic=(
                        xc > throat_end
                    ),
                )
            )


        states.append(
            {
                "x0_m": x0,
                "x1_m": x1,
                "x_center_m": xc,
                "radius_m": radius,
                **mach_state,
            }
        )


    return states


# =====================================================================
# ACCEPTED MESH -> OPENFOAM MSH 2.2
# =====================================================================

def export_openfoam_msh22(
    *,
    best_mesh_path: Path,
    output_path: Path,
) -> Path:

    best_mesh_path = Path(
        best_mesh_path
    )

    output_path = Path(
        output_path
    )

    if not best_mesh_path.exists():

        raise FileNotFoundError(
            f"Accepted mesh missing: "
            f"{best_mesh_path}"
        )


    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )


    gmsh.initialize()

    try:

        gmsh.open(
            str(
                best_mesh_path
            )
        )

        gmsh.option.setNumber(
            "Mesh.MshFileVersion",
            2.2,
        )

        gmsh.option.setNumber(
            "Mesh.Binary",
            0,
        )

        gmsh.write(
            str(
                output_path
            )
        )

    finally:

        gmsh.finalize()


    if not output_path.exists():

        raise RuntimeError(
            "OpenFOAM-compatible MSH 2.2 export failed."
        )


    return output_path


# =====================================================================
# MAIN PRODUCTION CASE BUILDER
# =====================================================================

def build_production_euler_case(
    *,
    case_dir: Path,
    best_mesh_path: Path,
    geometry_manifest: dict[str, Any],
    cfd_request: dict[str, Any],
    setup_plan: Any | None = None,
    end_time_s: float = 5.0e-4,
) -> Path:

    case_dir = Path(
        case_dir
    ).resolve()

    best_mesh_path = Path(
        best_mesh_path
    ).resolve()


    p0, T0, pout = _physics(
        cfd_request
    )


    # ------------------------------------------------------------
    # Guard the production backend.
    # ------------------------------------------------------------

    if setup_plan is not None:

        solver = str(
            getattr(
                setup_plan,
                "solver",
                "",
            )
        )

        simulation_mode = str(
            getattr(
                setup_plan,
                "simulation_mode",
                "",
            )
        )

        treatment = str(
            getattr(
                setup_plan,
                "turbulence_treatment",
                "",
            )
        ).lower()


        if solver != "shockFluid":

            raise ValueError(
                "Production Euler backend requires shockFluid."
            )


        if simulation_mode != "transient":

            raise ValueError(
                "Production Euler backend requires transient operation."
            )


        if treatment not in {
            "laminar",
            "none",
        }:

            raise ValueError(
                "Production Euler backend requires laminar/no-turbulence treatment."
            )


    if case_dir.exists():

        shutil.rmtree(
            case_dir
        )


    (
        case_dir
        / "0"
    ).mkdir(
        parents=True
    )

    (
        case_dir
        / "constant"
    ).mkdir()

    (
        case_dir
        / "system"
    ).mkdir()


    mesh_file = (
        export_openfoam_msh22(
            best_mesh_path=(
                best_mesh_path
            ),
            output_path=(
                case_dir
                / "mesh.msh"
            ),
        )
    )


    states = (
        build_initialization_states(
            geometry_manifest=(
                geometry_manifest
            ),
            p0_pa=p0,
            T0_k=T0,
            axial_regions=80,
        )
    )


    initial = states[0]

    final = states[-1]


    profile = _profile(
        geometry_manifest
    )

    radial_extent = (
        1.20
        * max(
            radius
            for _, radius
            in profile
        )
    )


    # =================================================================
    # system/controlDict
    # =================================================================

    control = (
        _foam_header(
            "dictionary",
            "system",
            "controlDict",
        )
        + f"""
solver          shockFluid;

startFrom       startTime;
startTime       0;

stopAt          endTime;
endTime         {end_time_s:.12g};

deltaT          1e-08;

adjustTimeStep  yes;
maxCo           0.05;
maxDeltaT       5e-08;

writeControl    runTime;
writeInterval   2e-05;

purgeWrite      0;

writeFormat     ascii;
writePrecision  9;
writeCompression off;

timeFormat      general;
timePrecision   12;

runTimeModifiable true;
"""
    )

    _write(
        case_dir
        / "system"
        / "controlDict",
        control,
    )


    # =================================================================
    # system/fvSchemes
    # =================================================================

    fv_schemes = (
        _foam_header(
            "dictionary",
            "system",
            "fvSchemes",
        )
        + """
fluxScheme      Kurganov;

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
    default         none;
}

laplacianSchemes
{
    default         Gauss linear corrected;
}

interpolationSchemes
{
    default          linear;
    reconstruct(rho) vanLeer;
    reconstruct(U)   vanLeerV;
    reconstruct(T)   vanLeer;
}

snGradSchemes
{
    default         corrected;
}
"""
    )

    _write(
        case_dir
        / "system"
        / "fvSchemes",
        fv_schemes,
    )


    # =================================================================
    # system/fvSolution
    # =================================================================

    fv_solution = (
        _foam_header(
            "dictionary",
            "system",
            "fvSolution",
        )
        + """
solvers
{
    "rho.*"
    {
        solver          diagonal;
    }

    "(U|e).*"
    {
        solver          smoothSolver;
        smoother        symGaussSeidel;
        tolerance       1e-8;
        relTol          0;
    }
}

PIMPLE
{
    nOuterCorrectors 1;
}
"""
    )

    _write(
        case_dir
        / "system"
        / "fvSolution",
        fv_solution,
    )


    # =================================================================
    # constant/physicalProperties
    #
    # Inviscid perfect gas:
    #   mu = 0
    # =================================================================

    Cv = (
        R_AIR
        / (
            GAMMA - 1.0
        )
    )

    physical = (
        _foam_header(
            "dictionary",
            "constant",
            "physicalProperties",
        )
        + f"""
thermoType
{{
    type            hePsiThermo;
    mixture         pureMixture;
    transport       const;
    thermo          eConst;
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
        Cv              {Cv:.12g};
        Hf              0;
    }}

    transport
    {{
        mu              0;
        Pr              1;
    }}
}}
"""
    )

    _write(
        case_dir
        / "constant"
        / "physicalProperties",
        physical,
    )


    momentum = (
        _foam_header(
            "dictionary",
            "constant",
            "momentumTransport",
        )
        + """
simulationType laminar;
"""
    )

    _write(
        case_dir
        / "constant"
        / "momentumTransport",
        momentum,
    )


    # =================================================================
    # 0/p
    # =================================================================

    p_field = (
        _foam_header(
            "volScalarField",
            "0",
            "p",
        )
        + f"""
dimensions      [pressure];

internalField   uniform {initial['pressure_pa']:.12g};

boundaryField
{{
    inlet
    {{
        type            totalPressure;
        value           uniform {initial['pressure_pa']:.12g};
        p0              uniform {p0:.12g};
        rho             none;
        psi             psi;
        gamma           1.4;
    }}

    outlet
    {{
        type            waveTransmissive;
        field           p;
        psi             psi;
        fieldInf        {pout:.12g};
        gamma           1.4;
        lInf            0.1;
        value           uniform {pout:.12g};
    }}

    walls
    {{
        type            zeroGradient;
    }}

    #includeEtc "caseDicts/setConstraintTypes"
}}
"""
    )

    _write(
        case_dir
        / "0"
        / "p",
        p_field,
    )


    # =================================================================
    # 0/U
    # =================================================================

    U_field = (
        _foam_header(
            "volVectorField",
            "0",
            "U",
        )
        + f"""
dimensions      [velocity];

internalField   uniform ({initial['velocity_m_s']:.12g} 0 0);

boundaryField
{{
    inlet
    {{
        type            pressureDirectedInletOutletVelocity;
        phi             phi;
        rho             rho;
        inletDirection  uniform (1 0 0);
        value           uniform ({initial['velocity_m_s']:.12g} 0 0);
    }}

    outlet
    {{
        type            pressureInletOutletVelocity;
        value           uniform ({final['velocity_m_s']:.12g} 0 0);
    }}

    walls
    {{
        type            slip;
    }}

    #includeEtc "caseDicts/setConstraintTypes"
}}
"""
    )

    _write(
        case_dir
        / "0"
        / "U",
        U_field,
    )


    # =================================================================
    # 0/T
    # =================================================================

    T_field = (
        _foam_header(
            "volScalarField",
            "0",
            "T",
        )
        + f"""
dimensions      [temperature];

internalField   uniform {initial['temperature_k']:.12g};

boundaryField
{{
    inlet
    {{
        type            totalTemperature;
        value           uniform {initial['temperature_k']:.12g};
        T0              uniform {T0:.12g};
        rho             none;
        gamma           1.4;
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
"""
    )

    _write(
        case_dir
        / "0"
        / "T",
        T_field,
    )


    # =================================================================
    # system/setFieldsDict
    #
    # Piecewise approximation of a smooth quasi-1D startup field.
    #
    # OpenFOAM executor applies this BEFORE foamRun.
    # =================================================================

    region_blocks = []

    for state in states:

        region_blocks.append(
            f"""
    boxToCell
    {{
        box
        (
            {state['x0_m']:.12g}
            {-radial_extent:.12g}
            {-radial_extent:.12g}
        )
        (
            {state['x1_m']:.12g}
            {radial_extent:.12g}
            {radial_extent:.12g}
        );

        fieldValues
        (
            volScalarFieldValue p {state['pressure_pa']:.12g}
            volVectorFieldValue U ({state['velocity_m_s']:.12g} 0 0)
            volScalarFieldValue T {state['temperature_k']:.12g}
        );
    }}
"""
        )


    set_fields = (
        _foam_header(
            "dictionary",
            "system",
            "setFieldsDict",
        )
        + f"""
defaultFieldValues
(
    volScalarFieldValue p {initial['pressure_pa']:.12g}
    volVectorFieldValue U ({initial['velocity_m_s']:.12g} 0 0)
    volScalarFieldValue T {initial['temperature_k']:.12g}
);

regions
(
{''.join(region_blocks)}
);
"""
    )

    _write(
        case_dir
        / "system"
        / "setFieldsDict",
        set_fields,
    )


    # =================================================================
    # PROVENANCE
    # =================================================================

    record = {
        "backend": (
            "production_euler_nozzle_v1"
        ),

        "solver": (
            "shockFluid"
        ),

        "physics": {
            "fluid": "air",
            "gamma": GAMMA,
            "R_j_kg_k": R_AIR,
            "mu_pa_s": 0.0,
            "turbulence_model": None,
            "walls": (
                "slip_adiabatic"
            ),
            "inlet_total_pressure_pa": (
                p0
            ),
            "inlet_total_temperature_k": (
                T0
            ),
            "outlet_static_pressure_pa": (
                pout
            ),
        },

        "initialization": {
            "method": (
                "quasi_1d_piecewise_setFields"
            ),
            "axial_regions": (
                len(
                    states
                )
            ),
            "theory_assisted": True,
            "analytical_targets_exposed_to_agent": (
                False
            ),
            "note": (
                "Quasi-1D gas dynamics is used only to generate "
                "a physically consistent startup state. Agent "
                "acceptance/rejection uses OpenFOAM evidence."
            ),
        },

        "numerics": {
            "flux": "Kurganov",
            "reconstruction_rho": (
                "vanLeer"
            ),
            "reconstruction_U": (
                "vanLeerV"
            ),
            "reconstruction_T": (
                "vanLeer"
            ),
            "time_scheme": "Euler",
            "max_courant": 0.05,
            "initial_delta_t_s": (
                1.0e-8
            ),
            "max_delta_t_s": (
                5.0e-8
            ),
            "end_time_s": (
                end_time_s
            ),
        },

        "mesh_file": str(
            mesh_file
        ),
    }


    _write(
        case_dir
        / "production_case_manifest.json",
        json.dumps(
            record,
            indent=2,
        ),
    )


    return case_dir
