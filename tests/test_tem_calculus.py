import unittest

from temflow.tem_calculus import (
    CPCAllocationCertificate,
    DirectCPCCertificate,
    EvidentialMeasure,
    ExposureCertificate,
    IdentitySignature,
    IntervalMeasureClaim,
    PopulationProjectionCertificate,
    classify_atlas_record,
    classify_temporal_record,
    derive_node_cpc_claim,
    latest_eligible_evidence,
    nearest_compatible_evidence,
    propagate_contaminant_exposure,
    resolve_node_cpc_claim,
    run_temporal_trend,
    run_typed_model,
)


def certified_scalar_cpc_payload(*, chemistry_certified: bool) -> dict:
    signature = {
        "country": "GHA",
        "food_domain": "food",
        "commodity": "maize",
        "product_form": "edible grain",
        "destination": "Tamale",
        "period": "2025",
        "denominator": "resident consumers",
        "unit": "kg/person/year",
    }
    certificates = {
        "direct_cpc": {
            "status": "certified",
            "certificate_id": "DIRECT-CPC-CERT",
            "signature": signature,
            "evidence_ids": ["DIRECT-CPC-AUDIT"],
            "boundary": "Exact node, product, period, denominator and unit.",
        }
    }
    if chemistry_certified:
        certificates["chemistry"] = {
            "status": "certified",
            "evidence_id": "CHEM-1",
            "external_evidence_uri": "doi:test",
            "evidence_date": "2019-06-30",
            "signature": {
                "country": "GHA",
                "food_domain": "food",
                "commodity": "maize",
                "product_form": "edible grain",
                "material": "grain",
                "destination": "Tamale",
                "period": "2019",
                "denominator": "food mass",
                "unit": "mg/kg-food",
            },
        }
    return {
        "cpc": {
            "identified_lower": 8,
            "identified_upper": 12,
            "measured_lower": 9,
            "measured_upper": 11,
            "signature": signature,
            "evidence_ids": ["DIRECT-CPC-SOURCE"],
            "concentration_mg_per_kg_food": 0.2,
            "body_weight_kg": 60,
            "reference_dose_mg_per_kg_day": 0.001,
        },
        "certificates": certificates,
    }


class TEMCalculusTests(unittest.TestCase):
    @staticmethod
    def _trend_record(period, value, evidence_id, signature, **extra):
        return {
            "status": "certified",
            "period": period,
            "value": value,
            "evidence_id": evidence_id,
            "signature": {**signature, "period": period},
            **extra,
        }

    def test_measure_addition_preserves_distinct_identity_atoms(self):
        whole = IdentitySignature(commodity="tilapia", product_form="whole fish", material="whole product", unit="kg/year")
        muscle = IdentitySignature(commodity="tilapia", product_form="fillet", material="muscle", unit="kg/year")
        measure = EvidentialMeasure({whole: 10.0}, {whole: ("mass",)}).add(EvidentialMeasure({muscle: 10.0}, {muscle: ("chem",)}))
        self.assertEqual(measure.total, 20.0)
        self.assertEqual(len(measure.atoms), 2)

    def test_identity_mismatch_is_not_erased_by_equal_scalar_total(self):
        whole = IdentitySignature(commodity="tilapia", material="whole product")
        muscle = IdentitySignature(commodity="tilapia", material="muscle")
        self.assertEqual(whole.compatibility(muscle)["status"], "incompatible")

    def test_uncertified_user_chemistry_is_blocked(self):
        result = run_typed_model(certified_scalar_cpc_payload(chemistry_certified=False))
        self.assertEqual(result["cpc_result"]["hazard"]["hi_total_status"], "blocked_by_evidence_identity")
        self.assertEqual(result["temflow_claims"][0]["status"], "blocked")

    def test_certified_chemistry_reproduces_scalar_hq(self):
        result = run_typed_model(certified_scalar_cpc_payload(chemistry_certified=True))
        self.assertAlmostEqual(result["cpc_result"]["hazard"]["hq_matched_lower"], 0.2 * 9 / (365 * 60 * 0.001))
        self.assertEqual(result["temflow_claims"][0]["status"], "identified")
        self.assertEqual(result["recalculation"]["status"], "explicit_node_cpc_used")
        temporal = result["calculation_certificate"]["temporal_selection"]
        self.assertFalse(temporal["contemporaneousness_required"])
        self.assertEqual(temporal["cpc_period"], "2025")
        self.assertEqual(temporal["chemistry_period"], "2019")

    def test_atlas_record_is_not_mislabeled_as_raw_measurement(self):
        classification = classify_atlas_record({"decision_status": "reported total THQ above one", "chemistry_or_contaminants": "THQ/HI reported"})
        self.assertEqual(classification["measurement_status"], "not_a_direct_machine_readable_measurement")

    def test_ziway_midpoint_is_pipeline_derived(self):
        classification = classify_temporal_record({
            "record_id": "ZIWAY_ADDIS_TOTAL_SHARE_2018", "evidence_type": "share", "value": 0.4107179382, "metadata": {}
        })
        self.assertEqual(classification["epistemic_origin"], "pipeline_derived_interval_summary")

    def test_certified_node_cpc_and_exposure_chain(self):
        mass_sig = IdentitySignature(
            country="GHA", food_domain="food", commodity="maize", product_form="edible grain",
            origin="Yendi", transient="Datoyili barrier", destination="Tamale",
            period="2014", denominator="destination allocation", unit="kg/year",
        )
        population_sig = IdentitySignature(
            country="GHA", destination="Tamale", period="2014",
            denominator="resident consumers", unit="persons",
        )
        cpc_sig = IdentitySignature(
            country="GHA", food_domain="food", commodity="maize", product_form="edible grain",
            origin="Yendi", transient="Datoyili barrier", destination="Tamale",
            period="2014", denominator="resident consumers", unit="kg/person/year",
        )
        mass = IntervalMeasureClaim(mass_sig, 90_000, 110_000, ("MASS",))
        population = IntervalMeasureClaim(population_sig, 9_500, 10_500, ("POP",))
        cpc_certificate = CPCAllocationCertificate(
            "CPC-CERT", mass_sig, population_sig, cpc_sig, 0.8, 0.9,
            ("YIELD",), "Destination population and edible-yield scope only.",
        )
        population_certificate = PopulationProjectionCertificate(
            "POP-PROJ-CERT", population_sig, "Ghana Statistical Service medium projection",
            "city", "2014 projection release", ("POP-PROJECTION-SOURCE",),
            "Tamale city projection for the claim period.",
        )
        cpc = derive_node_cpc_claim(
            allocated_mass=mass, consumer_population=population,
            population_certificate=population_certificate, certificate=cpc_certificate,
        )
        self.assertAlmostEqual(cpc.lower, 90_000 * 0.8 / 10_500)
        self.assertAlmostEqual(cpc.upper, 110_000 * 0.9 / 9_500)

        integrated = run_typed_model({
            "allocation": {
                "allocated_mass_lower_kg_year": 90_000,
                "allocated_mass_upper_kg_year": 110_000,
                "consumer_population_lower": 9_500,
                "consumer_population_upper": 10_500,
                "evidence_ids": ["MASS"],
            },
            "cpc": {"identified_lower": 0, "identified_upper": 20},
            "certificates": {
                "population_projection": {
                    "status": "certified",
                    "certificate_id": "POP-PROJ-CERT",
                    "signature": population_sig.__dict__,
                    "projection_scenario": "Ghana Statistical Service medium projection",
                    "geographic_level": "city",
                    "projection_as_of": "2014 projection release",
                    "evidence_ids": ["POP-PROJECTION-SOURCE"],
                    "boundary": "Tamale city projection for the claim period.",
                },
                "cpc_allocation": {
                    "status": "certified",
                    "certificate_id": "CPC-CERT",
                    "mass_signature": mass_sig.__dict__,
                    "population_signature": population_sig.__dict__,
                    "output_signature": cpc_sig.__dict__,
                    "edible_yield_lower": 0.8,
                    "edible_yield_upper": 0.9,
                    "evidence_ids": ["YIELD"],
                    "mass_evidence_id": "MASS",
                    "boundary": "Destination population and edible-yield scope only.",
                },
            },
        })
        self.assertEqual(integrated["recalculation"]["status"], "computed_from_certified_population_projection")
        self.assertAlmostEqual(integrated["cpc_result"]["comparison"]["measured_lower"], cpc.lower)
        self.assertAlmostEqual(integrated["cpc_result"]["comparison"]["measured_upper"], cpc.upper)

        concentration_sig = IdentitySignature(
            country="GHA", food_domain="food", commodity="maize", product_form="edible grain",
            material="grain", origin="Yendi", transient="Datoyili barrier", destination="Tamale",
            period="2011", denominator="food mass", unit="mg/kg-food",
        )
        bw_sig = IdentitySignature(country="GHA", destination="Tamale", period="2014", denominator="exposed consumers", unit="kg-bodyweight")
        rfd_sig = IdentitySignature(country="GHA", commodity="cadmium", denominator="reference dose", unit="mg/kg-bodyweight/day")
        intake_sig = IdentitySignature(**{**cpc_sig.__dict__, "material": "cadmium", "unit": "mg/kg-bodyweight/day"})
        hq_sig = IdentitySignature(**{**intake_sig.__dict__, "denominator": "reference dose", "unit": "HQ"})
        concentration = IntervalMeasureClaim(concentration_sig, 0.1, 0.2, ("CHEM",))
        body_weight = IntervalMeasureClaim(bw_sig, 55, 65, ("BW",))
        rfd = IntervalMeasureClaim(rfd_sig, 0.001, 0.001, ("RFD",))
        exposure_certificate = ExposureCertificate(
            "EXPOSURE-CERT", cpc_sig, concentration_sig, bw_sig, rfd_sig, intake_sig, hq_sig,
            365, ("JOIN-AUDIT",), "Exact food, tissue, destination, population and period join.",
        )
        result = propagate_contaminant_exposure(
            cpc=cpc, concentration=concentration, body_weight=body_weight,
            reference_dose=rfd, certificate=exposure_certificate,
        )
        self.assertAlmostEqual(result["estimated_daily_intake"].lower, cpc.lower * 0.1 / (365 * 65))
        self.assertAlmostEqual(result["hazard_quotient"].upper, cpc.upper * 0.2 / (365 * 55 * 0.001))
        self.assertNotEqual(cpc.signature.period, concentration.signature.period)

    def test_exposure_refuses_unmatched_commodity(self):
        cpc_sig = IdentitySignature(country="GHA", commodity="maize", destination="Tamale", period="2014", unit="kg/person/year")
        concentration_sig = IdentitySignature(country="GHA", commodity="maize", material="grain", destination="Tamale", period="2014", unit="mg/kg-food")
        bw_sig = IdentitySignature(country="GHA", destination="Tamale", period="2014", unit="kg-bodyweight")
        rfd_sig = IdentitySignature(commodity="cadmium", unit="mg/kg-bodyweight/day")
        intake_sig = IdentitySignature(country="GHA", commodity="maize", material="cadmium", destination="Tamale", period="2014", unit="mg/kg-bodyweight/day")
        hq_sig = IdentitySignature(**{**intake_sig.__dict__, "unit": "HQ"})
        certificate = ExposureCertificate("EX-CERT", cpc_sig, concentration_sig, bw_sig, rfd_sig, intake_sig, hq_sig, 365, ("AUDIT",), "Exact join.")
        rice = IntervalMeasureClaim(IdentitySignature(**{**cpc_sig.__dict__, "commodity": "rice"}), 1, 2, ("CPC",))
        with self.assertRaisesRegex(ValueError, "cpc_signature"):
            propagate_contaminant_exposure(
                cpc=rice,
                concentration=IntervalMeasureClaim(concentration_sig, 0.1, 0.2, ("CHEM",)),
                body_weight=IntervalMeasureClaim(bw_sig, 55, 65, ("BW",)),
                reference_dose=IntervalMeasureClaim(rfd_sig, 0.001, 0.001, ("RFD",)),
                certificate=certificate,
            )

    def test_explicit_node_cpc_precedes_population_derivation(self):
        cpc_sig = IdentitySignature(
            country="GHA", commodity="maize", destination="Tamale", period="2025",
            denominator="resident consumers", unit="kg/person/year",
        )
        reported = IntervalMeasureClaim(cpc_sig, 12, 14, ("DIRECT-CPC-SOURCE",))
        certificate = DirectCPCCertificate(
            "DIRECT-CPC-CERT", cpc_sig, ("DIRECT-CPC-AUDIT",),
            "Explicit CPC reported for this exact node, product, period and denominator.",
        )
        result = resolve_node_cpc_claim(explicit_cpc=reported, direct_cpc_certificate=certificate)
        self.assertEqual((result.lower, result.upper), (12, 14))
        self.assertIn("DIRECT-CPC-CERT", result.certificate_ids)
        integrated = certified_scalar_cpc_payload(chemistry_certified=False)
        integrated["allocation"] = {
            "allocated_mass_lower_kg_year": 999999,
            "consumer_population": 1,
        }
        model_result = run_typed_model(integrated)
        self.assertEqual(model_result["recalculation"]["status"], "explicit_node_cpc_used")
        self.assertEqual(model_result["cpc_result"]["comparison"]["matched_cpc_lower"], 9)

        selected = latest_eligible_evidence(
            [
                {"signature": {**cpc_sig.__dict__, "period": "2018"}, "evidence_date": "2018-12-31", "value": 10},
                {"signature": {**cpc_sig.__dict__, "period": "2023"}, "evidence_date": "2023-12-31", "value": 12},
                {"signature": {**cpc_sig.__dict__, "period": "2026"}, "evidence_date": "2026-12-31", "value": 14},
            ],
            evidence_cutoff="2025-12-31",
            required_signature=IdentitySignature(**{**cpc_sig.__dict__, "period": ""}),
        )
        self.assertEqual(selected["record"]["value"], 12)
        self.assertFalse(selected["contemporaneousness_required"])

    def test_nearest_time_matching_is_independent_by_predictor_stream(self):
        required = IdentitySignature(country="GHA", commodity="maize", destination="Tamale", unit="kg/year")
        selected = nearest_compatible_evidence(
            [
                self._trend_record("2017", 100, "MASS-2017", required.__dict__),
                self._trend_record("2021", 120, "MASS-2021", required.__dict__),
            ],
            target_date="2020",
            required_signature=IdentitySignature(**{**required.__dict__, "period": ""}),
            require_certified=True,
        )
        self.assertEqual(selected["record"]["evidence_id"], "MASS-2021")
        self.assertEqual(selected["temporal_gap_days"], 1)
        self.assertEqual(selected["temporal_direction"], "after")
        with self.assertRaisesRegex(ValueError, "within 100 days"):
            nearest_compatible_evidence(
                [self._trend_record("2010", 100, "MASS-2010", required.__dict__)],
                target_date="2020",
                required_signature=IdentitySignature(**{**required.__dict__, "period": ""}),
                max_gap_days=100,
                require_certified=True,
            )

    def test_historical_trend_matches_nearest_mass_population_and_chemistry_dates(self):
        common = {"country": "GHA", "food_domain": "food", "commodity": "maize", "product_form": "edible grain", "destination": "Tamale"}
        mass_sig = {**common, "denominator": "destination allocation", "unit": "kg/year"}
        population_sig = {"country": "GHA", "destination": "Tamale", "denominator": "resident consumers", "unit": "persons"}
        chemistry_sig = {**common, "material": "grain", "denominator": "food mass", "unit": "mg/kg-food"}
        body_weight_sig = {"country": "GHA", "destination": "Tamale", "denominator": "exposed consumers", "unit": "kg-bodyweight"}
        reference_sig = {"country": "GHA", "commodity": "cadmium", "denominator": "reference dose", "unit": "mg/kg-bodyweight/day"}
        payload = {
            "temporal_trend": {
                "anchor_stream": "mass",
                "required_signature": common,
                "required_signatures": {
                    "mass": mass_sig,
                    "population": population_sig,
                    "chemistry": chemistry_sig,
                    "body_weight": body_weight_sig,
                    "reference_dose": reference_sig,
                },
                "mass_is_edible": True,
                "streams": {
                    "mass": [
                        self._trend_record("2018", 1000, "MASS-2018", mass_sig),
                        self._trend_record("2020", 1200, "MASS-2020", mass_sig),
                        self._trend_record("2022", 1500, "MASS-2022", mass_sig),
                    ],
                    "population": [
                        self._trend_record("2017", 100, "POP-2017", population_sig),
                        self._trend_record("2021", 120, "POP-2021", population_sig),
                    ],
                    "chemistry": [
                        self._trend_record("2019", 0.1, "CHEM-2019", chemistry_sig),
                        self._trend_record("2023", 0.3, "CHEM-2023", chemistry_sig),
                    ],
                    "body_weight": [self._trend_record("2020", 50, "BW-2020", body_weight_sig)],
                    "reference_dose": [self._trend_record("2010", 0.001, "RFD-2010", reference_sig)],
                },
            }
        }
        trend = run_temporal_trend(payload)
        self.assertEqual(trend["target_dates"], ["2018", "2020", "2022"])
        self.assertEqual(trend["point_count"], 3)
        first, middle, last = trend["points"]
        self.assertEqual(first["temporal_matches"]["population"]["selected_evidence_date"], "2017")
        self.assertEqual(middle["temporal_matches"]["population"]["selected_evidence_date"], "2021")
        self.assertEqual(last["temporal_matches"]["chemistry"]["selected_evidence_date"], "2023")
        self.assertAlmostEqual(first["cpc"]["lower"], 10.0)
        self.assertAlmostEqual(middle["cpc"]["lower"], 10.0)
        self.assertAlmostEqual(last["cpc"]["lower"], 12.5)
        self.assertAlmostEqual(first["estimated_daily_intake"]["lower"], 10 * 0.1 / (365 * 50))
        self.assertAlmostEqual(last["target_hazard_quotient"]["upper"], 12.5 * 0.3 / (365 * 50 * 0.001))
        self.assertEqual(last["status"], "mass_cpc_edi_thq_computed")
        self.assertFalse(last["calculation_certificate"]["contemporaneousness_required"])

    def test_temporal_trend_direct_cpc_precedes_mass_population_at_each_date(self):
        common = {"country": "GHA", "commodity": "maize", "destination": "Tamale"}
        mass_sig = {**common, "unit": "kg/year"}
        population_sig = {"country": "GHA", "destination": "Tamale", "unit": "persons"}
        cpc_sig = {**common, "denominator": "resident consumers", "unit": "kg/person/year"}
        result = run_typed_model({
            "temporal_trend": {
                "target_dates": ["2020"],
                "required_signature": common,
                "required_signatures": {"mass": mass_sig, "population": population_sig, "direct_cpc": cpc_sig},
                "mass_is_edible": True,
                "streams": {
                    "mass": [self._trend_record("2020", 1000, "MASS-2020", mass_sig)],
                    "population": [self._trend_record("2020", 100, "POP-2020", population_sig)],
                    "direct_cpc": [self._trend_record("2019", 7, "CPC-2019", cpc_sig)],
                },
            }
        })
        point = result["temporal_trend"]["points"][0]
        self.assertEqual(point["cpc"]["mode"], "nearest_certified_direct_node_cpc")
        self.assertEqual(point["cpc"]["lower"], 7)
        self.assertEqual(point["temporal_matches"]["direct_cpc"]["selected_evidence_date"], "2019")

    def test_derived_cpc_refuses_population_without_named_projection(self):
        mass_sig = IdentitySignature(country="GHA", commodity="maize", destination="Tamale", period="2025", unit="kg/year")
        pop_sig = IdentitySignature(country="GHA", destination="Tamale", period="2025", denominator="resident consumers", unit="persons")
        cpc_sig = IdentitySignature(country="GHA", commodity="maize", destination="Tamale", period="2025", denominator="resident consumers", unit="kg/person/year")
        allocation_certificate = CPCAllocationCertificate(
            "CPC-CERT", mass_sig, pop_sig, cpc_sig, 1, 1, ("JOIN",), "Exact node join.",
        )
        with self.assertRaisesRegex(ValueError, "population projection certificate"):
            derive_node_cpc_claim(
                allocated_mass=IntervalMeasureClaim(mass_sig, 1000, 1000, ("MASS",)),
                consumer_population=IntervalMeasureClaim(pop_sig, 100, 100, ("POP",)),
                population_certificate=None,
                certificate=allocation_certificate,
            )
        integrated = run_typed_model({
            "allocation": {
                "allocated_mass_lower_kg_year": 1000,
                "consumer_population": 100,
                "evidence_ids": ["MASS"],
            },
            "cpc": {"identified_lower": 8, "identified_upper": 12},
        })
        self.assertEqual(integrated["recalculation"]["status"], "blocked")
        self.assertEqual(integrated["calculation_certificate"]["node_cpc_resolution"]["mode"], "blocked_population_derivation")
        self.assertIn("population_projection certificate", integrated["recalculation"]["reason"])


if __name__ == "__main__":
    unittest.main()
