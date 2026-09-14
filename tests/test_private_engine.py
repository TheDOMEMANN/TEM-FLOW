from __future__ import annotations

from temflow import __version__

from pathlib import Path
from tempfile import TemporaryDirectory
import json
import threading
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from temflow.private_engine import CATALOG, EngineServer, UI_PATH, VERSION, serve_private_engine


class PrivateEngineTests(unittest.TestCase):
    def test_catalog_contains_harmonized_and_geocoded_networks(self):
        self.assertEqual(VERSION, __version__)
        self.assertGreaterEqual(len(CATALOG.nodes), 3700)
        self.assertGreaterEqual(len(CATALOG.routes), 10600)
        self.assertTrue(any(node.get("lon") is not None for node in CATALOG.nodes.values()))
        self.assertTrue(all(route.get("from_name") and route.get("to_name") for route in CATALOG.routes.values()))
        self.assertEqual(len(CATALOG.waterbodies["features"]), 28)
        lake_names = {feature["properties"]["name"] for feature in CATALOG.waterbodies["features"]}
        self.assertTrue({"Lake Victoria", "Lake Tana", "Lake Ziway", "Lake Chamo", "Lake Nasser"} <= lake_names)
        self.assertTrue(all("not an ED-FLOW node" in feature["properties"]["geometry_role"] for feature in CATALOG.waterbodies["features"]))

    def test_continental_default_has_a_map_position_for_every_registered_object(self):
        self.assertTrue(all(node.get("map_lon") is not None and node.get("map_lat") is not None for node in CATALOG.nodes.values()))
        self.assertTrue(
            all(
                route.get("source_map_lon") is not None
                and route.get("source_map_lat") is not None
                and route.get("destination_map_lon") is not None
                and route.get("destination_map_lat") is not None
                for route in CATALOG.routes.values()
            )
        )
        proxies = [node for node in CATALOG.nodes.values() if "layout proxy" in str(node.get("map_position_kind", ""))]
        self.assertTrue(proxies)
        self.assertTrue(all(node.get("lon") is None and node.get("lat") is None for node in proxies))

    def test_cross_border_source_rows_are_quarantined_from_the_operational_network(self):
        self.assertEqual(len(CATALOG.routes), 17677)
        self.assertEqual(len(CATALOG.domestic_routes), 15428)
        self.assertEqual(len(CATALOG.verified_trade_routes), 1795)
        self.assertEqual(len(CATALOG.operational_routes), 17223)
        self.assertEqual(len(CATALOG.quarantined_cross_border_routes), 454)
        self.assertTrue(all(not route["network_eligible"] for route in CATALOG.quarantined_cross_border_routes.values()))
        self.assertTrue(
            all(
                route["network_eligible"]
                and route["origin_iso3"] == route["destination_iso3"]
                for route in CATALOG.domestic_routes.values()
            )
        )
        self.assertTrue(
            all(
                route["network_eligible"]
                and route["trade_eligible"]
                and route["origin_iso3"] != route["destination_iso3"]
                and float(str(route["quantity"]).replace(",", "")) > 0
                for route in CATALOG.verified_trade_routes.values()
            )
        )

    def test_route_queries_never_return_cross_border_rows(self):
        routes = CATALOG.query("route", {"limit": ["20000"]})
        self.assertEqual(routes["total"], 15428)
        self.assertTrue(all(route["origin_iso3"] == route["destination_iso3"] for route in routes["items"]))
        with_trade = CATALOG.query("route", {"include_trade": ["true"], "limit": ["20000"]})
        self.assertEqual(with_trade["total"], 17223)
        trade_rows = [route for route in with_trade["items"] if route["origin_iso3"] != route["destination_iso3"]]
        self.assertEqual(len(trade_rows), 1795)
        self.assertTrue(all(route["trade_eligible"] for route in trade_rows))

    def test_ethiopian_verified_topology_is_loaded_without_upgrading_evidence(self):
        ethiopian_nodes = CATALOG.query("node", {"country": ["ETH"], "limit": ["5000"]})
        ethiopian_routes = CATALOG.query("route", {"country": ["ETH"], "limit": ["20000"]})
        self.assertEqual(ethiopian_nodes["total"], 340)
        self.assertEqual(ethiopian_routes["total"], 604)
        self.assertTrue(all(node.get("map_lon") is not None for node in ethiopian_nodes["items"]))
        topology_routes = [route for route in ethiopian_routes["items"] if route["id"].startswith("ETHMAP_EDGE_")]
        self.assertEqual(len(topology_routes), 276)
        self.assertTrue(all(route["evidence_class"] for route in topology_routes))
        self.assertTrue(any("not measured flow" in route["evidence_class"] for route in topology_routes))

    def test_road_aligned_display_geometry_preserves_the_od_relation(self):
        payload = CATALOG.route_display_geometries({"country": ["ETH"], "limit": ["20000"]})
        self.assertGreater(payload["route_count"], 350)
        self.assertIn("ETH", payload["supported_countries"])
        self.assertGreaterEqual(len(payload["supported_countries"]), 50)
        self.assertIn("display only", payload["geometry_role"])
        self.assertIn("not evidence", payload["interpretive_boundary"])
        route_id = next(route_id for route_id in payload["route_paths"] if route_id.startswith("ETHMAP_EDGE_"))
        mapping = payload["route_paths"][route_id]
        self.assertIn(mapping["path_id"], payload["paths"])
        self.assertGreaterEqual(len(payload["paths"][mapping["path_id"]]["coordinates"]), 2)
        self.assertEqual(CATALOG.routes[route_id]["road_display_path_id"], mapping["path_id"])

    def test_generalized_road_alignment_is_available_across_continental_networks(self):
        for iso3 in ("BFA", "CMR", "GHA", "MLI"):
            payload = CATALOG.route_display_geometries({"country": [iso3], "limit": ["20000"]})
            self.assertGreater(payload["route_count"], 1000)
            self.assertTrue(all(value["country"] == iso3 for value in payload["route_paths"].values()))
        for iso3 in ("KEN", "MAR", "NGA", "ZAF", "ZWE"):
            payload = CATALOG.route_display_geometries({"country": [iso3], "limit": ["20000"]})
            self.assertGreater(payload["route_count"], 0)
            self.assertTrue(all(value["country"] == iso3 for value in payload["route_paths"].values()))

    def test_frozen_osm_reference_roads_cover_small_island_networks(self):
        for iso3 in ("CPV", "MUS", "SYC"):
            routes = CATALOG.query("route", {"country": [iso3], "limit": ["20000"]})
            payload = CATALOG.route_display_geometries({"country": [iso3], "limit": ["20000"]})
            self.assertGreaterEqual(payload["route_count"], sum(not row["id"].startswith("GEO_ROUTE_") for row in routes["items"]))
            self.assertTrue(any(rid.startswith("GEO_ROUTE_") for rid in payload["route_paths"]))
            self.assertTrue(all(value["country"] == iso3 for value in payload["route_paths"].values()))
            self.assertIn("OpenStreetMap/Overpass", payload["country_statistics"][iso3]["source"])

    def test_commodity_specific_fish_and_vegetable_routes_exist(self):
        domains = {route["food_domain"] for route in CATALOG.operational_routes.values()}
        self.assertTrue({"fish", "vegetable"} <= domains)
        self.assertTrue(any(route["commodity"] == "Fish" and route.get("source_lon") is not None for route in CATALOG.operational_routes.values()))
        self.assertTrue(any(route["commodity"] == "Tomato" and route.get("source_lon") is not None for route in CATALOG.operational_routes.values()))

    def test_ui_contains_required_history_and_save_controls(self):
        html = Path(UI_PATH).read_text(encoding="utf-8")
        for control in ('id="prev"', 'id="next"', 'id="save"', 'id="run"', 'id="countries"', 'id="commodities"', 'id="tradeOverlay"', 'id="roadAlignment"', 'id="showLakes"', 'id="showNodeLabels"', 'id="showRouteLabels"', 'id="objectCallout"'):
            self.assertIn(control, html)
        self.assertIn("Save new dated entry", html)
        self.assertIn("View date", html)
        self.assertIn("Refresh view · latest", html)

    def test_ui_exposes_opt_in_exposure_animation_at_version_1_0_0(self):
        html = Path(UI_PATH).read_text(encoding="utf-8")
        self.assertIn(f'v{VERSION}</span>', html)
        self.assertNotIn('v1.2.0</span>', html)
        for control in (
            'id="massBasis"',
            'id="populationBasis"',
            'id="chemistryBasis"',
            'id="thqThreshold"',
            'id="showExposure"',
            'id="exposureBanner"',
        ):
            self.assertIn(control, html)
        self.assertIn("toggleExposureAnimation", html)
        self.assertIn("drawExposureOverlay", html)
        self.assertIn("Scenario visualization; route pulses do not establish contaminant transport.", html)

    def test_ui_aggregates_continental_routes_and_exposes_map_navigation(self):
        html = Path(UI_PATH).read_text(encoding="utf-8")
        for control in (
            'id="panWest"',
            'id="panNorth"',
            'id="panSouth"',
            'id="panEast"',
            'id="zoomIn"',
            'id="zoomOut"',
            'id="fitActive"',
            'id="resetMap"',
            'id="tradeCallout"',
            'id="closeTradeCallout"',
            'id="openTradeRoutes"',
        ):
            self.assertIn(control, html)
        self.assertIn("continentalOverviewRoutes", html)
        self.assertNotIn("cross_border_aggregate", html)
        self.assertNotIn("country-pair overview", html)
        self.assertIn("verified_trade_aggregate", html)
        self.assertIn("National networks are always shown first", html)
        self.assertIn("positive-quantity customs or observed OD records", html)
        self.assertIn("include_trade", html)
        self.assertIn("fitActiveMap", html)
        self.assertIn("function tradeTransactions(route)", html)
        self.assertIn("function showTradeCallout(route,event={})", html)
        self.assertIn("Reported quantity", html)
        self.assertIn("Evidence class", html)
        self.assertIn("Provenance", html)
        self.assertIn("addEventListener('wheel'", html)
        self.assertIn("addEventListener('pointermove'", html)
        self.assertIn("function panMap(horizontal=0,vertical=0)", html)
        self.assertIn("Math.hypot(dx,dy)<5", html)
        self.assertIn("suppressMapClickUntil", html)
        self.assertNotIn("event.target!==map", html)
        self.assertIn("function roadPathFor(route)", html)
        self.assertIn("function compactAlias(value,context={})", html)
        self.assertIn("function abbreviateMapAlias(value,context={},maxChars=16)", html)
        self.assertIn("function routeLabelAlias(route)", html)
        self.assertNotIn("function routeLabelGuidePath(coordinates,a,b)", html)
        self.assertNotIn("svgEl('textPath'", html)
        self.assertIn("labelTransform=`rotate(${labelPoint.angle.toFixed(1)}", html)
        self.assertIn("label.textContent=labelAlias", html)
        self.assertIn("class:'route-label-hit'", html)
        self.assertIn("data-hit-id", html)
        self.assertIn(".route-label{paint-order:normal;stroke:none}", html)
        self.assertIn(".road-casing{display:none}.node-label,.lake-label{paint-order:normal;stroke:none}", html)
        self.assertNotIn("white-cased curves", html)
        self.assertIn('class="object-list-scroll" aria-label="Scrollable full node names"', html)
        self.assertIn('class="object-list-scroll" aria-label="Scrollable full route names"', html)
        self.assertIn(".object-list-scroll{width:100%;overflow-x:auto", html)
        self.assertIn("function pathLabelPoint(coordinates,a,b)", html)
        self.assertIn("function showObjectCallout(kind,id,event={})", html)
        self.assertIn(".route-label.fish-route-label", html)
        self.assertIn("Map labels are compact aliases only", html)
        self.assertIn("/api/waterbodies", html)
        self.assertIn("/api/route-display-geometries?", html)
        self.assertIn("Display context only—not evidence of the shipment path", html)
        self.assertIn("road=!tradeAggregate?roadPathFor(route):null", html)
        self.assertNotIn("!tradeAggregate&&!overviewMode?roadPathFor(route):null", html)
        self.assertNotIn("!routesAreScoped())", html)

    def test_map_controls_use_a_compact_horizontal_top_strip(self):
        html = Path(UI_PATH).read_text(encoding="utf-8")
        self.assertIn(
            ".map-controls{position:absolute;z-index:5;right:10px;top:10px;display:flex;align-items:center",
            html,
        )
        self.assertIn(".map-controls .wide{min-width:auto;font-size:10.5px}", html)
        self.assertNotIn(".map-controls{position:absolute;z-index:5;right:10px;top:10px;display:grid", html)

    def test_ui_exposes_all_first_and_scopes_model_runs(self):
        html = Path(UI_PATH).read_text(encoding="utf-8")
        self.assertIn("const ALL='__ALL__'", html)
        self.assertIn('value="__ALL__" checked> ALL', html)
        self.assertIn('`<option value="${ALL}">ALL</option>`', html)
        self.assertIn("scope:activeScope()", html)
        self.assertIn("ALL displayed as a legible non-duplicative overview", html)
        self.assertIn('id="commodityGroups"', html)
        self.assertIn('aria-label="Selectable nodes" multiple', html)
        self.assertIn('aria-label="Selectable routes" multiple', html)
        self.assertIn("Map legend, navigation and geometry interpretation", html)
        self.assertIn("Run workflow — include only the layers needed", html)
        self.assertIn("Run selected workflow", html)
        self.assertIn("/api/err/run", html)
        self.assertIn('id="countryInventory"', html)
        self.assertIn('id="showNodes" type="checkbox" checked', html)
        self.assertIn('id="showRoutes" type="checkbox" checked', html)
        self.assertIn('id="showNodeLabels" type="checkbox"> Node labels', html)
        self.assertIn('id="showRouteLabels" type="checkbox"> Route labels', html)
        self.assertNotIn('id="showNodeLabels" type="checkbox" checked', html)
        self.assertNotIn('id="showRouteLabels" type="checkbox" checked', html)
        self.assertIn('id="showLakes" type="checkbox" checked', html)
        self.assertIn('id="roadAlignment" type="checkbox" checked', html)
        self.assertIn('id="showProxyNodes" type="checkbox"', html)
        self.assertNotIn('id="showProxyNodes" type="checkbox" checked', html)
        self.assertIn('id="viewSummary"', html)
        self.assertIn(".route.overview{stroke-width:.8;stroke-opacity:.32}", html)
        self.assertIn(".road-casing{fill:none", html)
        self.assertIn("country-layout proxies", html)
        self.assertIn("state.routes=state.routeOptions", html)
        self.assertIn("$('routePanel').open=true", html)

    def test_audited_ziway_coordinate_replaces_proxy_and_child_inherits_it(self):
        ziway = CATALOG.nodes["ETH-N-LAKE-ZIWAY-4AD5F37"]
        commodity_child = CATALOG.nodes["ETH-M-UNSPECIFIED-FISH-COMMO-7EB0CC9E8"]
        self.assertAlmostEqual(ziway["lat"], 7.9877798)
        self.assertAlmostEqual(ziway["lon"], 38.8200713)
        self.assertIn("audited", ziway["map_position_kind"])
        self.assertEqual((commodity_child["lat"], commodity_child["lon"]), (ziway["lat"], ziway["lon"]))
        self.assertIn("inherited audited parent", commodity_child["map_position_kind"])

    def test_map_selection_is_double_click_and_escape_clears_state(self):
        html = Path(UI_PATH).read_text(encoding="utf-8")
        self.assertIn("path.ondblclick=event=>selectCountryFromMap", html)
        self.assertIn("circle.ondblclick=event=>selectObject", html)
        self.assertNotIn("circle.onclick=event=>selectObject", html)
        self.assertIn("event.button===2?'zoom':'pan'", html)
        self.assertIn("addEventListener('contextmenu'", html)
        self.assertIn("state.selectedNodeIds=[];state.selectedRouteIds=[]", html)

    def test_ui_exposes_explicit_model_layers_and_private_file_slot(self):
        html = Path(UI_PATH).read_text(encoding="utf-8")
        for control in (
            'id="layerErr" type="checkbox" checked', 'id="layerCpc" type="checkbox"',
            'id="layerContaminant" type="checkbox"', 'id="layerExposure" type="checkbox"',
            'id="layerMarketAccess" type="checkbox"', 'id="layerFlowIrregularity" type="checkbox"',
            'id="layerPostharvest" type="checkbox"', 'id="layerSupply" type="checkbox"',
            'id="layerPrice" type="checkbox"', 'id="privateLayerFile" type="file"',
        ):
            self.assertIn(control, html)
        self.assertIn("layers:selectedLayerPayload()", html)
        self.assertIn("private_layer_data:state.privateLayerData", html)

    def test_frozen_contaminant_ledger_is_explicitly_linked_without_propagation(self):
        if CATALOG.evidence_access_mode == "external_file_on_demand":
            self.assertEqual(len(CATALOG.evidence_records), 0)
            return
        self.assertEqual(len(CATALOG.evidence_records), 228)
        linked_nodes = [node for node in CATALOG.nodes.values() if node.get("evidence_record_count")]
        linked_routes = [route for route in CATALOG.operational_routes.values() if route.get("evidence_record_count")]
        self.assertTrue(linked_nodes)
        self.assertTrue(linked_routes)
        trace = CATALOG.evidence_trace("node", linked_nodes[0]["id"])
        self.assertEqual(trace["status"], "linked_records_available")
        self.assertTrue(trace["records"])
        self.assertIn("not propagated", trace["boundary"])

    def test_all_filter_is_an_open_scope(self):
        all_nodes = CATALOG.query("node", {"limit": ["5000"]})
        explicit_all_nodes = CATALOG.query("node", {"domain": ["__ALL__"], "commodity": ["ALL"], "limit": ["5000"]})
        all_routes = CATALOG.query("route", {"limit": ["20000"]})
        explicit_all_routes = CATALOG.query("route", {"country": ["*"], "limit": ["20000"]})
        self.assertEqual(explicit_all_nodes["total"], all_nodes["total"])
        self.assertEqual(explicit_all_routes["total"], all_routes["total"])

    def test_food_domain_filter_excludes_incompatible_items(self):
        fish_nodes = CATALOG.query("node", {"domain": ["fish"], "limit": ["5000"]})["items"]
        fish_routes = CATALOG.query("route", {"domain": ["fish"], "limit": ["20000"]})["items"]
        vegetable_routes = CATALOG.query("route", {"domain": ["vegetable"], "limit": ["20000"]})["items"]
        self.assertTrue(fish_nodes)
        self.assertTrue(fish_routes)
        self.assertTrue(vegetable_routes)
        self.assertTrue(all("fish" in node["food_domains"] for node in fish_nodes))
        self.assertTrue(all("fish" in route["food_domains"] for route in fish_routes))
        self.assertTrue(all("vegetable" in route["food_domains"] for route in vegetable_routes))

    def test_commodity_groups_are_compact_and_filter_model_objects(self):
        finfish_routes = CATALOG.query("route", {"commodity_group": ["Finfish"], "limit": ["20000"]})["items"]
        tomato_nodes = CATALOG.query("node", {"commodity_group": ["Tomato"], "limit": ["5000"]})["items"]
        self.assertTrue(finfish_routes)
        self.assertTrue(tomato_nodes)
        self.assertTrue(all("Finfish" in route["commodity_groups"] for route in finfish_routes))
        self.assertTrue(all("Tomato" in node["commodity_groups"] for node in tomato_nodes))

    def test_remote_binding_requires_private_tokens(self):
        with TemporaryDirectory() as directory:
            with patch.dict("os.environ", {"TEMFLOW_VIEW_TOKEN": "", "TEMFLOW_CURATOR_TOKEN": ""}):
                with self.assertRaises(ValueError):
                    serve_private_engine("0.0.0.0", 0, directory, open_browser=False, view_token=None, curator_token=None)

    def test_viewer_can_run_read_endpoints_but_cannot_write(self):
        with TemporaryDirectory() as directory:
            server = EngineServer(("127.0.0.1", 0), Path(directory), "reviewer-secret", "author-secret")
            worker = threading.Thread(target=server.serve_forever, daemon=True)
            worker.start()
            base = f"http://127.0.0.1:{server.server_port}"
            try:
                viewer = Request(f"{base}/api/metadata", headers={"X-TEMFLOW-Token": "reviewer-secret"})
                with urlopen(viewer, timeout=5) as response:
                    self.assertEqual(response.status, 200)
                    self.assertIn(b'"can_curate":false', response.read())

                unauthorized_write = Request(
                    f"{base}/api/revisions",
                    data=b"{}",
                    method="POST",
                    headers={"Content-Type": "application/json", "X-TEMFLOW-Token": "reviewer-secret"},
                )
                with self.assertRaises(HTTPError) as denied:
                    urlopen(unauthorized_write, timeout=5)
                self.assertEqual(denied.exception.code, 403)

                curator = Request(f"{base}/api/metadata", headers={"X-TEMFLOW-Token": "author-secret"})
                with urlopen(curator, timeout=5) as response:
                    self.assertEqual(response.status, 200)
                    self.assertIn(b'"can_curate":true', response.read())
            finally:
                server.shutdown()
                server.server_close()
                worker.join(timeout=5)

    def test_model_run_accepts_on_demand_private_exposure_and_monitoring_file(self):
        with TemporaryDirectory() as directory:
            server = EngineServer(("127.0.0.1", 0), Path(directory), "reviewer-secret", "author-secret")
            worker = threading.Thread(target=server.serve_forever, daemon=True)
            worker.start()
            base = f"http://127.0.0.1:{server.server_port}"
            node_id = "ETH-N-LAKE-ZIWAY-4AD5F37"
            payload = {
                "node_id": node_id,
                "selected_node_ids": [node_id],
                "scope": {"countries": ["ETH"]},
                "layers": {"exposure_scenario": True, "market_access": True},
                "private_layer_data": {
                    "exposure_scenario": {
                        "source_node_id": node_id,
                        "retained_mass_lower_kg_year": 3650,
                        "retained_mass_upper_kg_year": 7300,
                        "consumer_population": 100,
                        "concentration_mg_per_kg_food": 0.2,
                        "body_weight_kg": 50,
                        "reference_dose_mg_per_kg_day": 0.0001,
                        "declared_thq_threshold": 1,
                        "population_basis": "projected",
                        "mass_basis": "modelled",
                        "chemistry_basis": "last_reported",
                    },
                    "market_access": [{"node_id": node_id, "status": "alert", "private_value": 9}],
                },
            }
            try:
                request = Request(
                    f"{base}/api/model/run",
                    data=json.dumps(payload).encode("utf-8"),
                    method="POST",
                    headers={"Content-Type": "application/json", "X-TEMFLOW-Token": "reviewer-secret"},
                )
                with urlopen(request, timeout=5) as response:
                    result = json.loads(response.read())
                self.assertEqual(result["exposure_scenario"]["status"], "threshold_exceeded_across_interval")
                self.assertTrue(result["exposure_scenario"]["display_available"])
                self.assertEqual(result["monitoring_layers"]["market_access"]["trigger_count"], 1)
                self.assertNotIn("private_value", json.dumps(result["monitoring_layers"]))
                self.assertEqual(result["cpc_result"]["status"], "excluded_by_user")
            finally:
                server.shutdown()
                server.server_close()
                worker.join(timeout=5)

    def test_model_run_uses_typed_claim_operator_and_blocks_qualitative_chemistry(self):
        with TemporaryDirectory() as directory:
            server = EngineServer(("127.0.0.1", 0), Path(directory), "reviewer-secret", "author-secret")
            worker = threading.Thread(target=server.serve_forever, daemon=True)
            worker.start()
            base = f"http://127.0.0.1:{server.server_port}"
            route_id = "ATT-SPATIAL-TO-MASS-STATE-575EA66BC"
            payload = {
                "route_id": route_id,
                "selected_route_ids": [route_id],
                "as_of": "2026-08-30",
                "scope": {},
                "allocation": {},
                "cpc": {},
                "exposure_scenario": {
                    "requested": True,
                    "source_node_id": CATALOG.operational_routes[route_id]["from_node_id"],
                    "retained_mass_lower_kg_year": 3650,
                    "retained_mass_upper_kg_year": 7300,
                    "consumer_population": 100,
                    "concentration_mg_per_kg_food": 0.2,
                    "body_weight_kg": 50,
                    "reference_dose_mg_per_kg_day": 0.0001,
                    "declared_thq_threshold": 1,
                    "population_basis": "projected",
                    "mass_basis": "modelled",
                    "chemistry_basis": "last_reported",
                },
            }
            try:
                request = Request(
                    f"{base}/api/model/run",
                    data=json.dumps(payload).encode("utf-8"),
                    method="POST",
                    headers={"Content-Type": "application/json", "X-TEMFLOW-Token": "reviewer-secret"},
                )
                with urlopen(request, timeout=5) as response:
                    result = json.loads(response.read())
                self.assertEqual(result["engine_version"], VERSION)
                self.assertEqual(result["evidence_resolved_reconstruction"]["status"], "not_requested")
                self.assertEqual(result["temflow_claims"][0]["operator"], "TEM_ADMISSIBLE_CLAIM_V0_3")
                expected_records = 1 if CATALOG.evidence_access_mode == "bundled_editor_private" else 0
                self.assertEqual(result["contaminant_trace"]["record_count"], expected_records)
                if expected_records:
                    self.assertTrue(result["blocked_evidence"])
                self.assertEqual(result["cpc_result"]["alarm_projection"]["status"], "not_computable")
                self.assertEqual(result["exposure_scenario"]["status"], "threshold_exceeded_across_interval")
                self.assertTrue(result["exposure_scenario"]["display_available"])
                self.assertEqual(result["exposure_scenario"]["map"]["route_ids"], [route_id])
                self.assertEqual(result["exposure_scenario"]["inputs"]["evidence_basis"]["population"], "projected")
                temporal = result["calculation_certificate"]["temporal_selection"]
                self.assertFalse(temporal["contemporaneousness_required"])
                self.assertEqual(temporal["analysis_reference_date"], "2026-08-30")

                bare_population_payload = {
                    **payload,
                    "allocation": {
                        "allocated_mass_lower_kg_year": 1000,
                        "consumer_population": 100,
                        "evidence_ids": ["TEST-MASS"],
                    },
                    "cpc": {"identified_lower": 8, "identified_upper": 12},
                }
                bare_request = Request(
                    f"{base}/api/model/run",
                    data=json.dumps(bare_population_payload).encode("utf-8"),
                    method="POST",
                    headers={"Content-Type": "application/json", "X-TEMFLOW-Token": "reviewer-secret"},
                )
                with urlopen(bare_request, timeout=5) as response:
                    bare_result = json.loads(response.read())
                self.assertEqual(bare_result["model_steps"]["cpc_recalculation"]["status"], "blocked")
                self.assertEqual(
                    bare_result["calculation_certificate"]["node_cpc_resolution"]["mode"],
                    "blocked_population_derivation",
                )

                trend_signature = {
                    "country": "TCD",
                    "commodity": "fish",
                    "destination": "N'Djamena",
                    "denominator": "resident consumers",
                    "unit": "kg/person/year",
                }
                trend_payload = {
                    **payload,
                    "temporal_trend": {
                        "target_dates": ["2020"],
                        "required_signatures": {"direct_cpc": trend_signature},
                        "streams": {
                            "direct_cpc": [{
                                "status": "certified",
                                "period": "2019",
                                "value": 2.5,
                                "evidence_id": "TCD-CPC-2019",
                                "signature": {**trend_signature, "period": "2019"},
                            }],
                        },
                    },
                }
                trend_request = Request(
                    f"{base}/api/model/run",
                    data=json.dumps(trend_payload).encode("utf-8"),
                    method="POST",
                    headers={"Content-Type": "application/json", "X-TEMFLOW-Token": "reviewer-secret"},
                )
                with urlopen(trend_request, timeout=5) as response:
                    trend_result = json.loads(response.read())
                self.assertEqual(trend_result["temporal_trend"]["point_count"], 1)
                self.assertEqual(trend_result["temporal_trend"]["points"][0]["cpc"]["lower"], 2.5)
                self.assertEqual(
                    trend_result["temporal_trend"]["points"][0]["temporal_matches"]["direct_cpc"]["selected_evidence_date"],
                    "2019",
                )
            finally:
                server.shutdown()
                server.server_close()
                worker.join(timeout=5)

    def test_err_api_runs_full_polytope_and_never_zero_fills_uncertified_routes(self):
        with TemporaryDirectory() as directory:
            server = EngineServer(("127.0.0.1", 0), Path(directory), "reviewer-secret", "author-secret")
            worker = threading.Thread(target=server.serve_forever, daemon=True)
            worker.start()
            base = f"http://127.0.0.1:{server.server_port}"
            payload = {
                "variable_names": ["route-certified", "route-latent"],
                "lower": [0, 0],
                "upper": [None, None],
                "A_eq": [[1, 1]],
                "b_eq": [10],
                "certified_mask": [True, False],
                "certificate_ids_by_coordinate": {"route-certified": ["CERT-ROUTE-1"]},
                "known_total": 10,
            }
            try:
                request = Request(
                    f"{base}/api/err/run",
                    data=json.dumps(payload).encode("utf-8"),
                    method="POST",
                    headers={"Content-Type": "application/json", "X-TEMFLOW-Token": "reviewer-secret"},
                )
                with urlopen(request, timeout=5) as response:
                    result = json.loads(response.read())
                self.assertEqual(result["algorithm"], "TEMFLOW_ERR_V1_1")
                latent = next(row for row in result["coordinates"] if row["variable"] == "route-latent")
                self.assertEqual(latent["neutral_interval"], [0.0, 10.0])
                self.assertEqual(latent["named_report_status"], "blocked_unresolved_identity")
                self.assertEqual(result["operational_projection"]["status"], "not_requested")
            finally:
                server.shutdown()
                server.server_close()
                worker.join(timeout=5)


if __name__ == "__main__":
    unittest.main()

