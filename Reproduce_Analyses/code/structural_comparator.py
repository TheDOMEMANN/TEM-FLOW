"""Independent record-stage implementation of established budgeted series/parallel DP.

Each report becomes a serial capacity stage. Spending one unit bypasses that
stage. Both directions of every expanded-tree edge are computed once, so this
comparator neither enumerates missing sets nor repeats a solve per destination.
Mathematical precedent: Wolf (2023), Section 3.6, Proposition 3.16.
The all-terminal message implementation here is newly written for comparison;
it is not presented as the original author's software or the fastest possible.
"""
import json,time,statistics,platform,sys,hashlib,random
from pathlib import Path
from production_tree import from_payload

def expanded_profiles(payload,budget):
    total=float(payload['mass']); n=len(payload['nodes'])
    groups=[[] for _ in payload['edges']]
    for rec in payload['records']:groups[rec['edge']].append(float(rec['error']))
    adjacency=[[] for _ in range(n)]; capacity=[]; upgrade=[]
    def edge(u,v,c,can_upgrade):
        e=len(capacity);capacity.append(c);upgrade.append(can_upgrade)
        adjacency[u].append((v,e));adjacency[v].append((u,e))
    for idx,(u,v) in enumerate(payload['edges']):
        if not groups[idx]:edge(u,v,total,False);continue
        prev=u
        for j,err in enumerate(groups[idx]):
            nxt=v if j==len(groups[idx])-1 else len(adjacency)
            if nxt==len(adjacency):adjacency.append([])
            edge(prev,nxt,min(total,2*err),True);prev=nxt
    N=len(adjacency); parent=[-1]*N;parent[0]=0;order=[0];parentedge=[-1]*N
    for u in order:
        for v,e in adjacency[u]:
            if v!=parent[u]:parent[v]=u;parentedge[v]=e;order.append(v)
    terminals=set(payload['terminals']); zero=[0.]*(budget+1);full=[total]*(budget+1)
    directed={}
    def parallel(a,b):
        out=[0.]*(budget+1)
        for k in range(budget+1):
            best=0.
            for j in range(k+1):
                val=a[j]+b[k-j]
                if val>best:best=val
            out[k]=min(total,best)
        return out
    def serial(e,a):
        c=capacity[e];out=[min(c,x) for x in a]
        if upgrade[e]:
            for k in range(1,budget+1):out[k]=max(out[k],a[k-1])
        return out
    for v in reversed(order[1:]):
        incoming=full if v in terminals else zero
        for w,e in adjacency[v]:
            if w!=parent[v]:incoming=parallel(incoming,directed[w,v])
        directed[v,parent[v]]=serial(parentedge[v],incoming)
    for v in order:
        neighbors=adjacency[v]
        if v in terminals:
            for w,e in neighbors:directed[v,w]=serial(e,full)
            continue
        pre=[zero]
        for w,e in neighbors:pre.append(parallel(pre[-1],directed[w,v]))
        suf=zero
        for j in range(len(neighbors)-1,-1,-1):
            w,e=neighbors[j]
            directed[v,w]=serial(e,parallel(pre[j],suf))
            suf=parallel(directed[w,v],suf)
    return {v:(directed[adjacency[v][0][0],v] if adjacency[v] else zero) for v in sorted(terminals)}

def production(p,r):return from_payload(p).profiles(r)['widths']
def gap(a,b):return max((abs(x-y) for v in a for x,y in zip(a[v],b[v])),default=0.)

def main():
    root=Path(__file__).resolve().parents[1]; dest=root/'results/structural_comparison'
    dest.mkdir(parents=True,exist_ok=True)
    cases=[json.loads(p.read_text()) for p in sorted((root/'inputs/structural_cases').glob('*.json'))]
    assert len(cases)==21,len(cases)
    rows=[]
    for case in cases:
        p,r=case['payload'],case['r']; out1=production(p,r);out2=expanded_profiles(p,r)
        assert gap(out1,out2)<1e-7,(case['id'],gap(out1,out2))
        samples={'temflow':[],'record_stage_dp':[]}; funcs={'temflow':production,'record_stage_dp':expanded_profiles}
        for rep in range(7):
            order=list(funcs)
            if rep%2:order.reverse()
            for name in order:
                t=time.perf_counter(); funcs[name](p,r);elapsed=time.perf_counter()-t
                batch=min(100,max(1,int(.015/max(elapsed,1e-8))))
                t=time.perf_counter()
                for _ in range(batch):actual=funcs[name](p,r)
                samples[name].append((time.perf_counter()-t)/batch)
                assert gap(actual,out1)<1e-7
        row={'id':case['id'],'destinations':len(p['terminals']),'records':len(p['records']),'budget':r,'maximum_gap':gap(out1,out2),'widths':out1,'seconds':samples}
        row['medians']={k:statistics.median(v) for k,v in samples.items()}
        row['ratio_record_stage_over_temflow']=row['medians']['record_stage_dp']/row['medians']['temflow']
        rows.append(row); print(case['id'],round(row['ratio_record_stage_over_temflow'],3),flush=True)
    rng=random.Random(20261004); checks=[]
    for k in range(100):
        p=json.loads(json.dumps(cases[k%len(cases)]['payload']))
        if len(p['nodes'])>100:continue
        p['records']=[x for x in p['records'] if rng.random()>.25]
        p['mass']=rng.choice([0.,1.,100.])
        for rec in p['records']:rec['error']=rng.choice([0.,.1234,1.,200.])
        r=k%4;g=gap(production(p,r),expanded_profiles(p,r));assert g<1e-7;checks.append(g)
    result={'cases':rows,'comparison_values':sum(len(row['widths'])*(row['budget']+1) for row in rows),'extra_edge_case_checks':len(checks),'max_gap':max([x['maximum_gap'] for x in rows]+checks),'environment':{'python':sys.version,'platform':platform.platform()},'protocol':'7 paired repetitions; fresh construction; established recurrence; code-level independent implementation, not an independent research-team audit.'}
    (dest/'RESULTS.json').write_text(json.dumps(result,indent=2))
    print('COMPLETE',result['comparison_values'],result['max_gap'])
if __name__=='__main__':main()
