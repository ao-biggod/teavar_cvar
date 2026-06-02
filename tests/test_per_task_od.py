# -*- coding: utf-8 -*-
"""per-task OD：数据层、流锚点、SLA Model A 最小闭环。"""

from __future__ import annotations

import unittest

from gurobipy import GRB


class PerTaskOdTests(unittest.TestCase):
    def test_hub_mode_still_loads(self):
        from b4_joint_data import load_joint_data
        from duibi_metrics import teavar_flow_anchors

        data = load_joint_data(
            topology_name="B4",
            num_tasks=4,
            demand_scale=1.0,
            k_paths=2,
            routing_mode="hub",
        )
        self.assertEqual(getattr(data, "routing_mode", "hub"), "hub")
        h = data.hub
        self.assertEqual(teavar_flow_anchors(data), (h, h))
        self.assertEqual(teavar_flow_anchors(data, 0), (h, h))
        self.assertTrue(len(data.valid_assign) > 0)

    def test_per_task_od_has_task_src_dst(self):
        from b4_joint_data import load_joint_data

        n_tasks = 4
        data = load_joint_data(
            topology_name="B4",
            num_tasks=n_tasks,
            demand_scale=1.0,
            k_paths=2,
            routing_mode="per_task_od",
        )
        self.assertEqual(data.routing_mode, "per_task_od")
        self.assertEqual(len(data.task_src), n_tasks)
        self.assertEqual(len(data.task_dst), n_tasks)
        for i in data.I:
            self.assertIn(i, data.task_src)
            self.assertIn(i, data.task_dst)
            self.assertNotEqual(data.task_src[i], data.task_dst[i])

    def test_valid_assign_requires_both_ingress_and_egress_paths(self):
        from b4_joint_data import _build_valid_assign_per_task_od, _paths_reachable, load_joint_data

        data = load_joint_data(
            topology_name="B4",
            num_tasks=4,
            k_paths=2,
            routing_mode="per_task_od",
        )
        for (i, m) in data.valid_assign:
            src = data.task_src[i]
            dst = data.task_dst[i]
            self.assertTrue(_paths_reachable(data.P_cand, src, m))
            self.assertTrue(_paths_reachable(data.P_cand, m, dst))

        # 合成 3 节点链 0→1→2：任务 0→2 只能放在 1，不能放在 0（无 egress 到 2）或 2（无 ingress 从 0）
        P_cand = {
            (0, 0): [[]],
            (1, 1): [[]],
            (2, 2): [[]],
            (0, 1): [[(0, 1)]],
            (1, 2): [[(1, 2)]],
            (0, 2): [[]],
            (1, 0): [[]],
            (2, 0): [[]],
            (2, 1): [[]],
        }
        task_src = {0: 0}
        task_dst = {0: 2}
        va = _build_valid_assign_per_task_od([0], [0, 1, 2], task_src, task_dst, P_cand)
        self.assertIn((0, 1), va)
        self.assertNotIn((0, 0), va)
        self.assertNotIn((0, 2), va)

    def test_per_task_od_sla_model_optimal(self):
        from b4_joint_data import load_joint_data
        from cvar_compare import build_teavar_sla_cvar_model

        data = load_joint_data(
            topology_name="B4",
            num_tasks=4,
            demand_scale=1.0,
            k_paths=2,
            routing_mode="per_task_od",
        )
        m, cost, lv, *_ = build_teavar_sla_cvar_model(
            data,
            lambda_cvar=5.0,
            omega_deliver=1.0,
            lambda_compute_sf_cvar=1.0,
        )
        self.assertEqual(m.status, GRB.OPTIMAL)
        self.assertIsNotNone(cost)
        self.assertGreaterEqual(lv, 0.0)

    def test_per_task_od_virtual_bottleneck_builds(self):
        from b4_joint_data import load_joint_data
        from cvar_compare import build_teavar_sla_cvar_model

        data = load_joint_data(
            topology_name="B4",
            num_tasks=4,
            demand_scale=1.0,
            k_paths=2,
            routing_mode="per_task_od",
            virtual_source=True,
            virtual_source_sigma=0.99,
        )
        self.assertIsNotNone(getattr(data, "sigma_vs", None))
        m, cost, lv, *_ = build_teavar_sla_cvar_model(
            data,
            lambda_cvar=5.0,
            omega_deliver=1.0,
            lambda_compute_sf_cvar=0.0,
        )
        self.assertIn(m.status, (GRB.OPTIMAL, GRB.SUBOPTIMAL))
        self.assertIsNotNone(cost)
        self.assertGreaterEqual(lv, 0.0)

    def test_model_c_per_task_od_builds(self):
        from b4_joint_data import load_joint_data
        from teavar_framework_models import build_teavar_model_a, build_teavar_model_c

        data = load_joint_data(
            topology_name="B4",
            num_tasks=4,
            demand_scale=1.0,
            k_paths=2,
            routing_mode="per_task_od",
        )
        ma, ca, lva, sva, *_ = build_teavar_model_a(
            data, lambda_sla=10.0, lambda_sf=1.0, omega_deliver=1.0
        )
        self.assertEqual(ma.status, GRB.OPTIMAL)
        g_sla = max(float(lva) * 1.5, 1e-9)
        g_sf = max(float(sva) * 2.0 + 0.01, 1e-9) if sva and sva > 1e-12 else None
        mc, cc, lvc, svc, *_ = build_teavar_model_c(
            data,
            gamma_sla=g_sla,
            gamma_sf=g_sf,
            omega_deliver=1.0,
            include_sf_budget=g_sf is not None,
        )
        self.assertEqual(mc.status, GRB.OPTIMAL)
        self.assertIsNotNone(cc)
        self.assertLessEqual(lvc, g_sla + 1e-6)

    def test_model_c_hub_still_builds(self):
        from b4_joint_data import load_joint_data
        from teavar_framework_models import build_teavar_model_a, build_teavar_model_c

        data = load_joint_data(
            topology_name="B4",
            num_tasks=4,
            demand_scale=1.0,
            k_paths=2,
            routing_mode="hub",
        )
        ma, ca, lva, sva, *_ = build_teavar_model_a(
            data, lambda_sla=10.0, lambda_sf=1.0, omega_deliver=1.0
        )
        self.assertEqual(ma.status, GRB.OPTIMAL)
        g_sla = max(float(lva) * 1.5, 1e-9)
        g_sf = max(float(sva) * 2.0 + 0.01, 1e-9) if sva and sva > 1e-12 else None
        mc, cc, lvc, svc, *_ = build_teavar_model_c(
            data,
            gamma_sla=g_sla,
            gamma_sf=g_sf,
            omega_deliver=1.0,
            include_sf_budget=g_sf is not None,
        )
        self.assertEqual(mc.status, GRB.OPTIMAL)
        self.assertIsNotNone(cc)
        self.assertLessEqual(lvc, g_sla + 1e-6)


if __name__ == "__main__":
    unittest.main()
