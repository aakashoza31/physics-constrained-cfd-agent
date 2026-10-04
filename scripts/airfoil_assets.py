#!/usr/bin/env python3
"""Register and verify the airfoil (NACA0012) family's external assets.

Not part of the CFD Forge paper; development tooling for the airfoil mesh
qualification. Never downloads anything.

    report    print exactly which files are required, and where to put them
    register  compute SHA256 of the present files and write the lockfile
    verify    re-check every registered digest

Registration is a deliberate, one-time human act: the digest of a NASA download
cannot be known in advance, so it is recorded once from the file you installed
and then committed. After that a mismatch fails closed.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.pipeline.airfoil import assets as A  # noqa: E402
from src.pipeline.airfoil.p3d import CONVERSION_TOOLCHAIN  # noqa: E402


def cmd_report() -> int:
    root = A.asset_root()
    print(f"The airfoil family requires {len(A.REGISTER)} registered external assets.")
    print(f"Install them into: {root}\n")
    for n, asset in enumerate(A.REGISTER.values(), start=1):
        flag = "REQUIRED" if asset.required else "optional"
        print(f"{n}. {asset.filename}   [{flag}]")
        print(f"     role   : {asset.role}")
        print(f"     source : {asset.source}")
        if asset.expected:
            print(f"     expect : {json.dumps(asset.expected)}")
        print()
    print("Nothing is downloaded automatically and nothing is ever substituted.")
    print(f"After installing, run:  python scripts/airfoil_assets.py register")
    return 0


def cmd_register(force: bool) -> int:
    lock = A.lockfile_path()
    if lock.exists() and not force:
        print(f"refusing: {lock} already exists. Pass --force to re-register, "
              "which changes the authoritative digests.", file=sys.stderr)
        return 3
    entries = {}
    missing = []
    for key, asset in A.REGISTER.items():
        path = A.asset_path(key)
        if not path.exists():
            if asset.required:
                missing.append(asset.filename)
            continue
        digest = A.sha256_of(path)
        entries[key] = {
            "filename": asset.filename,
            "sha256": digest,
            "bytes": path.stat().st_size,
            "source": asset.source,
            "role": asset.role,
            "expected": asset.expected,
        }
        print(f"{asset.filename}\n  sha256 {digest}\n  bytes  {path.stat().st_size}")
    if missing:
        print(f"\nrefusing: required assets absent: {missing}", file=sys.stderr)
        print("Run 'report' for what to install. Nothing is substituted.",
              file=sys.stderr)
        return 3
    written = A.write_lock(entries, toolchain=CONVERSION_TOOLCHAIN)
    print(f"\nwrote {written}  -- commit this file.")
    return 0


def cmd_verify() -> int:
    audit = A.audit_assets()
    print(json.dumps(audit, indent=2))
    return 0 if audit["all_required_ok"] else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("report")
    p = sub.add_parser("register")
    p.add_argument("--force", action="store_true")
    sub.add_parser("verify")
    args = ap.parse_args()
    if args.cmd == "report":
        return cmd_report()
    if args.cmd == "register":
        return cmd_register(args.force)
    return cmd_verify()


if __name__ == "__main__":
    raise SystemExit(main())
