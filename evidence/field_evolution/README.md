# Verified field-video evidence

These records were produced from archived native OpenFOAM fields on 2026-09-28.
No CFD was rerun. Full MP4s and reports are local generated artifacts under
`outputs/field_videos/{nozzle_final,forward_step_final,cube_final}`; they are not
embedded in Git. SHA-256 hashes in these manifests bind the movies to this audit.
Reproduction instructions: `docs/field_evolution_video.md`.

| Case | Times | Frames | Verdict unchanged | Movie audit |
|---|---|---:|---|---|
| Canonical nozzle | 0 through 0.006 | 25 | ACCEPT | PASS |
| Mach-2 forward step | 0 through 4 | 41 | ACCEPT | PASS |
| Cube | 2 through 80 | 59 | REJECT | PASS |
| Airfoil | CFD not run | 0 | REJECT | VIDEO_NOT_AVAILABLE_CFD_NOT_RUN |

All actual output videos were fully decoded with FFmpeg; FFprobe verified frame
counts. Per-frame LUT endpoints match their global registered rendering ranges.
The summary and compatibility simulation.mp4 files are byte-identical. Contact
sheets were decoded from the actual summary movies. First, intermediate and final
field images were visually inspected; no scientific verdict was inferred from them.

Tests: 560 passed, 10 skipped, 17 subtests passed. The relevant suites covered
consolidated reporting/orchestration, architecture, nozzle, and both step modules.
The Windows-only path separator assertion was corrected without changing its test
meaning. One new symlink-shadow unit test is skipped on Windows; the actual WSL
renderer exercised that path, including the step's t=0 named-dimension translation.

The cube's global native spanwise-velocity range includes its strong near-body
crossflow. Weak late antisymmetric-mode growth is better assessed with the retained
force history; this movie is neither stationarity certification nor DNS validation.
The nozzle's initial state was already close to its final solution. No dramatic
startup is fabricated. Optional density is omitted from the common-time movies
because the initial directories do not retain it; temperature is included.
