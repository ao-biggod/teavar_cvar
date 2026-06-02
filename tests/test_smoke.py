# -*- coding: utf-8 -*-
"""轻量冒烟：数据加载、带宽费、Model A/C 可解性（需 Gurobi 许可证）。"""

from __future__ import annotations

import unittest

from gurobipy import GRB


class SmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from b4_joint_data import load_joint_data

        cls.data = load_joint_data(
            topology_name="B4",
            num_tasks=4,
            demand_scale=1.0,
            k_paths=2,
            stress_zero_s1=False,
        )

    def test_link_prices_and_bandwidth_tariff(self):
        from duibi_metrics import ensure_link_prices, path_bandwidth_tariff

        ensure_link_prices(self.data)
        self.assertTrue(len(self.data.link_price) > 0)
        p0 = path_bandwidth_tariff(self.data, 0, 1, 0)
        self.assertGreaterEqual(p0, 0.0)

    def test_teavar_sla_optimal_toy(self):
        from cvar_compare import build_teavar_sla_cvar_model

        m, cost, lv, *_ = build_teavar_sla_cvar_model(
            self.data,
            lambda_cvar=5.0,
            omega_deliver=1.0,
            lambda_compute_sf_cvar=1.0,
        )
        self.assertEqual(m.status, GRB.OPTIMAL)
        self.assertIsNotNone(cost)
        self.assertGreaterEqual(lv, 0.0)

    def test_model_c_from_a_calibration(self):
        from teavar_framework_models import build_teavar_model_a, build_teavar_model_c

        ma, ca, lva, sva, *_ = build_teavar_model_a(
            self.data, lambda_sla=10.0, lambda_sf=1.0, omega_deliver=1.0
        )
        self.assertEqual(ma.status, GRB.OPTIMAL)
        g_sla = max(float(lva) * 1.5, 1e-9)
        g_sf = max(float(sva) * 2.0 + 0.01, 1e-9) if sva and sva > 1e-12 else None
        mc, cc, lvc, svc, *_ = build_teavar_model_c(
            self.data,
            gamma_sla=g_sla,
            gamma_sf=g_sf,
            omega_deliver=1.0,
            include_sf_budget=g_sf is not None,
        )
        self.assertEqual(mc.status, GRB.OPTIMAL)
        self.assertIsNotNone(cc)
        self.assertLessEqual(lvc, g_sla + 1e-6)

    def test_topology_readiness_b4(self):
        from b4_joint_data import assess_topology_readiness

        r = assess_topology_readiness("B4", num_tasks=2)
        self.assertTrue(r["ready"], msg="; ".join(r["issues"]))


if __name__ == "__main__":
    unittest.main()
