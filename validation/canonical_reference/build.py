#!/usr/bin/env python3
"""Deterministic Foundation v14 canonical conical nozzle; no LLM dependencies."""
import argparse, json, math
from pathlib import Path

def header(name,cls='dictionary'):
 return f'FoamFile {{ format ascii; class {cls}; object {name}; }}\n'
def write(path,text):
 path.parent.mkdir(parents=True,exist_ok=True);path.write_text(text)
def state(r,sup):
 ar=(r/.0326)**2
 lo,hi=(1.,5.) if sup else (1e-8,1.)
 for _ in range(90):
  m=(lo+hi)/2; a=((5+m*m)/6)**3/m
  if (a<ar)==sup:lo=m
  else:hi=m
 m=(lo+hi)/2;t=300/(1+.2*m*m);p=200000*(t/300)**3.5
 return p,t,m*math.sqrt(1.4*287*t)
def build(case,scale,co=.4,end=.006,angle=5.,perturb=0.):
 if case.exists():raise RuntimeError(f'Refusing to overwrite {case}')
 xs=[0,.05,.15,.16,.28,.33];rs=[.05,.05,.0326,.0326,.0354,.0354]
 nx=[round(n*scale) for n in (20,40,4,48,20)];nr=round(16*scale)
 a=math.radians(angle/2); verts=[]
 for x,r in zip(xs,rs):verts.extend([(x,0,0),(x,r*math.cos(a),-r*math.sin(a)),(x,r*math.cos(a),r*math.sin(a))])
 blocks=[];front=[];back=[];wall=[]
 for i,n in enumerate(nx):
  b=3*i;c=b+3
  blocks.append(f'hex ({b} {c} {c+1} {b+1} {b} {c} {c+2} {b+2}) ({n} {nr} 1) simpleGrading (1 1 1)')
  front.append(f'({b} {b+1} {c+1} {c})');back.append(f'({b} {c} {c+2} {b+2})');wall.append(f'({b+1} {b+2} {c+2} {c+1})')
 bd=''
 for name,typ,faces in [('inlet','patch',['(0 2 1 0)']),('outlet','patch',['(15 16 17 15)']),('walls','wall',wall),('wedgeFront','wedge',front),('wedgeBack','wedge',back)]:
  bd+=f'{name} {{ type {typ}; faces ( {" ".join(faces)} ); }}\n'
 write(case/'system/blockMeshDict',header('blockMeshDict')+'vertices (\n'+'\n'.join('(%.16g %.16g %.16g)'%v for v in verts)+'\n);\nblocks (\n'+'\n'.join(blocks)+'\n);\nedges ();\ndefaultPatch {name axis; type empty;}\nboundary (\n'+bd+');\n')
 write(case/'constant/physicalProperties',header('physicalProperties')+'''thermoType { type hePsiThermo; mixture pureMixture; transport const; thermo eConst; equationOfState perfectGas; specie specie; energy sensibleInternalEnergy; }
mixture { specie { molWeight 28.9702542045296; } thermodynamics { Cv 717.5; Hf 0; } transport { mu 0; Pr 1; } }
''')
 write(case/'constant/momentumTransport',header('momentumTransport')+'simulationType laminar;\n')
 write(case/'system/fvSchemes',header('fvSchemes')+'''fluxScheme Kurganov;
ddtSchemes { default Euler; }
gradSchemes { default Gauss linear; }
divSchemes { default none; }
laplacianSchemes { default Gauss linear corrected; }
interpolationSchemes { default linear; reconstruct(rho) Minmod; reconstruct(U) Minmod; reconstruct(T) Minmod; }
snGradSchemes { default corrected; }
''')
 write(case/'system/fvSolution',header('fvSolution')+'''solvers { "rho.*" { solver diagonal; } "(U|e).*" { solver diagonal; } }
PIMPLE { nOuterCorrectors 1; }
''')
 p,t,u=state(.05,False)
 for name,val,dim,bc in [('p',str(p),'pressure',f'type totalPressure; p0 uniform 200000; psi psi; gamma 1.4; value uniform {p};'),('T',str(t),'temperature',f'type totalTemperature; T0 uniform 300; gamma 1.4; psi psi; value uniform {t};'),('U',f'({u} 0 0)','velocity','type directionMixed; refValue uniform (0 0 0); refGradient uniform (0 0 0); valueFraction uniform (0 0 0 1 0 1);')]:
  cls='volVectorField' if name=='U' else 'volScalarField'
  wallbc='slip' if name=='U' else 'zeroGradient'
  write(case/'0'/name,header(name,cls)+f'dimensions [{dim}];\ninternalField uniform {val};\nboundaryField {{ inlet {{ {bc} }} outlet {{type zeroGradient;}} walls {{type {wallbc};}} wedgeFront {{type wedge;}} wedgeBack {{type wedge;}} axis {{type empty;}} }}\n')
 funcs='''mass {type volFieldValue; libs ("libfieldFunctionObjects.so"); cellZone all; operation volIntegrate; writeFields false; fields (rho); writeControl timeStep; writeInterval 1; log false;}
extrema {type volFieldValue; cellZone all; operation min; writeFields false; libs ("libfieldFunctionObjects.so"); fields (p T rho); writeControl timeStep; writeInterval 1; log false;}
'''
 for patch in ['inlet','outlet','walls','wedgeFront','wedgeBack']:
  funcs+=f'flux_{patch} {{type surfaceFieldValue; libs ("libfieldFunctionObjects.so"); patch {patch}; operation sum; fields (phi); writeFields false; writeControl timeStep; writeInterval 1; log false;}}\n'
 for patch in ['inlet','outlet']:
  funcs+=f'average_{patch} {{type surfaceFieldValue; libs ("libfieldFunctionObjects.so"); patch {patch}; operation areaAverage; fields (p T U); writeFields false; writeControl timeStep; writeInterval 20; log false;}}\n'
 write(case/'system/controlDict',header('controlDict')+f'''application foamRun;
solver shockFluid;
startFrom startTime; startTime 0; stopAt endTime; endTime {end};
deltaT 1e-8; adjustTimeStep yes; maxCo {co}; maxDeltaT 2e-6;
writeControl adjustableRunTime; writeInterval 0.00025; purgeWrite 0;
writeFormat ascii; writePrecision 14; writeCompression off; timePrecision 14;
runTimeModifiable false;
functions {{ {funcs} }}
''')
 write(case/'manifest.json',json.dumps(dict(scale=scale,axial_cells=sum(nx),radial_cells=nr,angle_deg=angle,maxCo=co,end_time=end,perturbation=perturb,ambient_pa=30000,ambient_imposed=False,solver='shockFluid',initialization='quasi_1d_internal_only',R=287,gamma=1.4),indent=2))
if __name__=='__main__':
 ap=argparse.ArgumentParser();ap.add_argument('case',type=Path);ap.add_argument('--scale',type=float,default=1);ap.add_argument('--co',type=float,default=.4);ap.add_argument('--end',type=float,default=.006);ap.add_argument('--angle',type=float,default=5.);ap.add_argument('--perturb',type=float,default=0.)
 a=ap.parse_args();build(a.case,a.scale,a.co,a.end,a.angle,a.perturb)
