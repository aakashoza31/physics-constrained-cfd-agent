from __future__ import annotations

from pathlib import Path
import sys

# Allow this script to be executed directly from the repository
# without requiring the user to configure PYTHONPATH.
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


from src.openfoam.regime_aware_builder import (
    build_regime_aware_euler_case,
)

from src.openfoam.stability_supervisor import (
    run_supervised_openfoam_case,
)

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import gmsh


ROOT = (
    Path(
        __file__
    )
    .resolve()
    .parents[1]
)

if str(
    ROOT
) not in sys.path:

    sys.path.insert(
        0,
        str(
            ROOT
        ),
    )


from src.agents.cfd_request_agent import (
    parse_cfd_request,
)

from src.agents.cfd_visual_observer import (
    observe_cfd_images,
)

from src.agents.mesh_adaptation_agent import (
    propose_mesh_adaptation,
)

from src.agents.mesh_planner_agent import (
    plan_initial_mesh,
)

from src.agents.nozzle_design_agent import (
    plan_nozzle_case,
    plan_to_nozzle_spec,
)

from src.agents.openfoam_setup_agent import (
    plan_openfoam_setup,
)

from src.agents.theory_blind_cfd_agent import (
    diagnose_theory_blind,
)

from src.cad.nozzle_generator import (
    generate_nozzle,
)

from src.cfd.diagnostics import (
    collect_cfd_diagnostics,
)

from src.contracts.problem_spec import (
    CFDProblemSpec,
    NozzleFamily,
    NozzleGeometry,
    OperatingConditions,
)

from src.geometry.nozzle_analyzer import (
    analyze_nozzle_geometry,
)

from src.meshing.nozzle_mesher import (
    generate_initial_mesh,
)

from src.openfoam.executor import (
    check_openfoam_environment,
    run_openfoam_case,
    windows_path_to_wsl,
)

from src.openfoam.production_euler_builder import (
    build_production_euler_case,
)

from src.openfoam.visualization import (
    prepare_openfoam_visualization,
)

from src.reasoning.diagnostics_adapter import (
    adapt_raw_diagnostics,
)

from src.reasoning.initialization_policy_adapter import (
    select_initialization_mode,
)

from src.reporting.cfd_results_package import (
    create_final_results_package,
    create_standardized_cfd_images,
)


# =====================================================================
# PRODUCTION LIMITS
# =====================================================================

MAX_CFD_ITERATIONS = int(os.getenv("CFD_MAX_ITERATIONS", "2"))

MAX_PRE_CFD_MESH_TRIALS = 3

CFD_INCREMENT_S = float(os.getenv("CFD_DEMO_END_TIME_S", "1.0e-4"))

DEMO_RESOURCE_MAX_ELEMENTS = (
    150000
)


# Demo/runtime execution policy.  These are deliberately environment-
# configurable so the public repository works on different machines
# without changing the physics/agent code.
DEFAULT_MPI_RANKS = int(os.getenv("CFD_MPI_RANKS", "1"))
DEFAULT_SOLVER_TIMEOUT_S = int(os.getenv("CFD_SOLVER_TIMEOUT_S", "1200"))


# =====================================================================
# HELPERS
# =====================================================================

def save_json(
    path: Path,
    value: Any,
) -> None:

    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    if hasattr(
        value,
        "model_dump",
    ):

        value = (
            value.model_dump()
        )

    elif hasattr(
        value,
        "to_dict",
    ):

        value = (
            value.to_dict()
        )


    path.write_text(
        json.dumps(
            value,
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )


def enum_value(
    value: Any,
) -> str:

    return str(
        getattr(
            value,
            "value",
            value,
        )
    )


def slug(
    text: str,
) -> str:

    clean = re.sub(
        r"[^a-zA-Z0-9]+",
        "_",
        text,
    )

    return (
        clean.strip(
            "_"
        ).lower()
        or "case"
    )


def stage(
    number: str,
    title: str,
) -> None:

    print()
    print(
        "=" * 76
    )

    print(
        f"{number}. {title}"
    )

    print(
        "=" * 76
    )


def detect_family(
    prompt: str,
) -> str | None:

    text = prompt.lower()

    if (
        "smooth_cosine"
        in text
        or "smooth cosine"
        in text
        or "cosine nozzle"
        in text
    ):

        return "smooth_cosine"

    if "bell" in text:

        return "bell"

    if (
        "conical" in text
        or "cone nozzle"
        in text
    ):

        return "conical"

    return None


def normalize_cfd_request(
    request: dict[
        str,
        Any,
    ],
) -> tuple[
    dict[
        str,
        Any,
    ],
    list[
        str
    ],
]:

    data = json.loads(
        json.dumps(
            request
        )
    )

    changes: list[
        str
    ] = []


    physics = data.setdefault(
        "physics",
        {},
    )


    # ------------------------------------------------------------
    # Execution backend selection
    #
    # The engineering user requests a CFD simulation.
    # This application uses OpenFOAM as its validated execution
    # backend, so the user does not need to explicitly name
    # OpenFOAM in the natural-language request.
    # ------------------------------------------------------------

    if not bool(
        physics.get(
            "openfoam_requested",
            False,
        )
    ):

        physics[
            "openfoam_requested"
        ] = True

        changes.append(
            "OpenFOAM selected as the validated CFD execution backend"
        )


    # Validated production backend.
    if (
        physics.get(
            "solver_requested"
        )
        is None
    ):

        physics[
            "solver_requested"
        ] = "fluid"

        changes.append(
            "solver_requested=fluid "
            "(validated pressure-based transonic backend)"
        )


    turbulence = physics.get(
        "turbulence_model"
    )

    if (
        turbulence is not None
        and str(
            turbulence
        ).strip().lower()
        in {
            "",
            "none",
            "null",
            "laminar",
        }
    ):

        physics[
            "turbulence_model"
        ] = None


    mesh = data.setdefault(
        "mesh",
        {},
    )


    # These are runtime/numerical safety boundaries, not a
    # professor-selected mesh design. Gemini still chooses all
    # actual cell sizes and local refinement strategy.

    if mesh.get(
        "max_elements"
    ) is None:

        mesh[
            "max_elements"
        ] = (
            DEMO_RESOURCE_MAX_ELEMENTS
        )

        changes.append(
            "max_elements=150000 "
            "(demo resource guardrail)"
        )


    if mesh.get(
        "min_quality"
    ) is None:

        mesh[
            "min_quality"
        ] = 0.10

        changes.append(
            "min_quality=0.10 "
            "(numerical mesh-safety guardrail)"
        )


    if mesh.get(
        "boundary_layer_requested"
    ) is None:

        mesh[
            "boundary_layer_requested"
        ] = False


    # Euler flow does not need a viscous boundary layer mesh.
    if bool(
        mesh.get(
            "boundary_layer_requested",
            False,
        )
    ):

        raise ValueError(
            "Boundary-layer meshing is outside the validated "
            "Euler/slip-wall domain."
        )


    return (
        data,
        changes,
    )


def validate_supported_domain(
    cfd_request: dict[
        str,
        Any,
    ],
) -> None:

    physics = (
        cfd_request[
            "physics"
        ]
    )

    bc = physics.get(
        "boundary_conditions",
        {},
    )


    fluid = str(
        physics.get(
            "fluid",
            "",
        )
    ).strip().lower()

    if fluid not in {
        "air",
        "dry air",
    }:

        raise ValueError(
            "Validated demo currently supports air only."
        )


    if (
        str(
            physics.get(
                "flow_regime",
                "",
            )
        ).strip().lower()
        != "compressible"
    ):

        raise ValueError(
            "Validated demo requires compressible flow."
        )


    required = {
        "inlet_pressure_type": (
            "total_pressure"
        ),
        "inlet_temperature_type": (
            "total_temperature"
        ),
        "outlet_pressure_type": (
            "static_pressure"
        ),
        "wall_velocity_condition": (
            "slip"
        ),
        "wall_thermal_condition": (
            "adiabatic"
        ),
    }


    for key, expected in (
        required.items()
    ):

        actual = str(
            bc.get(
                key,
                "",
            )
        ).strip().lower()

        if actual != expected:

            raise ValueError(
                f"Unsupported {key}={actual!r}. "
                f"Validated value is {expected!r}."
            )


    turbulence = physics.get(
        "turbulence_model"
    )

    if turbulence is not None:

        raise ValueError(
            "Validated production experiment uses no turbulence model."
        )


    p0 = float(
        bc[
            "inlet_pressure_pa"
        ]
    )

    T0 = float(
        bc[
            "inlet_temperature_k"
        ]
    )

    pout = float(
        bc[
            "outlet_pressure_pa"
        ]
    )


    if (
        p0 <= 0
        or T0 <= 0
        or pout <= 0
        or pout >= p0
    ):

        raise ValueError(
            "Invalid operating pressures/temperature."
        )


def build_problem(
    *,
    family: str,
    spec: Any,
    cfd_request: dict[
        str,
        Any,
    ],
) -> CFDProblemSpec:

    bc = (
        cfd_request[
            "physics"
        ][
            "boundary_conditions"
        ]
    )


    problem = CFDProblemSpec(
        nozzle_family=(
            NozzleFamily(
                family
            )
        ),

        geometry=(
            NozzleGeometry(
                inlet_radius_m=(
                    float(
                        spec.inlet_radius
                    )
                ),
                throat_radius_m=(
                    float(
                        spec.throat_radius
                    )
                ),
                outlet_radius_m=(
                    float(
                        spec.outlet_radius
                    )
                ),
                inlet_length_m=(
                    float(
                        spec.inlet_length
                    )
                ),
                converging_length_m=(
                    float(
                        spec.converging_length
                    )
                ),
                throat_length_m=(
                    float(
                        spec.throat_length
                    )
                ),
                diverging_length_m=(
                    float(
                        spec.diverging_length
                    )
                ),
                outlet_length_m=(
                    float(
                        spec.outlet_length
                    )
                ),
            )
        ),

        operating_conditions=(
            OperatingConditions(
                inlet_total_pressure_pa=(
                    float(
                        bc[
                            "inlet_pressure_pa"
                        ]
                    )
                ),
                inlet_total_temperature_k=(
                    float(
                        bc[
                            "inlet_temperature_k"
                        ]
                    )
                ),
                outlet_static_pressure_pa=(
                    float(
                        bc[
                            "outlet_pressure_pa"
                        ]
                    )
                ),
            )
        ),

        engineering_objective=(
            "Obtain a numerically trustworthy "
            "compressible-Euler CFD solution, diagnosing "
            "and correcting numerical or mesh issues when "
            "the available evidence justifies an action."
        ),
    )

    problem.validate()

    return problem


def resolve_openfoam_runtime_case(
    execution: dict[str, Any],
) -> str:
    """
    Resolve the Linux-staged OpenFOAM runtime directory.

    OpenFOAM v14 may reject case paths containing spaces on /mnt/c.
    Solver execution therefore occurs in the Linux filesystem, and
    all OpenFOAM post-processing must use that same staged case.
    """

    raw = (
        execution.get(
            "openfoam",
            {},
        ).get(
            "runtime_case"
        )
    )

    if not raw:

        raise RuntimeError(
            "OpenFOAM execution summary does not contain runtime_case."
        )

    raw = str(raw)

    if raw.startswith("$HOME/"):

        suffix = raw[len("$HOME/"):]

        if not re.fullmatch(
            r"[A-Za-z0-9._/-]+",
            suffix,
        ):

            raise RuntimeError(
                "Unsafe OpenFOAM runtime path returned by executor."
            )

        distro = os.getenv(
            "OPENFOAM_WSL_DISTRO",
            "Ubuntu-24.04",
        )

        proc = subprocess.run(
            [
                "wsl.exe",
                "-d",
                distro,
                "--",
                "bash",
                "-lc",
                (
                    'printf "%s" '
                    f'"$HOME/{suffix}"'
                ),
            ],
            text=True,
            capture_output=True,
            timeout=30,
            check=False,
        )

        if proc.returncode != 0:

            raise RuntimeError(
                "Could not resolve Linux OpenFOAM runtime path.\n"
                + (
                    proc.stderr
                    or ""
                )
            )

        resolved = (
            proc.stdout.strip()
        )

    else:

        resolved = raw


    if not resolved.startswith("/"):

        raise RuntimeError(
            "Resolved OpenFOAM runtime is not an absolute Linux path: "
            f"{resolved}"
        )


    return resolved


def latest_positive_time(
    case_dir: Path,
) -> float | None:

    values = []

    for path in (
        case_dir.iterdir()
        if case_dir.exists()
        else []
    ):

        if not path.is_dir():
            continue

        try:

            value = float(
                path.name
            )

        except ValueError:

            continue

        if value > 0:
            values.append(
                value
            )


    return (
        max(
            values
        )
        if values
        else None
    )


def configure_continuation(
    *,
    case_dir: Path,
    current_time: float,
    duration_s: float,
) -> None:

    # Never reapply the clean initialization during continuation.
    set_fields = (
        case_dir
        / "system"
        / "setFieldsDict"
    )

    if set_fields.exists():

        set_fields.unlink()


    path = (
        case_dir
        / "system"
        / "controlDict"
    )

    text = path.read_text(
        encoding="utf-8"
    )


    def replace_entry(
        body: str,
        name: str,
        value: str,
    ) -> str:

        pattern = re.compile(
            rf"(?m)^[ \t]*"
            rf"{re.escape(name)}"
            rf"[ \t]+[^;]+;"
        )

        replacement = (
            f"{name:<16}"
            f"{value};"
        )

        if not pattern.search(
            body
        ):

            raise RuntimeError(
                f"controlDict entry missing: "
                f"{name}"
            )

        return pattern.sub(
            replacement,
            body,
            count=1,
        )


    text = replace_entry(
        text,
        "startFrom",
        "latestTime",
    )

    # startTime is optional for a latestTime continuation.
    # Historical or externally generated valid OpenFOAM cases may omit it.
    # If present, keep it synchronized for provenance/readability.
    # If absent, do not reject an otherwise valid continuation case.
    if re.search(
        r"(?m)^\s*startTime\s+[^;]+;",
        text,
    ):
        text = replace_entry(
            text,
            "startTime",
            f"{current_time:.12g}",
        )

    text = replace_entry(
        text,
        "endTime",
        f"{current_time + duration_s:.12g}",
    )


    path.write_text(
        text,
        encoding="utf-8",
    )


def produce_images(
    *,
    visualization: dict[
        str,
        Any,
    ],
    output_dir: Path,
) -> dict[
    str,
    str,
]:

    raw = visualization.get(
        "primary_vtk"
    )

    if not raw:
        return {}


    vtk_path = Path(
        str(
            raw
        )
    )


    if not vtk_path.exists():
        return {}


    try:

        return (
            create_standardized_cfd_images(
                primary_vtk=vtk_path,
                output_dir=(
                    output_dir
                ),
            )
        )

    except Exception as exc:

        print(
            "Visual-image generation warning:",
            f"{type(exc).__name__}: {exc}",
        )

        return {}


def save_iteration(
    *,
    output_dir: Path,
    iteration: int,
    record: dict[
        str,
        Any,
    ],
) -> None:

    save_json(
        output_dir
        / (
            f"iteration_{iteration:02d}.json"
        ),
        record,
    )


def print_decision(
    *,
    decision: Any,
    validation: Any,
) -> None:

    print()
    print(
        "=" * 76
    )

    print(
        "AGENT REASONING"
    )

    print(
        "=" * 76
    )

    print(
        "Diagnosis :",
        enum_value(
            decision.diagnosis
        ),
    )

    print(
        "Action    :",
        enum_value(
            decision.action
        ),
    )

    print(
        "Region    :",
        decision.target_region,
    )

    print(
        "Confidence:",
        decision.confidence,
    )

    print()

    print(
        "Reasoning:"
    )

    print(
        decision.reasoning_summary
    )


    if (
        decision.competing_hypotheses
    ):

        print()
        print(
            "Competing hypotheses:"
        )

        for hypothesis in (
            decision.competing_hypotheses
        ):

            print(
                "  *",
                hypothesis.hypothesis,
            )


    print()
    print(
        "Deterministic guardrail:",
        (
            "APPROVED"
            if validation.approved
            else "BLOCKED"
        ),
    )

    for reason in (
        validation.reasons
    ):

        print(
            "  -",
            reason,
        )


# =====================================================================
# PREFLIGHT
# =====================================================================

def preflight() -> int:

    print()
    print(
        "=" * 76
    )

    print(
        "AUTONOMOUS CFD PRODUCTION PREFLIGHT"
    )

    print(
        "=" * 76
    )


    if not os.getenv(
        "GEMINI_API_KEY"
    ):

        print(
            "[FAILED] GEMINI_API_KEY is not active."
        )

        return 2


    print(
        "[READY] Gemini API key"
    )


    foam = (
        check_openfoam_environment(mpi_ranks=DEFAULT_MPI_RANKS)
    )

    if not foam.get(
        "ok",
        False,
    ):

        print(
            "[FAILED] OpenFOAM v14 / WSL preflight"
        )

        print(
            foam.get(
                "stderr",
                "",
            )
        )

        return 3


    print(
        "[READY] OpenFOAM v14 / WSL"
    )

    print(
        "[READY] geometry design agent"
    )

    print(
        "[READY] CAD generator"
    )

    print(
        "[READY] geometry analyzer"
    )

    print(
        "[READY] CFD request interpreter"
    )

    print(
        "[READY] mesh planner + Gmsh"
    )

    print(
        "[READY] fluid / transonic PIMPLE Euler backend"
    )

    print(
        "[READY] numerical diagnostics"
    )

    print(
        "[READY] multimodal visual observer"
    )

    print(
        "[READY] theory-blind CFD reasoning agent"
    )

    print(
        "[READY] final CFD report package"
    )

    print()
    print(
        "PRODUCTION PREFLIGHT: PASS"
    )

    return 0


# =====================================================================
# MAIN AUTONOMOUS WORKFLOW
# =====================================================================

def run_autonomous(
    engineering_prompt: str,
) -> int:

    family = detect_family(
        engineering_prompt
    )


    if family is None:

        print()
        print(
            "The engineering request did not specify "
            "a supported nozzle family."
        )

        print(
            "Supported: conical, smooth_cosine, bell"
        )

        family = input(
            "Choose nozzle family: "
        ).strip().lower()


    if family not in {
        "conical",
        "smooth_cosine",
        "bell",
    }:

        raise ValueError(
            "Unsupported nozzle family."
        )


    timestamp = (
        datetime.now()
        .strftime(
            "%Y%m%d_%H%M%S"
        )
    )

    run_name = (
        f"{timestamp}_"
        f"{slug(family)}_nozzle"
    )

    run_root = (
        ROOT
        / "runs"
        / run_name
    )

    agent_dir = (
        run_root
        / "agent"
    )

    geometry_dir = (
        run_root
        / "geometry"
    )

    mesh_dir = (
        run_root
        / "mesh"
    )

    openfoam_dir = (
        run_root
        / "openfoam"
    )

    iterations_dir = (
        run_root
        / "iterations"
    )

    final_dir = (
        run_root
        / "final"
    )


    for directory in (
        agent_dir,
        geometry_dir,
        mesh_dir,
        iterations_dir,
    ):

        directory.mkdir(
            parents=True,
            exist_ok=True,
        )


    (
        run_root
        / "engineering_prompt.txt"
    ).write_text(
        engineering_prompt
        + "\n",
        encoding="utf-8",
    )


    trace: dict[
        str,
        Any,
    ] = {
        "run_name": run_name,
        "prompt": engineering_prompt,
        "family": family,
        "iterations": [],
    }


    # =================================================================
    # 1. GEOMETRY DESIGN
    # =================================================================

    stage(
        "1",
        "ENGINEERING REQUEST -> GEOMETRY",
    )


    plan, design_source = (
        plan_nozzle_case(
            user_prompt=(
                engineering_prompt
            ),
            requested_family=(
                family
            ),
            case_name=(
                run_name
            ),
            allow_fallback=True,
        )
    )


    spec = (
        plan_to_nozzle_spec(
            plan
        )
    )


    save_json(
        agent_dir
        / "design_plan.json",
        {
            "source": (
                design_source
            ),
            "plan": (
                plan.model_dump()
            ),
        },
    )


    print(
        "Geometry planner source:",
        design_source,
    )

    print(
        "Family:",
        spec.family,
    )


    # =================================================================
    # 2. CAD
    # =================================================================

    stage(
        "2",
        "GENERATE CFD FLUID GEOMETRY",
    )


    gmsh.initialize()

    try:

        manifest = (
            generate_nozzle(
                spec=spec,
                output_dir=(
                    geometry_dir
                ),
            )
        )

    finally:

        gmsh.finalize()


    cad_path = (
        geometry_dir
        / "fluid_domain.step"
    )

    manifest_path = (
        geometry_dir
        / "geometry_manifest.json"
    )


    if not cad_path.exists():

        raise RuntimeError(
            "Nozzle CAD was not generated."
        )


    print(
        "CAD:",
        cad_path,
    )


    # =================================================================
    # 3. DETERMINISTIC GEOMETRY ANALYSIS
    # =================================================================

    stage(
        "3",
        "DETERMINISTIC GEOMETRY VERIFICATION",
    )


    geometry_analysis = (
        analyze_nozzle_geometry(
            cad_path=(
                cad_path
            ),
            manifest_path=(
                manifest_path
            ),
            output_path=(
                geometry_dir
                / "geometry_analysis.json"
            ),
        )
    )


    print(
        "Geometry verification: PASS"
    )


    # =================================================================
    # 4. CFD REQUEST INTERPRETATION
    # =================================================================

    stage(
        "4",
        "ENGINEERING PROMPT -> CFD PROBLEM",
    )


    request_model, request_source = (
        parse_cfd_request(
            user_prompt=(
                engineering_prompt
            ),
            allow_fallback=True,
        )
    )


    cfd_request, normalizations = (
        normalize_cfd_request(
            request_model.model_dump()
        )
    )


    validate_supported_domain(
        cfd_request
    )


    save_json(
        agent_dir
        / "cfd_request.json",
        {
            "source": (
                request_source
            ),
            "request": (
                cfd_request
            ),
            "deterministic_backend_normalizations": (
                normalizations
            ),
        },
    )


    problem = (
        build_problem(
            family=family,
            spec=spec,
            cfd_request=(
                cfd_request
            ),
        )
    )


    save_json(
        agent_dir
        / "problem_spec.json",
        problem,
    )


    print(
        "CFD interpreter source:",
        request_source,
    )

    print(
        "Validated physics: "
        "compressible Euler / air / slip walls"
    )


    # =================================================================
    # 5. INITIALIZATION POLICY
    # =================================================================

    stage(
        "5",
        "INITIALIZATION POLICY",
    )


    init_decision = (
        select_initialization_mode(
            first_run=True,
            geometry_changed=False,
            mesh_changed=False,
            source_trusted=None,
            allow_mapping=False,
        )
    )


    print(
        "Initialization:",
        init_decision.mode.value,
    )

    print(
        "Reason:",
        init_decision.reason,
    )


    # =================================================================
    # 6. GEMINI INITIAL MESH
    # =================================================================

    stage(
        "6",
        "LLM MESH STRATEGY",
    )


    (
        current_strategy,
        mesh_source,
    ) = (
        plan_initial_mesh(
            geometry_analysis=(
                geometry_analysis
            ),
            cfd_request=(
                cfd_request
            ),
            allow_fallback=True,
        )
    )


    save_json(
        agent_dir
        / "initial_mesh_strategy.json",
        {
            "source": mesh_source,
            "strategy": (
                current_strategy
                .model_dump()
            ),
        },
    )


    print(
        "Mesh planner source:",
        mesh_source,
    )

    print(
        json.dumps(
            current_strategy.model_dump(),
            indent=2,
        )
    )


    # =================================================================
    # 7. PRE-CFD MESH EXECUTION / ADAPTATION
    # =================================================================

    stage(
        "7",
        "GMSH + PRE-CFD MESH GUARDRAILS",
    )


    mesh_history: list[
        dict[
            str,
            Any,
        ]
    ] = []

    current_result = None


    for trial in range(
        1,
        MAX_PRE_CFD_MESH_TRIALS
        + 1,
    ):

        trial_dir = (
            mesh_dir
            / (
                f"trial_{trial:02d}"
            )
        )


        current_result = (
            generate_initial_mesh(
                cad_path=(
                    cad_path
                ),
                geometry_analysis=(
                    geometry_analysis
                ),
                strategy=(
                    current_strategy
                ),
                constraints=(
                    cfd_request[
                        "mesh"
                    ]
                ),
                output_dir=(
                    trial_dir
                ),
            )
        )


        print()
        print(
            f"Mesh trial {trial}:"
        )

        print(
            "  elements :",
            current_result.get(
                "elements_3d"
            ),
        )

        print(
            "  min SICN :",
            current_result.get(
                "minimum_quality_minSICN"
            ),
        )

        print(
            "  throat nodes:",
            current_result.get(
                "throat_nodes"
            ),
        )

        print(
            "  deterministic feasible:",
            current_result.get(
                "feasible_initial_mesh"
            ),
        )


        record = {
            "trial": trial,
            "strategy": (
                current_strategy
                .model_dump()
            ),
            "mesh_result": (
                current_result
            ),
        }

        mesh_history.append(
            record
        )


        proposal, proposal_source = (
            propose_mesh_adaptation(
                geometry_analysis=(
                    geometry_analysis
                ),
                cfd_request=(
                    cfd_request
                ),
                current_strategy=(
                    current_strategy
                ),
                mesh_result=(
                    current_result
                ),
                history=(
                    mesh_history[:-1]
                ),
                allow_fallback=True,
            )
        )


        save_json(
            agent_dir
            / (
                f"mesh_decision_"
                f"{trial:02d}.json"
            ),
            {
                "source": (
                    proposal_source
                ),
                "proposal": (
                    proposal.model_dump()
                ),
            },
        )


        if (
            proposal.accept_mesh
            and bool(
                current_result.get(
                    "feasible_initial_mesh",
                    False,
                )
            )
        ):

            print(
                "LLM mesh decision: ACCEPT"
            )

            break


        if (
            trial
            >= MAX_PRE_CFD_MESH_TRIALS
        ):

            raise RuntimeError(
                "No acceptable pre-CFD mesh was found "
                "within the bounded mesh loop."
            )


        print(
            "LLM mesh action:",
            proposal.action,
        )

        print(
            "Reason:",
            proposal.rationale,
        )


        current_strategy = (
            proposal.next_strategy
        )


    if current_result is None:

        raise RuntimeError(
            "Mesh loop produced no result."
        )


    source_mesh = Path(
        str(
            current_result[
                "mesh_file"
            ]
        )
    )

    best_mesh = (
        mesh_dir
        / "best_mesh.msh"
    )

    shutil.copy2(
        source_mesh,
        best_mesh,
    )


    save_json(
        mesh_dir
        / "best_mesh_metrics.json",
        current_result,
    )


    # =================================================================
    # 8. OPENFOAM SETUP REASONING
    # =================================================================

    stage(
        "8",
        "LLM OPENFOAM SETUP",
    )


    (
        setup_plan,
        setup_source,
    ) = (
        plan_openfoam_setup(
            geometry_analysis=(
                geometry_analysis
            ),
            cfd_request=(
                cfd_request
            ),
            best_mesh_metrics=(
                current_result
            ),
            allow_fallback=True,
        )
    )


    save_json(
        agent_dir
        / "openfoam_setup.json",
        {
            "source": (
                setup_source
            ),
            "plan": (
                setup_plan
                .model_dump()
            ),
        },
    )


    print(
        "Setup planner source:",
        setup_source,
    )

    print(
        "Solver:",
        setup_plan.solver,
    )

    print(
        "Turbulence treatment:",
        setup_plan.turbulence_treatment,
    )


    # The physical request is explicit Euler.
    if (
        setup_plan.solver
        != "fluid"
        or setup_plan.simulation_mode
        != "transient"
        or str(
            setup_plan
            .turbulence_treatment
        ).lower()
        not in {
            "laminar",
            "none",
        }
    ):

        raise RuntimeError(
            "OpenFOAM setup proposal is outside the "
            "validated fluid/transonic Euler backend."
        )


    # =================================================================
    # 9. BUILD CLEAN OPENFOAM CASE
    # =================================================================

    stage(
        "9",
        "BUILD PRODUCTION OPENFOAM CASE",
    )


    build_regime_aware_euler_case(
        case_dir=(
            openfoam_dir
        ),
        best_mesh_path=(
            best_mesh
        ),
        geometry_manifest=(
            manifest
        ),
        cfd_request=(
            cfd_request
        ),
        setup_plan=(
            setup_plan
        ),
        end_time_s=(
            CFD_INCREMENT_S
        ),
    )


    print(
        "OpenFOAM case:",
        openfoam_dir,
    )

    print(
        "Clean initialization: "
        "quasi-1D startup field"
    )

    print(
        "Analytical targets exposed to agent: NO"
    )


    # =================================================================
    # 10. AUTONOMOUS CFD LOOP
    # =================================================================

    reasoning_history: list[
        dict[
            str,
            Any,
        ]
    ] = []

    final_diagnostics = None
    final_decision = None
    final_visualization = None
    final_images = {}
    terminal_reason = None

    diagnostic_followup_used = False


    for iteration in range(
        1,
        MAX_CFD_ITERATIONS
        + 1,
    ):

        stage(
            f"10.{iteration}",
            (
                f"AUTONOMOUS CFD ITERATION "
                f"{iteration}"
            ),
        )


        execution = (
            run_supervised_openfoam_case(
                openfoam_dir,
                run_solver=True,
                solver_timeout_s=(
                    DEFAULT_SOLVER_TIMEOUT_S
                ),
                mpi_ranks=(
                    DEFAULT_MPI_RANKS
                ),
            )
        )


        print(
            "OpenFOAM status:",
            execution.get(
                "status"
            ),
        )


        latest = (
            execution.get(
                "solver",
                {},
            ).get(
                "last_time"
            )
        )


        if latest is None:

            latest = (
                latest_positive_time(
                    openfoam_dir
                )
            )


        if latest is None:

            raise RuntimeError(
                "OpenFOAM produced no usable positive-time CFD state."
            )


        latest = float(
            latest
        )


        start_time = max(
            0.0,
            0.80 * latest,
        )


        case_wsl = (
            resolve_openfoam_runtime_case(
                execution
            )
        )

        solver_log_wsl = (
            windows_path_to_wsl(
                openfoam_dir
                / "log.foamRun"
            )
        )


        # --------------------------------------------------------------
        # Deterministic numerical evidence
        # --------------------------------------------------------------

        print()
        print(
            "Collecting deterministic CFD evidence..."
        )


        diagnostics = (
            collect_cfd_diagnostics(
                case_wsl=(
                    case_wsl
                ),
                start_time=(
                    start_time
                ),
                end_time=(
                    latest
                ),
                solver_log=(
                    solver_log_wsl
                ),
                geometry_manifest=(
                    manifest
                ),
            )
        )


        final_diagnostics = (
            diagnostics
        )


        # --------------------------------------------------------------
        # VTK + standardized images
        # --------------------------------------------------------------

        visualization = (
            prepare_openfoam_visualization(
                case_dir=(
                    openfoam_dir
                ),
                timeout_s=600,
                open_in_gmsh=False,
                create_demo_assets=True,
            )
        )


        final_visualization = (
            visualization
        )


        iteration_dir = (
            iterations_dir
            / (
                f"iteration_{iteration:02d}"
            )
        )

        iteration_dir.mkdir(
            parents=True,
            exist_ok=True,
        )


        images = (
            produce_images(
                visualization=(
                    visualization
                ),
                output_dir=(
                    iteration_dir
                    / "images"
                ),
            )
        )


        final_images = images


        # --------------------------------------------------------------
        # Actual multimodal Gemini observation
        # --------------------------------------------------------------

        visual_observation = (
            observe_cfd_images(
                image_paths=(
                    images
                ),
                numerical_context={
                    "status": (
                        diagnostics.get(
                            "status"
                        )
                    ),
                    "mass_imbalance_pct": (
                        diagnostics.get(
                            "flow",
                            {},
                        ).get(
                            "mass_imbalance_pct"
                        )
                    ),
                    "stationarity": (
                        diagnostics.get(
                            "stationarity",
                            {}
                        )
                    ),
                },
            )
        )


        save_json(
            iteration_dir
            / "visual_observation.json",
            visual_observation,
        )


        # --------------------------------------------------------------
        # Structured theory-blind evidence
        # --------------------------------------------------------------

        evidence = (
            adapt_raw_diagnostics(
                diagnostics,
                problem,
                mesh_context=(
                    current_result
                ),
                visual_paths=(
                    images
                ),
                iteration=(
                    iteration
                ),
                case_id=(
                    run_name
                ),
            )
        )


        history_for_call = (
            reasoning_history
            + [
                {
                    "iteration": (
                        iteration
                    ),
                    "visual_observation": (
                        visual_observation
                    ),
                    "theory_used_by_agent": (
                        False
                    ),
                }
            ]
        )


        # --------------------------------------------------------------
        # LLM diagnosis + deterministic action validation
        # --------------------------------------------------------------

        (
            decision,
            validation,
        ) = (
            diagnose_theory_blind(
                problem,
                evidence,
                history=(
                    history_for_call
                ),
            )
        )


        # --------------------------------------------------------------
        # REQUEST_DIAGNOSTIC:
        # automatically widen the temporal evidence window once.
        # --------------------------------------------------------------

        action = enum_value(
            decision.action
        )


        diagnostic_followup = None


        if (
            action
            == "REQUEST_DIAGNOSTIC"
            and not diagnostic_followup_used
        ):

            diagnostic_followup_used = (
                True
            )

            print()
            print(
                "Agent requested additional evidence."
            )

            print(
                "Collecting full available CFD history automatically..."
            )


            extended = (
                collect_cfd_diagnostics(
                    case_wsl=(
                        case_wsl
                    ),
                    solver_log=(
                        "log.foamRun"
                    ),
                    geometry_manifest=(
                        manifest
                    ),
                )
            )


            extended_evidence = (
                adapt_raw_diagnostics(
                    extended,
                    problem,
                    mesh_context=(
                        current_result
                    ),
                    visual_paths=(
                        images
                    ),
                    iteration=(
                        iteration
                    ),
                    case_id=(
                        run_name
                    ),
                )
            )


            diagnostic_followup = {
                "requested_diagnostic": (
                    decision
                    .requested_diagnostic
                ),
                "response": (
                    "Full available temporal, boundary, "
                    "global-extrema, throat, mesh, and "
                    "visual evidence recollected."
                ),
            }


            (
                decision,
                validation,
            ) = (
                diagnose_theory_blind(
                    problem,
                    extended_evidence,
                    history=(
                        history_for_call
                        + [
                            diagnostic_followup
                        ]
                    ),
                )
            )


            diagnostics = (
                extended
            )

            final_diagnostics = (
                extended
            )

            action = enum_value(
                decision.action
            )


        final_decision = decision


        print_decision(
            decision=(
                decision
            ),
            validation=(
                validation
            ),
        )


        decision_record = {
            "iteration": (
                iteration
            ),
            "physical_time_s": (
                latest
            ),
            "execution": (
                execution
            ),
            "diagnostics": (
                diagnostics
            ),
            "visualization": (
                visualization
            ),
            "standardized_images": (
                images
            ),
            "visual_observation": (
                visual_observation
            ),
            "decision": (
                decision.to_dict()
            ),
            "deterministic_validation": {
                "approved": (
                    validation.approved
                ),
                "reasons": (
                    validation.reasons
                ),
            },
            "diagnostic_followup": (
                diagnostic_followup
            ),
            "theory_used_by_agent": (
                False
            ),
        }


        save_iteration(
            output_dir=(
                iterations_dir
            ),
            iteration=(
                iteration
            ),
            record=(
                decision_record
            ),
        )


        trace[
            "iterations"
        ].append(
            {
                "iteration": (
                    iteration
                ),
                "diagnosis": (
                    enum_value(
                        decision.diagnosis
                    )
                ),
                "action": (
                    action
                ),
                "guardrail_approved": (
                    validation.approved
                ),
                "physical_time_s": (
                    latest
                ),
            }
        )


        reasoning_history.append(
            {
                "iteration": (
                    iteration
                ),
                "decision": (
                    decision.to_dict()
                ),
                "visual_observation": (
                    visual_observation
                ),
                "deterministic_validation": {
                    "approved": (
                        validation.approved
                    ),
                    "reasons": (
                        validation.reasons
                    ),
                },
            }
        )


        # --------------------------------------------------------------
        # Guardrail block
        # --------------------------------------------------------------

        if not validation.approved:

            terminal_reason = (
                "Deterministic guardrail blocked "
                f"the proposed action {action}."
            )

            break


        # --------------------------------------------------------------
        # ACCEPT
        # --------------------------------------------------------------

        if action == "ACCEPT":

            terminal_reason = (
                "Agent accepted the CFD result after "
                "deterministic validation."
            )

            break


        # --------------------------------------------------------------
        # CONTINUE_RUN
        # --------------------------------------------------------------

        if action == "CONTINUE_RUN":

            init = (
                select_initialization_mode(
                    first_run=False,
                    geometry_changed=False,
                    mesh_changed=False,
                    source_trusted=None,
                    allow_mapping=False,
                )
            )


            print()
            print(
                "Executing action:",
                action,
            )

            print(
                "Initialization policy:",
                init.mode.value,
            )


            configure_continuation(
                case_dir=(
                    openfoam_dir
                ),
                current_time=(
                    latest
                ),
                duration_s=(
                    CFD_INCREMENT_S
                ),
            )

            continue


        # --------------------------------------------------------------
        # RESTART_CLEAN
        # --------------------------------------------------------------

        if action == "RESTART_CLEAN":

            print()
            print(
                "Executing action:",
                action,
            )

            build_regime_aware_euler_case(
                case_dir=(
                    openfoam_dir
                ),
                best_mesh_path=(
                    best_mesh
                ),
                geometry_manifest=(
                    manifest
                ),
                cfd_request=(
                    cfd_request
                ),
                setup_plan=(
                    setup_plan
                ),
                end_time_s=(
                    CFD_INCREMENT_S
                ),
            )

            continue


        # --------------------------------------------------------------
        # CFD-DRIVEN REMESH
        # --------------------------------------------------------------

        if action in {
            "REFINE_THROAT",
            "REFINE_GRADIENT_REGION",
            "REPAIR_MESH",
        }:

            print()
            print(
                "Executing CFD-driven mesh adaptation..."
            )


            mesh_feedback_history = (
                mesh_history
                + [
                    {
                        "strategy": (
                            current_strategy
                            .model_dump()
                        ),
                        "cfd_feedback": (
                            decision.to_dict()
                        ),
                    }
                ]
            )


            (
                proposal,
                proposal_source,
            ) = (
                propose_mesh_adaptation(
                    geometry_analysis=(
                        geometry_analysis
                    ),
                    cfd_request=(
                        cfd_request
                    ),
                    current_strategy=(
                        current_strategy
                    ),
                    mesh_result=(
                        current_result
                    ),
                    history=(
                        mesh_feedback_history
                    ),
                    allow_fallback=True,
                )
            )


            current_strategy = (
                proposal.next_strategy
            )


            adaptation_dir = (
                mesh_dir
                / (
                    f"cfd_adapt_"
                    f"{iteration:02d}"
                )
            )


            new_result = (
                generate_initial_mesh(
                    cad_path=(
                        cad_path
                    ),
                    geometry_analysis=(
                        geometry_analysis
                    ),
                    strategy=(
                        current_strategy
                    ),
                    constraints=(
                        cfd_request[
                            "mesh"
                        ]
                    ),
                    output_dir=(
                        adaptation_dir
                    ),
                )
            )


            if not bool(
                new_result.get(
                    "feasible_initial_mesh",
                    False,
                )
            ):

                terminal_reason = (
                    "CFD-driven remesh did not satisfy "
                    "deterministic mesh constraints."
                )

                break


            current_result = (
                new_result
            )


            shutil.copy2(
                Path(
                    str(
                        current_result[
                            "mesh_file"
                        ]
                    )
                ),
                best_mesh,
            )


            init = (
                select_initialization_mode(
                    first_run=False,
                    geometry_changed=False,
                    mesh_changed=True,
                    source_trusted=None,
                    allow_mapping=False,
                )
            )


            print(
                "Remesh initialization:",
                init.mode.value,
            )

            print(
                "Field mapping used: NO"
            )


            build_regime_aware_euler_case(
                case_dir=(
                    openfoam_dir
                ),
                best_mesh_path=(
                    best_mesh
                ),
                geometry_manifest=(
                    manifest
                ),
                cfd_request=(
                    cfd_request
                ),
                setup_plan=(
                    setup_plan
                ),
                end_time_s=(
                    CFD_INCREMENT_S
                ),
            )

            continue


        # --------------------------------------------------------------
        # REQUEST_DIAGNOSTIC repeated
        # --------------------------------------------------------------

        if action == "REQUEST_DIAGNOSTIC":

            terminal_reason = (
                "Agent still requires additional diagnostic "
                "evidence after the automatic extended evidence pass."
            )

            break


        # --------------------------------------------------------------
        # OUTSIDE DOMAIN
        # --------------------------------------------------------------

        if action == "REJECT_OUTSIDE_DOMAIN":

            terminal_reason = (
                "Agent determined that the request/result "
                "is outside the validated domain."
            )

            break


        terminal_reason = (
            "Production runner reached an unsupported "
            f"terminal action: {action}"
        )

        break


    # =================================================================
    # 11. FINAL REPORT / ARTIFACTS
    # =================================================================

    stage(
        "11",
        "FINAL CFD RESULT PACKAGE",
    )


    if final_diagnostics is None:

        raise RuntimeError(
            "Pipeline ended without a usable CFD diagnostic record."
        )


    final_primary_vtk = None

    if final_visualization:

        raw_vtk = (
            final_visualization.get(
                "primary_vtk"
            )
        )

        if raw_vtk:

            candidate = Path(
                str(
                    raw_vtk
                )
            )

            if candidate.exists():

                final_primary_vtk = (
                    candidate
                )


    package = (
        create_final_results_package(
            run_name=(
                run_name
            ),
            output_dir=(
                final_dir
            ),
            problem_spec=(
                problem
            ),
            diagnostics=(
                final_diagnostics
            ),
            decision=(
                final_decision
            ),
            primary_vtk=(
                final_primary_vtk
            ),
            final_mesh=(
                best_mesh
            ),
            gamma=1.4,
            gas_constant=287.0,
            open_folder=True,
        )
    )


    trace[
        "terminal_reason"
    ] = terminal_reason

    trace[
        "final_package"
    ] = package

    trace[
        "theory_used_by_agent"
    ] = False

    trace[
        "initialization_theory_assisted"
    ] = True


    save_json(
        run_root
        / "RUN_TRACE.json",
        trace,
    )


    print()
    print(
        "=" * 76
    )

    print(
        "AUTONOMOUS CFD RUN COMPLETE"
    )

    print(
        "=" * 76
    )

    print(
        "Terminal reason:",
        terminal_reason,
    )

    print(
        "Results folder:",
        final_dir,
    )

    print(
        "Report:",
        final_dir
        / "CFD_REPORT.html",
    )

    print(
        "Full trace:",
        run_root
        / "RUN_TRACE.json",
    )

    print()
    print(
        "The final results folder has been opened."
    )


    return 0


# =====================================================================
# CLI
# =====================================================================

def main() -> int:

    parser = argparse.ArgumentParser(
        description=(
            "Professor-facing autonomous CFD agent."
        )
    )

    parser.add_argument(
        "--prompt",
        default=None,
        help=(
            "Complete engineering request. If omitted, "
            "the program asks interactively."
        ),
    )

    parser.add_argument(
        "--preflight",
        action="store_true",
        help=(
            "Verify production dependencies without "
            "running geometry, meshing, or CFD."
        ),
    )


    args = parser.parse_args()


    if args.preflight:

        return preflight()


    print()
    print(
        "=" * 76
    )

    print(
        "AUTONOMOUS CFD AGENT"
    )

    print(
        "Physics-constrained LLM + Gmsh + OpenFOAM"
    )

    print(
        "=" * 76
    )

    print(
        f"Demo CFD horizon: {CFD_INCREMENT_S:.6g} s | "
        f"MPI ranks: {DEFAULT_MPI_RANKS} | "
        f"solver timeout: {DEFAULT_SOLVER_TIMEOUT_S} s"
    )


    prompt = (
        args.prompt
    )


    if not prompt:

        print()
        print(
            "Enter the complete engineering request."
        )

        print(
            "Supported domain: compressible-air, "
            "axisymmetric C-D nozzles, Euler/slip walls."
        )

        print(
            "Supported families: conical, smooth_cosine, bell."
        )

        print()

        prompt = input(
            "> "
        ).strip()


    if not prompt:

        raise ValueError(
            "Engineering request cannot be empty."
        )


    return run_autonomous(
        prompt
    )


if __name__ == "__main__":

    raise SystemExit(
        main()
    )
