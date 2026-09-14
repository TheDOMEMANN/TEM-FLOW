import unittest

import numpy as np

from temflow.core import (
    OriginCommodity,
    build_time_expanded_network,
    channel_share_bounds,
    chronic_daily_intake,
    consequence_weighted_aggregation_adequacy,
    edible_consumption_kg_per_capita_year,
    kl_box_projection,
    propagate_acyclic_network,
    reference_destination_shares,
)


class CoreTests(unittest.TestCase):
    def test_unknown_coverage_is_uninformative(self):
        lower, upper = channel_share_bounds([0.4, 0.6], 0.0)
        np.testing.assert_allclose(lower, [0.0, 0.0])
        np.testing.assert_allclose(upper, [1.0, 1.0])

    def test_complete_coverage_collapses_to_channel_shares(self):
        lower, upper = channel_share_bounds([0.4, 0.6], 1.0)
        np.testing.assert_allclose(lower, [0.4, 0.6])
        np.testing.assert_allclose(upper, [0.4, 0.6])

    def test_invalid_coverage_fails(self):
        with self.assertRaises(ValueError):
            channel_share_bounds([1.0], 1.1)

    def test_kl_projection_respects_bounds_and_total(self):
        x = kl_box_projection([0.55, 0.30, 0.15], lower=[0.1, 0.2, 0.0], upper=[0.5, 0.6, 0.4])
        self.assertAlmostEqual(float(x.sum()), 1.0, places=8)
        self.assertTrue(np.all(x >= np.array([0.1, 0.2, 0.0]) - 1e-9))
        self.assertTrue(np.all(x <= np.array([0.5, 0.6, 0.4]) + 1e-9))

    def test_infeasible_kl_projection_fails(self):
        with self.assertRaises(ValueError):
            kl_box_projection([0.5, 0.5], lower=[0.6, 0.6])

    def test_structural_zero_is_exact(self):
        shares = reference_destination_shares(
            [100, 100], [1, 1], [0, 0], [0, 0], [0, 0], [True, False]
        )
        np.testing.assert_allclose(shares, [1.0, 0.0])

    def test_transit_is_not_local_consumption(self):
        key = OriginCommodity("lake", "tilapia")
        result = propagate_acyclic_network(
            ["source", "hub", "city"],
            {(key, "source"): 100.0},
            {"source": 0.0, "hub": 0.2, "city": 1.0},
            {"source": {"hub": 1.0}, "hub": {"city": 1.0}},
        )
        self.assertAlmostEqual(result.absorbed[(key, "hub")], 20.0)
        self.assertAlmostEqual(result.edge_flow[(key, "hub", "city")], 80.0)

    def test_explicit_closures_balance(self):
        key = OriginCommodity("lake", "tilapia")
        result = propagate_acyclic_network(
            ["source", "market"],
            {(key, "source"): 100.0},
            {"source": 0.10, "market": 1.0},
            {"source": {"market": 0.60}},
            {"source": {"loss": 0.10, "stock": 0.10, "export": 0.20}},
        )
        self.assertAlmostEqual(result.loss[(key, "source")], 9.0)
        self.assertAlmostEqual(result.stock[(key, "source")], 9.0)
        self.assertAlmostEqual(result.export[(key, "source")], 18.0)
        self.assertAlmostEqual(result.residual[(key, "source")], 0.0)
        self.assertLess(max(abs(x) for x in result.balance_error.values()), 1e-12)

    def test_invalid_closure_sum_fails(self):
        key = OriginCommodity("lake", "tilapia")
        with self.assertRaises(ValueError):
            propagate_acyclic_network(
                ["source", "market"], {(key, "source"): 1.0}, {"source": 0.0},
                {"source": {"market": 0.8}}, {"source": {"loss": 0.3}},
            )

    def test_species_specific_exposure(self):
        self.assertGreater(chronic_daily_intake([0.03], [4.0], 55.0), 0)
        self.assertEqual(chronic_daily_intake([0.0], [4.0], 55.0), 0)

    def test_edible_mass_closure(self):
        rate = edible_consumption_kg_per_capita_year([120.0, 80.0], [0.55, 0.60], 100_000)
        self.assertAlmostEqual(rate * 100_000, 1000 * (120 * 0.55 + 80 * 0.60))

    def test_cwaa_expected_excess_loss(self):
        score = consequence_weighted_aggregation_adequacy([8.0, 1.0], [2.0, 1.0], [0.2, 0.8])
        self.assertAlmostEqual(score, 1.2)

    def test_time_expansion_advances_period(self):
        nodes, transitions = build_time_expanded_network(
            ["source", "market"], ["2025", "2026", "2027"],
            [("source", "market", 1, 0.7)], {"market": 0.2},
        )
        self.assertIn("source@2025", nodes)
        self.assertIn("market@2026", transitions["source@2025"])
        self.assertIn("market@2027", transitions["market@2026"])

    def test_time_expansion_rejects_zero_lag(self):
        with self.assertRaises(ValueError):
            build_time_expanded_network(["a", "b"], ["t0", "t1"], [("a", "b", 0, 1.0)])


if __name__ == "__main__":
    unittest.main()

