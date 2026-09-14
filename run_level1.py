from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
CORE_RUNNER = ROOT / "scripts" / "run_autonomous_cfd.py"


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower()).strip()


def validate_level1_prompt(prompt: str) -> None:
    text = normalize(prompt)

    required = [
        "axisymmetric conical converging-diverging nozzle",
        "inlet radius = 50 mm",
        "throat radius = 32.6 mm",
        "outlet radius = 35.4 mm",
        "inlet straight length = 50 mm",
        "converging length = 100 mm",
        "throat length = 10 mm",
        "diverging length = 120 mm",
        "outlet straight length = 50 mm",
        "inlet stagnation pressure = 200 kpa",
        "inlet stagnation temperature = 300 k",
        "downstream back pressure = 30 kpa",
        "gamma = 1.4",
        "r = 287",
        "inviscid euler",
        "adiabatic slip walls",
        "do not expose analytical solution target values",
    ]

    missing = [item for item in required if item not in text]

    if missing:
        print()
        print("UNSUPPORTED INPUT")
        print()
        print("This repository currently supports only the supplied Level-1 nozzle prompt.")
        print()
        print("Missing or changed requirements:")
        for item in missing:
            print(" -", item)
        raise SystemExit(2)


def read_prompt() -> str:
    print()
    print("=" * 70)
    print("PHYSICS-CONSTRAINED CFD AGENT")
    print("LEVEL-1 CANONICAL NOZZLE VALIDATION")
    print("=" * 70)
    print()
    print("Paste the supplied Level-1 prompt.")
    print("When finished, type END on a new line.")
    print()

    lines = []

    while True:
        line = input()

        if line.strip() == "END":
            break

        lines.append(line)

    prompt = "\n".join(lines).strip()

    if not prompt:
        raise SystemExit("No prompt was provided.")

    return prompt


def main() -> int:
    if not CORE_RUNNER.exists():
        raise SystemExit(f"Core CFD runner not found: {CORE_RUNNER}")

    prompt = read_prompt()
    validate_level1_prompt(prompt)

    print()
    print("PASS: Level-1 prompt recognized.")
    print("Starting autonomous CFD workflow...")
    print()

    result = subprocess.run(
        [
            sys.executable,
            str(CORE_RUNNER),
            "--prompt",
            prompt,
        ],
        cwd=ROOT,
        check=False,
    )

    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
