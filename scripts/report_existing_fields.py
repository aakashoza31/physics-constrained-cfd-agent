#!/usr/bin/env python3
"""Rebuild the normal engineering report from registered evidence and archived raw fields.

Does not execute OpenFOAM and cannot alter the registered scientific decision.
Run from the repository root using Python (Windows/WSL supported).
"""
import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.agent.pipeline import REPLAY, run_pipeline
from src.reporting.report_builder import build


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--family', required=True)
    parser.add_argument('--case', required=True, help='Registered case ID')
    parser.add_argument('--raw-case', help='Existing OpenFOAM case; never modified')
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    run = run_pipeline('Report the registered archived CFD evidence', mode=REPLAY,
                       family=args.family, case=args.case)
    if args.raw_case:
        run.artifacts['raw_case'] = args.raw_case
    paths = build(run, args.out)
    print(paths.report_md)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
