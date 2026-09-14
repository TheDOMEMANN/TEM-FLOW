import unittest

from temflow.compositional import (
    compositional_allocation,
    finite_sample_radius,
    total_variation,
)


class CompositionalTests(unittest.TestCase):
    def test_finite_sample_order_statistic(self):
        self.assertEqual(finite_sample_radius([0.1, 0.2, 0.3, 0.4], 0.5), 0.3)

    def test_total_variation(self):
        self.assertAlmostEqual(total_variation([0.6, 0.4], [0.5, 0.5]), 0.1)

    def test_bounds_conserve_and_refuse_unresolved_name(self):
        result = compositional_allocation(
            remainder_mass=100.0,
            destinations=("local", "market", "UNRESOLVED_DESTINATION"),
            historical_shares=(0.6, 0.4, 0.0),
            epsilon=0.2,
        )
        self.assertLessEqual(sum(item.lower_mass for item in result.coordinates), 100.0)
        self.assertGreaterEqual(sum(item.upper_mass for item in result.coordinates), 100.0)
        self.assertEqual(result.coordinates[-1].named_report_status, "blocked_unresolved_identity")
        self.assertIsNone(result.operational_point_allocation)
        self.assertTrue(result.contains({"local": 50, "market": 40, "UNRESOLVED_DESTINATION": 10}))
        self.assertFalse(result.contains({"local": 20, "market": 30, "UNRESOLVED_DESTINATION": 50}))

    def test_source_only_state_remains_broad(self):
        result = compositional_allocation(
            remainder_mass=80.0,
            destinations=("A", "B", "UNRESOLVED_DESTINATION"),
            historical_shares=(0.4, 0.6, 0.0),
            epsilon=1.0,
        )
        self.assertTrue(all(item.lower_mass == 0 for item in result.coordinates))
        self.assertTrue(all(item.upper_mass == 80 for item in result.coordinates))
        self.assertEqual(result.width_contraction, 0.0)


if __name__ == "__main__":
    unittest.main()
