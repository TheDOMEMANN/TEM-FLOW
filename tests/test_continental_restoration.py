import unittest
from temflow.private_engine import CATALOG

class ContinentalRestorationTests(unittest.TestCase):
    def test_restored_predecessor_support_preserves_all_countries_and_no_private_cpc(self):
        nodes=[n for n in CATALOG.nodes.values() if n['id'].startswith('GEO_')]
        self.assertEqual(len(nodes),2409)
        self.assertEqual(len({n['iso3'] for n in nodes}),54)
        self.assertTrue(all(n.get('lon') is not None and n.get('lat') is not None for n in nodes))
        self.assertTrue(all('national_finfish_cpc_kg_capita_year' not in n for n in nodes))
        self.assertEqual(len([n for n in nodes if n['iso3']=='NGA']),140)
        self.assertEqual(len([n for n in nodes if n['iso3']=='COD']),117)

    def test_candidate_routes_have_no_observed_mass_and_preserve_endpoints(self):
        routes=[r for r in CATALOG.routes.values() if r['id'].startswith('GEO_ROUTE_')]
        self.assertEqual(len(routes),6770)
        for route in routes:
            self.assertEqual(route['quantity'],'')
            self.assertEqual(route['origin_iso3'],route['destination_iso3'])
            self.assertIn('not evidence',route['claim_boundary'])
            self.assertEqual(route['source_map_lon'],CATALOG.nodes[route['from_node_id']]['lon'])

    def test_continental_query_is_not_truncated_at_old_5000_limit(self):
        result=CATALOG.query('node',{'limit':['20000']})
        self.assertEqual(result['total'],len(result['items']))
