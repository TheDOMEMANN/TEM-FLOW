import csv
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class CanonicalProvenanceTests(unittest.TestCase):
    def test_parallel_evidence_ids_and_payload_hashes_are_unique(self):
        ledger = ROOT / "ledger" / "temflow_evidence_ledger.csv"
        if not ledger.exists():
            self.skipTest("CPC/contaminant application ledger is editor-private")
        with ledger.open(encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
        self.assertEqual(len(rows), len({row["tem_record_id"] for row in rows}))
        self.assertEqual(len(rows), len({row["original_payload_sha256"] for row in rows}))
        self.assertTrue(all(row["parent_record_id"] for row in rows))

    def test_observations_are_not_conflated_with_pipeline_results(self):
        ledger = ROOT / "ledger" / "temflow_evidence_ledger.csv"
        if not ledger.exists():
            self.skipTest("CPC/contaminant application ledger is editor-private")
        with ledger.open(encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
        measured = [row for row in rows if row["observation_calculation_class"] == "observed_or_reported_measurement"]
        pipeline = [row for row in rows if row["observation_calculation_class"] == "edflow_pipeline_calculation"]
        self.assertTrue(measured)
        self.assertTrue(all(row["numeric_status"] == "machine_readable_numeric_value" for row in measured))
        self.assertTrue(all(row["value"] and row["unit"] and row["source_uri"] for row in measured))
        self.assertTrue(all(not row["measurement_status"].startswith(("numeric_reported_measurement", "numeric_measurement")) for row in pipeline))

    def test_certificate_ledger_is_canonical_v03(self):
        expected = "TEMFLOW_Patterns_private_engine_v0_3_0_2026-09-01"
        with (ROOT / "ledger" / "temflow_transformation_certificate_ledger.csv").open(encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
        self.assertEqual({row["source_release"] for row in rows}, {expected})
        self.assertEqual(len(rows), len({row["certificate_id"] for row in rows}))
        self.assertEqual(len(rows), len({row["proof_digest"] for row in rows}))


if __name__ == "__main__":
    unittest.main()
