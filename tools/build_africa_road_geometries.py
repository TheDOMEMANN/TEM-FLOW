"""Build reproducible road-aligned *display* geometries for eligible OD links.

The ED-FLOW relation and its direction remain the quantitative object. This
builder changes only the cartographic line shown between registered display endpoints.
Eligible continental countries use the public-domain Natural Earth 1:10m roads
layer and are labelled as generalized road alignment.
Cape Verde, Mauritius and Seychelles use frozen OpenStreetMap/Overpass
major-road extracts where Natural Earth contains no road geometry.
Registered nodes without observed coordinates retain their explicit
country-layout-proxy label; routing those display endpoints does not upgrade
the underlying evidence.

Usage::

    python tools/build_africa_road_geometries.py path/to/ne_10m_roads.geojson
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime, timezone
import gzip
import hashlib
import heapq
import json
import math
from pathlib import Path
from typing import Any, Iterable

import numpy as np
from scipy.spatial import cKDTree

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from temflow.private_engine import COUNTRY_LAYOUT_ANCHORS, Catalog, _point_in_geometry


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "src" / "temflow" / "data"
OUTPUT = DATA / "patterns" / "africa_route_display_geometries.json"
OSM_REFERENCE_DIR = DATA / "patterns" / "reference_roads"
OSM_SOURCE_METADATA = OSM_REFERENCE_DIR / "osm_overpass_sources.json"
NATURAL_EARTH_URL = (
    "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/"
    "master/geojson/ne_10m_roads.geojson"
)
EXPECTED_NATURAL_EARTH_SHA256 = "66a0c7b438e92fd124822cc5921cfa11042f48c294ade5e0f03f2c6640fd0248"
MAX_PRECISE_SNAP_KM = 35.0
MAX_PROXY_SNAP_KM = 220.0
ROUND_DIGITS = 5


def haversine_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    lon1, lat1, lon2, lat2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    dlon, dlat = lon2 - lon1, lat2 - lat1
    value = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 6371.0088 * 2 * math.asin(min(1.0, math.sqrt(value)))


def perpendicular_distance(point: tuple[float, float], start: tuple[float, float], end: tuple[float, float]) -> float:
    if start == end:
        return math.hypot(point[0] - start[0], point[1] - start[1])
    dx, dy = end[0] - start[0], end[1] - start[1]
    fraction = max(
        0.0,
        min(1.0, ((point[0] - start[0]) * dx + (point[1] - start[1]) * dy) / (dx * dx + dy * dy)),
    )
    projected = (start[0] + fraction * dx, start[1] + fraction * dy)
    return math.hypot(point[0] - projected[0], point[1] - projected[1])


def simplify(points: list[tuple[float, float]], tolerance: float = 0.006) -> list[tuple[float, float]]:
    if len(points) <= 2:
        return points
    distances = [perpendicular_distance(point, points[0], points[-1]) for point in points[1:-1]]
    maximum = max(distances, default=0.0)
    if maximum <= tolerance:
        return [points[0], points[-1]]
    index = distances.index(maximum) + 1
    return simplify(points[: index + 1], tolerance)[:-1] + simplify(points[index:], tolerance)


def geometry_lines(geometry: dict[str, Any]) -> Iterable[list[list[float]]]:
    if geometry.get("type") == "LineString":
        yield geometry.get("coordinates", [])
    elif geometry.get("type") == "MultiLineString":
        yield from geometry.get("coordinates", [])


_bounds_cache = {}
def point_in_country_display_extent(lon: float, lat: float, iso3: str, catalog: Catalog) -> bool:
    """Assign reference-road segments without inventing missing country polygons."""
    geometry = catalog.country_geometry.get(iso3)
    if geometry:
        if iso3 not in _bounds_cache:
            points = []
            def collect(value):
                if isinstance(value[0], (int, float)): points.append(value)
                else:
                    for child in value: collect(child)
            collect(geometry["coordinates"])
            _bounds_cache[iso3] = (min(p[0] for p in points), min(p[1] for p in points), max(p[0] for p in points), max(p[1] for p in points))
        west, south, east, north = _bounds_cache[iso3]
        return west <= lon <= east and south <= lat <= north and _point_in_geometry(lon, lat, geometry)
    anchor = COUNTRY_LAYOUT_ANCHORS.get(iso3)
    if not anchor:
        return False
    centre_lon, centre_lat, width, height = anchor
    return abs(lon - centre_lon) <= width / 2 and abs(lat - centre_lat) <= height / 2


def largest_component(adjacency: dict[tuple[float, float], dict[tuple[float, float], float]]) -> set[tuple[float, float]]:
    seen: set[tuple[float, float]] = set()
    largest: set[tuple[float, float]] = set()
    for start in adjacency:
        if start in seen:
            continue
        component = {start}
        stack = [start]
        seen.add(start)
        while stack:
            node = stack.pop()
            for neighbour in adjacency[node]:
                if neighbour not in seen:
                    seen.add(neighbour)
                    component.add(neighbour)
                    stack.append(neighbour)
        if len(component) > len(largest):
            largest = component
    return largest


def dijkstra_paths(
    adjacency: dict[tuple[float, float], dict[tuple[float, float], float]],
    start: tuple[float, float],
    targets: set[tuple[float, float]],
) -> dict[tuple[float, float], list[tuple[float, float]]]:
    remaining = set(targets)
    distances = {start: 0.0}
    previous: dict[tuple[float, float], tuple[float, float]] = {}
    queue: list[tuple[float, tuple[float, float]]] = [(0.0, start)]
    while queue and remaining:
        distance, node = heapq.heappop(queue)
        if distance != distances.get(node):
            continue
        remaining.discard(node)
        for neighbour, weight in adjacency[node].items():
            candidate = distance + weight
            if candidate < distances.get(neighbour, math.inf):
                distances[neighbour] = candidate
                previous[neighbour] = node
                heapq.heappush(queue, (candidate, neighbour))
    output: dict[tuple[float, float], list[tuple[float, float]]] = {}
    for target in targets - remaining:
        path = [target]
        while path[-1] != start:
            path.append(previous[path[-1]])
        output[target] = list(reversed(path))
    return output


def add_path(
    paths: dict[str, dict[str, Any]],
    coordinates: list[tuple[float, float]],
    source: str,
    status: str,
    extra: dict[str, Any] | None = None,
) -> str:
    rounded = [[round(point[0], 5), round(point[1], 5)] for point in coordinates]
    digest = hashlib.sha256(json.dumps(rounded, separators=(",", ":")).encode("utf-8")).hexdigest()[:16]
    path_id = f"ROADPATH_{digest}"
    paths.setdefault(
        path_id,
        {"coordinates": rounded, "source": source, "status": status, **(extra or {})},
    )
    return path_id


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("natural_earth_roads", type=Path)
    parser.add_argument("--allow-source-hash-change", action="store_true")
    args = parser.parse_args()
    source_hash = hashlib.sha256(args.natural_earth_roads.read_bytes()).hexdigest()
    if source_hash != EXPECTED_NATURAL_EARTH_SHA256 and not args.allow_source_hash_change:
        raise SystemExit(f"Natural Earth source hash changed: {source_hash}")

    catalog = Catalog()
    display_domestic = [
        route
        for route in catalog.operational_routes.values()
        if route.get("origin_iso3") == route.get("destination_iso3")
        and route.get("source_map_lon") is not None
        and route.get("destination_map_lon") is not None
    ]
    target_countries = sorted({str(route["origin_iso3"]) for route in display_domestic})
    road_features = json.loads(args.natural_earth_roads.read_text(encoding="utf-8")).get("features", [])
    graphs: dict[str, dict[tuple[float, float], dict[tuple[float, float], float]]] = {
        iso3: defaultdict(dict) for iso3 in target_countries
    }
    for feature in road_features:
        if feature.get("properties", {}).get("continent") != "Africa":
            continue
        for line in geometry_lines(feature.get("geometry", {})):
            for raw_a, raw_b in zip(line, line[1:]):
                midpoint = ((float(raw_a[0]) + float(raw_b[0])) / 2, (float(raw_a[1]) + float(raw_b[1])) / 2)
                for iso3 in target_countries:
                    if not point_in_country_display_extent(*midpoint, iso3, catalog):
                        continue
                    a = (round(float(raw_a[0]), ROUND_DIGITS), round(float(raw_a[1]), ROUND_DIGITS))
                    b = (round(float(raw_b[0]), ROUND_DIGITS), round(float(raw_b[1]), ROUND_DIGITS))
                    weight = haversine_km(a, b)
                    graphs[iso3][a][b] = min(weight, graphs[iso3][a].get(b, math.inf))
                    graphs[iso3][b][a] = min(weight, graphs[iso3][b].get(a, math.inf))
                    break

    osm_source_metadata = json.loads(OSM_SOURCE_METADATA.read_text(encoding="utf-8"))
    for iso3, metadata in osm_source_metadata.get("extracts", {}).items():
        if iso3 not in graphs:
            continue
        source_file = OSM_REFERENCE_DIR / str(metadata["file"])
        compressed = source_file.read_bytes()
        if hashlib.sha256(compressed).hexdigest() != metadata["compressed_sha256"]:
            raise SystemExit(f"Compressed OpenStreetMap source hash changed for {iso3}")
        raw = gzip.decompress(compressed)
        if hashlib.sha256(raw).hexdigest() != metadata["raw_sha256"]:
            raise SystemExit(f"Raw OpenStreetMap source hash changed for {iso3}")
        osm_payload = json.loads(raw)
        if len(osm_payload.get("elements", [])) != int(metadata["element_count"]):
            raise SystemExit(f"OpenStreetMap element count changed for {iso3}")
        for element in osm_payload.get("elements", []):
            line = [
                [float(point["lon"]), float(point["lat"])]
                for point in element.get("geometry", [])
                if point.get("lon") is not None and point.get("lat") is not None
            ]
            for raw_a, raw_b in zip(line, line[1:]):
                a = (round(float(raw_a[0]), ROUND_DIGITS), round(float(raw_a[1]), ROUND_DIGITS))
                b = (round(float(raw_b[0]), ROUND_DIGITS), round(float(raw_b[1]), ROUND_DIGITS))
                weight = haversine_km(a, b)
                graphs[iso3][a][b] = min(weight, graphs[iso3][a].get(b, math.inf))
                graphs[iso3][b][a] = min(weight, graphs[iso3][b].get(a, math.inf))

    paths: dict[str, dict[str, Any]] = {}
    route_paths: dict[str, dict[str, Any]] = {}
    # Retain compatible frozen display geometry, including the audited Ethiopian OSM paths.
    for seed_file in (DATA / "patterns" / "africa_route_display_geometries.json", DATA / "patterns" / "predecessor_road_geometries.json"):
        seed = json.loads(seed_file.read_text(encoding="utf-8"))
        for rid, mapping in seed["route_paths"].items():
            route = catalog.domestic_routes.get(rid)
            if not route or rid in route_paths:
                continue
            value = seed["paths"].get(mapping["path_id"])
            if not value or len(value.get("coordinates", [])) < 2:
                continue
            coords = list(value["coordinates"])
            start = (route["source_map_lon"], route["source_map_lat"])
            end = (route["destination_map_lon"], route["destination_map_lat"])
            forward = max(haversine_km(start, coords[0]), haversine_km(end, coords[-1]))
            reverse = max(haversine_km(start, coords[-1]), haversine_km(end, coords[0]))
            tolerance = 35 if str(mapping.get("source", "")).startswith("OpenStreetMap/OSRM") else .05
            if min(forward, reverse) > tolerance:
                continue
            if reverse < forward:
                coords.reverse()
            if min(forward, reverse) > .05:
                coords = [list(start), *coords, list(end)]
                value = {**value, "endpoint_connectors": "node to nearest audited road endpoint; display only"}
            paths[mapping["path_id"]] = {**value, "coordinates": coords}
            route_paths[rid] = dict(mapping)
    print("Retained compatible frozen route paths:", len(route_paths), flush=True)
    country_statistics: dict[str, dict[str, Any]] = {}

    for iso3 in target_countries:
        print("Routing", iso3, flush=True)
        reference_source = (
            "OpenStreetMap/Overpass major roads"
            if iso3 in osm_source_metadata.get("extracts", {})
            else "Natural Earth 1:10m roads"
        )
        component = largest_component(graphs[iso3])
        country_routes = [
            route
            for route in display_domestic
            if route.get("origin_iso3") == iso3 and str(route.get("id")) not in route_paths
        ]
        if len(component) < 2:
            country_statistics.setdefault(
                iso3,
                {
                    "eligible_display_routes": sum(
                        1 for route in display_domestic if route.get("origin_iso3") == iso3
                    ),
                    "road_aligned_routes": sum(
                        1 for value in route_paths.values() if value["country"] == iso3
                    ),
                    "not_aligned_no_reference_roads": len(country_routes),
                    "source": f"{reference_source}; no connected road graph available",
                },
            )
            continue
        adjacency = {node: {other: weight for other, weight in graphs[iso3][node].items() if other in component} for node in component}
        vertices = sorted(component)
        mean_latitude = sum(point[1] for point in vertices) / len(vertices)
        longitude_scale = math.cos(math.radians(mean_latitude))
        tree = cKDTree(np.asarray([(point[0] * longitude_scale, point[1]) for point in vertices]))

        pair_routes: dict[tuple[tuple[float, float], tuple[float, float]], list[str]] = defaultdict(list)
        pair_proxy: dict[tuple[tuple[float, float], tuple[float, float]], bool] = {}
        for route in country_routes:
            source = (float(route["source_map_lon"]), float(route["source_map_lat"]))
            destination = (float(route["destination_map_lon"]), float(route["destination_map_lat"]))
            pair_routes[(source, destination)].append(str(route["id"]))
            pair_proxy[(source, destination)] = not (
                catalog.nodes[route["from_node_id"]].get("lon") is not None and catalog.nodes[route["to_node_id"]].get("lon") is not None
            )

        snapped: dict[tuple[float, float], tuple[tuple[float, float], float]] = {}
        for endpoint in {point for pair in pair_routes for point in pair}:
            _, index = tree.query((endpoint[0] * longitude_scale, endpoint[1]), k=1)
            road_vertex = vertices[int(index)]
            snapped[endpoint] = (road_vertex, haversine_km(endpoint, road_vertex))

        pairs_by_start: dict[tuple[float, float], list[tuple[tuple[float, float], tuple[float, float]]]] = defaultdict(list)
        rejected_snap = 0
        for pair in pair_routes:
            snap_limit = MAX_PROXY_SNAP_KM if pair_proxy[pair] else MAX_PRECISE_SNAP_KM
            if snapped[pair[0]][1] > snap_limit or snapped[pair[1]][1] > snap_limit:
                rejected_snap += len(pair_routes[pair])
                continue
            pairs_by_start[snapped[pair[0]][0]].append(pair)

        routed = 0
        for road_start, pairs in pairs_by_start.items():
            targets = {snapped[pair[1]][0] for pair in pairs}
            road_paths = dijkstra_paths(adjacency, road_start, targets)
            for pair in pairs:
                road_end = snapped[pair[1]][0]
                if road_end not in road_paths:
                    continue
                path = road_paths[road_end]
                coordinates = [pair[0], *path, pair[1]]
                cleaned: list[tuple[float, float]] = []
                for point in coordinates:
                    if not cleaned or point != cleaned[-1]:
                        cleaned.append(point)
                simplified = simplify(cleaned)
                path_id = add_path(
                    paths,
                    simplified,
                    reference_source,
                    (
                        "generalized road-aligned display geometry via country-layout proxy endpoints; topology only"
                        if pair_proxy[pair]
                        else "generalized road-aligned display geometry"
                    ),
                    {
                        "origin_snap_km": round(snapped[pair[0]][1], 3),
                        "destination_snap_km": round(snapped[pair[1]][1], 3),
                        "max_snap_km": MAX_PROXY_SNAP_KM if pair_proxy[pair] else MAX_PRECISE_SNAP_KM,
                        "endpoint_basis": "country-layout proxy" if pair_proxy[pair] else "reported or verified coordinate",
                    },
                )
                for route_id in pair_routes[pair]:
                    route_paths[route_id] = {
                        "path_id": path_id,
                        "country": iso3,
                        "source": reference_source,
                    }
                    routed += 1
        existing = sum(1 for value in route_paths.values() if value["country"] == iso3) - routed
        total_country_routes = sum(1 for route in display_domestic if route.get("origin_iso3") == iso3)
        country_statistics[iso3] = {
            "eligible_display_routes": total_country_routes,
            "road_aligned_routes": existing + routed,
            "not_aligned_snap_limit": rejected_snap,
            "not_aligned_disconnected": len(country_routes) - routed - rejected_snap,
            "largest_component_vertices": len(component),
            "source": (
                "OpenStreetMap/Overpass major roads; ODbL; cartographic reference geometry"
                if reference_source.startswith("OpenStreetMap")
                else "Natural Earth 1:10m roads; public domain; generalized cartographic geometry"
            ),
        }

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "geometry_role": "display only; the registered directed OD relation remains the quantitative topology",
        "interpretive_boundary": (
            "Road alignment is not evidence that a shipment used the displayed physical path. "
            "Natural Earth lines are generalized and island OpenStreetMap extracts are cartographic reference data. "
            "Reported coordinates use the strict snap limit; explicitly labelled country-layout proxy endpoints use "
            "a wider display-only snap limit and remain topology proxies."
        ),
        "sources": {
            "natural_earth": {
                "url": NATURAL_EARTH_URL,
                "sha256": source_hash,
                "licence": "public domain",
                "scale": "1:10m",
            },
            "osm_overpass_islands": osm_source_metadata,
        },
        "max_natural_earth_snap_km": MAX_PRECISE_SNAP_KM,
        "max_proxy_endpoint_snap_km": MAX_PROXY_SNAP_KM,
        "supported_countries": sorted(country_statistics),
        "country_statistics": country_statistics,
        "route_paths": route_paths,
        "paths": paths,
    }
    OUTPUT.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(
        f"wrote {OUTPUT} with {len(route_paths)} route mappings, "
        f"{len(paths)} unique paths across {len(country_statistics)} countries"
    )
    for iso3, statistics in sorted(country_statistics.items()):
        print(iso3, statistics)


if __name__ == "__main__":
    main()
