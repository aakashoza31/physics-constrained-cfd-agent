"""Figure 1: conceptual illustration of the workflow (top) linked to the real
OpenFOAM fields of the archived runs (bottom).

The top panel is a fixed AI-generated conceptual illustration supplied by the
authors (data/fig1_concept/concept_illustration.png; see the README there). It
is schematic and is not simulation output. Its Mach-2 step tile is
replaced at build time by a forward-facing-step schematic (ffs_tile below), because
the supplied tile showed a backward-facing step. The bottom panels are the archived
ParaView frames in data/frames/, cropped as in the earlier Figure 1; colour
scales are sampled from the colour bars in those frames.
Run from paper/cfd_forge/:  python scripts/make_fig1_workflow.py
Writes figures/fig1_workflow.{pdf,png}.
"""
import numpy as np, matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Polygon, FancyBboxPatch, FancyArrowPatch
from matplotlib.colors import ListedColormap, Normalize
from matplotlib.cm import ScalarMappable
from PIL import Image
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
FR=str(ROOT/"data/frames")+"/"
CONCEPT=ROOT/"data/fig1_concept/concept_illustration.png"
OUT=ROOT/"figures"

from scipy.ndimage import gaussian_filter

def ffs_tile(wpx,hpx,scale=4):
    """Schematic Mach field for supersonic flow over a FORWARD-facing step (flow left to right):
    a curved detached shock stands upstream of the step face, subsonic flow behind it,
    expansion over the step corner. Purely illustrative (not simulation output)."""
    W,H=wpx*scale,hpx*scale
    L,Hc=3.0,1.0; xs=0.6*L/3*3; xs=1.25; hs=0.30   # step face at x=1.25, height 0.3 (illustrative)
    x=np.linspace(0,L,W); y=np.linspace(0,Hc,H); X,Y=np.meshgrid(x,y)
    xsh=xs-0.42+0.30*(Y/Hc)**2                      # curved bow shock ahead of the face
    M=np.full_like(X,2.0)
    behind=X>xsh
    d=np.clip((X-xsh)/0.5,0,1)
    M_sub=0.45+0.35*Y+0.15*d
    M=np.where(behind,M_sub,M)
    over=(X>xs)&(Y>hs)
    acc=np.clip((X-xs)/0.9,0,1)
    M=np.where(over,0.8+0.9*acc*(0.6+0.4*(Y-hs)/(Hc-hs)),M)
    # weak reflected oblique shock from the upper wall
    xr=xs+0.55+0.9*(Hc-Y)
    M=np.where(over&(X>xr),M-0.35*np.exp(-((X-xr)/0.15)**2)-0.15,M)
    M=gaussian_filter(M,sigma=scale*1.2)
    M[(X>=xs)&(Y<=hs)]=np.nan
    fig=plt.figure(figsize=(W/100,H/100),dpi=100); ax=fig.add_axes([0,0,1,1]); ax.axis("off")
    cm=plt.get_cmap("jet").copy(); cm.set_bad("#b7bfc8")
    ax.contourf(X,Y,M,levels=np.linspace(0.2,2.7,40),cmap=cm,extend="both")
    ax.add_patch(plt.Rectangle((xs,0),L-xs,hs,fc="#b7bfc8",ec="#123a6b",lw=2.2*scale/4))
    sx=xs-0.42+0.30*(y/Hc)**2; ax.plot(sx,y,color="#b00018",lw=1.2*scale/4,alpha=0.8)
    ax.plot([0,L,L,0,0],[0,0,Hc,Hc,0],color="#123a6b",lw=3*scale/4)
    ax.set_xlim(0,L); ax.set_ylim(0,Hc)
    fig.canvas.draw(); img=np.asarray(fig.canvas.buffer_rgba())[...,:3]; plt.close(fig)
    return np.asarray(Image.fromarray(img).resize((wpx,hpx),Image.LANCZOS))

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
stp=crop_field(stp_im); cub=cub_im[90:420,180:900].astype(np.uint8)
cmaps=[colorbar_cmap(noz_im),colorbar_cmap(stp_im),colorbar_cmap(cub_im)]

L,T=9,10
con0=np.asarray(Image.open(CONCEPT).convert("RGB")).copy()
# The supplied illustration drew a backward-facing step; replace that schematic tile
# (pixel box below) with a forward-facing-step schematic matching the simulated case.
STEP_TILE=(351,709,550,630)
x0t,x1t,y0t,y1t=STEP_TILE; con0[y0t:y1t,x0t:x1t]=ffs_tile(x1t-x0t,y1t-y0t)
con=con0[T:,L:]
H,W=con.shape[:2]
INK="#1f2328"; LINK="#24476b"
figw=7.2; top_h=figw*H/W; bot_h=1.95
fig=plt.figure(figsize=(figw,top_h+bot_h)); FH=top_h+bot_h
ft=top_h/FH; fb=bot_h/FH
a0=fig.add_axes([0,fb,1,ft]); a0.imshow(con); a0.axis("off")
bg=fig.add_axes([0,0,1,fb],zorder=-2); bg.set_facecolor("#f3f6fa"); bg.set_xticks([]); bg.set_yticks([]); [sp.set_visible(False) for sp in bg.spines.values()]
ov=fig.add_axes([0,0,1,1],zorder=-1); ov.set_xlim(0,1); ov.set_ylim(0,1); ov.axis("off"); ov.patch.set_alpha(0)
lab=fig.add_axes([0,0,1,1],zorder=6); lab.set_xlim(0,1); lab.set_ylim(0,1); lab.axis("off"); lab.patch.set_alpha(0)
# schematic tiles in raw-pixel x of the concept image
tiles=[(40,300),(350,715),(752,1140)]
panels=[(noz,cmaps[0],(0.2301,1.5657),"Mach","(a) Nozzle: Mach number, $t=6$ ms"),
        (stp,cmaps[1],(0.0023,3.484),"Mach","(b) Mach-2 step: Mach number, $t=4$"),
        (cub,cmaps[2],(-1.0138,1.0138),"$U_z$","(c) Cube: $U_z$ on $y/H=0.5$, $t^*=80$")]
pw=0.26
ytop=fb*0.70; titles=[]
for (tx0,tx1),(img,cm,(lo,hi),q,title) in zip(tiles,panels):
    xc_t=((tx0+tx1)/2-L)/W; x0=min(max(xc_t-pw/2,0.012),0.988-pw)
    a=fig.add_axes([x0,fb*0.27,pw,fb*0.43],zorder=2); a.imshow(img,aspect="equal"); a.axis("off")
    a.apply_aspect(); p=a.get_position()
    sx0=(tx0-L)/W; sx1=(tx1-L)/W; sy=fb+0.002
    xa=(sx0+sx1)/2
    lab.add_patch(FancyArrowPatch(((p.x0+p.x1)/2,sy+0.002),((p.x0+p.x1)/2,p.y1+0.009),arrowstyle="-|>",mutation_scale=11,lw=1.5,color=LINK))
    ov.add_patch(FancyBboxPatch((p.x0-0.004,p.y0-0.006),p.width+0.008,p.height+0.012,boxstyle="round,pad=0,rounding_size=0.006",fc="white",ec=LINK,lw=0.8))
    titles.append(((p.x0+p.x1)/2,p.y0,title))
    cax=fig.add_axes([(p.x0+p.x1)/2-0.08,fb*0.075,0.16,0.010],zorder=2)
    cb=fig.colorbar(ScalarMappable(Normalize(lo,hi),cm),cax=cax,orientation="horizontal")
    cb.set_ticks([lo,hi]); cb.ax.set_xticklabels([f"{lo:.2g}" if abs(lo)>0.01 else "0",f"{hi:.2g}"],fontsize=5.4)
    cb.outline.set_linewidth(0.4); cb.solids.set_rasterized(True); cb.ax.tick_params(length=1.5,width=0.4,pad=1)
    cb.ax.text(1.06,0.5,q,transform=cb.ax.transAxes,fontsize=5.6,va="center",ha="left")
ymin=min(t[1] for t in titles)
for xc,_,t in titles: lab.text(xc,ymin-0.016,t,ha="center",va="top",fontsize=6.5,color=INK)
lab.text(0.622,fb-0.018,"Real OpenFOAM results from the archived runs",ha="center",va="top",fontsize=6.2,fontweight="bold",color=LINK)
fig.savefig(OUT/"fig1_workflow.pdf",dpi=300); fig.savefig(OUT/"fig1_workflow.png",dpi=300)
