from __future__ import annotations

import unittest

from temflow.downstream_consequence import (
    CPCObservation,
    ChemistryEvidence,
    EdibleConversionEvidence,
    FlowIdentity,
    Interval,
    MassEvidence,
    PopulationEvidence,
    TemporalPolicy,
    ToxicologyRule,
    calculate_cpc_state,
    evaluate_consequence,
    evaluate_history,
    mass_to_kg_year,
    select_latest_on_or_before,
    threshold_classification,
)


IDENTITY = FlowIdentity("fish", "Nile tilapia", "whole wet fish", "Lake A", "Market B", "Town C")
POLICY = TemporalPolicy(max_lag_days=800)


def mass(day: str = "2021-12-31", identity: FlowIdentity = IDENTITY) -> MassEvidence:
    return MassEvidence("MASS-1", identity, day, Interval(1, 2, "tonne/year"))


def population(day: str = "2023-07-01", place: str = "Town C") -> PopulationEvidence:
    return PopulationEvidence("POP-1", place, day, "official projection", "resident consumers", Interval(100, 200, "persons"))


def conversion(day: str = "2018-12-31") -> EdibleConversionEvidence:
    return EdibleConversionEvidence("YIELD-1", "fish", "whole wet fish", day, Interval(0.4, 0.6, "fraction"), "transferred scenario")


def chemistry(day: str | None = "2022-06-30", identity: FlowIdentity = IDENTITY) -> ChemistryEvidence:
    return ChemistryEvidence("CHEM-1", identity, "lead", "food", "muscle", day, Interval(0.1, 0.2, "mg/kg"))


TOX = ToxicologyRule("TOX-1", "lead", "screening endpoint", Interval(0.001, 0.001, "mg/kg-bw/day"))


class DownstreamConsequenceTests(unittest.TestCase):
    def test_unit_conversion(self):
        converted = mass_to_kg_year(Interval(1.5, 2, "tonne/year"))
        self.assertEqual((converted.lower, converted.upper, converted.unit), (1500, 2000, "kg/year"))
        with self.assertRaises(ValueError):
            mass_to_kg_year(Interval(1, 2, "kg/day"))

    def test_temporal_selection_uses_latest_past_and_reports_lag(self):
        records = [mass("2021-01-01"), mass("2022-01-01"), mass("2025-01-01")]
        selected, match, blocker = select_latest_on_or_before(records, "2023-01-01", TemporalPolicy(max_lag_days=500))
        self.assertIsNone(blocker)
        self.assertEqual(selected.observed_at, "2022-01-01")
        self.assertEqual(match["lag_days"], 365)

    def test_temporal_selection_blocks_future_leakage_and_undeclared_policy(self):
        selected, _, blocker = select_latest_on_or_before([mass("2025-01-01")], "2023-01-01", TemporalPolicy(10))
        self.assertIsNone(selected)
        self.assertEqual(blocker.code, "no_past_evidence")
        selected, _, blocker = select_latest_on_or_before([mass()], "2023-01-01", TemporalPolicy())
        self.assertIsNone(selected)
        self.assertEqual(blocker.code, "temporal_policy_missing")

    def test_mass_population_cpc_interval_reverses_denominator(self):
        state = calculate_cpc_state(
            identity=IDENTITY,
            target_date="2023-12-31",
            temporal_policy=TemporalPolicy(2200),
            mass_records=[mass()],
            population_records=[population()],
            conversion_records=[conversion()],
        )
        self.assertEqual(state["status"], "computed")
        self.assertAlmostEqual(state["cpc"]["lower"], 2.0)
        self.assertAlmostEqual(state["cpc"]["upper"], 12.0)
        self.assertEqual(state["interval_assumption"], "non-negative outer bounds; dependence not estimated")

    def test_exact_reported_cpc_has_precedence(self):
        reported = CPCObservation("CPC-1", IDENTITY, "2023-06-01", "Town C", "resident consumers", Interval(10, 20, "g/person/day"))
        state = calculate_cpc_state(
            identity=IDENTITY,
            target_date="2023-12-31",
            temporal_policy=POLICY,
            explicit_cpc_records=[reported],
        )
        self.assertEqual(state["source"], "explicit_cpc")
        self.assertAlmostEqual(state["cpc"]["lower"], 3.65)
        self.assertEqual(state["evidence_ids"], ["CPC-1"])

    def test_population_place_and_denominator_are_strict(self):
        state = calculate_cpc_state(
            identity=IDENTITY,
            target_date="2023-12-31",
            temporal_policy=TemporalPolicy(2200),
            mass_records=[mass()],
            population_records=[population(place="Other town")],
            conversion_records=[conversion()],
        )
        self.assertEqual(state["status"], "blocked")
        self.assertEqual(state["blockers"][0]["code"], "compatible_population_missing")
        self.assertIsNone(state["cpc"])

    def test_species_product_and_tissue_identity_are_strict(self):
        mixed = FlowIdentity("fish", "mixed fish", "whole wet fish", "Lake A", "Market B", "Town C")
        cpc_state = {
            "status": "computed",
            "cpc": Interval(1, 2, "kg/person/year").to_dict(),
            "evidence_ids": ["CPC-X"],
            "temporal_matches": {},
            "transformations": [],
        }
        result = evaluate_consequence(
            cpc_state=cpc_state,
            identity=mixed,
            target_date="2023-12-31",
            temporal_policy=POLICY,
            analyte="lead",
            matrix="food",
            tissue="muscle",
            chemistry_records=[chemistry()],
            toxicology_rule=TOX,
            body_weight_kg=Interval(50, 60, "kg"),
        )
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["blockers"][0]["code"], "compatible_chemistry_missing")
        self.assertIsNone(result["hazard_quotient"])

    def test_undated_chemistry_is_missing_not_zero(self):
        cpc_state = {
            "status": "computed",
            "cpc": Interval(1, 2, "kg/person/year").to_dict(),
            "evidence_ids": ["CPC-X"],
            "temporal_matches": {},
            "transformations": [],
        }
        result = evaluate_consequence(
            cpc_state=cpc_state,
            identity=IDENTITY,
            target_date="2023-12-31",
            temporal_policy=POLICY,
            analyte="lead",
            matrix="food",
            tissue="muscle",
            chemistry_records=[chemistry(None)],
            toxicology_rule=TOX,
            body_weight_kg=Interval(50, 60, "kg"),
        )
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["blockers"][0]["code"], "no_past_evidence")
        self.assertFalse(result["missing_values_are_zero"])

    def test_interval_propagation_and_threshold_crossing(self):
        cpc_state = {
            "status": "computed",
            "cpc": Interval(100, 200, "kg/person/year").to_dict(),
            "evidence_ids": ["CPC-X"],
            "temporal_matches": {},
            "transformations": [],
        }
        result = evaluate_consequence(
            cpc_state=cpc_state,
            identity=IDENTITY,
            target_date="2023-12-31",
            temporal_policy=POLICY,
            analyte="lead",
            matrix="food",
            tissue="muscle",
            chemistry_records=[chemistry()],
            toxicology_rule=TOX,
            body_weight_kg=Interval(50, 60, "kg"),
        )
        self.assertEqual(result["status"], "computed")
        self.assertLess(result["hazard_quotient"]["lower"], 1)
        self.assertGreater(result["hazard_quotient"]["upper"], 1)
        self.assertEqual(result["threshold_classification"], "crossing")
        self.assertEqual(threshold_classification(Interval(0.1, 0.9, "HQ"), 1), "below")
        self.assertEqual(threshold_classification(Interval(1, 2, "HQ"), 1), "above")

    def test_historical_states_use_separate_past_matches(self):
        older = mass("2021-01-01")
        newer = MassEvidence("MASS-2", IDENTITY, "2022-01-01", Interval(3, 4, "tonne/year"))
        histories = evaluate_history(
            ["2021-12-31", "2022-12-31"],
            identity=IDENTITY,
            temporal_policy=TemporalPolicy(2000),
            mass_records=[older, newer],
            population_records=[PopulationEvidence("POP-0", "Town C", "2020-01-01", "official", "resident consumers", Interval(100, 100, "persons"))],
            conversion_records=[conversion("2020-01-01")],
            explicit_cpc_records=[],
            chemistry_records=[chemistry("2020-01-01")],
            toxicology_rule=TOX,
            body_weight_kg=Interval(60, 60, "kg"),
            analyte="lead",
            matrix="food",
            tissue="muscle",
        )
        first_id = histories[0]["cpc_state"]["evidence_ids"][0]
        second_id = histories[1]["cpc_state"]["evidence_ids"][0]
        self.assertEqual((first_id, second_id), ("MASS-1", "MASS-2"))


if __name__ == "__main__":
    unittest.main()
