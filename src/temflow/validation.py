from __future__ import annotations

from collections.abc import Callable
import re
from . import __version__

import numpy as np

from .core import channel_share_bounds, kl_box_projection
from .downstream_consequence import (
    EdibleConversionEvidence,
    FlowIdentity,
    Interval,
    MassEvidence,
    PopulationEvidence,
    TemporalPolicy,
    calculate_cpc_state,
)
from .evidential_resolution import FlowPolytope, evidence_resolved_reconstruction
from .compositional import compositional_allocation
from .private_engine import CATALOG, UI_PATH, VERSION
from scipy.sparse import csr_matrix


def _check_version() -> None:
    if VERSION != __version__ or not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", VERSION):
        raise AssertionError(f"inconsistent or invalid release version: {VERSION}")


def _check_numerical_core() -> None:
    lower, upper = channel_share_bounds([0.4, 0.6], 1.0)
    np.testing.assert_allclose(lower, [0.4, 0.6], atol=1e-12)
    np.testing.assert_allclose(upper, [0.4, 0.6], atol=1e-12)

    values = kl_box_projection(
        [0.55, 0.30, 0.15],
        lower=[0.1, 0.2, 0.0],
        upper=[0.5, 0.6, 0.4],
    )
    if not np.isclose(values.sum(), 1.0, atol=1e-9):
        raise AssertionError("KL projection does not conserve the block total")
    if np.any(values < np.array([0.1, 0.2, 0.0]) - 1e-9):
        raise AssertionError("KL projection violates a lower bound")
    if np.any(values > np.array([0.5, 0.6, 0.4]) + 1e-9):
        raise AssertionError("KL projection violates an upper bound")


def _check_packaged_interface() -> None:
    if not UI_PATH.is_file():
        raise AssertionError("the private reviewer interface is missing")
    html = UI_PATH.read_text(encoding="utf-8")
    for control in ('id="refresh"', 'id="run"', 'id="countries"', 'id="nodeList"', 'id="routeList"'):
        if control not in html:
            raise AssertionError(f"reviewer control {control} is missing")


def _check_continental_registry() -> None:
    if len(CATALOG.nodes) != 6312:
        raise AssertionError(f"expected 6,312 nodes, found {len(CATALOG.nodes):,}")
    if len(CATALOG.domestic_routes) != 15428:
        raise AssertionError(f"expected 15,428 domestic routes, found {len(CATALOG.domestic_routes):,}")
    if len(CATALOG.verified_trade_routes) != 1795:
        raise AssertionError(f"expected 1,795 verified trade routes, found {len(CATALOG.verified_trade_routes):,}")
    if len(CATALOG.quarantined_cross_border_routes) != 454:
        raise AssertionError(
            "expected 454 quarantined cross-border records, "
            f"found {len(CATALOG.quarantined_cross_border_routes):,}"
        )
    default_routes = CATALOG.query("route", {"limit": ["20000"]})
    if default_routes["total"] != 15428:
        raise AssertionError("the default reviewer view is not restricted to national routes")


def _check_road_display_layer() -> None:
    payload = CATALOG.route_display_geometry_payload
    supported = payload.get("supported_countries", [])
    route_paths = payload.get("route_paths", {})
    paths = payload.get("paths", {})
    if len(supported) != 54:
        raise AssertionError(f"expected road display coverage for 54 countries, found {len(supported)}")
    if len(route_paths) < 8200 or len(paths) < 5200:
        raise AssertionError("the packaged continental road-display layer is incomplete")


def _check_evidence_resolved_reconstruction() -> None:
    polytope = FlowPolytope(
        variable_names=("a", "b"),
        prior=None,
        lower=np.zeros(2),
        upper=np.full(2, np.inf),
        A_eq=csr_matrix([[1.0, 1.0]]),
        b_eq=np.array([10.0]),
        A_ub=csr_matrix((0, 2)),
        b_ub=np.empty(0),
        equality_names=("total mass",),
    )
    result = evidence_resolved_reconstruction(polytope, [True, False], known_total=10.0)
    if not np.isclose(result.minimum_unresolved_mass, 0.0):
        raise AssertionError("ERR minimum unresolved mass is incorrect")
    if not np.isclose(result.maximum_unresolved_mass, 10.0):
        raise AssertionError("ERR maximum unresolved mass is incorrect")
    if result.operational_allocation is not None:
        raise AssertionError("ERR produced an operational point without an explicit request")
    if result.claim("b")["status"] != "blocked_unresolved_identity":
        raise AssertionError("ERR promoted an uncertified identity")


def _check_downstream_cpc() -> None:
    identity = FlowIdentity("fish", "mixed fish", "whole wet fish", "source", "checkpoint", "node")
    result = calculate_cpc_state(
        identity=identity,
        target_date="2022-12-31",
        temporal_policy=TemporalPolicy(allow_unbounded_past=True),
        mass_records=(MassEvidence("mass", identity, "2020-12-31", Interval(1.0, 1.0, "tonne/year")),),
        population_records=(PopulationEvidence("population", "node", "2021-12-31", "official projection", "resident population", Interval(1000.0, 1000.0, "persons")),),
        conversion_records=(EdibleConversionEvidence("yield", "fish", "whole wet fish", "2019-12-31", Interval(0.5, 0.5, "fraction"), "declared test value"),),
    )
    if result.get("status") != "computed":
        raise AssertionError("typed downstream CPC calculation was blocked")
    if not np.isclose(result["cpc"]["lower"], 0.5) or not np.isclose(result["cpc"]["upper"], 0.5):
        raise AssertionError("typed downstream CPC calculation is incorrect")
    if result["temporal_matches"]["mass"]["lag_days"] <= 0:
        raise AssertionError("downstream CPC temporal lag was not recorded")


def _check_compositional_allocation() -> None:
    result = compositional_allocation(
        remainder_mass=100.0,
        destinations=("local", "market", "UNRESOLVED_DESTINATION"),
        historical_shares=(0.6, 0.4, 0.0),
        epsilon=0.2,
    )
    if result.operational_point_allocation is not None:
        raise AssertionError("compositional operator produced an unrequested point")
    if not result.contains({"local": 50.0, "market": 40.0, "UNRESOLVED_DESTINATION": 10.0}):
        raise AssertionError("compositional operator rejected an in-set allocation")
    if result.coordinates[-1].named_report_status != "blocked_unresolved_identity":
        raise AssertionError("unresolved destination was promoted to a named route")


def run_packaged_validation(*, emit: Callable[[str], None] = print) -> int:
    """Run deterministic checks that are available inside the installed wheel."""

    checks: list[tuple[str, Callable[[], None]]] = [
        ("version identity", _check_version),
        ("numerical core", _check_numerical_core),
        ("reviewer interface", _check_packaged_interface),
        ("continental registry", _check_continental_registry),
        ("road display layer", _check_road_display_layer),
        ("evidence-resolved reconstruction", _check_evidence_resolved_reconstruction),
        ("joint compositional allocation", _check_compositional_allocation),
        ("typed downstream CPC", _check_downstream_cpc),
    ]
    failures: list[str] = []
    emit(f"TEM-FLOW {VERSION} installed-package validation")
    for label, check in checks:
        try:
            check()
        except Exception as exc:  # validation must report every failed gate
            failures.append(f"{label}: {exc}")
            emit(f"FAIL  {label}: {exc}")
        else:
            emit(f"PASS  {label}")
    if failures:
        emit(f"FAILED: {len(failures)} of {len(checks)} validation gates failed")
        return 1
    emit(f"PASS: all {len(checks)} installed-package validation gates passed")
    return 0

