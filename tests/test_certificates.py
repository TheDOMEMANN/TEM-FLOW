import csv
from pathlib import Path
import unittest

from temflow.certificates import build_registry_certificates, ziway_denominator_certificate
from temflow.tem_calculus import ziway_addis_mass_claim


ROOT = Path(__file__).resolve().parents[1]


class CertificateTests(unittest.TestCase):
    def test_registry_certificate_counts(self):
        path = ROOT / "src" / "temflow" / "data" / "patterns" / "edflow_edge_registry_v1_1.csv"
        with path.open(encoding="utf-8", newline="") as handle:
            records = build_registry_certificates(csv.DictReader(handle), source_release="test")
        self.assertEqual(len(records), 3907)
        self.assertEqual(sum(item.status == "certified" for item in records), 1655)
        self.assertEqual(sum(item.quantity_authorized for item in records), 1313)
        self.assertEqual(len({item.proof_digest for item in records}), len(records))

    def test_ziway_denominator_certificate_and_mass_claim(self):
        certificate = ziway_denominator_certificate()
        claim = ziway_addis_mass_claim()
        self.assertEqual(certificate.status, "certified")
        self.assertIn(certificate.certificate_id, claim.certificate_ids)
        self.assertLess(abs(claim.lower - 198.81), 0.1)
        self.assertLess(abs(claim.upper - 202.75), 0.1)
        self.assertTrue(claim.claim_id.startswith("TEM-CLAIM-"))
