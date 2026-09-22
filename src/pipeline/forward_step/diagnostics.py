"""Native ASCII field measurements for the finite-time Euler step benchmark."""
from pathlib import Path
import json,re
import numpy as np
from .spec import ForwardStep3DSpec
from .build import TEMPLATE

R=8314.46261815324/11640.3
CP=2.5
GAMMA=CP/(CP-R)

def field(path,n=None,vector=False):
    text=Path(path).read_text()
    m=re.search(r'internalField\s+nonuniform\s+List<(scalar|vector)>\s+(\d+)\s*\((.*?)\)\s*;',text,re.S)
    if m:
        values=np.fromstring(m[3].replace('(',' ').replace(')',' '),sep=' ')
        count=int(m[2]);width=3 if m[1]=='vector' else 1
        if values.size!=count*width: raise ValueError('Invalid field size: '+str(path))
        return values.reshape(count,3) if width==3 else values
    m=re.search(r'internalField\s+uniform\s+([^;]+);',text)
    if not m or n is None: raise ValueError('Unsupported/missing native field: '+str(path))
    values=np.fromstring(m[1].replace('(',' ').replace(')',' '),sep=' ')
    return np.tile(values,(n,1)) if vector else np.full(n,values[0])

def state(case,time,n):
    p=Path(case)/str(time)
    data={k:field(p/k,n,k=='U') for k in ['p','T','rho','U']}
    data['speed']=np.linalg.norm(data['U'],axis=1)
    with np.errstate(invalid='ignore',divide='ignore'):
        data['Mach']=data['speed']/np.sqrt(GAMMA*R*data['T'])
    return data

def relative_errors(actual,reference):
    a=np.asarray(actual);b=np.asarray(reference)
    return {'relative_L2':float(np.linalg.norm(a-b)/max(np.linalg.norm(b),1e-300)),
            'relative_Linf':float(np.max(np.abs(a-b))/max(np.max(np.abs(b)),1e-300))}

def transient_balance(time,mass,fluxes):
    t=np.asarray(time);m=np.asarray(mass);dt=np.diff(t)
    if np.any(dt<=0): raise ValueError('Monitor times must increase strictly')
    net=sum(fluxes.values());scale=np.maximum(np.maximum(abs(fluxes['inlet']),abs(fluxes['outlet'])),1e-300)
    residual=np.diff(m)/dt+net[1:]
    cumulative=m[1:]-m[0]+np.cumsum(dt*net[1:])
    result={'final_inlet':float(-fluxes['inlet'][-1]),'final_outlet':float(fluxes['outlet'][-1]),
            'instantaneous_mismatch_fraction':float(net[-1]/scale[-1]),
            'relative_residual_max':float(np.max(abs(residual/scale[1:]))),
            'relative_residual_p99':float(np.quantile(abs(residual/scale[1:]),.99)),
            'cumulative_defect_fraction_initial_mass':float(cumulative[-1]/m[0]),
            'cumulative_defect_max_abs_fraction':float(np.max(abs(cumulative))/m[0]),
            'impermeable_flux_max_abs':float(max(np.max(abs(fluxes[k])) for k in ['top','bottom','obstacle'])),
            'periodic_pair_net_flux_max_abs':float(np.max(abs(fluxes.get('spanMinus',0)+fluxes.get('spanPlus',0))))}
    return result,np.c_[t[1:],m[1:],net[1:],residual,residual/scale[1:],cumulative]

class Layout:
    def __init__(self,xyz):
        self.xyz=np.asarray(xyz)
        self.axes=[np.unique(np.round(xyz[:,i],12)) for i in range(3)]
        self.indices=[np.searchsorted(a,np.round(xyz[:,i],12)) for i,a in enumerate(self.axes)]
        self.shape=tuple(len(a) for a in self.axes[::-1])
        if len(set(zip(*self.indices)))!=len(xyz): raise ValueError('Duplicate coordinate bins')
    def grid(self,a):
        out=np.full(self.shape+np.shape(a)[1:],np.nan)
        ix,iy,iz=self.indices;out[iz,iy,ix]=a
        return out
    def mean_plane(self,a):
        g=self.grid(a)
        # Every z plane has identical occupancy; avoid all-NaN solid warnings.
        return np.mean(g,axis=0)
    def mid_plane(self,a):
        g=self.grid(a);z=self.axes[2];j=np.searchsorted(z,0)
        if j<len(z) and abs(z[j])<1e-12:return g[j]
        if j==0 or j==len(z):raise ValueError('Midplane not bracketed')
        return (g[j-1]*z[j]-g[j]*z[j-1])/(z[j]-z[j-1])

def shock_metrics(layout,data,spec):
    x,y,_=layout.axes;p=layout.mid_plane(data['p']);rho=layout.mid_plane(data['rho']);T=layout.mid_plane(data['T'])
    search=x[:-1]<spec.step_x*1.3
    dp=np.diff(p,axis=1)/np.diff(x)[None,:]
    loc=np.nanargmax(dp[:,search],axis=1);front=(x[:-1]+np.diff(x)/2)[loc]
    lo=(y>.025*spec.height)&(y<min(.1*spec.height,.5*spec.step_height))
    fit=(y>.35*spec.height)&(y<.65*spec.height)
    angle=float(np.degrees(np.arctan2(1,np.polyfit(y[fit],front[fit],1)[0]))) if sum(fit)>=2 else None
    # Select plateau samples relative to detected front; no theoretical state imposed.
    xf=float(np.mean(front[lo]));dx=float(np.median(np.diff(x)))
    up=lo[:,None]&(x[None,:]>xf-13*dx)&(x[None,:]<xf-7*dx)
    down=lo[:,None]&(x[None,:]>xf+3*dx)&(x[None,:]<min(xf+7*dx,spec.step_x-2*dx))
    result={'lower_front_x':xf,'regional_angle_deg':angle,'upper_stem_x':float(np.mean(front[y>.85*spec.height])),
            'front_x_by_y':front.tolist(),'sample_counts':[int(up.sum()),int(down.sum())],
            'qualification':'Gradient-based regional measurements; moving/curved shocks and grid sensitivity prevent exact stationary-shock interpretation.'}
    if up.sum() and down.sum():
        result['jumps']={k:float(np.nanmean(a[down])/np.nanmean(a[up])) for k,a in [('p',p),('rho',rho),('T',T)]}
        M=float(np.nanmean(layout.mid_plane(data['Mach'])[up]));pr=1+2*GAMMA/(GAMMA+1)*(M*M-1);rr=(GAMMA+1)*M*M/((GAMMA-1)*M*M+2)
        result['sample_upstream_Mach']=M;result['stationary_normal_shock_sanity']={'p':pr,'rho':rr,'T':pr/rr}
    return result

def diagnose(case,output,spec=None,reference=None):
    case=Path(case);out=Path(output);out.mkdir(parents=True,exist_ok=True)
    spec=spec or ForwardStep3DSpec.load(case/'spec.json')
    xyz=field(case/'0/C',vector=True);n=len(xyz);vol=field(case/'0/Vc',n);layout=Layout(xyz)
    times=sorted([p.name for p in case.iterdir() if p.is_dir() and re.fullmatch(r'\d+(?:\.\d+)?',p.name) and float(p.name)>0],key=float)
    if not times:raise ValueError('No saved solution states')
    health=True;positive=True;history=[];allranges={k:[float('inf'),-float('inf')] for k in ['p','rho','T','speed','Mach']}
    previous=None;data=None
    for t in times:
        previous=data;data=state(case,t,n)
        health &= all(np.isfinite(a).all() for a in data.values())
        positive &= all((data[k]>0).all() for k in ['p','rho','T'])
        for k in allranges:
            allranges[k]=[min(allranges[k][0],float(np.min(data[k]))),max(allranges[k][1],float(np.max(data[k])))]
        momentum=np.sum((data['rho']*vol)[:,None]*data['U'],axis=0)
        history.append([float(t),float(np.sum(data['rho']*vol)),*momentum.tolist(),float(np.sum(data['rho']*vol*((CP-R)*data['T']+.5*data['speed']**2)))])
    log=(case/'log.foamRun').read_text();mesh=(case/'log.checkMesh').read_text()
    records=json.loads((case/'execution.json').read_text())
    solver_record=next(r for r in records if 'foamRun' in r['argv'])
    result={'spec':spec.to_dict(),'cells':n,'final_time':float(times[-1]),'saved_times':len(times),
            'solver_completed':all(r['returncode']==0 for r in records) and 'End' in log and float(times[-1])==spec.end_time,
            'mesh_ok':'Mesh OK.' in mesh,'three_solution_directions':'3 solution (non-empty) directions' in mesh,
            'fatal_error':'FOAM FATAL' in log or 'Floating point exception' in log,
            'finite_all_saved':bool(health),'positive_all_saved':bool(positive),'ranges_all_saved':allranges,
            'final_ranges':{k:[float(np.min(data[k])),float(np.max(data[k]))] for k in allranges},
            'runtime_seconds':solver_record['wall_seconds'],'steps':len(re.findall(r'^Time = ',log,re.M)),
            'actual_inlet_Mach':float(spec.velocity/np.sqrt(GAMMA*R*spec.temperature)),
            'gas':{'R':R,'gamma':GAMMA},'warnings':[l for l in log.splitlines() if 'Warning' in l],
            'energy_momentum_scope':'Stored domain totals only. Numerical boundary momentum/energy flux closure not computed; no closure claim.'}
    boundary=(case/'constant/polyMesh/boundary').read_text()
    result['boundary']={'no_empty_patches':not bool(re.search(r'\btype\s+empty;',boundary)),
                        'cyclic_patch_count':len(re.findall(r'\btype\s+cyclic;',boundary)),
                        'translational_patch_count':len(re.findall(r'\btransformType\s+translational;',boundary)),
                        'coupled_matching_ok':bool(re.search(r'Coupled point location match.*OK',mesh))}
    result['fixed_recipe_unchanged']=all((case/f).read_bytes()==(TEMPLATE/f).read_bytes() for f in ['system/fvSchemes','system/fvSolution','constant/physicalProperties','constant/momentumTransport'])
    actual_initial={k:field(case/'0'/k,n,k=='U') for k in ['p','T','U']}
    result['initial_state_errors']={'p':float(np.max(abs(actual_initial['p']-spec.pressure))),
                                    'T':float(np.max(abs(actual_initial['T']-spec.temperature))),
                                    'U':float(np.max(abs(actual_initial['U']-np.array([spec.velocity,0,0]))))}
    co=[float(v) for v in re.findall(r'Courant Number mean: \S+ max: (\S+)',log.split('Starting time loop')[-1])]
    result['Co']={'target':spec.max_co,'time_loop_max':max(co),'last':co[-1]}
    result['courant_finite_positive']=bool(np.isfinite(co).all() and np.min(co)>0)
    for key,pattern in [('max_nonorthogonality',r'Mesh non-orthogonality Max: (\S+)'),('max_skewness',r'Max skewness = (\S+)'),('max_aspect_ratio',r'Max aspect ratio = (\S+)')]:
        m=re.search(pattern,mesh);result[key]=float(m[1]) if m else None
    def monitor(name):return np.loadtxt(next((case/'postProcessing'/name/'0').glob('*.dat')),comments='#',ndmin=2)
    mass=monitor('mass');flux={}
    for k in ['inlet','outlet','bottom','top','obstacle','spanMinus','spanPlus']:
        a=monitor('flux_'+k)
        if not np.array_equal(a[:,0],mass[:,0]):raise ValueError('Monitor times differ')
        flux[k]=a[:,1]
    result['mass'],balances=transient_balance(mass[:,0],mass[:,1],flux)
    result['minima_every_step']=dict(zip(['rho','p','T'],monitor('minima')[:,1:].min(axis=0).tolist()))
    result['recent_change']={k:relative_errors(data[k],previous[k]) for k in ['p','rho','T','U']} if previous else {}
    result['spanwise']={}
    for k in ['p','rho','T','U','Mach','speed']:
        g=layout.grid(data[k]);mean=np.mean(g,axis=0);valid=np.isfinite(mean)
        errors=[relative_errors(plane[valid],mean[valid]) for plane in g]
        result['spanwise'][k]={'max_plane_relative_L2':max(e['relative_L2'] for e in errors),'max_deviation_over_peak_mean':max(e['relative_Linf'] for e in errors)}
    result['spanwise']['max_abs_Uz']=float(np.max(abs(data['U'][:,2])))
    result['spanwise']['max_abs_Uz_over_inlet_speed']=float(np.max(abs(data['U'][:,2]))/spec.velocity)
    result['spanwise']['L2_Uz_over_U']=float(np.linalg.norm(data['U'][:,2])/np.linalg.norm(data['U']))
    result['shock']=shock_metrics(layout,data,spec)
    if reference:
        ref=np.load(reference);ref_layout=Layout(ref['coordinates']);comparison={}
        if not all(np.allclose(layout.axes[i],ref_layout.axes[i],rtol=0,atol=1e-10) for i in [0,1]):raise ValueError('Reference and target XY grids must match')
        x,y,_=layout.axes
        for k in ['Mach','p','rho','T','U','speed']:
            a=layout.mid_plane(data[k]);b=ref_layout.mid_plane(ref[k]);valid=np.isfinite(b)
            comparison[k]=relative_errors(a[valid],b[valid])
            regional=(x[None,:]<.2)&(y[:,None]<.7)
            if k=='U':regional=np.broadcast_to(regional[...,None],b.shape)
            mask=valid&regional;comparison[k]['upstream_region']=relative_errors(a[mask],b[mask])
        rs=shock_metrics(ref_layout,{k:ref[k] for k in ['Mach','p','rho','T','U']},spec)
        comparison['shock_reference']=rs
        comparison['shock_differences']={k:result['shock'][k]-rs[k] for k in ['lower_front_x','upper_stem_x','regional_angle_deg']}
        if 'jumps' in rs and 'jumps' in result['shock']:
            comparison['relative_jump_differences']={k:result['shock']['jumps'][k]/rs['jumps'][k]-1 for k in ['p','rho','T']}
        result['comparison_2d']=comparison
    np.savetxt(out/'stored_totals.csv',history,delimiter=',',header='time,mass,momentum_x,momentum_y,momentum_z,total_energy',comments='')
    np.savetxt(out/'transient_mass.csv',balances,delimiter=',',header='time,mass,net_outward_flux,residual,relative_residual,cumulative_defect',comments='')
    np.savez_compressed(out/'native_final.npz',coordinates=xyz,volumes=vol,**data)
    if (out/'scientific_review.json').exists():
        result['scientific_review']=json.loads((out/'scientific_review.json').read_text())
    (out/'diagnostics.json').write_text(json.dumps(result,indent=2,allow_nan=False))
    return result,layout,data
