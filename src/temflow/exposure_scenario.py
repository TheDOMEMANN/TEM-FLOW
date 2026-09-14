"""Explicit, non-default CPC, estimated intake and THQ scenario projection.

The result is a decision-support scenario.  It preserves the declared evidence
basis of each input and never converts a projected population, modelled mass,
or last reported chemistry value into an observed exposure claim.
"""

from __future__ import annotations

from collections import deque
import math
from typing import Mapping


def _finite(value: object, name: str, *, positive: bool = False) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be numeric") from exc
    if not math.isfinite(number) or number < 0 or (positive and number <= 0):
        rule = "positive" if positive else "finite and non-negative"
        raise ValueError(f"{name} must be {rule}")
    return number


def _basis(value: object, allowed: set[str], name: str) -> str:
    basis = str(value or "").strip()
    if basis not in allowed:
        raise ValueError(f"{name} must be one of: {', '.join(sorted(allowed))}")
    return basis


def calculate_exposure_scenario(
    payload: Mapping[str, object] | None,
    *,
    selected_node_ids: list[str],
    selected_route_ids: list[str],
    routes: Mapping[str, Mapping[str, object]],
    analysis_reference_date: str,
) -> dict[str, object]:
    """Calculate a declared scenario and its graph overlay instructions."""
    if not payload or not bool(payload.get("requested", False)):
        return {
            "status": "not_requested",
            "display_available": False,
            "reason": "Exposure animation requires an explicit scenario request in addition to the model run.",
        }

    mass_lower = _finite(payload.get("retained_mass_lower_kg_year"), "retained_mass_lower_kg_year")
    raw_upper = payload.get("retained_mass_upper_kg_year")
    mass_upper = mass_lower if raw_upper in (None, "") else _finite(raw_upper, "retained_mass_upper_kg_year")
    if mass_lower > mass_upper:
        raise ValueError("retained_mass_lower_kg_year cannot exceed retained_mass_upper_kg_year")
    population = _finite(payload.get("consumer_population"), "consumer_population", positive=True)
    concentration = _finite(payload.get("concentration_mg_per_kg_food"), "concentration_mg_per_kg_food")
    body_weight = _finite(payload.get("body_weight_kg"), "body_weight_kg", positive=True)
    reference_dose = _finite(payload.get("reference_dose_mg_per_kg_day"), "reference_dose_mg_per_kg_day", positive=True)
    threshold = _finite(payload.get("declared_thq_threshold", 1.0), "declared_thq_threshold", positive=True)

    population_basis = _basis(payload.get("population_basis"), {"last_known", "projected"}, "population_basis")
    mass_basis = _basis(payload.get("mass_basis"), {"last_observed", "modelled"}, "mass_basis")
    chemistry_basis = _basis(payload.get("chemistry_basis"), {"last_reported"}, "chemistry_basis")

    cpc_lower = mass_lower / population
    cpc_upper = mass_upper / population
    edi_factor = concentration / (365.0 * body_weight)
    edi_lower = cpc_lower * edi_factor
    edi_upper = cpc_upper * edi_factor
    thq_lower = edi_lower / reference_dose
    thq_upper = edi_upper / reference_dose
    if thq_lower >= threshold:
        status, severity = "threshold_exceeded_across_interval", "exceeded"
    elif thq_upper >= threshold:
        status, severity = "threshold_crossing_within_interval", "possible"
    else:
        status, severity = "below_declared_threshold", "below"

    route_ids = list(dict.fromkeys(selected_route_ids))
    node_ids = list(dict.fromkeys(selected_node_ids))
    for route_id in route_ids:
        route = routes[route_id]
        for key in ("from_node_id", "to_node_id"):
            node_id = str(route.get(key) or "")
            if node_id and node_id not in node_ids:
                node_ids.append(node_id)
    if len(node_ids) > 1 and not route_ids:
        selected = set(node_ids)
        route_ids = [
            route_id for route_id, route in routes.items()
            if str(route.get("from_node_id")) in selected and str(route.get("to_node_id")) in selected
        ]

    source_node_id = str(payload.get("source_node_id") or "").strip()
    if not source_node_id:
        source_node_id = node_ids[0] if node_ids else ""
    if source_node_id and source_node_id not in node_ids:
        raise ValueError("source_node_id must be in the selected scenario network")

    adjacency: dict[str, list[tuple[str, str]]] = {node_id: [] for node_id in node_ids}
    for route_id in route_ids:
        route = routes[route_id]
        origin, destination = str(route.get("from_node_id") or ""), str(route.get("to_node_id") or "")
        if origin in adjacency and destination in adjacency:
            adjacency[origin].append((destination, route_id))
            adjacency[destination].append((origin, route_id))
    node_hops = {source_node_id: 0} if source_node_id else {}
    route_hops: dict[str, int] = {}
    queue = deque([source_node_id] if source_node_id else [])
    while queue:
        current = queue.popleft()
        for neighbour, route_id in adjacency.get(current, []):
            route_hops.setdefault(route_id, node_hops[current])
            if neighbour not in node_hops:
                node_hops[neighbour] = node_hops[current] + 1
                queue.append(neighbour)
    fallback_hop = max(node_hops.values(), default=0) + 1

    return {
        "status": status,
        "display_available": status in {"threshold_exceeded_across_interval", "threshold_crossing_within_interval"},
        "severity": severity,
        "declared_thq_threshold": threshold,
        "analysis_reference_date": analysis_reference_date,
        "inputs": {
            "retained_mass_kg_year": [mass_lower, mass_upper],
            "consumer_population": population,
            "concentration_mg_per_kg_food": concentration,
            "body_weight_kg": body_weight,
            "reference_dose_mg_per_kg_day": reference_dose,
            "evidence_basis": {
                "population": population_basis,
                "retained_mass": mass_basis,
                "chemistry": chemistry_basis,
            },
        },
        "cpc_kg_person_year": [cpc_lower, cpc_upper],
        "estimated_daily_intake_mg_kg_bw_day": [edi_lower, edi_upper],
        "thq": [thq_lower, thq_upper],
        "map": {
            "source_node_id": source_node_id or None,
            "node_ids": node_ids,
            "route_ids": route_ids,
            "node_hops": {node_id: node_hops.get(node_id, fallback_hop) for node_id in node_ids},
            "route_hops": {route_id: route_hops.get(route_id, fallback_hop) for route_id in route_ids},
        },
        "display_rule": "The map animation is opt-in after calculation and is never displayed by Run selected workflow alone.",
        "interpretation_boundary": (
            "This is a scenario projection from declared last-known/projected population, last-observed/modelled retained mass, "
            "and last-reported chemistry inputs. It is not an observed exposure estimate, a diagnosis, or evidence that an "
            "animated route carried contaminated product."
        ),
    }
