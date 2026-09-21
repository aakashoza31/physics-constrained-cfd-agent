#!/usr/bin/env python3
"""Fail-closed CFD verification. Native numerical phi, actual mesh volumes.

All mass flows are scaled from the planar wedge to the full circular nozzle.
This corrects its polygon-sector area (sin(theta)), not just theta in radians.
"""
import argparse,json,math,re,sys
from pathlib import Path
import numpy as np
from foamio import field,value,table
from build import state

def mesh_list(path):
 s=path.read_text();m=re.search(r'\n\s*(\d+)\s*\n\((.*?)\n\)',s,re.S)
 if not m:raise ValueError(f'Cannot read mesh list {path}')
 return m[2]
def patch_geometry(case):
 pm=case/'constant/polyMesh';points=np.fromstring(mesh_list(pm/'points').replace('(',' ').replace(')',' '),sep=' ').reshape(-1,3)
 faces=[list(map(int,s.split())) for s in re.findall(r'\d+\(([^)]+)\)',mesh_list(pm/'faces'))]
 out={}
 for name,body in re.findall(r'(\w+)\s*\{([^{}]*)\}',(pm/'boundary').read_text()):
  n=re.search(r'nFaces\s+(\d+)',body);start=re.search(r'startFace\s+(\d+)',body)
  if not n:continue
  n=int(n[1]);start=int(start[1]);sf=[]
  for f in faces[start:start+n]:
   p=points[f];sf.append(.5*np.cross(p,np.roll(p,-1,axis=0)).sum(axis=0))
  out[name]=np.array(sf).reshape(-1,3)
 return out
def boundary(path,patch,n,vector=False,owners=None):
 t=path.read_text();m=re.search(r'\b'+re.escape(patch)+r'\s*\{([^{}]*)\}',t,re.S)
 if not m:raise ValueError(f'Missing patch {patch}')
 if re.search(r'\bvalue\s',m[1]):return value(m[1],'value',n,vector)
 if 'zeroGradient' in m[1] and owners is not None:return field(path)[owners]
 if 'directionMixed' in m[1] and owners is not None:
  a=field(path)[owners].copy();a[:,1:]=0;return a
 raise ValueError(f'Unsupported boundary storage: {path} {patch}')
def monitor(case,name,kind='vol'):
 return table(case/'postProcessing'/name/'0'/f'{kind}FieldValue.dat')
def relspan(a):return float(np.ptp(a)/max(abs(np.mean(a)),1e-12))
def inspect(case,partial=False):
 manifest=json.loads((case/'manifest.json').read_text());sf=patch_geometry(case)
 pm=case/'constant/polyMesh';own=np.fromstring(mesh_list(pm/'owner'),sep=' ',dtype=int);patchowners={}
 for name,body in re.findall(r'(\w+)\s*\{([^{}]*)\}',(pm/'boundary').read_text()):
  n=re.search(r'nFaces\s+(\d+)',body);st=re.search(r'startFace\s+(\d+)',body)
  if n:patchowners[name]=own[int(st[1]):int(st[1])+int(n[1])]
 coords=field(case/'0/C');vol=field(case/'0/Vc',count=len(coords));N=len(coords)
 full=2*math.pi/math.sin(math.radians(manifest['angle_deg']))
 times=sorted([(float(p.name),p) for p in case.iterdir() if p.is_dir() and re.fullmatch(r'[0-9.eE+-]+',p.name) and float(p.name)>0])
 if not times:raise ValueError('No saved solution fields')
 rows=[];all_ok=True;field_arrays=[];enthalpy_max=0.
 for time,folder in times:
  f={k:field(folder/k,count=N,vector=k=='U') for k in ['p','T','rho','U']}
  all_ok &= all(np.isfinite(a).all() for a in f.values()) and all((f[k]>0).all() for k in ['p','T','rho'])
  if not all_ok:raise ValueError(f'Nonphysical internal field at {time}')
  speed=np.linalg.norm(f['U'],axis=1);mach=speed/np.sqrt(1.4*287*f['T'])
  h0=1004.5*f['T']+.5*speed**2
  enthalpy_max=max(enthalpy_max,float(np.max(abs(h0/(1004.5*300)-1))))
  x=coords[:,0];throat=(x>.150)&(x<.160)
  row={'time':time,'throat_M':float(np.average(mach[throat],weights=vol[throat])), 'domain_mass':float(np.sum(f['rho']*vol)*full)}
  for patch in ['inlet','outlet']:
   area=np.linalg.norm(sf[patch],axis=1);n=len(area)
   b={k:boundary(folder/k,patch,n,k=='U',patchowners[patch]) for k in ['p','T','rho','U']}
   if not all(np.isfinite(a).all() for a in b.values()) or any((b[k]<=0).any() for k in ['p','T','rho']):raise ValueError('Invalid boundary state')
   un=np.sum(b['U']*sf[patch],axis=1)/area
   bm=np.linalg.norm(b['U'],axis=1)/np.sqrt(1.4*287*b['T'])
   row.update({f'{patch}_p':float(np.average(b['p'],weights=area)),f'{patch}_T':float(np.average(b['T'],weights=area)),f'{patch}_U':float(np.average(np.linalg.norm(b['U'],axis=1),weights=area)),f'{patch}_M':float(np.average(bm,weights=area)),f'{patch}_normal_M_min':float(np.min(un/np.sqrt(1.4*287*b['T']))),f'{patch}_physical_mdot':float(np.sum(b['rho']*un*area)*full)})
   row[f'{patch}_normal_M_max']=float(np.max(un/np.sqrt(1.4*287*b['T'])))
   row[f'{patch}_M_max']=float(bm.max())
   if patch=='inlet':
    row['inlet_max_p0_relative_error']=float(np.max(abs(b['p']*(1+.2*bm*bm)**3.5/200000-1)))
    row['inlet_max_T0_relative_error']=float(np.max(abs(b['T']*(1+.2*bm*bm)/300-1)))
  row.update(p_min=float(f['p'].min()),p_max=float(f['p'].max()),T_min=float(f['T'].min()),T_max=float(f['T'].max()),rho_min=float(f['rho'].min()))
  rows.append(row);field_arrays.append(f)
 mass=monitor(case,'mass');fluxes=[monitor(case,'flux_'+p,'surface') for p in ['inlet','outlet','walls','wedgeFront','wedgeBack']]
 if partial:
  # Concurrent writers may be a few timesteps apart. Partial reports have no
  # authority to accept a run; align only their common, completed prefix.
  n=min(len(mass),*(len(a) for a in fluxes));mass=mass[:n];fluxes=[a[:n] for a in fluxes]
 for a in fluxes:
  if a.shape!=mass.shape or not np.allclose(a[:,0],mass[:,0],rtol=1e-12,atol=1e-15):raise ValueError('Mass/flux time alignment failure')
 t=mass[:,0];dt=np.diff(t)
 if (dt<=0).any():raise ValueError('Non-increasing time')
 net=sum(a[:,1] for a in fluxes)
 mdin=-fluxes[0][:,1];mdout=fluxes[1][:,1];scale=np.maximum(np.maximum(abs(mdin),abs(mdout)),1e-15)
 # Euler's discrete derivative, with phi actually used in that update.
 continuity=(np.diff(mass[:,1])/dt+net[1:])/scale[1:]
 window=t>=t[-1]-.002
 drift={k:relspan(np.array([r[k] for r in rows if r['time']>=times[-1][0]-.002-1e-12])) for k in ['outlet_p','outlet_T','outlet_U','outlet_M','throat_M','domain_mass']}
 drift['inlet_mdot']=relspan(mdin[window]);drift['outlet_mdot']=relspan(mdout[window])
 mismatch=abs(mdin-mdout)/scale
 final=rows[-1];final.update(inlet_mdot=float(mdin[-1]*full),outlet_mdot=float(mdout[-1]*full),boundary_mismatch_pct=float(100*mismatch[-1]),max_window_mismatch_pct=float(100*mismatch[window].max()))
 f0=field_arrays[max(0,len(field_arrays)-9)];f1=field_arrays[-1]
 l2={}
 for k in ['p','T','rho','U']:
  a=f1[k]-f0[k];b=f1[k]
  if a.ndim==2:a=np.sum(a*a,axis=1);b=np.sum(b*b,axis=1)
  else:a=a*a;b=b*b
  l2[k]=float(np.sqrt(np.sum(vol*a)/np.sum(vol*b)))
 ext=monitor(case,'extrema');alltime_min=ext[:,1:].min(axis=0).tolist()
 log=(case/'log.foamRun').read_text();cos=np.array([float(s) for s in re.findall(r'Courant Number mean: \S+ max: (\S+)',log)])
 steps=np.array([float(s) for s in re.findall(r'^Time = ([\d.eE+-]+)s',log,re.M)])
 code=int((case/'solver.exitcode').read_text()) if (case/'solver.exitcode').exists() else None
 pe,te,ue=state(.0354,True);me=ue/math.sqrt(1.4*287*te);md=math.pi*.0326**2*200000/math.sqrt(300)*math.sqrt(1.4/287)*(2/2.4)**3
 theory=dict(outlet_p=pe,outlet_T=te,outlet_U=ue,outlet_M=me,outlet_mdot=md)
 errors={k:100*(final[k]/v-1) for k,v in theory.items()}
 numerical_vs_physical=max(abs(final['outlet_physical_mdot']/final['outlet_mdot']-1),abs(-final['inlet_physical_mdot']/final['inlet_mdot']-1))
 # Radially volume-weighted axial profiles (cell-slab averages). Preserve actual
 # throat length and conical corners; quasi-1D is a comparison, not the PDE.
 nx=[round(n*manifest['scale']) for n in (20,40,4,48,20)]
 xs=[0,.05,.15,.16,.28,.33]
 edges=np.concatenate([np.linspace(xs[j],xs[j+1],n+1)[:-1] for j,n in enumerate(nx)]+[np.array([.33])])
 groups=np.searchsorted(edges,coords[:,0],side='right')-1
 ff=field_arrays[-1];sp=np.linalg.norm(ff['U'],axis=1);ma=sp/np.sqrt(1.4*287*ff['T']);profile=[]
 for j in range(len(edges)-1):
  mask=groups==j
  profile.append([.5*(edges[j]+edges[j+1])]+[float(np.average(arr[mask],weights=vol[mask])) for arr in (ff['p'],ff['T'],sp,ma)])
 profile=np.array(profile)
 np.savetxt(case/'axial_profile.csv',profile,delimiter=',',header='x_m,p_Pa,T_K,U_m_s,Mach',comments='')
 downstream_min=float(profile[profile[:,0]>.17,4].min())
 checks={
 'solver_completed':code==0 and bool(re.search(r'^End\s*$',log,re.M)) and steps.size>0 and abs(steps[-1]-manifest['end_time'])<1e-10,
 'mesh_ok':'Mesh OK' in (case/'log.checkMesh').read_text(),
 'initialized':json.loads((case/'initialization_verified.json').read_text())['readback_pass'],
 'no_fatal':not bool(re.search(r'FOAM FATAL|Floating point exception \(core dumped\)|^#\d+.*sigFpe|\bnan\b',log,re.I|re.M)),
 'positive_finite':bool(all_ok and min(alltime_min)>0),
 'courant':bool(cos.size and np.max(cos)<=manifest['maxCo']*1.02),
 'physical_time':bool(t[-1]>=.006-1e-10 and np.median(dt[-100:])>1e-9),
 'outlet_all_supersonic':final['outlet_normal_M_min']>1.05,
 'inlet_subsonic_inflow':final['inlet_M_max']<1 and final['inlet_normal_M_max']<0,
 'reservoir_conditions':max(final['inlet_max_p0_relative_error'],final['inlet_max_T0_relative_error'])<.001,
 'sonic_throat':.9<final['throat_M']<1.1,
 'underexpanded_exit':final['outlet_p']>30000,
 'no_internal_normal_shock':downstream_min>1,
 'steady_mass_balance':bool(mismatch[window].max()<.001),
 'transient_continuity':bool(np.max(abs(continuity))<1e-4),
 'monitors_stationary':max(drift.values())<.002,
 'fields_stationary':max(l2.values())<.002,
 'stagnation_enthalpy':enthalpy_max<.05,
 'theory_consistency':abs(errors['outlet_p'])<5 and all(abs(v)<3 for k,v in errors.items() if k!='outlet_p'),
 'physical_numerical_flux_consistency':numerical_vs_physical<.005,
 }
 checks={k:bool(v) for k,v in checks.items()}
 result={'status':'PASS_SINGLE_MESH' if all(checks.values()) else ('RUNNING' if partial and code is None else 'FAIL'),'case':str(case),'checks':checks,'final':final,'theory':theory,'theory_error_pct':errors,'max_Co':float(cos.max()),'timesteps':len(steps),'final_dt':float(dt[-1]),'all_time_min_p_T_rho':alltime_min,'max_transient_continuity_pct':float(100*max(abs(continuity))),'drift_fraction_last_2ms':drift,'field_L2_change_last_2ms':l2,'max_saved_h0_relative_error':enthalpy_max,'physical_numerical_flux_relative_difference':numerical_vs_physical,'history':rows,'sector_to_full_flow_factor':full,'residual_note':'Diagonal inviscid explicit updates print zero linear residuals; these are not steady-convergence evidence.'}
 result['min_downstream_slab_Mach']=downstream_min
 (case/'validation.json').write_text(json.dumps(result,indent=2,allow_nan=False))
 print(json.dumps({k:v for k,v in result.items() if k not in ['history']},indent=2))
 return result
def study(root):
 results=[json.loads((root/f'mesh{i}/validation.json').read_text()) for i in (1,2,3,4)]
 keys=['outlet_p','outlet_T','outlet_U','outlet_M','outlet_mdot','throat_M']
 changes={k:100*abs(results[-1]['final'][k]/results[-2]['final'][k]-1) for k in keys}
 coarse_changes=[{k:100*abs(b['final'][k]/a['final'][k]-1) for k in keys} for a,b in zip(results[:-1],results[1:])]
 ok=all(r['status']=='PASS_SINGLE_MESH' for r in results) and max(changes.values())<.5
 r={'status':'PASS_SPATIAL_STUDY' if ok else 'FAIL','last_pair_change_pct':changes,'successive_mesh_changes_pct':coarse_changes,'acceptance':'Every mesh passes; last-pair changes below 0.5%; temporal, wedge-angle and startup verification also required for FINAL_REFERENCE.'}
 sensitivity={}
 for name in ['time_half','angle_half','startup_perturbed']:
  extra=json.loads((root/name/'validation.json').read_text())
  delta={k:100*abs(extra['final'][k]/results[0]['final'][k]-1) for k in keys}
  sensitivity[name]={'status':extra['status'],'change_pct':delta,'pass':extra['status']=='PASS_SINGLE_MESH' and max(delta.values())<.2}
 r['sensitivity_on_coarse_mesh']=sensitivity
 r['status']='FINAL_REFERENCE' if ok and all(s['pass'] for s in sensitivity.values()) else 'FAIL'
 r['scope']='Canonical axisymmetric internal inviscid nozzle only. Timestep, angle and startup sensitivity evaluated on coarse mesh; spatial refinement uses a common acoustic Courant bound.'
 (root/'study.json').write_text(json.dumps(r,indent=2));print(json.dumps(r,indent=2));return r
if __name__=='__main__':
 ap=argparse.ArgumentParser();ap.add_argument('case',type=Path,nargs='?');ap.add_argument('--partial',action='store_true');ap.add_argument('--study',type=Path);a=ap.parse_args()
 try:r=study(a.study) if a.study else inspect(a.case,a.partial)
 except Exception as e:
  print(json.dumps({'status':'ERROR','reason':str(e)}));sys.exit(2)
 sys.exit(0 if r['status'].startswith('PASS') or r['status']=='FINAL_REFERENCE' or a.partial else 1)
