"""Sparse evidence constraints and scalable TEM-FLOW projections.

The module exposes two complementary computational paths.

``SparseConstraintSystem`` is the general path.  It represents a convex
polytope with sparse equality and inequality matrices, obtains exact sharp
linear bounds with linear programming, and computes the minimum-discrimination
(Kullback-Leibler) reference point inside that polytope.

``project_grouped_kl`` and ``grouped_sharp_bounds`` are the structured fast
path for independent source/commodity/time blocks.  They operate directly on
contiguous sparse-edge vectors and avoid construction of a dense OD matrix.
The grouped bounds are exact, not approximations.
"""

from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter
from typing import Mapping, Sequence

import numpy as np
from scipy.optimize import linprog, minimize
from scipy.sparse import csr_matrix


NUMERICAL_TOLERANCE = 1e-9


def _as_vector(values: Sequence[float], name: str, length: int | None = None) -> np.ndarray:
    array = np.asarray(values, dtype=float)
    if array.ndim != 1 or (length is not None and array.size != length):
        raise ValueError(f"{name} must be a one-dimensional vector of the expected length")
    if np.any(~np.isfinite(array)):
        raise ValueError(f"{name} must contain only finite values")
    return array


def _as_csr(matrix, rows: int | None, columns: int, name: str) -> csr_matrix:
    if matrix is None:
        return csr_matrix((0 if rows is None else rows, columns), dtype=float)
    result = csr_matrix(matrix, dtype=float)
    if result.shape[1] != columns or (rows is not None and result.shape[0] != rows):
        raise ValueError(f"{name} has an incompatible shape")
    if np.any(~np.isfinite(result.data)):
        raise ValueError(f"{name} must contain only finite coefficients")
    return result


@dataclass(frozen=True)
class SparseConstraintSystem:
    """A sparse convex feasible set for non-negative flow variables."""

    variable_names: tuple[str, ...]
    prior: np.ndarray
    lower: np.ndarray
    upper: np.ndarray
    A_eq: csr_matrix
    b_eq: np.ndarray
    A_ub: csr_matrix
    b_ub: np.ndarray

    @property
    def n_variables(self) -> int:
        return self.prior.size

    @property
    def n_constraints(self) -> int:
        return self.A_eq.shape[0] + self.A_ub.shape[0]

    @property
    def constraint_nonzeros(self) -> int:
        return int(self.A_eq.nnz + self.A_ub.nnz)

    def validate(self) -> None:
        n = self.n_variables
        if n == 0 or len(self.variable_names) != n or len(set(self.variable_names)) != n:
            raise ValueError("variable names must be unique and aligned with the flow vector")
        for values, label in ((self.prior, "prior"), (self.lower, "lower")):
            _as_vector(values, label, n)
        upper = np.asarray(self.upper, dtype=float)
        if upper.ndim != 1 or upper.size != n or np.any(np.isnan(upper)) or np.any(np.isneginf(upper)):
            raise ValueError("upper must be a one-dimensional vector of finite values or positive infinity")
        if np.any(self.prior < 0) or np.any(self.lower < 0) or np.any(self.upper < self.lower):
            raise ValueError("prior and bounds must define non-negative flows with lower <= upper")
        if not np.any(self.prior > 0):
            raise ValueError("the reference prior must contain positive mass")
        if self.A_eq.shape != (self.b_eq.size, n) or self.A_ub.shape != (self.b_ub.size, n):
            raise ValueError("constraint matrices and right-hand sides are misaligned")
        _as_vector(self.b_eq, "b_eq", self.A_eq.shape[0])
        _as_vector(self.b_ub, "b_ub", self.A_ub.shape[0])


class ConstraintBuilder:
    """Compile named sparse evidence constraints from coefficient mappings."""

    def __init__(
        self,
        variable_names: Sequence[str],
        prior: Sequence[float],
        lower: Sequence[float] | None = None,
        upper: Sequence[float] | None = None,
    ) -> None:
        self.variable_names = tuple(variable_names)
        self.index = {name: i for i, name in enumerate(self.variable_names)}
        if len(self.index) != len(self.variable_names):
            raise ValueError("variable names must be unique")
        n = len(self.variable_names)
        self.prior = _as_vector(prior, "prior", n)
        self.lower = np.zeros(n) if lower is None else _as_vector(lower, "lower", n)
        self.upper = np.full(n, np.inf) if upper is None else _as_vector(upper, "upper", n)
        self._equalities: list[tuple[dict[int, float], float]] = []
        self._inequalities: list[tuple[dict[int, float], float]] = []

    def _coerce_coefficients(self, coefficients: Mapping[str | int, float]) -> dict[int, float]:
        row: dict[int, float] = {}
        for key, value in coefficients.items():
            index = self.index[key] if isinstance(key, str) else int(key)
            if not 0 <= index < len(self.variable_names) or not np.isfinite(value):
                raise ValueError("constraint contains an invalid variable or coefficient")
            if value:
                row[index] = row.get(index, 0.0) + float(value)
        if not row:
            raise ValueError("a constraint must involve at least one variable")
        return row

    def add_equality(self, coefficients: Mapping[str | int, float], value: float) -> "ConstraintBuilder":
        self._equalities.append((self._coerce_coefficients(coefficients), float(value)))
        return self

    def add_upper(self, coefficients: Mapping[str | int, float], value: float) -> "ConstraintBuilder":
        self._inequalities.append((self._coerce_coefficients(coefficients), float(value)))
        return self

    def add_lower(self, coefficients: Mapping[str | int, float], value: float) -> "ConstraintBuilder":
        row = {key: -coefficient for key, coefficient in self._coerce_coefficients(coefficients).items()}
        self._inequalities.append((row, -float(value)))
        return self

    @staticmethod
    def _matrix(rows: list[tuple[dict[int, float], float]], n: int) -> tuple[csr_matrix, np.ndarray]:
        data: list[float] = []
        row_index: list[int] = []
        column_index: list[int] = []
        rhs = np.empty(len(rows), dtype=float)
        for r, (coefficients, value) in enumerate(rows):
            rhs[r] = value
            for column, coefficient in coefficients.items():
                row_index.append(r)
                column_index.append(column)
                data.append(coefficient)
        return csr_matrix((data, (row_index, column_index)), shape=(len(rows), n)), rhs

    def build(self) -> SparseConstraintSystem:
        n = len(self.variable_names)
        A_eq, b_eq = self._matrix(self._equalities, n)
        A_ub, b_ub = self._matrix(self._inequalities, n)
        system = SparseConstraintSystem(
            self.variable_names,
            self.prior.copy(),
            self.lower.copy(),
            self.upper.copy(),
            A_eq,
            b_eq,
            A_ub,
            b_ub,
        )
        system.validate()
        return system


@dataclass(frozen=True)
class LinearSolveResult:
    values: np.ndarray
    objective: float
    runtime_seconds: float
    status: str


@dataclass(frozen=True)
class ProjectionResult:
    values: np.ndarray
    objective: float
    runtime_seconds: float
    iterations: int
    maximum_violation: float
    status: str


def _linprog_bounds(system: SparseConstraintSystem) -> list[tuple[float, float | None]]:
    return [
        (float(lower), None if np.isposinf(upper) else float(upper))
        for lower, upper in zip(system.lower, system.upper)
    ]


def solve_linear_objective(
    system: SparseConstraintSystem,
    objective: Sequence[float],
    maximize: bool = False,
) -> LinearSolveResult:
    """Solve a linear objective exactly over the evidence-defined polytope."""
    system.validate()
    coefficients = _as_vector(objective, "objective", system.n_variables)
    signed = -coefficients if maximize else coefficients
    started = perf_counter()
    result = linprog(
        signed,
        A_ub=system.A_ub if system.A_ub.shape[0] else None,
        b_ub=system.b_ub if system.A_ub.shape[0] else None,
        A_eq=system.A_eq if system.A_eq.shape[0] else None,
        b_eq=system.b_eq if system.A_eq.shape[0] else None,
        bounds=_linprog_bounds(system),
        method="highs",
    )
    elapsed = perf_counter() - started
    if not result.success:
        raise ValueError(f"constraint system is not solvable: {result.message}")
    objective_value = float(coefficients @ result.x)
    return LinearSolveResult(np.asarray(result.x), objective_value, elapsed, str(result.message))


def feasible_point(system: SparseConstraintSystem) -> LinearSolveResult:
    """Return one feasible flow vector or raise an explicit infeasibility error."""
    return solve_linear_objective(system, np.zeros(system.n_variables))


def sharp_flow_bounds(
    system: SparseConstraintSystem,
    indices: Sequence[int] | None = None,
) -> tuple[np.ndarray, np.ndarray, float]:
    """Obtain exact marginal bounds for selected flow variables.

    Each endpoint is a linear-program optimum and is therefore sharp for the
    stated feasible set.  Endpoints for different variables need not be
    attainable simultaneously.
    """
    requested = np.arange(system.n_variables) if indices is None else np.asarray(indices, dtype=int)
    if requested.ndim != 1 or np.any((requested < 0) | (requested >= system.n_variables)):
        raise ValueError("indices contain an invalid variable")
    lower = np.empty(requested.size)
    upper = np.empty(requested.size)
    started = perf_counter()
    objective = np.zeros(system.n_variables)
    for position, index in enumerate(requested):
        objective[index] = 1.0
        lower[position] = solve_linear_objective(system, objective).objective
        upper[position] = solve_linear_objective(system, objective, maximize=True).objective
        objective[index] = 0.0
    return lower, upper, perf_counter() - started


def maximum_constraint_violation(system: SparseConstraintSystem, values: Sequence[float]) -> float:
    x = _as_vector(values, "values", system.n_variables)
    violations = [0.0]
    violations.append(float(np.max(np.maximum(system.lower - x, 0.0))))
    violations.append(float(np.max(np.maximum(x - system.upper, 0.0))))
    if system.A_eq.shape[0]:
        violations.append(float(np.max(np.abs(system.A_eq @ x - system.b_eq))))
    if system.A_ub.shape[0]:
        violations.append(float(np.max(np.maximum(system.A_ub @ x - system.b_ub, 0.0))))
    return max(violations)


def project_general_kl(
    system: SparseConstraintSystem,
    initial: Sequence[float] | None = None,
    tolerance: float = 1e-8,
    max_iterations: int = 2_000,
) -> ProjectionResult:
    """Project a reference prior onto a general sparse convex feasible set.

    The bounded entropy conjugate eliminates the primal flow vector from the
    optimization.  The resulting dual has one variable per evidence constraint
    and requires only sparse matrix-vector products.  Equality multipliers are
    free and inequality multipliers are non-negative.  Independent blocks can
    still use :func:`project_grouped_kl` for a faster closed-form path.
    """
    system.validate()
    feasible = feasible_point(system).values if initial is None else _as_vector(initial, "initial", system.n_variables)
    if maximum_constraint_violation(system, feasible) > 1e-6:
        raise ValueError("initial vector is not feasible")
    prior = np.maximum(system.prior, 1e-300)

    n_equalities = system.A_eq.shape[0]
    n_inequalities = system.A_ub.shape[0]

    def primal_from_dual(dual: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        equality_dual = dual[:n_equalities]
        inequality_dual = dual[n_equalities:]
        linear = np.zeros(system.n_variables)
        if n_equalities:
            linear += np.asarray(system.A_eq.T @ equality_dual).ravel()
        if n_inequalities:
            linear += np.asarray(system.A_ub.T @ inequality_dual).ravel()
        conjugate_argument = -linear
        unconstrained = prior * np.exp(np.clip(conjugate_argument, -700.0, 700.0))
        return np.clip(unconstrained, system.lower, system.upper), conjugate_argument

    def dual_objective_gradient(dual: np.ndarray) -> tuple[float, np.ndarray]:
        x, conjugate_argument = primal_from_dual(dual)
        positive = x > 0
        primal_terms = np.full_like(x, prior)
        primal_terms[positive] = (
            x[positive] * np.log(x[positive] / prior[positive])
            - x[positive]
            + prior[positive]
        )
        conjugate = float(np.sum(conjugate_argument * x - primal_terms))
        equality_dual = dual[:n_equalities]
        inequality_dual = dual[n_equalities:]
        value = conjugate
        gradient_parts: list[np.ndarray] = []
        if n_equalities:
            value += float(system.b_eq @ equality_dual)
            gradient_parts.append(system.b_eq - np.asarray(system.A_eq @ x).ravel())
        if n_inequalities:
            value += float(system.b_ub @ inequality_dual)
            gradient_parts.append(system.b_ub - np.asarray(system.A_ub @ x).ravel())
        gradient = np.concatenate(gradient_parts) if gradient_parts else np.empty(0)
        return value, gradient

    if n_equalities + n_inequalities == 0:
        x = np.clip(prior, system.lower, system.upper)
        violation = maximum_constraint_violation(system, x)
        return ProjectionResult(x, 0.0, 0.0, 0, violation, "unconstrained bounded prior")

    dual_start = np.zeros(n_equalities + n_inequalities)
    dual_bounds = [(None, None)] * n_equalities + [(0.0, None)] * n_inequalities
    started = perf_counter()
    result = minimize(
        dual_objective_gradient,
        dual_start,
        jac=True,
        method="L-BFGS-B",
        bounds=dual_bounds,
        options={"ftol": tolerance * tolerance, "gtol": tolerance, "maxiter": max_iterations, "maxls": 50},
    )
    elapsed = perf_counter() - started
    x, _ = primal_from_dual(result.x)
    violation = maximum_constraint_violation(system, x)
    if not result.success or violation > max(1e-6, 10 * tolerance):
        raise RuntimeError(f"KL projection failed: {result.message}; maximum violation={violation:g}")
    positive = x > 0
    terms = np.full_like(x, prior)
    terms[positive] = x[positive] * np.log(x[positive] / prior[positive]) - x[positive] + prior[positive]
    return ProjectionResult(
        x,
        float(np.sum(terms)),
        elapsed,
        int(result.nit),
        violation,
        str(result.message),
    )


def _validate_grouped_inputs(
    prior: Sequence[float],
    group_offsets: Sequence[int],
    totals: Sequence[float],
    lower: Sequence[float] | None,
    upper: Sequence[float] | None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    p = _as_vector(prior, "prior")
    if p.size == 0 or np.any(p < 0):
        raise ValueError("prior must contain non-negative flow weights")
    offsets = np.asarray(group_offsets, dtype=np.int64)
    if offsets.ndim != 1 or offsets.size < 2 or offsets[0] != 0 or offsets[-1] != p.size or np.any(np.diff(offsets) <= 0):
        raise ValueError("group_offsets must define non-empty contiguous groups covering every variable")
    group_totals = _as_vector(totals, "totals", offsets.size - 1)
    lo = np.zeros_like(p) if lower is None else _as_vector(lower, "lower", p.size)
    hi = np.full_like(p, np.inf) if upper is None else _as_vector(upper, "upper", p.size)
    if np.any(group_totals < 0) or np.any(lo < 0) or np.any(hi < lo):
        raise ValueError("invalid grouped totals or bounds")
    return np.maximum(p, 1e-300), offsets, group_totals, lo, hi


def _project_equal_groups(
    prior: np.ndarray,
    group_size: int,
    totals: np.ndarray,
    lower: np.ndarray,
    upper: np.ndarray,
    tolerance: float,
) -> np.ndarray:
    groups = totals.size
    p = prior.reshape(groups, group_size)
    lo = lower.reshape(groups, group_size)
    hi = upper.reshape(groups, group_size)
    if np.any(lo.sum(axis=1) > totals + tolerance) or np.any(hi.sum(axis=1) < totals - tolerance):
        raise ValueError("at least one grouped bounded simplex is infeasible")
    left = np.zeros(groups)
    right = np.ones(groups)
    for _ in range(1_024):
        mass = np.clip(right[:, None] * p, lo, hi).sum(axis=1)
        incomplete = mass < totals
        if not np.any(incomplete):
            break
        right[incomplete] *= 2.0
    else:
        raise RuntimeError("failed to bracket grouped KL projection")
    for _ in range(100):
        middle = 0.5 * (left + right)
        mass = np.clip(middle[:, None] * p, lo, hi).sum(axis=1)
        incomplete = mass < totals
        left[incomplete] = middle[incomplete]
        right[~incomplete] = middle[~incomplete]
        if np.max(right - left) <= tolerance * max(1.0, float(np.max(right))):
            break
    result = np.clip((0.5 * (left + right))[:, None] * p, lo, hi)
    residual = totals - result.sum(axis=1)
    for row in np.flatnonzero(np.abs(residual) > 10 * tolerance):
        if residual[row] > 0:
            candidates = np.flatnonzero(hi[row] - result[row] > tolerance)
        else:
            candidates = np.flatnonzero(result[row] - lo[row] > tolerance)
        for column in candidates:
            adjustment = min(abs(residual[row]), hi[row, column] - result[row, column]) if residual[row] > 0 else min(abs(residual[row]), result[row, column] - lo[row, column])
            result[row, column] += np.sign(residual[row]) * adjustment
            residual[row] -= np.sign(residual[row]) * adjustment
            if abs(residual[row]) <= 10 * tolerance:
                break
    if np.max(np.abs(result.sum(axis=1) - totals)) > 1e-7:
        raise RuntimeError("grouped projection did not conserve block totals")
    return result.ravel()


def project_grouped_kl(
    prior: Sequence[float],
    group_offsets: Sequence[int],
    totals: Sequence[float],
    lower: Sequence[float] | None = None,
    upper: Sequence[float] | None = None,
    tolerance: float = NUMERICAL_TOLERANCE,
) -> np.ndarray:
    """Exact KL projection for independent contiguous flow blocks.

    Equal-sized groups are projected in vectorized batches.  Ragged groups use
    the same bounded-simplex solution one block at a time.
    """
    p, offsets, group_totals, lo, hi = _validate_grouped_inputs(prior, group_offsets, totals, lower, upper)
    sizes = np.diff(offsets)
    if np.all(sizes == sizes[0]):
        return _project_equal_groups(p, int(sizes[0]), group_totals, lo, hi, tolerance)

    from .core import kl_box_projection

    result = np.empty_like(p)
    for group, (start, stop) in enumerate(zip(offsets[:-1], offsets[1:])):
        result[start:stop] = kl_box_projection(
            p[start:stop],
            total=float(group_totals[group]),
            lower=lo[start:stop],
            upper=hi[start:stop],
            tol=tolerance,
        )
    return result


def grouped_sharp_bounds(
    group_offsets: Sequence[int],
    totals: Sequence[float],
    lower: Sequence[float],
    upper: Sequence[float],
) -> tuple[np.ndarray, np.ndarray]:
    """Exact all-variable bounds for independent bounded-sum groups."""
    lo = _as_vector(lower, "lower")
    hi = _as_vector(upper, "upper", lo.size)
    dummy_prior = np.ones(lo.size)
    _, offsets, group_totals, lo, hi = _validate_grouped_inputs(dummy_prior, group_offsets, totals, lo, hi)
    sizes = np.diff(offsets)
    group_index = np.repeat(np.arange(group_totals.size), sizes)
    sum_lower = np.add.reduceat(lo, offsets[:-1])
    sum_upper = np.add.reduceat(hi, offsets[:-1])
    if np.any(sum_lower > group_totals + NUMERICAL_TOLERANCE) or np.any(sum_upper < group_totals - NUMERICAL_TOLERANCE):
        raise ValueError("at least one grouped bounded simplex is infeasible")
    sharp_lower = np.maximum(lo, group_totals[group_index] - (sum_upper[group_index] - hi))
    sharp_upper = np.minimum(hi, group_totals[group_index] - (sum_lower[group_index] - lo))
    return sharp_lower, sharp_upper


def update_grouped_projection(
    previous: Sequence[float],
    prior: Sequence[float],
    group_offsets: Sequence[int],
    totals: Sequence[float],
    changed_groups: Sequence[int],
    lower: Sequence[float] | None = None,
    upper: Sequence[float] | None = None,
) -> np.ndarray:
    """Reproject only blocks affected by an additive or superseding record."""
    p, offsets, group_totals, lo, hi = _validate_grouped_inputs(prior, group_offsets, totals, lower, upper)
    result = _as_vector(previous, "previous", p.size).copy()
    selected = np.unique(np.asarray(changed_groups, dtype=int))
    if np.any((selected < 0) | (selected >= group_totals.size)):
        raise ValueError("changed_groups contains an invalid block")
    from .core import kl_box_projection

    for group in selected:
        start, stop = offsets[group], offsets[group + 1]
        result[start:stop] = kl_box_projection(
            p[start:stop],
            total=float(group_totals[group]),
            lower=lo[start:stop],
            upper=hi[start:stop],
        )
    return result

