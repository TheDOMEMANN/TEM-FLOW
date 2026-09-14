"""Core numerical routines for the TEM-FLOW sparse food-flow framework.

The implementation deliberately separates three tasks that are often conflated:
1. set identification from incomplete channel coverage;
2. an entropy/KL reference allocation for operational display; and
3. mass-conserving propagation through a staged directed network.

The reference allocation is never a substitute for the identified bounds.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Mapping, Sequence, Tuple

import numpy as np


TOL = 1e-10


def normalize(values: Sequence[float]) -> np.ndarray:
    """Return a non-negative vector normalized to sum to one."""
    x = np.asarray(values, dtype=float)
    if x.ndim != 1 or len(x) == 0:
        raise ValueError("values must be a non-empty one-dimensional vector")
    if np.any(~np.isfinite(x)) or np.any(x < 0):
        raise ValueError("values must be finite and non-negative")
    total = float(x.sum())
    if total <= 0:
        raise ValueError("values must contain positive mass")
    return x / total


def channel_share_bounds(
    q: Sequence[float], coverage_lower: float
) -> Tuple[np.ndarray, np.ndarray]:
    """Sharp marginal bounds for full-system destination shares.

    Let P = c*q + (1-c)*u, where q is the destination distribution observed
    inside a reporting channel, u is an unrestricted distribution over the
    admissible destinations outside that channel, and c >= coverage_lower.
    For each destination d, the sharp marginal bounds are

        coverage_lower*q[d] <= P[d]
        P[d] <= 1 - coverage_lower*(1-q[d]).

    If coverage_lower is zero, every marginal remains [0, 1].  The bounds are
    marginal; their endpoints cannot generally be attained simultaneously.
    """
    qv = normalize(q)
    c = float(coverage_lower)
    if not 0 <= c <= 1:
        raise ValueError("coverage_lower must be in [0, 1]")
    lower = c * qv
    upper = 1.0 - c * (1.0 - qv)
    return lower, upper


def kl_box_projection(
    prior: Sequence[float],
    total: float = 1.0,
    lower: Sequence[float] | None = None,
    upper: Sequence[float] | None = None,
    tol: float = TOL,
) -> np.ndarray:
    """KL projection of a positive prior onto a bounded simplex.

    Solves min_x sum_i x_i log(x_i / prior_i), subject to sum(x)=total and
    lower <= x <= upper.  The solution is clip(lambda*prior, lower, upper),
    with lambda obtained by bisection.
    """
    p = np.asarray(prior, dtype=float)
    if p.ndim != 1 or len(p) == 0 or np.any(~np.isfinite(p)) or np.any(p < 0):
        raise ValueError("prior must be a finite non-negative vector")
    p = np.maximum(p, 1e-15)
    n = len(p)
    lo = np.zeros(n) if lower is None else np.asarray(lower, dtype=float)
    hi = np.full(n, np.inf) if upper is None else np.asarray(upper, dtype=float)
    if lo.shape != p.shape or hi.shape != p.shape:
        raise ValueError("prior, lower and upper must have identical shapes")
    if np.any(lo < 0) or np.any(hi < lo):
        raise ValueError("invalid box bounds")
    target = float(total)
    if lo.sum() - tol > target or hi.sum() + tol < target:
        raise ValueError("bounded simplex is infeasible")

    def mass(scale: float) -> float:
        return float(np.clip(scale * p, lo, hi).sum())

    left, right = 0.0, 1.0
    while mass(right) < target and right < 1e18:
        right *= 2.0
    for _ in range(200):
        mid = 0.5 * (left + right)
        if mass(mid) < target:
            left = mid
        else:
            right = mid
        if right - left <= tol * max(1.0, right):
            break
    x = np.clip(0.5 * (left + right) * p, lo, hi)
    # Remove the tiny numerical closure error without violating the box.
    residual = target - float(x.sum())
    if abs(residual) > 10 * tol:
        free = np.where((x > lo + tol) & (x < hi - tol))[0]
        if len(free) == 0:
            free = np.where((hi - x > tol) if residual > 0 else (x - lo > tol))[0]
        if len(free):
            weights = p[free] / p[free].sum()
            x[free] += residual * weights
            x = np.clip(x, lo, hi)
    if abs(float(x.sum()) - target) > 1e-7:
        raise RuntimeError("projection did not close")
    return x


def reference_destination_shares(
    population: Sequence[float],
    travel_time_hours: Sequence[float],
    market_score: Sequence[float],
    lakeside_tradition: Sequence[float],
    route_support: Sequence[float],
    reachable: Sequence[bool],
    coefficients: Mapping[str, float] | None = None,
) -> np.ndarray:
    """Build a transparent gravity/market reference allocation.

    Population is an offset.  The remaining covariates modify per-person access
    and absorption.  Unreachable destinations receive exactly zero mass.
    """
    coef = {
        "log_population": 1.0,
        "log_travel_time": -1.2,
        "market": 0.6,
        "tradition": 0.8,
        "route": 1.0,
    }
    if coefficients:
        coef.update(coefficients)
    pop = np.asarray(population, dtype=float)
    tt = np.asarray(travel_time_hours, dtype=float)
    market = np.asarray(market_score, dtype=float)
    tradition = np.asarray(lakeside_tradition, dtype=float)
    route = np.asarray(route_support, dtype=float)
    reach = np.asarray(reachable, dtype=bool)
    shapes = {arr.shape for arr in (pop, tt, market, tradition, route, reach)}
    if len(shapes) != 1 or pop.ndim != 1:
        raise ValueError("all destination covariates must be aligned vectors")
    if np.any(pop <= 0) or np.any(tt <= 0):
        raise ValueError("population and travel time must be positive")
    if not np.any(reach):
        raise ValueError("at least one destination must be reachable")
    eta = (
        coef["log_population"] * np.log(pop)
        + coef["log_travel_time"] * np.log(tt)
        + coef["market"] * market
        + coef["tradition"] * tradition
        + coef["route"] * route
    )
    eta[~reach] = -np.inf
    finite = eta[np.isfinite(eta)]
    weights = np.zeros_like(eta)
    weights[reach] = np.exp(eta[reach] - finite.max())
    return normalize(weights)


@dataclass(frozen=True)
class OriginCommodity:
    origin: str
    commodity: str


@dataclass
class PropagationResult:
    throughput: Dict[Tuple[OriginCommodity, str], float]
    absorbed: Dict[Tuple[OriginCommodity, str], float]
    residual: Dict[Tuple[OriginCommodity, str], float]
    edge_flow: Dict[Tuple[OriginCommodity, str, str], float]
    loss: Dict[Tuple[OriginCommodity, str], float]
    stock: Dict[Tuple[OriginCommodity, str], float]
    export: Dict[Tuple[OriginCommodity, str], float]
    balance_error: Dict[Tuple[OriginCommodity, str], float]


def propagate_acyclic_network(
    topological_nodes: Sequence[str],
    injections: Mapping[Tuple[OriginCommodity, str], float],
    absorption_fraction: Mapping[str, float],
    transitions: Mapping[str, Mapping[str, float]],
    closure_fraction: Mapping[str, Mapping[str, float]] | None = None,
) -> PropagationResult:
    """Propagate origin- and commodity-preserving mass through a DAG.

    At every node, local absorption is applied to throughput.  Transition shares
    then allocate the unabsorbed remainder.  Any remainder not explicitly sent
    to a downstream node is recorded as residual/stock/export closure.
    """
    nodes = list(topological_nodes)
    order = {n: i for i, n in enumerate(nodes)}
    closure_fraction = closure_fraction or {}
    allowed_closures = {"loss", "stock", "export"}
    for node, outs in transitions.items():
        if node not in order:
            raise ValueError(f"unknown transition origin: {node}")
        if sum(outs.values()) > 1 + TOL or any(v < 0 for v in outs.values()):
            raise ValueError(f"invalid transition shares at {node}")
        for dest in outs:
            if dest not in order or order[dest] <= order[node]:
                raise ValueError("transitions must follow the supplied topological order")
    for node, frac in absorption_fraction.items():
        if node not in order or not 0 <= frac <= 1:
            raise ValueError(f"invalid absorption fraction at {node}")
    for node, parts in closure_fraction.items():
        if node not in order or set(parts) - allowed_closures:
            raise ValueError(f"invalid closure category at {node}")
        if any(v < 0 for v in parts.values()):
            raise ValueError(f"negative closure fraction at {node}")
        if sum(parts.values()) + sum(transitions.get(node, {}).values()) > 1 + TOL:
            raise ValueError(f"outgoing and closure fractions exceed one at {node}")

    keys = sorted({key for key, _ in injections}, key=lambda x: (x.origin, x.commodity))
    throughput: Dict[Tuple[OriginCommodity, str], float] = {}
    absorbed: Dict[Tuple[OriginCommodity, str], float] = {}
    residual: Dict[Tuple[OriginCommodity, str], float] = {}
    edge_flow: Dict[Tuple[OriginCommodity, str, str], float] = {}
    loss: Dict[Tuple[OriginCommodity, str], float] = {}
    stock: Dict[Tuple[OriginCommodity, str], float] = {}
    export: Dict[Tuple[OriginCommodity, str], float] = {}
    balance_error: Dict[Tuple[OriginCommodity, str], float] = {}

    for key in keys:
        inbound = {n: 0.0 for n in nodes}
        for (inj_key, node), value in injections.items():
            if inj_key == key:
                inbound[node] += float(value)
        for node in nodes:
            t = inbound[node]
            a = t * absorption_fraction.get(node, 0.0)
            remainder = t - a
            out_total = 0.0
            for dest, share in transitions.get(node, {}).items():
                f = remainder * float(share)
                edge_flow[(key, node, dest)] = f
                inbound[dest] += f
                out_total += f
            closure = closure_fraction.get(node, {})
            l = remainder * float(closure.get("loss", 0.0))
            s = remainder * float(closure.get("stock", 0.0))
            x = remainder * float(closure.get("export", 0.0))
            r = remainder - out_total - l - s - x
            throughput[(key, node)] = t
            absorbed[(key, node)] = a
            residual[(key, node)] = r
            loss[(key, node)] = l
            stock[(key, node)] = s
            export[(key, node)] = x
            balance_error[(key, node)] = t - a - out_total - l - s - x - r

    return PropagationResult(throughput, absorbed, residual, edge_flow, loss, stock, export, balance_error)


def build_time_expanded_network(
    physical_nodes: Sequence[str],
    periods: Sequence[str],
    lagged_edges: Sequence[tuple[str, str, int, float]],
    carryover_fraction: Mapping[str, float] | None = None,
) -> tuple[list[str], Dict[str, Dict[str, float]]]:
    """Convert cyclic/storage movement into an acyclic time-expanded graph.

    Each lagged edge is ``(origin, destination, lag_periods, share)``.  A lag
    of at least one is required, so every edge advances in time.  Optional
    carry-over adds storage edges from a node in one period to the same node in
    the next period.  Returned node names are ``physical@period``.
    """
    nodes = list(physical_nodes)
    times = list(periods)
    if len(nodes) == 0 or len(times) < 2 or len(set(nodes)) != len(nodes) or len(set(times)) != len(times):
        raise ValueError("physical_nodes must be unique and periods must contain at least two unique values")
    node_set = set(nodes)
    transitions: Dict[str, Dict[str, float]] = {}
    for origin, destination, lag, share in lagged_edges:
        if origin not in node_set or destination not in node_set or lag < 1 or not 0 <= share <= 1:
            raise ValueError("invalid lagged edge")
        for index in range(len(times) - lag):
            src = f"{origin}@{times[index]}"
            dst = f"{destination}@{times[index + lag]}"
            transitions.setdefault(src, {})[dst] = transitions.setdefault(src, {}).get(dst, 0.0) + float(share)
    for node, share in (carryover_fraction or {}).items():
        if node not in node_set or not 0 <= share <= 1:
            raise ValueError("invalid carry-over fraction")
        for index in range(len(times) - 1):
            src = f"{node}@{times[index]}"
            dst = f"{node}@{times[index + 1]}"
            transitions.setdefault(src, {})[dst] = transitions.setdefault(src, {}).get(dst, 0.0) + float(share)
    for node, outs in transitions.items():
        if sum(outs.values()) > 1 + TOL:
            raise ValueError(f"time-expanded outgoing shares exceed one at {node}")
    ordered = [f"{node}@{period}" for period in times for node in nodes]
    return ordered, transitions


def edible_consumption_kg_per_capita_year(
    absorbed_tonnes: Sequence[float],
    edible_fraction: Sequence[float],
    population: float,
) -> float:
    absorbed = np.asarray(absorbed_tonnes, dtype=float)
    edible = np.asarray(edible_fraction, dtype=float)
    if absorbed.shape != edible.shape or np.any(absorbed < 0) or np.any((edible < 0) | (edible > 1)):
        raise ValueError("invalid absorbed mass or edible fraction")
    if population <= 0:
        raise ValueError("population must be positive")
    return float(1000.0 * np.sum(absorbed * edible) / population)


def chronic_daily_intake(
    concentration_mg_per_kg: Sequence[float],
    consumption_kg_per_year: Sequence[float],
    body_weight_kg: float,
    preparation_factor: Sequence[float] | None = None,
) -> float:
    c = np.asarray(concentration_mg_per_kg, dtype=float)
    r = np.asarray(consumption_kg_per_year, dtype=float)
    pf = np.ones_like(c) if preparation_factor is None else np.asarray(preparation_factor, dtype=float)
    if c.shape != r.shape or c.shape != pf.shape:
        raise ValueError("concentration, consumption and preparation vectors must align")
    if np.any(c < 0) or np.any(r < 0) or np.any(pf < 0) or body_weight_kg <= 0:
        raise ValueError("exposure inputs must be non-negative and body weight positive")
    return float(np.sum(c * r * pf) / (365.0 * body_weight_kg))


def consequence_weighted_aggregation_adequacy(
    aggregate_action_loss: Sequence[float],
    spatial_action_loss: Sequence[float],
    posterior_weights: Sequence[float],
) -> float:
    """Expected excess loss from acting on an aggregate rather than spatial evidence."""
    la = np.asarray(aggregate_action_loss, dtype=float)
    ls = np.asarray(spatial_action_loss, dtype=float)
    w = normalize(posterior_weights)
    if la.shape != ls.shape or la.shape != w.shape:
        raise ValueError("loss and posterior-weight vectors must align")
    return float(np.sum(w * (la - ls)))

