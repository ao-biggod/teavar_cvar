# -*- coding: utf-8 -*-
"""UMCF per-task：虚拟锚点、valid_assign、Model A 构建。"""

from __future__ import annotations

import unittest

from gurobipy import GRB


class UmcfPerTaskTests(unittest.TestCase):
    def test_umcf_per_task_anchors_are_distinct(self):
        from b4_joint_data import load_joint_data
        from duibi_metrics import teavar_flow_anchors

        n_tasks = 8
        data = load_joint_data(
            topology_name="B4",
            num_tasks=n_tasks,
            demand_scale=1.0,
            k_paths=2,
            routing_mode="umcf_per_task",
        )
        self.assertEqual(data.routing_mode, "umcf_per_task")
        self.assertTrue(getattr(data, "umcf_per_task_nodes", False))

        pairs = [teavar_flow_anchors(data, i) for i in data.I]
        self.assertEqual(len(pairs), n_tasks)
        self.assertEqual(len(set(pairs)), n_tasks, "each task must have distinct (V_s, V_t)")

        src_ids = [data.umcf_task_src[i] for i in data.I]
        dst_ids = [data.umcf_task_dst[i] for i in data.I]
        self.assertEqual(len(set(src_ids)), n_tasks)
        self.assertEqual(len(set(dst_ids)), n_tasks)
        for i in data.I:
            self.assertNotEqual(data.umcf_task_src[i], data.umcf_task_dst[i])

    def test_umcf_per_task_valid_assign_uses_task_virtual_anchors(self):
        from b4_joint_data import _paths_reachable, load_joint_data

        data = load_joint_data(
            topology_name="B4",
            num_tasks=4,
            k_paths=2,
            routing_mode="umcf_per_task",
        )
        for (i, m) in data.valid_assign:
            vs = data.umcf_task_src[i]
            vt = data.umcf_task_dst[i]
            self.assertTrue(_paths_reachable(data.P_cand, vs, m))
            self.assertTrue(_paths_reachable(data.P_cand, m, vt))

        # 无效 placement 不应出现
        for i in data.I:
            vs = data.umcf_task_src[i]
            vt = data.umcf_task_dst[i]
            for m in data.M:
                ok = _paths_reachable(data.P_cand, vs, m) and _paths_reachable(
                    data.P_cand, m, vt
                )
                if ok:
                    self.assertIn((i, m), data.valid_assign)
                else:
                    self.assertNotIn((i, m), data.valid_assign)

    def test_umcf_global_still_single_pair(self):
        from b4_joint_data import load_joint_data
        from duibi_metrics import teavar_flow_anchors

        data = load_joint_data(
            topology_name="B4",
            num_tasks=4,
            demand_scale=1.0,
            k_paths=2,
            routing_mode="umcf_global",
        )
        self.assertEqual(data.routing_mode, "umcf_global")
        g = teavar_flow_anchors(data)
        for i in data.I:
            self.assertEqual(teavar_flow_anchors(data, i), g)
        self.assertIsNotNone(data.umcf_vs)
        self.assertIsNotNone(data.umcf_vt)

    def test_umcf_per_task_model_a_builds(self):
        from b4_joint_data import load_joint_data
        from cvar_compare import build_teavar_sla_cvar_model

        data = load_joint_data(
            topology_name="B4",
            num_tasks=4,
            demand_scale=1.0,
            k_paths=2,
            routing_mode="umcf_per_task",
        )
        m, cost, lva, *_rest = build_teavar_sla_cvar_model(
            data,
            lambda_cvar=5.0,
            omega_deliver=1.0,
            lambda_compute_sf_cvar=1.0,
            time_limit=30,
            mip_gap=0.05,
        )
        self.assertIn(m.status, (GRB.OPTIMAL, GRB.TIME_LIMIT, GRB.SUBOPTIMAL))
        self.assertGreater(m.NumVars, 0)

    def test_hub_and_per_task_od_still_pass(self):
        import tests.test_per_task_od as tpo
        import tests.test_smoke as ts

        ts_suite = unittest.defaultTestLoader.loadTestsFromModule(ts)
        tpo_suite = unittest.defaultTestLoader.loadTestsFromModule(tpo)
        combined = unittest.TestSuite([ts_suite, tpo_suite])
        result = unittest.TextTestRunner(verbosity=0).run(combined)
        self.assertTrue(result.wasSuccessful(), f"regressions: {result.failures + result.errors}")

    def test_physical_task_src_preserved(self):
        from b4_joint_data import load_joint_data

        data = load_joint_data(
            topology_name="B4",
            num_tasks=4,
            routing_mode="umcf_per_task",
            demand_scale=1.0,
            k_paths=2,
        )
        for i in data.I:
            self.assertIn(i, data.physical_task_src)
            self.assertIn(i, data.physical_task_dst)
            self.assertNotEqual(data.physical_task_src[i], data.physical_task_dst[i])
            # 流锚点为虚拟节点，与物理 OD 不同
            self.assertEqual(data.umcf_task_src[i], len(data.M) + i)


if __name__ == "__main__":
    unittest.main()
