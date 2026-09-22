"""Generate a three-block periodic mesh and preserve the canonical scheme recipe."""
from pathlib import Path
import hashlib,json,re,shutil
from .spec import ForwardStep3DSpec
from .initialize import initial_state

TEMPLATE=Path(__file__).parent/'template'

def mesh_dictionary(s):
    a,b=s.splits;L,H,x,h,w=s.length,s.height,s.step_x,s.step_height,s.span
    xy=[(0,0),(x,0),(0,h),(x,h),(L,h),(0,H),(x,H),(L,H)]
    vertices='\n'.join(f'    ({xx:.16g} {yy:.16g} {zz:.16g})' for zz in [-w/2,w/2] for xx,yy in xy)
    return f'''FoamFile {{ format ascii; class dictionary; object blockMeshDict; }}
vertices (\n{vertices}\n);
blocks (
 hex (0 1 3 2 8 9 11 10) ({a} {b} {s.nz}) simpleGrading (1 1 1)
 hex (2 3 6 5 10 11 14 13) ({a} {s.ny-b} {s.nz}) simpleGrading (1 1 1)
 hex (3 4 7 6 11 12 15 14) ({s.nx-a} {s.ny-b} {s.nz}) simpleGrading (1 1 1)
);
boundary (
 spanMinus {{ type cyclic; neighbourPatch spanPlus; faces ((0 2 3 1) (2 5 6 3) (3 6 7 4)); }}
 spanPlus {{ type cyclic; neighbourPatch spanMinus; faces ((8 9 11 10) (10 11 14 13) (11 12 15 14)); }}
 inlet {{ type patch; faces ((0 8 10 2) (2 10 13 5)); }}
 outlet {{ type patch; faces ((4 7 15 12)); }}
 bottom {{ type symmetryPlane; faces ((0 1 9 8)); }}
 top {{ type symmetryPlane; faces ((5 13 14 6) (6 14 15 7)); }}
 obstacle {{ type patch; faces ((1 3 11 9) (3 4 12 11)); }}
);
'''

def monitors():
    common='libs ("libfieldFunctionObjects.so"); writeFields false; writeControl timeStep; writeInterval 1; log false;'
    text='\nfunctions\n{\n'
    text+=f'mass {{ type volFieldValue; cellZone all; operation volIntegrate; fields (rho); {common} }}\n'
    text+=f'minima {{ type volFieldValue; cellZone all; operation min; fields (rho p T); {common} }}\n'
    for patch in ['inlet','outlet','bottom','top','obstacle','spanMinus','spanPlus']:
        text+=f'flux_{patch} {{ type surfaceFieldValue; patch {patch}; operation sum; fields (phi); {common} }}\n'
    return text+'}\n'

def build(spec:ForwardStep3DSpec,destination):
    dest=Path(destination)
    if dest.exists(): raise FileExistsError(f'Existing case preserved: {dest}')
    shutil.copytree(TEMPLATE,dest)
    (dest/'system/blockMeshDict').write_text(mesh_dictionary(spec))
    state=initial_state(spec)
    for name in ['p','T','U']:
        p=dest/'0'/name;t=p.read_text()
        t=re.sub(r'defaultFaces\s*\{\s*type\s+empty;\s*\}',
                 'spanMinus { type cyclic; }\n    spanPlus { type cyclic; }',t)
        val='('+ ' '.join(f'{v:.16g}' for v in state[name])+')' if name=='U' else f'{state[name]:.16g}'
        t=re.sub(r'(\b(?:internalField|value|inletValue)\s+uniform)\s+[^;]+;',lambda m:m[1]+' '+val+';',t)
        p.write_text(t)
    p=dest/'system/controlDict';t=p.read_text()
    for key,value in {'endTime':spec.end_time,'maxCo':spec.max_co,'writeInterval':spec.write_interval,'writePrecision':16,'timePrecision':14}.items():
        t=re.sub(r'\b'+key+r'\s+[^;]+;',f'{key} {value};',t)
    p.write_text(t+monitors())
    (dest/'spec.json').write_text(json.dumps(spec.to_dict(),indent=2))
    hashes={str(f.relative_to(TEMPLATE)):hashlib.sha256(f.read_bytes()).hexdigest() for f in sorted(TEMPLATE.rglob('*')) if f.is_file()}
    (dest/'template_hashes.json').write_text(json.dumps(hashes,indent=2))
    return dest
