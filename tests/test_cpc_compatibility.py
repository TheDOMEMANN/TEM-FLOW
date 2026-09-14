from __future__ import annotations

import unittest

from temflow.cpc_compatibility import (
    compare_and_screen,
    compare_cpc,
    hazard_alarm_projection,
    matched_hazard_quotient,
    recalculate_cpc,
)


class CPCCompatibilityTests(unittest.TestCase):
    def test_covered_measurement_uses_intersection(self):
        result = compare_cpc(6, 10, 8, 9)
        self.assertEqual(result.status, "covered")
        self.assertEqual((result.matched_cpc_lower, result.matched_cpc_upper), (8, 9))
        self.assertEqual((result.unmatched_cpc_lower, result.unmatched_cpc_upper), (0, 0))

    def test_upper_miss_retains_unmatched_product_state(self):
        result = compare_cpc(6, 10, 20)
        self.assertEqual(result.status, "upper_envelope_miss")
        self.assertEqual(result.gap, 10)
        self.assertEqual((result.matched_cpc_lower, result.matched_cpc_upper), (6, 10))
        self.assertEqual((result.unmatched_cpc_lower, result.unmatched_cpc_upper), (10, 14))

    def test_existing_chemistry_never_propagates_to_unmatched_cpc(self):
        result = compare_cpc(6, 10, 20)
        hazard = matched_hazard_quotient(result, 0.3, 60, 0.001)
        factor = 0.3 / (365 * 60 * 0.001)
        self.assertAlmostEqual(hazard["hq_matched_lower"], factor * 6)
        self.assertAlmostEqual(hazard["hq_matched_upper"], factor * 10)
        self.assertEqual(hazard["hi_total_status"], "partial")

    def test_lower_miss_is_not_called_influx(self):
        result = compare_cpc(6, 10, 3, 4)
        self.assertEqual(result.status, "lower_envelope_miss")
        self.assertIsNone(result.matched_cpc_lower)
        self.assertEqual(result.unmatched_cpc_upper, 0)
        hazard = matched_hazard_quotient(result, 0.3, 60, 0.001)
        self.assertIsNone(hazard["hq_matched_upper"])

    def test_invalid_intervals_fail(self):
        with self.assertRaises(ValueError):
            compare_cpc(10, 6, 8)
        with self.assertRaises(ValueError):
            compare_cpc(6, 10, 9, 8)

    def test_cpc_recalculation_uses_mass_over_corresponding_population(self):
        result = recalculate_cpc(6000, 1000, 10000)
        self.assertEqual(result["cpc_lower_kg_person_year"], 6)
        self.assertEqual(result["cpc_upper_kg_person_year"], 10)
        with self.assertRaises(ValueError):
            recalculate_cpc(6000, 0)

    def test_fixed_hq_alarm_projection_retains_interval_and_completeness(self):
        result = compare_and_screen(
            {
                "identified_lower": 6,
                "identified_upper": 10,
                "measured_lower": 8,
                "measured_upper": 9,
                "concentration_mg_per_kg_food": 3,
                "body_weight_kg": 60,
                "reference_dose_mg_per_kg_day": 0.001,
            }
        )
        self.assertEqual(result["alarm_projection"]["threshold_hq"], 1.0)
        self.assertEqual(result["alarm_projection"]["status"], "alarm_across_matched_interval")
        self.assertEqual(
            hazard_alarm_projection({"hq_matched_lower": 0.5, "hq_matched_upper": 1.5, "hi_total_status": "partial"})[
                "status"
            ],
            "threshold_crossing_within_matched_interval",
        )


if __name__ == "__main__":
    unittest.main()

