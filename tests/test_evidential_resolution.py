from __future__ import annotations

import unittest

import numpy as np
from scipy.sparse import block_diag, csr_matrix

from temflow.evidential_resolution import (
    FlowPolytope,
    evidence_resolved_reconstruction,
    run_evidence_resolved_payload,
)


def two_by_two(
    row: tuple[float, float] = (6.0, 4.0),
    column: tuple[float, float] = (5.0, 5.0),
    scale: float = 1.0,
    prior: bool = True,
) -> FlowPolytope:
    A_eq = csr_matrix([
        [1.0, 1.0, 0.0, 0.0],
        [0.0, 0.0, 1.0, 1.0],
        [1.0, 0.0, 1.0, 0.0],
    ])
    return FlowPolytope(
        variable_names=("11", "12", "21", "22"),
        prior=np.ones(4) * scale if prior else None,
        lower=np.zeros(4),
        upper=np.full(4, np.inf),
        A_eq=A_eq,
        b_eq=np.array([row[0], row[1], column[0]]) * scale,
        A_ub=csr_matrix((0, 4)),
        b_ub=np.empty(0),
        equality_names=("row-1", "row-2", "column-1"),
    )


def certificates(mask: list[bool]) -> dict[str, list[str]]:
    return {name: [f"CERT-{name}"] for name, keep in zip(("11", "12", "21", "22"), mask) if keep}


class EvidenceResolvedReconstructionTests(unittest.TestCase):
    def run_err(self, mask: list[bool], **kwargs):
        return evidence_resolved_reconstruction(
            kwargs.pop("polytope", two_by_two()),
            mask,
            certificate_ids_by_coordinate=certificates(mask),
            known_total=kwargs.pop("known_total", 10.0),
            **kwargs,
        )

    def test_result_1_existence_and_nonempty_optimum_face(self):
        result = self.run_err([True, False, False, True])
        self.assertAlmostEqual(result.minimum_unresolved_mass, 1.0)
        self.assertLess(result.maximum_violation, 1e-7)
        self.assertEqual(set(result.resolution_face["nonempty_witness"]), set(result.variable_names))

    def test_result_2_zero_iff_a_fully_resolved_feasible_allocation_exists(self):
        all_certified = self.run_err([True, True, True, True])
        diagonal = self.run_err([True, False, False, True])
        self.assertAlmostEqual(all_certified.minimum_unresolved_mass, 0.0)
        self.assertGreater(diagonal.minimum_unresolved_mass, 0.0)
        # With strictly positive unresolved weights, rho-=0 is equivalent to a
        # feasible point whose every unresolved coordinate is zero.
        one_route = self.run_err([True, False, True, False])
        self.assertAlmostEqual(one_route.minimum_unresolved_mass, 5.0)

    def test_result_2_caveat_nonnegative_zero_weights_are_allowed(self):
        result = self.run_err(
            [False, False, False, False],
            unresolved_weights=[0.0, 0.0, 0.0, 0.0],
        )
        self.assertAlmostEqual(result.minimum_unresolved_mass, 0.0)
        self.assertAlmostEqual(result.maximum_unresolved_mass, 0.0)
        self.assertIsNone(result.evidence_resolution_ratio_interval)
        with self.assertRaisesRegex(ValueError, "nonnegative"):
            self.run_err([False] * 4, unresolved_weights=[1.0, -1.0, 1.0, 1.0])

    def test_result_3_both_envelope_endpoints_are_antitone(self):
        masks = [
            [False, False, False, False],
            [True, False, False, False],
            [True, False, False, True],
            [True, True, False, True],
            [True, True, True, True],
        ]
        results = [self.run_err(mask) for mask in masks]
        for left, right in zip(results, results[1:]):
            self.assertGreaterEqual(left.minimum_unresolved_mass + 1e-8, right.minimum_unresolved_mass)
            self.assertGreaterEqual(left.maximum_unresolved_mass + 1e-8, right.maximum_unresolved_mass)

    def test_result_4_positive_homogeneity_of_both_endpoints(self):
        base = self.run_err([True, False, False, True])
        scaled = self.run_err(
            [True, False, False, True],
            polytope=two_by_two(scale=7.5),
            known_total=75.0,
        )
        self.assertAlmostEqual(scaled.minimum_unresolved_mass, 7.5 * base.minimum_unresolved_mass)
        self.assertAlmostEqual(scaled.maximum_unresolved_mass, 7.5 * base.maximum_unresolved_mass)

    def test_result_5_cartesian_additivity_of_both_endpoints(self):
        left = two_by_two()
        right = two_by_two(row=(7.0, 3.0), column=(4.0, 6.0))
        product = FlowPolytope(
            variable_names=tuple(f"L-{x}" for x in left.variable_names) + tuple(f"R-{x}" for x in right.variable_names),
            prior=None,
            lower=np.concatenate([left.lower, right.lower]),
            upper=np.concatenate([left.upper, right.upper]),
            A_eq=block_diag((left.A_eq, right.A_eq), format="csr"),
            b_eq=np.concatenate([left.b_eq, right.b_eq]),
            A_ub=csr_matrix((0, 8)),
            b_ub=np.empty(0),
        )
        mask_left = [True, False, False, True]
        mask_right = [False, True, True, False]
        a = evidence_resolved_reconstruction(left, mask_left)
        b = evidence_resolved_reconstruction(right, mask_right)
        combined = evidence_resolved_reconstruction(product, mask_left + mask_right)
        self.assertAlmostEqual(combined.minimum_unresolved_mass, a.minimum_unresolved_mass + b.minimum_unresolved_mass)
        self.assertAlmostEqual(combined.maximum_unresolved_mass, a.maximum_unresolved_mass + b.maximum_unresolved_mass)

    def test_result_6_unique_projection_is_opt_in_and_prior_versioned(self):
        set_result = self.run_err([True, False, False, True])
        self.assertIsNone(set_result.operational_allocation)
        with self.assertRaisesRegex(ValueError, "prior_version"):
            self.run_err([True, False, False, True], require_operational_table=True)
        first = self.run_err(
            [True, False, False, True],
            require_operational_table=True,
            prior_version="PRIOR-2026-09-01",
        )
        second = self.run_err(
            [True, False, False, True],
            require_operational_table=True,
            prior_version="PRIOR-2026-09-01",
        )
        np.testing.assert_allclose(first.operational_allocation, second.operational_allocation, atol=1e-8)
        self.assertEqual(first.operational_prior_version, "PRIOR-2026-09-01")

    def test_result_7_resolution_face_bounds_are_nested_and_sharp(self):
        result = self.run_err([True, False, False, True])
        self.assertTrue(np.all(result.resolved_face_lower >= result.neutral_lower - 1e-8))
        self.assertTrue(np.all(result.resolved_face_upper <= result.neutral_upper + 1e-8))
        self.assertEqual(result.claim("12")["status"], "blocked_unresolved_identity")
        self.assertGreater(result.neutral_upper[1], 0.0)

    def test_result_8_limiting_cases(self):
        complete = self.run_err([True] * 4)
        none = self.run_err([False] * 4)
        self.assertEqual(complete.evidence_resolution_ratio_interval, (1.0, 1.0))
        self.assertAlmostEqual(none.minimum_unresolved_mass, 10.0)
        self.assertAlmostEqual(none.maximum_unresolved_mass, 10.0)
        self.assertEqual(none.evidence_resolution_ratio_interval, (0.0, 0.0))

    def test_integrated_result_serializes_all_coordinates_witnesses_and_residuals(self):
        result = self.run_err(
            [True, False, False, True],
            evidence_ids=["MARGINS-2024"],
            require_operational_table=True,
            prior_version="PRIOR-V1",
        ).to_dict()
        self.assertEqual(result["algorithm"], "TEMFLOW_ERR_V1_1")
        self.assertEqual(len(result["coordinates"]), 4)
        self.assertEqual(len(result["dependency_witness"]), 4)
        self.assertIn("nonempty_witness", result["resolution_face"])
        self.assertIn("maximum_constraint_violation", result["solver_certificate"])
        self.assertEqual(result["operational_projection"]["status"], "computed")

    def test_json_adapter_preserves_latent_coordinate_and_optional_projection(self):
        payload = {
            "variable_names": ["certified-route", "latent-route"],
            "lower": [0, 0],
            "upper": [None, None],
            "A_eq": [[1, 1]],
            "b_eq": [10],
            "certified_mask": [True, False],
            "certificate_ids_by_coordinate": {"certified-route": ["CERT-1"]},
            "known_total": 10,
        }
        result = run_evidence_resolved_payload(payload)
        self.assertEqual(result["operational_projection"]["status"], "not_requested")
        self.assertEqual(result["coordinates"][1]["neutral_interval"], [0.0, 10.0])
        self.assertEqual(result["coordinates"][1]["named_report_status"], "blocked_unresolved_identity")

    def test_coordinate_width_monotonicity_is_not_asserted(self):
        result = self.run_err([True, False, False, True]).to_dict()
        self.assertIn("need not be monotone", result["caution"])


if __name__ == "__main__":
    unittest.main()
