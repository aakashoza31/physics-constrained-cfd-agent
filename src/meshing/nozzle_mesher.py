"""Legacy prototype (CAD->Gmsh path, paper Appendix C "Prototype before the
registered contracts"); not the registered nozzle family; not used for any
reported result except that prototype record.

Prototype Gmsh mesher. Not imported by the registered family runners or by
src/pipeline.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import gmsh

from src.agents.mesh_planner_agent import MeshStrategy


# ============================================================
# BOUNDARIES / PHYSICAL GROUPS
# ============================================================

def _add_physical_group(
    dim: int,
    tags: list[int],
    name: str,
) -> int:
    if not tags:
        raise ValueError(f"Cannot create empty physical group '{name}'.")
    group = gmsh.model.addPhysicalGroup(dim, tags)
    gmsh.model.setPhysicalName(dim, group, name)
    return group


def _classify_boundaries() -> dict[str, list[int]]:
    volumes = gmsh.model.getEntities(3)

    if len(volumes) != 1:
        raise RuntimeError(
            f"Expected exactly one fluid volume, found {len(volumes)}."
        )

    volume = volumes[0]
    bbox = gmsh.model.getBoundingBox(*volume)
    xmin, _, _, xmax, _, _ = bbox
    length = xmax - xmin

    if length <= 0.0:
        raise RuntimeError("Imported CAD has non-positive x-length.")

    tol = max(1e-8, length * 1e-6)

    boundary = gmsh.model.getBoundary(
        [volume],
        oriented=False,
        recursive=False,
    )
    surfaces = [tag for dim, tag in boundary if dim == 2]

    inlet: list[int] = []
    outlet: list[int] = []
    walls: list[int] = []

    for tag in surfaces:
        sxmin, _, _, sxmax, _, _ = gmsh.model.getBoundingBox(2, tag)

        if (
            abs(sxmin - xmin) <= tol
            and abs(sxmax - xmin) <= tol
        ):
            inlet.append(tag)

        elif (
            abs(sxmin - xmax) <= tol
            and abs(sxmax - xmax) <= tol
        ):
            outlet.append(tag)

        else:
            walls.append(tag)

    if not inlet:
        raise RuntimeError("Failed to identify inlet surface.")
    if not outlet:
        raise RuntimeError("Failed to identify outlet surface.")
    if not walls:
        raise RuntimeError("Failed to identify wall surfaces.")

    return {
        "inlet": inlet,
        "outlet": outlet,
        "walls": walls,
        "fluid": [volume[1]],
    }


# ============================================================
# VALIDATION
# ============================================================

def _validate_geometry_analysis(
    geometry_analysis: dict[str, Any],
) -> None:
    bbox = geometry_analysis.get("bounding_box")

    if not isinstance(bbox, (list, tuple)) or len(bbox) != 6:
        raise ValueError(
            "geometry_analysis['bounding_box'] must contain 6 values."
        )

    regions = geometry_analysis.get("regions")

    if not isinstance(regions, dict):
        raise ValueError(
            "geometry_analysis is missing the 'regions' dictionary."
        )

    for required in ("throat", "diverging_section"):
        if required not in regions:
            raise ValueError(
                f"geometry_analysis['regions'] is missing '{required}'."
            )

    throat = regions["throat"]

    for key in ("x_start_m", "x_end_m", "radius_m"):
        if key not in throat:
            raise ValueError(
                f"geometry_analysis throat region is missing '{key}'."
            )


def _validate_constraints(
    constraints: dict[str, Any],
) -> dict[str, int | float | None]:
    """
    Preserve the user-supplied mesh constraints exactly.

    Missing constraints remain None. No hidden defaults are inserted.
    """

    max_elements_raw = constraints.get("max_elements")
    min_quality_raw = constraints.get("min_quality")
    min_throat_nodes_raw = constraints.get("min_throat_nodes")

    max_elements = (
        None
        if max_elements_raw is None
        else int(max_elements_raw)
    )
    min_quality = (
        None
        if min_quality_raw is None
        else float(min_quality_raw)
    )
    min_throat_nodes = (
        None
        if min_throat_nodes_raw is None
        else int(min_throat_nodes_raw)
    )

    if max_elements is not None and max_elements <= 0:
        raise ValueError("max_elements must be positive.")

    if (
        min_quality is not None
        and not 0.0 <= min_quality <= 1.0
    ):
        raise ValueError("min_quality must be between 0 and 1.")

    if min_throat_nodes is not None and min_throat_nodes <= 0:
        raise ValueError("min_throat_nodes must be positive.")

    return {
        "max_elements": max_elements,
        "min_quality": min_quality,
        "min_throat_nodes": min_throat_nodes,
    }


# ============================================================
# MESH FIELDS
# ============================================================

def _add_box_field(
    size_in: float,
    size_out: float,
    x_min: float,
    x_max: float,
    radial_extent: float,
) -> int:
    if size_in <= 0.0 or size_out <= 0.0:
        raise ValueError("Mesh sizes must be positive.")
    if x_max <= x_min:
        raise ValueError("Box field requires x_max > x_min.")
    if radial_extent <= 0.0:
        raise ValueError("Box radial extent must be positive.")

    field = gmsh.model.mesh.field
    box = field.add("Box")

    field.setNumber(box, "VIn", size_in)
    field.setNumber(box, "VOut", size_out)
    field.setNumber(box, "XMin", x_min)
    field.setNumber(box, "XMax", x_max)
    field.setNumber(box, "YMin", -radial_extent)
    field.setNumber(box, "YMax", radial_extent)
    field.setNumber(box, "ZMin", -radial_extent)
    field.setNumber(box, "ZMax", radial_extent)

    return box


def _apply_mesh_fields(
    strategy: MeshStrategy,
    geometry_analysis: dict[str, Any],
    boundary_tags: dict[str, list[int]],
) -> dict[str, Any]:
    """
    Deterministically execute the LLM-proposed sizing strategy.
    """

    active_sizes = [strategy.global_size_m]

    if strategy.refine_throat:
        active_sizes.append(strategy.throat_size_m)
    if strategy.refine_walls:
        active_sizes.append(strategy.wall_size_m)
    if strategy.refine_diverging_section:
        active_sizes.append(strategy.diverging_size_m)

    effective_min = max(min(active_sizes) * 0.5, 1e-6)

    gmsh.option.setNumber("Mesh.MeshSizeMax", strategy.global_size_m)
    gmsh.option.setNumber("Mesh.MeshSizeMin", effective_min)
    gmsh.option.setNumber("Mesh.MeshSizeFromPoints", 0)
    gmsh.option.setNumber("Mesh.MeshSizeFromCurvature", 0)
    gmsh.option.setNumber("Mesh.MeshSizeExtendFromBoundary", 0)
    gmsh.option.setNumber("Mesh.MshFileVersion", 4.1)

    bbox = geometry_analysis["bounding_box"]
    radial_extent = max(
        abs(float(bbox[1])),
        abs(float(bbox[2])),
        abs(float(bbox[4])),
        abs(float(bbox[5])),
    )

    if radial_extent <= 0.0:
        raise RuntimeError(
            "Could not determine radial extent from geometry analysis."
        )

    # Slight cushion so box fields cover the full CAD envelope.
    field_radius = radial_extent * 1.05

    fields: list[int] = []
    descriptions: list[dict[str, Any]] = []
    field_api = gmsh.model.mesh.field
    regions = geometry_analysis["regions"]
    throat = regions["throat"]

    if strategy.refine_throat:
        x_min = (
            float(throat["x_start_m"])
            - strategy.throat_padding_m
        )
        x_max = (
            float(throat["x_end_m"])
            + strategy.throat_padding_m
        )

        tag = _add_box_field(
            size_in=strategy.throat_size_m,
            size_out=strategy.global_size_m,
            x_min=x_min,
            x_max=x_max,
            radial_extent=field_radius,
        )
        fields.append(tag)
        descriptions.append(
            {
                "type": "throat_box",
                "field_tag": tag,
                "size_m": strategy.throat_size_m,
                "x_min_m": x_min,
                "x_max_m": x_max,
            }
        )

    if strategy.refine_diverging_section:
        diverging = regions["diverging_section"]
        x_min = float(diverging["x_start_m"])
        x_max = float(diverging["x_end_m"])

        tag = _add_box_field(
            size_in=strategy.diverging_size_m,
            size_out=strategy.global_size_m,
            x_min=x_min,
            x_max=x_max,
            radial_extent=field_radius,
        )
        fields.append(tag)
        descriptions.append(
            {
                "type": "diverging_box",
                "field_tag": tag,
                "size_m": strategy.diverging_size_m,
                "x_min_m": x_min,
                "x_max_m": x_max,
            }
        )

    if strategy.refine_walls:
        distance = field_api.add("Distance")
        field_api.setNumbers(
            distance,
            "FacesList",
            boundary_tags["walls"],
        )

        threshold = field_api.add("Threshold")
        field_api.setNumber(threshold, "InField", distance)
        field_api.setNumber(
            threshold,
            "SizeMin",
            strategy.wall_size_m,
        )
        field_api.setNumber(
            threshold,
            "SizeMax",
            strategy.global_size_m,
        )
        field_api.setNumber(threshold, "DistMin", 0.0)
        field_api.setNumber(
            threshold,
            "DistMax",
            strategy.wall_refinement_distance_m,
        )

        fields.append(threshold)
        descriptions.append(
            {
                "type": "wall_distance_threshold",
                "distance_field_tag": distance,
                "field_tag": threshold,
                "size_min_m": strategy.wall_size_m,
                "size_max_m": strategy.global_size_m,
                "distance_max_m": (
                    strategy.wall_refinement_distance_m
                ),
                "wall_surface_tags": list(
                    boundary_tags["walls"]
                ),
            }
        )

    if strategy.refine_high_curvature:
        stations = regions.get("high_curvature_stations", [])

        if not isinstance(stations, list):
            raise ValueError(
                "high_curvature_stations must be a list."
            )

        half_width = max(
            strategy.global_size_m,
            strategy.throat_padding_m * 0.4,
        )
        curvature_size = min(
            strategy.wall_size_m,
            strategy.diverging_size_m,
        )

        for station in stations[:4]:
            if "x_m" not in station:
                continue

            x = float(station["x_m"])

            tag = _add_box_field(
                size_in=curvature_size,
                size_out=strategy.global_size_m,
                x_min=x - half_width,
                x_max=x + half_width,
                radial_extent=field_radius,
            )
            fields.append(tag)
            descriptions.append(
                {
                    "type": "high_curvature_box",
                    "field_tag": tag,
                    "center_x_m": x,
                    "half_width_m": half_width,
                    "size_m": curvature_size,
                }
            )

    background_field: int | None = None

    if len(fields) == 1:
        background_field = fields[0]
        field_api.setAsBackgroundMesh(background_field)

    elif len(fields) > 1:
        background_field = field_api.add("Min")
        field_api.setNumbers(
            background_field,
            "FieldsList",
            fields,
        )
        field_api.setAsBackgroundMesh(background_field)

    return {
        "background_field_tag": background_field,
        "field_tags": fields,
        "field_descriptions": descriptions,
        "global_size_m": strategy.global_size_m,
        "effective_mesh_size_min_m": effective_min,
    }


# ============================================================
# METRICS
# ============================================================

def _count_throat_nodes(
    coordinates: Any,
    geometry_analysis: dict[str, Any],
) -> tuple[int, dict[str, float]]:
    """
    Count unique global mesh nodes in a deterministic throat region.

    This is a regional throat-resolution metric, not a claim that
    every counted node lies exactly on the minimum-area plane.
    """

    throat = geometry_analysis["regions"]["throat"]
    x_start = float(throat["x_start_m"])
    x_end = float(throat["x_end_m"])
    radius = float(throat["radius_m"])

    if x_end < x_start:
        raise ValueError("Throat x_end_m must be >= x_start_m.")
    if radius <= 0.0:
        raise ValueError("Throat radius must be positive.")

    x_pad = max(
        (x_end - x_start) * 0.5,
        radius * 0.15,
    )
    radial_limit = radius * 1.10

    count = 0

    for i in range(0, len(coordinates), 3):
        x = float(coordinates[i])
        y = float(coordinates[i + 1])
        z = float(coordinates[i + 2])
        r = math.sqrt(y * y + z * z)

        if (
            x_start - x_pad <= x <= x_end + x_pad
            and r <= radial_limit
        ):
            count += 1

    return (
        count,
        {
            "x_min_m": x_start - x_pad,
            "x_max_m": x_end + x_pad,
            "radial_limit_m": radial_limit,
        },
    )


def _evaluate_constraints(
    element_count: int,
    minimum_quality: float,
    throat_nodes: int,
    constraints: dict[str, int | float | None],
    boundary_layer_requested: bool,
) -> tuple[bool, list[str]]:
    violations: list[str] = []

    max_elements = constraints["max_elements"]
    min_quality = constraints["min_quality"]
    min_throat_nodes = constraints["min_throat_nodes"]

    if (
        max_elements is not None
        and element_count > max_elements
    ):
        violations.append("element budget exceeded")

    if (
        min_quality is not None
        and minimum_quality < min_quality
    ):
        violations.append("minimum quality below target")

    if (
        min_throat_nodes is not None
        and throat_nodes < min_throat_nodes
    ):
        violations.append("throat-node target not reached")

    # Current mesher is tetrahedral only.
    if boundary_layer_requested:
        violations.append(
            "boundary-layer/prism mesh requested but "
            "not implemented in current tetrahedral mesher"
        )

    return not violations, violations


# ============================================================
# ONE INITIAL MESH
# ============================================================

def generate_initial_mesh(
    cad_path: Path,
    geometry_analysis: dict[str, Any],
    strategy: MeshStrategy,
    constraints: dict[str, Any],
    output_dir: Path,
) -> dict[str, Any]:
    """
    Generate exactly ONE initial Gmsh tetrahedral mesh.

    No adaptation loop and no OpenFOAM run happen here.
    """

    if not cad_path.exists():
        raise FileNotFoundError(
            f"Approved CAD file not found: {cad_path}"
        )

    _validate_geometry_analysis(geometry_analysis)
    validated_constraints = _validate_constraints(constraints)

    if not isinstance(strategy, MeshStrategy):
        strategy = MeshStrategy.model_validate(strategy)

    output_dir.mkdir(parents=True, exist_ok=True)

    gmsh.initialize()

    try:
        gmsh.model.add("agentic_initial_mesh")

        imported = gmsh.model.occ.importShapes(str(cad_path))
        gmsh.model.occ.synchronize()

        imported_volumes = [
            tag
            for dim, tag in imported
            if dim == 3
        ]

        if not imported_volumes:
            imported_volumes = [
                tag
                for dim, tag in gmsh.model.getEntities(3)
            ]

        if len(imported_volumes) != 1:
            raise RuntimeError(
                "Approved STEP import did not produce exactly "
                f"one fluid volume: {imported_volumes}"
            )

        boundaries = _classify_boundaries()

        physical_groups = {
            "inlet": _add_physical_group(
                2,
                boundaries["inlet"],
                "inlet",
            ),
            "outlet": _add_physical_group(
                2,
                boundaries["outlet"],
                "outlet",
            ),
            "walls": _add_physical_group(
                2,
                boundaries["walls"],
                "walls",
            ),
            "fluid": _add_physical_group(
                3,
                boundaries["fluid"],
                "fluid",
            ),
        }

        mesh_field_info = _apply_mesh_fields(
            strategy,
            geometry_analysis,
            boundaries,
        )

        # Exactly one 3D mesh generation.
        gmsh.model.mesh.generate(3)

        optimization_status = "not_attempted"

        try:
            gmsh.model.mesh.optimize("Netgen")
            optimization_status = "netgen_success"
        except Exception as exc:
            optimization_status = f"netgen_failed: {exc}"

        node_tags, coordinates, _ = gmsh.model.mesh.getNodes()
        (
            element_types,
            element_tags,
            _,
        ) = gmsh.model.mesh.getElements(3)

        volume_element_tags = [
            int(tag)
            for tags in element_tags
            for tag in tags
        ]

        if not volume_element_tags:
            raise RuntimeError("No 3D elements were generated.")

        qualities = gmsh.model.mesh.getElementQualities(
            volume_element_tags,
            "minSICN",
        )

        if len(qualities) == 0:
            raise RuntimeError(
                "Gmsh returned no 3D element quality values."
            )

        minimum_quality = float(min(qualities))
        average_quality = float(
            sum(qualities) / len(qualities)
        )

        (
            throat_nodes,
            throat_metric_definition,
        ) = _count_throat_nodes(
            coordinates,
            geometry_analysis,
        )

        element_count = len(volume_element_tags)

        feasible, violations = _evaluate_constraints(
            element_count=element_count,
            minimum_quality=minimum_quality,
            throat_nodes=throat_nodes,
            constraints=validated_constraints,
            boundary_layer_requested=(
                strategy.boundary_layer_requested
            ),
        )

        mesh_path = output_dir / "initial_mesh.msh"
        gmsh.write(str(mesh_path))

        result = {
            "status": "success",
            "stage": "single_initial_mesh_measurement",
            "mesh_file": str(mesh_path),
            "nodes": int(len(node_tags)),
            "elements_3d": element_count,
            "element_types_3d": [
                int(value)
                for value in element_types
            ],
            "quality_metric": "minSICN",
            "minimum_quality_minSICN": minimum_quality,
            "average_quality_minSICN": average_quality,
            "throat_nodes": throat_nodes,
            "throat_node_metric_definition": (
                throat_metric_definition
            ),
            "constraints": validated_constraints,
            "feasible_initial_mesh": feasible,
            "violations": violations,
            "boundary_tags": boundaries,
            "physical_group_tags": physical_groups,
            "mesh_strategy": strategy.model_dump(),
            "mesh_field_execution": mesh_field_info,
            "mesh_optimization": optimization_status,
            "boundary_layer_status": (
                "requested_but_not_implemented"
                if strategy.boundary_layer_requested
                else "not_requested"
            ),
        }

        metrics_path = output_dir / "mesh_metrics.json"
        metrics_path.write_text(
            json.dumps(result, indent=2),
            encoding="utf-8",
        )

        return result

    finally:
        gmsh.finalize()
