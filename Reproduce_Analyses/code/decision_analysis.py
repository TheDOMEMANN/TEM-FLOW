"""Retrospective information-matched comparison; thresholds fixed before this run.
No claim of a newly blinded test or externally validated policy thresholds.
"""
from pathlib import Path
from collections import defaultdict
from datetime import datetime
import csv,json,hashlib,math,statistics,sys
import numpy as np
from scipy.optimize import linprog
from production_compositional import compositional_allocation

def quantile(a):return sorted(a)[min(len(a),math.ceil((len(a)+1)*.9))-1]
def main():
    root=Path(__file__).resolve().parents[1];out=root/'results/decision';out.mkdir(parents=True,exist_ok=True)
    raw=root/'inputs/cattle-movements-to-slaughterhouses-during-2010.csv'
    assert hashlib.sha256(raw.read_bytes()).hexdigest()=='23584327dde9a6f6e59efe1281204cdaf5b9f6a3c69aed9233e43c0c7c163875'
    ag=defaultdict(lambda:defaultdict(float)); training=defaultdict(lambda:defaultdict(float))
    for row in csv.DictReader(raw.open(encoding='utf-8-sig',newline='')):
        s=row['From County'].strip().upper();d=row['To County'].strip().upper()
        if not s or not d:continue
        try:
            date=datetime.strptime(row['Month & Year of Movement'].strip(),'%b-%y')
            counts=[float(row[f'{c} Movements'].replace(',','').strip()) for c in ['Direct','Indirect']]
            if date.year!=2010 or any(not math.isfinite(v) or v<0 for v in counts):continue
        except (ValueError,KeyError):continue
        for c,v in zip(['direct','indirect'],counts):
            ag[s,date.month,c][d]+=v
            if date.month<=5:training[s,c][d]+=v
    sources=sorted({x[0] for x in ag}); anchors={}
    for s in sources:
        if any(sum(sum(ag[s,m,c].values()) for m in months for c in ['direct','indirect'])<=0 for months in [range(1,6),range(6,9),range(9,13)]):continue
        vals={d:sum(training[s,c].get(d,0) for c in ['direct','indirect']) for d in set(training[s,'direct'])|set(training[s,'indirect']) if d!=s}
        vals={d:v for d,v in vals.items() if v>0}
        if vals:anchors[s]=sorted(vals,key=lambda d:(-vals[d],d))[0]
    fitted={};scores={c:{'tv':[],'box':[]} for c in ['direct','indirect']}
    for s,a in anchors.items():
        for c in ['direct','indirect']:
            vals={d:v for d,v in training[s,c].items() if d!=a and v>0}
            names=sorted(vals)+['UNRESOLVED_DESTINATION'];t=sum(vals.values())
            p=np.array([vals.get(d,0)/t if t else 1. for d in names]);fitted[s,c]=(names,p)
    def case(s,m,c):
        a=anchors[s];names,p=fitted[s,c];counts=ag[s,m,c];N=sum(counts.values());R=N-counts.get(a,0)
        y=np.array([counts.get(d,0.) for d in names]);y[-1]=sum(v for d,v in counts.items() if d!=a and d not in names)
        assert abs(sum(y)-R)<1e-8
        return names,p,y,N,R
    for s in anchors:
        for c in ['direct','indirect']:
            for m in range(6,9):
                names,p,y,N,R=case(s,m,c)
                if R>0:
                    delta=abs(y/R-p);scores[c]['tv'].append(float(sum(delta)/2));scores[c]['box'].append(float(max(delta)))
    radii={c:{method:quantile(vals) for method,vals in methods.items()} for c,methods in scores.items()}
    records=[];joint=defaultdict(list);fullset=defaultdict(list);lp_gaps=[];singleton_nonzero=[]
    for s in anchors:
        for m in range(9,13):
            for c in ['direct','indirect']:
                names,p,y,N,R=case(s,m,c)
                tv=radii[c]['tv'];box=radii[c]['box'];K=len(names)
                if K==1 and R>0:singleton_nonzero.append([s,m,c,R])
                lo=np.maximum(0,p-tv)*R;hi=np.minimum(1,p+tv)*R
                if K==1:lo[:]=R;hi[:]=R
                actual_engine=compositional_allocation(remainder_mass=R,destinations=names,historical_shares=p.tolist(),epsilon=tv)
                assert np.allclose(lo,[v.lower_mass for v in actual_engine.coordinates],rtol=0,atol=1e-8)
                assert np.allclose(hi,[v.upper_mass for v in actual_engine.coordinates],rtol=0,atol=1e-8)
                blo=np.maximum(0,p-box);bhi=np.minimum(1,p+box)
                lower=np.maximum(blo,1-(sum(bhi)-bhi))*R;upper=np.minimum(bhi,1-(sum(blo)-blo))*R
                intervals={'information_only':(np.full(K,R) if K==1 else np.zeros(K),np.full(K,R)), 'temflow_tv':(lo,hi),'calibrated_box':(lower,upper)}
                if R>0:
                    fullset['temflow_tv'].append(bool(sum(abs(y/R-p))/2<=tv+1e-8))
                    fullset['calibrated_box'].append(bool(max(abs(y/R-p))<=box+1e-8))
                for method,(l,u) in intervals.items():
                    joint[method].append(bool(np.all(y>=l-1e-8) and np.all(y<=u+1e-8)))
                    for j,d in enumerate(names):
                        records.append({'source':s,'month':m,'class':c,'destination':d,'method':method,'group_total':N,'remainder':R,'truth':float(y[j]),'lower':float(l[j]),'upper':float(u[j])})
                # LP formulation of exactly the SAME total-variation assumptions.
                # Fixed deterministic subset, independent of observed test outcomes.
                if (m==9 and len(lp_gaps)<1000 or K==1) and R>0:
                    A=np.zeros((2*K+1,2*K));b=np.r_[p,-p,2*tv]
                    A[:K,:K]=np.eye(K);A[:K,K:]=-np.eye(K)
                    A[K:2*K,:K]=-np.eye(K);A[K:2*K,K:]=-np.eye(K);A[-1,K:]=1
                    eq=np.r_[np.ones(K),np.zeros(K)][None,:]
                    for j in range(K):
                        vals=[]
                        for sign in [1,-1]:
                            obj=np.zeros(2*K);obj[j]=sign
                            ans=linprog(obj,A_ub=A,b_ub=b,A_eq=eq,b_eq=[1],bounds=(0,None),method='highs')
                            assert ans.success;vals.append(ans.fun*sign*R)
                        lp_gaps.extend([abs(vals[0]-lo[j]),abs(vals[1]-hi[j])])
    # Reproduce the original headline exactly before interpreting extension.
    tv_positive=[x for x in records if x['method']=='temflow_tv' and x['truth']>0]
    count=sum(x['lower']-1e-8<=x['truth']<=x['upper']+1e-8 for x in tv_positive)
    assert len(tv_positive)==6430,(len(tv_positive),count)
    assert round(count/len(tv_positive)*100,2)==99.53
    summaries={};threshold_rows=[]
    for method in ['information_only','temflow_tv','calibrated_box']:
        subset=[x for x in records if x['method']==method];positive=[x for x in subset if x['truth']>0]
        covered=lambda x:x['lower']-1e-8<=x['truth']<=x['upper']+1e-8
        summaries[method]={'compartments':len(subset),'positive_compartments':len(positive),'positive_coverage':sum(map(covered,positive))/len(positive),'all_coverage':sum(map(covered,subset))/len(subset),'joint_coordinate_coverage':sum(joint[method])/len(joint[method]),'full_set_cases':len(fullset[method]),'full_set_coverage':statistics.mean(fullset[method]) if fullset[method] else 1.,'median_positive_width_over_remainder':statistics.median((x['upper']-x['lower'])/x['remainder'] for x in positive),'mean_all_width_over_group_total':statistics.mean((x['upper']-x['lower'])/x['group_total'] for x in subset if x['group_total']>0)}
        for selection in ['all','positive','named','exclude_source_0']:
            selected=[x for x in subset if x['group_total']>0 and (selection!='positive' or x['truth']>0) and (selection!='named' or x['destination']!='UNRESOLVED_DESTINATION') and (selection!='exclude_source_0' or x['source']!='0')]
            for fraction in [.05,.1,.25,.5]:
                resolved=wrong=above=0
                for x in selected:
                    threshold=fraction*x['group_total']
                    state=1 if x['lower']>=threshold-1e-8 else (0 if x['upper']<threshold-1e-8 else None)
                    if state is not None:
                        resolved+=1;above+=state;wrong+=int(state!=int(x['truth']>=threshold-1e-8))
                threshold_rows.append({'method':method,'selection':selection,'threshold':fraction,'cases':len(selected),'resolved':resolved,'above':above,'wrong':wrong,'resolved_fraction':resolved/len(selected),'wrong_among_resolved':wrong/resolved if resolved else None})
    result={'radii':radii,'calibration_counts':{c:len(v['tv']) for c,v in scores.items()},'sources':list(anchors),'targets':len(anchors)*8,'metrics':summaries,'decisions':threshold_rows,'same_assumption_lp_checks':len(lp_gaps),'maximum_lp_gap':max(lp_gaps),'positive_singleton_cases':singleton_nonzero,'interpretation':'Retrospective descriptive comparison; thresholds illustrate questions about destination share. UNKNOWN destination sums are not named routes. Box and TV impose different calibrated shape assumptions. Identical TV LP confirms equivalence, not exclusive capability.'}
    for name,rows in [('INTERVALS.csv',records),('DECISIONS.csv',threshold_rows)]:
        with (out/name).open('w',encoding='utf-8',newline='') as f:
            writer=csv.DictWriter(f,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    (out/'RESULTS.json').write_text(json.dumps(result,indent=2))
    print(json.dumps({'metrics':summaries,'radii':radii,'lp_gap':max(lp_gaps),'singleton':singleton_nonzero,'primary_decisions':[x for x in threshold_rows if x['selection']=='all']},indent=2))
if __name__=='__main__':main()
