from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import gmsh


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _profile_from_manifest(
    manifest: dict[str, Any],
) -> list[tuple[float, float]]:
    return [
        (float(item["x_m"]), float(item["radius_m"]))
        for item in manifest["generic_profile"]
    ]


def _curvature_indicators(
    profile: list[tuple[float, float]],
) -> list[dict[str, float]]:
    values: list[dict[str, float]] = []

    for i in range(1, len(profile) - 1):
        x0, r0 = profile[i - 1]
        x1, r1 = profile[i]
        x2, r2 = profile[i + 1]

        dx1 = x1 - x0
        dx2 = x2 - x1

        if dx1 <= 0 or dx2 <= 0:
            continue

        slope1 = (r1 - r0) / dx1
        slope2 = (r2 - r1) / dx2
        rpp = 2.0 * (slope2 - slope1) / (dx1 + dx2)
        slope = 0.5 * (slope1 + slope2)
        curvature = abs(rpp) / ((1.0 + slope * slope) ** 1.5)

        values.append(
            {
                "x_m": x1,
                "radius_m": r1,
                "curvature_indicator": curvature,
            }
        )

    values.sort(
        key=lambda item: item["curvature_indicator"],
        reverse=True,
    )
    return values


def _monotonic_cd_check(
    profile: list[tuple[float, float]],
    throat_start: float,
    throat_end: float,
) -> dict[str, Any]:
    tol = 1e-10

    before = [(x, r) for x, r in profile if x <= throat_start + tol]
    after = [(x, r) for x, r in profile if x >= throat_end - tol]

    converging_ok = all(
        before[i][1] <= before[i - 1][1] + tol
        for i in range(1, len(before))
    )

    diverging_ok = all(
        after[i][1] >= after[i - 1][1] - tol
        for i in range(1, len(after))
    )

    return {
        "converging_monotonic": converging_ok,
        "diverging_monotonic": diverging_ok,
        "passes": converging_ok and diverging_ok,
    }


def analyze_nozzle_geometry(
    cad_path: Path,
    manifest_path: Path,
    output_path: Path,
) -> dict[str, Any]:
    manifest = _load_json(manifest_path)
    profile = _profile_from_manifest(manifest)

    verified = manifest["verified_geometry"]
    throat = verified["throat"]
    expected_inlet_area = verified["inlet"]["area_m2"]
    expected_outlet_area = verified["outlet"]["area_m2"]

    gmsh.initialize()

    try:
        gmsh.model.add("geometry_verification")
        gmsh.model.occ.importShapes(str(cad_path))
        gmsh.model.occ.synchronize()

        volumes = gmsh.model.getEntities(3)

        if len(volumes) != 1:
            raise RuntimeError(
                f"Expected one fluid volume, found {len(volumes)}."
            )

        volume = volumes[0]
        bbox = gmsh.model.getBoundingBox(*volume)
        xmin, _, _, xmax, _, _ = bbox
        length = xmax - xmin
        tol = max(1e-8, length * 1e-6)

        boundary_dimtags = gmsh.model.getBoundary(
            [volume],
            oriented=False,
            recursive=False,
        )

        surfaces = [tag for dim, tag in boundary_dimtags if dim == 2]

        inlet: list[int] = []
        outlet: list[int] = []
        walls: list[int] = []
        surface_info: dict[str, Any] = {}

        for tag in surfaces:
            sbbox = gmsh.model.getBoundingBox(2, tag)
            sxmin, _, _, sxmax, _, _ = sbbox

            try:
                area = float(gmsh.model.occ.getMass(2, tag))
            except Exception:
                area = float("nan")

            surface_info[str(tag)] = {
                "bounding_box": list(sbbox),
                "area_m2": area,
            }

            if abs(sxmin - xmin) <= tol and abs(sxmax - xmin) <= tol:
                inlet.append(tag)
            elif abs(sxmin - xmax) <= tol and abs(sxmax - xmax) <= tol:
                outlet.append(tag)
            else:
                walls.append(tag)

        if not inlet or not outlet or not walls:
            raise RuntimeError("Automatic boundary classification failed.")

        inlet_area = sum(gmsh.model.occ.getMass(2, tag) for tag in inlet)
        outlet_area = sum(gmsh.model.occ.getMass(2, tag) for tag in outlet)

        inlet_area_rel_error = abs(inlet_area - expected_inlet_area) / max(
            expected_inlet_area, 1e-16
        )
        outlet_area_rel_error = abs(outlet_area - expected_outlet_area) / max(
            expected_outlet_area, 1e-16
        )

        curvature = _curvature_indicators(profile)
        top_curvature = curvature[: min(6, len(curvature))]

        monotonic = _monotonic_cd_check(
            profile,
            float(throat["x_start_m"]),
            float(throat["x_end_m"]),
        )

        diverging = verified["diverging_region"]

        result = {
            "geometry_valid": (
                len(volumes) == 1
                and bool(inlet)
                and bool(outlet)
                and bool(walls)
                and inlet_area_rel_error < 0.02
                and outlet_area_rel_error < 0.02
                and monotonic["passes"]
            ),
            "axis": "x",
            "volume_tags": [tag for _, tag in volumes],
            "bounding_box": list(bbox),
            "boundary_tags": {
                "inlet": inlet,
                "outlet": outlet,
                "walls": walls,
            },
            "surface_information": surface_info,
            "verification": {
                "inlet_area_relative_error": inlet_area_rel_error,
                "outlet_area_relative_error": outlet_area_rel_error,
                "profile_monotonicity": monotonic,
            },
            "regions": {
                "throat": {
                    "x_start_m": float(throat["x_start_m"]),
                    "x_end_m": float(throat["x_end_m"]),
                    "x_center_m": float(throat["x_center_m"]),
                    "radius_m": float(throat["radius_m"]),
                },
                "diverging_section": {
                    "x_start_m": float(diverging["x_start_m"]),
                    "x_end_m": float(diverging["x_end_m"]),
                    "role": (
                        "candidate shock-sensitive region; actual shock "
                        "location must come from CFD"
                    ),
                },
                "high_curvature_stations": top_curvature,
            },
        }

        if not result["geometry_valid"]:
            raise RuntimeError(
                "Generated geometry failed deterministic verification. "
                f"Details: {json.dumps(result['verification'], indent=2)}"
            )

        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(result, indent=2),
            encoding="utf-8",
        )

        return result

    finally:
        gmsh.finalize()
