# -*- coding: utf-8 -*-
"""M0.5 / M1: fixed-y F1 primal-dual validation and L0 baseline parity."""
from __future__ import annotations

import unittest

try:
    from gurobipy import GRB

    HAS_GUROBI = True
except ImportError:
    HAS_GUROBI = False

from bilevel_teavar_models import solve_fast_routing
from l2_full_models import (
    F1_DUAL_EPS_DEFAULT,
    solve_f1_fixed_y,
    validate_f1_strong_duality,
)
from toy_instances import CR_A, CR_B, CR_C, build_toy_combined_component_risk


def _cr_flow_data():
    data = build_toy_combined_component_risk(bandwidth_mode="flow")
    data.placement_node_labels = {"A": CR_A, "B": CR_B, "C": CR_C}
    return data


@unittest.skipUnless(HAS_GUROBI, "Gurobi required")
class TestL2F1Dual(unittest.TestCase):
    def test_f1_matches_l0_min_sla_cvar(self):
        data = _cr_flow_data()
        placement = {0: CR_C, 1: CR_C, 2: CR_C}
        l2 = solve_f1_fixed_y(data, placement)
        l0 = solve_fast_routing(data, placement, fast_objective="min_sla_cvar")
        self.assertEqual(l2.status, "OPTIMAL")
        self.assertIsNotNone(l0)
        assert l0 is not None
        self.assertEqual(l0.status, "OPTIMAL")
        self.assertIsNotNone(l2.r_sla)
        self.assertIsNotNone(l0.model_sla_cvar)
        self.assertAlmostEqual(l2.r_sla, l0.model_sla_cvar, places=6)

    def test_f1_strong_duality_gap(self):
        data = _cr_flow_data()
        placement = {0: CR_A, 1: CR_B, 2: CR_C}
        result = validate_f1_strong_duality(data, placement, eps=F1_DUAL_EPS_DEFAULT)
        self.assertEqual(result.status, "OPTIMAL")
        self.assertIsNotNone(result.primal_objective)
        self.assertIsNotNone(result.dual_objective)
        self.assertIsNotNone(result.gap)
        self.assertTrue(result.gap_ok, msg=f"gap={result.gap}")
        self.assertTrue(result.l0_match, msg=f"l0={result.l0_r_sla}, l2={result.primal_objective}")

    def test_dual_sign_checks(self):
        data = _cr_flow_data()
        placement = {i: CR_C for i in data.I}
        result = validate_f1_strong_duality(data, placement)
        for key in ("cap_in_", "cap_out_", "ru_in_", "ru_out_"):
            self.assertIn(key, result.sign_checks)
            self.assertEqual(result.sign_checks[key], "ok", msg=f"{key} sign check failed")

    def test_multiple_placements(self):
        data = _cr_flow_data()
        placements = [
            {i: CR_A for i in data.I},
            {i: CR_B for i in data.I},
            {0: CR_A, 1: CR_B, 2: CR_C},
        ]
        for placement in placements:
            with self.subTest(placement=placement):
                result = validate_f1_strong_duality(data, placement, eps=1e-5)
                self.assertTrue(result.gap_ok)
                self.assertTrue(result.l0_match)


if __name__ == "__main__":
    unittest.main()
