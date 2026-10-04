# CAD / STEP input

**Status: the interface exists; no family accepts STEP geometry.** A STEP file is
read, classified and then refused, without launching CFD. That is the designed
behaviour, not a missing feature to be worked around.

## What happens to a STEP file

```bash
python scripts/run_agent.py --prompt "analyse this part" --geometry part.step
```

1. `src/geometry/step_reader.py` confirms the ISO-10303-21 header and reads the
   schema, the file name and the entity histogram. This is text parsing and
   needs no CAD kernel.
2. It reports which CAD backends are importable (`OCP`, `OCC`, `cadquery`).
   Typically none is.
3. `src/geometry/features.py` returns `UNSUPPORTED_GEOMETRY` with the reason. It
   does **not** estimate a bounding box or a characteristic dimension from the
   entity counts.
4. `src/geometry/matching.py` finds no family declaring `step: true`.
5. The pipeline returns **INCONCLUSIVE / UNSUPPORTED**, with
   `solver_invoked: false`.

The geometry gate is recorded as *unresolved*, not *failed*: the system is not
claiming the part is unsuitable, only that it cannot judge it.

## What would have to be true for STEP to work

1. a CAD kernel present and able to load the solid;
2. feature extraction producing the dimensions a family's envelope is written in;
3. a family declaring `step: true` **and** a mesher able to mesh that solid to the
   family's frozen mesh contract;
4. the frozen quality gates passing on the resulting mesh.

Item 4 is the hard one. The NACA0012 airfoil mesh study (not part of the CFD Forge
paper) is an example: even with an analytically exact geometry and a
purpose-built mesher, every candidate mesh failed the frozen contract. Arbitrary
CAD is strictly harder.

## The CAD→Gmsh prototype

Before the registered nozzle family existed, a less constrained prototype
generated the nozzle geometry through a CAD→Gmsh path (`src/cad/`,
`src/meshing/`, `src/openfoam/`, `src/agents/nozzle_design_agent.py`), with the
model choosing the meshing strategy. Its archived run ended at t = 0.2 ms with
status `STABLE_UNCONVERGED` and a 50.8% mass-flow imbalance; the paper describes
it in its reproducibility appendix as the record that motivated the registered
contracts. The prototype is kept for provenance, is not part of the registered
path, and does not accept STEP input through `scripts/run_agent.py`. Carrying the
Gmsh path through to a solution that passes registered checks is future work.

## What this system does not claim

It does not claim that arbitrary CAD geometry can be simulated, and no family
accepts STEP geometry. It claims that
unsupported geometry is refused cleanly, early, and with a reason — which is the
property an engineering user actually needs from an autonomous tool.
