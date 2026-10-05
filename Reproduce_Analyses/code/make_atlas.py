from pathlib import Path
import json,matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'generated_figures';OUT.mkdir(exist_ok=True)
plt.rcParams.update({'font.family':'DejaVu Sans','font.size':10.5,'text.color':'#17212b'})

import csv
from matplotlib.patches import Polygon, Patch
from matplotlib.lines import Line2D
import argparse
from source_location import locate_source
parser=argparse.ArgumentParser(description='Regenerate the African atlas from companion source geography.')
parser.add_argument('--source-root',type=Path)
args=parser.parse_args()
SOURCE=locate_source(ROOT,args.source_root)
DATA=SOURCE/'src/temflow/data/patterns'
fig=plt.figure(figsize=(6.25,8.0));ax=fig.add_axes([.025,.18,.95,.75])
def rings(g):
    c=g.get('coordinates',[])
    return c if g.get('type')=='Polygon' else [r for p in c for r in p] if g.get('type')=='MultiPolygon' else []
for f in json.loads((DATA/'africa_countries.geojson').read_text(encoding='utf-8'))['features']:
    for r in rings(f['geometry']):ax.add_patch(Polygon([p[:2] for p in r],facecolor='#f5f1e8',edgecolor='#88969e',lw=.45))
for p in json.loads((DATA/'africa_route_display_geometries.json').read_text(encoding='utf-8')).get('paths',{}).values():
    c=p.get('coordinates',[])
    if len(c)>1:ax.plot([v[0] for v in c],[v[1] for v in c],lw=.18,color='#667985',alpha=.14)
for f in json.loads((DATA/'africa_major_lakes.geojson').read_text(encoding='utf-8'))['features']:
    for r in rings(f['geometry']):ax.add_patch(Polygon([p[:2] for p in r],facecolor='#9dc9df',edgecolor='#35749b',lw=.35))
coords=[]
for row in csv.DictReader((DATA/'continental_geolocated_nodes_v1_2.csv').open(encoding='utf-8',newline='')):
    try:coords.append((float(row['longitude']),float(row['latitude'])))
    except (KeyError,ValueError,TypeError):continue
ax.scatter([v[0] for v in coords],[v[1] for v in coords],s=1.1,color='#155c89',alpha=.65,linewidths=0)
ax.set(xlim=(-20,55),ylim=(-36,38),aspect='equal');ax.axis('off')
fig.legend(handles=[Line2D([],[],color='#88969e',lw=.7,label='Country boundary'),Line2D([],[],color='#667985',lw=.8,label='Road-constrained display path'),Line2D([],[],marker='o',ls='',ms=3,color='#155c89',label='Geolocated support node'),Patch(facecolor='#9dc9df',edgecolor='#35749b',label='Major lake or reservoir')],loc='lower center',bbox_to_anchor=(.5,.095),ncol=2,frameon=False,fontsize=10.5,columnspacing=1.1,handlelength=1.2)
fig.text(.5,.055,'Nodes and paths provide geographic context. They do not\nrepresent direct measurements of commodity movement.',ha='center',fontsize=10.5,linespacing=1.3)
for extension in ['png','pdf']:fig.savefig(OUT/f'Supplementary_Figure_S1_African_Atlas.{extension}',dpi=300,facecolor='white')
plt.close(fig)
