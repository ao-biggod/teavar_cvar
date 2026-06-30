# -*- coding: utf-8 -*-
"""sf CVaR per-resource normalization: D_ref[k] instead of scalar D_ref."""

from __future__ import annotations

import unittest

from gurobipy import GRB


class SfNormalizationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from b4_joint_data import load_joint_data

        cls.data = load_joint_data(
            topology_name="B4",
            num_tasks=8,
            demand_scale=1.0,
            k_paths=2,
            routing_mode="per_task_od",
        )

    def test_sf_d_ref_is_per_resource(self):
        from cvar_compare import compute_sf_resource_refs

        refs = compute_sf_resource_refs(self.data)
        self.assertIsInstance(refs, dict)
        for k in self.data.K:
            self.assertIn(k, refs, f"missing ref for resource dimension {k}")
            self.assertGreaterEqual(refs[k], 1.0, f"ref[{k}] should be >= 1.0")

        # per-dimension sums
        for k in self.data.K:
            expected = max(float(sum(self.data.w[i][k] for i in self.data.I)), 1.0)
            self.assertAlmostEqual(refs[k], expected, places=5,
                                   msg=f"D_ref[{k}]={refs[k]} != expected {expected}")

    def test_model_a_builds_with_per_resource_sf_ref(self):
        from cvar_compare import build_teavar_sla_cvar_model

        m, cost, lv, nv, sfv, *_ = build_teavar_sla_cvar_model(
            self.data, lambda_cvar=5.0, lambda_compute_sf_cvar=1.0,
            omega_deliver=1.0, time_limit=30,
        )
        self.assertEqual(m.status, GRB.OPTIMAL)
        self.assertIsNotNone(cost)
        self.assertIsNotNone(sfv)

    def test_model_c_builds_with_per_resource_sf_ref(self):
        from cvar_compare import build_teavar_sla_cvar_model
        from teavar_framework_models import build_teavar_model_c

        ma, ca, lva, sva, *_ = build_teavar_sla_cvar_model(
            self.data, lambda_cvar=10.0, lambda_compute_sf_cvar=1.0, omega_deliver=1.0,
        )
        self.assertEqual(ma.status, GRB.OPTIMAL)
        g_sla = max(float(lva) * 1.5, 1e-9)
        g_sf = max(float(sva) * 2.0 + 0.01, 1e-9) if sva and sva > 1e-12 else None
        mc, cc, lvc, svc, *_ = build_teavar_model_c(
            self.data, gamma_sla=g_sla, gamma_sf=g_sf,
            omega_deliver=1.0, include_sf_budget=g_sf is not None,
        )
        self.assertEqual(mc.status, GRB.OPTIMAL)
        self.assertIsNotNone(cc)


if __name__ == "__main__":
    unittest.main()
