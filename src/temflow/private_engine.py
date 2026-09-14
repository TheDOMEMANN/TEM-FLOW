"""Authenticated private review engine for TEM-FLOW release 1.0.0."""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import math
import threading
import os
from pathlib import Path
from typing import Any, Iterable, Mapping
from urllib.parse import parse_qs, urlsplit
import webbrowser

from .curation import AIProposalStore, AIProviderConfig, TopologyRecord, TopologyStore, extract_candidate
from .evidential_resolution import run_evidence_resolved_payload
from .exposure_scenario import calculate_exposure_scenario
from .compositional import run_compositional_payload
from .monitoring_layers import normalize_layer_selection, summarize_private_layers
from .tem_calculus import run_typed_model, tem_compare_and_screen
from .versioned_registry import RevisionStore
from .preview_build import preview_build_id
from .feature_changes import FeatureChangeStore, change_plan


from ._version import VERSION
PREVIEW_BUILD_ID = preview_build_id()
DATA_DIR = Path(__file__).with_name("data") / "patterns"
UI_PATH = Path(__file__).with_name("data") / "patterns_private_ui.html"

# Display anchors are used only when the bundled polygon layer omits a small
# island state. They never replace or assert a node coordinate.
COUNTRY_LAYOUT_ANCHORS: dict[str, tuple[float, float, float, float]] = {
    "CPV": (-23.6052, 15.1201, 1.4, 1.0),
    "COM": (43.3333, -11.6455, 0.35, 0.28),
    "MUS": (57.5522, -20.3484, 0.35, 0.28),
    "SYC": (55.4920, -4.6796, 0.55, 0.45),
    "STP": (6.6131, 0.1864, 0.25, 0.22),
}


def _csv(name: str) -> list[dict[str, str]]:
    with (DATA_DIR / name).open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


CERTIFICATE_ROWS = _csv("temflow_transformation_certificate_ledger.csv") if (DATA_DIR / "temflow_transformation_certificate_ledger.csv").exists() else []
CERTIFICATES_BY_OBJECT: dict[str, list[dict[str, str]]] = {}
for _certificate_row in CERTIFICATE_ROWS:
    CERTIFICATES_BY_OBJECT.setdefault(_certificate_row.get("object_id", ""), []).append(_certificate_row)


def _split(value: str) -> list[str]:
    return [part.strip() for part in str(value or "").replace("|", ";").split(";") if part.strip()]


def _normal_domains(value: str | Iterable[str]) -> list[str]:
    values = [value] if isinstance(value, str) else list(value)
    text = " ".join(str(item) for item in values).casefold()
    domains: list[str] = []
    if any(label in text for label in ("fish", "shellfish", "seafood", "aquatic")):
        domains.append("fish")
    if any(label in text for label in ("vegetable", "horticultur", "tomato", "onion", "leafy")):
        domains.append("vegetable")
    return domains


def _commodity_groups(value: object, domains: Iterable[str]) -> list[str]:
    """Return a compact, stable UI/model grouping without replacing raw labels."""
    text = str(value or "").casefold()
    domain_set = set(domains)
    groups: list[str] = []
    if "fish" in domain_set:
        if any(term in text for term in ("crustace", "shrimp", "prawn", "crayfish", "lobster", "crab")):
            groups.append("Crustaceans")
        if any(term in text for term in ("mollusc", "mussel", "oyster", "clam", "cephalopod", "squid")):
            groups.append("Molluscs")
        if any(term in text for term in ("fish", "tilapia", "catfish", "carp", "tuna", "mackerel", "bream", "lungfish", "monkfish", "sardine")):
            groups.append("Finfish")
        if any(term in text for term in ("other_aquatic", "aquatic invertebrate")):
            groups.append("Other aquatic foods")
        if not groups or "seafood" in text or "|" in text or "samples" in text or "species" in text:
            groups.append("Mixed or aggregate seafood")
    if "vegetable" in domain_set:
        vegetable_terms = {
            "Tomato": ("tomato",),
            "Onion and alliums": ("onion", "allium",),
            "Cabbage and brassicas": ("cabbage", "brassica",),
            "Leafy vegetables": ("leaf", "amaranth", "spinach", "bidens",),
            "Pepper and chilli": ("pepper", "chilli", "chili",),
            "Roots and tubers": ("carrot", "potato", "tuber", "amadumbe",),
            "Cucumber and gourds": ("cucumber", "gourd",),
        }
        for label, terms in vegetable_terms.items():
            if any(term in text for term in terms):
                groups.append(label)
        vegetable_groups = [group for group in groups if group not in {"Crustaceans", "Molluscs", "Finfish", "Other aquatic foods", "Mixed or aggregate seafood"}]
        if not vegetable_groups or any(term in text for term in ("vegetable", "composite", "common", ";", "|")):
            groups.append("Mixed or other vegetables")
    return list(dict.fromkeys(groups))


def _filter_parts(values: Iterable[object]) -> list[str]:
    """Normalize API/UI filter values while treating ALL as an open scope."""
    parts = [part.strip() for raw in values for part in str(raw or "").split(",")]
    return [part for part in parts if part and part.casefold() not in {"all", "__all__", "*"}]


def _filter_value(value: object) -> list[str]:
    if value is None:
        return []
    values = [value] if isinstance(value, str) or not isinstance(value, Iterable) else value
    return _filter_parts(values)


def _point_in_ring(lon: float, lat: float, ring: list[list[float]]) -> bool:
    inside = False
    if len(ring) < 3:
        return False
    x1, y1 = ring[-1][:2]
    for point in ring:
        x2, y2 = point[:2]
        if (y2 > lat) != (y1 > lat):
            cross = (x1 - x2) * (lat - y2) / (y1 - y2) + x2
            if lon < cross:
                inside = not inside
        x1, y1 = x2, y2
    return inside


def _point_in_geometry(lon: float, lat: float, geometry: Mapping[str, Any]) -> bool:
    coordinates = geometry.get("coordinates", [])
    if geometry.get("type") == "Polygon":
        polygons = [coordinates]
    elif geometry.get("type") == "MultiPolygon":
        polygons = coordinates
    else:
        return False
    for polygon in polygons:
        if polygon and _point_in_ring(lon, lat, polygon[0]):
            if not any(_point_in_ring(lon, lat, hole) for hole in polygon[1:]):
                return True
    return False


def _outer_rings(geometry: Mapping[str, Any]) -> list[list[list[float]]]:
    coordinates = geometry.get("coordinates", [])
    if geometry.get("type") == "Polygon":
        return [coordinates[0]] if coordinates else []
    if geometry.get("type") == "MultiPolygon":
        return [polygon[0] for polygon in coordinates if polygon]
    return []


def _ring_area(ring: list[list[float]]) -> float:
    return abs(sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(ring, ring[1:] + ring[:1]))) / 2


def _halton(index: int, base: int) -> float:
    result, fraction = 0.0, 1.0
    while index:
        fraction /= base
        index, remainder = divmod(index, base)
        result += remainder * fraction
    return result


def _country_layout_points(geometry: Mapping[str, Any], count: int) -> list[tuple[float, float]]:
    """Return deterministic display-only points inside the largest country polygon."""
    rings = _outer_rings(geometry)
    if not rings or count <= 0:
        return []
    ring = max(rings, key=_ring_area)
    xs, ys = [point[0] for point in ring], [point[1] for point in ring]
    left, right, bottom, top = min(xs), max(xs), min(ys), max(ys)
    points: list[tuple[float, float]] = []
    candidate = 1
    while len(points) < count and candidate <= max(10_000, count * 100):
        lon = left + _halton(candidate, 2) * (right - left)
        lat = bottom + _halton(candidate, 3) * (top - bottom)
        if _point_in_geometry(lon, lat, geometry):
            points.append((lon, lat))
        candidate += 1
    if len(points) < count:
        centroid_lon = sum(xs) / len(xs)
        centroid_lat = sum(ys) / len(ys)
        points.extend([(centroid_lon, centroid_lat)] * (count - len(points)))
    return points


def _anchor_layout_points(anchor: tuple[float, float, float, float], count: int) -> list[tuple[float, float]]:
    lon, lat, width, height = anchor
    return [
        (lon + (_halton(index, 2) - 0.5) * width, lat + (_halton(index, 3) - 0.5) * height)
        for index in range(1, count + 1)
    ]


class Catalog:
    def __init__(self) -> None:
        self.geometry = json.loads((DATA_DIR / "africa_countries.geojson").read_text(encoding="utf-8"))
        waterbody_file = DATA_DIR / "africa_major_lakes.geojson"
        self.waterbodies = (
            json.loads(waterbody_file.read_text(encoding="utf-8"))
            if waterbody_file.exists()
            else {"type": "FeatureCollection", "features": []}
        )
        self.country_features: list[tuple[str, str, Mapping[str, Any]]] = []
        self.country_geometry: dict[str, Mapping[str, Any]] = {}
        for feature in self.geometry.get("features", []):
            props = feature.get("properties", {})
            iso3 = str(props.get("ISO_A3") or props.get("ADM0_A3") or props.get("SOV_A3") or "")
            name = str(props.get("ADMIN") or props.get("NAME") or iso3)
            self.country_features.append((iso3, name, feature.get("geometry", {})))
            if iso3 and iso3 != "-99":
                self.country_geometry[iso3] = feature.get("geometry", {})
        self.country_map_anchor: dict[str, tuple[float, float]] = {
            iso3: _country_layout_points(geometry, 1)[0]
            for iso3, geometry in self.country_geometry.items()
            if _country_layout_points(geometry, 1)
        }
        self.country_map_anchor.update({iso3: (value[0], value[1]) for iso3, value in COUNTRY_LAYOUT_ANCHORS.items()})
        self.nodes: dict[str, dict[str, Any]] = {}
        self.routes: dict[str, dict[str, Any]] = {}
        self.evidence_records: dict[str, dict[str, Any]] = {}
        self.node_domains: dict[str, set[str]] = {}
        self.node_commodities: dict[str, set[str]] = {}
        self.node_commodity_groups: dict[str, set[str]] = {}
        road_path_file = DATA_DIR / "africa_route_display_geometries.json"
        self.route_display_geometry_payload: dict[str, Any] = (
            json.loads(road_path_file.read_text(encoding="utf-8")) if road_path_file.exists() else {}
        )
        self.evidence_access_mode = "bundled_editor_private" if (DATA_DIR / "atlas_evidence_ledger.csv").exists() else "external_file_on_demand"
        self._load_evidence_records()
        self._load_nodes()
        self._load_continental_support_nodes()
        self._load_reconciled_coordinates()
        self._load_routes()
        self._attach_route_display_geometry()
        self._attach_evidence_records()
        self._assign_map_positions()
        self.domestic_routes: dict[str, dict[str, Any]] = {
            route_id: route for route_id, route in self.routes.items() if route["network_scope"] == "within-country operational route"
        }
        self.verified_trade_routes: dict[str, dict[str, Any]] = {
            route_id: route for route_id, route in self.routes.items() if route["trade_eligible"]
        }
        self.operational_routes: dict[str, dict[str, Any]] = {**self.domestic_routes, **self.verified_trade_routes}
        self.quarantined_cross_border_routes: dict[str, dict[str, Any]] = {
            route_id: route
            for route_id, route in self.routes.items()
            if route["network_scope"] == "quarantined unsupported cross-border source record"
        }

    def _attach_route_display_geometry(self) -> None:
        """Attach only a compact path reference; the OD edge itself is unchanged."""
        mappings = self.route_display_geometry_payload.get("route_paths", {})
        for route_id, mapping in mappings.items():
            if route_id not in self.routes:
                continue
            route = self.routes[route_id]
            route["road_display_path_id"] = mapping.get("path_id")
            route["road_display_source"] = mapping.get("source")
            route["road_display_available"] = True

    def route_display_geometries(self, query: Mapping[str, list[str]]) -> dict[str, object]:
        """Return de-duplicated display paths for the currently filtered routes."""
        include_trade = query.get("include_trade", ["false"])[0].casefold() in {"1", "true", "yes"}
        source = self.operational_routes if include_trade else self.domestic_routes
        route_ids = {
            route_id
            for route_id, route in source.items()
            if route.get("road_display_path_id") and self._matches(route, query, node=False)
        }
        all_mappings = self.route_display_geometry_payload.get("route_paths", {})
        mappings = {route_id: all_mappings[route_id] for route_id in route_ids if route_id in all_mappings}
        path_ids = {str(mapping.get("path_id")) for mapping in mappings.values() if mapping.get("path_id")}
        all_paths = self.route_display_geometry_payload.get("paths", {})
        paths = {path_id: all_paths[path_id] for path_id in path_ids if path_id in all_paths}
        return {
            "geometry_role": self.route_display_geometry_payload.get("geometry_role"),
            "interpretive_boundary": self.route_display_geometry_payload.get("interpretive_boundary"),
            "supported_countries": self.route_display_geometry_payload.get("supported_countries", []),
            "country_statistics": self.route_display_geometry_payload.get("country_statistics", {}),
            "route_count": len(mappings),
            "path_count": len(paths),
            "route_paths": mappings,
            "paths": paths,
        }

    def _load_evidence_records(self) -> None:
        """Load the frozen chemistry ledger without upgrading any claim."""
        if not (DATA_DIR / "atlas_evidence_ledger.csv").exists():
            return
        for row in _csv("atlas_evidence_ledger.csv"):
            evidence_id = str(row.get("atlas_unit_id") or "").strip()
            if not evidence_id:
                continue
            evidence_key = evidence_id
            duplicate_index = 2
            while evidence_key in self.evidence_records:
                evidence_key = f"{evidence_id}#{duplicate_index}"
                duplicate_index += 1
            self.evidence_records[evidence_key] = {
                "evidence_key": evidence_key,
                "evidence_id": evidence_id,
                "source_record_id": row.get("source_record_id", ""),
                "country": row.get("country", ""),
                "iso3": row.get("iso3", ""),
                "food_domain": row.get("food_domain", ""),
                "source_node": row.get("source_node", ""),
                "destination_node": row.get("destination_node", ""),
                "route_as_reported": row.get("route_as_reported", ""),
                "commodity_or_species": row.get("commodity_or_species", ""),
                "chemistry_or_contaminants": row.get("chemistry_or_contaminants", ""),
                "decision_status": row.get("decision_status", ""),
                "route_evidence_class": row.get("route_evidence_class", ""),
                "consumption_input_status": row.get("consumption_input_status", ""),
                "coordinate_status": row.get("coordinate_status", ""),
                "provenance_status": row.get("provenance_status", ""),
                "source_citation": row.get("source_citation", ""),
                "source_locator": row.get("source_locator", ""),
                "claim_boundary": row.get("claim_boundary", ""),
                "merge_key": row.get("merge_key", ""),
                "origin_release": row.get("origin_release", ""),
            }

    def _evidence_ids_in(self, *values: object) -> list[str]:
        text = " | ".join(str(value or "") for value in values)
        return [
            evidence_key
            for evidence_key, record in self.evidence_records.items()
            if str(record["evidence_id"]) in text
        ]

    def _attach_evidence_records(self) -> None:
        """Attach only explicit source-reference links; never infer chemistry flow."""
        for node in self.nodes.values():
            evidence_ids = self._evidence_ids_in(node.get("provenance"), node.get("source_references"))
            node["evidence_ids"] = evidence_ids
            node["evidence_record_count"] = len(evidence_ids)
        for route in self.routes.values():
            direct_ids = self._evidence_ids_in(route.get("provenance"), route.get("source_reference"))
            source_ids = list(self.nodes.get(str(route.get("from_node_id")), {}).get("evidence_ids", []))
            destination_ids = list(self.nodes.get(str(route.get("to_node_id")), {}).get("evidence_ids", []))
            route["direct_evidence_ids"] = direct_ids
            route["source_node_evidence_ids"] = source_ids
            route["destination_node_evidence_ids"] = destination_ids
            route["evidence_ids"] = list(dict.fromkeys([*direct_ids, *source_ids, *destination_ids]))
            route["evidence_record_count"] = len(route["evidence_ids"])

    def evidence_trace(self, kind: str, object_id: str) -> dict[str, object]:
        """Return provenance-bound evidence context for one selected object."""
        if kind == "node":
            value = self.nodes[object_id]
            link_sets = {"direct_object_reference": list(value.get("evidence_ids", []))}
        else:
            value = self.routes[object_id]
            link_sets = {
                "direct_route_reference": list(value.get("direct_evidence_ids", [])),
                "source_node_reference": list(value.get("source_node_evidence_ids", [])),
                "destination_node_reference": list(value.get("destination_node_evidence_ids", [])),
            }
        records: list[dict[str, Any]] = []
        seen: set[str] = set()
        for link_role, evidence_ids in link_sets.items():
            for evidence_id in evidence_ids:
                if evidence_id in seen or evidence_id not in self.evidence_records:
                    continue
                seen.add(evidence_id)
                records.append({**self.evidence_records[evidence_id], "link_role": link_role})
        return {
            "object_kind": kind,
            "object_id": object_id,
            "status": "linked_records_available" if records else "no_explicit_provenance_link",
            "record_count": len(records),
            "records": records,
            "boundary": (
                "Records are linked only through explicit frozen source references. Chemistry is not propagated "
                "to an unmatched commodity, route or CPC state."
            ),
        }

    def country_for_point(self, lon: float, lat: float) -> tuple[str, str]:
        for iso3, name, geometry in self.country_features:
            if _point_in_geometry(lon, lat, geometry):
                return iso3, name
        return "", "Unresolved"

    def _load_nodes(self) -> None:
        for row in _csv("edflow_node_registry_v1_1.csv"):
            node_id = row["node_id"]
            self.nodes[node_id] = {
                "id": node_id,
                "name": row["display_name"],
                "country": row["country"],
                "iso3": row["iso3"],
                "roles": _split(row["roles"]),
                "food_domains": _normal_domains(_split(row["food_domains"])),
                "node_class": row["node_class"],
                "node_layer": row["node_layer"],
                "commodity": row["commodity_label"],
                "product_form": row["product_form"],
                "coordinate_status": row["coordinate_status"],
                "parent_node_id": row.get("parent_node_id", ""),
                "base_spatial_node_id": row.get("base_spatial_node_id", ""),
                "lon": None,
                "lat": None,
                "provenance": row["source_references"],
                "source_release": "NF_TEMFLOW_skeleton_harmonization_v1_1_0_2026-08-29",
            }
        for row in _csv("karg_nodes_aggregated.csv"):
            lon, lat = float(row["longitude"]), float(row["latitude"])
            iso3, country = self.country_for_point(lon, lat)
            roles = []
            if int(row["source_observations"]) > 0:
                roles.append("observed source endpoint")
            if int(row["destination_observations"]) > 0:
                roles.append("observed destination endpoint")
            self.nodes[row["node_id"]] = {
                "id": row["node_id"],
                "name": row["node_name"],
                "country": country,
                "iso3": iso3,
                "roles": roles,
                "food_domains": [],
                "node_class": "geocoded benchmark OD endpoint",
                "node_layer": "spatial",
                "commodity": "",
                "product_form": "",
                "coordinate_status": "reported geocoded benchmark endpoint",
                "lon": lon,
                "lat": lat,
                "provenance": row["provenance"],
                "source_release": "TEMFLOW_Patterns_fallback_v0_1_0_2026-08-27",
                "source_observations": int(row["source_observations"]),
                "destination_observations": int(row["destination_observations"]),
            }
        self._load_ethiopia_topology_nodes()

    def _load_continental_support_nodes(self) -> None:
        """Load the 54-country geolocated support grid without upgrading it to observed flow."""
        for row in _csv("continental_geolocated_nodes_v1_2.csv"):
            lon, lat = float(row["longitude"]), float(row["latitude"])
            self.nodes[row["node_id"]] = {
                "id": row["node_id"],
                "name": row["node_name"],
                "country": row["country"],
                "iso3": row["iso3"],
                "roles": [row["node_role"]],
                "food_domains": _normal_domains(_split(row["food_domains"])),
                "node_class": "geolocated national model-support node",
                "node_layer": "continental_model_support",
                "commodity": "",
                "product_form": "",
                "coordinate_status": row["coordinate_source"],
                "lon": lon,
                "lat": lat,
                "provenance": f"{row['coordinate_source']}; GeoNames ID {row['coordinate_source_id']}",
                "source_release": row["origin_release"],
                "evidence_state": row["evidence_class"],
                "claim_boundary": row["claim_boundary"],
            }

    def _load_reconciled_coordinates(self) -> None:
        """Apply only audited exact or manually reviewed predecessor matches."""
        coordinate_file = DATA_DIR / "node_coordinate_reconciliation_v1_0_0.csv"
        if not coordinate_file.exists():
            return
        for row in _csv("node_coordinate_reconciliation_v1_0_0.csv"):
            node = self.nodes.get(str(row.get("target_node_id") or ""))
            if node is None:
                continue
            node["lon"] = float(row["longitude"])
            node["lat"] = float(row["latitude"])
            node["coordinate_status"] = row["coordinate_status"]
            node["coordinate_precision"] = row["coordinate_precision"]
            node["coordinate_match_rule"] = row["match_rule"]
            node["coordinate_display_role"] = "audited named-feature representative; not a sampling coordinate"
            node["provenance"] = f"{node.get('provenance', '')}; {row['verification_source']}; {row['source_register_ref']}"

    def _load_ethiopia_topology_nodes(self) -> None:
        """Expose the verified Ethiopian fish-flow topology without changing its evidence labels."""
        for row in _csv("../ethiopia_nodes.csv"):
            lon, lat = float(row["Longitude"]), float(row["Latitude"])
            iso3, country = self.country_for_point(lon, lat)
            self.nodes[row["Node ID"]] = {
                "id": row["Node ID"],
                "name": row["Display name"],
                "country": country,
                "iso3": iso3,
                "roles": [value for value in (row["Node role"], row["Transit/interception role"]) if value],
                "food_domains": ["fish"],
                "node_class": row["Map class"],
                "node_layer": "Ethiopian fish-flow candidate topology",
                "commodity": "fish and seafood (unspecified)",
                "commodities": ["fish and seafood (unspecified)"],
                "commodity_groups": ["Mixed or aggregate seafood"],
                "product_form": "unspecified fish or seafood",
                "coordinate_status": row["Coordinate status"],
                "lon": lon,
                "lat": lat,
                "provenance": f"{row['Coordinate provenance']}; {row['Evidence state']}",
                "source_release": "TEMFLOW_Patterns_private_engine_v1_0_0_2026-08-29",
                "corridor_codes": _split(row["Corridor code(s)"]),
                "evidence_state": row["Evidence state"],
                "absorption_prior_tier": row["Absorption prior tier"],
            }
        for row in _csv("../ethiopia_sources.csv"):
            lon, lat = float(row["Longitude"]), float(row["Latitude"])
            iso3, country = self.country_for_point(lon, lat)
            self.nodes[row["Source ID"]] = {
                "id": row["Source ID"],
                "name": row["Source/system name"],
                "country": country,
                "iso3": iso3,
                "roles": ["production source"],
                "food_domains": ["fish"],
                "node_class": row["Source class"],
                "node_layer": "Ethiopian fish-flow candidate topology",
                "commodity": "fish and seafood (unspecified)",
                "commodities": ["fish and seafood (unspecified)"],
                "commodity_groups": ["Mixed or aggregate seafood"],
                "product_form": "unspecified fish or seafood",
                "coordinate_status": row["Coordinate status"],
                "lon": lon,
                "lat": lat,
                "provenance": f"{row['Coordinate provenance']}; {row['Evidence state']}",
                "source_release": "TEMFLOW_Patterns_private_engine_v1_0_0_2026-08-29",
                "corridor_codes": _split(row["Candidate corridor(s)"]),
                "evidence_state": row["Evidence state"],
                "quantity_status": row["Current quantity status"],
                "region": row["Region"],
            }

    def _register_route(self, route: dict[str, Any]) -> None:
        domains = _normal_domains(route.get("food_domains", [route.get("food_domain", "")]))
        route["food_domains"] = domains
        route["food_domain"] = domains[0] if len(domains) == 1 else "mixed" if domains else "unspecified"
        commodity = str(route.get("commodity") or "").strip()
        route["commodity_groups"] = _commodity_groups(commodity, domains)
        self.routes[route["id"]] = route
        for node_id in (route["from_node_id"], route["to_node_id"]):
            for domain in domains:
                self.node_domains.setdefault(node_id, set()).add(domain)
            if commodity:
                self.node_commodities.setdefault(node_id, set()).add(commodity)
            self.node_commodity_groups.setdefault(node_id, set()).update(route["commodity_groups"])

    def _load_routes(self) -> None:
        for row in _csv("edflow_edge_registry_v1_1.csv"):
            self._register_route(
                {
                    "id": row["edge_id"],
                    "from_node_id": row["from_node_id"],
                    "to_node_id": row["to_node_id"],
                    "country": row["country_context"],
                    "iso3": row["iso3_context"],
                    "origin_iso3": row["origin_iso3"],
                    "destination_iso3": row["destination_iso3"],
                    "cross_border": row["cross_border"],
                    "food_domain": row["food_domain"].casefold(),
                    "commodity": row["commodity_or_form"],
                    "route_kind": row["edge_kind"],
                    "evidence_class": row["evidence_class"],
                    "quantity": row["quantity_tonnes"],
                    "quantity_period": row["quantity_period"],
                    "provenance": row["source_reference"],
                    "geometry_role": "registry relation; no point geometry asserted",
                    "source_release": row["origin_release"],
                    "source_lon": None,
                    "source_lat": None,
                    "destination_lon": None,
                    "destination_lat": None,
                }
            )
        for row in _csv("karg_routes_by_commodity.csv"):
            origin = self.nodes.get(row["from_node_id"], {})
            destination = self.nodes.get(row["to_node_id"], {})
            self._register_route(
                {
                    "id": row["route_id"],
                    "from_node_id": row["from_node_id"],
                    "to_node_id": row["to_node_id"],
                    "from_name": row["source_name"],
                    "to_name": row["destination_name"],
                    "country": destination.get("country", ""),
                    "iso3": destination.get("iso3", ""),
                    "origin_iso3": origin.get("iso3", ""),
                    "destination_iso3": destination.get("iso3", ""),
                    "cross_border": "yes" if origin.get("iso3") != destination.get("iso3") else "no",
                    "food_domain": row["food_domain"].casefold(),
                    "commodity": row["commodity"],
                    "route_kind": "observed benchmark endpoint pair",
                    "evidence_class": "observed commodity-specific OD support",
                    "quantity": float(row["adjusted_daily_mass_sum"]),
                    "quantity_period": f"daily adjusted mass; observations {row['first_year']}-{row['last_year']}",
                    "provenance": row["provenance"],
                    "geometry_role": row["geometry_role"],
                    "source_release": "TEMFLOW_Patterns_private_engine_v1_0_0_2026-08-29",
                    "source_lon": float(row["source_lon"]),
                    "source_lat": float(row["source_lat"]),
                    "destination_lon": float(row["destination_lon"]),
                    "destination_lat": float(row["destination_lat"]),
                    "observation_count": int(row["observation_count"]),
                    "survey_city": row["survey_city"],
                }
            )
        for index, row in enumerate(_csv("../ethiopia_edges.csv"), start=1):
            origin = self.nodes[row["from_id"]]
            destination = self.nodes[row["to_id"]]
            self._register_route(
                {
                    "id": f"ETHMAP_EDGE_{index:03d}",
                    "from_node_id": row["from_id"],
                    "to_node_id": row["to_id"],
                    "from_name": origin["name"],
                    "to_name": destination["name"],
                    "country": "Ethiopia",
                    "iso3": "ETH",
                    "origin_iso3": origin["iso3"],
                    "destination_iso3": destination["iso3"],
                    "cross_border": "yes" if origin["iso3"] != destination["iso3"] else "no",
                    "food_domain": "fish",
                    "commodity": "fish and seafood (unspecified)",
                    "route_kind": row["qualitative_role"],
                    "evidence_class": row["evidence_state"],
                    "quantity": "",
                    "quantity_period": "",
                    "provenance": f"ethiopia_edges.csv; {row['evidence_state']}",
                    "geometry_role": "verified endpoint link; not an asserted physical path",
                    "source_release": "TEMFLOW_Patterns_private_engine_v1_0_0_2026-08-29",
                    "source_lon": origin["lon"],
                    "source_lat": origin["lat"],
                    "destination_lon": destination["lon"],
                    "destination_lat": destination["lat"],
                    "corridor_id": row["corridor_id"],
                    "corridor_name": row["corridor_name"],
                    "branch": row["branch"],
                    "segment_order": row["segment_order"],
                }
            )
        for row in _csv("continental_candidate_national_routes_v1_2.csv"):
            origin = self.nodes[row["from_node_id"]]
            destination = self.nodes[row["to_node_id"]]
            self._register_route(
                {
                    "id": row["route_id"],
                    "from_node_id": row["from_node_id"],
                    "to_node_id": row["to_node_id"],
                    "from_name": row["from_name"],
                    "to_name": row["to_name"],
                    "country": row["country"],
                    "iso3": row["iso3"],
                    "origin_iso3": row["iso3"],
                    "destination_iso3": row["iso3"],
                    "cross_border": "no",
                    "food_domains": _split(row["food_domains"]),
                    "commodity": "",
                    "route_kind": row["route_kind"],
                    "evidence_class": row["evidence_class"],
                    "quantity": "",
                    "quantity_period": "",
                    "provenance": row["source_reference"],
                    "geometry_role": row["road_geometry_status"],
                    "source_release": row["origin_release"],
                    "source_lon": origin["lon"],
                    "source_lat": origin["lat"],
                    "destination_lon": destination["lon"],
                    "destination_lat": destination["lat"],
                    "distance_km": float(row["great_circle_distance_km"]),
                    "quantitative_state": row["quantitative_state"],
                    "mass_balance_use": row["mass_balance_use"],
                    "claim_boundary": row["claim_boundary"],
                }
            )
        for node_id, domains in self.node_domains.items():
            if node_id in self.nodes:
                self.nodes[node_id]["food_domains"] = sorted(set(self.nodes[node_id].get("food_domains", [])) | domains)
                self.nodes[node_id]["commodities"] = sorted(self.node_commodities.get(node_id, set()), key=str.casefold)
                self.nodes[node_id]["commodity_groups"] = sorted(self.node_commodity_groups.get(node_id, set()), key=str.casefold)

    def _assign_map_positions(self) -> None:
        """Keep true coordinates separate from country-layout topology proxies."""
        for node in self.nodes.values():
            parent_id = str(node.get("base_spatial_node_id") or node.get("parent_node_id") or "")
            parent = self.nodes.get(parent_id)
            if parent and parent.get("lon") is not None and parent.get("lat") is not None:
                node["lon"] = parent["lon"]
                node["lat"] = parent["lat"]
                node["coordinate_status"] = f"inherits reconciled spatial parent {parent_id}"
                node["coordinate_precision"] = parent.get("coordinate_precision", "")
                node["coordinate_display_role"] = "inherited audited parent representative; not a sampling coordinate"
        unresolved_by_country: dict[str, list[dict[str, Any]]] = {}
        for node in self.nodes.values():
            if node.get("lon") is not None and node.get("lat") is not None:
                node["map_lon"] = node["lon"]
                node["map_lat"] = node["lat"]
                node["map_position_kind"] = node.get("coordinate_display_role", "reported or verified coordinate")
            elif node.get("iso3"):
                unresolved_by_country.setdefault(str(node["iso3"]), []).append(node)
        for iso3, nodes in unresolved_by_country.items():
            geometry = self.country_geometry.get(iso3)
            anchor = COUNTRY_LAYOUT_ANCHORS.get(iso3)
            if not geometry and not anchor:
                continue
            ordered = sorted(nodes, key=lambda node: str(node["id"]))
            positions = _country_layout_points(geometry, len(ordered)) if geometry else _anchor_layout_points(anchor, len(ordered))  # type: ignore[arg-type]
            for node, (lon, lat) in zip(ordered, positions):
                node["map_lon"] = lon
                node["map_lat"] = lat
                node["map_position_kind"] = (
                    "country-layout proxy; not a reported node coordinate"
                    if geometry
                    else "island-state layout proxy; not a reported node coordinate"
                )
        for route in self.routes.values():
            origin = self.nodes.get(str(route.get("from_node_id")), {})
            destination = self.nodes.get(str(route.get("to_node_id")), {})
            route["from_name"] = str(route.get("from_name") or origin.get("name") or route.get("from_node_id") or "Source")
            route["to_name"] = str(route.get("to_name") or destination.get("name") or route.get("to_node_id") or "Destination")
            route["source_map_lon"] = origin.get("map_lon")
            route["source_map_lat"] = origin.get("map_lat")
            route["destination_map_lon"] = destination.get("map_lon")
            route["destination_map_lat"] = destination.get("map_lat")
            route["map_geometry_status"] = (
                "reported or verified endpoint coordinates"
                if origin.get("lon") is not None and destination.get("lon") is not None
                else "country-layout endpoint proxy; topology only"
            )
            origin_anchor = self.country_map_anchor.get(str(route.get("origin_iso3") or ""))
            destination_anchor = self.country_map_anchor.get(str(route.get("destination_iso3") or ""))
            route["origin_country_map_lon"] = origin_anchor[0] if origin_anchor else None
            route["origin_country_map_lat"] = origin_anchor[1] if origin_anchor else None
            route["destination_country_map_lon"] = destination_anchor[0] if destination_anchor else None
            route["destination_country_map_lat"] = destination_anchor[1] if destination_anchor else None
            origin_iso3 = str(route.get("origin_iso3") or "")
            destination_iso3 = str(route.get("destination_iso3") or "")
            within_country = bool(origin_iso3 and destination_iso3 and origin_iso3 == destination_iso3)
            try:
                positive_quantity = float(str(route.get("quantity") or "").replace(",", "")) > 0
            except ValueError:
                positive_quantity = False
            trade_classes = {
                "formal customs directed country-pair and product-form evidence",
                "observed commodity-specific OD support",
            }
            route["trade_eligible"] = bool(
                origin_iso3
                and destination_iso3
                and origin_iso3 != destination_iso3
                and positive_quantity
                and str(route.get("evidence_class") or "") in trade_classes
            )
            route["network_eligible"] = within_country or route["trade_eligible"]
            route["network_scope"] = (
                "within-country operational route"
                if within_country
                else "verified import/export route; optional overlay"
                if route["trade_eligible"]
                else "quarantined unsupported cross-border source record"
            )

    def has_object(self, kind: str, object_id: str) -> bool:
        return object_id in (self.nodes if kind == "node" else self.routes if kind == "route" else {})

    @staticmethod
    def _matches(value: Mapping[str, Any], query: Mapping[str, list[str]], *, node: bool) -> bool:
        countries = set(_filter_parts(query.get("country", [])))
        domains = {part.casefold() for part in _filter_parts(query.get("domain", []))}
        commodities = {part.casefold() for part in _filter_parts(query.get("commodity", []))}
        commodity_groups = {part.casefold() for part in _filter_parts(query.get("commodity_group", []))}
        search = query.get("search", [""])[0].strip().casefold()
        if countries and str(value.get("iso3")) not in countries and str(value.get("country")) not in countries:
            if not node or not ({str(value.get("origin_iso3")), str(value.get("destination_iso3"))} & countries):
                return False
        value_domains = value.get("food_domains", [])
        if domains and not ({str(item).casefold() for item in value_domains} & domains):
            return False
        value_commodities = value.get("commodities", []) if node else [value.get("commodity", "")]
        if commodities and not ({str(item).casefold() for item in value_commodities} & commodities):
            return False
        value_groups = value.get("commodity_groups", [])
        if commodity_groups and not ({str(item).casefold() for item in value_groups} & commodity_groups):
            return False
        if search and search not in " ".join(str(item) for item in value.values()).casefold():
            return False
        return True

    def query(self, kind: str, query: Mapping[str, list[str]]) -> dict[str, object]:
        include_trade = query.get("include_trade", ["false"])[0].casefold() in {"1", "true", "yes"}
        source = self.nodes if kind == "node" else self.operational_routes if include_trade else self.domestic_routes
        rows = [value for value in source.values() if self._matches(value, query, node=kind == "node")]
        rows.sort(key=lambda row: (str(row.get("country", "")), str(row.get("name", row.get("id", "")))))
        offset = max(0, int(query.get("offset", ["0"])[0]))
        maximum = 20000
        limit = min(maximum, max(1, int(query.get("limit", [str(maximum)])[0])))
        return {"total": len(rows), "offset": offset, "limit": limit, "items": rows[offset : offset + limit]}


CATALOG = Catalog()


def _merge(base: Mapping[str, Any], revision: Mapping[str, Any] | None) -> dict[str, Any]:
    result = dict(base)
    if revision:
        result.update(dict(revision.get("attributes", {})))
        result["active_revision_id"] = revision["revision_id"]
        result["effective_at"] = revision["effective_at"]
        result["revision_status"] = revision["status"]
    else:
        result["active_revision_id"] = "BASE"
        result["revision_status"] = "approved"
    return result


def _optional_float(value: object, name: str, minimum: float | None = None, maximum: float | None = None) -> float | None:
    if value in (None, ""):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be numeric") from exc
    if not math.isfinite(number):
        raise ValueError(f"{name} must be finite")
    if minimum is not None and number < minimum:
        raise ValueError(f"{name} must be at least {minimum}")
    if maximum is not None and number > maximum:
        raise ValueError(f"{name} must be at most {maximum}")
    return number


def _country_name(iso3: str) -> str:
    match = next((name for code, name, _ in CATALOG.country_features if code == iso3), "")
    if match:
        return match
    return {
        "CPV": "Cabo Verde", "COM": "Comoros", "MUS": "Mauritius",
        "SYC": "Seychelles", "STP": "São Tomé and Príncipe",
    }.get(iso3, "")


def _candidate_domains(value: Mapping[str, object]) -> list[str]:
    raw = value.get("food_domains", value.get("food_domain", []))
    values = [raw] if isinstance(raw, str) else list(raw or [])
    domains = _normal_domains(values)
    if not domains:
        raise ValueError("food_domains must identify fish/seafood or vegetables")
    return domains


def _prepare_user_node(value: Mapping[str, object]) -> dict[str, Any]:
    name = str(value.get("name", "")).strip()
    iso3 = str(value.get("iso3", value.get("country_iso3", ""))).strip().upper()
    if not name:
        raise ValueError("node name is required")
    country = _country_name(iso3)
    if not country:
        raise ValueError("iso3 must identify a supported African country")
    lon = _optional_float(value.get("lon"), "longitude", -180, 180)
    lat = _optional_float(value.get("lat"), "latitude", -90, 90)
    if lon is None or lat is None:
        raise ValueError("new nodes require longitude and latitude")
    detected_iso3, _ = CATALOG.country_for_point(lon, lat)
    if detected_iso3 and detected_iso3 != iso3:
        raise ValueError(f"coordinates fall in {detected_iso3}, not {iso3}")
    domains = _candidate_domains(value)
    commodity = str(value.get("commodity", "")).strip()
    if not commodity:
        raise ValueError("commodity is required")
    roles_raw = value.get("roles", [])
    roles = _split(roles_raw) if isinstance(roles_raw, str) else [str(item).strip() for item in roles_raw or [] if str(item).strip()]
    if not roles:
        raise ValueError("at least one node role is required")
    object_id = str(value.get("id", "")).strip()
    return {
        "id": object_id,
        "name": name,
        "country": country,
        "iso3": iso3,
        "roles": roles,
        "food_domains": domains,
        "node_class": str(value.get("node_class", "curator-registered OD node")).strip(),
        "node_layer": "private append-only continental topology",
        "commodity": commodity,
        "commodities": [commodity],
        "commodity_groups": _commodity_groups(commodity, domains),
        "product_form": str(value.get("product_form", "")).strip(),
        "coordinate_status": "privileged curator-entered coordinates",
        "lon": lon,
        "lat": lat,
        "map_lon": lon,
        "map_lat": lat,
        "map_position_kind": "privileged curator-entered coordinate",
        "provenance": str(value.get("provenance", "")).strip(),
        "source_release": "private additive topology ledger",
        "evidence_ids": [],
        "evidence_record_count": 0,
        "user_defined": True,
    }


def _prepare_user_route(value: Mapping[str, object], nodes: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    from_id = str(value.get("from_node_id", value.get("from_id", ""))).strip()
    to_id = str(value.get("to_node_id", value.get("to_id", ""))).strip()
    if from_id == to_id or from_id not in nodes or to_id not in nodes:
        raise ValueError("route endpoints must be two different registered nodes")
    origin, destination = nodes[from_id], nodes[to_id]
    domains = _candidate_domains(value)
    commodity = str(value.get("commodity", "")).strip()
    if not commodity:
        raise ValueError("commodity is required")
    evidence_class = str(value.get("evidence_class", "")).strip()
    if not evidence_class:
        raise ValueError("route evidence_class is required")
    quantity = _optional_float(value.get("quantity"), "quantity", 0)
    origin_iso3 = str(origin.get("iso3", ""))
    destination_iso3 = str(destination.get("iso3", ""))
    within_country = bool(origin_iso3 and origin_iso3 == destination_iso3)
    trade_classes = {
        "formal customs directed country-pair and product-form evidence",
        "observed commodity-specific OD support",
    }
    trade_eligible = bool(not within_country and quantity is not None and quantity > 0 and evidence_class in trade_classes)
    source_lon, source_lat = origin.get("lon"), origin.get("lat")
    destination_lon, destination_lat = destination.get("lon"), destination.get("lat")
    object_id = str(value.get("id", "")).strip()
    origin_anchor = CATALOG.country_map_anchor.get(origin_iso3)
    destination_anchor = CATALOG.country_map_anchor.get(destination_iso3)
    return {
        "id": object_id,
        "from_node_id": from_id,
        "to_node_id": to_id,
        "from_name": origin.get("name", from_id),
        "to_name": destination.get("name", to_id),
        "country": origin.get("country", "") if within_country else f"{origin.get('country', origin_iso3)} → {destination.get('country', destination_iso3)}",
        "iso3": origin_iso3 if within_country else destination_iso3,
        "origin_iso3": origin_iso3,
        "destination_iso3": destination_iso3,
        "cross_border": "no" if within_country else "yes",
        "food_domains": domains,
        "food_domain": domains[0] if len(domains) == 1 else "mixed",
        "commodity": commodity,
        "commodity_groups": _commodity_groups(commodity, domains),
        "route_kind": str(value.get("route_kind", "curator-registered directed OD relation")).strip(),
        "evidence_class": evidence_class,
        "quantity": "" if quantity is None else quantity,
        "quantity_period": str(value.get("quantity_period", "")).strip(),
        "provenance": str(value.get("provenance", "")).strip(),
        "geometry_role": "user-entered endpoint relation; road alignment pending",
        "source_release": "private additive topology ledger",
        "source_lon": source_lon,
        "source_lat": source_lat,
        "destination_lon": destination_lon,
        "destination_lat": destination_lat,
        "source_map_lon": origin.get("map_lon", source_lon),
        "source_map_lat": origin.get("map_lat", source_lat),
        "destination_map_lon": destination.get("map_lon", destination_lon),
        "destination_map_lat": destination.get("map_lat", destination_lat),
        "map_geometry_status": "curator-entered endpoint coordinates; straight display pending road audit",
        "origin_country_map_lon": origin_anchor[0] if origin_anchor else None,
        "origin_country_map_lat": origin_anchor[1] if origin_anchor else None,
        "destination_country_map_lon": destination_anchor[0] if destination_anchor else None,
        "destination_country_map_lat": destination_anchor[1] if destination_anchor else None,
        "trade_eligible": trade_eligible,
        "network_eligible": within_country or trade_eligible,
        "network_scope": (
            "within-country operational route" if within_country else
            "verified import/export route; optional overlay" if trade_eligible else
            "quarantined unsupported cross-border source record"
        ),
        "direct_evidence_ids": [],
        "source_node_evidence_ids": list(origin.get("evidence_ids", [])),
        "destination_node_evidence_ids": list(destination.get("evidence_ids", [])),
        "evidence_ids": [],
        "evidence_record_count": 0,
        "user_defined": True,
    }


def _query_objects(kind: str, query: Mapping[str, list[str]], nodes: Mapping[str, Mapping[str, Any]], routes: Mapping[str, Mapping[str, Any]]) -> dict[str, object]:
    include_trade = query.get("include_trade", ["false"])[0].casefold() in {"1", "true", "yes"}
    if kind == "node":
        source = nodes
    else:
        source = {
            object_id: value for object_id, value in routes.items()
            if value.get("network_scope") == "within-country operational route" or (include_trade and value.get("trade_eligible"))
        }
    rows = [dict(value) for value in source.values() if CATALOG._matches(value, query, node=kind == "node")]
    rows.sort(key=lambda row: (str(row.get("country", "")), str(row.get("name", row.get("id", "")))))
    offset = max(0, int(query.get("offset", ["0"])[0]))
    maximum = 20000
    limit = min(maximum, max(1, int(query.get("limit", [str(maximum)])[0])))
    return {"total": len(rows), "offset": offset, "limit": limit, "items": rows[offset : offset + limit]}


class EngineHandler(BaseHTTPRequestHandler):
    server_version = f"TEMFLOWPrivate/{VERSION}"

    @property
    def store(self) -> RevisionStore:
        return self.server.revision_store  # type: ignore[attr-defined]

    @property
    def topology_store(self) -> TopologyStore:
        return self.server.topology_store  # type: ignore[attr-defined]

    @property
    def proposal_store(self) -> AIProposalStore:
        return self.server.proposal_store  # type: ignore[attr-defined]

    @property
    def ai_config(self) -> AIProviderConfig:
        return self.server.ai_config  # type: ignore[attr-defined]

    def _object_sources(self, *, include_drafts: bool = False, as_of: str | None = None, include_removed: bool = False) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
        nodes = {object_id: dict(value) for object_id, value in CATALOG.nodes.items()}
        routes = {object_id: dict(value) for object_id, value in CATALOG.routes.items()}
        as_of = as_of or datetime.now(timezone.utc).isoformat()
        additions = self.topology_store.objects(include_drafts=include_drafts, as_of=as_of)
        for kind, target in (("node", nodes), ("route", routes)):
            for object_id, record in additions[kind].items():
                value = dict(record.attributes)
                value["creation_record_id"] = record.record_id
                value["creation_status"] = record.status
                value["creation_effective_at"] = record.effective_at
                value["creation_source"] = record.source
                target[object_id] = value
        if not include_removed:
            removed = self.server.feature_changes.removed(as_of)
            removed_nodes = {oid for kind, oid in removed if kind == "node"}
            nodes = {oid: value for oid, value in nodes.items() if oid not in removed_nodes}
            routes = {oid: value for oid, value in routes.items()
                      if ("route", oid) not in removed
                      and not ({value.get("from_node_id"), value.get("to_node_id")} & removed_nodes)}
        return nodes, routes

    def _has_object(self, kind: str, object_id: str, *, include_drafts: bool = True) -> bool:
        nodes, routes = self._object_sources(include_drafts=include_drafts)
        return object_id in (nodes if kind == "node" else routes if kind == "route" else {})

    def _trace(self, kind: str, object_id: str) -> dict[str, object]:
        if CATALOG.has_object(kind, object_id):
            return CATALOG.evidence_trace(kind, object_id)
        return {
            "object_kind": kind,
            "object_id": object_id,
            "status": "private_additive_object_no_frozen_link",
            "record_count": 0,
            "records": [],
            "boundary": "This private additive object retains its own provenance. Frozen chemistry is not propagated to it without an explicit compatible evidence revision.",
        }

    def _append_topology(self, payload: Mapping[str, object], *, source: str = "manual-curator", proposal_id: str | None = None) -> TopologyRecord:
        with self.server.topology_edit_lock:
            return self._append_topology_unlocked(payload, source=source, proposal_id=proposal_id)

    def _append_topology_unlocked(self, payload: Mapping[str, object], *, source: str = "manual-curator", proposal_id: str | None = None) -> TopologyRecord:
        kind = str(payload.get("object_kind", payload.get("candidate_kind", ""))).strip().casefold()
        status = str(payload.get("status", "draft")).strip().casefold()
        current_nodes, current_routes = self._object_sources(include_drafts=status != "approved", as_of=str(payload.get("effective_at") or payload.get("observed_at") or datetime.now(timezone.utc).isoformat()))
        raw_attributes = payload.get("attributes")
        candidate = dict(raw_attributes) if isinstance(raw_attributes, Mapping) else dict(payload)
        candidate.pop("candidate_kind", None)
        candidate.pop("object_kind", None)
        candidate.pop("status", None)
        candidate.pop("observed_at", None)
        candidate.pop("effective_at", None)
        candidate.pop("change_reason", None)
        candidate.pop("source", None)
        candidate.pop("proposal_id", None)
        provenance = str(payload.get("provenance") or candidate.get("provenance") or "").strip()
        change_reason = str(payload.get("change_reason") or candidate.get("change_reason") or "").strip()
        if not provenance:
            raise ValueError("provenance is required")
        if not change_reason:
            raise ValueError("change_reason is required")
        candidate["provenance"] = provenance
        attributes = _prepare_user_node(candidate) if kind == "node" else _prepare_user_route(candidate, current_nodes) if kind == "route" else None
        if attributes is None:
            raise ValueError("object_kind must be node or route")
        object_id = str(payload.get("object_id") or candidate.get("id") or "").strip()
        if object_id and (object_id in CATALOG.nodes or object_id in CATALOG.routes or any(record.object_id == object_id for record in self.topology_store.records())):
            raise ValueError("object_id already exists in the frozen or additive registry")
        attributes["id"] = object_id
        return self.topology_store.append(
            {
                "object_kind": kind,
                "object_id": object_id,
                "observed_at": payload.get("observed_at") or candidate.get("observed_at"),
                "effective_at": payload.get("effective_at") or candidate.get("effective_at") or payload.get("observed_at") or candidate.get("observed_at"),
                "status": status,
                "actor": str(payload.get("actor", "private-engine-curator")),
                "provenance": provenance,
                "change_reason": change_reason,
                "attributes": attributes,
                "source": source,
                "proposal_id": proposal_id,
            }
        )

    def _feature_plan(self, payload):
        nodes, routes = self._object_sources(include_drafts=True, include_removed=True, as_of=str(payload.get("effective_at") or ""))
        registry_digest = PREVIEW_BUILD_ID + self.topology_store.digest(approved_only=False)
        return change_plan(payload, nodes, routes, self.server.feature_changes, registry_digest)

    def _activate_proposal(self, proposal: Mapping[str, object]) -> dict[str, object]:
        candidate = proposal.get("candidate")
        if not isinstance(candidate, Mapping):
            raise ValueError("proposal candidate is invalid")
        kind = str(candidate.get("candidate_kind", "")).strip().casefold()
        source_uri = str(proposal.get("source_uri", "")).strip()
        payload = dict(candidate)
        payload["provenance"] = str(payload.get("provenance") or source_uri)
        payload["status"] = "approved"
        payload["actor"] = "private-engine-human-approver"
        if kind in {"node", "route"}:
            record = self._append_topology(payload, source="ai-proposed-human-approved", proposal_id=str(proposal["proposal_id"]))
            return {"activation_kind": "topology", "object_kind": kind, "object_id": record.object_id, "record_id": record.record_id}
        if kind == "revision":
            object_kind = str(payload.get("object_kind", "")).strip().casefold()
            object_id = str(payload.get("object_id", "")).strip()
            if not self._has_object(object_kind, object_id):
                raise ValueError("AI revision target is not a registered node or route")
            attributes = payload.get("attributes")
            if not isinstance(attributes, Mapping):
                raise ValueError("AI revision attributes must be an object")
            revision = self.store.append(
                {
                    "object_kind": object_kind,
                    "object_id": object_id,
                    "observed_at": payload.get("observed_at"),
                    "effective_at": payload.get("effective_at") or payload.get("observed_at"),
                    "status": "approved",
                    "actor": "private-engine-human-approver",
                    "provenance": payload["provenance"],
                    "change_reason": str(payload.get("change_reason", "AI proposal human-reviewed and approved")),
                    "attributes": dict(attributes),
                }
            )
            return {"activation_kind": "revision", "object_kind": object_kind, "object_id": object_id, "revision_id": revision.revision_id}
        raise ValueError("unsupported AI candidate_kind")

    def _token(self) -> str:
        return self.headers.get("X-TEMFLOW-Token", "")

    def _authorized(self, write: bool = False) -> bool:
        view = self.server.view_token  # type: ignore[attr-defined]
        curator = self.server.curator_token  # type: ignore[attr-defined]
        if write:
            return curator is None or self._token() == curator
        return view is None or self._token() in {view, curator}

    def _json(self, status: int, value: object) -> None:
        encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(encoded)

    def _body(self) -> dict[str, object]:
        length = int(self.headers.get("Content-Length", "0"))
        if not 0 < length <= 2_000_000:
            raise ValueError("invalid request size")
        value = json.loads(self.rfile.read(length).decode("utf-8"))
        if not isinstance(value, dict):
            raise ValueError("request body must be an object")
        return value

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlsplit(self.path)
        query = parse_qs(parsed.query)
        if parsed.path in {"/", "/index.html"}:
            encoded = UI_PATH.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(encoded)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(encoded)
            return
        if parsed.path == "/api/health":
            self._json(200, {"status": "ok", "version": VERSION, "private_review": True})
            return
        if not self._authorized():
            self._json(401, {"error": "private viewer token required"})
            return
        try:
            if parsed.path == "/api/metadata":
                visible_nodes, visible_routes = self._object_sources(include_drafts=False)
                operational_routes = {
                    route_id: route for route_id, route in visible_routes.items()
                    if route.get("network_scope") in {"within-country operational route", "verified import/export route; optional overlay"}
                }
                countries = sorted({(row["iso3"], row["country"]) for row in visible_nodes.values() if row.get("iso3")}, key=lambda item: item[1])
                commodities = sorted({str(route["commodity"]) for route in operational_routes.values() if route.get("commodity")}, key=str.casefold)
                commodity_domain_sets: dict[str, set[str]] = {}
                for route in operational_routes.values():
                    commodity = str(route.get("commodity") or "").strip()
                    if commodity:
                        commodity_domain_sets.setdefault(commodity, set()).update(route.get("food_domains", []))
                commodity_domains = {commodity: sorted(commodity_domain_sets.get(commodity, set())) for commodity in commodities}
                commodity_group_domains: dict[str, set[str]] = {}
                commodity_group_commodities: dict[str, set[str]] = {}
                for route in operational_routes.values():
                    commodity = str(route.get("commodity") or "").strip()
                    for group in route.get("commodity_groups", []):
                        commodity_group_domains.setdefault(group, set()).update(route.get("food_domains", []))
                        if commodity:
                            commodity_group_commodities.setdefault(group, set()).add(commodity)
                commodity_groups = sorted(commodity_group_domains, key=str.casefold)
                self._json(
                    200,
                    {
                        "version": VERSION,
                        "preview_build_id": PREVIEW_BUILD_ID,
                        "countries": [{"iso3": iso3, "name": name} for iso3, name in countries],
                        "domains": ["fish", "vegetable"],
                        "commodities": commodities,
                        "commodity_domains": commodity_domains,
                        "commodity_groups": commodity_groups,
                        "commodity_group_domains": {group: sorted(commodity_group_domains[group]) for group in commodity_groups},
                        "commodity_group_commodities": {group: sorted(commodity_group_commodities.get(group, set()), key=str.casefold) for group in commodity_groups},
                        "node_count": len(visible_nodes),
                        "route_count": sum(route.get("network_scope") == "within-country operational route" for route in visible_routes.values()),
                        "operational_route_count": len(operational_routes),
                        "verified_import_export_route_count": sum(bool(route.get("trade_eligible")) for route in visible_routes.values()),
                        "source_cross_border_record_count": len(CATALOG.routes) - len(CATALOG.domestic_routes),
                        "quarantined_cross_border_record_count": len(CATALOG.quarantined_cross_border_routes),
                        "contaminant_evidence_record_count": len(CATALOG.evidence_records),
                        "evidence_access_mode": CATALOG.evidence_access_mode,
                        "objects_with_explicit_evidence_links": sum(
                            1 for value in [*CATALOG.nodes.values(), *CATALOG.operational_routes.values()] if value.get("evidence_record_count")
                        ),
                        "road_display_supported_countries": CATALOG.route_display_geometry_payload.get("supported_countries", []),
                        "road_display_route_count": len(CATALOG.route_display_geometry_payload.get("route_paths", {})),
                        "major_lake_count": len(CATALOG.waterbodies.get("features", [])),
                        "default_view": "National OD networks first; verified positive-quantity import/export routes are available only through the optional trade overlay",
                        "can_curate": self._authorized(write=True),
                        "private_topology_record_count": len(self.topology_store.records()),
                        "pending_ai_proposal_count": sum(item["status"] == "pending" for item in self.proposal_store.proposals()),
                        "ai_provider": self.ai_config.public_metadata(),
                    },
                )
            elif parsed.path == "/api/geometry":
                self._json(200, CATALOG.geometry)
            elif parsed.path == "/api/waterbodies":
                self._json(200, CATALOG.waterbodies)
            elif parsed.path in {"/api/nodes", "/api/routes"}:
                kind = "node" if parsed.path.endswith("nodes") else "route"
                include_drafts = query.get("include_drafts", ["false"])[0].casefold() in {"1", "true", "yes"} and self._authorized(write=True)
                nodes, routes = self._object_sources(include_drafts=include_drafts, as_of=query.get("as_of", [None])[0])
                self._json(200, _query_objects(kind, query, nodes, routes))
            elif parsed.path == "/api/route-display-geometries":
                geometry = CATALOG.route_display_geometries(query)
                _, active_routes = self._object_sources(as_of=query.get("as_of", [None])[0])
                geometry["route_paths"] = {rid: mapping for rid, mapping in geometry.get("route_paths", {}).items() if rid in active_routes}
                used_paths = {item["path_id"] for item in geometry["route_paths"].values()}
                geometry["paths"] = {pid: path for pid, path in geometry.get("paths", {}).items() if pid in used_paths}
                self._json(200, geometry)
            elif parsed.path == "/api/object":
                kind = query.get("kind", [""])[0]
                object_id = query.get("id", [""])[0]
                as_of = query.get("as_of", [None])[0]
                include_drafts = query.get("include_drafts", ["false"])[0].casefold() == "true" and self._authorized(write=True)
                nodes, routes = self._object_sources(include_drafts=include_drafts, as_of=as_of)
                source = nodes if kind == "node" else routes if kind == "route" else {}
                if object_id not in source:
                    self._json(404, {"error": "object not found"})
                    return
                history = self.store.history(kind, object_id, include_drafts=include_drafts, as_of=as_of)
                latest = history[-1].to_dict() if history else None
                self._json(
                    200,
                    {
                        "kind": kind,
                        "base": source[object_id],
                        "current": _merge(source[object_id], latest),
                        "evidence_trace": self._trace(kind, object_id),
                        "history": [record.to_dict() for record in history],
                        "selected_history_index": len(history) - 1,
                    },
                )
            elif parsed.path == "/api/features/removed":
                if not self._authorized(write=True):
                    self._json(403, {"error": "private curator token required"})
                    return
                removed = self.server.feature_changes.removed(query.get("as_of", [None])[0])
                self._json(200, {"items": [item["target"] for item in removed.values()],
                                 "event_count": len(self.server.feature_changes.events())})
            elif parsed.path == "/api/topology":
                if not self._authorized(write=True):
                    self._json(403, {"error": "private curator token required"})
                    return
                records = [record.to_dict() for record in self.topology_store.records()]
                self._json(200, {"records": records, "ledger_digest": self.topology_store.digest(approved_only=False)})
            elif parsed.path == "/api/ai/status":
                if not self._authorized(write=True):
                    self._json(403, {"error": "private curator token required"})
                    return
                self._json(200, self.ai_config.public_metadata())
            elif parsed.path == "/api/ai/proposals":
                if not self._authorized(write=True):
                    self._json(403, {"error": "private curator token required"})
                    return
                self._json(200, {"proposals": self.proposal_store.proposals(), "ledger_digest": self.proposal_store.digest()})
            elif parsed.path == "/api/export-presets":
                self._json(
                    200,
                    {
                        "fish_seafood": {"domain": ["fish"], "geometry": "Africa", "route_detail": "compatible selected routes", "panel": "A"},
                        "vegetables": {"domain": ["vegetable"], "geometry": "Africa", "route_detail": "compatible selected routes", "panel": "B"},
                        "rule": "Static exports use approved frozen snapshots and panel letters only; descriptions belong in captions.",
                    },
                )
            else:
                self._json(404, {"error": "not found"})
        except (ValueError, TypeError) as exc:
            self._json(400, {"error": str(exc)})

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlsplit(self.path)
        curator_paths = {"/api/features/preview", "/api/features/apply", "/api/revisions", "/api/topology", "/api/ai/extract", "/api/ai/proposals", "/api/ai/decisions"}
        if not self._authorized(write=parsed.path in curator_paths):
            # Consume a bounded request body before closing the response; unread
            # TCP data can otherwise turn an intended 403 into a reset on Windows.
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if 0 < length <= 2_000_000:
                    self.connection.settimeout(2)
                    self.rfile.read(length)
            except (ValueError, OSError):
                pass
            self._json(403, {"error": "private curator token required"})
            return
        try:
            payload = self._body()
            if parsed.path == "/api/revisions":
                kind = str(payload.get("object_kind", ""))
                object_id = str(payload.get("object_id", ""))
                if not self._has_object(kind, object_id):
                    raise ValueError("revision target is not a registered node or route")
                self._json(201, {"revision": self.store.append(payload).to_dict(), "ledger_digest": self.store.digest()})
            elif parsed.path == "/api/topology":
                record = self._append_topology(payload)
                self._json(
                    201,
                    {
                        "record": record.to_dict(),
                        "ledger_digest": self.topology_store.digest(approved_only=False),
                        "frozen_register_modified": False,
                    },
                )
            elif parsed.path == "/api/features/preview":
                with self.server.topology_edit_lock:
                    self._json(200, self._feature_plan(payload))
            elif parsed.path == "/api/features/apply":
                with self.server.topology_edit_lock:
                    plan = self._feature_plan(payload)
                    if payload.get("expected_plan_id") != plan["plan_id"]:
                        self._json(409, {"error": "The network or selection changed. Review the affected features again."})
                        return
                    event = self.server.feature_changes.append(plan,
                        actor=str(payload.get("actor", "private-engine-curator")),
                        provenance=str(payload.get("provenance", "")).strip(),
                        change_reason=str(payload.get("change_reason", "")).strip())
                    self._json(201, {"event": event, "frozen_register_modified": False})
            elif parsed.path == "/api/ai/extract":
                candidate, metadata = extract_candidate(
                    self.ai_config,
                    source_uri=str(payload.get("source_uri", "")),
                    source_text=str(payload.get("source_text", "")),
                    requested_kind=str(payload.get("requested_kind", "auto")),
                )
                self._json(200, {"candidate": candidate, "ai_metadata": metadata, "activated": False, "human_approval_required": True})
            elif parsed.path == "/api/ai/proposals":
                proposal = self.proposal_store.create(
                    {
                        **payload,
                        "actor": str(payload.get("actor", "private-engine-curator")),
                    }
                )
                self._json(
                    201,
                    {
                        "proposal": proposal,
                        "ledger_digest": self.proposal_store.digest(),
                        "activated": False,
                        "human_approval_required": True,
                    },
                )
            elif parsed.path == "/api/ai/decisions":
                proposal_id = str(payload.get("proposal_id", ""))
                decision = str(payload.get("decision", ""))
                note = str(payload.get("note", ""))
                proposal = self.proposal_store.current(proposal_id)
                if proposal is None:
                    raise ValueError("unknown proposal_id")
                activation: dict[str, object] = {}
                if decision.casefold() == "approved":
                    activation = self._activate_proposal(proposal)
                event = self.proposal_store.decide(
                    proposal_id,
                    decision,
                    str(payload.get("actor", "private-engine-human-approver")),
                    note,
                    activation,
                )
                self._json(200, {"decision": event, "activation": activation, "ledger_digest": self.proposal_store.digest()})
            elif parsed.path == "/api/cpc/compare":
                self._json(200, tem_compare_and_screen(payload))
            elif parsed.path == "/api/err/run":
                self._json(200, run_evidence_resolved_payload(payload))
            elif parsed.path == "/api/compositional/run":
                self._json(200, run_compositional_payload(payload))
            elif parsed.path == "/api/model/run":
                node_id = str(payload.get("node_id", ""))
                route_id = str(payload.get("route_id", ""))
                as_of = str(payload.get("as_of") or datetime.now(timezone.utc).isoformat())
                model_nodes, all_model_routes = self._object_sources(include_drafts=self._authorized(write=True), as_of=as_of)
                model_routes = {
                    object_id: route for object_id, route in all_model_routes.items()
                    if route.get("network_scope") in {"within-country operational route", "verified import/export route; optional overlay"}
                }
                if node_id and node_id not in model_nodes:
                    raise ValueError("unknown node_id")
                if route_id and route_id not in model_routes:
                    raise ValueError("route_id is neither a within-country route nor a verified import/export route")
                raw_scope = payload.get("scope", {})
                if raw_scope is not None and not isinstance(raw_scope, Mapping):
                    raise ValueError("scope must be an object containing countries, domains and commodities")
                scope = dict(raw_scope or {})
                countries = _filter_value(scope.get("countries"))
                domains = _filter_value(scope.get("domains"))
                commodities = _filter_value(scope.get("commodities"))
                commodity_groups = _filter_value(scope.get("commodity_groups"))
                include_trade = bool(scope.get("include_trade", False))
                scope_query = {"country": countries, "domain": domains, "commodity": commodities, "commodity_group": commodity_groups}
                selected_node_ids = list(dict.fromkeys(_filter_value(payload.get("selected_node_ids"))))
                selected_route_ids = list(dict.fromkeys(_filter_value(payload.get("selected_route_ids"))))
                if node_id and node_id not in selected_node_ids:
                    selected_node_ids.append(node_id)
                if route_id and route_id not in selected_route_ids:
                    selected_route_ids.append(route_id)
                for selected_node_id in selected_node_ids:
                    if selected_node_id not in model_nodes:
                        raise ValueError(f"unknown selected node_id: {selected_node_id}")
                    if not CATALOG._matches(model_nodes[selected_node_id], scope_query, node=True):
                        raise ValueError("selected node is outside the active country, food-domain or commodity scope")
                for selected_route_id in selected_route_ids:
                    if selected_route_id not in model_routes:
                        raise ValueError(f"selected route is neither a within-country route nor a verified import/export route: {selected_route_id}")
                    if model_routes[selected_route_id]["trade_eligible"] and not include_trade:
                        raise ValueError("verified import/export route requires the trade overlay in the active scope")
                    if not CATALOG._matches(model_routes[selected_route_id], scope_query, node=False):
                        raise ValueError("selected route is outside the active country, food-domain or commodity scope")
                node_revision = self.store.latest("node", node_id, as_of=as_of) if node_id else None
                route_revision = self.store.latest("route", route_id, as_of=as_of) if route_id else None
                evidence_fields = (
                    "id", "name", "food_domain", "food_domains", "commodity", "commodities", "commodity_groups", "product_form",
                    "reported_mass", "mass_unit_period", "quantity", "quantity_period", "cpc_identified_lower",
                    "cpc_identified_upper", "cpc_measured_lower", "cpc_measured_upper", "cpc_unit",
                    "chemistry_status", "analytes", "provenance",
                    "retained_mass_lower_kg_year", "retained_mass_upper_kg_year", "consumer_population",
                    "population_basis", "mass_basis", "concentration_mg_per_kg_food", "chemistry_basis",
                    "body_weight_kg", "reference_dose_mg_per_kg_day", "declared_thq_threshold",
                    "evidence_ids", "evidence_record_count",
                )
                def selected_context(kind: str, object_id: str) -> dict[str, object]:
                    base = model_nodes[object_id] if kind == "node" else model_routes[object_id]
                    revision = self.store.latest(kind, object_id, as_of=as_of)
                    current = _merge(base, revision.to_dict() if revision else None)
                    return {key: current[key] for key in evidence_fields if key in current and current[key] not in (None, "", [])}

                active_evidence = {
                    "nodes": [selected_context("node", selected_id) for selected_id in selected_node_ids],
                    "routes": [selected_context("route", selected_id) for selected_id in selected_route_ids],
                }
                active_certificates = [
                    certificate
                    for selected_id in selected_route_ids
                    for certificate in CERTIFICATES_BY_OBJECT.get(selected_id, [])
                ]
                active_evidence["transformation_certificates"] = active_certificates
                trace_objects = [
                    *[self._trace("node", selected_id) for selected_id in selected_node_ids],
                    *[self._trace("route", selected_id) for selected_id in selected_route_ids],
                ]
                trace_records: list[dict[str, object]] = []
                trace_seen: set[str] = set()
                for trace_object in trace_objects:
                    for record in trace_object["records"]:
                        evidence_key = str(record.get("evidence_key") or record["evidence_id"])
                        if evidence_key not in trace_seen:
                            trace_seen.add(evidence_key)
                            trace_records.append(record)
                contaminant_trace = {
                    "status": "linked_records_available" if trace_records else "no_explicit_provenance_link",
                    "selected_object_count": len(trace_objects),
                    "record_count": len(trace_records),
                    "records": trace_records,
                    "objects": trace_objects,
                    "boundary": (
                        "This is provenance-bound contaminant tracing, not concentration propagation. Chemistry remains attached "
                        "to its frozen source/product record and compatible CPC state."
                    ),
                }
                layers = normalize_layer_selection(payload.get("layers"))
                raw_private_data = payload.get("private_layer_data")
                if raw_private_data is not None and not isinstance(raw_private_data, Mapping):
                    raise ValueError("private_layer_data must be an object")
                private_data = dict(raw_private_data or {})
                model_payload = dict(payload)
                private_cpc = private_data.get("cpc_compatibility")
                if layers["cpc_compatibility"] and private_cpc is not None:
                    if not isinstance(private_cpc, Mapping):
                        raise ValueError("private_layer_data.cpc_compatibility must be an object")
                    entered_cpc = payload.get("cpc") if isinstance(payload.get("cpc"), Mapping) else {}
                    model_payload["cpc"] = {**entered_cpc, **private_cpc}
                private_trace = private_data.get("contaminant_trace")
                if layers["contaminant_trace"] and private_trace is not None:
                    if not isinstance(private_trace, list) or not all(isinstance(record, Mapping) for record in private_trace):
                        raise ValueError("private_layer_data.contaminant_trace must be an array of objects")
                    trace_records = [dict(record) for record in private_trace]
                    contaminant_trace = {
                        "status": "private_on_demand_records_available" if trace_records else "no_explicit_provenance_link",
                        "selected_object_count": len(trace_objects),
                        "record_count": len(trace_records),
                        "records": trace_records,
                        "objects": [],
                        "boundary": "Private on-demand records apply only to this declared run and are not bundled with the public release.",
                    }
                typed_result = run_typed_model(
                    model_payload,
                    active_evidence=active_evidence,
                    contaminant_trace=contaminant_trace,
                )
                recalculation = typed_result["recalculation"]
                cpc_result = typed_result["cpc_result"]
                if not layers["cpc_compatibility"]:
                    recalculation = {"status": "excluded_by_user"}
                    cpc_result = {"status": "excluded_by_user", "alarm_projection": {"status": "excluded_by_user"}}
                if not layers["contaminant_trace"]:
                    contaminant_trace = {"status": "excluded_by_user", "selected_object_count": 0, "record_count": 0, "records": [], "objects": []}
                entered_exposure = payload.get("exposure_scenario") if isinstance(payload.get("exposure_scenario"), Mapping) else {}
                private_exposure = private_data.get("exposure_scenario")
                if private_exposure is not None and not isinstance(private_exposure, Mapping):
                    raise ValueError("private_layer_data.exposure_scenario must be an object")
                exposure_payload = {**entered_exposure, **dict(private_exposure or {})}
                if private_exposure:
                    exposure_payload["requested"] = bool(exposure_payload.get("requested", True))
                exposure_scenario = (
                    calculate_exposure_scenario(
                        exposure_payload,
                        selected_node_ids=selected_node_ids,
                        selected_route_ids=selected_route_ids,
                        routes=model_routes,
                        analysis_reference_date=as_of,
                    )
                    if layers["exposure_scenario"]
                    else {"status": "excluded_by_user", "display_available": False}
                )
                raw_err_problem = payload.get("err_problem")
                if not layers["err"]:
                    err_result = {"status": "excluded_by_user"}
                elif raw_err_problem is None:
                    err_result: dict[str, object] = {
                        "status": "not_requested",
                        "reason": (
                            "submit a complete err_problem with variable_names, physical constraints, bounds and "
                            "the coordinate certificate mask; the registry topology alone is not treated as a mass constraint system"
                        ),
                        "semantic_rule": "missing route evidence is not converted to zero",
                    }
                elif not isinstance(raw_err_problem, Mapping):
                    raise ValueError("err_problem must be an object")
                else:
                    err_result = run_evidence_resolved_payload(raw_err_problem)
                monitoring_layers = summarize_private_layers(layers, private_data)
                manifest = {
                    "engine_version": VERSION,
                    "as_of": as_of,
                    "selection_scope": {"countries": countries, "domains": domains, "commodity_groups": commodity_groups, "commodities": commodities, "include_trade": include_trade},
                    "selected_node_ids": selected_node_ids,
                    "selected_route_ids": selected_route_ids,
                    "included_layers": layers,
                    "monitoring_layers": monitoring_layers,
                    "evidence_access_mode": CATALOG.evidence_access_mode,
                    "node_id": node_id or None,
                    "node_revision_id": node_revision.revision_id if node_revision else "BASE" if node_id else None,
                    "route_id": route_id or None,
                    "route_revision_id": route_revision.revision_id if route_revision else "BASE" if route_id else None,
                    "approved_ledger_digest": self.store.digest(),
                    "active_evidence": active_evidence,
                    "model_steps": {
                        "evidence_resolved_reconstruction": err_result,
                        "cpc_recalculation": recalculation,
                        "contaminant_tracing": contaminant_trace,
                        "transformation_certification": {
                            "status": "certificates_linked" if active_certificates else "no_route_certificate_linked",
                            "record_count": len(active_certificates),
                            "records": active_certificates,
                            "boundary": "A certificate authorizes an identity operation, not occurrence or mass unless quantity_authorized is true and a compatible measure is present.",
                        },
                        "alarm_projection": cpc_result["alarm_projection"],
                        "temporal_trend": typed_result["temporal_trend"],
                    },
                    "cpc_result": cpc_result,
                    "exposure_scenario": exposure_scenario,
                    "evidence_resolved_reconstruction": err_result,
                    "contaminant_trace": contaminant_trace,
                    "temflow_claims": typed_result["temflow_claims"],
                    "blocked_evidence": typed_result["blocked_evidence"],
                    "calculation_certificate": typed_result["calculation_certificate"],
                    "temporal_trend": typed_result["temporal_trend"],
                }
                manifest["run_id"] = hashlib.sha256(json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()).hexdigest()[:20]
                self._json(200, manifest)
            else:
                self._json(404, {"error": "not found"})
        except (KeyError, ValueError, TypeError, json.JSONDecodeError) as exc:
            self._json(400, {"error": str(exc)})
        except Exception:
            self._json(500, {"error": "unexpected private-engine error"})

    def log_message(self, format: str, *args: object) -> None:
        return


class EngineServer(ThreadingHTTPServer):
    def __init__(self, address: tuple[str, int], data_directory: Path, view_token: str | None, curator_token: str | None) -> None:
        super().__init__(address, EngineHandler)
        self.revision_store = RevisionStore(data_directory)
        self.topology_store = TopologyStore(data_directory)
        self.feature_changes = FeatureChangeStore(data_directory)
        self.topology_edit_lock = threading.RLock()
        self.proposal_store = AIProposalStore(data_directory)
        self.ai_config = AIProviderConfig.from_environment()
        self.view_token = view_token
        self.curator_token = curator_token


def serve_private_engine(
    host: str = "127.0.0.1",
    port: int = 8770,
    data_directory: Path | str = "user_data_patterns",
    *,
    open_browser: bool = True,
    view_token: str | None = None,
    curator_token: str | None = None,
) -> int:
    remote = host not in {"127.0.0.1", "localhost", "::1"}
    view_token = view_token or os.environ.get("TEMFLOW_VIEW_TOKEN")
    curator_token = curator_token or os.environ.get("TEMFLOW_CURATOR_TOKEN")
    if remote and (not view_token or not curator_token):
        raise ValueError("remote binding requires TEMFLOW_VIEW_TOKEN and TEMFLOW_CURATOR_TOKEN")
    server = EngineServer((host, port), Path(data_directory), view_token, curator_token)
    url = f"http://{host}:{port}/"
    print(f"TEM-FLOW private review engine {VERSION}: {url}", flush=True)
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


def private_engine_parser(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser("patterns-engine", help="run the private Patterns review engine")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8770)
    parser.add_argument("--data-dir", default="user_data_patterns")
    parser.add_argument("--no-browser", action="store_true")


def main() -> int:
    parser = argparse.ArgumentParser(prog="python -m temflow.private_engine")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8770)
    parser.add_argument("--data-dir", default="user_data_patterns")
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    return serve_private_engine(args.host, args.port, args.data_dir, open_browser=not args.no_browser)


if __name__ == "__main__":
    raise SystemExit(main())

