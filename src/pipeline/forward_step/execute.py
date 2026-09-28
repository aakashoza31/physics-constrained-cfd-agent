"""Explicit Linux/OpenFOAM execution; no implicit restart or timeout-as-physics rule."""
from pathlib import Path
import json,os,subprocess,time,shutil

def execute(case,ranks=1):
    case=Path(case).resolve()
    if os.environ.get('WM_PROJECT_VERSION')!='14':
        raise RuntimeError('Source OpenFOAM Foundation v14 before execution')
    if (case/'execution.json').exists() or (case/'log.foamRun').exists():
        raise FileExistsError('Existing execution evidence preserved; use a new case directory')
    if type(ranks) is not int or ranks<1:raise ValueError('ranks must be a positive integer')
    for command in ['blockMesh','checkMesh','foamPostProcess','foamRun']:
        if not shutil.which(command): raise RuntimeError(f'Missing executable: {command}')
    records=[]
    stages=[(['blockMesh'],'blockMesh'),(['checkMesh','-allTopology','-allGeometry'],'checkMesh'),
                      (['foamPostProcess','-func','writeCellCentres','-time','0'],'centres'),
                      (['foamPostProcess','-func','writeCellVolumes','-time','0'],'volumes')]
    if ranks>1:
        for program in ['mpirun','decomposePar','reconstructPar']:
            if not shutil.which(program):raise RuntimeError('Missing parallel executable: '+program)
        (case/'system/decomposeParDict').write_text('FoamFile { format ascii; class dictionary; object decomposeParDict; }\nnumberOfSubdomains '+str(ranks)+';\nmethod scotch;\n')
        stages.extend([(['decomposePar'],'decomposePar'),(['mpirun','--bind-to','none','-np',str(ranks),'foamRun','-parallel'],'foamRun'),(['reconstructPar','-noZero'],'reconstructPar')])
    else:stages.append((['foamRun'],'foamRun'))
    for args,name in stages:
        argv=args+['-case',str(case)];start=time.monotonic()
        with (case/('log.'+name)).open('w') as log:
            result=subprocess.run(argv,stdout=log,stderr=subprocess.STDOUT)
        records.append(dict(stage=name,argv=argv,returncode=result.returncode,wall_seconds=time.monotonic()-start))
        (case/'execution.json').write_text(json.dumps(records,indent=2))
        if result.returncode: raise RuntimeError(f'{name} failed: inspect {case / ("log."+name)}')
    return records
