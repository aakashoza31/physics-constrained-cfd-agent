from __future__ import annotations

import importlib
import os
import sys

from src.pipeline.foam_runtime import FoamRuntime


def status(name: str, ok: bool, details: str = "") -> bool:
    label = "PASS" if ok else "FAIL"
    suffix = f" - {details}" if details else ""
    print(f"{label:4}  {name}{suffix}")
    return ok


def main() -> int:
    print()
    print("=" * 70)
    print("PHYSICS-CONSTRAINED CFD AGENT - ENVIRONMENT CHECK")
    print("=" * 70)
    print()

    required_ok = True
    required_ok &= status(
        "Python",
        sys.version_info >= (3, 11),
        sys.version.split()[0],
    )

    modules = {
        "NumPy": "numpy",
        "Pydantic": "pydantic",
        "PyYAML": "yaml",
        "Google GenAI": "google.genai",
        "Pillow": "PIL",
        "Matplotlib": "matplotlib",
    }

    # These are retained research dependencies, but the validated blockMesh
    # nozzle path does not require them for every run.
    optional_modules = {
        "Gmsh (optional for current blockMesh path)": "gmsh",
        "PyVista (optional for current feedback path)": "pyvista",
    }

    for label, module in modules.items():
        try:
            mod = importlib.import_module(module)
            version = getattr(mod, "__version__", "available")
            required_ok &= status(label, True, str(version))
        except Exception as exc:
            required_ok &= status(label, False, str(exc))

    for label, module in optional_modules.items():
        try:
            mod = importlib.import_module(module)
            version = getattr(mod, "__version__", "available")
            status(label, True, str(version))
        except Exception as exc:
            status(label, False, str(exc))

    runtime = FoamRuntime.detect()
    try:
        preflight = runtime.preflight()
        required_ok &= status(
            "OpenFOAM Foundation v14 runtime",
            bool(preflight.get("ok")),
            (
                f"mode={preflight.get('mode')}, "
                f"version={preflight.get('openfoam_version')}, "
                f"numpy={preflight.get('numpy')}"
                if preflight.get("ok")
                else preflight.get("reason", preflight.get("raw", "unavailable"))
            ),
        )
    except Exception as exc:
        required_ok &= status("OpenFOAM Foundation v14 runtime", False, str(exc))

    api_key = bool(os.getenv("GEMINI_API_KEY"))
    required_ok &= status(
        "GEMINI_API_KEY",
        api_key,
        "configured" if api_key else "not configured",
    )

    model = os.getenv("GEMINI_MODEL", "<code default>")
    status("GEMINI_MODEL", True, model)

    print()
    print("The API key check never prints the key itself.")
    return 0 if required_ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
