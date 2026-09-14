from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path.cwd().resolve()

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.resume_autonomous_cfd_run import (
    process_existing_state,
    reconstruct_problem,
)
from src.openfoam.executor import (
    windows_path_to_wsl,
)


# ============================================================
# SOURCE AUTONOMOUS RUN
# ============================================================

SOURCE_RUN = (
    ROOT
    / "runs"
    / "20260913_132428_conical_nozzle"
)

WSL_TEST_A = (
    "/home/aakash/nozzle_test_A/case"
)

REPLAY_ROOT = (
    SOURCE_RUN
    / "level1_testA_autonomous_replay"
)

OPENFOAM_DIR = (
    REPLAY_ROOT
    / "openfoam"
)

AGENT_DIR = (
    REPLAY_ROOT
    / "agent"
)

GEOMETRY_DIR = (
    REPLAY_ROOT
    / "geometry"
)

MESH_DIR = (
    REPLAY_ROOT
    / "mesh"
)


# ============================================================
# VERIFY REQUIRED CURRENT PIPELINE INPUTS
# ============================================================

problem_source = (
    SOURCE_RUN
    / "agent"
    / "problem_spec.json"
)

manifest_source = (
    SOURCE_RUN
    / "geometry"
    / "geometry_manifest.json"
)

for path in [
    problem_source,
    manifest_source,
]:
    if not path.exists():
        raise RuntimeError(
            f"Missing required autonomous artifact: {path}"
        )


# ============================================================
# CREATE ISOLATED REPLAY
#
# IMPORTANT:
# This does NOT modify Test-A.
# This does NOT run OpenFOAM.
# ============================================================

if REPLAY_ROOT.exists():
    shutil.rmtree(
        REPLAY_ROOT
    )

AGENT_DIR.mkdir(
    parents=True,
    exist_ok=True,
)

GEOMETRY_DIR.mkdir(
    parents=True,
    exist_ok=True,
)

MESH_DIR.mkdir(
    parents=True,
    exist_ok=True,
)

OPENFOAM_DIR.mkdir(
    parents=True,
    exist_ok=True,
)


shutil.copy2(
    problem_source,
    AGENT_DIR
    / "problem_spec.json",
)

shutil.copy2(
    manifest_source,
    GEOMETRY_DIR
    / "geometry_manifest.json",
)


# ============================================================
# COPY SAVED TEST-A OPENFOAM CASE FROM WSL TO WINDOWS
#
# No solver invocation.
# ============================================================

dest_wsl = windows_path_to_wsl(
    OPENFOAM_DIR
)

copy_command = (
    "cd /home/aakash"
    " && "
    f"test -d {shlex.quote(WSL_TEST_A)}"
    " && "
    f"mkdir -p {shlex.quote(dest_wsl)}"
    " && "
    f"cp -a {shlex.quote(WSL_TEST_A + '/.')} "
    f"{shlex.quote(dest_wsl + '/')}"
)

proc = subprocess.run(
    [
        "wsl.exe",
        "-d",
        os.getenv(
            "OPENFOAM_WSL_DISTRO",
            "Ubuntu-24.04",
        ),
        "--",
        "bash",
        "-lc",
        copy_command,
    ],
    text=True,
    capture_output=True,
    check=False,
)

if proc.returncode != 0:
    raise RuntimeError(
        "Could not import Test-A case:\n"
        + (proc.stdout or "")
        + "\n"
        + (proc.stderr or "")
    )

print()
print(
    "PASS: Test-A copied into isolated replay."
)


# ============================================================
# VERIFY 1 ms STATE
# ============================================================

latest_dir = (
    OPENFOAM_DIR
    / "0.001"
)

for field in [
    "p",
    "U",
    "T",
]:
    path = (
        latest_dir
        / field
    )

    if not path.exists():
        raise RuntimeError(
            f"Missing Test-A field: {path}"
        )

print(
    "PASS: Test-A t=0.001 p/U/T present."
)


# ============================================================
# EXPOSE HISTORICAL SOLVER LOG TO CURRENT DIAGNOSTICS
#
# Historical Test-A used log.testA_to_1ms.
# Current diagnostics expects log.foamRun.
# This is only a filename compatibility alias.
# No solver is executed.
# ============================================================

historical_solver_log = (
    OPENFOAM_DIR
    / "log.testA_to_1ms"
)

current_solver_log = (
    OPENFOAM_DIR
    / "log.foamRun"
)

if not historical_solver_log.exists():
    raise RuntimeError(
        "Historical Test-A solver log is missing: "
        + str(historical_solver_log)
    )

shutil.copy2(
    historical_solver_log,
    current_solver_log,
)

print(
    "PASS: historical Test-A solver log exposed as log.foamRun."
)


# ============================================================
# TRUTHFUL TEST-A MESH CONTEXT
#
# This is NOT the newer ~36k-cell mesh.
# ============================================================

mesh_context = {
    "source":
        "historical_level1_testA",

    "feasible":
        True,

    "mesh_ok":
        True,

    "cell_count":
        63747,

    "node_count":
        12517,

    "minimum_gmsh_quality":
        0.349,

    "max_nonorthogonality_deg":
        57.57001781,

    "max_skewness":
        1.150350725,

    "geometry_changed":
        False,

    "mesh_changed_during_replay":
        False,

    "note":
        (
            "Saved Level-1 canonical verification mesh. "
            "No remeshing performed by this replay."
        ),
}

(
    MESH_DIR
    / "best_mesh_metrics.json"
).write_text(
    json.dumps(
        mesh_context,
        indent=2,
    ),
    encoding="utf-8",
)


# ============================================================
# LOAD CURRENT PROBLEM + GEOMETRY
# ============================================================

problem = reconstruct_problem(
    AGENT_DIR
    / "problem_spec.json"
)

manifest = json.loads(
    (
        GEOMETRY_DIR
        / "geometry_manifest.json"
    ).read_text(
        encoding="utf-8",
    )
)


# ============================================================
# EXECUTION PROVENANCE
#
# Solver already ran historically.
# We deliberately do NOT call foamRun here.
# ============================================================

execution = {
    "status":
        "imported_saved_testA_state",

    "overall_ok":
        True,

    "run_solver_requested":
        False,

    "solver": {
        "completed":
            True,

        "last_time":
            0.001,

        "historical_solver":
            "shockFluid",
    },

    "execution_mode": {
        "parallel":
            False,

        "mpi_ranks":
            1,
    },

    "openfoam": {
        "distro":
            "Ubuntu-24.04",

        "runtime_case":
            WSL_TEST_A,
    },

    "provenance": {
        "current_state_origin":
            "saved_historical_level1_testA",

        "geometry_regenerated":
            False,

        "mesh_changed":
            False,

        "solution_mapped_to_new_mesh":
            False,

        "field_mapping_performed":
            False,

        "solver_rerun_for_replay":
            False,
    },
}


# ============================================================
# THEORY-BLIND HISTORY CONTEXT
#
# DO NOT put analytical exit targets here.
# ============================================================

history = [
    {
        "iteration":
            0,

        "context":
            (
                "This is a saved canonical Level-1 CFD state "
                "being replayed through the current autonomous "
                "diagnostic/reasoning stack."
            ),

        "initialization_theory_assisted":
            True,

        "theory_used_by_agent":
            False,

        "geometry_regenerated":
            False,

        "mesh_changed":
            False,

        "solution_mapped_to_new_mesh":
            False,

        "field_mapping_performed":
            False,
    }
]


# ============================================================
# CURRENT AUTONOMOUS STACK
#
# diagnostics
# -> visualizations
# -> Gemini visual observer
# -> theory-blind evidence
# -> Gemini proposal
# -> deterministic validator
#
# NO CFD SOLVE OCCURS HERE.
# ============================================================

print()
print(
    "=" * 76
)
print(
    "LEVEL-1 SAVED CFD -> AUTONOMOUS REASONING"
)
print(
    "=" * 76
)
print(
    "Gemini model:",
    os.getenv(
        "GEMINI_MODEL"
    ),
)
print(
    "Solver rerun: NO"
)
print(
    "Analytical exit target supplied to agent: NO"
)

(
    action,
    physical_time,
    diagnostics,
    visualization,
    images,
    decision,
    validation,
    visual_observation,
) = process_existing_state(
    run_root=REPLAY_ROOT,
    iteration=1,
    execution=execution,
    problem=problem,
    manifest=manifest,
    mesh_context=mesh_context,
    history=history,
)


# ============================================================
# POST-HOC THEORY
#
# This is created ONLY AFTER the agent decision.
# Therefore the LLM does not use these values.
# ============================================================

posthoc_theory = {
    "theory_exposed_to_agent":
        False,

    "reference_exit_mach":
        1.5044036557,

    "reference_exit_pressure_pa":
        54134.0,

    "reference_exit_temperature_k":
        206.520,

    "reference_exit_velocity_m_s":
        433.361,

    "reference_mass_flow_kg_s":
        1.558238,

    "purpose":
        "researcher-only post-hoc Level-1 verification",
}


summary = {
    "case":
        "Level-1 Test-A autonomous replay",

    "physical_time_s":
        physical_time,

    "raw_agent_decision":
        decision.to_dict(),

    "effective_action":
        action,

    "deterministic_validation": {
        "approved":
            validation.approved,

        "reasons":
            validation.reasons,
    },

    "visual_observation":
        visual_observation,

    "diagnostics":
        diagnostics,

    "provenance":
        execution[
            "provenance"
        ],

    "initialization_theory_assisted":
        True,

    "theory_used_by_agent":
        False,

    "posthoc_theory":
        posthoc_theory,
}


summary_path = (
    REPLAY_ROOT
    / "LEVEL1_AUTONOMOUS_REPLAY.json"
)

summary_path.write_text(
    json.dumps(
        summary,
        indent=2,
        default=str,
    ),
    encoding="utf-8",
)


print()
print(
    "=" * 76
)
print(
    "LEVEL-1 AUTONOMOUS REPLAY COMPLETE"
)
print(
    "=" * 76
)

print(
    "Physical time      :",
    physical_time,
)

print(
    "Agent action       :",
    action,
)

print(
    "Validator approved :",
    validation.approved,
)

print(
    "Validator reasons  :",
    validation.reasons,
)

flow = diagnostics.get(
    "flow",
    {},
)

print()
print(
    "Mass imbalance %   :",
    flow.get(
        "mass_imbalance_pct"
    ),
)

print(
    "Outlet Mach        :",
    flow.get(
        "outlet_mach"
    ),
)

print(
    "Outlet pressure Pa :",
    flow.get(
        "outlet_pressure_pa"
    ),
)

print()
print(
    "Saved trace:",
    summary_path,
)

print()
print(
    "IMPORTANT:"
)
print(
    "No geometry generation."
)
print(
    "No remeshing."
)
print(
    "No OpenFOAM solver rerun."
)
print(
    "Analytical targets were introduced only AFTER the agent decision."
)

