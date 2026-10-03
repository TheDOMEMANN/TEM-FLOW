"""Check that numerical failures and censored results cannot be reported as success."""
import copy, json, unittest, sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
from reproduce_benchmark import evaluate

class ReproductionChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows=json.loads((Path(__file__).parent/'recorded/RESULTS.json').read_text())
    def test_recorded_evidence_agrees(self):
        result=evaluate(self.rows,self.rows)
        self.assertEqual(result['status'],'PASS')
        self.assertEqual(result['matched_destination_budget_values'],1776)
    def test_changed_bound_fails(self):
        rows=copy.deepcopy(self.rows)
        row=next(r for r in rows if r['method']!='temflow' and r['status']=='pass')
        row['profiles'][0][0]+=1
        self.assertEqual(evaluate(rows,self.rows)['status'],'FAIL')
    def test_missing_case_fails(self):
        with self.assertRaises(ValueError):evaluate(self.rows[:-1],self.rows)
    def test_additional_timeout_is_incomplete(self):
        rows=copy.deepcopy(self.rows)
        next(r for r in rows if r['method']!='temflow' and r['status']=='pass')['status']='timeout'
        self.assertEqual(evaluate(rows,self.rows)['status'],'INCOMPLETE')
    def test_speed_is_measured_separately(self):
        rows=copy.deepcopy(self.rows)
        row=next(r for r in rows if r['method']!='temflow' and r['status']=='pass')
        row['median_seconds']=1e-9
        result=evaluate(rows,self.rows)
        self.assertEqual(result['status'],'PASS')
        self.assertFalse(result['temflow_faster_in_every_completed_comparison'])
    def test_nonfinite_bound_fails(self):
        rows=copy.deepcopy(self.rows)
        next(r for r in rows if r['status']=='pass')['profiles'][0][0]=float('nan')
        with self.assertRaises(ValueError):evaluate(rows,self.rows)

if __name__=='__main__':unittest.main()
