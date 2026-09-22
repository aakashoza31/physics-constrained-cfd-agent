"""Figures from native fields and native polyMesh vertices/faces, without invented data."""
from pathlib import Path
import re
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d.art3d import Line3DCollection
from matplotlib.patches import Rectangle
from .diagnostics import Layout

def edges(c):
    c=np.asarray(c)
    return np.r_[c[0]-(c[1]-c[0])/2,(c[1:]+c[:-1])/2,c[-1]+(c[-1]-c[-2])/2]

def actual_xy_edges(spec):
    a,b=spec.splits
    return (np.r_[np.linspace(0,spec.step_x,a+1),np.linspace(spec.step_x,spec.length,spec.nx-a+1)[1:]],
            np.r_[np.linspace(0,spec.step_height,b+1),np.linspace(spec.step_height,spec.height,spec.ny-b+1)[1:]])

def native_boundary_edges(case):
    mesh=Path(case)/'constant/polyMesh'
    text=(mesh/'points').read_text();m=re.search(r'\n\s*(\d+)\s*\n\(\s*(.*?)\n\)',text,re.S)
    if not m:raise ValueError('Unsupported points file')
    points=np.fromstring(m[2].replace('(',' ').replace(')',' '),sep=' ').reshape(-1,3)
    if len(points)!=int(m[1]):raise ValueError('Point count mismatch')
    faces=[np.fromstring(v,sep=' ',dtype=int) for v in re.findall(r'^\d+\(([^\n]*)\)',(mesh/'faces').read_text(),re.M)]
    boundary=(mesh/'boundary').read_text();pairs=set()
    for body in re.findall(r'\{([^{}]+)\}',boundary,re.S):
        start=re.search(r'startFace\s+(\d+);',body);n=re.search(r'nFaces\s+(\d+);',body)
        if not start or not n:continue
        for face in faces[int(start[1]):int(start[1])+int(n[1])]:
            for a,b in zip(face,np.roll(face,-1)):pairs.add(tuple(sorted((int(a),int(b)))))
    return points[np.array(sorted(pairs))]

def make_plots(case,out,spec,layout,data,reference=None):
    out=Path(out);figs=out/'figures';figs.mkdir(exist_ok=True)
    x,y,z=layout.axes;xe,ye=actual_xy_edges(spec);ze=edges(z)
    plt.rcParams.update({'font.size':11,'figure.dpi':145})
    def decorate(ax):
        ax.add_patch(Rectangle((spec.step_x,0),spec.length-spec.step_x,spec.step_height,facecolor='white',edgecolor='none',zorder=3))
        ax.plot([0,spec.step_x,spec.step_x,spec.length],[0,0,spec.step_height,spec.step_height],'k',lw=1)
        ax.set(xlim=(0,spec.length),ylim=(0,spec.height),xlabel='x (normalized)',ylabel='y (normalized)');ax.set_aspect('equal')
    for k in ['Mach','p','rho','T','speed']:
        fig,ax=plt.subplots(figsize=(12,4.5),layout='constrained')
        a=layout.mid_plane(data[k]);pc=ax.pcolormesh(xe,ye,a,shading='flat',cmap='viridis');decorate(ax)
        ax.set_title(f'{Path(case).name}: {k}, interpolated z=0 slice, t={spec.end_time:g}')
        fig.colorbar(pc,ax=ax,label=k);fig.savefig(figs/(k+'_midplane.png'));plt.close(fig)
    fig,axs=plt.subplots(3,1,figsize=(12,10),layout='constrained');g=layout.grid(data['rho'])
    for ax,j in zip(axs,[0,len(z)//2,len(z)-1]):
        pc=ax.pcolormesh(xe,ye,g[j],vmin=float(data['rho'].min()),vmax=float(data['rho'].max()),shading='flat');decorate(ax);ax.set_title(f'Density at native z={z[j]:.6g}, t={spec.end_time:g}')
    fig.colorbar(pc,ax=axs,label='rho');fig.savefig(figs/'spanwise_xy_slices.png');plt.close(fig)
    j=int(np.argmin(abs(y-.5*spec.height)));i=int(np.argmin(abs(x-.8*spec.length)))
    fig,axs=plt.subplots(2,1,figsize=(12,7),layout='constrained');g=layout.grid(data['Mach'])
    pc=axs[0].pcolormesh(xe,ze,g[:,j,:],shading='flat');axs[0].set(title=f'Mach x-z section at y={y[j]:.6g}',xlabel='x',ylabel='z');fig.colorbar(pc,ax=axs[0])
    pc=axs[1].pcolormesh(ye,ze,g[:,:,i],shading='flat');axs[1].set(title=f'Mach y-z section at x={x[i]:.6g}',xlabel='y',ylabel='z');fig.colorbar(pc,ax=axs[1]);fig.savefig(figs/'xz_yz_sections.png');plt.close(fig)
    fig,ax=plt.subplots(figsize=(12,4.5),layout='constrained')
    rho=layout.mid_plane(data['rho']);levels=np.linspace(1.4*spec.pressure/spec.temperature,6.4*spec.pressure/spec.temperature,30)
    ax.contour(x,y,rho,levels=levels,colors='#28495b',linewidths=.6);decorate(ax);ax.set_title(f'{Path(case).name}: native density contours at t={spec.end_time:g}')
    fig.savefig(figs/'shock_density_contours.png');plt.close(fig)
    # All exterior mesh edges come directly from OpenFOAM points/faces/boundary.
    segments=native_boundary_edges(case)
    fig=plt.figure(figsize=(13,6),layout='constrained');ax=fig.add_subplot(111,projection='3d')
    ax.add_collection3d(Line3DCollection(segments[:,:,[0,2,1]],colors='#426a82',linewidths=.10,alpha=.65))
    for zz in [-spec.span/2,spec.span/2]:
        px=[0,spec.step_x,spec.step_x,spec.length,spec.length,0,0]
        py=[0,0,spec.step_height,spec.step_height,spec.height,spec.height,0]
        ax.plot(px,[zz]*7,py,color='#183448',lw=.9)
    ax.set(xlim=(0,spec.length),ylim=(-spec.span/2,spec.span/2),zlim=(0,spec.height),xlabel='x',ylabel='z',zlabel='y',title='Native polyMesh boundary edges (span z visually expanded for readability)')
    ax.set_yticks([-spec.span/2,0,spec.span/2])
    ax.set_box_aspect((spec.length,max(spec.span,.5),spec.height));ax.view_init(20,-65);fig.savefig(figs/'mesh_3d.png',dpi=190);plt.close(fig)
    if reference:
        ref=np.load(reference);rl=Layout(ref['coordinates'])
        fig,axs=plt.subplots(3,2,figsize=(13,11),layout='constrained');rows=[]
        for row,yy in enumerate([.1,.5,.9]):
            j=int(np.argmin(abs(y-yy)))
            for col,k in enumerate(['p','rho']):
                ax=axs[row,col];a=layout.mid_plane(data[k])[j];b=rl.mid_plane(ref[k])[j]
                ax.plot(x,b,label='verified 2D');ax.plot(x,a,'--',label='3D z=0');ax.set(title=f'{k}, y={y[j]:.5g}',xlabel='x');ax.legend()
                if col==0:rows.extend(np.c_[np.full(len(x),y[j]),x,b,a,rl.mid_plane(ref['rho'])[j],layout.mid_plane(data['rho'])[j]].tolist())
        fig.savefig(figs/'profiles_2d_vs_3d.png');plt.close(fig)
        np.savetxt(out/'profiles_2d_vs_3d.csv',rows,delimiter=',',header='y,x,p_2d,p_3d,rho_2d,rho_3d',comments='')
    balance=np.loadtxt(out/'transient_mass.csv',delimiter=',',skiprows=1)
    fig,axs=plt.subplots(2,1,figsize=(10,7),layout='constrained');axs[0].plot(balance[:,0],balance[:,4]);axs[0].set(xlabel='Time',ylabel='Relative discrete mass residual');axs[1].plot(balance[:,0],balance[:,5]);axs[1].set(xlabel='Time',ylabel='Cumulative mass defect');fig.savefig(figs/'transient_conservation.png');plt.close(fig)
