"""Check the explicit expansion reduction and the boundary of the hierarchy law.

All inputs are synthetic. This is a comparison of mathematical formulations,
not a claim of publication priority or a new implementation of TEM-FLOW v1.0.0.
"""
from pathlib import Path
from collections import deque
from itertools import combinations
import json
import sys
import numpy as np
from scipy.optimize import linprog
from temflow._structural_tree import from_payload, NestedLedger, Record
from validate import explicit_cut_width

ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'baseline'))
from measurement_design import FlowSet, MeasurementDesign


def maximum_flow(arcs, source, sink):
    """Edmonds-Karp on a residual graph; additive parallel capacities allowed."""
    residual={}
    for u,v,c in arcs:
        residual.setdefault(u,{})[v]=residual.setdefault(u,{}).get(v,0.)+c
        residual.setdefault(v,{}).setdefault(u,0.)
    total=0.
    while True:
        parent={source:None};queue=deque([source])
        while queue and sink not in parent:
            u=queue.popleft()
            for v,c in residual[u].items():
                if c>1e-10 and v not in parent:
                    parent[v]=u;queue.append(v)
        if sink not in parent:return total
        amount=float('inf');v=sink
        while parent[v] is not None:
            u=parent[v];amount=min(amount,residual[u][v]);v=u
        v=sink
        while parent[v] is not None:
            u=parent[v];residual[u][v]-=amount;residual[v][u]+=amount;v=u
        total+=amount


def expanded_network(ledger, target, erased):
    """One stage per record; an erased record activates a unit-cost bypass.

The source cap M makes stage capacities above M irrelevant. Non-destination
dead ends are harmless for the flow calculation; prune them for the formal
two-terminal series-parallel representation. Orient away from the target.
The undirected version has the same maximum value because this construction
is a series-parallel source-to-sink network after pruning.
"""
    M=ledger.mass
    source=ledger.n;sink=ledger.n+1;next_node=ledger.n+2
    arcs=[(source,target,M)]
    parent={target:target};order=[target]
    for u in order:
        for v,edge in ledger.adj[u]:
            if v==parent[u]:continue
            parent[v]=u;order.append(v)
            records=ledger.by_edge[edge]
            if not records:
                arcs.append((u,v,M));continue
            start=u
            for j,record in enumerate(records):
                end=v if j==len(records)-1 else next_node
                if end==next_node:next_node+=1
                arcs.append((start,end,min(M,2*record.error)))
                if record.id in erased:arcs.append((start,end,M))
                start=end
    for terminal in ledger.terminals:
        if terminal!=target:arcs.append((terminal,sink,M))
    return arcs,source,sink


def main():
    cases=json.loads((ROOT/'results/cases.json').read_text())
    boundaries=json.loads((ROOT/'results/edge_cases.json').read_text())
    cases+= [{'kind':'boundary','id':c['name'],'input':c['input']} for c in boundaries]
    comparisons=[];fixed_checks=0;profile_checks=0;max_gap=0.
    for case in cases:
        ledger=from_payload(case['input']);profiles=ledger.profiles(3)
        worst={t:[0.]*4 for t in ledger.terminals}
        ids=[r.id for r in ledger.records]
        for k in range(min(3,len(ids))+1):
            for selection in combinations(ids,k):
                erased=set(selection)
                for target in ledger.terminals:
                    value=maximum_flow(*expanded_network(ledger,target,erased))
                    cut=explicit_cut_width(ledger,target,erased)
                    gap=abs(value-cut);max_gap=max(max_gap,gap)
                    assert gap<1e-7
                    fixed_checks+=1
                    for r in range(k,4):worst[target][r]=max(worst[target][r],value)
        for target in ledger.terminals:
            expected=profiles['widths'][target]
            assert np.allclose(worst[target],expected,atol=1e-7,rtol=0)
            profile_checks+=4
            comparisons.append({'kind':case['kind'],'case_id':case['id'],
                                'target':ledger.nodes[target],'expansion_widths':worst[target],
                                'compact_widths':expected})

    # Crossing groups on four destinations cannot both be represented by tree
    # edge splits, even after replacing a group by its complement.
    M=100.;H=np.array([[1,1,0,0],[1,0,1,0]],float)
    f=FlowSet.create(['A','B','C','D'],[0]*4,[M]*4,[np.ones(4)],[M])
    model=MeasurementDesign(f,H,[0,0],[1,1],np.eye(4),[1]*4)
    crossing_widths=list(model.diameter([0,1])['physical_widths'])
    assert np.allclose(crossing_widths,[50]*4,atol=1e-8,rtol=0)
    x=np.array([50,0,0,50.]);xp=np.array([0,50,50,0.])
    assert np.allclose(H@x,H@xp) and sum(x)==sum(xp)==M

    # Conditioned on a particular exact group total, a nested model need not
    # have the prospective 0-or-M width: fixed readings can narrow it to 40.
    nested=NestedLedger(['R','G','A','B','U'],[(0,1),(1,2),(1,3),(0,4)],
                        [2,3,4],[Record('G-total',0,0)],100)
    aeq=np.array([[1,1,1],[1,1,0]],float);beq=np.array([100,40.])
    lo=linprog([1,0,0],A_eq=aeq,b_eq=beq,bounds=[(0,None)]*3,method='highs')
    hi=linprog([-1,0,0],A_eq=aeq,b_eq=beq,bounds=[(0,None)]*3,method='highs')
    assert lo.success and hi.success
    fixed_interval=[float(lo.fun),float(-hi.fun)]
    prospective=nested.profiles(0)['widths'][2][0]
    assert np.allclose(fixed_interval,[0,40]) and prospective==100.

    result={'date':'2026-10-01','all_passed':True,'case_count':len(cases),
            'fixed_expansion_vs_cut_checks':fixed_checks,
            'target_budget_profile_checks':profile_checks,'maximum_fixed_gap':max_gap,
            'comparison':'Explicit record-stage expansion plus augmenting-path maximum flow versus independently enumerated cuts and compact tree profiles.',
            'crossing_example':{'mass':M,'H':H.tolist(),'errors':[0,0],
                                'prospective_widths':crossing_widths,'x':x.tolist(),'x_prime':xp.tolist(),
                                'common_readings':list(H@x),'analytic_upper_bound':'d=(t,-t,-t,t); positive mass is 2|t| <= M.'},
            'conditional_example':{'input':nested.payload(),'received_group_total':40,
                                   'conditional_A_interval':fixed_interval,'prospective_A_width':prospective},
            'novelty_inference':'These checks verify mathematical relationships and assumptions; they do not establish literature priority.'}
    (ROOT/'results/structural_comparison_checks.json').write_text(json.dumps(comparisons,indent=2),encoding='utf-8')
    (ROOT/'results/structural_comparison_summary.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result,indent=2))


if __name__=='__main__':main()
