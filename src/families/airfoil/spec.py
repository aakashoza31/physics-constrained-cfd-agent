#!/usr/bin/env python3
"""Airfoil spec (not part of the CFD Forge paper): 2D turbulent NACA0012, NASA TMR 2DN00 validation case.

FROZEN SCIENTIFIC SCALING (reviewed and frozen; every value below was verified
arithmetically against its definition before being written here):

    chord            c     = 1.0 m
    freestream       U_inf = 1.0 m/s
    density          rho   = 1.0 kg/m^3
    Reynolds number  Re_c  = 6e6
    kinematic visc.  nu    = U*c/Re = 1/6e6 = 1.6666666667e-7 m^2/s
    incompressible, isothermal -- Mach and temperature are NOT solved.

PROVENANCE NOTE, CARRIED INTO EVERY EVIDENCE DOCUMENT: the NASA CFD reference
for this case is run at M = 0.15. Our Foundation-v14 implementation is
INCOMPRESSIBLE. This is a validation against external evidence, NOT an exact
reproduction of the NASA code. Nothing in this family may be described as
reproducing CFL3D.

The spec carries geometry-free run control only. The airfoil geometry comes from
a registered NASA structured grid; it is never regenerated from a polynomial and
there is no C-grid generator here. Angle of attack is imposed by ROTATING THE
FREESTREAM VECTOR -- the airfoil is never rotated and never remeshed.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

from src.pipeline.airfoil import family2 as _family2
from src.pipeline.airfoil import mesh_hierarchy as _hierarchy
from src.pipeline.airfoil import mesh_levels as _levels

FAMILY = "airfoil"
PHYSICS = "incompressible_rans_kOmegaSST"

# -- frozen dimensional scaling ----------------------------------------
CHORD_M = 1.0
U_INF = 1.0
RHO = 1.0
RE_C = 6.0e6
#: nu = U*c/Re. Written as the quotient so it can never drift from Re.
NU = U_INF * CHORD_M / RE_C

# -- canonical operating condition -------------------------------------
CANONICAL_ALPHA_DEG = 0.0
#: The first planned variation, registered but NOT run as part of canonical
#: closure. Present so the envelope is declared rather than discovered later.
FIRST_VARIATION_ALPHA_DEG = 10.0

#: Attached / pre-stall family only. Fully turbulent smooth wall, no transition.
ALPHA_ENVELOPE_DEG = (0.0, 10.0)

# -- frozen freestream turbulence --------------------------------------
#: NASA benchmark freestream turbulence quantities.
TURBULENCE_INTENSITY = 0.052e-2          # 0.052 %
NUT_RATIO_INF = 0.009                    # nu_t / nu

#: Derived for OUR dimensional scaling. Both were recomputed from the benchmark
#: quantities and match the frozen reference values exactly:
#:   k     = 1.5 * (U * Ti)^2      = 1.5 * (1.0 * 5.2e-4)^2 = 4.056e-7
#:   omega = k / nu_t             = 4.056e-7 / (0.009*nu)  = 270.4
K_INF = 4.056e-7
OMEGA_INF = 270.4
NUT_INF = NUT_RATIO_INF * NU

# -- registered grids --------------------------------------------------
#: Grid level identifiers. The active mesh source for these levels is the NASA
#: TMR Family II hierarchy (src/pipeline/airfoil/family2.py); the preregistered
#: Gmsh hierarchy that first used these names is archived evidence.
COARSE_GRID, MEDIUM_GRID, FINE_GRID = "coarse", "medium", "fine"
GRID_KEYS = (COARSE_GRID, MEDIUM_GRID, FINE_GRID)

#: The canonical level for validation is the fine mesh; the sensitivity pair is
#: medium vs fine, with coarse supplying the contraction check.
CANONICAL_GRID = FINE_GRID
SENSITIVITY_GRID = MEDIUM_GRID

#: Retained for the optional NASA supporting branch only. Not active airfoil grids.
NASA_CANONICAL_GRID = "mesh_canonical"
NASA_SENSITIVITY_GRID = "mesh_sensitivity"

#: Span of the NASA Plot3D supporting grids, as NASA WRITES them: two identical
#: x-z planes separated by y = 1. This is a property of those FILES, not of the
#: active recipe, whose span is SPAN_M = 0.01 c. The two numbers are deliberately
#: different, and the supporting branch must be audited against its own.
NASA_SPAN_M = 1.0

#: Registered NASA Plot3D dimensions, as the files actually are: 3-D, single
#: block, SPANWISE FIRST. ni = 2 is the two identical x-z planes separated by
#: y = 1, which is exactly one spanwise cell.
#: NASA Plot3D dimensions, kept for the OPTIONAL supporting branch.
GRID_DIMENSIONS: Dict[str, Tuple[int, int, int]] = {
    NASA_CANONICAL_GRID: (2, 897, 257),
    NASA_SENSITIVITY_GRID: (2, 449, 129),
}

#: The flow-plane dimensions, derived from the registered triple.
def flow_plane_dimensions(grid_key: str) -> Tuple[int, int]:
    _, nj, nk = GRID_DIMENSIONS[grid_key]
    return (nj, nk)


def cells_for(grid_key: str) -> int:
    """(ni-1)*(nj-1)*(nk-1) -- the identity, not a transcribed integer."""
    ni, nj, nk = GRID_DIMENSIONS[grid_key]
    return (ni - 1) * (nj - 1) * (nk - 1)


NASA_CANONICAL_CELLS = cells_for(NASA_CANONICAL_GRID)      # 229376
NASA_SENSITIVITY_CELLS = cells_for(NASA_SENSITIVITY_GRID)  # 57344

# -- active hierarchy cell counts --------------------------------------
#: ACTIVE hierarchy: the NASA TMR Family II levels. Their cell counts are
#: NASA-DECLARED and derived as the identity (ni-1)(nj-1), so they ARE
#: requirements -- unlike the archived Gmsh hierarchy, whose counts were only
#: forecasts of whatever its recipe produced.
EXPECTED_CELLS: Dict[str, int] = dict(_family2.CELLS)
NASA_FAMILY2_DIMENSIONS: Dict[str, Tuple[int, int]] = dict(_family2.DIMENSIONS)

#: Retained so the archived Gmsh reports stay readable. Forecast, never a
#: requirement, and not part of the active path.
ARCHIVED_GMSH_FORECAST_CELLS: Dict[str, Tuple[int, int]] = {
    key: tuple(_levels.level(key).forecast_cells) for key in GRID_KEYS
}
#: Cell envelope of the active hierarchy, coarse to fine.
CELL_ENVELOPE: Tuple[int, int] = (EXPECTED_CELLS[COARSE_GRID],
                                 EXPECTED_CELLS[FINE_GRID])


def measured_cells(grid_key: str, repo_root: Optional[Any] = None) -> Optional[int]:
    """Cell count MEASURED from the generated level, or None if not generated.

    There is deliberately no fallback to the forecast: an ungenerated level has
    no cell count, and inventing one would make a forecast look like a fact.
    """
    if grid_key not in GRID_KEYS:
        return None
    return _hierarchy.hierarchy_state(repo_root)["measured_cells"].get(grid_key)


def refine_ceiling_cells(repo_root: Optional[Any] = None) -> int:
    """Largest mesh this family may hold: the finest REGISTERED level.

    Refining past the fine level leaves the frozen hierarchy, so the ceiling is
    the fine level itself -- measured when it exists, and otherwise its frozen
    forecast upper bound. No factor is invented on top of either.
    """
    measured = measured_cells(FINE_GRID, repo_root)
    return int(measured) if measured else int(EXPECTED_CELLS[FINE_GRID])

#: Span of the one-layer extrusion. It appears in the force normalisation, so it
#: is part of the frozen recipe rather than a meshing convenience.
#:
#: FROZEN AT 0.01 c. The NASA Family II grids are supplied with their own span;
#: the conversion rescales the spanwise separation to this value and changes
#: nothing else. Force normalisation uses this actual span, never a nominal 1 m.
SPAN_M = _family2.REQUIRED_SPAN


def freestream_velocity(alpha_deg: float, u_inf: float = U_INF) -> Tuple[float, float, float]:
    """Freestream vector for an incidence, in the UNROTATED mesh frame.

    Incidence is imposed here and nowhere else. The airfoil is not rotated.
    """
    a = math.radians(float(alpha_deg))
    return (u_inf * math.cos(a), u_inf * math.sin(a), 0.0)


def lift_drag_directions(alpha_deg: float) -> Dict[str, Tuple[float, float, float]]:
    """Drag along the freestream, lift normal to it, in the mesh frame."""
    a = math.radians(float(alpha_deg))
    return {
        "drag": (math.cos(a), math.sin(a), 0.0),
        "lift": (-math.sin(a), math.cos(a), 0.0),
    }


def dynamic_reference(span_m: float = SPAN_M) -> float:
    """0.5 * rho * U^2 * c * b -- the force normalisation denominator."""
    return 0.5 * RHO * U_INF * U_INF * CHORD_M * float(span_m)


@dataclass(frozen=True)
class AirfoilSpec:
    """One scope-checked NACA0012 case."""

    alpha_deg: float = CANONICAL_ALPHA_DEG
    grid: str = CANONICAL_GRID

    # Run control. end_iterations is the declared budget, not an accuracy knob.
    end_iterations: int = 5000
    #: Window over which numerical qualification is assessed.
    qualification_window: int = 500

    # Frozen scaling, carried so every artefact records what it was run with.
    chord_m: float = CHORD_M
    u_inf: float = U_INF
    rho: float = RHO
    nu: float = NU
    span_m: float = SPAN_M

    k_inf: float = K_INF
    omega_inf: float = OMEGA_INF

    family: str = FAMILY
    physics: str = PHYSICS

    def __post_init__(self) -> None:
        if self.grid not in GRID_KEYS:
            raise ValueError(
                f"grid must be one of {GRID_KEYS}; got {self.grid!r}. "
                "This family uses the registered coarse/medium/fine levels only "
                "(NASA TMR Family II; the preregistered Gmsh hierarchy is "
                "archived) and never substitutes a mesh. The NASA 2DN00 Plot3D "
                "grids are an optional supporting branch and are not run levels."
            )
        for key in ("chord_m", "u_inf", "rho", "nu", "span_m", "k_inf", "omega_inf"):
            value = getattr(self, key)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"{key} must be a number")
            if not math.isfinite(float(value)) or float(value) <= 0.0:
                raise ValueError(f"{key} must be finite and positive, got {value}")
        if isinstance(self.alpha_deg, bool) or not isinstance(self.alpha_deg, (int, float)):
            raise ValueError("alpha_deg must be a number")
        if not math.isfinite(float(self.alpha_deg)):
            raise ValueError("alpha_deg must be finite")
        for key in ("end_iterations", "qualification_window"):
            value = getattr(self, key)
            if type(value) is not int or value < 1:
                raise ValueError(f"{key} must be a positive integer, got {value!r}")
        if self.qualification_window > self.end_iterations:
            raise ValueError(
                "qualification_window cannot exceed end_iterations: the numerical "
                "qualification window must lie inside the run"
            )
        # The frozen scaling is an identity, not three independent numbers.
        implied_re = self.u_inf * self.chord_m / self.nu
        if abs(implied_re - RE_C) / RE_C > 1e-9:
            raise ValueError(
                f"chord/velocity/viscosity imply Re_c = {implied_re:.6e}, not the "
                f"registered {RE_C:.6e}. The scaling is frozen as an identity."
            )

    # ------------------------------------------------------------------
    @property
    def reynolds_number(self) -> float:
        return self.u_inf * self.chord_m / self.nu

    @property
    def cells(self) -> Optional[int]:
        """MEASURED cells of this level, or None while it is ungenerated.

        Deliberately Optional. The frozen recipe specifies the mesh; the count
        is a result of it, so there is nothing to declare and nothing to hit.
        """
        return measured_cells(self.grid)

    @property
    def expected_cells(self) -> int:
        """NASA's declared cell count for this level. A requirement, not a guess."""
        return EXPECTED_CELLS[self.grid]

    @property
    def nasa_dimensions(self) -> Tuple[int, int]:
        """The Family II structured dimensions this level corresponds to."""
        return NASA_FAMILY2_DIMENSIONS[self.grid]

    @property
    def is_canonical(self) -> bool:
        return (
            abs(self.alpha_deg - CANONICAL_ALPHA_DEG) < 1e-12
            and self.grid == CANONICAL_GRID
        )

    @property
    def freestream(self) -> Tuple[float, float, float]:
        return freestream_velocity(self.alpha_deg, self.u_inf)

    @property
    def directions(self) -> Dict[str, Tuple[float, float, float]]:
        return lift_drag_directions(self.alpha_deg)

    @property
    def force_reference(self) -> float:
        return dynamic_reference(self.span_m)

    def to_dict(self) -> Dict[str, Any]:
        return {k: getattr(self, k) for k in self.__dataclass_fields__}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AirfoilSpec":
        fields = set(cls.__dataclass_fields__)
        return cls(**{k: v for k, v in data.items() if k in fields})

    def replace(self, **changes: Any) -> "AirfoilSpec":
        return AirfoilSpec.from_dict({**self.to_dict(), **changes})


CANONICAL_SPEC = AirfoilSpec()
SENSITIVITY_SPEC = AirfoilSpec(grid=SENSITIVITY_GRID)
