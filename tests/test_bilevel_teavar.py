# -*- coding: utf-8 -*-
"""Tests for bilevel_teavar_models (independent of single-layer edits)."""
from __future__ import annotations

import unittest

try:
    from gurobipy import GRB

    HAS_GUROBI = True
except ImportError:
    HAS_GUROBI = False

from bilevel_teavar_models import (
    compare_bilevel_c_with_single_layer_c,
    compare_with_single_layer_a,
    evaluate_placement,
    format_placement_code,
    solve_bilevel_model_a,
    solve_bilevel_model_c,
    solve_fast_routing,
)
from exact_enumeration_solver import assert_close, placements_match
from toy_instances import CR_A, CR_B, CR_C, build_toy_combined_component_risk


def _cr_data():
    data = build_toy_combined_component_risk()
    data.placement_node_labels = {"A": CR_A, "B": CR_B, "C": CR_C}
    return data


@unittest.skipUnless(HAS_GUROBI, "Gurobi required")
class TestBilevelTeavar(unittest.TestCase):
    def test_fast_routing_full_delivery(self):
        data = _cr_data()
        placement = {i: CR_A for i in data.I}
        fast = solve_fast_routing(data, placement, omega_deliver=1.0)
        self.assertIsNotNone(fast)
        assert fast is not None
        self.assertEqual(fast.status, "OPTIMAL")
        nominal = sum(float(data.b_in[i]) + float(data.b_out[i]) for i in data.I)
        self.assertGreater(fast.expected_delivery, 0.0)
        self.assertLessEqual(fast.expected_delivery, nominal + 1e-9)

    def test_fast_routing_lexicographic(self):
        data = _cr_data()
        placement = {i: CR_A for i in data.I}
        fast_del = solve_fast_routing(data, placement, fast_objective="delivery", omega_deliver=1.0)
        fast_lex = solve_fast_routing(data, placement, fast_objective="lexicographic")
        self.assertIsNotNone(fast_del)
        self.assertIsNotNone(fast_lex)
        assert fast_del is not None and fast_lex is not None
        self.assertEqual(fast_lex.status, "OPTIMAL")
        self.assertAlmostEqual(fast_lex.expected_delivery, fast_del.expected_delivery, places=4)

    def test_bilevel_c_matches_single_at_tight_gamma(self):
        data = _cr_data()
        rep = compare_bilevel_c_with_single_layer_c(
            data,
            gamma_sla=0.05,
            gamma_sf=0.05,
            omega_deliver=1.0,
            compare_single=True,
        )
        self.assertEqual(rep.bilevel_status, "OPTIMAL")
        self.assertEqual(rep.single_status, "OPTIMAL")
        self.assertTrue(rep.placement_match)

    def test_bilevel_model_a_high_lambda_sf_prefers_low_sf_risk(self):
        data = _cr_data()
        res = solve_bilevel_model_a(
            data,
            lambda_sla=0.0,
            lambda_sf=10.0,
            omega_deliver=1.0,
        )
        self.assertEqual(res.status, "OPTIMAL")
        self.assertIsNotNone(res.best)
        assert res.best is not None
        # BBB / CCC 类 SF 风险低于 AAA
        self.assertNotEqual(res.best.placement_code, "AAA")

    def test_bilevel_model_c_tight_gamma(self):
        data = _cr_data()
        res = solve_bilevel_model_c(
            data,
            gamma_sla=0.05,
            gamma_sf=0.05,
            omega_deliver=1.0,
        )
        self.assertEqual(res.status, "OPTIMAL")
        self.assertIsNotNone(res.best)
        assert res.best is not None
        self.assertLessEqual(res.best.cvar_sla, 0.05 + 1e-6)
        self.assertLessEqual(res.best.cvar_sf, 0.05 + 1e-6)

    def test_placement_code(self):
        data = _cr_data()
        code = format_placement_code(data, {0: CR_A, 1: CR_B, 2: CR_C})
        self.assertEqual(code, "ABC")

    def test_compare_with_single_layer(self):
        data = _cr_data()
        report = compare_with_single_layer_a(
            data,
            lambda_sla=1.0,
            lambda_sf=1.0,
            omega_deliver=1.0,
        )
        self.assertIsNotNone(report)
        assert report is not None
        self.assertIsNotNone(report.single_layer_placement_code)
        # 双层与单层在 component-risk toy 上通常一致（带宽绑 placement）
        self.assertTrue(report.placement_match or report.cost_gap is not None)

    def test_evaluate_known_placement_aaa(self):
        data = _cr_data()
        placement = {i: CR_A for i in data.I}
        ev = evaluate_placement(
            data,
            placement,
            omega_deliver=1.0,
            lambda_sla=0.0,
            lambda_sf=0.0,
        )
        self.assertIsNotNone(ev)
        assert ev is not None
        assert_close(ev.slow_cost, 0.12, tol=1e-4)
        self.assertEqual(ev.placement_code, "AAA")


if __name__ == "__main__":
    unittest.main()
