"""Evidence-Resolved Reconstruction (ERR) for partial mass-flow evidence.

ERR keeps every physically admissible coordinate in the feasible polytope
``F(E) = {x >= 0 : A x = b, G x <= h, l <= x <= u}``.  The evidence mask
controls reportability, not physical existence.  Uncertified coordinates stay
latent and are never converted to structural zeros.  A unique prior projection
is computed only when an operational table is explicitly requested.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
import os
from typing import Mapping, Sequence

import numpy as np
from scipy.optimize import Bounds, LinearConstraint, linprog, minimize
from scipy.sparse import csr_matrix, vstack


TOLERANCE = 1e-8
ALGORITHM_ID = "TEMFLOW_ERR_V1_1"


def _as_float_vector(values: Sequence[float], n: int, label: str) -> np.ndarray:
    array = np.asarray(values, dtype=float)
    if array.shape != (n,) or np.any(np.isnan(array)):
        raise ValueError(f"{label} must contain {n} numeric values")
    return array


@dataclass(frozen=True)
class FlowPolytope:
    """A named linear mass-flow feasible set; the operational prior is optional."""

    variable_names: tuple[str, ...]
    prior: np.ndarray | None
    lower: np.ndarray
    upper: np.ndarray
    A_eq: csr_matrix
    b_eq: np.ndarray
    A_ub: csr_matrix
    b_ub: np.ndarray
    equality_names: tuple[str, ...] = ()
    inequality_names: tuple[str, ...] = ()

    def validate(self, *, require_prior: bool = False) -> None:
        n = len(self.variable_names)
        if n == 0 or len(set(self.variable_names)) != n:
            raise ValueError("variable_names must be non-empty and unique")
        lower = _as_float_vector(self.lower, n, "lower")
        upper = _as_float_vector(self.upper, n, "upper")
        if np.any(lower < 0) or np.any(upper < lower):
            raise ValueError("flow bounds must satisfy 0 <= lower <= upper")
        if require_prior and self.prior is None:
            raise ValueError("an explicit strictly positive prior is required for an operational table")
        if self.prior is not None:
            prior = _as_float_vector(self.prior, n, "prior")
            if np.any(~np.isfinite(prior)) or np.any(prior <= 0):
                raise ValueError("prior values must be finite and strictly positive")
        if self.A_eq.shape != (len(self.b_eq), n):
            raise ValueError("A_eq and b_eq are misaligned")
        if self.A_ub.shape != (len(self.b_ub), n):
            raise ValueError("A_ub and b_ub are misaligned")
        if self.equality_names and len(self.equality_names) != len(self.b_eq):
            raise ValueError("equality_names are misaligned")
        if self.inequality_names and len(self.inequality_names) != len(self.b_ub):
            raise ValueError("inequality_names are misaligned")


@dataclass(frozen=True)
class EvidenceResolvedResult:
    """Integrated ERR result, including scientific and numerical certificates."""

    variable_names: tuple[str, ...]
    certified_mask: np.ndarray
    unresolved_weights: np.ndarray
    minimum_unresolved_mass: float
    maximum_unresolved_mass: float
    evidence_resolution_ratio_interval: tuple[float, float] | None
    neutral_lower: np.ndarray
    neutral_upper: np.ndarray
    resolved_face_lower: np.ndarray
    resolved_face_upper: np.ndarray
    operational_allocation: np.ndarray | None
    operational_prior_version: str | None
    blockers: tuple[dict[str, object], ...]
    dependency_witness: tuple[dict[str, object], ...]
    resolution_face: dict[str, object]
    solver_certificate: dict[str, object]
    tolerances: dict[str, float]

    @property
    def maximum_violation(self) -> float:
        return float(self.solver_certificate["maximum_constraint_violation"])

    def _witness_for(self, index: int) -> dict[str, object]:
        return dict(self.dependency_witness[index])

    def claim(self, variable_name: str) -> dict[str, object]:
        index = self.variable_names.index(variable_name)
        witness = self._witness_for(index)
        if not bool(self.certified_mask[index]):
            return {
                "variable": variable_name,
                "status": "blocked_unresolved_identity",
                "reason": "the coordinate remains latent and is not authorized for named reporting",
                "neutral_interval_retained_in_integrated_result": True,
                "dependency_witness": witness,
            }
        claim: dict[str, object] = {
            "variable": variable_name,
            "status": "evidence_resolved_model_claim",
            "neutral_interval": [float(self.neutral_lower[index]), float(self.neutral_upper[index])],
            "resolution_optimal_interval": [
                float(self.resolved_face_lower[index]), float(self.resolved_face_upper[index])
            ],
            "epistemic_status": "model-derived conditional on the stated physical constraints and identity certificate",
            "dependency_witness": witness,
        }
        if self.operational_allocation is not None:
            claim["operational_allocation"] = float(self.operational_allocation[index])
            claim["operational_prior_version"] = self.operational_prior_version
        return claim

    def to_dict(self) -> dict[str, object]:
        coordinates = []
        for index, name in enumerate(self.variable_names):
            row: dict[str, object] = {
                "variable": name,
                "certified": bool(self.certified_mask[index]),
                "unresolved_weight": float(self.unresolved_weights[index]),
                "neutral_interval": [float(self.neutral_lower[index]), float(self.neutral_upper[index])],
                "resolution_optimal_interval": [
                    float(self.resolved_face_lower[index]), float(self.resolved_face_upper[index])
                ],
                "named_report_status": (
                    "evidence_resolved_model_claim"
                    if bool(self.certified_mask[index])
                    else "blocked_unresolved_identity"
                ),
                "dependency_witness": self._witness_for(index),
            }
            if self.operational_allocation is not None:
                row["operational_allocation"] = float(self.operational_allocation[index])
            coordinates.append(row)
        projection: dict[str, object] = {
            "status": "not_requested",
            "reason": "a point table is not part of the set-valued ERR result unless explicitly requested",
        }
        if self.operational_allocation is not None:
            projection = {
                "status": "computed",
                "prior_version": self.operational_prior_version,
                "allocation": {
                    name: float(value)
                    for name, value in zip(self.variable_names, self.operational_allocation)
                },
                "interpretive_boundary": "unique operational reference on F*_K; not an observed route table",
            }
        return {
            "status": "computed",
            "algorithm": ALGORITHM_ID,
            "semantic_rule": "uncertified coordinates remain latent; absence of identity evidence is not a structural zero",
            "unresolved_envelope": {
                "lower": self.minimum_unresolved_mass,
                "upper": self.maximum_unresolved_mass,
                "resolution_ratio_interval": (
                    list(self.evidence_resolution_ratio_interval)
                    if self.evidence_resolution_ratio_interval is not None
                    else None
                ),
            },
            "resolution_face": dict(self.resolution_face),
            "coordinates": coordinates,
            "operational_projection": projection,
            "blockers": [dict(value) for value in self.blockers],
            "dependency_witness": [dict(value) for value in self.dependency_witness],
            "solver_certificate": dict(self.solver_certificate),
            "tolerances": dict(self.tolerances),
            "caution": "coordinate interval widths need not be monotone under certificate refinement; only the two unresolved-envelope endpoints are guaranteed antitone",
        }


def _bounds(polytope: FlowPolytope) -> list[tuple[float, float | None]]:
    return [(float(lo), None if np.isposinf(hi) else float(hi)) for lo, hi in zip(polytope.lower, polytope.upper)]


def _solve_lp(polytope: FlowPolytope, objective: np.ndarray, maximize: bool = False):
    result = linprog(
        -objective if maximize else objective,
        A_ub=polytope.A_ub if polytope.A_ub.shape[0] else None,
        b_ub=polytope.b_ub if polytope.A_ub.shape[0] else None,
        A_eq=polytope.A_eq if polytope.A_eq.shape[0] else None,
        b_eq=polytope.b_eq if polytope.A_eq.shape[0] else None,
        bounds=_bounds(polytope),
        method="highs",
    )
    if not result.success:
        kind = {2: "infeasible", 3: "unbounded"}.get(result.status, "unsolved")
        raise ValueError(f"evidence flow polytope is {kind}: {result.message}")
    return result


def _sharp_bounds(polytope: FlowPolytope) -> tuple[np.ndarray, np.ndarray]:
    n = len(polytope.variable_names)
    workers = max(1, int(os.environ.get("TEMFLOW_ERR_WORKERS", "1")))

    def solve_coordinate(index: int) -> tuple[int, float, float]:
        objective = np.zeros(n)
        objective[index] = 1.0
        return (
            index,
            float(_solve_lp(polytope, objective).fun),
            float(-_solve_lp(polytope, objective, maximize=True).fun),
        )

    if workers == 1 or n < 32:
        solved = map(solve_coordinate, range(n))
    else:
        executor = ThreadPoolExecutor(max_workers=workers)
        solved = executor.map(solve_coordinate, range(n))
    lower = np.empty(n)
    upper = np.empty(n)
    try:
        for index, lo, hi in solved:
            lower[index] = lo
            upper[index] = hi
    finally:
        if workers > 1 and n >= 32:
            executor.shutdown(wait=True)
    return lower, upper


def _with_resolution_face(polytope: FlowPolytope, cost: np.ndarray, optimum: float, constant: bool) -> FlowPolytope:
    if constant or not np.any(cost):
        return polytope
    return FlowPolytope(
        variable_names=polytope.variable_names,
        prior=None if polytope.prior is None else polytope.prior.copy(),
        lower=polytope.lower.copy(),
        upper=polytope.upper.copy(),
        A_eq=vstack([polytope.A_eq, csr_matrix(cost.reshape(1, -1))], format="csr"),
        b_eq=np.concatenate([polytope.b_eq, [optimum]]),
        A_ub=polytope.A_ub.copy(),
        b_ub=polytope.b_ub.copy(),
        equality_names=polytope.equality_names + ("ERR minimum-unresolved face",),
        inequality_names=polytope.inequality_names,
    )


def _constraint_residuals(polytope: FlowPolytope, values: np.ndarray) -> dict[str, float]:
    lower = float(np.max(np.maximum(polytope.lower - values, 0.0)))
    upper = float(np.max(np.maximum(values - polytope.upper, 0.0)))
    equality = float(np.max(np.abs(polytope.A_eq @ values - polytope.b_eq))) if polytope.A_eq.shape[0] else 0.0
    inequality = float(np.max(np.maximum(polytope.A_ub @ values - polytope.b_ub, 0.0))) if polytope.A_ub.shape[0] else 0.0
    return {"lower_bound": lower, "upper_bound": upper, "equality": equality, "inequality": inequality, "maximum": max(lower, upper, equality, inequality)}


def _maximum_violation(polytope: FlowPolytope, values: np.ndarray) -> float:
    return _constraint_residuals(polytope, values)["maximum"]


def _unique_reference(polytope: FlowPolytope, initial: np.ndarray) -> np.ndarray:
    if polytope.prior is None:
        raise ValueError("an operational projection requires a prior")
    prior = np.asarray(polytope.prior, dtype=float)
    scale = np.maximum(prior, 1e-12)

    def objective(x: np.ndarray) -> float:
        delta = x - prior
        return float(0.5 * np.sum(delta * delta / scale))

    constraints: list[dict[str, object]] = []
    if polytope.A_eq.shape[0]:
        constraints.append({"type": "eq", "fun": lambda x: np.asarray(polytope.A_eq @ x).ravel() - polytope.b_eq, "jac": lambda x: polytope.A_eq.toarray()})
    if polytope.A_ub.shape[0]:
        constraints.append({"type": "ineq", "fun": lambda x: polytope.b_ub - np.asarray(polytope.A_ub @ x).ravel(), "jac": lambda x: -polytope.A_ub.toarray()})
    result = minimize(
        objective, initial, jac=lambda x: (x - prior) / scale, method="SLSQP",
        bounds=_bounds(polytope), constraints=constraints, options={"ftol": 1e-11, "maxiter": 4000},
    )
    if not result.success:
        linear_constraints = []
        if polytope.A_eq.shape[0]:
            linear_constraints.append(LinearConstraint(polytope.A_eq, polytope.b_eq, polytope.b_eq))
        if polytope.A_ub.shape[0]:
            linear_constraints.append(LinearConstraint(polytope.A_ub, np.full(len(polytope.b_ub), -np.inf), polytope.b_ub))
        result = minimize(
            objective, initial, jac=lambda x: (x - prior) / scale, hess=lambda x: np.diag(1.0 / scale),
            method="trust-constr", bounds=Bounds(polytope.lower, polytope.upper), constraints=linear_constraints,
            options={"gtol": 1e-10, "xtol": 1e-11, "barrier_tol": 1e-11, "maxiter": 4000},
        )
        if not result.success and _maximum_violation(polytope, np.asarray(result.x)) > 1e-6:
            raise RuntimeError(f"unique reference allocation failed: {result.message}")
    return np.asarray(result.x, dtype=float)


def evidence_resolved_reconstruction(
    polytope: FlowPolytope,
    certified_mask: Sequence[bool],
    *,
    evidence_ids: Sequence[str] = (),
    certificate_ids_by_coordinate: Mapping[str, Sequence[str]] | None = None,
    unresolved_weights: Sequence[float] | None = None,
    known_total: float | None = None,
    require_operational_table: bool = False,
    prior_version: str | None = None,
    neutral_bounds: tuple[Sequence[float], Sequence[float]] | None = None,
    tolerance: float = TOLERANCE,
) -> EvidenceResolvedResult:
    """Run ERR on the full feasible polytope without evidential zero-filling."""

    polytope.validate(require_prior=require_operational_table)
    if tolerance <= 0 or not np.isfinite(tolerance):
        raise ValueError("tolerance must be finite and positive")
    if require_operational_table and not str(prior_version or "").strip():
        raise ValueError("a non-empty prior_version is required when an operational table is requested")
    mask = np.asarray(certified_mask, dtype=bool)
    n = len(polytope.variable_names)
    if mask.shape != (n,):
        raise ValueError("certified_mask must align with variable_names")
    weights = np.ones(n) if unresolved_weights is None else np.asarray(unresolved_weights, dtype=float)
    if weights.shape != (n,) or np.any(~np.isfinite(weights)) or np.any(weights < 0):
        raise ValueError("unresolved_weights must be finite and nonnegative")

    cost = weights * (~mask).astype(float)
    minimum_solution = _solve_lp(polytope, cost)
    maximum_solution = _solve_lp(polytope, cost, maximize=True)
    rho_min = float(cost @ minimum_solution.x)
    rho_max = float(cost @ maximum_solution.x)
    constant = rho_max - rho_min <= tolerance
    face = _with_resolution_face(polytope, cost, rho_min, constant)
    if neutral_bounds is None:
        neutral_lower, neutral_upper = _sharp_bounds(polytope)
        neutral_bounds_source = "computed"
    else:
        neutral_lower = _as_float_vector(neutral_bounds[0], n, "neutral_bounds lower")
        neutral_upper = _as_float_vector(neutral_bounds[1], n, "neutral_bounds upper")
        if np.any(neutral_lower < polytope.lower - tolerance) or np.any(neutral_upper > polytope.upper + tolerance) or np.any(neutral_upper < neutral_lower - tolerance):
            raise ValueError("cached neutral bounds are incompatible with the supplied polytope bounds")
        neutral_bounds_source = "caller-supplied exact cache for the same physical polytope"
    face_lower, face_upper = _sharp_bounds(face)

    operational = None
    operational_residuals: dict[str, float] | None = None
    if require_operational_table:
        operational = _unique_reference(face, np.asarray(minimum_solution.x, dtype=float))
        operational_residuals = _constraint_residuals(face, operational)
        if operational_residuals["maximum"] > max(1e-6, 10 * tolerance):
            raise RuntimeError(f"operational allocation violates the resolution face by {operational_residuals['maximum']:g}")

    total = known_total
    if total is None and polytope.A_eq.shape[0]:
        for row, rhs in zip(polytope.A_eq.toarray(), polytope.b_eq):
            if np.allclose(row, np.ones(n), atol=1e-12):
                total = float(rhs)
                break
    ratio_interval = None
    if total is not None and total > 0 and np.allclose(weights, np.ones(n)):
        ratio_interval = (max(0.0, min(1.0, 1.0 - rho_max / total)), max(0.0, min(1.0, 1.0 - rho_min / total)))

    global_evidence = tuple(sorted({str(value).strip() for value in evidence_ids if str(value).strip()}))
    certificate_map = certificate_ids_by_coordinate or {}
    witnesses: list[dict[str, object]] = []
    blockers: list[dict[str, object]] = []
    for index, (name, certified, weight) in enumerate(zip(polytope.variable_names, mask, weights)):
        coordinate_certificates = tuple(sorted({str(value).strip() for value in certificate_map.get(name, ()) if str(value).strip()}))
        witness = {
            "variable": name,
            "certificate_status": "certified" if bool(certified) else "uncertified",
            "certificate_ids": list(coordinate_certificates),
            "global_evidence_ids": list(global_evidence),
            "unresolved_weight": float(weight),
            "witness_completeness": (
                "coordinate_certificate_ids_recorded" if coordinate_certificates else
                "mask_asserted_without_coordinate_certificate_id" if bool(certified) else
                "not_applicable_uncertified"
            ),
        }
        witnesses.append(witness)
        if not bool(certified):
            blockers.append({
                "variable": name,
                "code": "unresolved_identity",
                "reason": "no active certificate authorizes named reporting; coordinate retained as a latent balance variable",
                "neutral_interval": [float(neutral_lower[index]), float(neutral_upper[index])],
            })

    min_residuals = _constraint_residuals(polytope, np.asarray(minimum_solution.x))
    max_residuals = _constraint_residuals(polytope, np.asarray(maximum_solution.x))
    face_residual = abs(float(cost @ minimum_solution.x) - rho_min)
    max_violation = max(min_residuals["maximum"], max_residuals["maximum"], operational_residuals["maximum"] if operational_residuals else 0.0, face_residual)
    resolution_face = {
        "notation": "F*_K = {x in F(E): <w*(1-a_K),x> = rho^-_K}",
        "objective_coefficients": {name: float(value) for name, value in zip(polytope.variable_names, cost)},
        "optimum": rho_min,
        "equals_full_polytope": bool(constant),
        "nonempty_witness": {name: float(value) for name, value in zip(polytope.variable_names, minimum_solution.x)},
    }
    solver_certificate = {
        "minimum_lp_status": str(minimum_solution.message),
        "maximum_lp_status": str(maximum_solution.message),
        "minimum_witness_residuals": min_residuals,
        "maximum_witness_residuals": max_residuals,
        "operational_projection_residuals": operational_residuals,
        "resolution_face_objective_residual": face_residual,
        "maximum_constraint_violation": max_violation,
        "compactness_check": "all coordinate minima and maxima solved to finite optima",
        "neutral_bounds_source": neutral_bounds_source,
    }
    return EvidenceResolvedResult(
        variable_names=polytope.variable_names, certified_mask=mask, unresolved_weights=weights,
        minimum_unresolved_mass=rho_min, maximum_unresolved_mass=rho_max,
        evidence_resolution_ratio_interval=ratio_interval,
        neutral_lower=neutral_lower, neutral_upper=neutral_upper,
        resolved_face_lower=face_lower, resolved_face_upper=face_upper,
        operational_allocation=operational,
        operational_prior_version=str(prior_version).strip() if require_operational_table else None,
        blockers=tuple(blockers), dependency_witness=tuple(witnesses), resolution_face=resolution_face,
        solver_certificate=solver_certificate,
        tolerances={"requested": float(tolerance), "operational_acceptance": max(1e-6, 10 * tolerance)},
    )


def _json_matrix(value: object, rows: int, columns: int, label: str) -> csr_matrix:
    if value is None:
        if rows:
            raise ValueError(f"{label} is required when its right-hand side is non-empty")
        return csr_matrix((0, columns))
    array = np.asarray(value, dtype=float)
    if array.ndim != 2 or array.shape != (rows, columns):
        raise ValueError(f"{label} must have shape ({rows}, {columns})")
    return csr_matrix(array)


def run_evidence_resolved_payload(payload: Mapping[str, object]) -> dict[str, object]:
    """Validated JSON-compatible adapter used by the private review API."""

    names = tuple(str(value).strip() for value in payload.get("variable_names", ()))
    if not names or any(not value for value in names):
        raise ValueError("err_problem.variable_names must contain non-empty names")
    n = len(names)
    lower = _as_float_vector(payload.get("lower", [0.0] * n), n, "lower")
    raw_upper = payload.get("upper", [None] * n)
    if not isinstance(raw_upper, Sequence) or isinstance(raw_upper, (str, bytes)) or len(raw_upper) != n:
        raise ValueError(f"upper must contain {n} values")
    upper = np.asarray([np.inf if value is None else float(value) for value in raw_upper], dtype=float)
    raw_prior = payload.get("prior")
    prior = None if raw_prior is None else _as_float_vector(raw_prior, n, "prior")
    b_eq = np.asarray(payload.get("b_eq", ()), dtype=float)
    b_ub = np.asarray(payload.get("b_ub", ()), dtype=float)
    polytope = FlowPolytope(
        variable_names=names, prior=prior, lower=lower, upper=upper,
        A_eq=_json_matrix(payload.get("A_eq"), len(b_eq), n, "A_eq"), b_eq=b_eq,
        A_ub=_json_matrix(payload.get("A_ub"), len(b_ub), n, "A_ub"), b_ub=b_ub,
        equality_names=tuple(str(value) for value in payload.get("equality_names", ())),
        inequality_names=tuple(str(value) for value in payload.get("inequality_names", ())),
    )
    result = evidence_resolved_reconstruction(
        polytope, payload.get("certified_mask", ()),
        evidence_ids=payload.get("evidence_ids", ()),
        certificate_ids_by_coordinate=payload.get("certificate_ids_by_coordinate", {}),
        unresolved_weights=payload.get("unresolved_weights"), known_total=payload.get("known_total"),
        require_operational_table=bool(payload.get("require_operational_table", False)),
        prior_version=payload.get("prior_version"), tolerance=float(payload.get("tolerance", TOLERANCE)),
    )
    return result.to_dict()
