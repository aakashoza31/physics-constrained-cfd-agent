#!/usr/bin/env python3
"""Explicit build/run/analyze commands for the 3-D forward-step prototype (Linux/WSL).

Not part of the CFD Forge paper; the paper's step family is the 2-D runner
scripts/run_forward_step_2d.py.
"""
from pathlib import Path
import argparse,json,sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from pipeline.forward_step import ForwardStep3DSpec,build,execute

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('action',choices=['build','execute','analyze','all'])
    p.add_argument('--case',required=True,type=Path)
    p.add_argument('--config',type=Path)
    p.add_argument('--output',type=Path)
    p.add_argument('--ranks',type=int,default=1,help='MPI ranks; default serial. Execution detail, not a physics parameter.')
    p.add_argument('--reference',type=Path,help='Verified 2D native_final.npz, canonical XY mesh only')
    a=p.parse_args()
    if a.action in ['build','all']:
        if not a.config:p.error('--config is required to build')
        build(ForwardStep3DSpec.load(a.config),a.case)
    if a.action in ['execute','all']:execute(a.case,a.ranks)
    if a.action in ['analyze','all']:
        from pipeline.forward_step.diagnostics import diagnose
        from pipeline.forward_step.plots import make_plots
        from pipeline.forward_step.validate import validate
        out=a.output or a.case/'analysis'
        s=ForwardStep3DSpec.load(a.case/'spec.json');d,layout,data=diagnose(a.case,out,s,a.reference)
        v=validate(d);(out/'validation.json').write_text(json.dumps(v,indent=2))
        make_plots(a.case,out,s,layout,data,a.reference)
        print(json.dumps({'status':v['status'],'diagnostics':str(out/'diagnostics.json'),'failed':v['failed_checks']},indent=2))
        if v['failed_checks']:raise SystemExit(2)

if __name__=='__main__':main()
