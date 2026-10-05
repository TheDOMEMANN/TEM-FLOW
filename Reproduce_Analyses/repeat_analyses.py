"""Repeat the dated Array analyses without altering recorded results."""
from pathlib import Path
from datetime import datetime
import argparse,csv,hashlib,html,json,math,os,shutil,subprocess,sys,traceback

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE/'code'))
from source_location import locate_source
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def equal(a,b,path='result'):
    if isinstance(a,dict):
        assert a.keys()==b.keys(),path+' keys'
        for k in a:equal(a[k],b[k],path+'/'+str(k))
    elif isinstance(a,list):
        assert len(a)==len(b),path+' length'
        for i,(x,y) in enumerate(zip(a,b)):equal(x,y,path+'/'+str(i))
    elif isinstance(a,(float,int)) and not isinstance(a,bool):
        assert math.isclose(a,b,rel_tol=1e-9,abs_tol=1e-7),(path,a,b)
    else:assert a==b,(path,a,b)

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path)
    parser.add_argument('--source-root',type=Path,help='Companion source folder containing src/temflow.')
    args=parser.parse_args()
    out=(args.output or HERE/'fresh_runs'/datetime.now().strftime('%Y%m%d-%H%M%S-%f')).resolve()
    if out.exists():raise ValueError('Choose a new output folder; recorded or previous results will not be overwritten.')
    if any(out==p.resolve() or out.is_relative_to(p.resolve()) for p in [HERE/'code',HERE/'inputs',HERE/'recorded_results',HERE/'generated_figures']):raise ValueError('Do not write into supplied evidence or code.')
    out.mkdir(parents=True)
    report={'status':'running','software_version':'1.0.0','source_revision':'2026-10-05','checks':{},'fresh_output':str(out),'python':sys.version,'timing_rule':'Timing is measured again, but matching a previous time or speed ordering is not a pass criterion.'}
    try:
        manifest=json.loads((HERE/'MANIFEST.json').read_text())
        for rel,digest in manifest['files'].items():assert sha(HERE/rel)==digest,'Checksum mismatch: '+rel
        report['checks']['input_and_code_integrity']={'status':'pass','files':len(manifest['files'])}
        source=locate_source(HERE,args.source_root)
        report['source_root']=str(source)
        for copied,original in [('production_tree.py','_structural_tree.py'),('production_compositional.py','compositional.py')]:
            assert sha(HERE/'code'/copied)==sha(source/'src/temflow'/original),'Companion source differs: '+original
        report['checks']['production_source_identity']={'status':'pass','files':2}
        for name in ['code','inputs']:shutil.copytree(HERE/name,out/name)
        for script in ['structural_comparator.py','decision_analysis.py','reporting_example.py']:
            print('Running '+script.replace('_',' ').replace('.py','')+' ...',flush=True)
            env=dict(os.environ,PYTHONUTF8='1',PYTHONDONTWRITEBYTECODE='1')
            with (out/(script+'.log')).open('w',encoding='utf-8') as log:
                completed=subprocess.run([sys.executable,'-B','-c',"import runpy,sys; sys.path.insert(0,sys.argv[1]); runpy.run_path(sys.argv[2],run_name='__main__')",str(out/'code'),str(out/'code'/script)],cwd=out,stdout=log,stderr=subprocess.STDOUT,env=env)
            assert completed.returncode==0,'Calculation failed; see '+str(out/(script+'.log'))
        print('Running African retrospective reporting analysis ...',flush=True)
        with (out/'african_reporting.py.log').open('w',encoding='utf-8') as log:
            done=subprocess.run([sys.executable,'-B','-c',
                "import sys; sys.path.insert(0,sys.argv[1]); from african_reporting import run; run(sys.argv[2],sys.argv[3],sys.argv[4])",
                str(out/'code'),str(out/'results/african_reporting'),str(out/'inputs/brazzaville'),str(source)],
                cwd=out,stdout=log,stderr=subprocess.STDOUT,env=env)
        assert done.returncode==0,'African analysis failed; see african_reporting.py.log'
        expected_africa=json.loads((HERE/'recorded_results/african_reporting/RESULTS.json').read_text(encoding='utf-8'))
        actual_africa=json.loads((out/'results/african_reporting/RESULTS.json').read_text(encoding='utf-8'))
        for values in [expected_africa,actual_africa]:values.pop('environment',None)
        equal(expected_africa,actual_africa,'African results (environment metadata excluded)')
        equal(json.loads((HERE/'recorded_results/african_reporting/REPORTING_PAYLOADS.json').read_text(encoding='utf-8')),
              json.loads((out/'results/african_reporting/REPORTING_PAYLOADS.json').read_text(encoding='utf-8')),'African public-engine payloads')
        assert actual_africa['validation']['public_engine_calls']==256
        report['checks']['african_reporting']={'status':'pass',**actual_africa['validation']}
        for folder in [HERE/'recorded_results/african_reporting',out/'results/african_reporting']:
            for name,digest in json.loads((folder/'OUTPUT_MANIFEST.json').read_text(encoding='utf-8')).items():
                assert sha(folder/name)==digest,'African output manifest mismatch: '+name
        report['checks']['african_output_manifests']={'status':'pass'}
        for key in ['decision','reporting_example']:
            equal(json.loads((HERE/'recorded_results'/key/'RESULTS.json').read_text()),json.loads((out/'results'/key/'RESULTS.json').read_text()))
            report['checks'][key]={'status':'pass','comparison':'all saved numerical fields, absolute tolerance 1e-7 and relative tolerance 1e-9'}
        old=json.loads((HERE/'recorded_results/structural_comparison/RESULTS.json').read_text())
        new=json.loads((out/'results/structural_comparison/RESULTS.json').read_text())
        equal(old['comparison_values'],new['comparison_values']);equal(old['extra_edge_case_checks'],new['extra_edge_case_checks'])
        assert len(old['cases'])==len(new['cases'])
        for a,b in zip(old['cases'],new['cases']):
            for key in ['id','destinations','records','budget','widths']:equal(a[key],b[key],key)
            assert b['maximum_gap']<1e-7
        report['checks']['structural_comparison']={'status':'pass','compared_values':new['comparison_values'],'maximum_gap':new['max_gap'],'cases':len(new['cases']),'timing_repeated':True}
        # Compare every output CSV, including every African endpoint and scenario.
        expected_csv={p.relative_to(HERE/'recorded_results').as_posix():p for p in (HERE/'recorded_results').rglob('*.csv')}
        actual_csv={p.relative_to(out/'results').as_posix():p for p in (out/'results').rglob('*.csv')}
        assert expected_csv.keys()==actual_csv.keys(),'Output CSV inventory differs'
        table_rows={}
        for name,path in sorted(expected_csv.items()):
            with path.open(newline='',encoding='utf-8') as f:
                reader=csv.DictReader(f);expected_columns=reader.fieldnames;expected=list(reader)
            with actual_csv[name].open(newline='',encoding='utf-8') as f:
                reader=csv.DictReader(f);actual_columns=reader.fieldnames;actual=list(reader)
            assert expected_columns==actual_columns,name+' columns'
            assert len(expected)==len(actual),name+' rows'
            for i,(a,b) in enumerate(zip(expected,actual)):
                for k in expected_columns:
                    try:left,right=float(a[k]),float(b[k])
                    except (ValueError,TypeError):equal(a[k],b[k],f'{name}/{i}/{k}')
                    else:equal(left,right,f'{name}/{i}/{k}')
            table_rows[name]=len(expected)
        report['checks']['complete_output_tables']={'status':'pass','files':len(table_rows),'rows_by_file':table_rows}
        if source.exists():
            for copied,original in [('production_tree.py','_structural_tree.py'),('production_compositional.py','compositional.py')]:
                assert sha(HERE/'code'/copied)==sha(source/'src/temflow'/original)
            target=out/'BASE_EMPIRICAL_CHECK.json'
            with (out/'base_empirical.log').open('w',encoding='utf-8') as log:
                done=subprocess.run([sys.executable,'-B',str(source/'analysis/python/reproduce_all.py'),'--output',str(target)],cwd=source,stdout=log,stderr=subprocess.STDOUT,env=env)
            assert done.returncode==0,'Older empirical check failed; see base_empirical.log'
            report['checks']['base_empirical_checks']=json.loads(target.read_text())
        else:raise FileNotFoundError('Keep the Editable_Source (user) or Source (journal) folder beside this analysis folder.')
        report['status']='pass'
    except Exception as exc:
        report['status']='fail';report['error']=str(exc)
        (out/'ERROR.txt').write_text(traceback.format_exc(),encoding='utf-8')
    (out/'REPORT.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    lines=['<!doctype html><meta charset="utf-8"><title>TEM-FLOW reproduction report</title><style>body{font:18px system-ui;max-width:850px;margin:3em auto;line-height:1.5}h1{font-size:28px}</style>',f'<h1>Reproduction {report["status"].upper()}</h1>', '<p>Version 1.0.0, source revision 5 October 2026. Recorded files were preserved.</p>']
    for k,v in report['checks'].items():lines.append('<p><b>'+html.escape(k.replace('_',' '))+':</b> '+html.escape(v['status'])+'</p>')
    lines.append('<p>'+html.escape(report['timing_rule'])+'</p>')
    lines.append('<p>The Brazzaville analysis is repeated from 8,208 African survey records, with all 256 cases checked through the public engine. Loss is simulated after aggregation; reports share the underlying survey estimates. This is retrospective reporting evaluation, not independent validation of measurement acquisition or an operational field trial. The UK test is repeated from raw data; earlier Karg, Dryad and Comtrade results are rescored, Nigeria uses public derived truth and Zambia uses published tables.</p>')
    if 'error' in report:lines.append('<p>'+html.escape(report['error'])+'</p>')
    lines.append('<p>See REPORT.json for details and the results folder for fresh outputs.</p>')
    (out/'REPORT.html').write_text('\n'.join(lines),encoding='utf-8')
    print(report['status'].upper()+': '+str(out/'REPORT.html'),flush=True)
    return 0 if report['status']=='pass' else 1
if __name__=='__main__':raise SystemExit(main())
