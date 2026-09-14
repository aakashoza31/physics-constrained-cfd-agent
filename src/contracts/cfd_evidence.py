from dataclasses import dataclass, asdict, field
from typing import Any, Dict, List, Optional


@dataclass
class SolverHealthEvidence:
    completed_normally: bool

    max_courant_number: Optional[float] = None
    timestep_collapse_detected: bool = False

    nan_detected: bool = False
    inf_detected: bool = False
    solver_error_detected: bool = False

    notes: List[str] = field(default_factory=list)


@dataclass
class ConservationEvidence:
    inlet_mass_flow_kg_s: Optional[float] = None
    outlet_mass_flow_kg_s: Optional[float] = None

    mass_imbalance_percent: Optional[float] = None
    mass_imbalance_trend: Optional[str] = None


@dataclass
class StationarityEvidence:
    enough_samples: bool = False
    passes_stationarity: bool = False

    mass_flow_range_percent: Optional[float] = None
    mass_flow_drift_percent: Optional[float] = None

    outlet_pressure_range_percent: Optional[float] = None
    outlet_pressure_drift_percent: Optional[float] = None

    outlet_temperature_range_percent: Optional[float] = None
    outlet_temperature_drift_percent: Optional[float] = None

    outlet_velocity_range_percent: Optional[float] = None
    outlet_velocity_drift_percent: Optional[float] = None

    pressure_extrema_trend: Optional[str] = None
    temperature_extrema_trend: Optional[str] = None
    density_extrema_trend: Optional[str] = None


@dataclass
class PhysicalAdmissibilityEvidence:
    pressure_positive: bool = True
    temperature_positive: bool = True
    density_positive: bool = True

    pressure_min_pa: Optional[float] = None
    pressure_max_pa: Optional[float] = None

    temperature_min_k: Optional[float] = None
    temperature_max_k: Optional[float] = None

    density_min_kg_m3: Optional[float] = None
    density_max_kg_m3: Optional[float] = None

    suspicious_local_state_detected: Optional[bool] = None
    suspicious_region: Optional[str] = None

    notes: List[str] = field(default_factory=list)


@dataclass
class BoundaryEvidence:
    inlet_mass_flow_kg_s: Optional[float] = None
    outlet_mass_flow_kg_s: Optional[float] = None

    inlet_flow_direction_valid: Optional[bool] = None
    outlet_flow_direction_valid: Optional[bool] = None

    inlet_reverse_flow_detected: Optional[bool] = None
    outlet_reverse_flow_detected: Optional[bool] = None

    boundary_anomaly_detected: Optional[bool] = None

    notes: List[str] = field(default_factory=list)


@dataclass
class MeshEvidence:
    check_mesh_passed: bool = False

    cell_count: Optional[int] = None

    max_non_orthogonality_deg: Optional[float] = None
    max_skewness: Optional[float] = None
    max_aspect_ratio: Optional[float] = None

    local_quality_issue_detected: bool = False
    local_quality_issue_region: Optional[str] = None

    region_resolution: Dict[str, Any] = field(default_factory=dict)

    notes: List[str] = field(default_factory=list)


@dataclass
class FlowFeatureEvidence:
    strongest_gradient_region: Optional[str] = None

    pressure_gradient_region: Optional[str] = None
    velocity_gradient_region: Optional[str] = None
    mach_gradient_region: Optional[str] = None
    density_gradient_region: Optional[str] = None

    shock_candidate_detected: Optional[bool] = None
    shock_candidate_region: Optional[str] = None

    sonic_transition_detected: Optional[bool] = None
    sonic_transition_region: Optional[str] = None

    candidate_underresolved_regions: List[str] = field(default_factory=list)

    notes: List[str] = field(default_factory=list)


@dataclass
class VisualEvidence:
    pressure_slice_path: Optional[str] = None
    mach_slice_path: Optional[str] = None
    velocity_slice_path: Optional[str] = None

    mesh_slice_path: Optional[str] = None
    mesh_throat_zoom_path: Optional[str] = None
    hotspot_image_path: Optional[str] = None

    visual_anomaly_detected: Optional[bool] = None
    visual_candidate_regions: List[str] = field(default_factory=list)

    notes: List[str] = field(default_factory=list)


@dataclass
class EngineeringEvidence:
    requested_outputs: List[str] = field(default_factory=list)
    measured_outputs: Dict[str, Any] = field(default_factory=dict)


@dataclass
class CFDEvidence:
    solver: SolverHealthEvidence
    conservation: ConservationEvidence
    stationarity: StationarityEvidence
    admissibility: PhysicalAdmissibilityEvidence
    boundaries: BoundaryEvidence
    mesh: MeshEvidence
    flow_features: FlowFeatureEvidence
    visuals: VisualEvidence

    engineering: EngineeringEvidence = field(
        default_factory=EngineeringEvidence
    )

    iteration: int = 0
    case_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

