# Nozzle case declarations

These YAML files document the three demonstrated cases and a nearby-case template.

- `case_A_reference.yaml`: canonical geometry, p0 = 200 kPa.
- `case_B_geometry.yaml`: same physics/conditions with exit radius 0.0370 m.
- `case_C_conditions.yaml`: canonical geometry with p0 = 220 kPa.
- `case_template.yaml`: starting point for a nearby extension.

The natural-language prompt is the primary agent entry point. The YAML files make the internal engineering specification easy to audit.

Before changing values, read `docs/PARAMETER_GUIDE.md`. The software scope gate is wider than the A/B/C evidence and should not be mistaken for a validated-accuracy envelope.

The 30 kPa ambient pressure is external-environment metadata. It is not automatically imposed as fixed static pressure at the computational outlet.
