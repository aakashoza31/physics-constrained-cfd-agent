# Autonomous CFD Results: 20260914_020146_conical_nozzle

## Executive summary

- CFD status: **STABLE_UNCONVERGED**
- Final agent diagnosis: **UNCONVERGED**
- Final agent action: **CONTINUE_RUN**
- Agent confidence: **high**
- Mass-flow imbalance: **50.7713 %**
- Stationarity passed: **No**
- Mesh cells: **63747**

### Agent interpretation

The simulation remains numerically healthy, physically admissible, and is continuing to evolve without any remeshing or mapping changes. Although stationarity has not yet been achieved and mass imbalance is high, policy allows continuing the run as long as progress is maintained and no numerical failures occur. Therefore, CONTINUE_RUN is the appropriate permitted action.

## Problem specification

```json
{
  "nozzle_family": "conical",
  "geometry": {
    "inlet_radius_m": 0.05,
    "throat_radius_m": 0.0326,
    "outlet_radius_m": 0.0354,
    "inlet_length_m": 0.05,
    "converging_length_m": 0.1,
    "throat_length_m": 0.01,
    "diverging_length_m": 0.12,
    "outlet_length_m": 0.05
  },
  "operating_conditions": {
    "inlet_total_pressure_pa": 200000.0,
    "inlet_total_temperature_k": 300.0,
    "outlet_static_pressure_pa": 30000.0,
    "gas": "air",
    "gamma": 1.4,
    "gas_constant_j_kg_k": 287.0
  },
  "engineering_objective": "Obtain a numerically trustworthy compressible-Euler CFD solution, diagnosing and correcting numerical or mesh issues when the available evidence justifies an action.",
  "physics_model": "compressible_euler",
  "geometry_class": "axisymmetric_converging_diverging_nozzle"
}
```

## Key physical-field diagnostics

| Quantity | Value |
|---|---:|
| Global pressure minimum | Not measured Pa |
| Global pressure maximum | Not measured Pa |
| Global temperature minimum | Not measured K |
| Global temperature maximum | Not measured K |
| Mass-flow imbalance | 50.7713 % |
| Stationarity passed | No |

## CFD evidence

The numerical diagnostics determine whether the solution is trustworthy. The images below are supporting evidence used to inspect flow structure, localized gradients, and mesh resolution.

### Pressure field

![Pressure field](images/pressure.png)

### Mach-number field

![Mach-number field](images/mach.png)

### Velocity-magnitude field

![Velocity-magnitude field](images/velocity_magnitude.png)

### Final CFD mesh

![Final CFD mesh](images/mesh.png)

## Complete deterministic diagnostics

The compact table below records every scalar diagnostic stored by the CFD diagnostics subsystem.

| Diagnostic | Value |
|---|---|
| `case_wsl` | /home/aakash/physics_constrained_cfd_openfoam_runtime |
| `monitoring_window.start_time_s` | 0.0002 |
| `monitoring_window.end_time_s` | 0.0002 |
| `monitoring_window.saved_times_available` | 20.0000 |
| `mesh.mesh_ok` | Yes |
| `mesh.cells` | 63747.0000 |
| `mesh.max_aspect_ratio` | 4.6458 |
| `mesh.max_non_orthogonality` | 57.5700 |
| `mesh.average_non_orthogonality` | 15.3135 |
| `mesh.max_skewness` | 1.1504 |
| `solver.checked` | Yes |
| `solver.failure_detected` | No |
| `solver.failure_markers` | [] |
| `solver.completed_normally` | Yes |
| `solver.log` | /mnt/c/Backup from one drive/Desktop/Research/physics-constrained-cfd-agent/runs/20260914_020146_conical_nozzle/openfoam/log.foamRun |
| `flow.inlet_mass_flow_kg_s` | -1.5020 |
| `flow.outlet_mass_flow_kg_s` | 0.7394 |
| `flow.mass_imbalance_pct` | 50.7713 |
| `flow.outlet_pressure_pa` | 191,411.950 |
| `flow.outlet_temperature_k` | 296.2627 |
| `flow.outlet_velocity_vector_mps` | [84.4826056, 0.26182483, 0.0308201754] |
| `flow.outlet_velocity_mps` | 84.4830 |
| `flow.outlet_mach` | 0.2449 |
| `global_field_validity.pressure.min.value` | 185,670.899 |
| `global_field_validity.pressure.min.location_m` | [0.245449174, -0.0237526408, 0.0223045399] |
| `global_field_validity.pressure.min.cell` | 33056.0000 |
| `global_field_validity.pressure.max.value` | 227,003.413 |
| `global_field_validity.pressure.max.location_m` | [0.121267952, 0.000724299803, -0.0352047219] |
| `global_field_validity.pressure.max.cell` | 62752.0000 |
| `global_field_validity.temperature.min.value` | 293.7101 |
| `global_field_validity.temperature.min.location_m` | [0.242140345, 0.0120835703, 0.0294274221] |
| `global_field_validity.temperature.min.cell` | 25520.0000 |
| `global_field_validity.temperature.max.value` | 310.9631 |
| `global_field_validity.temperature.max.location_m` | [0.121267952, 0.000724299803, -0.0352047219] |
| `global_field_validity.temperature.max.cell` | 62752.0000 |
| `global_field_validity.density.min.value` | 2.2025 |
| `global_field_validity.density.min.location_m` | [0.242330747, 0.0308709048, -0.0102095005] |
| `global_field_validity.density.min.cell` | 62087.0000 |
| `global_field_validity.density.max.value` | 2.5436 |
| `global_field_validity.density.max.location_m` | [0.121267952, 0.000724299803, -0.0352047219] |
| `global_field_validity.density.max.cell` | 62752.0000 |
| `global_field_validity.positive_pressure` | Yes |
| `global_field_validity.positive_temperature` | Yes |
| `global_field_validity.positive_density` | Yes |
| `stationarity.enough_samples` | Yes |
| `stationarity.checks.mass_imbalance` | No |
| `stationarity.checks.outlet_mass_flow_stationary` | No |
| `stationarity.checks.outlet_pressure_stationary` | Yes |
| `stationarity.checks.outlet_temperature_stationary` | Yes |
| `stationarity.checks.outlet_velocity_stationary` | No |
| `stationarity.passes_all_monitored_metrics` | No |
| `stationarity.outlet_mass_flow.samples` | 5.0000 |
| `stationarity.outlet_mass_flow.window_samples` | 5.0000 |
| `stationarity.outlet_mass_flow.latest` | 0.7394 |
| `stationarity.outlet_mass_flow.window_min` | 0.7394 |
| `stationarity.outlet_mass_flow.window_max` | 0.7504 |
| `stationarity.outlet_mass_flow.window_mean` | 0.7449 |
| `stationarity.outlet_mass_flow.relative_range_pct` | 1.4771 |
| `stationarity.outlet_mass_flow.relative_drift_pct` | -1.4662 |
| `stationarity.outlet_pressure.samples` | 5.0000 |
| `stationarity.outlet_pressure.window_samples` | 5.0000 |
| `stationarity.outlet_pressure.latest` | 191,411.950 |
| `stationarity.outlet_pressure.window_min` | 191,411.950 |
| `stationarity.outlet_pressure.window_max` | 191,911.097 |
| `stationarity.outlet_pressure.window_mean` | 191,662.731 |
| `stationarity.outlet_pressure.relative_range_pct` | 0.2604 |
| `stationarity.outlet_pressure.relative_drift_pct` | -0.2601 |
| `stationarity.outlet_temperature.samples` | 5.0000 |
| `stationarity.outlet_temperature.window_samples` | 5.0000 |
| `stationarity.outlet_temperature.latest` | 296.2627 |
| `stationarity.outlet_temperature.window_min` | 296.2627 |
| `stationarity.outlet_temperature.window_max` | 296.4826 |
| `stationarity.outlet_temperature.window_mean` | 296.3733 |
| `stationarity.outlet_temperature.relative_range_pct` | 0.0742 |
| `stationarity.outlet_temperature.relative_drift_pct` | -0.0742 |
| `stationarity.outlet_velocity.samples` | 5.0000 |
| `stationarity.outlet_velocity.window_samples` | 5.0000 |
| `stationarity.outlet_velocity.latest` | 84.4830 |
| `stationarity.outlet_velocity.window_min` | 84.4830 |
| `stationarity.outlet_velocity.window_max` | 85.5797 |
| `stationarity.outlet_velocity.window_mean` | 85.0250 |
| `stationarity.outlet_velocity.relative_range_pct` | 1.2898 |
| `stationarity.outlet_velocity.relative_drift_pct` | -1.2815 |
| `throat.geometry.x_start_m` | 0.1500 |
| `throat.geometry.x_center_m` | 0.1550 |
| `throat.geometry.x_end_m` | 0.1600 |
| `throat.geometry.radius_m` | 0.0326 |
| `throat.geometry.exact_area_m2` | 0.0033 |
| `throat.latest_time_s` | 0.0002 |
| `throat.latest_planes.start.area_m2` | 0.0033 |
| `throat.latest_planes.start.pressure_pa` | 211,016.570 |
| `throat.latest_planes.start.temperature_k` | 304.7214 |
| `throat.latest_planes.start.velocity_vector_mps` | [117.62969262307907, 0.033573234999795566, 0.010740584596603181] |
| `throat.latest_planes.start.speed_mps` | 117.8751 |
| `throat.latest_planes.start.mach` | 0.3369 |
| `throat.latest_planes.start.surface_points` | 2679.0000 |
| `throat.latest_planes.start.surface_polygons` | 3963.0000 |
| `throat.latest_planes.start.requested_time_s` | 0.0002 |
| `throat.latest_planes.start.actual_diagnostic_time_s` | 0.0002 |
| `throat.latest_planes.start.used_time_fallback` | No |
| `throat.latest_planes.start.cut_plane_vtk_path` | postProcessing/cutPlaneSurface(point=(0.1500),normal=(100),fields=(pTU))/0.000200004930555/cutPlane.vtk |
| `throat.latest_planes.start.x_m` | 0.1500 |
| `throat.latest_planes.start.area_error_pct_vs_exact_geometry` | 0.0620 |
| `throat.latest_planes.center.area_m2` | 0.0033 |
| `throat.latest_planes.center.pressure_pa` | 209,217.161 |
| `throat.latest_planes.center.temperature_k` | 303.9746 |
| `throat.latest_planes.center.velocity_vector_mps` | [117.5028972257193, -0.03821324703616534, 0.07726236610599979] |
| `throat.latest_planes.center.speed_mps` | 117.5703 |
| `throat.latest_planes.center.mach` | 0.3364 |
| `throat.latest_planes.center.surface_points` | 2691.0000 |
| `throat.latest_planes.center.surface_polygons` | 3966.0000 |
| `throat.latest_planes.center.requested_time_s` | 0.0002 |
| `throat.latest_planes.center.actual_diagnostic_time_s` | 0.0002 |
| `throat.latest_planes.center.used_time_fallback` | No |
| `throat.latest_planes.center.cut_plane_vtk_path` | postProcessing/cutPlaneSurface(point=(0.15500),normal=(100),fields=(pTU))/0.000200004930555/cutPlane.vtk |
| `throat.latest_planes.center.x_m` | 0.1550 |
| `throat.latest_planes.center.area_error_pct_vs_exact_geometry` | 0.0537 |
| `throat.latest_planes.end.area_m2` | 0.0033 |
| `throat.latest_planes.end.pressure_pa` | 207,476.420 |
| `throat.latest_planes.end.temperature_k` | 303.2189 |
| `throat.latest_planes.end.velocity_vector_mps` | [116.56878942391829, -0.009259626300513751, 0.022023344306598025] |
| `throat.latest_planes.end.speed_mps` | 116.5898 |
| `throat.latest_planes.end.mach` | 0.3340 |
| `throat.latest_planes.end.surface_points` | 2684.0000 |
| `throat.latest_planes.end.surface_polygons` | 3979.0000 |
| `throat.latest_planes.end.requested_time_s` | 0.0002 |
| `throat.latest_planes.end.actual_diagnostic_time_s` | 0.0002 |
| `throat.latest_planes.end.used_time_fallback` | No |
| `throat.latest_planes.end.cut_plane_vtk_path` | postProcessing/cutPlaneSurface(point=(0.1600),normal=(100),fields=(pTU))/0.000200004930555/cutPlane.vtk |
| `throat.latest_planes.end.x_m` | 0.1600 |
| `throat.latest_planes.end.area_error_pct_vs_exact_geometry` | 0.0620 |
| `throat.sonic_transition.detected` | No |
| `throat.sonic_transition.x_m` | Not measured |
| `throat.sonic_transition.method` | Not measured |
| `throat.sonic_transition.bracket_x_m` | Not measured |
| `throat.sonic_transition.interpolated_state` | Not measured |
| `throat.sonic_transition.note` | No Mach-1 crossing was detected between the sampled throat planes. |
| `throat.center_stationarity.times_s` | [0.000160004930555, 0.000170004930555, 0.000180004930555, 0.000190004930555, 0.000200004930555] |
| `throat.center_stationarity.pressure.samples` | 5.0000 |
| `throat.center_stationarity.pressure.latest` | 209,217.161 |
| `throat.center_stationarity.pressure.minimum` | 205,998.282 |
| `throat.center_stationarity.pressure.maximum` | 209,217.161 |
| `throat.center_stationarity.pressure.mean` | 207,572.754 |
| `throat.center_stationarity.pressure.relative_range_pct` | 1.5507 |
| `throat.center_stationarity.pressure.relative_drift_pct` | 1.5626 |
| `throat.center_stationarity.temperature.samples` | 5.0000 |
| `throat.center_stationarity.temperature.latest` | 303.9746 |
| `throat.center_stationarity.temperature.minimum` | 302.5982 |
| `throat.center_stationarity.temperature.maximum` | 303.9746 |
| `throat.center_stationarity.temperature.mean` | 303.2723 |
| `throat.center_stationarity.temperature.relative_range_pct` | 0.4539 |
| `throat.center_stationarity.temperature.relative_drift_pct` | 0.4549 |
| `throat.center_stationarity.speed.samples` | 5.0000 |
| `throat.center_stationarity.speed.latest` | 117.5703 |
| `throat.center_stationarity.speed.minimum` | 111.3802 |
| `throat.center_stationarity.speed.maximum` | 117.5703 |
| `throat.center_stationarity.speed.mean` | 114.3910 |
| `throat.center_stationarity.speed.relative_range_pct` | 5.4113 |
| `throat.center_stationarity.speed.relative_drift_pct` | 5.5576 |
| `throat.center_stationarity.mach.samples` | 5.0000 |
| `throat.center_stationarity.mach.latest` | 0.3364 |
| `throat.center_stationarity.mach.minimum` | 0.3194 |
| `throat.center_stationarity.mach.maximum` | 0.3364 |
| `throat.center_stationarity.mach.mean` | 0.3277 |
| `throat.center_stationarity.mach.relative_range_pct` | 5.1829 |
| `throat.center_stationarity.mach.relative_drift_pct` | 5.3169 |
| `throat.interpretation_guardrail` | The sonic transition is detected from area-averaged CFD cut planes. The interpolated sonic state is an estimate between sampled stations and must not be represented as an exact CFD root solve. |
| `thresholds.mass_imbalance_pct_max` | 1.0000 |
| `thresholds.outlet_mass_flow_relative_range_pct_max` | 0.2500 |
| `thresholds.outlet_pressure_relative_range_pct_max` | 0.5000 |
| `thresholds.outlet_temperature_relative_range_pct_max` | 0.5000 |
| `thresholds.outlet_velocity_relative_range_pct_max` | 0.5000 |
| `thresholds.minimum_stationarity_samples` | 4.0000 |
| `thresholds.stationarity_window_samples` | 5.0000 |
| `coverage.global_field_validity_checked` | Yes |
| `coverage.throat_state_checked` | Yes |
| `coverage.note` | Global pressure, temperature, and density extrema are checked. When a geometry manifest is provided, throat entry, center, exit, sonic transition, and recent throat-center history are also extracted. |
| `status` | STABLE_UNCONVERGED |

## Interpretation notes

- Solver completion alone is not treated as evidence of CFD convergence.
- Mesh quality passing alone is not treated as evidence of adequate physical resolution.
- Analytical theory, when available, should be reported separately as post-hoc validation rather than silently used as CFD evidence.
- Full machine-readable evidence and the agent decision are stored beside this report.
