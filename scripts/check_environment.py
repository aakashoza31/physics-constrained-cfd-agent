from __future__ import annotations

import importlib
import os
import shutil
import subprocess
import sys


def status(name: str, ok: bool, details: str = "") -> None:
    label = "PASS" if ok else "FAIL"
    suffix = f" - {details}" if details else ""
    print(f"{label:4}  {name}{suffix}")


print()
print("=" * 70)
print("PHYSICS-CONSTRAINED CFD AGENT - ENVIRONMENT CHECK")
print("=" * 70)
print()

status(
    "Python",
    sys.version_info >= (3, 11),
    sys.version.split()[0],
)

modules = {
    "NumPy": "numpy",
    "Pydantic": "pydantic",
    "PyYAML": "yaml",
    "Gmsh": "gmsh",
    "Pillow": "PIL",
    "PyVista": "pyvista",
    "Google GenAI": "google.genai",
}

for label, module in modules.items():
    try:
        importlib.import_module(module)
        status(label, True)
    except Exception as exc:
        status(label, False, str(exc))

wsl = shutil.which("wsl")

status(
    "WSL executable",
    wsl is not None,
    wsl or "not found",
)

distro = os.getenv("OPENFOAM_WSL_DISTRO", "Ubuntu-24.04")
bashrc = os.getenv(
    "OPENFOAM_BASHRC",
    "/opt/openfoam14/etc/bashrc",
)

if wsl:

    command = (
        f'source "{bashrc}" >/dev/null 2>&1 '
        '&& command -v foamRun '
        '&& foamVersion'
    )

    result = subprocess.run(
        [
            "wsl",
            "-d",
            distro,
            "--",
            "bash",
            "-lc",
            command,
        ],
        capture_output=True,
        text=True,
    )

    status(
        "OpenFOAM in WSL",
        result.returncode == 0,
        result.stdout.strip() or result.stderr.strip(),
    )

api_key = bool(os.getenv("GEMINI_API_KEY"))

status(
    "GEMINI_API_KEY",
    api_key,
    "configured" if api_key else "not configured",
)

print()
print(
    "The API key check does not print the key."
)
