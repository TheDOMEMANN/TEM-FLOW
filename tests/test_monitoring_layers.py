from __future__ import annotations

import unittest

from temflow.monitoring_layers import normalize_layer_selection, summarize_private_layers


class MonitoringLayerTests(unittest.TestCase):
    def test_explicit_selection_defaults_optional_layers_off(self):
        selection = normalize_layer_selection({"err": True, "market_access": True})
        self.assertTrue(selection["err"])
        self.assertTrue(selection["market_access"])
        self.assertFalse(selection["cpc_compatibility"])
        self.assertFalse(selection["contaminant_trace"])

    def test_private_monitoring_returns_counts_without_record_values(self):
        selection = normalize_layer_selection({"err": True, "market_access": True, "flow_irregularity": True})
        result = summarize_private_layers(
            selection,
            {
                "market_access": [{"node_id": "PRIVATE-1", "status": "alert", "value": 999}],
                "flow_irregularity": [],
            },
        )
        self.assertEqual(result["market_access"], {"status": "monitoring_active", "record_count": 1, "trigger_count": 1})
        self.assertEqual(result["flow_irregularity"]["status"], "awaiting_private_file")
        self.assertNotIn("value", str(result))


if __name__ == "__main__":
    unittest.main()
