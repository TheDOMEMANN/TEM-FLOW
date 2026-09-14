import unittest

from temflow.proof_obligations import run_proof_checks
from temflow.tem_calculus import (
    IdentitySignature,
    PathCertificate,
    RouteCertificate,
    certified_marginal_flow_claim,
    certified_path_flow_claim,
)


class ProofObligationTests(unittest.TestCase):
    def test_all_executable_proof_obligations_pass(self):
        checks = run_proof_checks()
        self.assertEqual(len(checks), 6)
        self.assertTrue(all(check.passed for check in checks), [check for check in checks if not check.passed])

    def test_certificate_gated_marginal_bounds_are_sharp(self):
        signature = IdentitySignature(
            country="MAR",
            food_domain="fish",
            commodity="aggregate aquatic products",
            product_form="net product weight",
            origin="MAR",
            destination="CIV",
            period="2024",
            unit="t/year",
        )
        route_certificate = RouteCertificate("ROUTE-CERT", signature, ("HISTORICAL-ROUTE",), "Route identity only; occurrence is not asserted.")
        claim = certified_marginal_flow_claim(
            row_total=70.0,
            column_total=60.0,
            network_total=100.0,
            signature=signature,
            evidence_ids=("ROW", "COLUMN"),
            route_certificate=route_certificate,
        )
        self.assertEqual((claim.lower, claim.upper), (30.0, 60.0))

    def test_marginal_claim_refuses_missing_certificate(self):
        with self.assertRaises(ValueError):
            certified_marginal_flow_claim(
                row_total=10.0,
                column_total=10.0,
                network_total=20.0,
                signature=IdentitySignature(country="ETH", unit="t/year"),
                evidence_ids=("ROW", "COLUMN"),
                route_certificate=None,
            )

    def test_marginal_claim_refuses_identity_mismatched_certificate(self):
        signature = IdentitySignature(country="ETH", commodity="fish", product_form="whole", origin="A", destination="B", period="2024", unit="t")
        corrupted = IdentitySignature(**{**signature.__dict__, "product_form": "fillet"})
        certificate = RouteCertificate("ROUTE-CERT", signature, ("ROUTE-EVIDENCE",), "Identity scope only.")
        with self.assertRaisesRegex(ValueError, "product_form"):
            certified_marginal_flow_claim(
                row_total=10.0,
                column_total=10.0,
                network_total=20.0,
                signature=corrupted,
                evidence_ids=("ROW", "COLUMN"),
                route_certificate=certificate,
            )

    def test_three_margin_path_bounds_and_transient_gate(self):
        signature = IdentitySignature(
            country="GHA", commodity="maize", product_form="fresh-weight equivalent",
            origin="Yendi", transient="Datoyili barrier", destination="Tamale",
            period="2014-peak-holdout", denominator="path flow", unit="kg",
        )
        certificate = PathCertificate("PATH-CERT", signature, ("TRAINING-PATH",), "Exact path identity only.")
        claim = certified_path_flow_claim(
            source_total=80, transient_total=70, destination_total=60, network_total=100,
            signature=signature, evidence_ids=("MARGINS",), path_certificate=certificate,
        )
        self.assertEqual((claim.lower, claim.upper), (10.0, 60.0))
        corrupted = IdentitySignature(**{**signature.__dict__, "transient": "Airport junction"})
        with self.assertRaisesRegex(ValueError, "transient"):
            certified_path_flow_claim(
                source_total=80, transient_total=70, destination_total=60, network_total=100,
                signature=corrupted, evidence_ids=("MARGINS",), path_certificate=certificate,
            )


if __name__ == "__main__":
    unittest.main()
