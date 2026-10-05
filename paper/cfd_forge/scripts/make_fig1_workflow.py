"""Figure 1: illustrative manual workflow vs. CFD Forge, with fields from the archived runs.

Reads the archived ParaView frames in data/frames/ (colour scales are sampled from
the colour bars in those frames) and writes figures/fig1_workflow.{pdf,png}.
Run from paper/cfd_forge/:  python scripts/make_fig1_workflow.py
"""
import numpy as np, matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch, Circle, Rectangle, Polygon, Wedge
from matplotlib.colors import ListedColormap, Normalize
from matplotlib.cm import ScalarMappable
from PIL import Image
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
FR=str(ROOT/"data/frames")+"/"

def frame(path):
    return np.asarray(Image.open(path).convert("RGB")).astype(int)
def crop_field(im):
    bg=im[5,5]; d=np.abs(im-bg).sum(2)>40
    d[:60,:]=False; d[int(im.shape[0]*0.70):,:]=False
    ys,xs=np.where(d); out=im[ys.min():ys.max()+1, xs.min():xs.max()+1].copy()
    out[np.abs(out-bg).sum(2)<=40]=255
    return out.astype(np.uint8)
def colorbar_cmap(im):
    # ParaView colour bar: the widest run of non-background, saturated pixels in the lower part
    bg=im[5,5]; H=im.shape[0]
    best=None
    for y in range(int(H*0.70),H-5):
        row=im[y]; m=np.abs(row-bg).sum(1)>60
        xs=np.where(m)[0]
        if len(xs)<100: continue
        # longest contiguous run
        runs=np.split(xs,np.where(np.diff(xs)!=1)[0]+1); r=max(runs,key=len)
        if best is None or len(r)>len(best[1]): best=(y,r)
    y,r=best; cols=np.median(im[y+2:y+12, r[2]:r[-2]],axis=0)/255.0
    # remove the tick marks ParaView draws into the bar (isolated near-white columns)
    d=np.abs(np.diff(cols,axis=0)).sum(1); bad=set()
    for i in np.where(d>0.15)[0]:
        bad.update([i,i+1])
    good=np.array([i for i in range(len(cols)) if i not in bad])
    for ch in range(3): cols[:,ch]=np.interp(np.arange(len(cols)),good,cols[good,ch])
    return ListedColormap(cols)

noz_im=frame(FR+"nozzle_mach_t0.006.png"); stp_im=frame(FR+"step_mach_t4.png"); cub_im=frame(FR+"cube_Uz_t80.png")
noz=crop_field(noz_im); noz=np.concatenate([noz,noz[::-1]],0)
stp=crop_field(stp_im)
cub=cub_im[90:420,180:900].astype(np.uint8)
cmaps=[colorbar_cmap(noz_im),colorbar_cmap(stp_im),colorbar_cmap(cub_im)]

INK="#1f2328"; GREY="#57606a"
C_HUM="#8c959f"; C_LLM="#2f6db5"; C_TOOL="#3f9a5b"; C_GATE="#d9822b"
fig=plt.figure(figsize=(7.2,5.5))
ax=fig.add_axes([0,0.36,1,0.64]); ax.set_xlim(0,12); ax.set_ylim(0.35,7.0); ax.axis("off"); ax.set_aspect("auto")
xs=np.linspace(1.05,10.95,6); w=1.66

# ---------- icons ----------
def icon_request(x,y,c):
    ax.add_patch(FancyBboxPatch((x-0.34,y-0.18),0.68,0.42,boxstyle="round,pad=0.02,rounding_size=0.08",fc="white",ec=c,lw=1.2))
    ax.add_patch(Polygon([[x-0.18,y-0.2],[x-0.28,y-0.38],[x-0.04,y-0.2]],closed=True,fc="white",ec=c,lw=1.2))
    ax.add_patch(Rectangle((x-0.18,y-0.21),0.15,0.04,fc="white",ec="none"))
    for k,l in enumerate([0.44,0.36,0.26]): ax.plot([x-0.24,x-0.24+l],[y+0.12-k*0.1]*2,color=c,lw=1.1,solid_capstyle="round")
def icon_mesh(x,y,c):
    top=lambda t: 0.22-0.09*np.exp(-((t)/0.16)**2)
    t=np.linspace(-0.36,0.36,60)
    ax.plot(x+t,y+top(t),color=c,lw=1.2); ax.plot(x+t,y-top(t),color=c,lw=1.2)
    for tv in np.linspace(-0.36,0.36,7): ax.plot([x+tv,x+tv],[y-top(tv),y+top(tv)],color=c,lw=0.7)
    for f in [-0.5,0,0.5]: ax.plot(x+t,y+f*top(t),color=c,lw=0.7)
def icon_solve(x,y,c):
    for k in range(8):
        a=k*np.pi/4; ax.add_patch(Rectangle((x+0.25*np.cos(a)-0.05,y+0.25*np.sin(a)-0.05),0.1,0.1,angle=0,fc=c,ec="none"))
    ax.add_patch(Circle((x,y),0.24,fc=c,ec="none")); ax.add_patch(Circle((x,y),0.1,fc="white",ec="none"))
def icon_evidence(x,y,c):
    ax.plot([x-0.32,x-0.32,x+0.34],[y+0.26,y-0.22,y-0.22],color=c,lw=1.1)
    t=np.linspace(0,1,40); ax.plot(x-0.28+0.6*t,y-0.18+0.4*np.exp(-4*t),color=c,lw=1.3)
    ax.plot(x-0.28+0.6*t,y-0.18+0.25*np.exp(-2.5*t)+0.03*np.sin(20*t),color=c,lw=0.9,alpha=0.6)
def icon_decide(x,y,c):
    ax.add_patch(Polygon([[x-0.26,y+0.24],[x+0.26,y+0.24],[x+0.26,y],[x,y-0.3],[x-0.26,y]],closed=True,fc=c+"22",ec=c,lw=1.2,joinstyle="round"))
    ax.plot([x-0.12,x-0.02,x+0.14],[y+0.0,y-0.1,y+0.12],color=c,lw=1.6,solid_capstyle="round")
def icon_report(x,y,c):
    ax.add_patch(Polygon([[x-0.22,y-0.3],[x+0.22,y-0.3],[x+0.22,y+0.18],[x+0.1,y+0.3],[x-0.22,y+0.3]],closed=True,fc="white",ec=c,lw=1.2))
    for k,h in enumerate([0.12,0.22,0.16]): ax.add_patch(Rectangle((x-0.14+k*0.1,y-0.22),0.07,h,fc=c,ec="none"))
    ax.plot([x-0.14,x+0.08],[y+0.16,y+0.16],color=c,lw=0.9)
stages=["Request","Case & mesh","Solve","Evidence","Decision","Report"]
icons=[icon_request,icon_mesh,icon_solve,icon_evidence,icon_decide,icon_report]
for x,s,f in zip(xs,stages,icons):
    f(x,6.42,"#24476b"); ax.text(x,5.83,s,ha="center",va="center",fontsize=7.6,fontweight="bold",color="#24476b")

def box(x,y,txt,col,h=0.82,lw=1.0,fs=7.0):
    ax.add_patch(FancyBboxPatch((x-w/2,y-h/2),w,h,boxstyle="round,pad=0.02,rounding_size=0.12",fc=col+"20",ec=col,lw=lw))
    ax.text(x,y,txt,ha="center",va="center",fontsize=fs,color=INK,linespacing=1.15)
def arrow(x0,x1,y):
    ax.add_patch(FancyArrowPatch((x0+w/2,y),(x1-w/2,y),arrowstyle="-|>",mutation_scale=8,lw=0.9,color=INK))

# ---------- manual row ----------
yM=4.75
ax.text(0.22,yM+0.62,"Illustrative manual workflow",fontsize=8.2,fontweight="bold",color=INK)
man=["Engineer sets\ngoals and models","Builds case\nand mesh","Runs solver","Inspects results","Engineer\njudges result","Writes report"]
for i,(x,t) in enumerate(zip(xs,man)):
    box(x,yM,t,C_HUM)
    if i: arrow(xs[i-1],x,yM)

# ---------- CFD Forge row ----------
yF=2.55
ax.text(0.22,yF+0.78,"CFD Forge",fontsize=8.2,fontweight="bold",color=INK)
def split(x,y,top,bot,ctop,cbot,h=1.0):
    ax.add_patch(FancyBboxPatch((x-w/2,y-h/2),w,h,boxstyle="round,pad=0.02,rounding_size=0.12",fc="white",ec="#8c959f",lw=1.3))
    ax.add_patch(Rectangle((x-w/2+0.03,y),w-0.06,h/2-0.04,fc=ctop+"20",ec="none"))
    ax.add_patch(Rectangle((x-w/2+0.03,y-h/2+0.04),w-0.06,h/2-0.04,fc=cbot+"20",ec="none"))
    ax.text(x,y+h/4,top,ha="center",va="center",fontsize=6.8,color=INK)
    ax.text(x,y-h/4,bot,ha="center",va="center",fontsize=6.8,color=INK)
forge=[("LLM turns text\ninto a spec",C_LLM),("Family builder\nwrites case, mesh",C_TOOL),("OpenFOAM",C_TOOL),None,("Validators\ndecide",C_GATE),None]
for i,x in enumerate(xs):
    if i==3: split(x,yF,"Code measures","LLM proposes action",C_TOOL,C_LLM)
    elif i==5: split(x,yF,"LLM summary","Audit record",C_LLM,C_TOOL)
    else:
        t,c=forge[i]; box(x,yF,t,c,h=1.0,lw=1.4)
    if i: arrow(xs[i-1],x,yF)
# verdict badges
for k,(lab,sym,col) in enumerate([("ACCEPT","✓","#2e8b57"),("REJECT","✗","#c0392b"),("INCONCLUSIVE","?","#7f8c8d")]):
    xx=xs[4]+[-0.78,0.0,0.82][k]
    ax.add_patch(Circle((xx,yF+0.78),0.13,fc=col,ec="none"))
    ax.text(xx,yF+0.78,sym,ha="center",va="center",fontsize=7,color="white",fontweight="bold")
    ax.text(xx,yF+1.02,lab,ha="center",va="bottom",fontsize=5.0,color=col,fontweight="bold")
# correction loop
ax.add_patch(FancyArrowPatch((xs[4],yF-0.52),(xs[2]-0.35,yF-0.52),connectionstyle="arc3,rad=-0.18",arrowstyle="-|>",mutation_scale=8,lw=1.1,color=C_GATE))
ax.text((xs[2]+xs[4])/2-0.15,yF-1.42,"approved correction from a closed action set",ha="center",fontsize=6.6,color=C_GATE)

# legend
for j,(c,l) in enumerate([(C_LLM,"LLM call (proposes)"),(C_TOOL,"deterministic tool"),(C_GATE,"deterministic gate (decides)"),(C_HUM,"human step")]):
    ax.add_patch(FancyBboxPatch((0.45+j*2.95,0.45),0.3,0.2,boxstyle="round,pad=0.01",fc=c+"20",ec=c,lw=1))
    ax.text(0.86+j*2.95,0.55,l,va="center",fontsize=6.4,color=INK)

# ---------- fields ----------
panels=[(noz,cmaps[0],(0.2301,1.5657),"Mach","(a) Nozzle, Mach number, $t=6$ ms"),
        (stp,cmaps[1],(0.0023,3.484),"Mach","(b) Mach-2 step, Mach number, $t=4$"),
        (cub,cmaps[2],(-1.0138,1.0138),"$U_z$","(c) Cube, $U_z$ on $y/H=0.5$, $t^*=80$")]
for k,(img,cm,(lo,hi),q,lab) in enumerate(panels):
    a=fig.add_axes([0.03+k*0.325,0.105,0.29,0.21]); a.imshow(img,aspect="equal"); a.axis("off")
    fig.text(0.175+k*0.325,0.322,lab,ha="center",va="bottom",fontsize=6.9,color=INK)
    cax=fig.add_axes([0.065+k*0.325,0.065,0.22,0.014])
    cb=fig.colorbar(ScalarMappable(Normalize(lo,hi),cm),cax=cax,orientation="horizontal")
    cb.set_ticks([lo,(lo+hi)/2,hi]); cb.ax.set_xticklabels([f"{lo:.2g}" if abs(lo)>0.01 else "0",f"{(lo+hi)/2:.2g}",f"{hi:.2g}"],fontsize=5.8)
    cb.outline.set_linewidth(0.4); cb.solids.set_edgecolor('face'); cb.solids.set_rasterized(True); cb.ax.tick_params(length=2,width=0.4)
    cb.set_label(q,fontsize=6.2,labelpad=1)
OUT=ROOT/"figures"; fig.savefig(OUT/"fig1_workflow.pdf"); fig.savefig(OUT/"fig1_workflow.png",dpi=300)
