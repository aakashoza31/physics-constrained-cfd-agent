# Field-evolution videos

The shared report builder (`src/reporting/`) produces plots, static contours,
field movies rendered from saved CFD fields, a history animation, and then the
engineering report. `scripts/run_agent.py` calls this builder after the
deterministic authority finishes. Live runner evidence supplies `runtime_case`,
which is passed to reporting as `raw_case`. Rendering does not change any family
runner, CFD gate, model, boundary condition or discretization. The cube is a
diagnostic study and is not routable for live acceptance.

## Outputs and status

`video/summary_evolution.mp4` is the primary movie. `simulation.mp4` is a byte-for-byte
compatibility copy of that summary. Individual movies use the names
`pressure_evolution.mp4`, `velocity_evolution.mp4`, `mach_evolution.mp4`,
`temperature_evolution.mp4`, and, when present at every selected time,
`density_evolution.mp4`, `turbulence_evolution.mp4` (k), and
`turbulent_viscosity_evolution.mp4` (nut). Cube additionally renders
`wake_evolution.mp4`, the spanwise component of solved U on a horizontal mid-height
slice. It is not a newly solved or inferred turbulence field.

Force/shock-front animations are named `history_evolution.mp4` (GIF fallback if no
host encoder exists). They are never used as `simulation.mp4`. A compact archive's
existing history movie can be copied under the new name only if its old metadata
explicitly identifies it as a non-field animation.

Each report includes `video_manifest.json` and `visualization_status.json`.
Missing tools, raw fields, required arrays, or failed rendering give
`VISUALIZATION_INCOMPLETE`. A request with no executed CFD (including airfoil's
mesh rejection) gives `VIDEO_NOT_AVAILABLE_CFD_NOT_RUN`. The report's
`artifact_complete` flag is separate from its unchanged ACCEPT/REJECT/INCONCLUSIVE
decision. An artifact failure does not erase the scientific decision.

## Scientific rendering contract

- Read numeric on-disk time directories; intersect availability across processor
  partitions when reading decomposed cases. At most 100 actual times are selected
  at uniform indices, including both endpoints. There is no interpolation or
  fabricated intermediate state. Nonuniform time spacing is recorded.
- Explicitly enable and refresh the reader's zero-time discovery. Check its
  reported times against the selected directory times. Labels retain the actual
  directory times; steady-state dictionaries are labelled iterations.
- First pass measures global cell-field ranges over **all selected times on the
  rendered dataset**. For cube this means the fixed slice, not the entire volume.
  Second pass uses exactly those ranges and one fixed camera. Constant-valued
  fields get a documented small display-range expansion.
- ParaView `ColorBy` can reset color limits even with automatic rescaling disabled.
  Reapply the same global limits after every switch and assert the actual LUT
  endpoints after every screenshot. Save those observations in the manifest.
- Mach is read if available throughout; otherwise derive it only for explicitly
  supported constant-heat-capacity perfect-gas dictionaries using
  `mag(U)/sqrt(gamma*R*T)`. Record the formula and coefficient. Other thermodynamics
  fail the required-Mach check instead of assuming air properties.
- Root case, mesh and time directories are never modified. The reader gets a
  temporary symlink view. Foundation-v14 initial `[velocity]`, `[pressure]` and
  `[temperature]` dimension aliases are translated into equivalent numeric
  dimensions only in private t=0 copies for ParaView 5.11 compatibility. Field
  values are unchanged and input hashes are recorded. Unknown aliases fail.
- Hash source configuration and mesh before/after; reject a changing snapshot.
  The manifest records output MP4 hashes, tool versions, fixed camera/slice,
  actual times, field ranges, cadence, and live versus archived provenance.
- `contact_sheet.png` is decoded from the resulting summary MP4 (first, middle,
  last frames). Static final contours are also supplied from the final real frame.

## Dependencies and reproduction

On Linux install ParaView's `pvpython`, FFmpeg and, for GLX builds without a usable
display, Xvfb. On Windows with native WSL cases the wrapper
(`src/reporting/field_video.py`) calls
`wsl -d <distro> -- xvfb-run -a env LIBGL_ALWAYS_SOFTWARE=1 pvpython ...`.

Two environment variables name a WSL distribution, both defaulting to
`Ubuntu-24.04`:

| Variable | Read by | Used for |
|---|---|---|
| `CFD_WSL_DISTRO` | `src/reporting/field_video.py` (also `src/pipeline/airfoil/cgns.py`) | launching ParaView for field videos |
| `OPENFOAM_WSL_DISTRO` | `src/openfoam/executor.py`, `src/pipeline/foam_runtime.py`, `src/cfd/diagnostics.py` | running OpenFOAM (with `OPENFOAM_BASHRC`) |

Set both to the same distribution when ParaView and OpenFOAM are installed
together. `CFD_PVPYTHON` overrides the native renderer; `CFD_FFMPEG` supplies a
renderer-side encoder path. Python dependencies
are in `requirements.txt`; optional `imageio-ffmpeg` supplies the host-side history
encoder when FFmpeg is absent from PATH. Missing tools are reported, not installed
automatically during a user run.

From the repository root, normal live prompts need no extra video command:

```text
python scripts/run_agent.py --mode live --i-want-to-run-cfd --family nozzle --prompt "<registered engineering request>" --out runs/my_run
```

To reproduce movies and reports from existing fields without rerunning CFD:

```text
python scripts/report_existing_fields.py --family nozzle --case canonical_reference --raw-case <existing-nozzle-case> --out outputs/field_videos/nozzle
python scripts/report_existing_fields.py --family forward_step_2d --case mach20_canonical --raw-case <existing-Mach2-case> --out outputs/field_videos/forward_step
python scripts/report_existing_fields.py --family cube --case drifting_wake --raw-case <existing-cube-case> --out outputs/field_videos/cube
python scripts/report_existing_fields.py --family airfoil --case mesh_rejection --out outputs/field_videos/airfoil
```

For a standalone renderer invocation, prepare a JSON metadata file containing
`family`, registered `case`, `verdict`, `solver_invoked` (for this invocation), and
`source_kind` (`live` or `archived_raw_fields`), then:

```text
xvfb-run -a env LIBGL_ALWAYS_SOFTWARE=1 pvpython --force-offscreen-rendering src/reporting/paraview_field_video.py --case <case> --out <output> --metadata <metadata.json>
```

Use this only to visualize an already established verdict; it cannot certify CFD.
The report command obtains the verdict from registered evidence instead.

## Retention audit and limitations

The frozen nozzle writes every 0.00025 time units with `purgeWrite 0`; the canonical
run retains 25 directories from 0 through 0.006. Mach-2 step writes every 0.1 with
`purgeWrite 0`, retaining 41 directories through 4. No output controls needed edits.
The cube has 59 common decomposed times from 2 through 80, with changing historical
cadence. Its movie cannot show a missing t=0 startup. The nozzle was initialized
near its solution, so its true startup is subtle; it must not be dramatized.

The fixed cube view assumes this registered geometry: H=1, y=0.5 slice, x downstream,
z spanwise. Its visual wake development does not establish stationarity or
experimental agreement. The scalar color range covers the whole slice even though
the camera focuses on the cube and near wake. Movie playback at 8 fps is a sequence
of saved states, not real-time playback. Missing-at-some-times optional fields are
omitted instead of synthesized. These are rendering choices, not CFD corrections.

The retained raw fields remain external assets. Portable manifests use
`external-case://<basename>` with a case identifier and content hashes; local
reproduction commands provide the actual paths. No private absolute paths belong
in committed provenance.
