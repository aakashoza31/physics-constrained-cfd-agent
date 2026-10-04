"""Legacy: adapter from raw prototype diagnostics to ``CFDEvidence`` (unused).

Not part of the CFD Forge paper; not imported by the registered families'
runners (``scripts/run_nozzle_feedback.py``, ``scripts/run_nozzle_e2e.py``,
``scripts/run_forward_step_2d.py``) or by ``src/pipeline``.  Kept for
reference only.

``adapt_raw_diagnostics`` converts the nested diagnostics dictionary produced
by the earlier CAD->Gmsh prototype stack (solver health, extrema, throat
features, stationarity, mesh context and image paths) into the
``src.contracts.cfd_evidence.CFDEvidence`` contract.  The registered nozzle
family builds its evidence with ``src/reasoning/reference_evidence_adapter.py``
and ``src/pipeline/nozzle/feedback_diagnostics.py`` instead.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from src.contracts.cfd_evidence import (
    BoundaryEvidence,
    CFDEvidence,
    ConservationEvidence,
    EngineeringEvidence,
    FlowFeatureEvidence,
    MeshEvidence,
    PhysicalAdmissibilityEvidence,
    SolverHealthEvidence,
    StationarityEvidence,
    VisualEvidence,
)

from src.contracts.problem_spec import CFDProblemSpec


def _nested(
    obj: Dict[str, Any],
    *keys: str,
    default: Any = None,
) -> Any:
    current: Any = obj

    for key in keys:
        if not isinstance(current, dict):
            return default

        if key not in current:
            return default

        current = current[key]

    return current


def _extrema_value(
    global_fields: Dict[str, Any],
    field_name: str,
    which: str,
) -> Optional[float]:

    item = _nested(
        global_fields,
        field_name,
        which,
        default=None,
    )

    if item is None:
        return None

    if isinstance(item, dict):
        item = item.get("value")

    if item is None:
        return None

    try:
        return float(item)
    except (TypeError, ValueError):
        return None


def _float_or_none(value: Any) -> Optional[float]:
    if value is None:
        return None

    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _relative_change_pct(
    first: Any,
    second: Any,
) -> Optional[float]:

    a = _float_or_none(first)
    b = _float_or_none(second)

    if a is None or b is None:
        return None

    if abs(a) < 1.0e-30:
        return None

    return 100.0 * (b - a) / abs(a)


def _stationarity_value(
    raw_stationarity: Dict[str, Any],
    group: str,
    metric: str,
) -> Optional[float]:

    return _float_or_none(
        _nested(
            raw_stationarity,
            group,
            metric,
            default=None,
        )
    )


def _extract_throat_feature_evidence(
    throat: Any,
) -> FlowFeatureEvidence:

    if not isinstance(throat, dict):
        return FlowFeatureEvidence(
            notes=[
                "No throat cut-plane diagnostics were available."
            ]
        )

    sonic = throat.get(
        "sonic_transition",
        {}
    )

    planes = throat.get(
        "latest_planes",
        {}
    )

    start = planes.get(
        "start",
        {}
    )

    center = planes.get(
        "center",
        {}
    )

    end = planes.get(
        "end",
        {}
    )

    notes = []

    pressure_start_to_center = _relative_change_pct(
        start.get("pressure_pa"),
        center.get("pressure_pa"),
    )

    pressure_center_to_end = _relative_change_pct(
        center.get("pressure_pa"),
        end.get("pressure_pa"),
    )

    mach_start_to_center = _relative_change_pct(
        start.get("mach"),
        center.get("mach"),
    )

    mach_center_to_end = _relative_change_pct(
        center.get("mach"),
        end.get("mach"),
    )

    if pressure_start_to_center is not None:
        notes.append(
            "Measured throat pressure change start->center: "
            f"{pressure_start_to_center:.3f}%."
        )

    if pressure_center_to_end is not None:
        notes.append(
            "Measured throat pressure change center->end: "
            f"{pressure_center_to_end:.3f}%."
        )

    if mach_start_to_center is not None:
        notes.append(
            "Measured throat Mach change start->center: "
            f"{mach_start_to_center:.3f}%."
        )

    if mach_center_to_end is not None:
        notes.append(
            "Measured throat Mach change center->end: "
            f"{mach_center_to_end:.3f}%."
        )

    # Important:
    # We may say CFD measured a gradient across the throat region.
    # We do NOT automatically claim it is under-resolved.
    gradient_measured = any(
        value is not None and abs(value) > 1.0e-9
        for value in (
            pressure_start_to_center,
            pressure_center_to_end,
            mach_start_to_center,
            mach_center_to_end,
        )
    )

    sonic_detected = None

    if isinstance(sonic, dict):
        if "detected" in sonic:
            sonic_detected = bool(
                sonic.get("detected")
            )

    return FlowFeatureEvidence(
        strongest_gradient_region=None,

        pressure_gradient_region=(
            "throat"
            if gradient_measured
            else None
        ),

        mach_gradient_region=(
            "throat"
            if gradient_measured
            else None
        ),

        sonic_transition_detected=(
            sonic_detected
        ),

        sonic_transition_region=(
            "throat"
            if sonic_detected
            else None
        ),

        # Under-resolution is NOT inferred from
        # gradient existence alone.
        candidate_underresolved_regions=[],

        notes=notes,
    )


def adapt_raw_diagnostics(
    raw: Dict[str, Any],
    problem: CFDProblemSpec,
    *,
    mesh_context: Optional[Dict[str, Any]] = None,
    visual_paths: Optional[Dict[str, str]] = None,
    iteration: int = 0,
    case_id: Optional[str] = None,
) -> CFDEvidence:

    if not isinstance(raw, dict):
        raise TypeError(
            "raw diagnostics must be a dictionary."
        )

    problem.validate()

    mesh_context = (
        mesh_context
        if isinstance(mesh_context, dict)
        else {}
    )

    visual_paths = (
        visual_paths
        if isinstance(visual_paths, dict)
        else {}
    )

    raw_solver = raw.get(
        "solver",
        {}
    )

    raw_flow = raw.get(
        "flow",
        {}
    )

    raw_stationarity = raw.get(
        "stationarity",
        {}
    )

    global_fields = raw.get(
        "global_field_validity",
        {}
    )

    raw_mesh = raw.get(
        "mesh",
        {}
    )

    # ------------------------------------------------------------
    # Solver health
    # ------------------------------------------------------------

    failure_markers = (
        raw_solver.get(
            "failure_markers",
            []
        )
        if isinstance(raw_solver, dict)
        else []
    )

    failure_text = " ".join(
        str(item)
        for item in failure_markers
    ).lower()

    completed_raw = raw_solver.get(
        "completed_normally"
    )

    solver = SolverHealthEvidence(
        # Conservative handling:
        # unchecked solver completion is NOT treated as success.
        completed_normally=(
            completed_raw is True
        ),

        max_courant_number=_float_or_none(
            raw_solver.get(
                "max_courant_seen"
            )
        ),

        nan_detected=(
            "nan"
            in failure_text
        ),

        inf_detected=(
            "inf"
            in failure_text
            or "floating point"
            in failure_text
        ),

        solver_error_detected=bool(
            raw_solver.get(
                "failure_detected",
                False,
            )
        ),

        notes=[
            (
                "Solver completion was not checked in the raw diagnostics."
                if completed_raw is None
                else "Solver completion was checked."
            )
        ],
    )

    # ------------------------------------------------------------
    # Conservation
    # ------------------------------------------------------------

    inlet_flow = _float_or_none(
        raw_flow.get(
            "inlet_mass_flow_kg_s"
        )
    )

    outlet_flow = _float_or_none(
        raw_flow.get(
            "outlet_mass_flow_kg_s"
        )
    )

    imbalance = _float_or_none(
        raw_flow.get(
            "mass_imbalance_pct"
        )
    )

    conservation = ConservationEvidence(
        inlet_mass_flow_kg_s=inlet_flow,
        outlet_mass_flow_kg_s=outlet_flow,
        mass_imbalance_percent=imbalance,
        mass_imbalance_trend=None,
    )

    # ------------------------------------------------------------
    # Stationarity
    # ------------------------------------------------------------

    stationarity = StationarityEvidence(
        enough_samples=bool(
            raw_stationarity.get(
                "enough_samples",
                False,
            )
        ),

        passes_stationarity=bool(
            raw_stationarity.get(
                "passes_all_monitored_metrics",
                False,
            )
        ),

        mass_flow_range_percent=(
            _stationarity_value(
                raw_stationarity,
                "outlet_mass_flow",
                "relative_range_pct",
            )
        ),

        mass_flow_drift_percent=(
            _stationarity_value(
                raw_stationarity,
                "outlet_mass_flow",
                "relative_drift_pct",
            )
        ),

        outlet_pressure_range_percent=(
            _stationarity_value(
                raw_stationarity,
                "outlet_pressure",
                "relative_range_pct",
            )
        ),

        outlet_pressure_drift_percent=(
            _stationarity_value(
                raw_stationarity,
                "outlet_pressure",
                "relative_drift_pct",
            )
        ),

        outlet_temperature_range_percent=(
            _stationarity_value(
                raw_stationarity,
                "outlet_temperature",
                "relative_range_pct",
            )
        ),

        outlet_temperature_drift_percent=(
            _stationarity_value(
                raw_stationarity,
                "outlet_temperature",
                "relative_drift_pct",
            )
        ),

        outlet_velocity_range_percent=(
            _stationarity_value(
                raw_stationarity,
                "outlet_velocity",
                "relative_range_pct",
            )
        ),

        outlet_velocity_drift_percent=(
            _stationarity_value(
                raw_stationarity,
                "outlet_velocity",
                "relative_drift_pct",
            )
        ),

        # The old diagnostics currently do not provide
        # time histories of global extrema.
        pressure_extrema_trend=None,
        temperature_extrema_trend=None,
        density_extrema_trend=None,
    )

    # ------------------------------------------------------------
    # Physical admissibility
    # ------------------------------------------------------------

    admissibility = PhysicalAdmissibilityEvidence(
        pressure_positive=bool(
            global_fields.get(
                "positive_pressure",
                False,
            )
        ),

        temperature_positive=bool(
            global_fields.get(
                "positive_temperature",
                False,
            )
        ),

        density_positive=bool(
            global_fields.get(
                "positive_density",
                False,
            )
        ),

        pressure_min_pa=_extrema_value(
            global_fields,
            "pressure",
            "min",
        ),

        pressure_max_pa=_extrema_value(
            global_fields,
            "pressure",
            "max",
        ),

        temperature_min_k=_extrema_value(
            global_fields,
            "temperature",
            "min",
        ),

        temperature_max_k=_extrema_value(
            global_fields,
            "temperature",
            "max",
        ),

        density_min_kg_m3=_extrema_value(
            global_fields,
            "density",
            "min",
        ),

        density_max_kg_m3=_extrema_value(
            global_fields,
            "density",
            "max",
        ),

        # IMPORTANT:
        # latest extrema cannot prove absence of localized
        # temporal instability.
        suspicious_local_state_detected=None,

        notes=[
            "Legacy diagnostics provide latest global extrema; "
            "localized temporal anomaly status remains unknown "
            "until dedicated history diagnostics are supplied."
        ],
    )

    # ------------------------------------------------------------
    # Boundaries
    # ------------------------------------------------------------

    inlet_direction_valid = (
        inlet_flow < 0.0
        if inlet_flow is not None
        else None
    )

    outlet_direction_valid = (
        outlet_flow > 0.0
        if outlet_flow is not None
        else None
    )

    direction_problem = (
        inlet_direction_valid is False
        or outlet_direction_valid is False
    )

    boundaries = BoundaryEvidence(
        inlet_mass_flow_kg_s=inlet_flow,
        outlet_mass_flow_kg_s=outlet_flow,

        inlet_flow_direction_valid=(
            inlet_direction_valid
        ),

        outlet_flow_direction_valid=(
            outlet_direction_valid
        ),

        # Current raw diagnostics use patch-integrated flow.
        # They do NOT establish whether some patch faces
        # contain reverse flow.
        inlet_reverse_flow_detected=None,
        outlet_reverse_flow_detected=None,

        boundary_anomaly_detected=(
            True
            if direction_problem
            else None
        ),

        notes=[
            "Patch-integrated flow direction is checked.",
            "Face-wise reverse-flow distribution has not yet been measured.",
        ],
    )

    # ------------------------------------------------------------
    # Mesh
    # ------------------------------------------------------------

    region_resolution = dict(
        mesh_context.get(
            "region_resolution",
            {}
        )
    )

    throat_target_size = _float_or_none(
        mesh_context.get(
            "throat_target_size_m"
        )
    )

    if throat_target_size is not None:

        g = problem.geometry

        throat_resolution = {
            "target_size_m": throat_target_size,
            "throat_radius_m": g.throat_radius_m,
            "throat_length_m": g.throat_length_m,

            "estimated_cells_per_throat_radius": (
                g.throat_radius_m
                / throat_target_size
            ),

            "estimated_cells_per_throat_length": (
                g.throat_length_m
                / throat_target_size
            ),
        }

        region_resolution[
            "throat"
        ] = throat_resolution

    mesh = MeshEvidence(
        check_mesh_passed=bool(
            raw_mesh.get(
                "mesh_ok",
                False,
            )
        ),

        cell_count=raw_mesh.get(
            "cells"
        ),

        max_non_orthogonality_deg=(
            _float_or_none(
                raw_mesh.get(
                    "max_non_orthogonality"
                )
            )
        ),

        max_skewness=_float_or_none(
            raw_mesh.get(
                "max_skewness"
            )
        ),

        max_aspect_ratio=_float_or_none(
            raw_mesh.get(
                "max_aspect_ratio"
            )
        ),

        # Do not infer local quality failure from
        # global checkMesh alone.
        local_quality_issue_detected=False,

        local_quality_issue_region=None,

        region_resolution=region_resolution,

        notes=[
            "checkMesh metrics were adapted from the existing diagnostics.",
            "Local resolution metadata is included only when supplied "
            "by deterministic meshing context.",
        ],
    )

    # ------------------------------------------------------------
    # Flow features
    # ------------------------------------------------------------

    flow_features = (
        _extract_throat_feature_evidence(
            raw.get(
                "throat"
            )
        )
    )

    explicit_candidates = mesh_context.get(
        "candidate_underresolved_regions"
    )

    if isinstance(
        explicit_candidates,
        list,
    ):
        flow_features.candidate_underresolved_regions = [
            str(item)
            for item
            in explicit_candidates
        ]

    # ------------------------------------------------------------
    # Visual evidence metadata
    # ------------------------------------------------------------

    visuals = VisualEvidence(
        pressure_slice_path=visual_paths.get(
            "pressure"
        ),

        mach_slice_path=visual_paths.get(
            "mach"
        ),

        velocity_slice_path=visual_paths.get(
            "velocity"
        ),

        mesh_slice_path=visual_paths.get(
            "mesh"
        ),

        mesh_throat_zoom_path=visual_paths.get(
            "mesh_throat"
        ),

        hotspot_image_path=visual_paths.get(
            "hotspot"
        ),

        # Paths alone are NOT visual interpretation.
        visual_anomaly_detected=None,

        visual_candidate_regions=[],

        notes=[
            "Image paths are recorded here. Actual image pixels "
            "will be supplied to the multimodal agent in the "
            "visual-reasoning integration stage."
        ],
    )

    engineering = EngineeringEvidence(
        requested_outputs=[
            "trustworthy CFD solution",
            "diagnostic reasoning",
            "mesh adaptation when justified",
        ],

        measured_outputs={
            "outlet_pressure_pa": (
                _float_or_none(
                    raw_flow.get(
                        "outlet_pressure_pa"
                    )
                )
            ),

            "outlet_temperature_k": (
                _float_or_none(
                    raw_flow.get(
                        "outlet_temperature_k"
                    )
                )
            ),

            "outlet_velocity_mps": (
                _float_or_none(
                    raw_flow.get(
                        "outlet_velocity_mps"
                    )
                )
            ),

            "outlet_mach": (
                _float_or_none(
                    raw_flow.get(
                        "outlet_mach"
                    )
                )
            ),
        },
    )

    return CFDEvidence(
        solver=solver,
        conservation=conservation,
        stationarity=stationarity,
        admissibility=admissibility,
        boundaries=boundaries,
        mesh=mesh,
        flow_features=flow_features,
        visuals=visuals,
        engineering=engineering,
        iteration=iteration,
        case_id=case_id,
    )
