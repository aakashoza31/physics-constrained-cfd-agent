# Autonomous CFD Results: level1_testA_autonomous_replay

## Executive summary

- CFD status: **STABLE_UNCONVERGED**
- Final agent diagnosis: **UNCONVERGED**
- Final agent action: **CONTINUE_RUN**
- Agent confidence: **high**
- Mass-flow imbalance: **1.0768 %**
- Stationarity passed: **No**
- Mesh cells: **63747**

### Agent interpretation

The simulation remains numerically stable, physically admissible, and completed normally on the same mesh. Although stationarity checks have not yet passed, the solution is still settling and health metrics remain good without degradation or divergence across continuations. Therefore, continuing the run is justified.

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
| Mass-flow imbalance | 1.0768 % |
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
| `case_wsl` | /home/user/llm_guided_meshing_openfoam_runtime |
| `monitoring_window.start_time_s` | 0.0010 |
| `monitoring_window.end_time_s` | 0.0012 |
| `monitoring_window.saved_times_available` | 44.0000 |
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
| `solver.log` | /mnt/c/Backup from one drive/Desktop/Research/LLM_guided_meshing/runs/20260913_132428_conical_nozzle/level1_testA_autonomous_replay/openfoam/log.foamRun |
| `flow.inlet_mass_flow_kg_s` | -1.5482 |
| `flow.outlet_mass_flow_kg_s` | 1.5316 |
| `flow.mass_imbalance_pct` | 1.0768 |
| `flow.outlet_pressure_pa` | 54725.1856 |
| `flow.outlet_temperature_k` | 208.1724 |
| `flow.outlet_velocity_vector_mps` | [430.3186741, -0.1471585119, -0.3474242227] |
| `flow.outlet_velocity_mps` | 430.3188 |
| `flow.outlet_mach` | 1.4879 |
| `global_field_validity.pressure.min.value` | 47272.6465 |
| `global_field_validity.pressure.min.location_m` | [0.2725389908, -0.03307040039, -0.007500734417] |
| `global_field_validity.pressure.min.cell` | 57504.0000 |
| `global_field_validity.pressure.max.value` | 424,850.384 |
| `global_field_validity.pressure.max.location_m` | [0.001005641152, 0.0294376622, -0.03576988464] |
| `global_field_validity.pressure.max.cell` | 229.0000 |
| `global_field_validity.temperature.min.value` | 200.4817 |
| `global_field_validity.temperature.min.location_m` | [0.2994987898, -0.001379523375, 0.002216651624] |
| `global_field_validity.temperature.min.cell` | 51764.0000 |
| `global_field_validity.temperature.max.value` | 341.2634 |
| `global_field_validity.temperature.max.location_m` | [0.001005641152, 0.0294376622, -0.03576988464] |
| `global_field_validity.temperature.max.cell` | 229.0000 |
| `global_field_validity.density.min.value` | 0.8194 |
| `global_field_validity.density.min.location_m` | [0.2725389908, -0.03307040039, -0.007500734417] |
| `global_field_validity.density.min.cell` | 57504.0000 |
| `global_field_validity.density.max.value` | 4.3377 |
| `global_field_validity.density.max.location_m` | [0.001005641152, 0.0294376622, -0.03576988464] |
| `global_field_validity.density.max.cell` | 229.0000 |
| `global_field_validity.positive_pressure` | Yes |
| `global_field_validity.positive_temperature` | Yes |
| `global_field_validity.positive_density` | Yes |
| `stationarity.enough_samples` | Yes |
| `stationarity.checks.mass_imbalance` | No |
| `stationarity.checks.outlet_mass_flow_stationary` | Yes |
| `stationarity.checks.outlet_pressure_stationary` | Yes |
| `stationarity.checks.outlet_temperature_stationary` | Yes |
| `stationarity.checks.outlet_velocity_stationary` | Yes |
| `stationarity.passes_all_monitored_metrics` | No |
| `stationarity.outlet_mass_flow.samples` | 5.0000 |
| `stationarity.outlet_mass_flow.window_samples` | 5.0000 |
| `stationarity.outlet_mass_flow.latest` | 1.5316 |
| `stationarity.outlet_mass_flow.window_min` | 1.5312 |
| `stationarity.outlet_mass_flow.window_max` | 1.5319 |
| `stationarity.outlet_mass_flow.window_mean` | 1.5316 |
| `stationarity.outlet_mass_flow.relative_range_pct` | 0.0456 |
| `stationarity.outlet_mass_flow.relative_drift_pct` | -0.0178 |
| `stationarity.outlet_pressure.samples` | 5.0000 |
| `stationarity.outlet_pressure.window_samples` | 5.0000 |
| `stationarity.outlet_pressure.latest` | 54725.1856 |
| `stationarity.outlet_pressure.window_min` | 54680.9270 |
| `stationarity.outlet_pressure.window_max` | 54725.1856 |
| `stationarity.outlet_pressure.window_mean` | 54693.0594 |
| `stationarity.outlet_pressure.relative_range_pct` | 0.0809 |
| `stationarity.outlet_pressure.relative_drift_pct` | 0.0688 |
| `stationarity.outlet_temperature.samples` | 5.0000 |
| `stationarity.outlet_temperature.window_samples` | 5.0000 |
| `stationarity.outlet_temperature.latest` | 208.1724 |
| `stationarity.outlet_temperature.window_min` | 208.1343 |
| `stationarity.outlet_temperature.window_max` | 208.1724 |
| `stationarity.outlet_temperature.window_mean` | 208.1504 |
| `stationarity.outlet_temperature.relative_range_pct` | 0.0183 |
| `stationarity.outlet_temperature.relative_drift_pct` | 0.0107 |
| `stationarity.outlet_velocity.samples` | 5.0000 |
| `stationarity.outlet_velocity.window_samples` | 5.0000 |
| `stationarity.outlet_velocity.latest` | 430.3188 |
| `stationarity.outlet_velocity.window_min` | 430.3188 |
| `stationarity.outlet_velocity.window_max` | 430.6663 |
| `stationarity.outlet_velocity.window_mean` | 430.5381 |
| `stationarity.outlet_velocity.relative_range_pct` | 0.0807 |
| `stationarity.outlet_velocity.relative_drift_pct` | -0.0721 |
| `throat.geometry.x_start_m` | 0.1500 |
| `throat.geometry.x_center_m` | 0.1550 |
| `throat.geometry.x_end_m` | 0.1600 |
| `throat.geometry.radius_m` | 0.0326 |
| `throat.geometry.exact_area_m2` | 0.0033 |
| `throat.latest_time_s` | 0.0012 |
| `throat.latest_planes.start.area_m2` | 0.0033 |
| `throat.latest_planes.start.pressure_pa` | 118,269.712 |
| `throat.latest_planes.start.temperature_k` | 258.2336 |
| `throat.latest_planes.start.velocity_vector_mps` | [288.8644087120238, -0.09259104803163444, -0.1536094484331867] |
| `throat.latest_planes.start.speed_mps` | 289.6546 |
| `throat.latest_planes.start.mach` | 0.9001 |
| `throat.latest_planes.start.surface_points` | 2679.0000 |
| `throat.latest_planes.start.surface_polygons` | 3963.0000 |
| `throat.latest_planes.start.requested_time_s` | 0.0012 |
| `throat.latest_planes.start.actual_diagnostic_time_s` | 0.0012 |
| `throat.latest_planes.start.used_time_fallback` | No |
| `throat.latest_planes.start.cut_plane_vtk_path` | postProcessing/cutPlaneSurface(point=(0.1500),normal=(100),fields=(pTU))/0.0012/cutPlane.vtk |
| `throat.latest_planes.start.x_m` | 0.1500 |
| `throat.latest_planes.start.area_error_pct_vs_exact_geometry` | 0.0620 |
| `throat.latest_planes.center.area_m2` | 0.0033 |
| `throat.latest_planes.center.pressure_pa` | 97282.5549 |
| `throat.latest_planes.center.temperature_k` | 244.3365 |
| `throat.latest_planes.center.velocity_vector_mps` | [334.44436431119567, 0.047811309672444825, -0.1089232761067866] |
| `throat.latest_planes.center.speed_mps` | 334.4707 |
| `throat.latest_planes.center.mach` | 1.0693 |
| `throat.latest_planes.center.surface_points` | 2691.0000 |
| `throat.latest_planes.center.surface_polygons` | 3966.0000 |
| `throat.latest_planes.center.requested_time_s` | 0.0012 |
| `throat.latest_planes.center.actual_diagnostic_time_s` | 0.0012 |
| `throat.latest_planes.center.used_time_fallback` | No |
| `throat.latest_planes.center.cut_plane_vtk_path` | postProcessing/cutPlaneSurface(point=(0.15500),normal=(100),fields=(pTU))/0.0012/cutPlane.vtk |
| `throat.latest_planes.center.x_m` | 0.1550 |
| `throat.latest_planes.center.area_error_pct_vs_exact_geometry` | 0.0537 |
| `throat.latest_planes.end.area_m2` | 0.0033 |
| `throat.latest_planes.end.pressure_pa` | 91130.1547 |
| `throat.latest_planes.end.temperature_k` | 240.1994 |
| `throat.latest_planes.end.velocity_vector_mps` | [347.4199162767003, 0.17935962676916975, 0.07221478384654584] |
| `throat.latest_planes.end.speed_mps` | 347.4968 |
| `throat.latest_planes.end.mach` | 1.1188 |
| `throat.latest_planes.end.surface_points` | 2684.0000 |
| `throat.latest_planes.end.surface_polygons` | 3979.0000 |
| `throat.latest_planes.end.requested_time_s` | 0.0012 |
| `throat.latest_planes.end.actual_diagnostic_time_s` | 0.0012 |
| `throat.latest_planes.end.used_time_fallback` | No |
| `throat.latest_planes.end.cut_plane_vtk_path` | postProcessing/cutPlaneSurface(point=(0.1600),normal=(100),fields=(pTU))/0.0012/cutPlane.vtk |
| `throat.latest_planes.end.x_m` | 0.1600 |
| `throat.latest_planes.end.area_error_pct_vs_exact_geometry` | 0.0620 |
| `throat.sonic_transition.detected` | Yes |
| `throat.sonic_transition.x_m` | 0.1530 |
| `throat.sonic_transition.method` | linear_interpolation_between_area_averaged_cut_planes |
| `throat.sonic_transition.bracket_x_m` | [0.15000000000000002, 0.15500000000000003] |
| `throat.sonic_transition.bracket_mach` | [0.900059247219299, 1.0692566935521362] |
| `throat.sonic_transition.interpolation_fraction` | 0.5907 |
| `throat.sonic_transition.interpolated_state.mach` | 1.0000 |
| `throat.sonic_transition.interpolated_state.pressure_pa` | 105,873.117 |
| `throat.sonic_transition.interpolated_state.temperature_k` | 250.0249 |
| `throat.sonic_transition.interpolated_state.speed_mps` | 316.1264 |
| `throat.sonic_transition.interpolated_state.velocity_vector_mps` | [315.7873627696826, -0.009658842934826897, -0.12721443008046693] |
| `throat.center_stationarity.times_s` | [0.001, 0.00105, 0.0011, 0.00115, 0.0012] |
| `throat.center_stationarity.pressure.samples` | 5.0000 |
| `throat.center_stationarity.pressure.latest` | 97282.5549 |
| `throat.center_stationarity.pressure.minimum` | 97255.3456 |
| `throat.center_stationarity.pressure.maximum` | 97282.5549 |
| `throat.center_stationarity.pressure.mean` | 97265.9939 |
| `throat.center_stationarity.pressure.relative_range_pct` | 0.0280 |
| `throat.center_stationarity.pressure.relative_drift_pct` | 0.0207 |
| `throat.center_stationarity.temperature.samples` | 5.0000 |
| `throat.center_stationarity.temperature.latest` | 244.3365 |
| `throat.center_stationarity.temperature.minimum` | 244.3218 |
| `throat.center_stationarity.temperature.maximum` | 244.3452 |
| `throat.center_stationarity.temperature.mean` | 244.3341 |
| `throat.center_stationarity.temperature.relative_range_pct` | 0.0096 |
| `throat.center_stationarity.temperature.relative_drift_pct` | 0.0004 |
| `throat.center_stationarity.speed.samples` | 5.0000 |
| `throat.center_stationarity.speed.latest` | 334.4707 |
| `throat.center_stationarity.speed.minimum` | 334.4192 |
| `throat.center_stationarity.speed.maximum` | 334.4707 |
| `throat.center_stationarity.speed.mean` | 334.4407 |
| `throat.center_stationarity.speed.relative_range_pct` | 0.0154 |
| `throat.center_stationarity.speed.relative_drift_pct` | 0.0119 |
| `throat.center_stationarity.mach.samples` | 5.0000 |
| `throat.center_stationarity.mach.latest` | 1.0693 |
| `throat.center_stationarity.mach.minimum` | 1.0691 |
| `throat.center_stationarity.mach.maximum` | 1.0693 |
| `throat.center_stationarity.mach.mean` | 1.0692 |
| `throat.center_stationarity.mach.relative_range_pct` | 0.0179 |
| `throat.center_stationarity.mach.relative_drift_pct` | 0.0128 |
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
