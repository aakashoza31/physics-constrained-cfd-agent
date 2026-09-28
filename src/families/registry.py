#!/usr/bin/env python3
"""The family register: the deterministic list of what this system may attempt.

The router may only dispatch to a family that is registered here AND whose
status is routable. Everything else is REJECT / NO_REGISTERED_FAMILY. The
register also records families kept as evidence but deliberately not accepted
as core, so their status is auditable rather than implicit.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from src.families.base import (
    CORE,
    CORE_PENDING,
    EXECUTABLE_STATUSES,
    NONACCEPTED,
    STATUSES,
    SUPPORTING,
)


@dataclass(frozen=True)
class FamilyRecord:
    name: str
    status: str
    physics: str
    #: One-line description used by the router prompt. Declarative.
    description: str
    #: Phrases that positively indicate this family. Declarative.
    keywords: tuple = ()
    #: Lazy adapter factory; None for families with no executable adapter.
    factory: Optional[Callable[[], Any]] = None
    #: Why a non-core family is retained.
    retained_as: str = ""
    #: Repository-relative path to tracked evidence, or None when none exists.
    #: Never an absolute path: a register entry must mean the same thing in a
    #: reviewer's clone as it does on the machine that wrote it.
    evidence_root: Optional[str] = None
    notes: str = ""

    @property
    def routable(self) -> bool:
        """May a request be dispatched here for EXECUTION?

        Only CORE. A CORE-PENDING family is visible in the register and its
        adapter is constructible for inspection, but it may not be routed to,
        because its scientific recipe is not registered and so no result it
        produced could be accepted.
        """
        return self.status in EXECUTABLE_STATUSES and self.factory is not None

    @property
    def inspectable(self) -> bool:
        """May its adapter and recipe be constructed and printed?"""
        return self.factory is not None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status,
            "physics": self.physics,
            "description": self.description,
            "keywords": list(self.keywords),
            "routable": self.routable,
            "inspectable": self.inspectable,
            "has_adapter": self.factory is not None,
            "retained_as": self.retained_as,
            "evidence_root": self.evidence_root,
            "notes": self.notes,
        }


_REGISTER: Dict[str, FamilyRecord] = {}


def register(record: FamilyRecord) -> FamilyRecord:
    if record.status not in STATUSES:
        raise ValueError(f"unknown family status {record.status!r}")
    if record.name in _REGISTER:
        raise ValueError(f"family {record.name!r} is already registered")
    _REGISTER[record.name] = record
    return record


def get(name: str) -> Optional[FamilyRecord]:
    return _REGISTER.get(name)


def adapter(name: str, *, for_execution: bool = False) -> Any:
    """Instantiate a family's adapter.

    Constructible for any family that has one, so a CORE-PENDING recipe can be
    inspected. ``for_execution=True`` additionally requires the family to be
    routable, which is what the CLI's executing subcommands pass.
    """
    record = _REGISTER.get(name)
    if record is None:
        raise KeyError(f"{name!r} is not a registered family")
    if record.factory is None:
        raise KeyError(f"{name!r} has no adapter (status {record.status})")
    if for_execution and not record.routable:
        raise PermissionError(
            f"{name!r} is status {record.status} and is not executable; "
            + (
                "its scientific recipe is not registered, so no result could be "
                "accepted"
                if record.status == CORE_PENDING
                else f"it is retained as {record.retained_as or 'evidence'}"
            )
        )
    return record.factory()


def all_families() -> List[FamilyRecord]:
    return [_REGISTER[k] for k in sorted(_REGISTER)]


def routable_families() -> List[FamilyRecord]:
    return [r for r in all_families() if r.routable]


def routable_names() -> List[str]:
    return [r.name for r in routable_families()]


def pending_families() -> List[FamilyRecord]:
    """Registered but not yet executable. Visible, never routed to."""
    return [r for r in all_families() if r.status == CORE_PENDING]


def reset_for_tests() -> None:
    _REGISTER.clear()


# ----------------------------------------------------------------------
# Standing register. Lazy factories keep import cost and optional deps out of
# the common path: importing the registry must never import an LLM client.
# ----------------------------------------------------------------------
def _forward_step_adapter():
    from src.families.forward_step_2d_adapter import ForwardStep2DAdapter

    return ForwardStep2DAdapter()


def _nozzle_adapter():
    from src.families.nozzle_adapter import NozzleAdapter

    return NozzleAdapter()


def _airfoil_adapter():
    from src.families.airfoil.adapter import AirfoilAdapter

    return AirfoilAdapter()


def _backward_step_adapter():
    from src.families.backward_step.adapter import BackwardStepAdapter

    return BackwardStepAdapter()


def install_standing_register() -> None:
    """Populate the register. Idempotent."""
    if _REGISTER:
        return

    register(
        FamilyRecord(
            name="nozzle",
            status=CORE,
            physics="compressible_euler",
            description=(
                "3D compressible inviscid converging-diverging nozzle, validated "
                "against quasi-1D isentropic compressible-flow theory."
            ),
            keywords=(
                "nozzle", "converging-diverging", "convergent-divergent",
                "throat", "de laval", "expansion ratio", "area ratio",
            ),
            factory=_nozzle_adapter,
            notes="Frozen recipe. Scientific definition unchanged by this refactor.",
        )
    )
    register(
        FamilyRecord(
            name="forward_step_2d",
            status=CORE,
            physics="inviscid_euler",
            description=(
                "2D compressible forward-facing step with supersonic inflow; "
                "shock/compression structure benchmark."
            ),
            keywords=(
                "forward step", "forward-facing step", "forward facing step",
                "step", "shock", "supersonic channel", "compression",
            ),
            factory=_forward_step_adapter,
            notes="Frozen recipe. Scientific definition unchanged by this refactor.",
        )
    )
    register(
        FamilyRecord(
            name="airfoil",
            status=CORE_PENDING,
            physics="incompressible_or_low_mach_rans",
            description=(
                "2D turbulent NACA0012 airfoil, steady RANS with SST; validated "
                "against an authoritative TMR-type reference."
            ),
            keywords=("airfoil", "aerofoil", "naca", "naca0012", "lift", "drag",
                      "angle of attack", "aoa", "wing section"),
            factory=_airfoil_adapter,
            notes="Scientific recipe TODO. Cannot ACCEPT until constants registered.",
        )
    )
    register(
        FamilyRecord(
            name="backward_step",
            status=CORE_PENDING,
            physics="incompressible_rans",
            description=(
                "2D turbulent backward-facing step, steady RANS with SST; "
                "separation and reattachment benchmark."
            ),
            keywords=("backward step", "backward-facing step", "backward facing step",
                      "back step", "sudden expansion", "reattachment", "separation bubble"),
            factory=_backward_step_adapter,
            notes="Scientific recipe TODO. Cannot ACCEPT until constants registered.",
        )
    )
    register(
        FamilyRecord(
            name="square_duct",
            status=SUPPORTING,
            physics="incompressible_rans",
            description=(
                "3D turbulent square duct. NOT ACCEPTED as a core family: the "
                "reference case is OpenCFD v2006 and its omegaWallFunction / "
                "near-wall production treatment is not equivalent to Foundation "
                "v14, so a dictionary conversion is not the same numerical "
                "experiment."
            ),
            factory=None,
            retained_as=(
                "cross-version incompatibility evidence: matching turbulence-model "
                "names across CFD versions does not imply equivalent numerical physics"
            ),
            #: Repository-relative, or None when the evidence is not in the tree.
            #: The square-duct audit was produced outside this repository and was
            #: never imported, so there is no path to point at and none is
            #: invented. Its conclusion is recorded in `retained_as` above.
            evidence_root=None,
            notes=(
                "Validation protocol was not the problem: the original McConkey run "
                "passes our residual and forcing-stationarity gates. Preserved, not deleted."
            ),
        )
    )
    register(
        FamilyRecord(
            name="cube",
            status=NONACCEPTED,
            physics="incompressible_rans",
            description=(
                "Surface-mounted cube. NOT ACCEPTED: solver was numerically "
                "healthy while a lateral mode kept growing, and the deterministic "
                "stationarity gate rejected the run."
            ),
            factory=None,
            retained_as="stationarity stress test / safe-rejection evidence",
            evidence_root="cases/cube/drifting_wake",
            notes=(
                "Tracked and replayable: the registered case is "
                "cases/cube/drifting_wake (force history, statistics and "
                "lateral-mode characterisation), with the generated artifact "
                "directory at evidence/cube/drifting_wake. Replay with "
                "`python scripts/run_demo.py --family cube --case drifting_wake "
                "--mode replay`."
            ),
        )
    )
