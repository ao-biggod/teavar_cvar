# -*- coding: utf-8 -*-
"""Unit tests for scenario_generator.build_link_scenarios (micro_pruned Phase 1)."""
from __future__ import annotations

import unittest

from scenario_generator import build_link_scenarios, combine_link_compute_scenarios


class ScenarioGeneratorTests(unittest.TestCase):
    def _three_edge_pf(self) -> tuple[list[tuple[int, int]], dict[tuple[int, int], float]]:
        edges = [(0, 1), (1, 2), (2, 0)]
        pf = {(0, 1): 0.01, (1, 2): 0.02, (2, 0): 0.03}
        return edges, pf

    def test_probabilities_sum_to_one_after_renorm(self):
        edges, pf = self._three_edge_pf()
        result = build_link_scenarios(
            edges, pf, k_max=2, pi_min=0.0, renormalize=True
        )
        self.assertAlmostEqual(result.audit.probability_sum_after_renorm, 1.0, places=9)
        self.assertTrue(result.audit.renormalized)

    def test_pi_min_pruning_reduces_or_keeps_count(self):
        edges, pf = self._three_edge_pf()
        loose = build_link_scenarios(edges, pf, k_max=2, pi_min=0.0, renormalize=False)
        tight = build_link_scenarios(edges, pf, k_max=2, pi_min=0.5, renormalize=False)
        self.assertGreaterEqual(loose.audit.num_kept, tight.audit.num_kept)
        self.assertGreater(tight.audit.mass_pruned_pi_lt_pi_min, 0.0)

    def test_kmax_tail_mass_reported(self):
        edges, pf = self._three_edge_pf()
        result = build_link_scenarios(edges, pf, k_max=1, pi_min=0.0, renormalize=False)
        self.assertGreater(result.audit.mass_tail_k_gt_kmax, 0.0)
        # 3 edges, k_max=1: enumerated = 1 + 3 = 4; tail = triple failure mass
        self.assertEqual(result.audit.num_raw_enumerated, 4)

    def test_edge_coverage_for_single_failures(self):
        edges, pf = self._three_edge_pf()
        result = build_link_scenarios(edges, pf, k_max=2, pi_min=0.0, renormalize=False)
        self.assertTrue(all(result.audit.edge_coverage.values()))

    def test_binary_sigma(self):
        edges, pf = self._three_edge_pf()
        result = build_link_scenarios(edges, pf, k_max=2, pi_min=0.0, renormalize=False)
        for sc in result.scenarios:
            for val in sc.sigma.values():
                self.assertIn(val, (0, 1))

    def test_missing_pf_raises_without_fallback(self):
        edges = [(0, 1), (1, 2)]
        pf = {(0, 1): 0.01}
        with self.assertRaises(ValueError):
            build_link_scenarios(edges, pf, k_max=1)

    def test_combine_link_compute_default_guard(self):
        edges, pf = self._three_edge_pf()
        link = build_link_scenarios(edges, pf, k_max=2, pi_min=0.0, renormalize=True)
        combined = combine_link_compute_scenarios(
            link,
            [("nominal", 0.9), ("s2_derate", 0.1)],
            pi_min=0.0,
            renormalize=True,
            max_scenarios_guard=100,
        )
        self.assertEqual(combined.audit.num_after_cross_product, link.audit.num_kept * 2)
        self.assertAlmostEqual(combined.audit.probability_sum_after_renorm, 1.0, places=9)


if __name__ == "__main__":
    unittest.main()
