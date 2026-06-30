# -*- coding: utf-8 -*-
"""M2 L2-light embedded-y tests."""
from __future__ import annotations

import unittest

try:
    from gurobipy import GRB

    HAS_GUROBI = True
except ImportError:
    HAS_GUROBI = False

from bilevel_teavar_models import solve_bilevel_lexicographic
from l2_full_models import (
    build_l2_light_embedded_y,
    embedded_y_variable_counts,
    solve_l2_light_lexicographic,
    summarize_dual_bounds,
)
from toy_instances import CR_A, CR_B, CR_C, build_toy_combined_component_risk


def _cr_flow_data():
    data = build_toy_combined_component_risk(bandwidth_mode="flow")
    data.placement_node_labels = {"A": CR_A, "B": CR_B, "C": CR_C}
    return data


@unittest.skipUnless(HAS_GUROBI, "Gurobi required")
class TestL2Light(unittest.TestCase):
    def test_build_embedded_y_full_space(self):
        data = _cr_flow_data()
        ctx = build_l2_light_embedded_y(data)
        counts = embedded_y_variable_counts(ctx, data)
        self.assertEqual(counts["y_pairs"], len(data.I) * len(data.M))
        self.assertEqual(counts["xin_keys"], len(data.I) * len(data.M))
        self.assertGreater(counts["del_in_keys"], counts["xin_keys"])
        self.assertEqual(counts["mccormick_pairs"], counts["xin_keys"] + counts["xout_keys"])

    def test_dual_bounds_finite(self):
        data = _cr_flow_data()
        ctx = build_l2_light_embedded_y(data)
        bounds = summarize_dual_bounds(ctx)
        for name, (lb, ub) in bounds.items():
            self.assertLess(lb, ub, msg=name)
            self.assertTrue(abs(lb) < float("inf") and abs(ub) < float("inf"), msg=name)

    def test_placement_matches_l0_on_toy(self):
        data = _cr_flow_data()
        l2 = solve_l2_light_lexicographic(data, time_limit=120)
        l0 = solve_bilevel_lexicographic(data)
        self.assertEqual(l2.status, "OPTIMAL")
        self.assertIsNotNone(l0.best)
        assert l0.best is not None
        self.assertEqual(l2.placement_code, l0.best.placement_code)
        self.assertAlmostEqual(l2.r_sla, l0.R_sla_star, places=6)

    def test_not_placement_pruned_xin(self):
        """Embedded-y must create xin on non-chosen nodes (unlike L0 fixed-y)."""
        data = _cr_flow_data()
        ctx = build_l2_light_embedded_y(data)
        nodes = set(data.M)
        for i in data.I:
            xin_nodes = {m for (ii, m, _p) in ctx.xin if ii == i}
            self.assertEqual(xin_nodes, nodes)


if __name__ == "__main__":
    unittest.main()
