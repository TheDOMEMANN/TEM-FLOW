import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from temflow.feature_changes import FeatureChangeStore
from temflow.private_engine import CATALOG, DATA_DIR, EngineServer


class FeatureEditingTests(unittest.TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.server = EngineServer(('127.0.0.1', 0), Path(self.directory.name), 'reader-test', 'curator-test')
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f'http://127.0.0.1:{self.server.server_port}'

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(5)
        self.directory.cleanup()

    def call(self, path, payload=None, token='curator-test'):
        request = Request(self.base + path, data=None if payload is None else json.dumps(payload).encode(),
                          headers={'Content-Type': 'application/json', 'X-TEMFLOW-Token': token})
        try:
            with urlopen(request, timeout=20) as response:
                return response.status, json.load(response)
        except HTTPError as error:
            return error.code, json.load(error)

    def node(self, name, lon=38.75):
        payload = {'object_kind': 'node', 'name': name, 'iso3': 'ETH', 'lon': lon, 'lat': 8.98,
                   'roles': 'consumer market', 'food_domains': ['fish'], 'commodity': 'Fish',
                   'effective_at': '2026-01-01', 'observed_at': '2026-01-01', 'status': 'approved',
                   'provenance': 'synthetic isolated test', 'change_reason': 'feature regression test'}
        status, result = self.call('/api/topology', payload)
        self.assertEqual(status, 201, result)
        return result['record']['object_id']

    def route_payload(self, a, b):
        return {'object_kind': 'route', 'from_node_id': a, 'to_node_id': b,
                'food_domains': ['fish'], 'commodity': 'Fish', 'status': 'approved',
                'evidence_class': 'expert candidate topology; not measured flow',
                'effective_at': '2026-01-01', 'observed_at': '2026-01-01',
                'provenance': 'synthetic isolated test', 'change_reason': 'feature regression test'}

    def change(self, targets, action='remove', **extra):
        return {'action': action, 'effective_at': '2026-02-01',
                'targets': [{'object_kind': kind, 'object_id': oid} for kind, oid in targets],
                'provenance': 'synthetic isolated test', 'change_reason': 'feature regression test', **extra}

    def apply(self, payload):
        status, plan = self.call('/api/features/preview', payload)
        self.assertEqual(status, 200, plan)
        return self.call('/api/features/apply', {**payload, 'expected_plan_id': plan['plan_id']})

    def test_non_curators_cannot_add_remove_restore_or_read_private_history(self):
        for path in ('/api/topology', '/api/features/preview', '/api/features/apply'):
            self.assertEqual(self.call(path, {}, 'reader-test')[0], 403)
        self.assertEqual(self.call('/api/features/removed', token='reader-test')[0], 403)
        self.assertFalse(self.call('/api/metadata', token='reader-test')[1]['can_curate'])

    def test_node_removal_reviews_dependencies_filters_models_and_restores_with_history(self):
        a, b = self.node('Lifecycle source'), self.node('Lifecycle market', 38.88)
        status, result = self.call('/api/topology', self.route_payload(a, b))
        self.assertEqual(status, 201, result)
        route = result['record']['object_id']
        payload = self.change([('node', a)])
        _, plan = self.call('/api/features/preview', payload)
        self.assertFalse(plan['can_apply'])
        self.assertEqual(len(plan['connected_routes']), 1)
        self.assertEqual(self.call('/api/features/apply', {**payload, 'expected_plan_id': plan['plan_id']})[0], 400)
        self.assertEqual(self.call('/api/object?kind=node&id=' + a)[0], 200)
        payload['include_connected_routes'] = True
        status, result = self.apply(payload)
        self.assertEqual(status, 201, result)
        self.assertEqual(len(result['event']['targets']), 2)
        self.assertEqual(self.call('/api/object?kind=node&id=' + a)[0], 404)
        self.assertEqual(self.call('/api/object?kind=route&id=' + route)[0], 404)
        self.assertEqual(self.call('/api/model/run', {'node_id': a})[0], 400)
        self.assertEqual(self.call('/api/model/run', {'route_id': route})[0], 400)
        self.assertEqual(self.call('/api/object?kind=node&id=' + a + '&as_of=2026-01-15')[0], 200)
        persisted = FeatureChangeStore(self.directory.name)
        self.assertIn(('node', a), persisted.removed())
        restore = self.change([('route', route)], action='restore', effective_at='2026-03-01')
        self.assertFalse(self.call('/api/features/preview', restore)[1]['can_apply'])
        restore['targets'].append({'object_kind': 'node', 'object_id': a})
        self.assertEqual(self.apply(restore)[0], 201)
        self.assertEqual(self.call('/api/object?kind=node&id=' + a)[0], 200)
        self.assertEqual(self.call('/api/object?kind=route&id=' + route)[0], 200)
        self.assertEqual(self.call('/api/object?kind=node&id=' + a + '&as_of=2026-02-15')[0], 404)
        self.assertEqual(len(persisted.events()), 2)
        self.assertNotIn(a, CATALOG.nodes)
        self.assertNotIn(route, CATALOG.routes)

    def test_frozen_route_removal_preserves_source_and_filters_road_geometry(self):
        rid = next(rid for rid in CATALOG.route_display_geometry_payload['route_paths'] if rid.startswith('GEO_ROUTE_'))
        source = DATA_DIR / 'africa_route_display_geometries.json'
        before = hashlib.sha256(source.read_bytes()).hexdigest()
        self.assertEqual(self.apply(self.change([('route', rid)]))[0], 201)
        geometry = self.call('/api/route-display-geometries?limit=20000')[1]
        self.assertNotIn(rid, geometry['route_paths'])
        self.assertEqual(before, hashlib.sha256(source.read_bytes()).hexdigest())
        self.assertIn(rid, CATALOG.routes)
        self.assertEqual(self.apply(self.change([('route', rid)], action='restore', effective_at='2026-03-01'))[0], 201)
        self.assertIn(rid, self.call('/api/route-display-geometries?limit=20000')[1]['route_paths'])

    def test_stale_plan_invalid_target_and_missing_provenance_do_not_write(self):
        a, b = self.node('First'), self.node('Second')
        payload = self.change([('node', a)])
        _, stale = self.call('/api/features/preview', payload)
        self.assertEqual(self.apply(self.change([('node', b)]))[0], 201)
        self.assertEqual(self.call('/api/features/apply', {**payload, 'expected_plan_id': stale['plan_id']})[0], 409)
        invalid = self.change([('node', a), ('node', 'missing')])
        self.assertEqual(self.call('/api/features/preview', invalid)[0], 400)
        self.assertEqual(self.apply({**payload, 'provenance': ''})[0], 400)
        self.assertEqual(len(self.server.feature_changes.events()), 1)

    def test_distinct_finite_active_endpoints_and_removed_ids_cannot_be_reused(self):
        a, b = self.node('First'), self.node('Second')
        self.assertEqual(self.call('/api/topology', self.route_payload(a, a))[0], 400)
        payload = self.route_payload(a, b)
        self.assertEqual(self.apply(self.change([('node', a)]))[0], 201)
        payload['effective_at'] = '2026-04-01'
        self.assertEqual(self.call('/api/topology', payload)[0], 400)
        self.assertEqual(self.call('/api/topology', {'object_kind': 'node', 'name': 'Invalid', 'iso3': 'ETH', 'lon': 'nan', 'lat': 8.98,
                         'provenance': 'test', 'change_reason': 'test'})[0], 400)
        same = {'object_kind': 'node', 'object_id': a, 'name': 'Reuse', 'iso3': 'ETH', 'lon': 38.75, 'lat': 8.98,
                'food_domains': ['fish'], 'commodity': 'Fish', 'roles': 'market', 'provenance': 'test', 'change_reason': 'test'}
        self.assertEqual(self.call('/api/topology', same)[0], 400)

    def test_future_removal_does_not_change_current_view_and_batch_removal_is_single_event(self):
        a, b = self.node('First'), self.node('Second')
        payload = self.change([('node', a), ('node', b)], effective_at='2099-01-01')
        self.assertEqual(self.apply(payload)[0], 201)
        self.assertEqual(len(self.server.feature_changes.events()), 1)
        self.assertEqual(self.call('/api/object?kind=node&id=' + a)[0], 200)
        self.assertEqual(self.call('/api/object?kind=node&id=' + a + '&as_of=2099-01-02')[0], 404)


if __name__ == '__main__':
    unittest.main()
