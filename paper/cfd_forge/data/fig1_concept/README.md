# Figure 1 conceptual illustration

`concept_illustration.png` is the top panel of Figure 1. It is an AI-generated
conceptual illustration of the CFD Forge workflow, supplied by the authors and
used unchanged apart from two edits made in `scripts/make_fig1_workflow.py`:
a screenshot border is cropped, and the "Mach-2 step" schematic tile, which in
the supplied image showed a backward-facing step, is replaced by a
forward-facing-step schematic drawn by the script (`ffs_tile`), consistent with
the simulated case (curved shock standing upstream of the step face). Its flow pictures (nozzle, step and cube
tiles, the "Solve" contour, the streamlines) are schematic and are not
simulation output. The real OpenFOAM fields shown under it come from the
archived ParaView frames in `../frames/`. The paper's caption and
acknowledgements state that the illustration is AI-generated.
