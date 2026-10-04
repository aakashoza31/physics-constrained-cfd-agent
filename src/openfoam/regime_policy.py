"""Legacy prototype (CAD->Gmsh path, paper Appendix C "Prototype before the
registered contracts"); not the registered nozzle family; not used for any
reported result except that prototype record.

Prototype nozzle-regime policy. Not imported by the registered family runners
or by src/pipeline.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
import math
from typing import Any


GAMMA_AIR = 1.4
R_AIR = 287.0


class NozzleRegime(str, Enum):
    SUBSONIC = "SUBSONIC"
    CHOKED_INTERNAL_SHOCK = "CHOKED_INTERNAL_SHOCK"
    SUPERSONIC_EXIT = "SUPERSONIC_EXIT"


@dataclass(frozen=True)
class NozzleRegimePolicy:
    regime: NozzleRegime

    back_pressure_ratio: float
    exit_area_ratio: float

    subsonic_choking_threshold_ratio: float
    isentropic_supersonic_exit_pressure_ratio: float
    shock_at_exit_pressure_ratio: float

    subsonic_exit_mach_at_choking: float
    supersonic_exit_mach: float

    outlet_pressure_bc: str
    outlet_velocity_bc: str
    outlet_temperature_bc: str

    initialization_mode: str

    shock_x_m: float | None = None
    shock_area_ratio: float | None = None
    downstream_total_pressure_ratio: float | None = None

    explanation: str = ""

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["regime"] = self.regime.value
        return result


def area_mach_ratio(
    mach: float,
    gamma: float = GAMMA_AIR,
) -> float:

    if mach <= 0.0:
        raise ValueError(
            "Mach number must be positive."
        )

    factor = (
        2.0
        / (gamma + 1.0)
        * (
            1.0
            + 0.5
            * (gamma - 1.0)
            * mach**2
        )
    )

    exponent = (
        (gamma + 1.0)
        / (
            2.0
            * (gamma - 1.0)
        )
    )

    return (
        factor**exponent
        / mach
    )


def solve_area_mach(
    area_ratio: float,
    *,
    supersonic: bool,
    gamma: float = GAMMA_AIR,
) -> float:

    if area_ratio < 1.0:
        raise ValueError(
            "A/A* must be >= 1."
        )

    if abs(area_ratio - 1.0) < 1.0e-12:
        return 1.0

    if supersonic:

        lo = 1.0 + 1.0e-10
        hi = 2.0

        while (
            area_mach_ratio(
                hi,
                gamma,
            )
            < area_ratio
        ):
            hi *= 1.5

            if hi > 50.0:
                raise RuntimeError(
                    "Could not bracket supersonic Mach."
                )

        for _ in range(120):

            mid = 0.5 * (
                lo + hi
            )

            value = area_mach_ratio(
                mid,
                gamma,
            )

            if value < area_ratio:
                lo = mid
            else:
                hi = mid

    else:

        lo = 1.0e-8
        hi = 1.0 - 1.0e-10

        for _ in range(120):

            mid = 0.5 * (
                lo + hi
            )

            value = area_mach_ratio(
                mid,
                gamma,
            )

            if value > area_ratio:
                lo = mid
            else:
                hi = mid

    return 0.5 * (
        lo + hi
    )


def isentropic_pressure_ratio(
    mach: float,
    gamma: float = GAMMA_AIR,
) -> float:

    return (
        1.0
        + 0.5
        * (gamma - 1.0)
        * mach**2
    ) ** (
        -gamma
        / (gamma - 1.0)
    )


def mach_from_pressure_ratio(
    p_over_p0: float,
    gamma: float = GAMMA_AIR,
) -> float:

    if not (
        0.0
        < p_over_p0
        <= 1.0
    ):
        raise ValueError(
            "Static/total pressure ratio "
            "must be in (0, 1]."
        )

    value = (
        2.0
        / (gamma - 1.0)
        * (
            p_over_p0
            ** (
                -(gamma - 1.0)
                / gamma
            )
            - 1.0
        )
    )

    return math.sqrt(
        max(
            value,
            0.0,
        )
    )


def normal_shock_downstream_mach(
    mach1: float,
    gamma: float = GAMMA_AIR,
) -> float:

    if mach1 <= 1.0:
        raise ValueError(
            "Normal shock upstream Mach "
            "must exceed one."
        )

    numerator = (
        1.0
        + 0.5
        * (gamma - 1.0)
        * mach1**2
    )

    denominator = (
        gamma
        * mach1**2
        - 0.5
        * (gamma - 1.0)
    )

    return math.sqrt(
        numerator
        / denominator
    )


def normal_shock_static_pressure_ratio(
    mach1: float,
    gamma: float = GAMMA_AIR,
) -> float:

    return (
        1.0
        + (
            2.0
            * gamma
            / (gamma + 1.0)
        )
        * (
            mach1**2
            - 1.0
        )
    )


def normal_shock_total_pressure_ratio(
    mach1: float,
    gamma: float = GAMMA_AIR,
) -> float:

    mach2 = (
        normal_shock_downstream_mach(
            mach1,
            gamma,
        )
    )

    p1_p01 = (
        isentropic_pressure_ratio(
            mach1,
            gamma,
        )
    )

    p2_p1 = (
        normal_shock_static_pressure_ratio(
            mach1,
            gamma,
        )
    )

    p2_p02 = (
        isentropic_pressure_ratio(
            mach2,
            gamma,
        )
    )

    return (
        p1_p01
        * p2_p1
        / p2_p02
    )


def isentropic_state(
    *,
    mach: float,
    total_pressure_pa: float,
    total_temperature_k: float,
    gamma: float = GAMMA_AIR,
    gas_constant: float = R_AIR,
) -> dict[str, float]:

    temperature = (
        total_temperature_k
        / (
            1.0
            + 0.5
            * (gamma - 1.0)
            * mach**2
        )
    )

    pressure = (
        total_pressure_pa
        * isentropic_pressure_ratio(
            mach,
            gamma,
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

    density = (
        pressure
        / (
            gas_constant
            * temperature
        )
    )

    return {
        "mach": mach,
        "pressure_pa": pressure,
        "temperature_k": temperature,
        "velocity_m_s": velocity,
        "density_kg_m3": density,
    }


def _geometry(
    manifest: dict[str, Any],
) -> dict[str, Any]:

    raw_profile = manifest.get(
        "generic_profile"
    )

    if not isinstance(
        raw_profile,
        list,
    ) or len(
        raw_profile
    ) < 2:
        raise ValueError(
            "geometry_manifest requires generic_profile."
        )

    profile = sorted(
        [
            {
                "x_m": float(
                    item["x_m"]
                ),
                "radius_m": float(
                    item["radius_m"]
                ),
            }
            for item in raw_profile
        ],
        key=lambda item: item["x_m"],
    )

    throat_radius = min(
        item["radius_m"]
        for item in profile
    )

    throat_info = (
        manifest
        .get(
            "verified_geometry",
            {},
        )
        .get(
            "throat",
            {},
        )
    )

    if throat_info:

        throat_start = float(
            throat_info[
                "x_start_m"
            ]
        )

        throat_end = float(
            throat_info[
                "x_end_m"
            ]
        )

        throat_radius = float(
            throat_info[
                "radius_m"
            ]
        )

    else:

        throat_points = [
            item["x_m"]
            for item in profile
            if abs(
                item["radius_m"]
                - throat_radius
            )
            < 1.0e-10
        ]

        throat_start = min(
            throat_points
        )

        throat_end = max(
            throat_points
        )

    return {
        "profile": profile,
        "x_start_m": profile[0]["x_m"],
        "x_end_m": profile[-1]["x_m"],
        "throat_start_m": throat_start,
        "throat_end_m": throat_end,
        "throat_radius_m": throat_radius,
        "exit_radius_m": profile[-1][
            "radius_m"
        ],
    }


def radius_at(
    profile: list[dict[str, float]],
    x_m: float,
) -> float:

    if x_m <= profile[0]["x_m"]:
        return profile[0][
            "radius_m"
        ]

    if x_m >= profile[-1]["x_m"]:
        return profile[-1][
            "radius_m"
        ]

    for left, right in zip(
        profile[:-1],
        profile[1:],
    ):

        x0 = left["x_m"]
        x1 = right["x_m"]

        if x0 <= x_m <= x1:

            if abs(
                x1 - x0
            ) < 1.0e-15:
                return left[
                    "radius_m"
                ]

            fraction = (
                (x_m - x0)
                / (x1 - x0)
            )

            return (
                left["radius_m"]
                + fraction
                * (
                    right["radius_m"]
                    - left["radius_m"]
                )
            )

    raise RuntimeError(
        "Could not interpolate nozzle radius."
    )


def _shock_exit_pressure_ratio(
    shock_area_ratio: float,
    exit_area_ratio: float,
    gamma: float,
) -> tuple[
    float,
    dict[str, float],
]:

    mach1 = solve_area_mach(
        shock_area_ratio,
        supersonic=True,
        gamma=gamma,
    )

    mach2 = (
        normal_shock_downstream_mach(
            mach1,
            gamma,
        )
    )

    p02_p01 = (
        normal_shock_total_pressure_ratio(
            mach1,
            gamma,
        )
    )

    downstream_astar_over_at = (
        shock_area_ratio
        / area_mach_ratio(
            mach2,
            gamma,
        )
    )

    exit_over_downstream_astar = (
        exit_area_ratio
        / downstream_astar_over_at
    )

    exit_mach = solve_area_mach(
        exit_over_downstream_astar,
        supersonic=False,
        gamma=gamma,
    )

    exit_pressure_ratio = (
        p02_p01
        * isentropic_pressure_ratio(
            exit_mach,
            gamma,
        )
    )

    return (
        exit_pressure_ratio,
        {
            "mach1": mach1,
            "mach2": mach2,
            "p02_p01": p02_p01,
            "downstream_astar_over_at":
                downstream_astar_over_at,
            "exit_mach": exit_mach,
        },
    )


def _find_internal_shock(
    *,
    back_pressure_ratio: float,
    exit_area_ratio: float,
    gamma: float,
) -> dict[str, float]:

    lo = 1.0 + 1.0e-7
    hi = exit_area_ratio

    details: dict[
        str,
        float,
    ] | None = None

    for _ in range(120):

        mid = 0.5 * (
            lo + hi
        )

        exit_ratio, local = (
            _shock_exit_pressure_ratio(
                mid,
                exit_area_ratio,
                gamma,
            )
        )

        details = local

        # Moving shock downstream lowers
        # the resulting exit pressure.
        if (
            exit_ratio
            > back_pressure_ratio
        ):
            lo = mid
        else:
            hi = mid

    shock_area_ratio = (
        0.5
        * (
            lo + hi
        )
    )

    exit_ratio, details = (
        _shock_exit_pressure_ratio(
            shock_area_ratio,
            exit_area_ratio,
            gamma,
        )
    )

    details = dict(
        details
    )

    details[
        "shock_area_ratio"
    ] = shock_area_ratio

    details[
        "predicted_exit_pressure_ratio"
    ] = exit_ratio

    return details


def _shock_x(
    *,
    geometry: dict[str, Any],
    shock_area_ratio: float,
) -> float:

    profile = geometry[
        "profile"
    ]

    rt = geometry[
        "throat_radius_m"
    ]

    target_radius = (
        rt
        * math.sqrt(
            shock_area_ratio
        )
    )

    throat_end = geometry[
        "throat_end_m"
    ]

    downstream = [
        item
        for item in profile
        if item["x_m"] >= throat_end
    ]

    if not downstream:
        raise ValueError(
            "No diverging geometry after throat."
        )

    for left, right in zip(
        downstream[:-1],
        downstream[1:],
    ):

        r0 = left[
            "radius_m"
        ]
        r1 = right[
            "radius_m"
        ]

        low = min(
            r0,
            r1,
        )

        high = max(
            r0,
            r1,
        )

        if (
            low
            <= target_radius
            <= high
        ):

            if abs(
                r1 - r0
            ) < 1.0e-15:
                return left[
                    "x_m"
                ]

            fraction = (
                (
                    target_radius
                    - r0
                )
                / (
                    r1 - r0
                )
            )

            return (
                left["x_m"]
                + fraction
                * (
                    right["x_m"]
                    - left["x_m"]
                )
            )

    return geometry[
        "x_end_m"
    ]


def classify_nozzle_regime(
    *,
    geometry_manifest: dict[str, Any],
    inlet_total_pressure_pa: float,
    outlet_back_pressure_pa: float,
    gamma: float = GAMMA_AIR,
) -> NozzleRegimePolicy:

    p0 = float(
        inlet_total_pressure_pa
    )

    pb = float(
        outlet_back_pressure_pa
    )

    if p0 <= 0.0:
        raise ValueError(
            "Inlet total pressure must be positive."
        )

    if not (
        0.0
        < pb
        < p0
    ):
        raise ValueError(
            "Back pressure must satisfy 0 < pb < p0 "
            "for the current nozzle kernel."
        )

    geometry = _geometry(
        geometry_manifest
    )

    rt = geometry[
        "throat_radius_m"
    ]

    re = geometry[
        "exit_radius_m"
    ]

    if re <= rt:
        raise ValueError(
            "Prototype C-D nozzle kernel requires "
            "exit radius > throat radius."
        )

    exit_area_ratio = (
        re / rt
    ) ** 2

    mach_exit_sub = solve_area_mach(
        exit_area_ratio,
        supersonic=False,
        gamma=gamma,
    )

    mach_exit_sup = solve_area_mach(
        exit_area_ratio,
        supersonic=True,
        gamma=gamma,
    )

    subsonic_threshold = (
        isentropic_pressure_ratio(
            mach_exit_sub,
            gamma,
        )
    )

    supersonic_exit_ratio = (
        isentropic_pressure_ratio(
            mach_exit_sup,
            gamma,
        )
    )

    shock_at_exit_ratio = (
        supersonic_exit_ratio
        * normal_shock_static_pressure_ratio(
            mach_exit_sup,
            gamma,
        )
    )

    beta = (
        pb / p0
    )

    tolerance = 1.0e-6

    if (
        beta
        >= (
            subsonic_threshold
            - tolerance
        )
    ):

        return NozzleRegimePolicy(
            regime=(
                NozzleRegime.SUBSONIC
            ),
            back_pressure_ratio=beta,
            exit_area_ratio=(
                exit_area_ratio
            ),
            subsonic_choking_threshold_ratio=(
                subsonic_threshold
            ),
            isentropic_supersonic_exit_pressure_ratio=(
                supersonic_exit_ratio
            ),
            shock_at_exit_pressure_ratio=(
                shock_at_exit_ratio
            ),
            subsonic_exit_mach_at_choking=(
                mach_exit_sub
            ),
            supersonic_exit_mach=(
                mach_exit_sup
            ),
            outlet_pressure_bc=(
                "fixedValue"
            ),
            outlet_velocity_bc=(
                "pressureInletOutletVelocity"
            ),
            outlet_temperature_bc=(
                "zeroGradient"
            ),
            initialization_mode=(
                "SUBSONIC_ISENTROPIC"
            ),
            explanation=(
                "Back pressure is above the choking threshold. "
                "The nozzle is initialized on the subsonic branch "
                "and static outlet pressure is imposed."
            ),
        )

    if (
        beta
        > (
            shock_at_exit_ratio
            + tolerance
        )
    ):

        shock = (
            _find_internal_shock(
                back_pressure_ratio=beta,
                exit_area_ratio=(
                    exit_area_ratio
                ),
                gamma=gamma,
            )
        )

        shock_x_m = (
            _shock_x(
                geometry=geometry,
                shock_area_ratio=(
                    shock[
                        "shock_area_ratio"
                    ]
                ),
            )
        )

        return NozzleRegimePolicy(
            regime=(
                NozzleRegime.CHOKED_INTERNAL_SHOCK
            ),
            back_pressure_ratio=beta,
            exit_area_ratio=(
                exit_area_ratio
            ),
            subsonic_choking_threshold_ratio=(
                subsonic_threshold
            ),
            isentropic_supersonic_exit_pressure_ratio=(
                supersonic_exit_ratio
            ),
            shock_at_exit_pressure_ratio=(
                shock_at_exit_ratio
            ),
            subsonic_exit_mach_at_choking=(
                mach_exit_sub
            ),
            supersonic_exit_mach=(
                mach_exit_sup
            ),
            outlet_pressure_bc=(
                "fixedValue"
            ),
            outlet_velocity_bc=(
                "pressureInletOutletVelocity"
            ),
            outlet_temperature_bc=(
                "zeroGradient"
            ),
            initialization_mode=(
                "QUASI_1D_NORMAL_SHOCK"
            ),
            shock_x_m=shock_x_m,
            shock_area_ratio=(
                shock[
                    "shock_area_ratio"
                ]
            ),
            downstream_total_pressure_ratio=(
                shock[
                    "p02_p01"
                ]
            ),
            explanation=(
                "Back pressure requires a choked nozzle with "
                "an internal normal-shock-compatible startup."
            ),
        )

    return NozzleRegimePolicy(
        regime=(
            NozzleRegime.SUPERSONIC_EXIT
        ),
        back_pressure_ratio=beta,
        exit_area_ratio=(
            exit_area_ratio
        ),
        subsonic_choking_threshold_ratio=(
            subsonic_threshold
        ),
        isentropic_supersonic_exit_pressure_ratio=(
            supersonic_exit_ratio
        ),
        shock_at_exit_pressure_ratio=(
            shock_at_exit_ratio
        ),
        subsonic_exit_mach_at_choking=(
            mach_exit_sub
        ),
        supersonic_exit_mach=(
            mach_exit_sup
        ),
        outlet_pressure_bc=(
            "zeroGradient"
        ),
        outlet_velocity_bc=(
            "zeroGradient"
        ),
        outlet_temperature_bc=(
            "zeroGradient"
        ),
        initialization_mode=(
            "CHOKED_ISENTROPIC"
        ),
        explanation=(
            "The exit is supersonic. The requested back pressure "
            "is used to classify the regime but is not imposed on "
            "the nozzle exit plane. All exit characteristics leave "
            "the nozzle domain."
        ),
    )


def build_regime_initialization_states(
    *,
    geometry_manifest: dict[str, Any],
    inlet_total_pressure_pa: float,
    inlet_total_temperature_k: float,
    outlet_back_pressure_pa: float,
    axial_regions: int = 96,
    gamma: float = GAMMA_AIR,
    gas_constant: float = R_AIR,
) -> tuple[
    NozzleRegimePolicy,
    list[dict[str, float | str]],
]:

    if axial_regions < 16:
        raise ValueError(
            "Use at least 16 axial initialization regions."
        )

    geometry = _geometry(
        geometry_manifest
    )

    policy = classify_nozzle_regime(
        geometry_manifest=(
            geometry_manifest
        ),
        inlet_total_pressure_pa=(
            inlet_total_pressure_pa
        ),
        outlet_back_pressure_pa=(
            outlet_back_pressure_pa
        ),
        gamma=gamma,
    )

    profile = geometry[
        "profile"
    ]

    x_start = geometry[
        "x_start_m"
    ]

    x_end = geometry[
        "x_end_m"
    ]

    throat_start = geometry[
        "throat_start_m"
    ]

    throat_end = geometry[
        "throat_end_m"
    ]

    rt = geometry[
        "throat_radius_m"
    ]

    re = geometry[
        "exit_radius_m"
    ]

    at = math.pi * rt**2
    ae = math.pi * re**2

    p0 = float(
        inlet_total_pressure_pa
    )

    t0 = float(
        inlet_total_temperature_k
    )

    pb = float(
        outlet_back_pressure_pa
    )

    subsonic_astar = None
    downstream_astar = None
    downstream_p0 = None

    if (
        policy.regime
        == NozzleRegime.SUBSONIC
    ):

        exit_mach = (
            mach_from_pressure_ratio(
                pb / p0,
                gamma,
            )
        )

        if exit_mach >= 1.0:
            raise RuntimeError(
                "Subsonic policy produced Mach >= 1."
            )

        subsonic_astar = (
            ae
            / area_mach_ratio(
                exit_mach,
                gamma,
            )
        )

    elif (
        policy.regime
        == NozzleRegime.CHOKED_INTERNAL_SHOCK
    ):

        assert (
            policy.shock_area_ratio
            is not None
        )

        shock_details = (
            _find_internal_shock(
                back_pressure_ratio=(
                    pb / p0
                ),
                exit_area_ratio=(
                    policy.exit_area_ratio
                ),
                gamma=gamma,
            )
        )

        downstream_astar = (
            at
            * shock_details[
                "downstream_astar_over_at"
            ]
        )

        downstream_p0 = (
            p0
            * shock_details[
                "p02_p01"
            ]
        )

    dx = (
        (x_end - x_start)
        / axial_regions
    )

    states: list[
        dict[str, float | str]
    ] = []

    for index in range(
        axial_regions
    ):

        x0 = (
            x_start
            + index * dx
        )

        x1 = (
            x_start
            + (index + 1) * dx
        )

        x = 0.5 * (
            x0 + x1
        )

        radius = radius_at(
            profile,
            x,
        )

        area = (
            math.pi
            * radius**2
        )

        branch = ""
        local_p0 = p0

        if (
            policy.regime
            == NozzleRegime.SUBSONIC
        ):

            assert (
                subsonic_astar
                is not None
            )

            mach = solve_area_mach(
                area / subsonic_astar,
                supersonic=False,
                gamma=gamma,
            )

            branch = "subsonic"

        elif (
            policy.regime
            == NozzleRegime.SUPERSONIC_EXIT
        ):

            if (
                throat_start
                <= x
                <= throat_end
            ):

                mach = 1.0
                branch = "sonic_throat"

            elif x < throat_start:

                mach = solve_area_mach(
                    area / at,
                    supersonic=False,
                    gamma=gamma,
                )

                branch = "subsonic_upstream"

            else:

                mach = solve_area_mach(
                    area / at,
                    supersonic=True,
                    gamma=gamma,
                )

                branch = "supersonic_downstream"

        else:

            assert (
                policy.shock_x_m
                is not None
            )

            assert (
                downstream_astar
                is not None
            )

            assert (
                downstream_p0
                is not None
            )

            if (
                throat_start
                <= x
                <= throat_end
            ):

                mach = 1.0
                branch = "sonic_throat"

            elif x < throat_start:

                mach = solve_area_mach(
                    area / at,
                    supersonic=False,
                    gamma=gamma,
                )

                branch = "subsonic_upstream"

            elif x < policy.shock_x_m:

                mach = solve_area_mach(
                    area / at,
                    supersonic=True,
                    gamma=gamma,
                )

                branch = "supersonic_pre_shock"

            else:

                local_p0 = (
                    downstream_p0
                )

                mach = solve_area_mach(
                    area
                    / downstream_astar,
                    supersonic=False,
                    gamma=gamma,
                )

                branch = "subsonic_post_shock"

        state = isentropic_state(
            mach=mach,
            total_pressure_pa=(
                local_p0
            ),
            total_temperature_k=t0,
            gamma=gamma,
            gas_constant=gas_constant,
        )

        states.append(
            {
                "x0_m": x0,
                "x1_m": x1,
                "x_mid_m": x,
                "radius_m": radius,
                "branch": branch,
                **state,
            }
        )

    return (
        policy,
        states,
    )
