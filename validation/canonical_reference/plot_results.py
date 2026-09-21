#!/usr/bin/env python3
"""Optional scientific figures from completed, validated native case data."""
import json,sys
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.tri import Triangulation
from foamio import field,table
from build import state
root=Path(sys.argv[1]);out=Path(sys.argv[2]);out.mkdir(parents=True,exist_ok=True)
plt.rcParams.update({'font.size':10,'axes.spines.top':False,'axes.spines.right':False,'figure.dpi':150})
colors=['#9AA1AC','#D58A27','#2D8990','#204E91']
fig,axs=plt.subplots(2,2,figsize=(11,7),layout='constrained')
for i,c in enumerate(colors,1):
 d=root/f'mesh{i}';a=np.loadtxt(d/'axial_profile.csv',delimiter=',',skiprows=1);m=json.loads((d/'manifest.json').read_text())
 for ax,col,label in zip(axs.flat,[1,4,2,3],['Static pressure (kPa)','Mach number','Static temperature (K)','Speed (m/s)']):
  ax.plot(a[:,0],a[:,col]/(1000 if col==1 else 1),color=c,label=f"{m['axial_cells']*m['radial_cells']:,} cells",lw=1.5);ax.set(xlabel='Axial position (m)',ylabel=label);ax.axvspan(.15,.16,color='#CCCCCC',alpha=.3);ax.grid(alpha=.2)
x=np.linspace(0,.33,700);r=np.interp(x,[0,.05,.15,.16,.28,.33],[.05,.05,.0326,.0326,.0354,.0354]);s=np.array([state(rr,xx>.16) for xx,rr in zip(x,r)]);theory=[s[:,0]/1000,s[:,2]/np.sqrt(1.4*287*s[:,1]),s[:,1],s[:,2]]
for ax,y in zip(axs.flat,theory):ax.plot(x,y,'--',color='#222222',lw=1,label='Quasi-1D comparison')
axs[0,0].legend(fontsize=8);fig.suptitle('Canonical conical nozzle: mesh sensitivity at 6 ms')
fig.savefig(out/'reference_profiles.png');plt.close(fig)
case=root/'mesh4';c=field(case/'0/C');T=field(case/'0.006/T');p=field(case/'0.006/p');u=field(case/'0.006/U');ma=np.linalg.norm(u,axis=1)/np.sqrt(1.4*287*T)
tri=Triangulation(c[:,0],c[:,1]);tc=c[tri.triangles].mean(axis=1)
tri.set_mask(tc[:,1]>np.interp(tc[:,0],[0,.05,.15,.16,.28,.33],[.05,.05,.0326,.0326,.0354,.0354]))
fig,axs=plt.subplots(2,1,figsize=(11,5.5),layout='constrained')
for ax,v,title in zip(axs,[p/1000,ma],['Pressure (kPa)','Mach number']):
 h=ax.tricontourf(tri,v,levels=35,cmap='viridis');ax.plot(x,r,'k',lw=1);ax.plot(x,np.zeros_like(x),'k',lw=.7);ax.set(xlim=(0,.33),ylim=(0,.053),ylabel='Radius (m)',xlabel='Axial position (m)',title=title);fig.colorbar(h,ax=ax,shrink=.88)
fig.suptitle('Finest axisymmetric wedge: internal fields at 6 ms')
fig.savefig(out/'reference_fields.png');plt.close(fig)
fig,axs=plt.subplots(2,1,figsize=(10,6),layout='constrained')
for i,c in enumerate(colors,1):
 d=root/f'mesh{i}';ri=table(d/'postProcessing/flux_inlet/0/surfaceFieldValue.dat');ro=table(d/'postProcessing/flux_outlet/0/surfaceFieldValue.dat');mis=100*abs(ri[:,1]+ro[:,1])/np.maximum(abs(ri[:,1]),abs(ro[:,1]));ix=np.linspace(1,len(ri)-1,2500,dtype=int)
 axs[0].semilogy(ri[ix,0]*1000,np.maximum(mis[ix],1e-8),color=c,lw=.9,label=f'Mesh {i}')
 v=json.loads((d/'validation.json').read_text());hist=v['history'];axs[1].plot([z['time']*1000 for z in hist],[z['outlet_p']/1000 for z in hist],color=c,label=f'Mesh {i}')
axs[0].axhline(.1,color='black',ls='--',label='0.1% acceptance bound');axs[0].set(ylabel='Boundary mismatch (%)',xlabel='Physical time (ms)');axs[0].legend(fontsize=8)
axs[1].set(ylabel='Exit static pressure (kPa)',xlabel='Physical time (ms)')
for ax in axs:ax.axvspan(4,6,color='#B4D4BB',alpha=.2);ax.grid(alpha=.2)
fig.suptitle('Settling and steady mass balance; shaded region is the acceptance window')
fig.savefig(out/'convergence.png');plt.close(fig)
replay=Path(__file__).parent/'audit_evidence/failure_replay.json'
if replay.exists():
 d=json.loads(replay.read_text())['history'];fig,ax=plt.subplots(figsize=(9,4),layout='constrained');ax.plot([r['time']*1e6 for r in d],[r['Tmin'] for r in d],color='#A63838',marker='.',ms=4);ax.axhline(0,color='black',ls='--');ax.set(xlabel='Physical time (microseconds)',ylabel='Cell 106 temperature (K)',title='Archived failure replay: loss of positive internal temperature');ax.grid(alpha=.2);fig.savefig(out/'crash_replay.png');plt.close(fig)
print(out)
