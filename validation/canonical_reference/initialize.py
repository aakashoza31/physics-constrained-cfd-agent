#!/usr/bin/env python3
import json,re,sys
from pathlib import Path
import numpy as np
from build import state
from foamio import field
case=Path(sys.argv[1]);c=field(case/'0/C');manifest=json.loads((case/'manifest.json').read_text())
xs=np.array([0,.05,.15,.16,.28,.33]);rs=np.array([.05,.05,.0326,.0326,.0354,.0354])
values=[]
for x,y,z in c:
 j=min(np.searchsorted(xs,x,side='right')-1,4);r=np.interp(x,xs,rs);slope=(rs[j+1]-rs[j])/(xs[j+1]-xs[j])
 p,t,u=state(r,x>.16)
 p*=1+manifest['perturbation']*np.sin(np.pi*x/.33)
 # Quasi-1D axial velocity plus wall-tangent radial component. This is an
 # approximate startup, not an exact 2D steady solution or a persistent source.
 values.append((p,t,u,u*y*slope/r,u*z*slope/r))
v=np.array(values)
for name,arr in [('p',v[:,0]),('T',v[:,1]),('U',v[:,2:])]:
 path=case/'0'/name;text=path.read_text();vector=arr.ndim==2
 body='\n'.join('('+' '.join(f'{x:.16g}' for x in row)+')' for row in arr) if vector else '\n'.join(f'{x:.16g}' for x in arr)
 block=f'internalField nonuniform List<{"vector" if vector else "scalar"}>\n{len(arr)}\n(\n{body}\n);'
 text,n=re.subn(r'internalField\s+uniform\s+[^;]+;',block,text,count=1)
 if n!=1:raise ValueError(f'Refusing to reinitialize {path}')
 path.write_text(text)
 assert np.allclose(field(path),arr,rtol=1e-13,atol=1e-13)
assert v[:,0].min()<60000 and v[:,0].max()>190000
(case/'initialization_verified.json').write_text(json.dumps({'cells':len(c),'p_min':float(v[:,0].min()),'p_max':float(v[:,0].max()),'T_min':float(v[:,1].min()),'Uax_max':float(v[:,2].max()),'readback_pass':True},indent=2))
print((case/'initialization_verified.json').read_text())
