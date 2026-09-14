import unittest

import numpy as np

from temflow.constraints import (
    ConstraintBuilder,
    feasible_point,
    grouped_sharp_bounds,
    maximum_constraint_violation,
    project_general_kl,
    project_grouped_kl,
    sharp_flow_bounds,
    update_grouped_projection,
)


class ConstraintSystemTests(unittest.TestCase):
    def coupled_system(self):
        builder = ConstraintBuilder(
            ["A-X", "A-Y", "B-X", "B-Y"],
            prior=[0.7, 0.3, 0.2, 0.8],
            lower=[0.0, 0.0, 0.0, 0.0],
            upper=[1.0, 1.0, 1.0, 1.0],
        )
        builder.add_equality({"A-X": 1, "A-Y": 1}, 1.0)
        builder.add_equality({"B-X": 1, "B-Y": 1}, 1.0)
        builder.add_lower({"A-X": 1, "B-X": 1}, 0.55)
        builder.add_upper({"A-X": 1, "B-X": 1}, 0.75)
        return builder.build()

    def test_general_system_finds_feasible_point(self):
        system = self.coupled_system()
        result = feasible_point(system)
        self.assertLess(maximum_constraint_violation(system, result.values), 1e-9)

    def test_general_sharp_bounds_are_exact(self):
        system = self.coupled_system()
        lower, upper, _ = sharp_flow_bounds(system, [0])
        self.assertAlmostEqual(lower[0], 0.0, places=8)
        self.assertAlmostEqual(upper[0], 0.75, places=8)

    def test_general_kl_projection_respects_overlapping_constraints(self):
        system = self.coupled_system()
        result = project_general_kl(system)
        self.assertLess(result.maximum_violation, 1e-6)
        self.assertAlmostEqual(result.values[0] + result.values[1], 1.0, places=7)
        self.assertAlmostEqual(result.values[2] + result.values[3], 1.0, places=7)

    def test_sparse_dual_projection_matches_grouped_closed_form(self):
        offsets = np.array([0, 3, 6])
        totals = np.array([1.0, 2.0])
        prior = np.array([0.6, 0.3, 0.1, 0.2, 0.7, 0.1])
        lower = np.array([0.1, 0.0, 0.0, 0.0, 0.4, 0.0])
        upper = np.array([0.7, 0.8, 0.5, 1.5, 1.2, 1.0])
        expected = project_grouped_kl(prior, offsets, totals, lower, upper)
        builder = ConstraintBuilder([f"x{i}" for i in range(6)], prior, lower, upper)
        builder.add_equality({0: 1, 1: 1, 2: 1}, 1.0)
        builder.add_equality({3: 1, 4: 1, 5: 1}, 2.0)
        observed = project_general_kl(builder.build()).values
        np.testing.assert_allclose(observed, expected, atol=2e-7)

    def test_sparse_dual_projection_matches_ipf_for_exact_margins(self):
        rng = np.random.default_rng(20260820)
        rows, columns = 4, 5
        prior = rng.lognormal(size=(rows, columns))
        truth = rng.lognormal(size=(rows, columns))
        row_totals = truth.sum(axis=1)
        column_totals = truth.sum(axis=0)

        ipf = prior.copy()
        for _ in range(20_000):
            previous = ipf.copy()
            ipf *= (row_totals / ipf.sum(axis=1))[:, None]
            ipf *= (column_totals / ipf.sum(axis=0))[None, :]
            if np.max(np.abs(ipf - previous)) < 1e-12:
                break

        names = [f"x_{i}_{j}" for i in range(rows) for j in range(columns)]
        builder = ConstraintBuilder(names, prior.ravel())
        for i in range(rows):
            builder.add_equality({i * columns + j: 1.0 for j in range(columns)}, row_totals[i])
        # One column equality is redundant once every row total and the other
        # column totals are fixed.  Removing it gives an identifiable dual.
        for j in range(columns - 1):
            builder.add_equality({i * columns + j: 1.0 for i in range(rows)}, column_totals[j])

        initial = np.outer(row_totals, column_totals) / row_totals.sum()
        observed = project_general_kl(builder.build(), initial=initial.ravel()).values
        np.testing.assert_allclose(observed.reshape(rows, columns), ipf, atol=2e-7)

    def test_infeasible_system_is_rejected(self):
        builder = ConstraintBuilder(["x", "y"], [0.5, 0.5], upper=[0.4, 0.4])
        builder.add_equality({"x": 1, "y": 1}, 1.0)
        with self.assertRaises(ValueError):
            feasible_point(builder.build())


class GroupedFastPathTests(unittest.TestCase):
    def setUp(self):
        self.offsets = np.array([0, 3, 6])
        self.totals = np.array([1.0, 2.0])
        self.prior = np.array([0.6, 0.3, 0.1, 0.2, 0.7, 0.1])
        self.lower = np.array([0.1, 0.0, 0.0, 0.0, 0.4, 0.0])
        self.upper = np.array([0.7, 0.8, 0.5, 1.5, 1.2, 1.0])

    def test_group_projection_conserves_every_block(self):
        values = project_grouped_kl(self.prior, self.offsets, self.totals, self.lower, self.upper)
        self.assertAlmostEqual(values[:3].sum(), 1.0, places=8)
        self.assertAlmostEqual(values[3:].sum(), 2.0, places=8)
        self.assertTrue(np.all(values >= self.lower - 1e-9))
        self.assertTrue(np.all(values <= self.upper + 1e-9))

    def test_grouped_bounds_match_linear_program(self):
        grouped_lower, grouped_upper = grouped_sharp_bounds(
            self.offsets, self.totals, self.lower, self.upper
        )
        builder = ConstraintBuilder(
            [f"x{i}" for i in range(6)], self.prior, self.lower, self.upper
        )
        builder.add_equality({0: 1, 1: 1, 2: 1}, 1.0)
        builder.add_equality({3: 1, 4: 1, 5: 1}, 2.0)
        exact_lower, exact_upper, _ = sharp_flow_bounds(builder.build())
        np.testing.assert_allclose(grouped_lower, exact_lower, atol=1e-8)
        np.testing.assert_allclose(grouped_upper, exact_upper, atol=1e-8)

    def test_additive_bounds_cannot_widen_identified_interval(self):
        old_lower, old_upper = grouped_sharp_bounds(
            self.offsets, self.totals, self.lower, self.upper
        )
        revised_lower = self.lower.copy()
        revised_upper = self.upper.copy()
        revised_lower[0] = 0.3
        revised_upper[1] = 0.5
        new_lower, new_upper = grouped_sharp_bounds(
            self.offsets, self.totals, revised_lower, revised_upper
        )
        self.assertTrue(np.all(new_lower >= old_lower - 1e-9))
        self.assertTrue(np.all(new_upper <= old_upper + 1e-9))

    def test_incremental_update_changes_only_selected_group(self):
        initial = project_grouped_kl(self.prior, self.offsets, self.totals, self.lower, self.upper)
        revised_lower = self.lower.copy()
        revised_lower[4] = 0.9
        updated = update_grouped_projection(
            initial,
            self.prior,
            self.offsets,
            self.totals,
            [1],
            revised_lower,
            self.upper,
        )
        np.testing.assert_allclose(updated[:3], initial[:3])
        self.assertGreaterEqual(updated[4], 0.9)
        self.assertAlmostEqual(updated[3:].sum(), 2.0, places=8)


if __name__ == "__main__":
    unittest.main()

