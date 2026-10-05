from pathlib import Path
import json
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch
ROOT=Path(__file__).resolve().parents[1]
RESULTS=ROOT/'recorded_results'
OUT=ROOT/'generated_figures';OUT.mkdir(exist_ok=True)
plt.rcParams.update({'font.family':'DejaVu Sans','font.size':11,'axes.labelsize':11,'xtick.labelsize':11,'ytick.labelsize':11,'legend.fontsize':11,'lines.linewidth':1.3,'axes.linewidth':1.,'pdf.fonttype':42,'svg.fonttype':'none'})
def save(fig,name):
    for ext in ['png','pdf','svg']:fig.savefig(OUT/f'{name}.{ext}',dpi=300,bbox_inches='tight',facecolor='white')
    plt.close(fig)
# Publication flowchart with explicit calculation stages.
fig=plt.figure(figsize=(6.5,4.1))
ax=fig.add_axes([0,0,1,1]);ax.set(xlim=(0,1),ylim=(0,1));ax.axis('off')
from matplotlib.patches import FancyBboxPatch
ink='#182733';arrow='#44545f'
def box(x,y,w,h,label,face,edge):
    patch=FancyBboxPatch((x,y),w,h,boxstyle='round,pad=0.008,rounding_size=0.018',
                        facecolor=face,edgecolor=edge,linewidth=1.1)
    ax.add_patch(patch)
    ax.text(x+w/2,y+h/2,label,ha='center',va='center',fontsize=10.8,
            color=ink,linespacing=1.45)
box(.025,.84,.95,.125,'Records with product, place, date, unit and provenance',
    '#e8edf2','#647886')
left=[('Received values\nand physical constraints','#eaf3fa'),
      ('Conditional bounds\nfor the supplied records','#eaf3fa'),
      ('Declared threshold\nAbove / below / unresolved','#d8eaf7')]
right=[('Groups, error allowances\nand missing-record budget','#eaf4ef'),
       ('Prospective uncertainty\nover possible readings','#eaf4ef'),
       ('Reporting assessment\nCompare additional observations','#d9ecdf')]
for y,(lt,lf),(rt,rf) in zip([.59,.32,.05],left,right):
    box(.025,y,.445,.17,lt,lf,'#4e7a97')
    box(.53,y,.445,.17,rt,rf,'#547d68')
# A shared source branches to the two calculations; arrowheads meet box borders.
ax.plot([.5,.5],[.832,.797],color=arrow,lw=1.25)
ax.plot([.2475,.7525],[.797,.797],color=arrow,lw=1.25)
for x in [.2475,.7525]:
    for start,end in [(.797,.77),(.582,.50),(.312,.23)]:
        ax.add_patch(FancyArrowPatch((x,start),(x,end),arrowstyle='-|>',
                     mutation_scale=12,linewidth=1.25,color=arrow,shrinkA=0,shrinkB=0))
# Fixed canvas preserves the figure size and 10.8-point labels in the manuscript.
for ext in ['png','pdf','svg']:
    fig.savefig(OUT/f'Figure_1.{ext}',dpi=300,facecolor='white')
plt.close(fig)
d=json.loads((RESULTS/'decision/RESULTS.json').read_text())
fig,axs=plt.subplots(2,1,figsize=(6.5,6.3),sharex=True,layout='constrained')
colors=['#777777','#14608a','#b05b15'];labels=['Information only','Total variation','Calibrated box']
for method,color,label in zip(['information_only','temflow_tv','calibrated_box'],colors,labels):
    rows=[x for x in d['decisions'] if x['method']==method and x['selection']=='all']
    x=[100*r['threshold'] for r in rows]
    axs[0].plot(x,[100*r['resolved_fraction'] for r in rows],marker='o',label=label,color=color)
    axs[1].plot(x,[100*r['wrong_among_resolved'] for r in rows],marker='o',label=label,color=color)
axs[0].set(ylim=(-1,102),ylabel='Questions resolved (%)');axs[0].legend(loc='upper left',frameon=False)
axs[1].set(ylim=(-.05,4.1),ylabel='Incorrect among resolved (%)',xlabel='Threshold as share of group total (%)',xticks=[5,10,25,50])
for a,letter in zip(axs,['A','B']):
    a.text(-.10,1.02,letter,transform=a.transAxes,fontweight='bold',fontsize=11);a.spines[['top','right']].set_visible(False)
save(fig,'Figure_2')
b=json.loads((RESULTS/'structural_comparison/RESULTS.json').read_text())
fig,axs=plt.subplots(2,1,figsize=(6.5,6.3),layout='constrained')
for ax,r,letter in zip(axs,[0,3],['A','B']):
    rows=sorted([c for c in b['cases'] if c['id'].startswith('balanced') and c['budget']==r],key=lambda c:c['destinations'])
    for method,color,label in zip(['temflow','record_stage_dp'],['#14608a','#b05b15'],['TEM-FLOW','Record-stage dynamic program']):
        x=[v['destinations'] for v in rows];y=[v['medians'][method]*1000 for v in rows]
        err=[[v['medians'][method]*1000-min(v['seconds'][method])*1000 for v in rows],[max(v['seconds'][method])*1000-v['medians'][method]*1000 for v in rows]]
        ax.errorbar(x,y,yerr=err,marker='o',label=label,color=color,capsize=3)
    ax.set(xscale='log',yscale='log',xlabel='Destinations',ylabel='Computation time (ms)')
    ax.text(-.10,1.02,letter,transform=ax.transAxes,fontweight='bold',fontsize=11);ax.spines[['top','right']].set_visible(False)
axs[0].legend(frameon=False)
save(fig,'Supplementary_Figure_S2')
print(OUT)
