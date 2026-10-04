#!/usr/bin/env python3
"""What each family can actually accept, declared rather than assumed.

A capability declaration is a PROMISE THE CODE KEEPS. Nothing here advertises an
input a family cannot process: `step: false` means a STEP file routed to that
family is refused before any mesh or solver is touched, and there is no code path
that reinterprets it as parametric input.

Read with `capabilities(name)`; the whole table is `TABLE`.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Mapping, Tuple

# The action vocabularies are taken from the enums the agent paths validate
# against, so the declaration cannot drift from the code. Neither module imports
# src.families, so there is no import cycle.
from src.contracts.agent_decision import AgentAction
from src.reasoning.forward_step_actions import ForwardStepAction

#: Lifecycle status of a family in the frozen scope.
ACCEPTED = "ACCEPTED"                 # registered, routable
RUNTIME_REJECTED = "RUNTIME_REJECTED"  # executed, deterministically rejected
SUPPLEMENTARY = "SUPPLEMENTARY"       # preserved evidence only, never routable
NOT_IMPLEMENTED = "NOT_IMPLEMENTED"   # declared for completeness, no implementation


@dataclass(frozen=True)
class GeometryInputs:
    """Which geometry sources the family genuinely accepts."""

    parametric: bool
    step: bool
    #: Why STEP is unsupported, when it is. Stated so the refusal is explainable.
    step_note: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {"parametric": self.parametric, "step": self.step,
                "step_note": self.step_note}


@dataclass(frozen=True)
class Physics:
    compressible: bool
    turbulent: bool
    transient: bool
    dimensionality: str
    model: str

    def to_dict(self) -> Dict[str, Any]:
        return {"compressible": self.compressible, "turbulent": self.turbulent,
                "transient": self.transient, "dimensionality": self.dimensionality,
                "model": self.model}


@dataclass(frozen=True)
class FamilyCapabilities:
    """One family's advertised contract."""

    name: str
    status: str
    geometry_inputs: GeometryInputs
    physics: Physics
    allowed_actions: Tuple[str, ...]
    #: Characteristic dimension used to normalise an incoming geometry.
    characteristic_dimension: str
    #: Admissible envelope, as registered. Free-form per family, always declared.
    envelope: Mapping[str, Any] = field(default_factory=dict)
    #: Registered case identifiers under cases/<name>/.
    cases: Tuple[str, ...] = ()
    solver: str = ""
    notes: str = ""

    @property
    def routable(self) -> bool:
        """Only ACCEPTED families may reach a solver through the agent."""
        return self.status == ACCEPTED

    def accepts_step(self) -> bool:
        return self.geometry_inputs.step

    def to_dict(self) -> Dict[str, Any]:
        return {
            "family": self.name,
            "status": self.status,
            "routable": self.routable,
            "geometry_inputs": self.geometry_inputs.to_dict(),
            "physics": self.physics.to_dict(),
            "allowed_actions": list(self.allowed_actions),
            "characteristic_dimension": self.characteristic_dimension,
            "envelope": dict(self.envelope),
            "cases": list(self.cases),
            "solver": self.solver,
            "notes": self.notes,
        }


_NO_STEP = (
    "this family meshes a parametric geometry it generates itself; no STEP "
    "import, healing or feature-recognition path is implemented for it"
)

TABLE: Dict[str, FamilyCapabilities] = {
    "nozzle": FamilyCapabilities(
        name="nozzle",
        status=ACCEPTED,
        geometry_inputs=GeometryInputs(parametric=True, step=False, step_note=_NO_STEP),
        physics=Physics(compressible=True, turbulent=False, transient=False,
                        dimensionality="axisymmetric 5° wedge",
                        model="inviscid compressible (Euler), shockFluid"),
        allowed_actions=tuple(a.value for a in AgentAction),
        characteristic_dimension="throat_radius",
        envelope={"regime": "supersonic converging-diverging",
                  "validation": "quasi-1D isentropic consistency (registered checks)"},
        cases=("canonical_reference", "condition_variation", "geometry_variation"),
        solver="OpenFOAM Foundation v14",
        notes="Registered, routable family; ACCEPTED.",
    ),
    "forward_step_2d": FamilyCapabilities(
        name="forward_step_2d",
        status=ACCEPTED,
        geometry_inputs=GeometryInputs(parametric=True, step=False, step_note=_NO_STEP),
        physics=Physics(compressible=True, turbulent=False, transient=True,
                        dimensionality="2-D planar",
                        model="inviscid compressible (Euler), shockFluid"),
        allowed_actions=tuple(a.value for a in ForwardStepAction),
        characteristic_dimension="step_height",
        envelope={"regime": "supersonic forward-facing step",
                  "validation": "registered numerical checks and directional "
                                "compression diagnostics; no reference-field "
                                "comparison"},
        cases=("mach20_canonical", "mach35_variation", "step_height_010",
               "step_height_030_x060", "step_height_030_x100",
               "iterative_correction", "mesh_sensitivity", "live_run"),
        solver="OpenFOAM Foundation v14",
        notes="Registered, routable family; ACCEPTED.",
    ),
    "cube": FamilyCapabilities(
        name="cube",
        status=SUPPLEMENTARY,
        geometry_inputs=GeometryInputs(parametric=True, step=False, step_note=_NO_STEP),
        physics=Physics(compressible=False, turbulent=True, transient=True,
                        dimensionality="3-D",
                        model="incompressible URANS, k-omega SST, "
                              "surface-mounted cube"),
        allowed_actions=("CONTINUE_RUN", "FAIL_SAFELY", "REJECT_UNSUPPORTED"),
        characteristic_dimension="cube_height",
        envelope={"regime": "3-D turbulent flow over a wall-mounted cube",
                  "validation": "not reached: the exploratory run did not satisfy "
                                "the stationarity/development criterion"},
        cases=("drifting_wake",),
        solver="OpenFOAM Foundation v14",
        notes=("Exploratory 3-D turbulent stationarity/development study, run "
               "outside the agent loop; the stationarity gate was registered "
               "retrospectively. The archived run is preserved for provenance, "
               "is not a validated benchmark result, and is not routable for "
               "acceptance."),
    ),
    "airfoil": FamilyCapabilities(
        name="airfoil",
        status=SUPPLEMENTARY,
        geometry_inputs=GeometryInputs(parametric=True, step=False, step_note=_NO_STEP),
        physics=Physics(compressible=False, turbulent=True, transient=False,
                        dimensionality="2-D",
                        model="incompressible RANS k-omega SST, NACA0012"),
        allowed_actions=("FAIL_SAFELY", "REJECT_UNSUPPORTED"),
        characteristic_dimension="chord",
        envelope={"regime": "attached / pre-stall NACA0012",
                  "validation": "NOT REACHED: CFD_NOT_RUN"},
        cases=("mesh_rejection",),
        solver="not executed",
        notes=("Not part of the CFD Forge paper. Supplementary mesh-rejection "
               "case. No CFD was ever run for this family: every candidate mesh "
               "failed the frozen quality contract, so the family is not "
               "routable (register status CORE-PENDING: inspectable, not "
               "executable)."),
    ),
    "backward_step": FamilyCapabilities(
        name="backward_step",
        status=NOT_IMPLEMENTED,
        geometry_inputs=GeometryInputs(parametric=False, step=False,
                                       step_note="no implementation"),
        physics=Physics(compressible=False, turbulent=True, transient=False,
                        dimensionality="2-D", model="not registered"),
        allowed_actions=(),
        characteristic_dimension="step_height",
        envelope={},
        cases=(),
        notes=("Not part of the CFD Forge paper. Adapter skeleton only: the "
               "scientific recipe is unregistered and no CFD has been run, so "
               "the family is not routable (register status CORE-PENDING: "
               "inspectable, not executable)."),
    ),
}

#: Families that may reach a solver through the agent.
ROUTABLE = tuple(name for name, cap in TABLE.items() if cap.routable)
#: Families whose evidence is preserved and replayable but never acceptable.
EVIDENCE_ONLY = tuple(
    name for name, cap in TABLE.items()
    if cap.status in (RUNTIME_REJECTED, SUPPLEMENTARY)
)


#: Short names used by the public CLI and the case library. The register key
#: stays authoritative; an alias never creates a second family.
ALIASES: Dict[str, str] = {"forward_step": "forward_step_2d",
                           "fs2d": "forward_step_2d",
                           "naca0012": "airfoil"}


def resolve(name: str) -> str:
    """Canonical family key for a name or alias. Unknown names pass through."""
    return ALIASES.get(name, name)


def capabilities(name: str) -> FamilyCapabilities:
    name = resolve(name)
    if name not in TABLE:
        raise KeyError(
            f"{name!r} is not a registered family; known families are "
            f"{tuple(TABLE)}"
        )
    return TABLE[name]


def step_capable_families() -> Tuple[str, ...]:
    """Families that genuinely accept STEP input. Currently none -- by design."""
    return tuple(n for n, c in TABLE.items() if c.accepts_step())


def as_table() -> Dict[str, Dict[str, Any]]:
    return {name: cap.to_dict() for name, cap in TABLE.items()}
