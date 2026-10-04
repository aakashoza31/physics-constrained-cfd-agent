# configs/forward_step

Not part of the CFD Forge paper; experimental development configurations.

These YAML files are 3-D extruded forward-step development configurations
(`family: forward_step_3d`, inviscid Euler, cyclic span). They are experimental
and are not used by any run reported in the paper.

- `case_A_reference.yaml`: the default 3-D spec (`src/pipeline/forward_step/spec.py`);
  loaded by `tests/forward_step/test_family.py`.
- `case_B_step_height.yaml`, `case_C_mach.yaml`, `case_D_span.yaml`: single-parameter
  overrides of the reference spec.

They are distinct from the paper's 2-D forward-step family (`cases/forward_step/`),
which is driven by natural-language requests (`examples/forward_step_2d/`) through
`scripts/run_forward_step_2d.py` and has no YAML config.
