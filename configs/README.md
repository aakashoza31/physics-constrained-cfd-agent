# configs

- `cfd_reasoning_policy_v2.yaml`: the expert reasoning policy for the nozzle
  family. Its raw text is placed verbatim in the system instruction of the nozzle
  diagnosis call (`src/agents/theory_blind_cfd_agent.py`), so the file is kept
  byte for byte as used in the archived sessions; notes about it live here
  rather than as comments inside it.
  The policy lists three supported nozzle families (`conical`, `smooth_cosine`,
  `bell`). Only the conical nozzle is demonstrated in the CFD Forge paper; the
  other two are named in the policy and in the nozzle design agent's vocabulary
  but have no archived run in the paper.
- `nozzles/`: the nozzle case configurations (see `nozzles/README.md`).
- `forward_step/`: 3-D extruded forward-step development configurations; not part
  of the CFD Forge paper (see `forward_step/README.md`).
- `families/airfoil/`: asset lock for the NACA0012 development family; not part
  of the CFD Forge paper.
