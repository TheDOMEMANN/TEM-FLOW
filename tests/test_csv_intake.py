import unittest

from temflow.csv_intake import convert_csv_text


class CsvIntakeTests(unittest.TestCase):
    def test_monitoring_and_od_rows_convert_without_inventing_blanks(self):
        text = (
            "layer,record_id,observed_at,origin,destination,reported_mass,unit,status,trigger,provenance\n"
            "od_evidence,OD-1,2026-01-31,A,B,12.5,kg/year,,,ledger page 4\n"
            "supply_continuity,SUP-1,2026-02-01,,, , ,warning,yes,field report\n"
        )
        result = convert_csv_text(text, filename="records.csv")
        private = result["private_layer_data"]
        self.assertEqual(result["row_count"], 2)
        self.assertEqual(private["od_evidence"][0]["reported_mass"], 12.5)
        self.assertNotIn("status", private["od_evidence"][0])
        self.assertTrue(private["supply_continuity"][0]["trigger"])

    def test_direct_cpc_row_builds_matching_certificate(self):
        text = (
            "layer,record_id,observed_at,identified_lower,identified_upper,measured_lower,measured_upper,"
            "country,food_domain,commodity,product_form,destination,period,denominator,unit,"
            "certificate_id,evidence_ids,claim_boundary\n"
            "cpc_compatibility,CPC-1,2025-12-31,8,12,9,11,GHA,food,maize,edible grain,Tamale,2025,"
            "resident consumers,kg/person/year,CERT-1,SURVEY-1;LEDGER-2,Exact node and product\n"
        )
        private = convert_csv_text(text)["private_layer_data"]
        cpc = private["cpc_compatibility"]
        certificate = private["certificates"]["direct_cpc"]
        self.assertEqual(cpc["signature"], certificate["signature"])
        self.assertEqual(certificate["evidence_ids"], ["SURVEY-1", "LEDGER-2"])
        self.assertEqual(certificate["status"], "certified")

    def test_exposure_row_converts_numeric_and_default_requested(self):
        text = (
            "layer,record_id,observed_at,source_node_id,retained_mass_lower_kg_year,"
            "retained_mass_upper_kg_year,consumer_population,concentration_mg_per_kg_food,"
            "body_weight_kg,reference_dose_mg_per_kg_day,declared_thq_threshold\n"
            "exposure_scenario,EXP-1,2026-03-05,NODE-1,100,120,5000,0.02,60,0.001,1\n"
        )
        exposure = convert_csv_text(text)["private_layer_data"]["exposure_scenario"]
        self.assertEqual(exposure["consumer_population"], 5000.0)
        self.assertTrue(exposure["requested"])

    def test_rejects_bad_date_unknown_column_negative_and_reversed_interval(self):
        cases = (
            ("layer,record_id,observed_at\nod_evidence,X,15/09/2026\n", "YYYY-MM-DD"),
            ("layer,record_id,observed_at,mystery\nod_evidence,X,2026-09-15,a\n", "unknown CSV columns"),
            ("layer,record_id,observed_at,value\nmarket_access,X,2026-09-15,-1\n", "non-negative"),
            ("layer,record_id,observed_at,lower,upper\npostharvest_loss,X,2026-09-15,5,4\n", "cannot exceed"),
        )
        for text, message in cases:
            with self.subTest(message=message), self.assertRaisesRegex(ValueError, message):
                convert_csv_text(text)

    def test_requires_records_and_one_object_row_per_layer(self):
        with self.assertRaisesRegex(ValueError, "no dated records"):
            convert_csv_text("layer,record_id,observed_at\n")
        text = (
            "layer,record_id,observed_at,requested\n"
            "exposure_scenario,A,2026-01-01,yes\n"
            "exposure_scenario,B,2026-01-02,yes\n"
        )
        with self.assertRaisesRegex(ValueError, "only one exposure_scenario"):
            convert_csv_text(text)


if __name__ == "__main__":
    unittest.main()
