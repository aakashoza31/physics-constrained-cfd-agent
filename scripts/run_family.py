#!/usr/bin/env python3
"""Orchestrator entry point: the parallel opt-in path. Family-generic.

The existing runners -- scripts/run_forward_step_2d.py and
scripts/run_nozzle_feedback.py -- are NOT modified by this refactor. They remain
the default execution path for Families 1 and 2, byte-for-byte. This script is
the separate, opt-in route through the shared architecture.

This CLI contains NO family-specific code. Spec loading and evidence loading go
through adapter.load_spec() / adapter.load_evidence(), so a family is reachable
here the moment its adapter implements them, with no edit to this file.

Subcommands
-----------
  route     Route a natural-language request. No CFD.
  register  Print the family register (all families, including non-executable).
  recipe    Print one family's recipe, including unresolved constants.
  decide    One decision cycle on evidence that already exists. No CFD.
  faults    Fault-injection + gates-off comparison on existing evidence. No CFD.
  run       Full loop INCLUDING CFD. Refuses without --i-want-to-run-cfd.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from src.families import registry  # noqa: E402
from src.orchestrator import modes as modes_mod  # noqa: E402
from src.orchestrator.ledger import Ledger  # noqa: E402
from src.orchestrator.loop import decide_once, run_loop  # noqa: E402
from src.router.route import route  # noqa: E402


def _emit(obj) -> None:
    print(json.dumps(obj, indent=2, default=str))


def _adapter(name: str, *, for_execution: bool):
    """Resolve an adapter, turning a refusal into a clean CLI error."""
    try:
        return registry.adapter(name, for_execution=for_execution)
    except (KeyError, PermissionError) as exc:
        print(f"refusing: {exc}", file=sys.stderr)
        raise SystemExit(3) from exc


def _spec_and_evidence(adapter, evidence_dir: str, spec_arg: str | None):
    """Load both through the family's own hooks. No family names appear here."""
    evidence_path = Path(evidence_dir)
    spec_path = Path(spec_arg) if spec_arg else evidence_path
    spec = adapter.load_spec(spec_path)
    evidence = adapter.load_evidence(evidence_path)
    return spec, evidence


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("route"); p.add_argument("request")
    sub.add_parser("register")
    p = sub.add_parser("recipe"); p.add_argument("family")

    p = sub.add_parser("decide")
    p.add_argument("family")
    p.add_argument("evidence_dir")
    p.add_argument("--spec", help="spec file or directory; defaults to evidence_dir")
    p.add_argument("--mode", default=modes_mod.FULL, choices=list(modes_mod.MODES))
    p.add_argument("--ledger")

    p = sub.add_parser("faults")
    p.add_argument("family")
    p.add_argument("evidence_dir")
    p.add_argument("--spec")

    p = sub.add_parser("run")
    p.add_argument("family")
    p.add_argument("workdir")
    p.add_argument("--spec", required=True)
    p.add_argument("--mode", default=modes_mod.FULL, choices=list(modes_mod.MODES))
    p.add_argument("--i-want-to-run-cfd", action="store_true",
                   help="required: this subcommand launches OpenFOAM")

    args = ap.parse_args()
    registry.install_standing_register()

    if args.cmd == "register":
        _emit([r.to_dict() for r in registry.all_families()])
        return 0

    if args.cmd == "route":
        _emit(route(args.request).to_dict())
        return 0

    if args.cmd == "recipe":
        # Inspection only: a CORE-PENDING recipe is meant to be readable.
        _emit(_adapter(args.family, for_execution=False).recipe.to_dict())
        return 0

    if args.cmd == "decide":
        adapter = _adapter(args.family, for_execution=True)
        spec, evidence = _spec_and_evidence(adapter, args.evidence_dir, args.spec)
        ledger = Ledger(path=Path(args.ledger) if args.ledger else None,
                        mode=args.mode)
        step = decide_once(adapter, spec, evidence, mode=args.mode, ledger=ledger)
        _emit({
            "family": adapter.name,
            "mode": args.mode,
            "decision": step.decision,
            "reasons": step.reasons,
            "proposed_action": step.proposal.to_dict(),
            "ruling": step.ruling.to_dict(),
            "validation_status": step.validation.get("status"),
            "failed_checks": step.validation.get("failed_checks"),
            "unresolved_criteria": step.unresolved_criteria,
            "blocked_capabilities": adapter.recipe.unresolved_capabilities(),
        })
        return 0

    if args.cmd == "faults":
        from src.eval.faults import faults_for
        from src.eval.harness import fault_injection, gates_off_comparison

        adapter = _adapter(args.family, for_execution=True)
        spec, evidence = _spec_and_evidence(adapter, args.evidence_dir, args.spec)
        suite = faults_for(adapter.name)
        if not suite:
            print(f"refusing: no fault suite registered for {adapter.name!r}",
                  file=sys.stderr)
            return 3
        _emit({
            "fault_injection": fault_injection(
                adapter, spec, evidence, suite).to_dict(),
            "gates_off": gates_off_comparison(
                adapter, spec, evidence, suite).to_dict(),
        })
        return 0

    # args.cmd == "run"
    if not args.i_want_to_run_cfd:
        print("refusing: 'run' launches OpenFOAM. Pass --i-want-to-run-cfd.",
              file=sys.stderr)
        return 2
    adapter = _adapter(args.family, for_execution=True)
    spec = adapter.load_spec(Path(args.spec))
    workdir = Path(args.workdir)
    outcome = run_loop(
        adapter, spec, workdir, mode=args.mode,
        ledger=Ledger(path=workdir / "ledger.jsonl", mode=args.mode),
    )
    _emit(outcome.to_dict())
    return 0 if outcome.decision == "ACCEPT" else 1


if __name__ == "__main__":
    raise SystemExit(main())
