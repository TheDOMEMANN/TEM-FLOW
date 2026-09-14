import unittest

from temflow.ledger import EvidenceLedger, EvidenceRecord, EstimandSpec, compatibility_gate
from temflow.temporal import affected_outputs, channel_bounds_from_record, latest_compatible_record


def record(record_id, entered_at="2026-01-01", observed_at="2025-12-01", **kwargs):
    defaults = dict(
        evidence_type="route", source_uri="doi:test", commodity="fish",
        origin="Lake A", destination="City B", stage="trade",
    )
    defaults.update(kwargs)
    return EvidenceRecord(record_id, entered_at, observed_at, **defaults)


class LedgerTests(unittest.TestCase):
    def test_append_only_rejects_duplicate(self):
        ledger = EvidenceLedger([record("r1")])
        with self.assertRaises(ValueError):
            ledger.append(record("r1"))

    def test_supersession_changes_later_snapshot_only(self):
        first = record("r1", evidence_type="share", value=0.4, denominator="channel", coverage_lower=0.2,
                       metadata={"within_channel_shares": [0.4, 0.6]})
        second = record("r2", entered_at="2026-02-01", evidence_type="share", value=0.4,
                        denominator="channel", coverage_lower=0.7, supersedes="r1",
                        metadata={"within_channel_shares": [0.4, 0.6]})
        ledger = EvidenceLedger([first, second])
        self.assertEqual([x.record_id for x in ledger.active("2026-01-15")], ["r1"])
        self.assertEqual([x.record_id for x in ledger.active("2026-02-15")], ["r2"])

    def test_digest_is_snapshot_stable(self):
        ledger = EvidenceLedger([record("r1")])
        self.assertEqual(ledger.digest("2026-01-02"), ledger.digest("2026-01-03"))

    def test_route_without_quantity_is_topology(self):
        decision = compatibility_gate(record("r1"), EstimandSpec("fish", allowed_stages=("trade",)))
        self.assertEqual(decision.model_use, "topology")

    def test_edible_contaminant_is_dose(self):
        item = record("r1", evidence_type="contaminant", species="tilapia", matrix="muscle", value=0.03, unit="mg/kg")
        spec = EstimandSpec("fish", allowed_stages=("trade",), species="tilapia")
        self.assertEqual(compatibility_gate(item, spec).model_use, "dose")

    def test_sediment_contaminant_is_alert_not_dose(self):
        item = record("r1", evidence_type="contaminant", species="tilapia", matrix="sediment", value=0.5, unit="mg/kg")
        spec = EstimandSpec("fish", allowed_stages=("trade",), species="tilapia")
        self.assertEqual(compatibility_gate(item, spec).model_use, "alert")

    def test_species_mismatch_does_not_propagate(self):
        item = record("r1", evidence_type="contaminant", species="tilapia", matrix="muscle", value=0.03, unit="mg/kg")
        spec = EstimandSpec("fish", allowed_stages=("trade",), species="catfish")
        self.assertFalse(compatibility_gate(item, spec).compatible)

    def test_latest_compatible_uses_observation_time(self):
        early = record("r1", observed_at="2025-01-01", evidence_type="contaminant", species="tilapia", matrix="muscle")
        late = record("r2", entered_at="2026-02-01", observed_at="2025-12-01", evidence_type="contaminant", species="tilapia", matrix="muscle")
        ledger = EvidenceLedger([early, late])
        spec = EstimandSpec("fish", allowed_stages=("trade",), species="tilapia")
        self.assertEqual(latest_compatible_record(ledger, "2026-03-01", spec, "dose").record_id, "r2")

    def test_channel_update_narrows_bounds(self):
        item = record("r1", evidence_type="share", value=0.4, coverage_lower=0.6,
                      metadata={"within_channel_shares": [0.4, 0.6]})
        lower, upper = channel_bounds_from_record(item)
        self.assertAlmostEqual(upper[0] - lower[0], 0.4)

    def test_affected_outputs_are_selective(self):
        edible = record("r1", evidence_type="contaminant", species="tilapia", matrix="muscle")
        sediment = record("r2", evidence_type="contaminant", species="tilapia", matrix="sediment")
        ledger = EvidenceLedger([edible, sediment])
        specs = [
            ("tilapia-dose", EstimandSpec("fish", allowed_stages=("trade",), species="tilapia")),
            ("catfish-dose", EstimandSpec("fish", allowed_stages=("trade",), species="catfish")),
        ]
        effects = affected_outputs(ledger, "2026-02-01", specs)
        self.assertEqual({x.output_key for x in effects}, {"tilapia-dose"})
        self.assertEqual({x.model_use for x in effects}, {"dose", "alert"})


if __name__ == "__main__":
    unittest.main()

