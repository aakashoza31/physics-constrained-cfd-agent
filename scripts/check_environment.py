#!/usr/bin/env python3
"""Check the Python packages, OpenFOAM runtime and Gemini settings CFD Forge uses.

    python scripts/check_environment.py

Exit code 0 when every required item is present, 2 otherwise. The API key is
reported as configured or not; its value is never printed.
"""
from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.agents.llm_provenance import gemini_model_name  # noqa: E402
from src.pipeline.foam_runtime import FoamRuntime  # noqa: E402


def status(name: str, ok: bool, details: str = "") -> bool:
    label = "PASS" if ok else "FAIL"
    suffix = f" - {details}" if details else ""
    print(f"{label:4}  {name}{suffix}")
    return ok


def main() -> int:
    print()
    print("=" * 70)
    print("CFD FORGE - ENVIRONMENT CHECK")
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

    # Optional: the registered blockMesh nozzle and step paths do not need them.
    optional_modules = {
        "Gmsh (optional; not used by the blockMesh paths)": "gmsh",
        "PyVista (optional; field rendering)": "pyvista",
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

    source = "GEMINI_MODEL" if os.getenv("GEMINI_MODEL") else "code default"
    status("Gemini model", True, f"{gemini_model_name()} ({source})")

    print()
    print("The API key check never prints the key itself.")
    return 0 if required_ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
