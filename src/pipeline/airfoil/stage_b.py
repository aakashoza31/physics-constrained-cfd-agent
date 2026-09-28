#!/usr/bin/env python3
"""Stage B of the mesh audit: OpenFOAM mesh utilities only. NEVER the solver.

Runs, in order, on the repository's existing FoamRuntime bridge:

  1. gmshToFoam on the Stage-A converted mesh
  2. a deterministic boundary rewrite: the two spanwise patches are merged into
     one `frontAndBack` patch of type `empty`, airfoil -> wall, farfield -> patch
  3. checkMesh -allTopology -allGeometry
  4. PARSING of the checkMesh report -- not the return code alone

THIS IS NOT CFD. The command allow-list below is enforced before every call, so
`foamRun`, `simpleFoam`, `incompressibleFluid` and friends cannot be invoked from
this module even by mistake. There is no second subprocess system: everything
goes through FoamRuntime.bash.
"""
from __future__ import annotations

import re
import shlex
import time
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any, Dict, List, Optional, Tuple

from src.pipeline.airfoil import p3d

#: The ONLY OpenFOAM executables Stage B may run. A mesh utility list.
ALLOWED_TOOLS = ("gmshToFoam", "checkMesh", "foamDictionary")

#: Anything matching these may never appear in a Stage-B command.
FORBIDDEN_TOOLS = (
    "foamRun", "simpleFoam", "pimpleFoam", "potentialFoam", "rhoCentralFoam",
    "shockFluid", "incompressibleFluid", "compressibleFluid", "solidDisplacement",
    "interFoam", "mpirun",
)

#: Final OpenFOAM patch inventory the converted mesh must have.
EXPECTED_PATCHES: Dict[str, str] = {
    p3d.PATCH_AIRFOIL: "wall",
    p3d.PATCH_FARFIELD: "patch",
    "frontAndBack": "empty",
}

STAGE_B_VERSION = "airfoil-stage-b/1.0.0"


class StageBRefused(RuntimeError):
    """A Stage-B command was refused before it ran."""


def assert_mesh_only(script: str) -> None:
    """Refuse any script naming a flow solver. Called before every command."""
    lowered = script.lower()
    for tool in FORBIDDEN_TOOLS:
        if re.search(rf"\b{re.escape(tool.lower())}\b", lowered):
            raise StageBRefused(
                f"Stage B refused a command naming {tool!r}. Stage B runs mesh "
                f"utilities only ({', '.join(ALLOWED_TOOLS)}); it never invokes a "
                "flow solver."
            )


# ----------------------------------------------------------------------
_CONTROL_DICT = """FoamFile
{
    format      ascii;
    class       dictionary;
    location    "system";
    object      controlDict;
}

// Minimal controlDict so the MESH UTILITIES can construct a Time object.
// No solver is named here and none is run in Stage B.
startFrom       startTime;
startTime       0;
stopAt          endTime;
endTime         0;
deltaT          1;
writeControl    timeStep;
writeInterval   1;
"""


def _boundary_rewrite_script(case: str) -> str:
    """Deterministic patch typing, via foamDictionary. No hand-edited text."""
    q = shlex.quote
    lines = [
        f'cd {q(case)} || exit 91',
        'b=constant/polyMesh/boundary',
        '[ -f "$b" ] || b=0/polyMesh/boundary',
        '[ -f "$b" ] || { echo "AIRFOIL_STAGEB_ERROR=no boundary file"; exit 92; }',
        # Merge the two spanwise patches into one empty patch. gmshToFoam names
        # them from the Gmsh physical surfaces, so the names are known exactly.
        'python3 - "$b" <<\'__PYEOF__\'',
        "import re, sys",
        "path = sys.argv[1]",
        "text = open(path).read()",
        "blocks = re.findall(r'\\n    (\\w+)\\n    \\{(.*?)\\n    \\}', text, re.S)",
        "names = [b[0] for b in blocks]",
        # Two mesh provenances reach this rewrite. The Plot3D branch produces
        # two spanwise physical surfaces (front, back) that must be MERGED; the
        # Gmsh branch already writes one `frontAndBack` surface, which must only
        # be retyped. Anything else is refused rather than guessed at.
        "span = [n for n in ('front', 'back') if n in names]",
        "merged = 'frontAndBack' in names",
        "if merged and span:",
        "    print('AIRFOIL_STAGEB_ERROR=both merged and split spanwise patches:"
        " %s' % names)",
        "    raise SystemExit(93)",
        "if not merged and len(span) != 2:",
        "    print('AIRFOIL_STAGEB_ERROR=spanwise patches absent: %s' % names)",
        "    raise SystemExit(93)",
        "def body(name):",
        "    return dict(blocks)[name]",
        "def faces(name):",
        "    m = re.search(r'nFaces\\s+(\\d+)', body(name));  return int(m.group(1))",
        "def start(name):",
        "    m = re.search(r'startFace\\s+(\\d+)', body(name)); return int(m.group(1))",
        "if merged:",
        "    fb_faces, fb_start = faces('frontAndBack'), start('frontAndBack')",
        "    spanwise = ['frontAndBack']",
        "else:",
        "    fb_faces = faces('front') + faces('back')",
        "    fb_start = min(start('front'), start('back'))",
        "    spanwise = ['front', 'back']",
        "keep = [n for n in names if n not in spanwise]",
        "out = []",
        "for name in keep:",
        "    kind = 'wall' if name == 'airfoil' else 'patch'",
        "    out.append('    %s\\n    {\\n        type            %s;\\n"
        "        nFaces          %d;\\n        startFace       %d;\\n    }'"
        " % (name, kind, faces(name), start(name)))",
        "out.append('    frontAndBack\\n    {\\n        type            empty;\\n"
        "        nFaces          %d;\\n        startFace       %d;\\n    }'"
        " % (fb_faces, fb_start))",
        "header = text[:text.index('(')]",
        "open(path, 'w').write(header + '(\\n' + '\\n'.join(out) + '\\n)\\n\\n"
        "// ************************************************************************* //\\n')",
        "print('AIRFOIL_STAGEB_BOUNDARY_REWRITTEN=%d' % (len(out),))",
        "__PYEOF__",
    ]
    return "; ".join(lines[:4]) + "\n" + "\n".join(lines[4:])


# ----------------------------------------------------------------------
_CHECKMESH_PATCH = re.compile(
    r"^\s*(\w+)\s+(\d+)\s+(\d+)\s*$", re.M
)


def parse_check_mesh(text: str) -> Dict[str, Any]:
    """Parse the checkMesh report. The return code alone is not evidence."""
    mesh_ok = bool(re.search(r"^\s*Mesh OK\.\s*$", text, re.M))
    failed = re.findall(r"\*\*\*(.+)$", text, re.M)

    cells = points = faces = None
    m = re.search(r"cells:\s*(\d+)", text)
    if m:
        cells = int(m.group(1))
    m = re.search(r"points:\s*(\d+)", text)
    if m:
        points = int(m.group(1))
    m = re.search(r"faces:\s*(\d+)", text)
    if m:
        faces = int(m.group(1))

    hexes = None
    m = re.search(r"hexahedra:\s*(\d+)", text)
    if m:
        hexes = int(m.group(1))

    patches: Dict[str, Dict[str, Any]] = {}
    section = re.search(
        r"Checking patch topology.*?(?=\nChecking|\nMesh OK|\Z)", text, re.S
    )
    if section:
        for name, nfaces, npoints in _CHECKMESH_PATCH.findall(section.group(0)):
            patches[name] = {"nFaces": int(nfaces), "nPoints": int(npoints)}

    return {
        "mesh_ok": mesh_ok,
        "failed_checks": [f.strip() for f in failed],
        "cells": cells,
        "points": points,
        "faces": faces,
        "hexahedra": hexes,
        "patch_face_counts": patches,
        "parsed": bool(cells is not None or mesh_ok),
    }


def parse_boundary_types(text: str) -> Dict[str, str]:
    """Patch name -> type, read from the OpenFOAM boundary file."""
    out: Dict[str, str] = {}
    for name, body in re.findall(r"\n    (\w+)\n    \{(.*?)\n    \}", text, re.S):
        kind = re.search(r"type\s+(\w+)\s*;", body)
        if kind:
            out[name] = kind.group(1)
    return out


# ----------------------------------------------------------------------
@dataclass
class StageBResult:
    status: str
    ok: bool = False
    empty_patches_ok: bool = False
    patch_types: Dict[str, str] = field(default_factory=dict)
    summary: Dict[str, Any] = field(default_factory=dict)
    commands: List[Dict[str, Any]] = field(default_factory=list)
    note: str = ""
    provenance: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "ok": self.ok,
            "empty_patches_ok": self.empty_patches_ok,
            "patch_types": dict(self.patch_types),
            "summary": dict(self.summary),
            "commands": list(self.commands),
            "note": self.note,
            "provenance": dict(self.provenance),
            "version": STAGE_B_VERSION,
            "allowed_tools": list(ALLOWED_TOOLS),
            "solver_invoked": False,
        }


def run_stage_b(
    mesh_file: Path,
    *,
    runtime: Any,
    expected_cells: int,
    expected_patch_faces: Optional[Dict[str, int]] = None,
    timeout: float = 1800.0,
) -> Dict[str, Any]:
    """Convert, retype the boundary, and checkMesh. Mesh utilities only.

    ``runtime`` is a FoamRuntime (or anything exposing ``.bash(script, foam=...)``
    and ``.to_runtime_path``), so tests can substitute a recorder and assert that
    no solver was ever named.
    """
    mesh_file = Path(mesh_file)
    started = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    result = StageBResult(status="RUNNING")
    stamp = f"airfoil-mesh-audit-{int(time.time())}"

    def run(script: str, label: str, *, foam: bool = True) -> Any:
        assert_mesh_only(script)
        outcome = runtime.bash(script, foam=foam, timeout=timeout)
        result.commands.append(
            {
                "label": label,
                "returncode": getattr(outcome, "returncode", None),
                "stdout_tail": (getattr(outcome, "stdout", "") or "")[-2000:],
                "stderr_tail": (getattr(outcome, "stderr", "") or "")[-1000:],
            }
        )
        return outcome

    # -- 0. a case directory and the mesh, inside the runtime -----------
    host_mesh = runtime.to_runtime_path(mesh_file)
    case = f'"$HOME/.cache/cfd-agent/{stamp}"'
    setup = (
        f'set -e; mkdir -p {case}/system {case}/constant; '
        f'cp -- {shlex.quote(host_mesh)} {case}/mesh.msh; '
        f'printf "%s" {shlex.quote(_CONTROL_DICT)} > {case}/system/controlDict; '
        f'printf "AIRFOIL_STAGEB_CASE=%s\\n" {case}'
    )
    outcome = run(setup, "stage_setup", foam=False)
    if not getattr(outcome, "ok", False):
        result.status = "STAGE_B_SETUP_FAILED"
        result.note = "could not stage the converted mesh into the runtime"
        return result.to_dict()
    marked = [
        line.split("=", 1)[1].strip()
        for line in (outcome.stdout or "").splitlines()
        if line.startswith("AIRFOIL_STAGEB_CASE=")
    ]
    if not marked:
        result.status = "STAGE_B_SETUP_FAILED"
        result.note = "runtime did not report the case directory"
        return result.to_dict()
    case_path = marked[-1]

    # -- 1. gmshToFoam -------------------------------------------------
    outcome = run(
        f'cd {shlex.quote(case_path)} && gmshToFoam mesh.msh 2>&1 | tail -40',
        "gmshToFoam",
    )
    if not getattr(outcome, "ok", False):
        result.status = "GMSHTOFOAM_FAILED"
        result.note = "gmshToFoam did not complete"
        return result.to_dict()

    # -- 2. deterministic boundary rewrite -----------------------------
    outcome = run(_boundary_rewrite_script(case_path), "boundary_rewrite", foam=False)
    if not getattr(outcome, "ok", False) or "AIRFOIL_STAGEB_BOUNDARY_REWRITTEN" not in (
        outcome.stdout or ""
    ):
        result.status = "BOUNDARY_REWRITE_FAILED"
        result.note = (
            "could not merge the spanwise patches into an empty frontAndBack patch"
        )
        return result.to_dict()

    # -- 3. verify the boundary inventory ------------------------------
    outcome = run(
        f'cd {shlex.quote(case_path)} && '
        'cat constant/polyMesh/boundary 2>/dev/null || cat 0/polyMesh/boundary',
        "read_boundary", foam=False,
    )
    result.patch_types = parse_boundary_types(outcome.stdout or "")
    inventory_ok = all(
        result.patch_types.get(name) == kind
        for name, kind in EXPECTED_PATCHES.items()
    ) and set(result.patch_types) == set(EXPECTED_PATCHES)
    result.empty_patches_ok = result.patch_types.get("frontAndBack") == "empty"
    if not inventory_ok:
        result.status = "PATCH_INVENTORY_WRONG"
        result.note = (
            f"expected {EXPECTED_PATCHES}, found {result.patch_types}"
        )
        return result.to_dict()

    # -- 4. checkMesh, parsed ------------------------------------------
    outcome = run(
        f'cd {shlex.quote(case_path)} && checkMesh -allTopology -allGeometry 2>&1',
        "checkMesh",
    )
    report = parse_check_mesh(outcome.stdout or "")
    result.summary = report
    if not report["parsed"]:
        result.status = "CHECKMESH_UNPARSEABLE"
        result.note = "checkMesh output could not be parsed; refusing to trust it"
        return result.to_dict()

    checks = {
        "mesh_ok_reported": report["mesh_ok"],
        "no_failed_checks": not report["failed_checks"],
        "cell_count_matches": report["cells"] == expected_cells,
        "all_hexahedra": report["hexahedra"] in (None, expected_cells),
        "one_spanwise_cell": (
            report["patch_face_counts"].get("frontAndBack", {}).get("nFaces")
            == 2 * expected_cells
            if report["patch_face_counts"] else None
        ),
        "patch_types_correct": inventory_ok,
    }
    if expected_patch_faces:
        for name, count in expected_patch_faces.items():
            observed = report["patch_face_counts"].get(name, {}).get("nFaces")
            checks[f"patch_faces_{name}"] = (
                observed == count if observed is not None else None
            )
    result.summary["checks"] = checks
    failed = [k for k, v in checks.items() if v is False]
    unknown = [k for k, v in checks.items() if v is None]

    result.ok = not failed and not unknown
    result.status = "STAGE_B_PASSED" if result.ok else "STAGE_B_FAILED"
    result.note = (
        "gmshToFoam + boundary rewrite + checkMesh -allTopology -allGeometry; "
        "report parsed, not merely trusted"
        if result.ok
        else f"failed: {failed}; indeterminate: {unknown}"
    )
    result.provenance = {
        "stage_b_version": STAGE_B_VERSION,
        "started_utc": started,
        "finished_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "runtime_mode": getattr(runtime, "mode", "unknown"),
        "runtime_bashrc": getattr(runtime, "bashrc", None),
        "case_directory": case_path,
        "converted_mesh": str(mesh_file),
        "commands_run": [c["label"] for c in result.commands],
        "tools_allowed": list(ALLOWED_TOOLS),
        "solver_invoked": False,
        "expected_cells": expected_cells,
        "checkMesh_report": report,
        "final_patch_types": dict(result.patch_types),
    }
    return result.to_dict()
