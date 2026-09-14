from __future__ import annotations

import argparse
import csv
import json
import math
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import gmsh


# ============================================================
# DATA MODEL
# ============================================================


@dataclass
class NozzleSpec:
    """
    Generic axisymmetric single-throat converging-diverging nozzle.

    The design agent chooses the family and dimensions. This CAD module
    must not silently reinterpret them.
    """

    name: str = "nozzle_01"
    family: str = "smooth_cosine"

    # Main dimensions [m]
    inlet_radius: float = 0.050
    throat_radius: float = 0.020
    outlet_radius: float = 0.040

    inlet_length: float = 0.050
    converging_length: float = 0.100
    throat_length: float = 0.015
    diverging_length: float = 0.180
    outlet_length: float = 0.050

    # Sampling resolution for curved analytic profiles
    n_converging_points: int = 20
    n_diverging_points: int = 30

    # Generic bell-shape control. Used exactly as supplied.
    bell_exponent: float = 1.70

    # Used by spline/custom families: [[x0, r0], [x1, r1], ...]
    profile_points: list[list[float]] = field(default_factory=list)


SUPPORTED_FAMILIES = {
    "conical",
    "smooth_cosine",
    "bell",
    "spline",
    "custom",
}


# ============================================================
# NUMERIC / SECTION HELPERS
# ============================================================


def _close(
    actual: float,
    expected: float,
    *,
    atol: float = 1e-12,
    rtol: float = 1e-10,
) -> bool:
    return math.isclose(
        float(actual),
        float(expected),
        abs_tol=atol,
        rel_tol=rtol,
    )


def _require_close(
    name: str,
    actual: float,
    expected: float,
    *,
    atol: float = 1e-12,
    rtol: float = 1e-10,
) -> None:
    if not _close(actual, expected, atol=atol, rtol=rtol):
        raise ValueError(
            f"Geometry fidelity failure for {name}: "
            f"actual={actual}, expected={expected}."
        )


def section_positions(spec: NozzleSpec) -> dict[str, float]:
    x0 = 0.0
    x1 = x0 + spec.inlet_length
    x2 = x1 + spec.converging_length
    x3 = x2 + spec.throat_length
    x4 = x3 + spec.diverging_length
    x5 = x4 + spec.outlet_length

    return {
        "inlet_start_x_m": x0,
        "inlet_end_x_m": x1,
        "throat_start_x_m": x2,
        "throat_end_x_m": x3,
        "diverging_end_x_m": x4,
        "outlet_end_x_m": x5,
        "total_length_m": x5 - x0,
    }


# ============================================================
# SPEC / PROFILE VALIDATION
# ============================================================


def validate_basic_spec(spec: NozzleSpec) -> None:
    if spec.family not in SUPPORTED_FAMILIES:
        raise ValueError(
            f"Unsupported nozzle family '{spec.family}'. "
            f"Supported: {sorted(SUPPORTED_FAMILIES)}"
        )

    for name, value in {
        "inlet_radius": spec.inlet_radius,
        "throat_radius": spec.throat_radius,
        "outlet_radius": spec.outlet_radius,
    }.items():
        if not math.isfinite(value) or value <= 0:
            raise ValueError(f"{name} must be positive and finite.")

    if spec.throat_radius >= spec.inlet_radius:
        raise ValueError("throat_radius must be smaller than inlet_radius.")
    if spec.throat_radius >= spec.outlet_radius:
        raise ValueError("throat_radius must be smaller than outlet_radius.")

    for name, value in {
        "inlet_length": spec.inlet_length,
        "converging_length": spec.converging_length,
        "throat_length": spec.throat_length,
        "diverging_length": spec.diverging_length,
        "outlet_length": spec.outlet_length,
    }.items():
        if not math.isfinite(value) or value <= 0:
            raise ValueError(f"{name} must be positive and finite.")

    if spec.n_converging_points < 2:
        raise ValueError("n_converging_points must be >= 2.")
    if spec.n_diverging_points < 2:
        raise ValueError("n_diverging_points must be >= 2.")

    if not math.isfinite(spec.bell_exponent):
        raise ValueError("bell_exponent must be finite.")
    if spec.family == "bell" and spec.bell_exponent <= 0:
        raise ValueError("bell_exponent must be > 0 for family='bell'.")

    if spec.family in {"spline", "custom"}:
        if not spec.profile_points:
            raise ValueError(f"family='{spec.family}' requires profile_points.")
        for i, point in enumerate(spec.profile_points):
            if len(point) != 2:
                raise ValueError(
                    f"profile_points[{i}] must contain exactly [x, radius]."
                )
            x, r = float(point[0]), float(point[1])
            if not math.isfinite(x):
                raise ValueError(f"profile_points[{i}].x must be finite.")
            if not math.isfinite(r) or r <= 0:
                raise ValueError(
                    f"profile_points[{i}].radius must be positive and finite."
                )


def validate_profile(
    profile: list[tuple[float, float]],
) -> dict[str, Any]:
    """
    Deterministic topology/profile validation.

    Duplicate x values are rejected. Nothing is silently deleted or merged.
    """

    if len(profile) < 4:
        raise ValueError("Profile requires at least four points.")

    xs = [float(x) for x, _ in profile]
    rs = [float(r) for _, r in profile]

    if not all(math.isfinite(x) for x in xs):
        raise ValueError("All profile x coordinates must be finite.")
    if not all(math.isfinite(r) and r > 0 for r in rs):
        raise ValueError("All profile radii must be positive and finite.")

    for i in range(1, len(xs)):
        if xs[i] <= xs[i - 1]:
            raise ValueError(
                "Profile x coordinates must strictly increase. "
                "Duplicate x values are not silently rewritten."
            )

    min_radius = min(rs)
    throat_tol = max(1e-10, min_radius * 1e-8)
    throat_indices = [
        i for i, r in enumerate(rs) if abs(r - min_radius) <= throat_tol
    ]

    expected = list(range(throat_indices[0], throat_indices[-1] + 1))
    if throat_indices != expected:
        raise ValueError(
            "Profile contains multiple separated minimum-radius regions."
        )
    if throat_indices[0] == 0:
        raise ValueError("Minimum radius occurs at inlet; not a C-D nozzle.")
    if throat_indices[-1] == len(profile) - 1:
        raise ValueError("Minimum radius occurs at outlet; not a C-D nozzle.")
    if rs[0] <= min_radius:
        raise ValueError("Inlet radius must exceed throat radius.")
    if rs[-1] <= min_radius:
        raise ValueError("Outlet radius must exceed throat radius.")

    monotonic_tol = max(1e-12, max(rs) * 1e-10)
    throat_first = throat_indices[0]
    throat_last = throat_indices[-1]

    for i in range(1, throat_first + 1):
        if rs[i] > rs[i - 1] + monotonic_tol:
            raise ValueError(
                "Converging portion is not monotonically non-increasing."
            )

    for i in range(throat_last + 1, len(rs)):
        if rs[i] < rs[i - 1] - monotonic_tol:
            raise ValueError(
                "Diverging portion is not monotonically non-decreasing."
            )

    throat_start = profile[throat_first][0]
    throat_end = profile[throat_last][0]

    return {
        "minimum_radius_m": min_radius,
        "throat_start_x_m": throat_start,
        "throat_end_x_m": throat_end,
        "throat_center_x_m": 0.5 * (throat_start + throat_end),
        "throat_indices": throat_indices,
    }


# ============================================================
# PROFILE GENERATION
# ============================================================


def cosine_blend(t: float) -> float:
    return 0.5 * (1.0 - math.cos(math.pi * t))


def generate_conical_profile(spec: NozzleSpec) -> list[tuple[float, float]]:
    """Exact piecewise-linear conical C-D profile."""
    p = section_positions(spec)
    return [
        (p["inlet_start_x_m"], spec.inlet_radius),
        (p["inlet_end_x_m"], spec.inlet_radius),
        (p["throat_start_x_m"], spec.throat_radius),
        (p["throat_end_x_m"], spec.throat_radius),
        (p["diverging_end_x_m"], spec.outlet_radius),
        (p["outlet_end_x_m"], spec.outlet_radius),
    ]


def generate_cosine_profile(spec: NozzleSpec) -> list[tuple[float, float]]:
    p = section_positions(spec)
    x1 = p["inlet_end_x_m"]
    x2 = p["throat_start_x_m"]
    x3 = p["throat_end_x_m"]
    x5 = p["outlet_end_x_m"]

    profile: list[tuple[float, float]] = [
        (0.0, spec.inlet_radius),
        (x1, spec.inlet_radius),
    ]

    for i in range(1, spec.n_converging_points + 1):
        t = i / spec.n_converging_points
        s = cosine_blend(t)
        x = x1 + t * spec.converging_length
        r = spec.inlet_radius + s * (
            spec.throat_radius - spec.inlet_radius
        )
        profile.append((x, r))

    _require_close("cosine converging end x", profile[-1][0], x2)
    profile.append((x3, spec.throat_radius))

    for i in range(1, spec.n_diverging_points + 1):
        t = i / spec.n_diverging_points
        s = cosine_blend(t)
        x = x3 + t * spec.diverging_length
        r = spec.throat_radius + s * (
            spec.outlet_radius - spec.throat_radius
        )
        profile.append((x, r))

    profile.append((x5, spec.outlet_radius))
    return profile


def generate_bell_profile(spec: NozzleSpec) -> list[tuple[float, float]]:
    """
    Smooth cosine contraction plus generic bell-like expansion.

    bell_exponent is used exactly as supplied. This is not claimed to be
    a Rao-optimized nozzle.
    """

    p = section_positions(spec)
    x1 = p["inlet_end_x_m"]
    x3 = p["throat_end_x_m"]
    x5 = p["outlet_end_x_m"]

    profile: list[tuple[float, float]] = [
        (0.0, spec.inlet_radius),
        (x1, spec.inlet_radius),
    ]

    for i in range(1, spec.n_converging_points + 1):
        t = i / spec.n_converging_points
        s = cosine_blend(t)
        x = x1 + t * spec.converging_length
        r = spec.inlet_radius + s * (
            spec.throat_radius - spec.inlet_radius
        )
        profile.append((x, r))

    profile.append((x3, spec.throat_radius))

    exponent = spec.bell_exponent
    for i in range(1, spec.n_diverging_points + 1):
        t = i / spec.n_diverging_points
        s = 1.0 - (1.0 - t) ** exponent
        x = x3 + t * spec.diverging_length
        r = spec.throat_radius + s * (
            spec.outlet_radius - spec.throat_radius
        )
        profile.append((x, r))

    profile.append((x5, spec.outlet_radius))
    return profile


def generate_control_point_profile(
    spec: NozzleSpec,
) -> list[tuple[float, float]]:
    if not spec.profile_points:
        raise ValueError(f"family='{spec.family}' requires profile_points.")
    return [(float(x), float(r)) for x, r in spec.profile_points]


def build_generic_profile(spec: NozzleSpec) -> list[tuple[float, float]]:
    if spec.family == "conical":
        return generate_conical_profile(spec)
    if spec.family == "smooth_cosine":
        return generate_cosine_profile(spec)
    if spec.family == "bell":
        return generate_bell_profile(spec)
    if spec.family in {"spline", "custom"}:
        return generate_control_point_profile(spec)
    raise RuntimeError(f"Unhandled family: {spec.family}")


# ============================================================
# STRUCTURED-SPEC -> PROFILE FIDELITY
# ============================================================


def _compare_profiles(
    actual: list[tuple[float, float]],
    expected: list[tuple[float, float]],
    label: str,
) -> None:
    if len(actual) != len(expected):
        raise ValueError(
            f"{label} fidelity failure: expected {len(expected)} points, "
            f"got {len(actual)}."
        )
    for i, ((ax, ar), (ex, er)) in enumerate(zip(actual, expected)):
        _require_close(f"{label}.profile[{i}].x", ax, ex)
        _require_close(f"{label}.profile[{i}].radius", ar, er)


def validate_family_fidelity(
    spec: NozzleSpec,
    profile: list[tuple[float, float]],
    throat_info: dict[str, Any],
) -> dict[str, Any]:
    """
    Verify that the profile matches the structured design specification.

    This prevents a topologically-valid but family-wrong geometry from
    passing unnoticed.
    """

    result: dict[str, Any] = {
        "family": spec.family,
        "profile_matches_structured_spec": True,
        "dimensions_match_structured_spec": True,
        "no_silent_profile_rewrite": True,
    }

    if spec.family == "conical":
        expected = generate_conical_profile(spec)
        _compare_profiles(profile, expected, "conical")
        if len(profile) != 6:
            raise ValueError("Conical profile must contain exactly 6 breakpoints.")
        result.update(
            {
                "shape_contract": "piecewise-linear conical profile",
                "converging_wall": "straight conical frustum",
                "diverging_wall": "straight conical frustum",
                "expected_cad_builder": (
                    "exact_occ_cylinders_and_conical_frustums"
                ),
            }
        )

    elif spec.family == "smooth_cosine":
        _compare_profiles(profile, generate_cosine_profile(spec), "smooth_cosine")
        result.update(
            {
                "shape_contract": "cosine contraction and cosine expansion",
                "expected_cad_builder": "smooth_profile_loft",
            }
        )

    elif spec.family == "bell":
        _compare_profiles(profile, generate_bell_profile(spec), "bell")
        result.update(
            {
                "shape_contract": (
                    "cosine contraction and generic bell-like expansion"
                ),
                "bell_exponent_used": spec.bell_exponent,
                "expected_cad_builder": "smooth_profile_loft",
            }
        )

    elif spec.family in {"spline", "custom"}:
        _compare_profiles(
            profile,
            generate_control_point_profile(spec),
            spec.family,
        )
        result.update(
            {
                "shape_contract": (
                    "supplied profile_points preserved at all section stations"
                ),
                "expected_cad_builder": "smooth_profile_loft",
            }
        )

    if spec.family in {"conical", "smooth_cosine", "bell"}:
        p = section_positions(spec)
        _require_close("inlet radius", profile[0][1], spec.inlet_radius)
        _require_close(
            "throat radius",
            throat_info["minimum_radius_m"],
            spec.throat_radius,
        )
        _require_close("outlet radius", profile[-1][1], spec.outlet_radius)
        _require_close(
            "throat start x",
            throat_info["throat_start_x_m"],
            p["throat_start_x_m"],
        )
        _require_close(
            "throat end x",
            throat_info["throat_end_x_m"],
            p["throat_end_x_m"],
        )
        _require_close(
            "total length",
            profile[-1][0] - profile[0][0],
            p["total_length_m"],
        )
        result["section_positions_m"] = p

    return result


# ============================================================
# CAD CONSTRUCTION
# ============================================================


def create_circle_wire(x: float, radius: float) -> int:
    curve = gmsh.model.occ.addCircle(
        x,
        0.0,
        0.0,
        radius,
        zAxis=[1.0, 0.0, 0.0],
    )
    return gmsh.model.occ.addWire([curve])


def create_fluid_volume(profile: list[tuple[float, float]]) -> int:
    """
    Smooth loft for curved families only.

    The conical family must not use this path.
    """

    wires = [create_circle_wire(x, r) for x, r in profile]
    entities = gmsh.model.occ.addThruSections(
        wires,
        makeSolid=True,
        makeRuled=False,
    )
    gmsh.model.occ.synchronize()

    volumes = [tag for dim, tag in entities if dim == 3]
    if not volumes:
        volumes = [tag for dim, tag in gmsh.model.getEntities(3)]
    if len(volumes) != 1:
        raise RuntimeError(
            f"Expected exactly one lofted fluid volume. Found: {volumes}"
        )
    return volumes[0]


def _fuse_two_volumes(first_tag: int, second_tag: int) -> int:
    out, _ = gmsh.model.occ.fuse(
        [(3, first_tag)],
        [(3, second_tag)],
        removeObject=True,
        removeTool=True,
    )
    volumes = [tag for dim, tag in out if dim == 3]
    if len(volumes) != 1:
        raise RuntimeError(
            "Conical OCC fuse did not produce exactly one volume. "
            f"Result: {out}"
        )
    return volumes[0]


def create_exact_conical_fluid_volume(spec: NozzleSpec) -> int:
    """
    Exact conical CAD:
        inlet cylinder
        + converging conical frustum
        + throat cylinder
        + diverging conical frustum
        + outlet cylinder

    This is the key fix for the previous BSpline-wall bug.
    """

    p = section_positions(spec)

    inlet = gmsh.model.occ.addCylinder(
        p["inlet_start_x_m"], 0.0, 0.0,
        spec.inlet_length, 0.0, 0.0,
        spec.inlet_radius,
    )
    converging = gmsh.model.occ.addCone(
        p["inlet_end_x_m"], 0.0, 0.0,
        spec.converging_length, 0.0, 0.0,
        spec.inlet_radius,
        spec.throat_radius,
    )
    throat = gmsh.model.occ.addCylinder(
        p["throat_start_x_m"], 0.0, 0.0,
        spec.throat_length, 0.0, 0.0,
        spec.throat_radius,
    )
    diverging = gmsh.model.occ.addCone(
        p["throat_end_x_m"], 0.0, 0.0,
        spec.diverging_length, 0.0, 0.0,
        spec.throat_radius,
        spec.outlet_radius,
    )
    outlet = gmsh.model.occ.addCylinder(
        p["diverging_end_x_m"], 0.0, 0.0,
        spec.outlet_length, 0.0, 0.0,
        spec.outlet_radius,
    )

    current = inlet
    for next_volume in (converging, throat, diverging, outlet):
        current = _fuse_two_volumes(current, next_volume)

    gmsh.model.occ.removeAllDuplicates()
    gmsh.model.occ.synchronize()

    volumes = [tag for dim, tag in gmsh.model.getEntities(3)]
    if len(volumes) != 1:
        raise RuntimeError(
            "Exact conical construction must leave one connected volume. "
            f"Found: {volumes}"
        )
    return volumes[0]


def create_family_fluid_volume(
    spec: NozzleSpec,
    profile: list[tuple[float, float]],
) -> tuple[int, str]:
    if spec.family == "conical":
        return (
            create_exact_conical_fluid_volume(spec),
            "exact_occ_cylinders_and_conical_frustums",
        )
    return create_fluid_volume(profile), "smooth_profile_loft"


# ============================================================
# POST-CAD FIDELITY VERIFICATION
# ============================================================


def _surface_type(tag: int) -> str:
    try:
        return str(gmsh.model.getType(2, tag))
    except Exception:
        return "unknown"


def _classify_boundary_surfaces(
    volume_tag: int,
    x_min_expected: float,
    x_max_expected: float,
    tolerance: float,
) -> dict[str, list[int]]:
    boundary = gmsh.model.getBoundary(
        [(3, volume_tag)],
        oriented=False,
        recursive=False,
    )

    inlet: list[int] = []
    outlet: list[int] = []
    walls: list[int] = []

    for dim, tag in boundary:
        if dim != 2:
            continue
        bbox = gmsh.model.getBoundingBox(2, tag)
        sx_min, sx_max = bbox[0], bbox[3]

        if (
            abs(sx_min - x_min_expected) <= tolerance
            and abs(sx_max - x_min_expected) <= tolerance
        ):
            inlet.append(tag)
        elif (
            abs(sx_min - x_max_expected) <= tolerance
            and abs(sx_max - x_max_expected) <= tolerance
        ):
            outlet.append(tag)
        else:
            walls.append(tag)

    return {"inlet": inlet, "outlet": outlet, "walls": walls}


def verify_cad_against_spec(
    spec: NozzleSpec,
    profile: list[tuple[float, float]],
    volume_tag: int,
    builder_name: str,
) -> dict[str, Any]:
    gmsh.model.occ.synchronize()

    volumes = [tag for dim, tag in gmsh.model.getEntities(3)]
    if len(volumes) != 1:
        raise RuntimeError(
            "CAD fidelity failure: expected exactly one connected volume, "
            f"found {volumes}."
        )
    volume_tag = volumes[0]

    bbox = gmsh.model.getBoundingBox(3, volume_tag)
    x_min, y_min, z_min, x_max, y_max, z_max = bbox

    if spec.family in {"conical", "smooth_cosine", "bell"}:
        p = section_positions(spec)
        expected_x_min = 0.0
        expected_x_max = p["outlet_end_x_m"]
        expected_max_radius = max(spec.inlet_radius, spec.outlet_radius)
    else:
        expected_x_min = profile[0][0]
        expected_x_max = profile[-1][0]
        expected_max_radius = max(r for _, r in profile)

    scale = max(1.0, abs(expected_x_max), expected_max_radius)
    bbox_tol = 2e-6 * scale

    _require_close("CAD x_min", x_min, expected_x_min, atol=bbox_tol, rtol=0.0)
    _require_close("CAD x_max", x_max, expected_x_max, atol=bbox_tol, rtol=0.0)
    _require_close(
        "CAD y_min", y_min, -expected_max_radius, atol=bbox_tol, rtol=0.0
    )
    _require_close(
        "CAD y_max", y_max, expected_max_radius, atol=bbox_tol, rtol=0.0
    )
    _require_close(
        "CAD z_min", z_min, -expected_max_radius, atol=bbox_tol, rtol=0.0
    )
    _require_close(
        "CAD z_max", z_max, expected_max_radius, atol=bbox_tol, rtol=0.0
    )

    boundary_tags = _classify_boundary_surfaces(
        volume_tag,
        expected_x_min,
        expected_x_max,
        bbox_tol,
    )

    if len(boundary_tags["inlet"]) != 1:
        raise RuntimeError(
            "CAD fidelity failure: expected exactly one inlet surface, "
            f"found {boundary_tags['inlet']}."
        )
    if len(boundary_tags["outlet"]) != 1:
        raise RuntimeError(
            "CAD fidelity failure: expected exactly one outlet surface, "
            f"found {boundary_tags['outlet']}."
        )
    if not boundary_tags["walls"]:
        raise RuntimeError("CAD fidelity failure: no wall surfaces detected.")

    wall_surface_types = {
        str(tag): _surface_type(tag) for tag in boundary_tags["walls"]
    }

    if spec.family == "conical":
        if builder_name != "exact_occ_cylinders_and_conical_frustums":
            raise RuntimeError(
                "Conical CAD fidelity failure: wrong CAD builder used."
            )

        bad_types = {
            tag: surface_type
            for tag, surface_type in wall_surface_types.items()
            if "spline" in surface_type.lower()
        }
        if bad_types:
            raise RuntimeError(
                "Conical CAD fidelity failure: spline wall surfaces were "
                f"generated: {bad_types}"
            )

    return {
        "cad_fidelity_passed": True,
        "builder": builder_name,
        "volume_tag": volume_tag,
        "volume_count": 1,
        "bounding_box_m": {
            "x_min": x_min,
            "y_min": y_min,
            "z_min": z_min,
            "x_max": x_max,
            "y_max": y_max,
            "z_max": z_max,
        },
        "boundary_tags": boundary_tags,
        "wall_surface_types": wall_surface_types,
    }


# ============================================================
# GEOMETRY METRICS / OUTPUT
# ============================================================


def calculate_profile_metrics(
    profile: list[tuple[float, float]],
    throat_info: dict[str, Any],
) -> dict[str, Any]:
    inlet_x, inlet_radius = profile[0]
    outlet_x, outlet_radius = profile[-1]
    throat_radius = throat_info["minimum_radius_m"]
    throat_start = throat_info["throat_start_x_m"]
    throat_end = throat_info["throat_end_x_m"]

    return {
        "total_length_m": outlet_x - inlet_x,
        "inlet": {
            "x_m": inlet_x,
            "radius_m": inlet_radius,
            "area_m2": math.pi * inlet_radius**2,
        },
        "throat": {
            "x_start_m": throat_start,
            "x_end_m": throat_end,
            "x_center_m": 0.5 * (throat_start + throat_end),
            "radius_m": throat_radius,
            "area_m2": math.pi * throat_radius**2,
        },
        "outlet": {
            "x_m": outlet_x,
            "radius_m": outlet_radius,
            "area_m2": math.pi * outlet_radius**2,
        },
        "converging_region": {
            "x_start_m": inlet_x,
            "x_end_m": throat_start,
        },
        "diverging_region": {
            "x_start_m": throat_end,
            "x_end_m": outlet_x,
        },
        "exit_to_throat_area_ratio": (outlet_radius / throat_radius) ** 2,
        "inlet_to_throat_area_ratio": (inlet_radius / throat_radius) ** 2,
    }


def write_profile_csv(
    profile: list[tuple[float, float]],
    path: Path,
) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["x_m", "radius_m"])
        writer.writerows(profile)


def build_manifest(
    spec: NozzleSpec,
    profile: list[tuple[float, float]],
    geometry_metrics: dict[str, Any],
    family_fidelity: dict[str, Any],
    cad_fidelity: dict[str, Any],
    step_path: Path,
) -> dict[str, Any]:
    return {
        "schema_version": 2,
        "domain": "axisymmetric_single_throat_converging_diverging_nozzle",
        "case_name": spec.name,
        "nozzle_family": spec.family,
        "units": "SI",
        "representation": {
            "geometry": "3D CFD fluid volume",
            "axisymmetric": True,
            "axis": "x",
        },
        "design_parameters": asdict(spec),
        "generic_profile": [
            {"x_m": x, "radius_m": r} for x, r in profile
        ],
        "verified_geometry": geometry_metrics,
        "family_fidelity": family_fidelity,
        "cad_fidelity": cad_fidelity,
        "semantic_regions": {
            "inlet": {"role": "flow inlet"},
            "outlet": {"role": "flow outlet"},
            "walls": {"role": "internal nozzle wall"},
            "throat": {"role": "minimum-area region"},
            "converging_section": {"role": "flow contraction"},
            "diverging_section": {"role": "flow expansion"},
        },
        "files": {"fluid_domain_step": str(step_path)},
    }


# ============================================================
# MAIN GENERATION ENTRY POINT
# ============================================================


def generate_nozzle(
    spec: NozzleSpec,
    output_dir: Path,
) -> dict[str, Any]:
    validate_basic_spec(spec)
    output_dir.mkdir(parents=True, exist_ok=True)

    profile = build_generic_profile(spec)
    throat_info = validate_profile(profile)
    family_fidelity = validate_family_fidelity(spec, profile, throat_info)
    geometry_metrics = calculate_profile_metrics(profile, throat_info)

    gmsh.clear()
    gmsh.model.add(spec.name)

    volume_tag, builder_name = create_family_fluid_volume(spec, profile)
    gmsh.model.occ.synchronize()

    cad_fidelity = verify_cad_against_spec(
        spec=spec,
        profile=profile,
        volume_tag=volume_tag,
        builder_name=builder_name,
    )

    step_path = output_dir / "fluid_domain.step"
    gmsh.write(str(step_path))

    profile_path = output_dir / "profile.csv"
    write_profile_csv(profile, profile_path)

    manifest = build_manifest(
        spec=spec,
        profile=profile,
        geometry_metrics=geometry_metrics,
        family_fidelity=family_fidelity,
        cad_fidelity=cad_fidelity,
        step_path=step_path,
    )

    manifest_path = output_dir / "geometry_manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2),
        encoding="utf-8",
    )

    return manifest


# ============================================================
# SPEC LOADING / CLI
# ============================================================


def load_spec(
    path: Path | None,
    family_override: str | None,
) -> NozzleSpec:
    if path is None:
        spec = NozzleSpec()
    else:
        data = json.loads(path.read_text(encoding="utf-8"))
        spec = NozzleSpec(**data)

    if family_override is not None:
        spec.family = family_override
    return spec


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generic axisymmetric C-D nozzle fluid-domain generator."
    )
    parser.add_argument(
        "--spec",
        type=Path,
        default=None,
        help="JSON design specification, normally generated by the LLM agent.",
    )
    parser.add_argument(
        "--family",
        choices=sorted(SUPPORTED_FAMILIES),
        default=None,
        help="Optional nozzle-family override.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("cases/nozzle_01/geometry"),
    )
    args = parser.parse_args()

    spec = load_spec(args.spec, args.family)

    gmsh.initialize()
    try:
        manifest = generate_nozzle(spec=spec, output_dir=args.output)

        print()
        print("=" * 60)
        print("GENERIC NOZZLE CAD GENERATION SUCCESSFUL")
        print("=" * 60)
        print(f"Case:   {spec.name}")
        print(f"Family: {spec.family}")
        print(
            "Throat radius:",
            manifest["verified_geometry"]["throat"]["radius_m"],
            "m",
        )
        print("CAD builder:", manifest["cad_fidelity"]["builder"])
        print(
            "Family fidelity:",
            manifest["family_fidelity"]["profile_matches_structured_spec"],
        )
        print("CAD fidelity:", manifest["cad_fidelity"]["cad_fidelity_passed"])
        print("Fluid STEP:", manifest["files"]["fluid_domain_step"])
        print("=" * 60)
    finally:
        gmsh.finalize()


if __name__ == "__main__":
    main()
