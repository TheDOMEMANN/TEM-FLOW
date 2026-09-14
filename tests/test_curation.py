from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import threading
import unittest
from urllib.request import Request, urlopen

from temflow.curation import AIProposalStore, AIProviderConfig, TopologyStore
from temflow.private_engine import EngineServer, UI_PATH


class CurationStoreTests(unittest.TestCase):
    def test_topology_store_is_append_only_and_approved_views_exclude_drafts(self):
        with TemporaryDirectory() as directory:
            store = TopologyStore(directory)
            draft = store.append(
                {
                    "object_kind": "node",
                    "observed_at": "2026-08-30",
                    "status": "draft",
                    "actor": "curator",
                    "provenance": "local:test",
                    "change_reason": "test draft",
                    "attributes": {"id": "USR_NODE_TEST", "name": "Test node"},
                }
            )
            self.assertNotIn(draft.object_id, store.objects()["node"])
            self.assertIn(draft.object_id, store.objects(include_drafts=True)["node"])
            with self.assertRaises(ValueError):
                store.append(
                    {
                        "object_kind": "node",
                        "object_id": draft.object_id,
                        "observed_at": "2026-08-30",
                        "status": "approved",
                        "actor": "curator",
                        "provenance": "local:test",
                        "change_reason": "missing supersedes",
                        "attributes": {"id": draft.object_id, "name": "Test node"},
                    }
                )

    def test_ai_proposal_needs_a_human_decision_and_preserves_source_hash(self):
        with TemporaryDirectory() as directory:
            store = AIProposalStore(directory)
            proposal = store.create(
                {
                    "source_uri": "doi:10.test/example",
                    "source_text": "Exact recoverable evidence text.",
                    "candidate": {"candidate_kind": "node", "name": "Candidate"},
                    "ai_metadata": {"model": "test-model"},
                }
            )
            current = store.current(proposal["proposal_id"])
            self.assertEqual(current["status"], "pending")
            self.assertEqual(len(current["source_text_sha256"]), 64)
            store.decide(proposal["proposal_id"], "rejected", "human-curator", "Insufficient coordinate evidence")
            self.assertEqual(store.current(proposal["proposal_id"])["status"], "rejected")

    def test_provider_metadata_never_exposes_the_api_key(self):
        metadata = AIProviderConfig("https://provider.example/v1", "model", "SECRET").public_metadata()
        self.assertTrue(metadata["configured"])
        self.assertFalse(metadata["secrets_exposed_to_browser"])
        self.assertNotIn("SECRET", json.dumps(metadata))


class PrivateCurationAPITests(unittest.TestCase):
    def post(self, base: str, path: str, value: dict) -> dict:
        request = Request(
            base + path,
            data=json.dumps(value).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(request, timeout=15) as response:
            return json.loads(response.read().decode("utf-8"))

    def test_privileged_api_adds_nodes_and_route_without_mutating_frozen_catalog(self):
        with TemporaryDirectory() as directory:
            server = EngineServer(("127.0.0.1", 0), Path(directory), None, None)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            base = f"http://127.0.0.1:{server.server_port}"
            try:
                def node(name: str, lon: float, lat: float) -> dict:
                    return self.post(
                        base,
                        "/api/topology",
                        {
                            "object_kind": "node",
                            "name": name,
                            "iso3": "ETH",
                            "food_domains": ["fish"],
                            "lon": lon,
                            "lat": lat,
                            "roles": "production source",
                            "commodity": "Fish",
                            "product_form": "fresh whole fish",
                            "observed_at": "2026-08-30",
                            "status": "approved",
                            "provenance": "local:test-ledger",
                            "change_reason": "API integration test",
                        },
                    )

                first = node("Curated source", 38.75, 8.98)["record"]["object_id"]
                second = node("Curated market", 38.88, 9.05)["record"]["object_id"]
                route = self.post(
                    base,
                    "/api/topology",
                    {
                        "object_kind": "route",
                        "from_node_id": first,
                        "to_node_id": second,
                        "food_domains": ["fish"],
                        "commodity": "Fish",
                        "evidence_class": "observed commodity-specific OD support",
                        "quantity": 10,
                        "quantity_period": "t/year",
                        "observed_at": "2026-08-30",
                        "status": "approved",
                        "provenance": "local:test-ledger",
                        "change_reason": "API integration test",
                    },
                )["record"]
                with urlopen(base + "/api/nodes?search=Curated&limit=50", timeout=15) as response:
                    nodes = json.loads(response.read().decode("utf-8"))
                with urlopen(base + "/api/routes?search=Curated&limit=50", timeout=15) as response:
                    routes = json.loads(response.read().decode("utf-8"))
                self.assertEqual(nodes["total"], 2)
                self.assertEqual(routes["total"], 1)
                self.assertEqual(routes["items"][0]["id"], route["object_id"])
                self.assertTrue(routes["items"][0]["network_eligible"])
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)

    def test_ui_exposes_curation_ai_and_semantic_zoom_controls(self):
        html = Path(UI_PATH).read_text(encoding="utf-8")
        for identifier in (
            'id="curationPanel"',
            'id="addNode"',
            'id="addRoute"',
            'id="captureNodeLocation"',
            'id="extractAI"',
            'id="stageAI"',
            'id="approveProposal"',
            'id="rejectProposal"',
            'id="semanticZoomState"',
        ):
            self.assertIn(identifier, html)
        self.assertIn("function updateSemanticZoom()", html)
        self.assertIn("data-base-radius", html)
        self.assertIn("human approval", html.casefold())


if __name__ == "__main__":
    unittest.main()

