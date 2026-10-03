"""Matched prospective-width benchmark; does not modify the TEM-FLOW engine."""
from pathlib import Path
import os
for _key in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS'):
    os.environ[_key]='1'
import argparse, csv, ctypes, hashlib, json, math, platform, random, statistics, subprocess, sys, time
from itertools import combinations

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE/'vendor'))
import numpy as np
import scipy
from scipy.sparse import csr_matrix, hstack, vstack
from scipy.sparse.csgraph import maximum_flow
from scipy.optimize import linprog
from temflow._structural_tree import from_payload

METHODS=['temflow','expanded_dinic','paired_highs_lp']
REPEATS=3
RUN_LIMIT=10.0

def make_case(shape,L,r):
    rng=random.Random(2026100200+L)
    if shape=='balanced':
        edges=[((v-1)//2,v) for v in range(1,2*L-1)]
        leaves=list(range(L-1,2*L-1)); n=2*L-1
    elif shape=='star':
        edges=[(0,v) for v in range(1,L+1)]; leaves=list(range(1,L+1)); n=L+1
    else:
        edges=[]; leaves=[0]; n=1
        while len(leaves)<L:
            v=leaves.pop(-1 if shape=='comb' else rng.randrange(len(leaves)))
            edges.extend([(v,n),(v,n+1)]);leaves.extend([n,n+1]);n+=2
    records=[{'id':f'r{e}_{j}','edge':e,'error':rng.choice([0.25,0.5,1.,1.5,2.,2.5])}
             for e in range(len(edges)) for j in range(2)]
    payload={'nodes':[f'n{v}' for v in range(n)],'edges':edges,'terminals':leaves,'records':records,'mass':100.}
    return {'id':f'{shape}_L{L}_r{r}','shape':shape,'leaves':L,'records':len(records),'r':r,'payload':payload}

def compile_networks(ledger,deadline):
    """Compile one undirected record-stage graph shared by all destinations.

    Removing a record replaces its stage capacity with M. This is equivalent
    to a parallel bypass of capacity M, since the source is itself capped at M.
    All benchmark capacities are exact multiples of 1/2, so scaling by 2 is
    exact and satisfies SciPy's integer-capacity interface without rounding.
    """
    scale=2
    rec_index={rec.id:i for i,rec in enumerate(ledger.records)}
    source=ledger.n;sink=source+1;next_node=sink+1;arcs=[]
    for e,(u,v) in enumerate(ledger.edges):
        records=ledger.by_edge[e];start=u
        if not records:arcs.extend([(u,v,ledger.mass,-1),(v,u,ledger.mass,-1)])
        for j,rec in enumerate(records):
            end=v if j==len(records)-1 else next_node
            if end==next_node:next_node+=1
            cap=min(ledger.mass,2*rec.error);idx=rec_index[rec.id]
            arcs.extend([(start,end,cap,idx),(end,start,cap,idx)]);start=end
    for target in ledger.terminals:
        arcs.extend([(source,target,0.,-1),(target,sink,ledger.mass,-1)])
    rows,cols,caps,_=zip(*arcs);scaled=np.asarray(caps)*scale
    assert np.array_equal(scaled,np.rint(scaled))
    graph=csr_matrix((scaled.astype(np.int64),(rows,cols)),shape=(next_node,next_node))
    def slot(u,v):
        start,end=graph.indptr[u:u+2]
        return start+int(np.flatnonzero(graph.indices[start:end]==v)[0])
    records=[[] for _ in ledger.records]
    for u,v,cap,idx in arcs:
        if idx>=0:records[idx].append(slot(u,v))
    slots=np.asarray(records,dtype=int)
    target_slots=[(slot(source,t),slot(t,sink)) for t in ledger.terminals]
    return graph,graph.data.copy(),slots,target_slots,source,sink

def solve(case,method,deadline):
    ledger=from_payload(case['payload']); r=case['r']; L=len(ledger.terminals); m=len(ledger.records)
    if method=='temflow':
        calc=ledger.profiles(r)
        return np.array([calc['widths'][v] for v in ledger.terminals]),{'solver_calls':0,'operations':calc['operations']}
    profiles=np.zeros((L,r+1)); calls=0
    if method=='expanded_dinic':
        networks=compile_networks(ledger,deadline)
    else:
        H=csr_matrix(np.asarray(ledger.measurement_matrix(),float).reshape(m,L))
        D=hstack([H,-H],format='csr'); errors=2*np.array([a.error for a in ledger.records])
        eq=csr_matrix(np.array([[1.]*L+[0.]*L,[0.]*L+[1.]*L]))
        bounds=[(0,ledger.mass)]*(2*L)
        objectives=[]
        for j in range(L):
            c=np.zeros(2*L);c[j]=-1;c[L+j]=1;objectives.append(c)
    for k in range(r+1):
        for erased in combinations(range(m),min(k,m)):
            if time.perf_counter()>deadline:raise TimeoutError('per-evaluation limit reached')
            if method=='expanded_dinic':
                graph,base,slots,target_slots,source,sink=networks
                graph.data[:]=base
                if erased:graph.data[slots[list(erased)].ravel()]=round(ledger.mass*2)
                for j,(source_slot,sink_slot) in enumerate(target_slots):
                    if time.perf_counter()>deadline:raise TimeoutError('per-evaluation limit reached')
                    graph.data[source_slot]=round(ledger.mass*2);graph.data[sink_slot]=0
                    value=maximum_flow(graph,source,sink,method='dinic').flow_value/2
                    profiles[j,k]=max(profiles[j,k],value);calls+=1
                    graph.data[source_slot]=0;graph.data[sink_slot]=round(ledger.mass*2)
            else:
                removed=set(erased);keep=[i for i in range(m) if i not in removed]
                d=D[keep];ub=vstack([d,-d],format='csr');b=np.concatenate([errors[keep],errors[keep]])
                for j,c in enumerate(objectives):
                    if time.perf_counter()>deadline:raise TimeoutError('per-evaluation limit reached')
                    ans=linprog(c,A_ub=ub,b_ub=b,A_eq=eq,b_eq=[ledger.mass]*2,bounds=bounds,
                        method='highs',options={'primal_feasibility_tolerance':1e-9,'dual_feasibility_tolerance':1e-9})
                    if not ans.success:raise RuntimeError(ans.message)
                    profiles[j,k]=max(profiles[j,k],-ans.fun);calls+=1
    return profiles,{'solver_calls':calls,'erasure_subsets':sum(math.comb(m,min(k,m)) for k in range(r+1))}

def memory():
    if os.name!='nt':return {}
    from ctypes import wintypes
    class PMC(ctypes.Structure):
        _fields_=[('cb',wintypes.DWORD),('PageFaultCount',wintypes.DWORD)]+[(n,ctypes.c_size_t) for n in
         ['PeakWorkingSetSize','WorkingSetSize','QuotaPeakPagedPoolUsage','QuotaPagedPoolUsage','QuotaPeakNonPagedPoolUsage','QuotaNonPagedPoolUsage','PagefileUsage','PeakPagefileUsage']]
    p=PMC();p.cb=ctypes.sizeof(p)
    ctypes.windll.kernel32.GetCurrentProcess.restype=wintypes.HANDLE
    ctypes.windll.psapi.GetProcessMemoryInfo.argtypes=[wintypes.HANDLE,ctypes.POINTER(PMC),wintypes.DWORD]
    ctypes.windll.psapi.GetProcessMemoryInfo.restype=wintypes.BOOL
    ok=ctypes.windll.psapi.GetProcessMemoryInfo(ctypes.windll.kernel32.GetCurrentProcess(),ctypes.byref(p),p.cb)
    return {'peak_working_set_mib':p.PeakWorkingSetSize/1048576,'working_set_mib':p.WorkingSetSize/1048576} if ok else {}

def worker(case,method):
    # Identical warm-up imports for all methods; never cache a requested case.
    tiny=make_case('balanced',2,0)
    for warm_method in METHODS:solve(tiny,warm_method,time.perf_counter()+RUN_LIMIT)
    baseline=memory(); result={'case':case['id'],'method':method,'status':'running','repeats':REPEATS,'baseline_memory':baseline}
    samples=[];outputs=None;meta={}
    try:
        t=time.perf_counter(); outputs,meta=solve(case,method,t+RUN_LIMIT); pilot=time.perf_counter()-t
        if pilot>RUN_LIMIT:raise TimeoutError('pilot exceeded per-evaluation limit')
        batch=max(1,min(256,math.ceil(0.025/max(pilot,1e-9))))
        for rep in range(REPEATS):
            t=time.perf_counter()
            for _ in range(batch):
                current,meta=solve(case,method,time.perf_counter()+RUN_LIMIT)
            samples.append((time.perf_counter()-t)/batch)
            if not np.allclose(current,outputs,rtol=0,atol=1e-7):raise AssertionError('non-reproducible result')
        result.update(status='pass',seconds=samples,median_seconds=statistics.median(samples),
                      min_seconds=min(samples),max_seconds=max(samples),batch=batch,
                      pilot_seconds=pilot,profiles=outputs.tolist(),details=meta)
    except TimeoutError as exc:result.update(status='timeout',reason=str(exc),evaluation_limit_seconds=RUN_LIMIT,completed_samples=samples)
    except Exception as exc:result.update(status='error',reason=repr(exc))
    result['memory']=memory()
    print(json.dumps(result),flush=True)

def main():
    p=argparse.ArgumentParser();p.add_argument('--worker');p.add_argument('--method',choices=METHODS);p.add_argument('--output',type=Path)
    a=p.parse_args()
    if a.worker:
        worker(json.loads(Path(a.worker).read_text()),a.method);return
    out=a.output
    if (out/'RAW_RUNS.jsonl').exists():raise SystemExit('Choose a fresh output directory to preserve previous benchmark results.')
    out.mkdir(parents=True,exist_ok=True);(out/'inputs').mkdir(exist_ok=True)
    cases=[make_case('balanced',L,0) for L in [4,8,16,32,128,1024]]
    cases += [make_case('balanced',L,r) for r in [1,2] for L in [4,8,16]]
    cases += [make_case(shape,8,2) for shape in ['star','comb','random']]
    scaling=[make_case('balanced',L,r) for L in [128,1024,8192] for r in [1,3]]
    protocol={'created_at':time.strftime('%Y-%m-%dT%H:%M:%S%z'),'question':'Runtime to compute all destination prospective width profiles for all budgets 0..r under identical nested mass-accounting assumptions.',
      'repeats':REPEATS,'evaluation_limit_seconds':RUN_LIMIT,'case_ids':[c['id'] for c in cases],
      'temflow_only_scaling_ids':[c['id'] for c in scaling],
      'methods':METHODS,'timing':'Fresh in-memory construction and complete calculation; excludes JSON I/O, process startup, imports, and common warm-up. Includes graph or LP preparation. Three repeated batches; batch chosen by an untimed pilot, capped at 256; median with range.',
      'accuracy':'All completed full profiles compared to TEM-FLOW at absolute tolerance 1e-7 and zero relative tolerance.',
      'fairness':'Compiled Dinic; one undirected record-stage CSR graph shared across every target and erasure subset, with capacities updated in-place. HiGHS paired-flow LP omits prototype witness/caching overhead. Baselines enumerate record losses; no claim to beat the best specialized loss-budget algorithm.',
      'limits':'One Windows PC, deterministic synthetic quarter-unit errors, three repeats, no CPU affinity or controlled power plan. Peak working set includes imports and allocator history. Limits apply to each evaluation; timed-out pilot prevents further repeats. Missing-record profiles, not conditional inverse problems or whole GUI latency.',
      'sources':['https://docs.scipy.org/doc/scipy/reference/generated/scipy.sparse.csgraph.maximum_flow.html','https://docs.scipy.org/doc/scipy/reference/optimize.linprog-highs.html']}
    (out/'PROTOCOL.json').write_text(json.dumps(protocol,indent=2))
    environment={'python':sys.version,'executable':sys.executable,'platform':platform.platform(),'numpy':np.__version__,'scipy':scipy.__version__,'logical_cpus':os.cpu_count(),'thread_environment':{k:os.environ[k] for k in ['OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS']}}
    (out/'ENVIRONMENT.json').write_text(json.dumps(environment,indent=2))
    tasks=[]
    for case in cases+scaling:
        path=out/'inputs'/f"{case['id']}.json";path.write_text(json.dumps(case,indent=2))
        order=METHODS.copy() if case in cases else ['temflow'];random.Random(case['id']).shuffle(order)
        tasks.extend((case,path,m) for m in order)
    rows=[]
    for i,(case,path,method) in enumerate(tasks):
        try:
            done=subprocess.run([sys.executable,'-B',str(Path(__file__).resolve()),'--worker',str(path),'--method',method],capture_output=True,text=True,timeout=65)
            if done.returncode:raise RuntimeError(done.stderr[-2000:])
            row=json.loads(done.stdout)
        except subprocess.TimeoutExpired:row={'case':case['id'],'method':method,'status':'timeout','reason':'worker hard limit 65 seconds'}
        except Exception as exc:row={'case':case['id'],'method':method,'status':'error','reason':repr(exc)}
        row.update(shape=case['shape'],leaves=case['leaves'],records=case['records'],r=case['r'])
        rows.append(row)
        with (out/'RAW_RUNS.jsonl').open('a',encoding='utf-8') as f:f.write(json.dumps(row)+'\n')
        print(f"{i+1}/{len(tasks)} {case['id']} {method}: {row['status']} {row.get('median_seconds','')} s",flush=True)
    for row in rows:
        if row['status']!='pass':continue
        ref=next(x for x in rows if x['case']==row['case'] and x['method']=='temflow')
        row['maximum_absolute_gap']=float(np.max(np.abs(np.array(row['profiles'])-np.array(ref['profiles']))))
        row['same_results']=row['maximum_absolute_gap']<=1e-7
        row['speed_ratio_vs_temflow']=row['median_seconds']/ref['median_seconds']
        if not row['same_results']:row['status']='mismatch'
    (out/'RESULTS.json').write_text(json.dumps(rows,indent=2))
    fields=['case','shape','leaves','records','r','method','status','median_seconds','min_seconds','max_seconds','speed_ratio_vs_temflow','maximum_absolute_gap']
    with (out/'RESULTS.csv').open('w',newline='',encoding='utf-8') as f:
        w=csv.DictWriter(f,fieldnames=fields,extrasaction='ignore');w.writeheader();w.writerows(rows)
    print('BENCHMARK COMPLETE',flush=True)

if __name__=='__main__':main()
