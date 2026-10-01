"""Research extension for TEM-FLOW: bounded-error measurement design.

This is an exploratory module, not part of the published v1.0.0 release.
It extends established optimal-recovery and implicit hitting-set ideas.
See mathematical_note.tex for assumptions, proofs, and attribution.
All guarantees are conditional on the supplied polytope and error bounds.
"""
from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations
import numpy as np
from scipy.optimize import linprog, milp, Bounds, LinearConstraint
from scipy.sparse import block_diag, csr_matrix, hstack, vstack


class DesignError(ValueError):
    """Invalid, infeasible, unauthorized, or numerically unresolved input."""


def vector(values, size, name):
    a = np.asarray(values, dtype=float)
    if a.shape != (size,) or not np.isfinite(a).all():
        raise DesignError(f"{name} must have {size} finite entries")
    return a.copy()


def matrix(values, size, name):
    a = csr_matrix((0, size)) if values is None else csr_matrix(values, dtype=float)
    if a.shape[1] != size or not np.isfinite(a.data).all():
        raise DesignError(f"{name} has incompatible columns or nonfinite entries")
    return a.copy()


@dataclass
class FlowSet:
    names: tuple[str, ...]
    lower: np.ndarray
    upper: np.ndarray
    A_eq: csr_matrix
    b_eq: np.ndarray
    A_ub: csr_matrix
    b_ub: np.ndarray

    @classmethod
    def create(cls, names, lower, upper, A_eq=None, b_eq=(), A_ub=None, b_ub=()):
        names = tuple(names)
        n = len(names)
        if n == 0 or len(set(names)) != n or any(not x for x in names):
            raise DesignError("flow variable names must be nonempty and unique")
        lo, hi = vector(lower, n, "lower"), vector(upper, n, "upper")
        if np.any(lo < 0) or np.any(lo > hi):
            raise DesignError("finite bounds must satisfy 0 <= lower <= upper")
        eq, ub = matrix(A_eq, n, "A_eq"), matrix(A_ub, n, "A_ub")
        return cls(names, lo, hi, eq, vector(b_eq, eq.shape[0], "b_eq"),
                   ub, vector(b_ub, ub.shape[0], "b_ub"))

    @classmethod
    def from_temflow(cls, polytope):
        """Copy the full neutral FlowPolytope, including latent coordinates.

        The prototype requires finite physical upper bounds. It deliberately
        does not use a prior or the minimum-unresolved-mass optimum face.
        Upstream identity authorization must be supplied separately.
        """
        polytope.validate()
        return cls.create(polytope.variable_names, polytope.lower, polytope.upper,
                          polytope.A_eq, polytope.b_eq, polytope.A_ub, polytope.b_ub)


class MeasurementDesign:
    def __init__(self, flows, H, error, costs, target, tolerance,
                 measurement_names=None, target_names=None,
                 eligible=None, target_authorized=None, numerical_tolerance=1e-8):
        self.flows = flows
        n = len(flows.names)
        self.H = matrix(H, n, "H").toarray()
        self.L = matrix(target, n, "target").toarray()
        self.m, self.k = len(self.H), len(self.L)
        if self.k == 0:
            raise DesignError("at least one target is required")
        self.error = vector(error, self.m, "error")
        self.costs = vector(costs, self.m, "costs")
        self.tolerance = vector(tolerance, self.k, "tolerance")
        if (self.error < 0).any() or (self.costs < 0).any() or (self.tolerance <= 0).any():
            raise DesignError("errors/costs must be nonnegative and tolerances positive")
        self.eligible = np.ones(self.m, bool) if eligible is None else np.asarray(eligible, bool)
        self.authorized = np.ones(self.k, bool) if target_authorized is None else np.asarray(target_authorized, bool)
        if self.eligible.shape != (self.m,) or self.authorized.shape != (self.k,):
            raise DesignError("eligibility or target authorization is misaligned")
        if not self.authorized.all():
            raise DesignError("blocked target identity: precision cannot authorize a named route")
        self.measurement_names = tuple(measurement_names or [f"m{i}" for i in range(self.m)])
        self.target_names = tuple(target_names or [f"q{i}" for i in range(self.k)])
        if (len(self.measurement_names) != self.m or len(set(self.measurement_names)) != self.m
                or len(self.target_names) != self.k or len(set(self.target_names)) != self.k):
            raise DesignError("measurement and target names must be aligned and unique")
        self.numtol = float(numerical_tolerance)
        if not np.isfinite(self.numtol) or self.numtol <= 0:
            raise DesignError("numerical tolerance must be positive and finite")
        self.lp_calls = 0
        self._cache = {}
        self._lp(np.zeros(n), flows.A_ub, flows.b_ub, flows.A_eq, flows.b_eq,
                 list(zip(flows.lower, flows.upper)))

    def _lp(self, c, A_ub, b_ub, A_eq, b_eq, bounds):
        self.lp_calls += 1
        result = linprog(c, A_ub=A_ub if A_ub.shape[0] else None,
                         b_ub=b_ub if A_ub.shape[0] else None,
                         A_eq=A_eq if A_eq.shape[0] else None,
                         b_eq=b_eq if A_eq.shape[0] else None, bounds=bounds,
                         method="highs", options={"primal_feasibility_tolerance": 1e-9,
                                                  "dual_feasibility_tolerance": 1e-9})
        if not result.success:
            raise DesignError(f"LP {result.status}: {result.message}")
        violation = 0.0
        if A_ub.shape[0]:
            violation = max(violation, float(np.max(A_ub @ result.x - b_ub)))
        if A_eq.shape[0]:
            violation = max(violation, float(np.max(np.abs(A_eq @ result.x - b_eq))))
        lo, hi = np.asarray(bounds).T
        violation = max(violation, float(np.max(lo-result.x)), float(np.max(result.x-hi)))
        # Finite bounds permit a direct primal/dual objective consistency check.
        dual = float(lo @ result.lower.marginals + hi @ result.upper.marginals)
        if A_ub.shape[0]: dual += float(b_ub @ result.ineqlin.marginals)
        if A_eq.shape[0]: dual += float(b_eq @ result.eqlin.marginals)
        gap = abs(float(result.fun) - dual)
        if violation > 10*self.numtol or gap > 10*self.numtol*max(1.0, abs(result.fun)):
            raise DesignError("LP numerical verification failed")
        result.audit = {"maximum_primal_violation": max(0.0, violation), "duality_gap": gap}
        return result

    def _selection(self, selected):
        selected = tuple(sorted(set(selected)))
        if any(not isinstance(i, (int, np.integer)) or i < 0 or i >= self.m for i in selected):
            raise DesignError("unknown measurement index")
        if any(not self.eligible[i] for i in selected):
            raise DesignError("selection includes an ineligible measurement")
        return tuple(int(i) for i in selected)

    def diameter(self, selected):
        """Sharp worst-response normalized target width and an ambiguity pair.

        A result of at most one means every target's range is no wider than
        its requested tolerance for every compatible future reading.
        This is not a probabilistic coverage claim.
        """
        selected = self._selection(selected)
        if selected in self._cache: return self._cache[selected]
        f, n = self.flows, len(self.flows.names)
        eq, ub = block_diag((f.A_eq, f.A_eq), format="csr"), block_diag((f.A_ub, f.A_ub), format="csr")
        beq, bub = np.tile(f.b_eq, 2), np.tile(f.b_ub, 2)
        if selected:
            h = csr_matrix(self.H[list(selected)])
            d = hstack((h, -h), format="csr")
            ub = vstack((ub, d, -d), format="csr")
            bub = np.concatenate((bub, 2*self.error[list(selected)], 2*self.error[list(selected)]))
        bounds = list(zip(f.lower, f.upper))*2
        worst, widths, audits = None, [], []
        for j, row in enumerate(self.L):
            direction = np.concatenate((row, -row))/self.tolerance[j]
            result = self._lp(-direction, ub, bub, eq, beq, bounds)
            width = max(0.0, float(direction @ result.x))
            widths.append(width)
            audits.append(result.audit)
            if worst is None or width > worst["diameter"]:
                x, xp = result.x[:n], result.x[n:]
                worst = {"diameter": width, "target_index": j,
                         "x": x.tolist(), "x_prime": xp.tolist(),
                         "common_reading": (self.H @ ((x+xp)/2)).tolist()}
        worst.update({"selected": list(selected), "normalized_widths": widths,
                      "physical_widths": (np.asarray(widths)*self.tolerance).tolist(),
                      "maximum_primal_violation": max(a["maximum_primal_violation"] for a in audits),
                      "maximum_duality_gap": max(a["duality_gap"] for a in audits)})
        self._cache[selected] = worst
        return worst

    def robust_diameter(self, selected, failures=0):
        selected = self._selection(selected)
        if not isinstance(failures, int) or failures < 0:
            raise DesignError("failures must be a nonnegative integer")
        worst = None
        # Monotonicity makes the largest permitted erasure count sufficient.
        for erased in combinations(selected, min(failures, len(selected))):
            retained = tuple(i for i in selected if i not in erased)
            result = self.diameter(retained)
            if worst is None or result["diameter"] > worst["diameter"]:
                worst = dict(result, installed=list(selected), erased=list(erased))
        return worst

    def posterior_widths(self, selected, reading):
        """Actual post-measurement widths; an incompatible reading raises."""
        selected = self._selection(selected)
        y = vector(reading, len(selected), "reading")
        f = self.flows
        h = csr_matrix(self.H[list(selected)])
        ub = vstack((f.A_ub, h, -h), format="csr")
        bub = np.concatenate((f.b_ub, y+self.error[list(selected)], -y+self.error[list(selected)]))
        bounds = list(zip(f.lower, f.upper))
        widths = []
        for row in self.L:
            a = self._lp(row, ub, bub, f.A_eq, f.b_eq, bounds)
            b = self._lp(-row, ub, bub, f.A_eq, f.b_eq, bounds)
            widths.append(max(0.0, -float(b.fun)-float(a.fun)))
        return widths

    def minimum_cost(self, failures=0, max_iterations=4096):
        """Witness-guided multicover with exact MILP masters and LP oracles.

        Mathematical exactness is proved for exact oracles; this implementation
        reports floating-point solver checks and tolerances, not formal proof.
        Failure budgets refer to known missing readings, not silent corruption.
        """
        if not isinstance(max_iterations, int) or max_iterations < 1:
            raise DesignError("max_iterations must be a positive integer")
        all_available = tuple(int(i) for i in np.flatnonzero(self.eligible))
        full = self.robust_diameter(all_available, failures)
        if full["diameter"] > 1+self.numtol:
            return {"status": "impossible_with_available_measurements", "witness": full,
                    "selected": [], "cost": None, "cuts": [], "lp_calls": self.lp_calls}
        cuts, history, seen = [], [], set()
        selected, lower_bound = (), 0.0
        for iteration in range(max_iterations):
            if cuts:
                a = np.zeros((len(cuts), self.m))
                for j, cut in enumerate(cuts): a[j, cut["indices"]] = 1
                solve = milp(self.costs, integrality=np.ones(self.m),
                             bounds=Bounds(np.zeros(self.m), self.eligible.astype(float)),
                             constraints=LinearConstraint(a, [c["rhs"] for c in cuts], np.inf),
                             options={"mip_rel_gap": 0.0})
                if not solve.success:
                    raise DesignError(f"MILP not optimal: {solve.message}")
                selected = tuple(int(i) for i in np.flatnonzero(solve.x > .5))
                lower_bound = float(solve.mip_dual_bound)
            cert = self.robust_diameter(selected, failures)
            cost = float(self.costs[list(selected)].sum())
            history.append({"iteration": iteration, "selected": list(selected), "cost": cost,
                            "lower_bound": lower_bound, "diameter": cert["diameter"]})
            if cert["diameter"] <= 1+self.numtol:
                return {"status": "optimal_within_numerical_tolerance", "selected": list(selected),
                        "measurement_names": [self.measurement_names[i] for i in selected],
                        "cost": cost, "lower_bound": lower_bound,
                        "absolute_cost_gap": max(0.0, cost-lower_bound), "witness": cert,
                        "cuts": cuts, "history": history, "lp_calls": self.lp_calls,
                        "numerical_tolerance": self.numtol, "failures": failures}
            difference = np.asarray(cert["x"])-np.asarray(cert["x_prime"])
            gaps = np.abs(self.H @ difference)-2*self.error
            # A conservative superset of strict separators keeps a cut weak,
            # rather than excluding a feasible design at a floating boundary.
            indices = tuple(i for i in all_available if gaps[i] >= -self.numtol)
            rhs, kind = failures+1, "ambiguity_pair_multicover"
            if sum(i in selected for i in indices) >= rhs:
                # Numerical near-equality: monotonicity excludes S and subsets.
                indices = tuple(i for i in all_available if i not in selected)
                rhs, kind = 1, "failed_selection_monotone_cut"
            key = (indices, rhs)
            if key in seen or not indices:
                raise DesignError("unresolved numerical separation; no optimality claim")
            seen.add(key)
            cuts.append({"indices": list(indices), "rhs": rhs, "kind": kind,
                         "target_index": cert["target_index"], "diameter": cert["diameter"],
                         "x": cert["x"], "x_prime": cert["x_prime"]})
        return {"status": "iteration_limit", "selected": list(selected),
                "lower_bound": lower_bound, "cuts": cuts, "history": history,
                "lp_calls": self.lp_calls, "witness": cert}

    def exhaustive_minimum_cost(self, failures=0):
        """Small-catalogue independent subset search for verification only."""
        available = tuple(np.flatnonzero(self.eligible))
        best = None
        for count in range(len(available)+1):
            for selected in combinations(available, count):
                cost = float(self.costs[list(selected)].sum())
                if best is not None and cost >= best["cost"]: continue
                result = self.robust_diameter(selected, failures)
                if result["diameter"] <= 1+self.numtol:
                    best = {"selected": list(selected), "cost": cost, "diameter": result["diameter"]}
        return best


def from_payload(payload):
    f = FlowSet.create(**payload["flow_set"])
    return MeasurementDesign(f, **payload["design"])


if __name__ == "__main__":
    import argparse, json
    from pathlib import Path
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("input", type=Path)
    p.add_argument("--failures", type=int, default=0)
    p.add_argument("--output", type=Path)
    a = p.parse_args()
    result = from_payload(json.loads(a.input.read_text(encoding="utf-8"))).minimum_cost(a.failures)
    rendered = json.dumps(result, indent=2)
    if a.output: a.output.write_text(rendered, encoding="utf-8")
    else: print(rendered)
