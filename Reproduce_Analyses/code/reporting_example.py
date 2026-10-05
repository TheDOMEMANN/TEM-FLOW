"""Constructed acquisition design, not field measurements or empirical validation."""
from pathlib import Path
import json,itertools
import numpy as np
from scipy.optimize import linprog
from production_tree import from_payload
from structural_comparator import expanded_profiles

def main():
    root=Path(__file__).resolve().parents[1];out=root/'results/reporting_example';out.mkdir(parents=True,exist_ok=True)
    edges=[(0,1),(0,2),(1,3),(1,4),(2,5),(2,6)]
    base=[{'id':name,'edge':edge,'error':1.} for name,edge in [('group_G',0),('A',2),('B',3),('C',4),('U',5)]]
    records=[]
    for design,extra in [('repeat_group_G',0),('repeat_destination_A',2)]:
        p={'mass':100.,'nodes':['Source','G','H','A','B','C','U'],'edges':edges,'terminals':[3,4,5,6], 'records':base+[{'id':'independent_backup','edge':extra,'error':1.}]}
        ledger=from_payload(p);H=np.array(ledger.measurement_matrix());truth=np.array([20.,30.,10.,40.]);readings=H@truth
        profiles=ledger.profiles(1)['widths'];other=expanded_profiles(p,1)
        assert profiles==other
        conditional=[]
        for lost in [None]+list(range(len(p['records']))):
            keep=[i for i in range(len(p['records'])) if i!=lost];A=np.r_[H[keep],-H[keep]];b=np.r_[readings[keep]+1,-readings[keep]+1]
            lo=linprog([1,0,0,0],A_ub=A,b_ub=b,A_eq=[[1,1,1,1]],b_eq=[100],bounds=(0,None),method='highs')
            hi=linprog([-1,0,0,0],A_ub=A,b_ub=b,A_eq=[[1,1,1,1]],b_eq=[100],bounds=(0,None),method='highs')
            assert lo.success and hi.success
            conditional.append({'lost':p['records'][lost]['id'] if lost is not None else None,'lower':lo.fun,'upper':-hi.fun,'width':-hi.fun-lo.fun})
        records.append({'design':design,'payload':p,'constructed_true_allocation':truth.tolist(),'readings':readings.tolist(),'prospective_A':profiles[3],'conditional_A':conditional,'worst_conditional_width':max(v['width'] for v in conditional),'status':'Hypothetical separate acquisitions of overlapping aggregates; not duplicates of one report.'})
    assert records[0]['prospective_A']==[2.,4.]
    assert records[1]['prospective_A']==[2.,2.]
    (out/'RESULTS.json').write_text(json.dumps(records,indent=2));print(json.dumps(records,indent=2))
if __name__=='__main__':main()
