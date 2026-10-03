"""Regenerate the manuscript comparison figure from recorded or fresh timings."""
from pathlib import Path
import argparse,json
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.ticker import ScalarFormatter

def main():
    p=argparse.ArgumentParser();p.add_argument('--results',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    a.output.mkdir(parents=True,exist_ok=False)
    rows=json.loads(a.results.read_text());by={(r['case'],r['method']):r for r in rows}
    plt.rcParams.update({'font.family':'DejaVu Sans','font.size':10.5,'axes.labelsize':10.5,'xtick.labelsize':10.5,'ytick.labelsize':10.5,'legend.fontsize':10.5,'pdf.fonttype':42,'svg.fonttype':'none'})
    fig,axes=plt.subplots(1,2,figsize=(6.25,4.3))
    methods=[('temflow','TEM-FLOW','#2166ac','o'),('expanded_dinic','Expanded network','#a35d08','s'),('paired_highs_lp','Linear programming','#6b4c9a','D')]
    for ax,panel in zip(axes,['A','B']):
        for method,label,color,marker in methods:
            xs=[4,8,16,32,128,1024] if panel=='A' else [0,1,2]
            values=[by[(f'balanced_L{x}_r0' if panel=='A' else f'balanced_L8_r{x}',method)] for x in xs]
            kept=[(x,row) for x,row in zip(xs,values) if row['status']=='pass']
            xx=[x for x,row in kept];yy=[row['median_seconds']*1000 for x,row in kept]
            errors=[[row['median_seconds']*1000-row['min_seconds']*1000 for x,row in kept],[row['max_seconds']*1000-row['median_seconds']*1000 for x,row in kept]]
            ax.errorbar(xx,yy,yerr=errors,marker=marker,color=color,label=label,lw=1.2,ms=4,capsize=3)
            for x,row in zip(xs,values):
                if row['status']=='timeout':ax.plot(x,10000,'^',color=color,mfc='none',ms=7,clip_on=False)
        ax.set_yscale('log');ax.grid(axis='y',alpha=.25);ax.spines[['top','right']].set_visible(False)
        ax.text(0,1.05,panel,transform=ax.transAxes,weight='bold',fontsize=12)
        ax.set_ylim(.04,25000)
        if panel=='A':
            ax.set_xscale('log',base=2);ax.set_xticks([4,32,128,1024]);ax.xaxis.set_major_formatter(ScalarFormatter());ax.set_xlabel('Destinations\nNo missing records');ax.set_ylabel('Computation time (ms)')
        else:ax.set_xticks([0,1,2]);ax.set_xlabel('Missing-record allowance\nEight destinations');ax.set_xlim(-.15,2.15)
    handles,labels=axes[0].get_legend_handles_labels();fig.legend(handles,labels,loc='upper center',bbox_to_anchor=(.52,.995),ncol=1,frameon=False)
    fig.subplots_adjust(top=.73,bottom=.19,left=.13,right=.98,wspace=.43)
    for ext in ('png','pdf','svg'):fig.savefig(a.output/f'Supplementary_Figure_S2_Computational_Efficiency.{ext}',dpi=350)
    print('Saved figure from '+str(a.results))

if __name__=='__main__':main()
