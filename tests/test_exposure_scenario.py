import unittest

from temflow.exposure_scenario import calculate_exposure_scenario


ROUTES = {
    "r1": {"from_node_id": "source", "to_node_id": "market-a"},
    "r2": {"from_node_id": "market-a", "to_node_id": "market-b"},
}


def scenario(**updates):
    value = {
        "requested": True,
        "source_node_id": "source",
        "retained_mass_lower_kg_year": 3650,
        "retained_mass_upper_kg_year": 7300,
        "consumer_population": 100,
        "concentration_mg_per_kg_food": 0.2,
        "body_weight_kg": 50,
        "reference_dose_mg_per_kg_day": 0.0001,
        "declared_thq_threshold": 1.0,
        "population_basis": "projected",
        "mass_basis": "modelled",
        "chemistry_basis": "last_reported",
    }
    value.update(updates)
    return value


class ExposureScenarioTests(unittest.TestCase):
    def test_explicit_exceedance_returns_cpc_edi_thq_and_wave_order(self):
        result = calculate_exposure_scenario(
            scenario(),
            selected_node_ids=["source", "market-a", "market-b"],
            selected_route_ids=["r1", "r2"],
            routes=ROUTES,
            analysis_reference_date="2026-09-13",
        )
        self.assertEqual(result["status"], "threshold_exceeded_across_interval")
        self.assertTrue(result["display_available"])
        self.assertEqual(result["cpc_kg_person_year"], [36.5, 73.0])
        self.assertAlmostEqual(result["estimated_daily_intake_mg_kg_bw_day"][0], 0.0004)
        self.assertAlmostEqual(result["thq"][0], 4.0)
        self.assertEqual(result["map"]["node_hops"], {"source": 0, "market-a": 1, "market-b": 2})
        self.assertEqual(result["map"]["route_hops"], {"r1": 0, "r2": 1})

    def test_below_threshold_does_not_offer_animation(self):
        result = calculate_exposure_scenario(
            scenario(concentration_mg_per_kg_food=0.001),
            selected_node_ids=["source"],
            selected_route_ids=[],
            routes=ROUTES,
            analysis_reference_date="2026-09-13",
        )
        self.assertEqual(result["status"], "below_declared_threshold")
        self.assertFalse(result["display_available"])

    def test_not_requested_remains_separate_from_model_run(self):
        result = calculate_exposure_scenario(
            None,
            selected_node_ids=[],
            selected_route_ids=[],
            routes=ROUTES,
            analysis_reference_date="2026-09-13",
        )
        self.assertEqual(result["status"], "not_requested")
        self.assertFalse(result["display_available"])

    def test_invalid_basis_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "population_basis"):
            calculate_exposure_scenario(
                scenario(population_basis="observed_and_projected"),
                selected_node_ids=["source"],
                selected_route_ids=[],
                routes=ROUTES,
                analysis_reference_date="2026-09-13",
            )


if __name__ == "__main__":
    unittest.main()
