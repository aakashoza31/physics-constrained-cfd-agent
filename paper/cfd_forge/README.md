# CFD Forge: A Physics-Constrained Agentic Framework for Autonomous CFD

Aakash Shailesh Oza, Ryan F. Johnson, Amir Barati Farimani
Department of Mechanical Engineering, Carnegie Mellon University

This directory holds the paper source, the figures, the evidence the figures
read, and the scripts that produce them.

| Path | Contents |
|---|---|
| `main.tex` | Manuscript (single file; the bibliography is inline). |
| `main.pdf` | Compiled manuscript. |
| `figures/` | Figure files (PDF used by the paper; PNG previews). |
| `data/` | Verbatim copies of the archived evidence the figure scripts read, plus the call statistics and session ledger. |
| `scripts/` | Figure, statistics and analysis scripts (below). |
| `EVIDENCE_MAP.md` | Every numerical claim in the paper with its source file and key. |

## Building the PDF

`main.tex` includes figures as `Figures/<name>.pdf`, while the directory in
this repository is `figures/`. Before building, provide `Figures/` next to
`main.tex` as a copy of, or a symbolic link to, `figures/`:

```
cd paper/cfd_forge
ln -s figures Figures          # Windows: mklink /D Figures figures, or copy the folder
latexmk -pdf main.tex
```

Alternatively, upload `main.tex` and the figure files to Overleaf in a folder
named `Figures/`. The packages used are standard (graphicx, booktabs,
tabularx, amsmath, hyperref, authblk, xcolor, placeins, geometry).

## Figures and the scripts that produce them

Run the scripts from `paper/cfd_forge/` with Python 3, NumPy and Matplotlib.
They read only `data/` and write to `figures/`; no CFD is run.

| Figure file(s) | Paper figure | Script |
|---|---|---|
| `fig1_workflow.pdf` | Conceptual workflow illustration (AI-generated, `data/fig1_concept/`) linked to the archived OpenFOAM fields | `scripts/make_fig1_workflow.py` |
| `fig_agent_loop.pdf` | Agent loop as implemented, with call counts | `scripts/make_agent_loop_figure.py` |
| `fig_agent_stats.pdf` | Model calls by stage; proposals and rulings | `scripts/make_mesh_field_figures.py` |
| `fig_mesh_nozzle.pdf` | Nozzle wedge mesh and prototype Gmsh surface | `scripts/make_mesh_field_figures.py` |
| `fig_mesh_step_cube.pdf` | Step and cube meshes from the native polyMesh | `scripts/make_mesh_field_figures.py` |
| `fig_nozzle_fields.pdf` | Nozzle Mach, p, T at 6 ms | `scripts/make_mesh_field_figures.py` |
| `fig_step_evolution.pdf` | Step Mach number at t = 0.5, 1, 2, 4 | `scripts/make_mesh_field_figures.py` |
| `fig3_nozzle.pdf` | Nozzle profiles vs. quasi-1-D theory; stationarity metrics | `scripts/make_figures.py` |
| `fig4_step.pdf` | Mach-2 step fields, front position, mass closure | `scripts/make_figures.py` |
| `fig5_cube.pdf` | Cube diagnostic study (field, drag, lateral force, cycles) | `scripts/make_figures.py` |
| `fig2_configurations.*` | not used in the paper | `scripts/make_figures.py` |
| `fig_cube_wake.pdf` | not used in the paper | `scripts/make_mesh_field_figures.py` |

The scripts also write PNG versions next to each PDF. Regenerated PDFs differ
from the committed ones only in their creation date.

## Data

`data/` contains verbatim copies of archived evidence, grouped by study:
`nozzle/` (canonical run), `nozzle_continuation/` (continuation run), `step/`
(Mach-2 forward step and two decision logs), `cube/` (force history,
registered gate result, audit tables, mesh files and logs), `frames/`
(ParaView renders of native fields with their video manifests), `gmsh/` and
`prototype/` (records of the prototype CAD-to-Gmsh run, which is not an agent
result). `data/DATA_MANIFEST.json` lists the source and SHA-256 of every file;
sources are labelled `archive (Zenodo)`, `verification package (Zenodo)`,
`repo`, or `workstation output (not released)` when the copy in `data/` is the
only released copy.

Two files are derived from the session archive rather than copied:

- `data/agent_stats.json`: model calls by stage, latencies, proposals and
  rulings for the 19 archived agent sessions, from
  `scripts/recount_agent_calls.py` (the fields `note` and `model` are written
  by hand).
- `data/session_ledger.json`: one entry per session with its per-stage call
  counts (additive over sessions, 74 text calls), proposals in chronological
  order, final status and the paper's ledger row and decision; statuses and
  proposal order are recomputed by `scripts/ledger_statuses.py`.

## Scripts that need the session archive

The agent sessions, the cube solver logs and the verification package are in
the session archive on Zenodo (https://doi.org/10.5281/zenodo.23148676). These scripts read
it:

| Script | Needs | Purpose |
|---|---|---|
| `recount_agent_calls.py --demo <archive>/demo [--out file]` | archive `demo/` | Recounts calls, proposals and rulings (`data/agent_stats.json`). |
| `ledger_statuses.py --demo <archive>/demo [--check]` | archive `demo/` | Recomputes ledger statuses and proposal order. |
| `scan_agent_sessions.py` | archive `demo/` | Superseded event-stream count (82 calls / 23 proposals); kept for reference. |
| `cube_llm_diagnosis.py --logs <archive>/CFD_Verification_Package_20260929/03_cube/logs` | verification package, Gemini API key | Model diagnosis of the cube evidence (records in `evidence/cube/drifting_wake/llm_diagnosis/`). |
| `controller_comparison.py --demo-root <archive>/demo --cube-logs <...>/03_cube/logs` | archive `demo/`, verification package, Gemini API key | Controller comparison (records in `evidence/controller_comparison/`). |
| `extract_native_fields.py` | native cube case (Zenodo data archive, `native_cases/cube/campaign_t4_retry2/`) | Extracts mesh geometry used for `data/cube/cube_mesh_only.npz`. |

`cube_llm_diagnosis.py` and `controller_comparison.py` also accept the
locations through the environment variables `CFD_FORGE_CUBE_LOGS` and
`CFD_FORGE_DEMO`. Model outputs are not reproducible byte for byte; the
archived records are the reference.
