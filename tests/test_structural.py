import copy
import json
from pathlib import Path
import tempfile
import threading
import unittest
from urllib.request import Request, urlopen
from temflow.structural import run_structural_payload, structural_csv_to_payload, _general_profiles
from temflow.private_engine import EngineServer

ROOT = Path(__file__).resolve().parents[1]


class StructuralTests(unittest.TestCase):
    def setUp(self):
        self.p = json.loads((ROOT/'docs/STRUCTURAL_EXAMPLE.json').read_text())

    def test_conditional_and_prospective_are_distinct(self):
        r = run_structural_payload(self.p)
        self.assertEqual(r['engine_version'], '1.0.0')
        self.assertEqual(r['conditional']['bounds']['A'], {'lower': 0., 'upper': 40.})
        self.assertEqual(r['prospective']['widths']['A'], [100., 100.])
        self.assertEqual(r['conditional']['bounds']['Unallocated'], {'lower': 60., 'upper': 60.})
        self.assertEqual(r['prospective']['widths']['Unallocated'], [0., 100.])

    def test_crossing_groups_use_general_formula(self):
        self.p['destinations'] = ['A','B','C','D']; self.p.pop('unallocated_destination')
        self.p['records'] = [{'id':'ab','destinations':['A','B'],'value':50,'error':0},
                             {'id':'ac','destinations':['A','C'],'value':50,'error':0}]
        r = run_structural_payload(self.p)
        self.assertEqual(r['structure'], 'crossing_groups')
        self.assertTrue(all(x == [50.,100.] for x in r['prospective']['widths'].values()))

    def test_noisy_repeat_records_and_witness(self):
        self.p['records'] = [{'id':'a1','destinations':['A'],'value':30,'error':1},
                             {'id':'a2','destinations':['A'],'value':30,'error':2}]
        self.p['missing_record_budget']=2; self.p['include_witnesses']=True
        r = run_structural_payload(self.p)
        self.assertEqual(r['prospective']['widths']['A'], [2.,4.,100.])
        self.assertEqual(r['conditional']['bounds']['A'], {'lower':29.,'upper':31.})
        w = r['prospective']['witnesses']['A'][1]
        self.assertLessEqual(len(w['erased']),1)
        self.assertAlmostEqual(sum(w['x_prime']),100)
        self.assertEqual(w['width'],4)

    def test_known_missing_and_blank_reading(self):
        self.p['records'][0]['value']=None
        self.assertEqual(run_structural_payload(self.p)['conditional']['status'],'readings_required')
        self.p['known_missing_record_ids']=['market-pair-1']; self.p['missing_record_budget']=0
        r=run_structural_payload(self.p)
        self.assertEqual(r['conditional']['bounds']['Unallocated']['upper'],100)

    def test_incompatible_observations_not_silent(self):
        self.p['records'][0]['value']=120
        r=run_structural_payload(self.p)
        self.assertEqual(r['conditional']['status'],'infeasible')
        self.assertEqual(r['prospective']['status'],'ok')

    def test_csv_roundtrip_and_context_validation(self):
        text=(ROOT/'docs/AGGREGATE_RECORD_EXAMPLE.csv').read_text()
        self.assertEqual(run_structural_payload(structural_csv_to_payload(text))['conditional'],
                         run_structural_payload(self.p)['conditional'])
        with self.assertRaises(ValueError): structural_csv_to_payload(text+'\n100,A|B|Unallocated,1,other,Fish,kg,2026-01-01,2026-01-31,r2,A,0,30,2026-01-31,test')

    def test_invalid_contracts_rejected(self):
        for field,value in [('total_mass',float('nan')),('missing_record_budget',True),('destinations',['A','A']),
                            ('known_missing_record_ids',['absent']),('schema','unknown'),('prior',[.5,.5])]:
            p=copy.deepcopy(self.p);p[field]=value
            with self.subTest(field=field),self.assertRaises(ValueError):run_structural_payload(p)
        p=copy.deepcopy(self.p);p['records']*=2
        with self.assertRaises(ValueError):run_structural_payload(p)

    def test_one_destination_and_total_only(self):
        self.p.update(destinations=['A'],records=[{'id':'total','destinations':['A'],'value':100,'error':1}],unallocated_destination=None)
        r=run_structural_payload(self.p)
        self.assertEqual(r['prospective']['widths'],{'A':[0.,0.]})
        self.assertEqual(r['conditional']['bounds']['A'],{'lower':100.,'upper':100.})

    def test_tree_against_general_for_compatible_groups(self):
        for error in [0, .1, 2.5, 80]:
            self.p['records']=[{'id':'ab','destinations':['A','B'],'error':error,'value':40},
                               {'id':'a','destinations':['A'],'error':error/2,'value':20}]
            r=run_structural_payload(self.p)
            g=_general_profiles(self.p['destinations'],self.p['records'],100,1)
            for name, values in g['widths'].items():
                for k, value in enumerate(values):
                    self.assertAlmostEqual(r['prospective']['widths'][name][k], value, places=7)

    def test_http_and_integrated_workflow(self):
        with tempfile.TemporaryDirectory() as d:
            server=EngineServer(('127.0.0.1',0),Path(d),None,None)
            thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            try:
                def post(path,p):
                    req=Request(f'http://127.0.0.1:{server.server_port}'+path,data=json.dumps(p).encode(),headers={'Content-Type':'application/json'})
                    with urlopen(req,timeout=15) as response:return json.load(response)
                direct=post('/api/structural/run',self.p)
                integrated=post('/api/model/run',{'structural_problem':self.p})
                self.assertEqual(direct,integrated['structural_evidence_analysis'])
                csv_result=post('/api/structural/run',{'csv_text':(ROOT/'docs/AGGREGATE_RECORD_EXAMPLE.csv').read_text()})
                self.assertEqual(direct['conditional'],csv_result['conditional'])
                for name in ['AGGREGATE_RECORD_EXAMPLE.csv','AGGREGATE_RECORD_TEMPLATE.csv','STRUCTURAL_INPUT_GUIDE.md']:
                    with urlopen(f'http://127.0.0.1:{server.server_port}/docs/{name}',timeout=5) as response:
                        self.assertEqual(response.read(),(ROOT/'docs'/name).read_bytes())
            finally:server.shutdown();server.server_close();thread.join()


if __name__ == '__main__': unittest.main()
