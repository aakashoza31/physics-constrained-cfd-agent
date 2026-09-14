from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from src.openfoam.production_euler_builder import (
    build_production_euler_case,
)

from src.openfoam.fluid_euler_builder import (
    build_pressure_based_fluid_case,
)

from src.openfoam.regime_policy import (
    NozzleRegime,
    build_regime_initialization_states,
)


def _header(
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


def _extract_conditions(
    request: dict[str, Any],
) -> tuple[
    float,
    float,
    float,
]:

    physics = request.get(
        "physics",
        {},
    )

    bc = physics.get(
        "boundary_conditions",
        {},
    )

    p0 = bc.get(
        "inlet_pressure_pa"
    )

    t0 = bc.get(
        "inlet_temperature_k"
    )

    pb = bc.get(
        "outlet_pressure_pa"
    )

    if (
        p0 is None
        or t0 is None
        or pb is None
    ):
        raise ValueError(
            "Regime-aware nozzle kernel requires "
            "inlet total pressure, inlet total temperature, "
            "and downstream/back pressure."
        )

    return (
        float(p0),
        float(t0),
        float(pb),
    )


def _write_initial_fields(
    *,
    case_dir: Path,
    policy,
    states,
    p0: float,
    t0: float,
    pb: float,
) -> None:

    first = states[0]
    last = states[-1]

    p_initial = float(
        first["pressure_pa"]
    )

    t_initial = float(
        first["temperature_k"]
    )

    u_initial = float(
        first["velocity_m_s"]
    )

    u_exit = float(
        last["velocity_m_s"]
    )

    if (
        policy.regime
        == NozzleRegime.SUPERSONIC_EXIT
    ):

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

    p_text = (
        _header(
            "volScalarField",
            "0",
            "p",
        )
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
        gamma           1.4;
    }}
{p_outlet}
    walls
    {{
        type            zeroGradient;
    }}

    #includeEtc "caseDicts/setConstraintTypes"
}}
"""
    )

    t_text = (
        _header(
            "volScalarField",
            "0",
            "T",
        )
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

    u_text = (
        _header(
            "volVectorField",
            "0",
            "U",
        )
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
"""
    )

    _write(
        case_dir / "0" / "p",
        p_text,
    )

    _write(
        case_dir / "0" / "T",
        t_text,
    )

    _write(
        case_dir / "0" / "U",
        u_text,
    )


def _write_setfields(
    *,
    case_dir: Path,
    geometry_manifest: dict[str, Any],
    states,
) -> None:

    profile = (
        geometry_manifest[
            "generic_profile"
        ]
    )

    max_radius = max(
        float(
            item["radius_m"]
        )
        for item in profile
    )

    extent = (
        1.25
        * max_radius
        + 1.0e-6
    )

    first = states[0]

    chunks: list[str] = []

    for state in states:

        chunks.append(
            f"""
    boxToCell
    {{
        box
        (
            {float(state["x0_m"]):.12g}
            {-extent:.12g}
            {-extent:.12g}
        )
        (
            {float(state["x1_m"]):.12g}
            {extent:.12g}
            {extent:.12g}
        );

        fieldValues
        (
            volScalarFieldValue p {float(state["pressure_pa"]):.12g}
            volVectorFieldValue U ({float(state["velocity_m_s"]):.12g} 0 0)
            volScalarFieldValue T {float(state["temperature_k"]):.12g}
        );
    }}
"""
        )

    text = (
        _header(
            "dictionary",
            "system",
            "setFieldsDict",
        )
        + f"""
defaultFieldValues
(
    volScalarFieldValue p {float(first["pressure_pa"]):.12g}
    volVectorFieldValue U ({float(first["velocity_m_s"]):.12g} 0 0)
    volScalarFieldValue T {float(first["temperature_k"]):.12g}
);

regions
(
{''.join(chunks)}
);
"""
    )

    _write(
        case_dir
        / "system"
        / "setFieldsDict",
        text,
    )


def _patch_control(
    case_dir: Path,
) -> None:

    path = (
        case_dir
        / "system"
        / "controlDict"
    )

    text = path.read_text(
        encoding="utf-8",
    )

    replacements = {
        "deltaT": "1e-09",
        "maxCo": "0.03",
        "maxDeltaT": "2e-08",
    }

    for key, value in replacements.items():

        pattern = (
            rf"(?m)^\s*"
            rf"{re.escape(key)}"
            rf"\s+[^;]+;"
        )

        replacement = (
            f"{key:<16}{value};"
        )

        text, count = re.subn(
            pattern,
            replacement,
            text,
            count=1,
        )

        if count != 1:
            raise RuntimeError(
                f"Could not patch {key} "
                "in controlDict."
            )

    path.write_text(
        text,
        encoding="utf-8",
    )


def build_regime_aware_euler_case(
    *,
    case_dir: Path,
    best_mesh_path: Path,
    geometry_manifest: dict[str, Any],
    cfd_request: dict[str, Any],
    setup_plan,
    end_time_s: float,
) -> Path:

    solver = str(
        getattr(
            setup_plan,
            "solver",
            "shockFluid",
        )
    ).strip()

    if solver == "fluid":
        return build_pressure_based_fluid_case(
            case_dir=case_dir,
            best_mesh_path=best_mesh_path,
            geometry_manifest=geometry_manifest,
            cfd_request=cfd_request,
            setup_plan=setup_plan,
            end_time_s=end_time_s,
        )

    if solver != "shockFluid":
        raise ValueError(
            "Unsupported regime-aware OpenFOAM backend: "
            f"{solver!r}."
        )

    # First reuse the already-tested production
    # thermophysical/numerical case construction.
    result = build_production_euler_case(
        case_dir=case_dir,
        best_mesh_path=best_mesh_path,
        geometry_manifest=(
            geometry_manifest
        ),
        cfd_request=cfd_request,
        setup_plan=setup_plan,
        end_time_s=end_time_s,
    )

    p0, t0, pb = (
        _extract_conditions(
            cfd_request
        )
    )

    policy, states = (
        build_regime_initialization_states(
            geometry_manifest=(
                geometry_manifest
            ),
            inlet_total_pressure_pa=p0,
            inlet_total_temperature_k=t0,
            outlet_back_pressure_pa=pb,
            axial_regions=96,
        )
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
        geometry_manifest=(
            geometry_manifest
        ),
        states=states,
    )

    _patch_control(
        case_dir
    )

    metadata = {
        "kernel_version":
            "regime-aware-nozzle-v1",
        "policy":
            policy.to_dict(),
        "initialization": {
            "regions": len(states),
            "theory_assisted": True,
            "theory_used_by_reasoning_agent": False,
            "minimum_pressure_pa": min(
                float(x["pressure_pa"])
                for x in states
            ),
            "minimum_temperature_k": min(
                float(x["temperature_k"])
                for x in states
            ),
            "maximum_mach": max(
                float(x["mach"])
                for x in states
            ),
        },
        "numerical_startup": {
            "initial_delta_t_s": 1.0e-9,
            "max_delta_t_s": 2.0e-8,
            "max_courant": 0.03,
        },
        "important_boundary_semantics": {
            "requested_back_pressure_pa": pb,
            "back_pressure_directly_imposed_at_exit": (
                policy.regime
                != NozzleRegime.SUPERSONIC_EXIT
            ),
        },
    }

    (
        case_dir
        / "regime_policy.json"
    ).write_text(
        json.dumps(
            metadata,
            indent=2,
        ),
        encoding="utf-8",
    )

    print(
        "Deterministic nozzle regime:",
        policy.regime.value,
    )

    print(
        "Back-pressure ratio:",
        f"{policy.back_pressure_ratio:.6f}",
    )

    print(
        "Subsonic choking threshold:",
        f"{policy.subsonic_choking_threshold_ratio:.6f}",
    )

    print(
        "Shock-at-exit threshold:",
        f"{policy.shock_at_exit_pressure_ratio:.6f}",
    )

    print(
        "Isentropic supersonic exit ratio:",
        f"{policy.isentropic_supersonic_exit_pressure_ratio:.6f}",
    )

    print(
        "Outlet pressure BC:",
        policy.outlet_pressure_bc,
    )

    print(
        "Initialization:",
        policy.initialization_mode,
    )

    return result
