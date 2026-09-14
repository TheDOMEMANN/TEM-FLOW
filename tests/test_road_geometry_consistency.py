import math
import unittest
from temflow.private_engine import CATALOG

def distance_km(a,b):
    x,y,u,v=map(math.radians,(*a,*b))
    h=math.sin((v-y)/2)**2+math.cos(y)*math.cos(v)*math.sin((u-x)/2)**2
    return 6371.0088*2*math.asin(min(1,math.sqrt(h)))

class RoadGeometryConsistencyTests(unittest.TestCase):
    def test_restored_continental_routes_keep_their_predecessor_road_geometry(self):
        mapped=CATALOG.route_display_geometry_payload['route_paths']
        self.assertGreaterEqual(sum(rid.startswith('GEO_ROUTE_') for rid in mapped),5560)

    def test_every_road_path_joins_its_current_directed_endpoints(self):
        payload=CATALOG.route_display_geometry_payload
        for rid,mapping in payload['route_paths'].items():
            route=CATALOG.routes[rid]
            coords=payload['paths'][mapping['path_id']]['coordinates']
            self.assertGreaterEqual(len(coords),2,rid)
            self.assertLess(distance_km(coords[0],(route['source_map_lon'],route['source_map_lat'])),.05,rid)
            self.assertLess(distance_km(coords[-1],(route['destination_map_lon'],route['destination_map_lat'])),.05,rid)
            self.assertEqual(mapping['country'],route['origin_iso3'],rid)
