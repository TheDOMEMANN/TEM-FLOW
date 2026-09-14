import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from temflow.dashboard import append_topology, calculate_scenario, effective_map_data, load_map_data, temporal_snapshot


class DashboardTests(unittest.TestCase):
    def payload(self):
        return {
            "source": "Lake A",
            "commodity": "fish / tilapia",
            "production_tonnes": 100,
            "coverage_lower": 0.5,
            "edible_fraction": 0.5,
            "concentration_mg_kg": 0.03,
            "body_weight_kg": 55,
            "slope_factor": 0.34,
            "destinations": [
                {"name": "Local", "pop": 10000, "time": 1, "market": 0.5, "tradition": 1, "route": 1, "q": 0.7, "reachable": True},
                {"name": "City", "pop": 100000, "time": 4, "market": 1, "tradition": 0.1, "route": 1, "q": 0.3, "reachable": True},
            ],
        }

    def test_reference_closes_inside_bounds(self):
        result = calculate_scenario(self.payload())
        self.assertAlmostEqual(sum(row["share_reference"] for row in result["destinations"]), 1.0)
        for row in result["destinations"]:
            self.assertGreaterEqual(row["share_reference"], row["share_lower"] - 1e-10)
            self.assertLessEqual(row["share_reference"], row["share_upper"] + 1e-10)

    def test_exposure_is_scenario_specific(self):
        result = calculate_scenario(self.payload())
        self.assertGreater(result["destinations"][0]["cancer_risk_reference"], 0)

    def test_unreachable_destination_is_structural_zero(self):
        payload = self.payload()
        payload["destinations"][1]["reachable"] = False
        result = calculate_scenario(payload)
        self.assertEqual(result["destinations"][1]["share_reference"], 0)

    def test_geographic_map_registers_are_complete(self):
        data = load_map_data()
        self.assertEqual(len(data["corridors"]), 15)
        self.assertGreaterEqual(len(data["nodes"]), 100)
        self.assertGreaterEqual(len(data["sources"]), 30)
        self.assertGreaterEqual(len(data["edges"]), 200)
        ids = {item["id"] for item in data["nodes"] + data["sources"]}
        self.assertFalse({edge[key] for edge in data["edges"] for key in ("from", "to")} - ids)
        self.assertEqual(len(data["regional_context"]["features"]), 9)
        self.assertEqual(
            {feature["properties"]["iso_a3"] for feature in data["regional_context"]["features"]},
            {"ETH", "SOM", "KEN", "DJI", "ERI", "SSD", "SDN", "YEM", "SAU"},
        )
        self.assertEqual(data["regional_context_sources"]["provider"], "geoBoundaries gbOpen ADM0")
        source_register = {row["iso_a3"]: row for row in data["regional_context_sources"]["countries"]}
        self.assertEqual(set(source_register), {"ETH", "SOM", "KEN", "DJI", "ERI", "SSD", "SDN", "YEM", "SAU"})
        self.assertIn("OCHA Somalia", source_register["SOM"]["boundary_source"])
        regional_ethiopia = next(
            feature for feature in data["regional_context"]["features"] if feature["properties"]["iso_a3"] == "ETH"
        )
        self.assertEqual(data["boundary"]["features"][0]["geometry"], regional_ethiopia["geometry"])
        self.assertIn("Red Sea", {label["name"] for label in data["regional_labels"]})
        self.assertEqual(data["bounds"], [30.0, -2.0, 53.0, 19.0])
        somalia = next(feature for feature in data["regional_context"]["features"] if feature["properties"]["name"] == "Somalia")
        points = []

        def collect_coordinates(value):
            if isinstance(value, list) and len(value) >= 2 and all(isinstance(item, (int, float)) for item in value[:2]):
                points.append(value)
            elif isinstance(value, list):
                for item in value:
                    collect_coordinates(item)

        collect_coordinates(somalia["geometry"]["coordinates"])
        self.assertLess(min(point[1] for point in points), -1.6)
        somalia_label = next(label for label in data["regional_labels"] if label["name"] == "Somalia")
        self.assertGreater(somalia_label["lon"], 48.0)
        self.assertLess(somalia_label["lat"], 7.0)

    def test_lake_koka_has_registered_directed_path_to_addis(self):
        data = load_map_data()
        edges = {(edge["from"], edge["to"], edge["corridor_id"]) for edge in data["edges"]}
        self.assertIn(("KOKA_RES", "KOKA_TOWN", "C_RIFT_ADDIS"), edges)
        self.assertIn(("KOKA_TOWN", "MODJO", "C_RIFT_ADDIS"), edges)
        self.assertIn(("MODJO", "DUKEM", "C_RIFT_ADDIS"), edges)
        self.assertIn(("DUKEM", "BISHOFTU", "C_RIFT_ADDIS"), edges)
        self.assertIn(("BISHOFTU", "ADDIS", "C_RIFT_ADDIS"), edges)
        self.assertIn(("KOKA_RES", "BOTE_ALEM_TENA", "C_RIFT_ADDIS"), edges)
        self.assertIn(("MODJO", "ADAMA", "C_RIFT_ADDIS"), edges)
        self.assertIn(("ADAMA", "ASELA", "C_RIFT_ADDIS"), edges)
        koka = next(source for source in data["sources"] if source["id"] == "KOKA_RES")
        self.assertEqual(koka["branch_scope"]["C_RIFT_ADDIS"], [1, 7, 10, 11])

    def test_beseka_source_keeps_realized_catch_separate_from_modeled_potential(self):
        data = load_map_data()
        beseka = next(source for source in data["sources"] if source["id"] == "BESEKA_LAKE")
        self.assertIn("Realized catch unquantified", beseka["quantity_status"])
        self.assertIn("tilapia", beseka["source_class"].lower())
        self.assertIn("catfish", beseka["source_class"].lower())
        edges = {(edge["from"], edge["to"]) for edge in data["edges"]}
        self.assertIn(("BESEKA_LAKE", "METEHARA"), edges)
        self.assertIn(("BESEKA_LAKE", "AWASH_ARBA"), edges)
        self.assertIn(("METEHARA", "WONJI"), edges)

    def test_afar_terminal_lake_clusters_are_registered_sources(self):
        data = load_map_data()
        sources = {source["id"]: source for source in data["sources"]}
        self.assertIn("Gamery", sources["TEND_AWASH"]["name"])
        self.assertEqual(sources["TEND_AWASH"]["branch_scope"]["C_EASTERN_AWASH"], [1, 4])
        abhe_afambo = sources["ABHE_AFAMBO_CLUSTER"]
        self.assertIn("Abhe", abhe_afambo["name"])
        self.assertIn("Afambo", abhe_afambo["name"])
        self.assertEqual(abhe_afambo["coordinate_status"], "representative cluster centroid")
        self.assertEqual(abhe_afambo["branch_scope"]["C_EASTERN_AWASH"], [1, 4, 14])
        edges = {(edge["from"], edge["to"], edge["corridor_id"]) for edge in data["edges"]}
        self.assertIn(("ABHE_AFAMBO_CLUSTER", "ASAYITA", "C_EASTERN_AWASH"), edges)

    def test_ziway_and_langano_routes_include_local_centres_and_addis(self):
        data = load_map_data()
        nodes = {node["id"]: node for node in data["nodes"]}
        self.assertEqual(nodes["BATU_ZIWAY"]["tier"], "HIGH_LOCAL_CULTURAL")
        self.assertEqual(nodes["MEKI"]["tier"], "HIGH_LOCAL_CULTURAL")
        self.assertIn("ADAMI_TULU", nodes)
        self.assertIn("BULBULA", nodes)
        edges = {(edge["from"], edge["to"], edge["branch"]) for edge in data["edges"] if edge["corridor_id"] == "C_RIFT_ADDIS"}
        for expected in {
            ("ZIWAY_LAKE", "BATU_ZIWAY", 4),
            ("BATU_ZIWAY", "MEKI", 4),
            ("BISHOFTU", "ADDIS", 4),
            ("BATU_ZIWAY", "ADAMI_TULU", 14),
            ("ARSI_NEGELE", "SHASHEMENE", 14),
            ("MODJO", "ADAMA", 16),
            ("MEKI", "BUTAJIRA", 17),
            ("LANGANO_LAKE_CHILD", "BULBULA", 5),
            ("BISHOFTU", "ADDIS", 5),
            ("ARSI_NEGELE", "SHASHEMENE", 15),
        }:
            self.assertIn(expected, edges)
        ziway = next(source for source in data["sources"] if source["id"] == "ZIWAY_LAKE")
        langano = next(source for source in data["sources"] if source["id"] == "LANGANO_LAKE_CHILD")
        self.assertEqual(ziway["branch_scope"]["C_RIFT_ADDIS"], [4, 14, 16, 17])
        self.assertEqual(langano["branch_scope"]["C_RIFT_ADDIS"], [5, 15])
        self.assertEqual(ziway["branch_scope"]["C_SOUTHWEST_MULTI"], [])
        self.assertEqual(langano["branch_scope"]["C_SOUTHWEST_MULTI"], [])

    def test_ziway_reported_share_retains_matched_denominator_bounds(self):
        snapshot = temporal_snapshot("2020-12-31T23:59:59Z", "observed")
        record = next(row for row in snapshot["records"] if row["record_id"] == "ZIWAY_ADDIS_TOTAL_SHARE_2018")
        self.assertAlmostEqual(record["metadata"]["share_lower"], 0.4067293925)
        self.assertAlmostEqual(record["metadata"]["share_upper"], 0.4147064839)
        self.assertEqual(record["metadata"]["measurement_basis"], "total_source_share")

    def test_melka_wakena_is_scoped_to_its_candidate_market_branches(self):
        data = load_map_data()
        source = next(item for item in data["sources"] if item["id"] == "MELKA_WAKENA_RES")
        self.assertEqual(source["label"], "M-Wakena Res.")
        self.assertEqual(source["name"], "Melka-Wakena Reservoir")
        self.assertEqual(source["branch_scope"]["C_EASTERN_AWASH"], [3, 9, 10, 11])
        edges = {(edge["from"], edge["to"]) for edge in data["edges"]}
        for expected in {
            ("MELKA_WAKENA_RES", "GOBA_BALE"),
            ("GOBA_BALE", "ROBE_BALE"),
            ("MELKA_WAKENA_RES", "BEKOJI"),
            ("BEKOJI", "ASELA"),
            ("MELKA_WAKENA_RES", "ASASA"),
            ("DODOLA", "KOFELE"),
        }:
            self.assertIn(expected, edges)

    def test_genale_dawa_iii_reservoir_negele_and_bale_market_branches_are_registered(self):
        data = load_map_data()
        sources = {source["id"]: source for source in data["sources"]}
        source = sources["GENALE_DAWA_RES_SYSTEM"]
        self.assertEqual(source["name"], "Genale–Dawa III Reservoir")
        self.assertEqual(source["source_class"], "Reservoir fishery source")
        self.assertAlmostEqual(source["lat"], 5.714526, places=6)
        self.assertAlmostEqual(source["lon"], 39.674077, places=6)
        self.assertEqual(source["coordinate_status"], "user-verified")
        self.assertEqual(source["branch_scope"]["C_GENALE_DAWA"], [1, 2])
        self.assertIn("unquantified", source["quantity_status"].lower())
        nodes = {node["id"]: node for node in data["nodes"]}
        self.assertEqual(nodes["NEGELE_BORANA"]["name"], "Negele Borana")
        edges = {(edge["from"], edge["to"], edge["corridor_id"]) for edge in data["edges"]}
        self.assertIn(("GENALE_DAWA_RES_SYSTEM", "NEGELE_BORANA", "C_GENALE_DAWA"), edges)
        self.assertIn(("GENALE_DAWA_RES_SYSTEM", "GOBA_BALE", "C_GENALE_DAWA"), edges)
        self.assertIn(("GOBA_BALE", "ROBE_BALE", "C_GENALE_DAWA"), edges)

    def test_fincha_and_amerti_are_independent_reservoir_sources(self):
        data = load_map_data()
        sources = {source["id"]: source for source in data["sources"]}
        self.assertEqual(sources["FINCHA_RES"]["name"], "Fincha’a Reservoir")
        self.assertEqual(sources["FINCHA_RES"]["branch_scope"]["C_FINCHA_WEST"], [1])
        self.assertEqual(sources["AMERTI_RES"]["name"], "Amerti Reservoir")
        self.assertEqual(sources["AMERTI_RES"]["source_class"], "Reservoir fishery")
        self.assertEqual(sources["AMERTI_RES"]["branch_scope"]["C_FINCHA_WEST"], [2])
        edges = {(edge["from"], edge["to"], edge["branch"]) for edge in data["edges"] if edge["corridor_id"] == "C_FINCHA_WEST"}
        self.assertIn(("FINCHA_RES", "NEKEMTE", 1), edges)
        self.assertIn(("AMERTI_RES", "NEKEMTE", 2), edges)
        self.assertNotIn("AMERTI_RES_CHILD", sources)

    def test_woldiya_name_and_tekeze_korem_sekota_gayint_branch(self):
        data = load_map_data()
        nodes = {node["id"]: node for node in data["nodes"]}
        self.assertEqual(nodes["WOLDIA"]["name"], "Woldiya")
        self.assertTrue({"KOREM", "SEKOTA", "GAYINT"} <= nodes.keys())
        edges = {(edge["from"], edge["to"], edge["branch"]) for edge in data["edges"] if edge["corridor_id"] == "C_TEKEZE_NORTH"}
        self.assertIn(("TEKEZE_RES", "KOREM", 5), edges)
        self.assertIn(("KOREM", "SEKOTA", 5), edges)
        self.assertIn(("SEKOTA", "GAYINT", 5), edges)
        sources = {source["id"]: source for source in data["sources"]}
        self.assertEqual(sources["TEKEZE_RES"]["branch_scope"]["C_TEKEZE_NORTH"], [1, 3, 4, 5])
        self.assertEqual(sources["HASHENGE_LAKE_CHILD"]["branch_scope"]["C_TEKEZE_NORTH"], [2])

    def test_source_display_priority_distinguishes_surplus_from_production(self):
        data = effective_map_data("2026-12-31T23:59:59Z", "observed")
        sources = {source["id"]: source for source in data["sources"]}
        ziway = sources["ZIWAY_LAKE"]
        self.assertEqual(ziway["display_priority_class"], 4)
        self.assertAlmostEqual(ziway["quantified_outbound_tonnes"], 488.9 * 0.4107179382, places=3)
        self.assertEqual(sources["TURKANA_ETH_LAKE"]["display_priority_class"], 3)
        self.assertIsNone(sources["TURKANA_ETH_LAKE"]["quantified_outbound_tonnes"])
        self.assertEqual(sources["TEKEZE_RES"]["display_priority_class"], 2)
        self.assertIn("surplus amount unidentified", sources["TEKEZE_RES"]["display_priority_label"])

    def test_current_qualitative_surplus_priority_is_not_backcast(self):
        data = effective_map_data("2020-12-31T23:59:59Z", "observed")
        sources = {source["id"]: source for source in data["sources"]}
        self.assertEqual(sources["TURKANA_ETH_LAKE"]["display_priority_class"], 0)
        self.assertEqual(sources["GAMBELLA_DIFFUSE"]["display_priority_class"], 0)
        self.assertEqual(sources["GERD_RIVERS"]["display_priority_class"], 0)
        self.assertEqual(sources["TANA_LAKE"]["display_priority_class"], 2)

    def test_fullscreen_map_retains_model_control_and_continuous_animation(self):
        html = (Path(__file__).parents[1] / "src" / "temflow" / "data" / "dashboard_ui.html").read_text(encoding="utf-8")
        self.assertIn('id="mapRun"', html)
        self.assertIn('id="mapRunDock"', html)
        self.assertIn('id="traceSelectionDock"', html)
        self.assertIn('id="multiSelectModeDock"', html)
        self.assertIn('id="zoomInDock"', html)
        self.assertIn('id="zoomOutDock"', html)
        self.assertIn('id="fullMapDock"', html)
        self.assertIn('id="sourceAlert"', html)
        self.assertIn('id="showOtherSources"', html)
        self.assertIn("animation:routePulse 2s linear infinite", html)
        self.assertIn("Lake Chamo evidence alert", html)
        self.assertIn("function nodeSinkPriority(node)", html)
        self.assertIn("reference_tonnes", html)
        self.assertIn("function retainPriorityLabels(labels,accepted=[])", html)
        self.assertIn("display_priority_score", html)
        self.assertIn("nodeMarkerThreshold", html)
        self.assertIn("source-zoom-item", html)
        self.assertIn("Horn regional overview · sources ordered by surplus evidence; largest sinks retained", html)
        self.assertIn("mapData.regional_context?.features", html)
        self.assertIn("Show additional production-source labels", html)
        self.assertIn("active-scenario sink tonnes", html)

    def test_upper_map_controls_are_collapsible_and_auto_hide(self):
        html = (Path(__file__).parents[1] / "src" / "temflow" / "data" / "dashboard_ui.html").read_text(encoding="utf-8")
        self.assertIn('id="mapUpperControls"', html)
        self.assertIn('id="toggleMapControls"', html)
        self.assertIn('id="autoHideMapControls"', html)
        self.assertIn("function setMapControlsCollapsed(collapsed)", html)
        self.assertIn("function scheduleAutoHideControls", html)
        self.assertIn("#mapCard:fullscreen.controls-collapsed .map-shell", html)
        self.assertIn("#mapCard:fullscreen .map-control-dock", html)
        self.assertGreater(html.index('class="map-controls-strip"'), html.index('id="mapUpperControls"'))
        self.assertLess(html.index('class="map-controls-strip"'), html.index('class="map-shell"'))

    def test_input_sections_legends_and_selection_inspector_are_streamlined(self):
        html = (Path(__file__).parents[1] / "src" / "temflow" / "data" / "dashboard_ui.html").read_text(encoding="utf-8")
        for control in ('id="scenarioSection"', 'id="destinationSection"', 'id="exposureSection"', 'id="sourceDataDetails"', 'id="sourceDataDetailsStatus"', 'id="mapLegendSection"', 'id="mapLegendStatus"'):
            self.assertIn(control, html)
        self.assertIn('id="allocationResultsSection"', html)
        self.assertIn('id="allocationResultsStatus"', html)
        self.assertIn("Destination allocation and exposure results", html)
        self.assertIn('id="mapInspectorWindow"', html)
        self.assertIn('id="mapInspectorHandle"', html)
        self.assertIn('id="closeMapInspector"', html)
        self.assertIn("function updateInputSectionSummaries()", html)
        self.assertIn("function bindSelectionInspector()", html)
        self.assertIn("function placeSelectionInspectorAway()", html)
        self.assertIn("selectionOrder=[]", html)
        self.assertIn("function selectionDetail(entry,position)", html)
        self.assertIn("Items are listed in selection order", html)
        self.assertIn("e.key!=='Escape'", html)
        self.assertIn("hideSelectionInspector(true)", html)
        self.assertIn("if(document.fullscreenElement){e.preventDefault();document.exitFullscreen();return}", html)
        self.assertNotIn("!e.target.closest('.map-shell')", html)
        self.assertIn("function appendSelectedFlowArrow", html)
        self.assertIn("function segmentIsBidirectional", html)
        self.assertIn("attrs.keyPoints='1;0'", html)
        self.assertIn("function updateMapLegend(active,corridors)", html)

    def test_new_destination_requires_anchor_and_verified_ledger_save(self):
        html = (Path(__file__).parents[1] / "src" / "temflow" / "data" / "dashboard_ui.html").read_text(encoding="utf-8")
        for control in ('id="pendingNodeRegistration"', 'id="pendingNodeSource"', 'id="pendingNodeVerified"', 'id="anchorPendingNode"', 'id="savePendingNode"'):
            self.assertIn(control, html)
        self.assertIn("function startPendingNode()", html)
        self.assertIn("function anchorPendingNodeAt(point)", html)
        self.assertIn("function savePendingNodeToLedger()", html)
        self.assertIn("save.disabled=!(name&&source&&date&&verified&&anchored)", html)
        self.assertIn("Node saved as ${nodeId}. Route destination is prefilled", html)
        self.assertIn("not an exhaustive road polyline network", html)

    def test_map_selection_targets_do_not_start_pan_capture(self):
        html = (Path(__file__).parents[1] / "src" / "temflow" / "data" / "dashboard_ui.html").read_text(encoding="utf-8")
        self.assertIn("stroke-width:32", html)
        self.assertIn("interactiveSelector='.route-hit,.marker-hit,.node-marker,.source-marker'", html)
        self.assertIn("e.target.closest(interactiveSelector))return", html)
        self.assertIn("toggleNodeSelection(n,e)", html)
        self.assertIn("toggleEdgeSelection(edge,index,e)", html)

    def test_map_supports_exact_multi_and_context_network_selection(self):
        html = (Path(__file__).parents[1] / "src" / "temflow" / "data" / "dashboard_ui.html").read_text(encoding="utf-8")
        self.assertIn('id="mapContextMenu"', html)
        self.assertIn("selectedEdgeIndices=new Set()", html)
        self.assertIn("Shift/Ctrl-click", html)
        self.assertIn("Select this node only", html)
        self.assertIn("Select nearest source → node → nearest sink", html)
        self.assertIn("Select this route segment only", html)
        self.assertIn("Select adjacent connected route segments", html)
        self.assertIn("Select all source–sink routes using this segment", html)
        self.assertIn("Select those routes plus all nodes along them", html)
        self.assertIn("stroke-width:6.4", html)

    def test_complete_network_selection_and_external_sinks_are_visible(self):
        data = load_map_data()
        external = {node["id"] for node in data["nodes"] if node["map_class"] == "external_terminal"}
        self.assertEqual(external, {"SUDAN_EXPORT_NW", "SUDAN_EXPORT_WEST", "KENYA_MARKET", "SOUTH_SUDAN_EXPORT"})
        html = (Path(__file__).parents[1] / "src" / "temflow" / "data" / "dashboard_ui.html").read_text(encoding="utf-8")
        for control in ('id="selectAllMap"', 'id="selectAllMapDock"'):
            self.assertIn(control, html)
        self.assertIn("function selectAllMapFeatures()", html)
        self.assertIn("external=n.map_class==='external_terminal'", html)
        self.assertIn("orange cross = external sink", html)
        self.assertIn("selectedEdge=allFeaturesSelected||selectedEdgeIndices.has(index)", html)
        self.assertIn("All network selected", html)
        self.assertIn(".map-control-dock { display:flex; position:absolute", html)

    def test_active_corridors_are_source_scoped_over_full_network_background(self):
        html = (Path(__file__).parents[1] / "src" / "temflow" / "data" / "dashboard_ui.html").read_text(encoding="utf-8")
        self.assertIn("function activatedSources()", html)
        self.assertIn("function coveredCorridorIds()", html)
        self.assertIn("function populateCorridorFilter()", html)
        self.assertIn("isActive=active.has(edge.corridor_id)&&reachableEdges.has(index)", html)
        self.assertIn("showAsBackground=showBackground&&!isActive", html)
        self.assertIn("populateCorridorFilter();reconcileSelectionOrder()", html)
        self.assertNotIn('<option value="__all__">All corridors', html)

    def test_source_and_corridor_changes_keep_continuous_flow_animation(self):
        html = (Path(__file__).parents[1] / "src" / "temflow" / "data" / "dashboard_ui.html").read_text(encoding="utf-8")
        self.assertIn("await loadTemporalSnapshot(false);renderMap(true)", html)
        self.assertIn("clearFeatureSelection();renderMap(true)", html)
        self.assertIn("selectionSummary('Source multi-selection');renderMap(true)", html)
        self.assertIn("continuous flow animation active", html)
        self.assertIn("animation:routePulse 2s linear infinite", html)
        self.assertIn('<option value="colorwave">Color glow wave</option>', html)
        self.assertIn("animation:routeColorWave 3.2s", html)
        self.assertIn("repeatCount:'indefinite'", html)
        self.assertIn("flowAnimationEnabled=true", html)
        self.assertIn("traceState&&traceState.edgeIndices.size>0&&!traced", html)

    def test_temporal_snapshot_does_not_backcast_chamo_contaminants(self):
        earlier = temporal_snapshot("2024-12-31T23:59:59Z", "observed")
        current = temporal_snapshot("2026-12-31T23:59:59Z", "observed")
        earlier_chamo = [r for r in earlier["records"] if r["evidence_type"] == "contaminant" and r["origin"] == "Lake Chamo"]
        current_chamo = [r for r in current["records"] if r["evidence_type"] == "contaminant" and r["origin"] == "Lake Chamo"]
        self.assertEqual(earlier_chamo, [])
        self.assertEqual(len(current_chamo), 6)

    def test_temporal_interface_controls_are_retained(self):
        html = (Path(__file__).parents[1] / "src" / "temflow" / "data" / "dashboard_ui.html").read_text(encoding="utf-8")
        for control in ('id="temporalSection"', 'id="temporalSectionStatus"', 'id="asOfSlider"', 'id="timeAxis"', 'id="playTimeline"', 'id="evidenceEditor"', 'id="appendEvidence"', 'id="topologyEditor"', 'id="appendTopology"', 'id="clearTrace"', 'id="contaminant"', 'id="multiSources"', 'id="traceSelection"', 'id="multiSelectMode"', 'id="animationType"'):
            self.assertIn(control, html)
        self.assertIn("function updateTemporalSectionSummary()", html)
        self.assertIn("append-only", html)
        self.assertIn("syncDestinationsToSource", html)
        self.assertIn("'A.A.'", html)

    def test_direct_survey_share_replaces_model_only_bound(self):
        payload = self.payload()
        payload["destinations"][0]["direct_share_lower"] = 0.38
        payload["destinations"][0]["direct_share_upper"] = 0.42
        result = calculate_scenario(payload)
        local = result["destinations"][0]
        self.assertEqual(local["share_lower"], 0.38)
        self.assertEqual(local["share_upper"], 0.42)
        self.assertTrue(local["direct_evidence_override"])

    def test_infeasible_direct_survey_constraints_are_rejected(self):
        payload = self.payload()
        payload["destinations"][0]["direct_share_lower"] = 0.10
        payload["destinations"][0]["direct_share_upper"] = 0.10
        with self.assertRaisesRegex(ValueError, "jointly infeasible"):
            calculate_scenario(payload)

    def test_dated_user_source_node_and_route_are_append_only(self):
        with TemporaryDirectory() as directory:
            ledger = Path(directory) / "topology.jsonl"
            with patch("temflow.dashboard._user_topology_path", return_value=ledger):
                source = append_topology({"kind": "source", "observed_at": "2026-08-01", "source_uri": "test:source", "name": "Test Reservoir", "lon": 39.0, "lat": 8.0})
                node = append_topology({"kind": "node", "observed_at": "2026-08-01", "source_uri": "test:node", "name": "Test Market", "lon": 39.2, "lat": 8.2})
                corridor = load_map_data()["corridors"][0]["id"]
                append_topology({"kind": "edge", "observed_at": "2026-08-01", "source_uri": "test:route", "from_id": source["item"]["id"], "to_id": node["item"]["id"], "corridor_id": corridor})
                before = effective_map_data("2025-12-31", "observed")
                after = effective_map_data("2026-12-31", "observed")
                self.assertEqual(before["user_topology_count"], 0)
                self.assertEqual(after["user_topology_count"], 3)
                self.assertTrue(any(item["name"] == "Test Reservoir" for item in after["sources"]))
                self.assertTrue(any(edge["from"] == source["item"]["id"] for edge in after["edges"]))

    def test_route_retirement_is_append_only_and_temporally_effective(self):
        with TemporaryDirectory() as directory:
            ledger = Path(directory) / "topology.jsonl"
            with patch("temflow.dashboard._user_topology_path", return_value=ledger):
                current = effective_map_data("2026-01-01", "observed")
                edge = next(item for item in current["edges"] if item["from"] == "TURKANA_ETH_LAKE" and item["to"] == "JINKA")
                append_topology({
                    "kind": "retirement", "target_kind": "edge", "observed_at": "2026-08-19",
                    "source_uri": "test:expert-correction", "reason": "Unrealistic direct linkage",
                    "from_id": edge["from"], "to_id": edge["to"], "corridor_id": edge["corridor_id"],
                    "branch": edge.get("branch"), "order": edge.get("order"),
                })
                before = effective_map_data("2026-08-18", "observed")
                after = effective_map_data("2026-08-20", "observed")
                self.assertTrue(any(item["from"] == edge["from"] and item["to"] == edge["to"] for item in before["edges"]))
                self.assertFalse(any(item["from"] == edge["from"] and item["to"] == edge["to"] for item in after["edges"]))
                self.assertEqual(after["topology_retirement_count"], 1)

    def test_corrected_ggiii_and_jinka_source_topology(self):
        data = load_map_data()
        edges = {(edge["from"], edge["to"], edge["corridor_id"], edge["branch"]) for edge in data["edges"]}
        self.assertNotIn(("GILGEL_GIBE_III_RES", "JINKA", "C_SOUTHWEST_MULTI", 4), edges)
        self.assertIn(("TURKANA_ETH_LAKE", "JINKA", "C_TURKANA_ADDIS", 1), edges)
        self.assertIn(("CHAMO_LAKE", "ARBAMINCH", "C_SOUTHWEST_MULTI", 1), edges)
        self.assertIn(("ABAYA_LAKE_CHILD", "ARBAMINCH", "C_SOUTHWEST_MULTI", 2), edges)
        self.assertIn(("ARBAMINCH", "JINKA", "C_SOUTHWEST_MULTI", 8), edges)
        for expected in {
            ("GILGEL_GIBE_III_RES", "TERCHA", "C_SOUTHWEST_MULTI", 18),
            ("TERCHA", "BELE_HAWASSA_UNVERIFIED", "C_SOUTHWEST_MULTI", 18),
            ("BELE_HAWASSA_UNVERIFIED", "WOLAITA_SODO", "C_SOUTHWEST_MULTI", 18),
            ("GILGEL_GIBE_III_RES", "BELE_HAWASSA_UNVERIFIED", "C_SOUTHWEST_MULTI", 19),
            ("BELE_HAWASSA_UNVERIFIED", "HADERO", "C_SOUTHWEST_MULTI", 19),
            ("HADERO", "SHINSHICHO", "C_SOUTHWEST_MULTI", 19),
            ("SHINSHICHO", "DURAME", "C_SOUTHWEST_MULTI", 19),
            ("DURAME", "HOSAENA", "C_SOUTHWEST_MULTI", 19),
        }:
            self.assertIn(expected, edges)
        ggiii = next(source for source in data["sources"] if source["id"] == "GILGEL_GIBE_III_RES")
        self.assertEqual(ggiii["branch_scope"]["C_SOUTHWEST_MULTI"], [18, 19])
        self.assertIn("TERCHA", {node["id"] for node in data["nodes"]})

    def test_gambella_important_sources_nodes_and_capacity_layer(self):
        data = load_map_data()
        sources = {source["id"]: source for source in data["sources"]}
        children = {
            "AKOBO_PINYUDO_WETLANDS", "PIBOR_FLOODPLAIN", "GILO_FLOODPLAIN",
            "MAJANG_ITANG_BARO_WETLANDS", "TATA_LENTIC", "GOP_LENTIC_UNVERIFIED", "ALWERO_RES",
        }
        self.assertTrue(children <= sources.keys())
        parent = sources["GAMBELLA_DIFFUSE"]
        self.assertEqual(parent["potential_upper_tonnes"], 20_000.0)
        self.assertFalse(parent["potential_is_observed_production"])
        for source_id in children:
            self.assertEqual(sources[source_id]["capacity_parent"], "GAMBELLA_DIFFUSE")
            self.assertTrue(sources[source_id]["included_in_parent_potential"])
        nodes = {node["id"]: node for node in data["nodes"]}
        self.assertEqual(nodes["PINYUDO"]["map_class"], "source_proximate")
        self.assertEqual(nodes["ITANG"]["map_class"], "source_proximate")
        edges = {(edge["from"], edge["to"], edge["branch"]) for edge in data["edges"] if edge["corridor_id"] == "C_GAMBELLA_LOCAL"}
        for expected in {
            ("AKOBO_PINYUDO_WETLANDS", "PINYUDO", 4),
            ("PIBOR_FLOODPLAIN", "ITANG", 5),
            ("GILO_FLOODPLAIN", "PINYUDO", 6),
            ("MAJANG_ITANG_BARO_WETLANDS", "ITANG", 7),
            ("TATA_LENTIC", "PINYUDO", 1),
            ("GOP_LENTIC_UNVERIFIED", "PINYUDO", 2),
            ("ALWERO_RES", "ABOBO", 3),
            ("ITANG", "GAMBELLA", 5),
            ("ABOBO", "GAMBELLA", 3),
        }:
            self.assertIn(expected, edges)
        self.assertNotIn(("TATA_LENTIC", "GOP_LENTIC_UNVERIFIED", 1), edges)
        self.assertEqual(sources["AKOBO_PINYUDO_WETLANDS"]["branch_scope"]["C_GAMBELLA_LOCAL"], [4])
        self.assertEqual(sources["PIBOR_FLOODPLAIN"]["branch_scope"]["C_GAMBELLA_LOCAL"], [5])
        snapshot = temporal_snapshot("2026-12-31T23:59:59Z", "observed")
        self.assertFalse(any(record["evidence_type"] == "production" and record.get("value") == 20_000 for record in snapshot["records"]))

    def test_context_menus_offer_audited_source_node_and_route_removal(self):
        html = (Path(__file__).parents[1] / "src" / "temflow" / "data" / "dashboard_ui.html").read_text(encoding="utf-8")
        self.assertIn('id="retirementDialog"', html)
        self.assertIn("Retire/remove this production source…", html)
        self.assertIn("Retire/remove this place node…", html)
        self.assertIn("Retire/remove this route segment…", html)
        self.assertIn("kind:'retirement'", html)
        self.assertIn("Date, provenance and reason are required.", html)


if __name__ == "__main__":
    unittest.main()

