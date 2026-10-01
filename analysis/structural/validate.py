"""Reproducible structural-theorem checks; all data are synthetic."""
from pathlib import Path
import sys,json,time,random,math,platform
from itertools import combinations
import numpy as np
import scipy
from temflow._structural_tree import NestedLedger,Record,example
ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'baseline'))
from measurement_design import FlowSet,MeasurementDesign

def random_tree(rng,L,M,max_records=8,integer=False):
    edges=[];leaves=[0];n=1
    while len(leaves)<L:
        v=rng.choice(leaves);leaves.remove(v)
        edges.extend([(v,n),(v,n+1)]);leaves.extend([n,n+1]);n+=2
    possible=[e for e in range(len(edges)) for _ in range(rng.randrange(3))]
    rng.shuffle(possible);possible=possible[:max_records]
    records=[Record(f'rec-{i}',e,rng.randrange(5)/2 if integer else rng.choice([0.,rng.uniform(.1,4)]))
             for i,e in enumerate(possible)]
    return NestedLedger([f'node-{i}' for i in range(n)],edges,leaves,records,M)

def general(ledger):
    L=len(ledger.terminals)
    f=FlowSet.create([ledger.nodes[v] for v in ledger.terminals],[0]*L,[ledger.mass]*L,[np.ones(L)],[ledger.mass])
    H=np.asarray(ledger.measurement_matrix(),float).reshape((-1,L))
    return MeasurementDesign(f,H,[r.error for r in ledger.records],[1]*len(ledger.records),np.eye(L),[1]*L)

def check_witness(ledger,target,r,calc):
    w=ledger.witness(target,r,calc);x=np.array(w['x']);xp=np.array(w['x_prime'])
    assert min(x)>=-1e-8 and min(xp)>=-1e-8
    assert abs(sum(x)-ledger.mass)<1e-8 and abs(sum(xp)-ledger.mass)<1e-8
    assert abs(x[ledger.terminals.index(target)]-xp[ledger.terminals.index(target)]-w['width'])<1e-8
    H=np.asarray(ledger.measurement_matrix()).reshape((-1,len(x)))
    for i,rec in enumerate(ledger.records):
        if rec.id not in w['erased']:
            assert abs(H[i]@x-w['common_readings'][i])<=rec.error+1e-7
            assert abs(H[i]@xp-w['common_readings'][i])<=rec.error+1e-7
    return w

def compositions(M,L):
    if L==1:
        yield (M,);return
    for v in range(M+1):
        for tail in compositions(M-v,L-1):yield (v,)+tail

def explicit_cut_width(ledger,target,erased):
    n=ledger.n;other=set(ledger.terminals)-{target}
    internal=[v for v in range(n) if v!=target and v not in other]
    caps=[min([ledger.mass]+[2*rec.error for rec in a if rec.id not in erased]) for a in ledger.by_edge]
    result=ledger.mass
    for mask in range(1<<len(internal)):
        side={target}|{v for i,v in enumerate(internal) if mask>>i&1}
        result=min(result,sum(c for (u,v),c in zip(ledger.edges,caps) if (u in side)!=(v in side)))
    return result

def main():
    rng=random.Random(2026093003);cases=[];lp_checks=[];int_checks=[];cut_checks=[]
    witness_count=0;max_gap=0.;max_residual=0.
    for i in range(30):
        ledger=random_tree(rng,2+i%4,100,max_records=8)
        calc=ledger.profiles(3);d=general(ledger);m=len(ledger.records)
        cases.append({'kind':'continuous','id':i,'input':ledger.payload()})
        for r in range(4):
            worst=np.zeros(len(ledger.terminals))
            for E in combinations(range(m),min(r,m)):
                result=d.diameter([j for j in range(m) if j not in E])
                worst=np.maximum(worst,result['physical_widths'])
                max_residual=max(max_residual,result['maximum_primal_violation'])
            for j,target in enumerate(ledger.terminals):
                val=calc['widths'][target][r];gap=abs(val-worst[j]);max_gap=max(max_gap,gap)
                assert gap<1e-7,(i,r,target,val,worst[j])
                w=check_witness(ledger,target,r,calc);witness_count+=1
                lp_checks.append({'case':i,'target':target,'erasures':r,'tree_width':val,'lp_width':float(worst[j]),'witness':w})
        # Fixed failures: compare independent enumeration of tree cuts.
        E={rec.id for rec in ledger.records[::3]}
        reduced=NestedLedger(ledger.nodes,ledger.edges,ledger.terminals,[rec for rec in ledger.records if rec.id not in E],100)
        fixed=reduced.profiles(0)
        for t in ledger.terminals:
            cut=explicit_cut_width(ledger,t,E)
            assert abs(cut-fixed['widths'][t][0])<1e-7
            cut_checks.append({'case':i,'target':t,'removed':sorted(E),'min_cut':cut,'tree_width':fixed['widths'][t][0]})
    print('Continuous LP, cut and witness checks passed.',flush=True)
    for i in range(24):
        ledger=random_tree(rng,2+i%3,5,max_records=8,integer=True)
        calc=ledger.profiles(3);H=ledger.measurement_matrix();truth=list(compositions(5,len(ledger.terminals)))
        widths={t:[0]*4 for t in ledger.terminals}
        for x in truth:
            for xp in truth:
                delta=[a-b for a,b in zip(x,xp)]
                need=sum(abs(sum(h*z for h,z in zip(row,delta)))>2*rec.error
                         for row,rec in zip(H,ledger.records))
                if need>3:continue
                for j,t in enumerate(ledger.terminals):
                    for r in range(need,4):widths[t][r]=max(widths[t][r],abs(delta[j]))
        for t in ledger.terminals:
            assert widths[t]==calc['widths'][t]
            int_checks.append({'case':i,'target':t,'enumerated':widths[t],'tree':calc['widths'][t]})
        cases.append({'kind':'integer','id':i,'input':ledger.payload(),'integer_states':len(truth)})
    print('Exhaustive integer-state checks passed.',flush=True)
    # Exact-reading phase transition: shortest path record count.
    exact_checks=[]
    for i in range(12):
        base=random_tree(rng,2+i%4,17,max_records=10)
        ledger=NestedLedger(base.nodes,base.edges,base.terminals,[Record(a.id,a.edge,0) for a in base.records],17)
        calc=ledger.profiles(4)
        for t in ledger.terminals:
            dist={t:0};order=[t]
            for v in order:
                for w,e in ledger.adj[v]:
                    if w not in dist:dist[w]=dist[v]+len(ledger.by_edge[e]);order.append(w)
            q=min(dist[u] for u in ledger.terminals if u!=t)
            expected=[0. if r<q else 17. for r in range(5)]
            assert expected==calc['widths'][t]
            exact_checks.append({'case':i,'target':t,'nearest_record_distance':q,'profile':expected})
        cases.append({'kind':'exact','id':i,'input':ledger.payload()})
    # Edge cases and invalid topology/model input.
    edge_checks=[]
    for name,ledger in [
        ('one_destination',NestedLedger(['only'],[],[0],[],100)),
        ('zero_mass',NestedLedger(['A','B'],[(0,1)],[0,1],[Record('r',0,.5)],0)),
        ('no_records',NestedLedger(['root','A','U'],[(0,1),(0,2)],[1,2],[],100)),
        ('unary_chain',NestedLedger(['A','n1','n2','B'],[(0,1),(1,2),(2,3)],[0,3],[Record('r1',0,1),Record('r2',2,2)],100)),
        ('shared_erasure_budget',NestedLedger(['A','middle','B'],[(0,1),(1,2)],[0,2],[Record('r1',0,1),Record('r2',1,1)],100)),
        ('high_degree_star',NestedLedger(['root']+[f'leaf{i}' for i in range(8)],[(0,i) for i in range(1,9)],list(range(1,9)),[Record(f'r{i}',i-1,(i%3)/2) for i in range(1,9)],100))]:
        calc=ledger.profiles(5)
        for t in ledger.terminals:
            for r in range(6):check_witness(ledger,t,r,calc);witness_count+=1
        if name=='shared_erasure_budget':assert calc['widths'][0][:3]==[2.,2.,100.]
        if name=='high_degree_star':
            cap=[2*rec.error for rec in ledger.records]
            for i,t in enumerate(ledger.terminals):
                assert calc['widths'][t][0]==min(cap[i],sum(cap)-cap[i])
        edge_checks.append({'name':name,'input':ledger.payload(),'widths':calc['widths']})
    invalid=0
    for p in [dict(nodes=['a','b','c'],edges=[(0,1),(1,0)],terminals=[2],records=[],mass=1),
              dict(nodes=['a','b','c'],edges=[(0,1),(1,2)],terminals=[1],records=[],mass=1),
              dict(nodes=['a','b'],edges=[(0,1)],terminals=[0,1],records=[Record('a',0,-1)],mass=1)]:
        try:NestedLedger(**p)
        except ValueError:invalid+=1
        else:raise AssertionError('Invalid model accepted')
    ex=example();excalc=ex.profiles(3)
    assert excalc['widths'][2][:3]==[4.,6.,100.]
    worked={'input':ex.payload(),'widths':excalc['widths'],
            'witnesses':{str(r):check_witness(ex,2,r,excalc) for r in range(3)}}
    # Wall times are single local runs, not a comprehensive performance study.
    scaling=[]
    for L in [16,128,1024,8192]:
        n=2*L-1;edges=[((v-1)//2,v) for v in range(1,n)]
        terminals=list(range(L-1,n))
        records=[Record(f'r-{e}-{copy}',e,1+(e%7)/4+copy/4) for e in range(len(edges)) for copy in range(2)]
        ledger=NestedLedger([f'n{i}' for i in range(n)],edges,terminals,records,100)
        for r in [0,1,3]:
            start=time.perf_counter();ans=ledger.profiles(r);elapsed=time.perf_counter()-start
            scaling.append({'leaves':L,'vertices':n,'records':len(records),'r':r,
                            'seconds':elapsed,'scalar_candidates':ans['operations'],
                            'min_width':min(a[r] for a in ans['widths'].values()),
                            'max_width':max(a[r] for a in ans['widths'].values())})
    # Direct comparison to prior prototype on a small, same-assumptions instance.
    L=8;n=2*L-1;edges=[((v-1)//2,v) for v in range(1,n)]
    small=NestedLedger([f'n{i}' for i in range(n)],edges,list(range(L-1,n)),[Record(f'r-{e}-{copy}',e,1+(e%5)/4+copy/4) for e in range(len(edges)) for copy in range(2)],100)
    t0=time.perf_counter();quick=small.profiles(2);quicktime=time.perf_counter()-t0
    d=general(small);t0=time.perf_counter();brute=np.zeros(L)
    for E in combinations(range(len(small.records)),2):
        cert=d.diameter([i for i in range(len(small.records)) if i not in E]);brute=np.maximum(brute,cert['physical_widths'])
    slowtime=time.perf_counter()-t0
    assert np.allclose(brute,[quick['widths'][v][2] for v in small.terminals],atol=1e-7,rtol=0)
    performance={'input':small.payload(),'r':2,'tree_seconds':quicktime,'prototype_seconds':slowtime,
                 'prototype_lp_calls':d.lp_calls,'same_widths':True,
                 'qualification':'Single local timing, includes Python/solver overhead; no superiority claim over the best published specialized algorithms.'}
    out=ROOT/'results';out.mkdir(exist_ok=True)
    data={'cases.json':cases,'lp_checks.json':lp_checks,'cut_checks.json':cut_checks,
          'integer_checks.json':int_checks,'exact_transition_checks.json':exact_checks,
          'edge_cases.json':edge_checks,'worked_example.json':worked,'scaling.json':scaling,'performance.json':performance}
    for file,obj in data.items():(out/file).write_text(json.dumps(obj,indent=2),encoding='utf-8')
    summary={'seed':2026093003,'continuous_cases':30,'continuous_target_budget_checks':len(lp_checks),
             'fixed_cut_checks':len(cut_checks),'integer_cases':24,'integer_target_budget_checks':4*len(int_checks),
             'exact_cases':12,'exact_target_budget_checks':5*len(exact_checks),
             'witnesses_checked':witness_count+3,'edge_cases':len(edge_checks),'invalid_inputs_rejected':invalid,
             'maximum_lp_gap':max_gap,'maximum_lp_primal_violation':max_residual,'all_passed':True,
             'python':platform.python_version(),'numpy':np.__version__,'scipy':scipy.__version__,
             'largest_scaling_run':scaling[-1],'prototype_comparison':performance,
             'novelty_status':'Proven structural specialization; publication originality not established by these tests.'}
    (out/'summary.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
    print(json.dumps(summary,indent=2))

if __name__=='__main__':main()
