"""Repeat the matched benchmark without overwriting its recorded evidence."""
from pathlib import Path
import argparse, csv, hashlib, html, json, math, subprocess, sys

HERE = Path(__file__).resolve().parent
METHODS = ('temflow', 'expanded_dinic', 'paired_highs_lp')
LABELS = dict(zip(METHODS, ('TEM-FLOW', 'Expanded network with Dinic', 'Paired-allocation HiGHS LP')))
TOLERANCE = 1e-7

def read(path): return json.loads(path.read_text(encoding='utf-8'))
def digest(path): return hashlib.sha256(path.read_bytes()).hexdigest()
def save(path, data): path.write_text(json.dumps(data, indent=2, allow_nan=False)+'\n', encoding='utf-8')

def verify_inputs():
    manifest = read(HERE/'BENCHMARK_MANIFEST.json')
    for item in manifest['files']:
        path = HERE/item['path']
        if digest(path) != item['sha256']:
            raise ValueError('Benchmark evidence or code checksum changed: '+item['path'])
    source = HERE.parents[1]/'src/temflow/_structural_tree.py'
    if not source.is_file() or digest(source) != manifest['kernel_sha256']:
        raise ValueError('The benchmark kernel does not match the supplied production engine.')
    # Inspect the deterministic generator before any timing is started.
    sys.path.insert(0, str(HERE/'code'))
    import benchmark
    for path in sorted((HERE/'recorded/inputs').glob('*.json')):
        case = read(path)
        generated=json.loads(json.dumps(benchmark.make_case(case['shape'], case['leaves'], case['r'])))
        if generated != case:
            raise ValueError('Generated input differs from recorded input: '+path.name)
    return manifest

def evaluate(rows, reference):
    actual = {(r['case'], r['method']): r for r in rows}
    expected = {(r['case'], r['method']): r for r in reference}
    if len(actual) != len(rows) or set(actual) != set(expected):
        raise ValueError('Missing, duplicate or unexpected method/case evaluations.')
    failures=[]; incomplete=[]; gaps=[]; comparisons=[]; timeouts=[]
    for key, row in actual.items():
        if row['status']=='timeout':
            timeouts.append('/'.join(key))
            if expected[key]['status']=='pass': incomplete.append('/'.join(key))
            continue
        if row['status']!='pass':
            failures.append('/'.join(key)+': '+row['status']); continue
        recorded = expected[key] if expected[key]['status']=='pass' else expected[(key[0],'temflow')]
        a,b=row['profiles'],recorded['profiles']
        if len(a)!=len(b) or any(len(x)!=len(y) for x,y in zip(a,b)):
            raise ValueError('Profile dimensions differ: '+str(key))
        if not all(math.isfinite(v) for p in a for v in p):
            raise ValueError('Nonfinite profile: '+str(key))
        gap=max(abs(v-w) for x,y in zip(a,b) for v,w in zip(x,y))
        gaps.append(gap)
        if gap>TOLERANCE: failures.append('/'.join(key)+': numerical disagreement')
        samples=row['seconds']
        if len(samples)!=3 or not all(math.isfinite(t) and t>0 for t in samples):
            raise ValueError('Three finite positive timing samples are required: '+str(key))
        if key[1]!='temflow':
            target=actual[(key[0],'temflow')]
            if target['status']!='pass': failures.append(key[0]+': TEM-FLOW did not complete');continue
            same_run_gap=max(abs(v-w) for x,y in zip(a,target['profiles']) for v,w in zip(x,y))
            if same_run_gap>TOLERANCE:failures.append('/'.join(key)+': same-run disagreement')
            comparisons.append({'case':key[0],'method':key[1], 'values':sum(map(len,a)),
                'gap':same_run_gap, 'ratio':row['median_seconds']/target['median_seconds']})
    return {'status':'FAIL' if failures else 'INCOMPLETE' if incomplete else 'PASS',
        'failed_checks':failures,'additional_timeouts':incomplete,'timeouts':timeouts,
        'completed_method_case_evaluations':sum(r['status']=='pass' for r in rows),
        'completed_comparator_cases':len(comparisons),
        'matched_destination_budget_values':sum(c['values'] for c in comparisons),
        'maximum_absolute_gap_from_recorded':max(gaps, default=None),
        'maximum_absolute_gap_between_methods':max((c['gap'] for c in comparisons), default=None),
        'temflow_faster_in_every_completed_comparison':bool(comparisons) and all(c['ratio']>1 for c in comparisons),
        'comparisons':comparisons,
        'interpretation':'Exact timing values and timeout patterns depend on the computer. Numerical agreement is checked separately from measured speed. No universal superiority or memory advantage is asserted.'}

def report(rows, summary, out):
    out.mkdir(parents=True, exist_ok=True)
    save(out/'VERIFICATION.json',summary)
    by={(r['case'],r['method']):r for r in rows}
    table=[]
    selected=['balanced_L8_r0','balanced_L8_r1','balanced_L8_r2','balanced_L128_r0','balanced_L1024_r0','balanced_L16_r2']
    for case in selected:
        base=by[(case,'temflow')]
        row={'case':case,'destinations':base['leaves'],'records':base['records'],'maximum_missing':base['r']}
        for method in METHODS:
            entry=by[(case,method)]
            row[method+'_milliseconds']=entry['median_seconds']*1000 if entry['status']=='pass' else 'TIMEOUT'
        table.append(row)
    with (out/'MANUSCRIPT_TIMING_TABLE.csv').open('w',newline='',encoding='utf-8') as f:
        w=csv.DictWriter(f,fieldnames=list(table[0]));w.writeheader();w.writerows(table)
    cells=''.join('<tr>'+''.join('<td>'+html.escape(f'{v:,.3f}' if isinstance(v,float) else str(v))+'</td>' for v in r.values())+'</tr>' for r in table)
    heads=''.join('<th>'+html.escape(k)+'</th>' for k in table[0])
    body=f'''<!doctype html><meta charset="utf-8"><title>TEM-FLOW benchmark reproduction</title>
<style>body{{font:17px/1.5 system-ui;margin:2em;max-width:1100px}}table{{border-collapse:collapse;font-size:14px}}td,th{{padding:.5em;border-bottom:1px solid #999;text-align:left}}pre{{white-space:pre-wrap}}</style>
<h1>TEM-FLOW benchmark reproduction</h1><p>Verification status: <b>{summary['status']}</b>.</p>
<p>All times below are median milliseconds from three repeated batches. TIMEOUT is censored and is not a measured completion time. Every row computes all destinations and every budget from zero through the maximum shown.</p>
<table><thead><tr>{heads}</tr></thead><tbody>{cells}</tbody></table>
<p>Completed comparator cases: {summary['completed_comparator_cases']}. Compared destination/budget values: {summary['matched_destination_budget_values']}. Largest difference from recorded profiles: {summary['maximum_absolute_gap_from_recorded']}.</p>
<p>TEM-FLOW faster in every completed comparison in this run: {summary['temflow_faster_in_every_completed_comparison']}.</p>
<p>In the eight-destination, 28-record, two-loss example, both reference methods enumerate 407 missing-record sets and solve 3,256 optimization problems. TEM-FLOW reuses calculations across the accounting tree.</p>
<p>{summary['interpretation']}</p><pre>{html.escape(json.dumps(summary,indent=2))}</pre>'''
    (out/'REPORT.html').write_text(body,encoding='utf-8')

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',type=Path,help='A new folder for fresh timings and numerical comparisons.')
    p.add_argument('--check-recorded',action='store_true',help='Verify supplied files and regenerate tables without rerunning timings.')
    a=p.parse_args()
    if a.output is None:p.error('--output is required')
    out=a.output.resolve()
    if out.exists():p.error('Choose a new output folder; existing results are never overwritten.')
    verify_inputs()
    reference=read(HERE/'recorded/RESULTS.json')
    if a.check_recorded:
        report(reference,evaluate(reference,reference),out)
        print('Recorded evidence verified. Tables regenerated; no new timing measurements were made.')
    else:
        subprocess.run([sys.executable,'-B',str(HERE/'code/benchmark.py'),'--output',str(out)],check=True)
        rows=read(out/'RESULTS.json'); summary=evaluate(rows,reference)
        report(rows,summary,out)
        print(json.dumps({k:v for k,v in summary.items() if k!='comparisons'},indent=2))
        if summary['status']!='PASS':raise SystemExit(1)
    print('Open '+str(out/'REPORT.html'))

if __name__=='__main__':main()
