# -*- coding: utf-8 -*-
"""链式 DAG MVP：模板、placement MILP、smoke。"""

from __future__ import annotations

import unittest

from gurobipy import GRB


class DagChainTests(unittest.TestCase):
    def _load_b4(self, num_tasks: int = 4):
        from b4_joint_data import load_joint_data

        return load_joint_data(
            topology_name="B4",
            num_tasks=num_tasks,
            k_paths=4,
            routing_mode="per_task_od",
            eta=1.3,
            demand_scale=1.0,
            demand_scale_explicit=False,
        )

    def test_chain_template_preserves_total_compute(self):
        from task_dag_templates import build_chain_task_dag, total_service_compute

        data = self._load_b4(4)
        build_chain_task_dag(data, chain_len=3)
        for i in data.I:
            spec = data.task_dag[i]
            for k in data.K:
                total = total_service_compute(spec, k)
                self.assertAlmostEqual(total, float(data.w[i][k]), places=5)

    def test_chain_template_has_expected_arcs(self):
        from task_dag_templates import build_chain_task_dag

        data = self._load_b4(2)
        build_chain_task_dag(data, chain_len=3)
        for i in data.I:
            self.assertEqual(data.task_dag[i]["services"], [0, 1, 2])
            self.assertEqual(data.task_dag[i]["arcs"], [(0, 1), (1, 2)])

    def test_chain_dag_model_builds_toy_or_b4_small(self):
        from dag_sla_model import build_chain_dag_placement_model
        from task_dag_templates import build_chain_task_dag

        data = self._load_b4(2)
        build_chain_task_dag(data, chain_len=3)
        model, variables, meta = build_chain_dag_placement_model(data, time_limit=60)
        self.assertFalse(meta["has_sla_cvar"])
        self.assertGreater(meta["num_y_vars"], 0)
        self.assertGreater(meta["num_z_vars"], 0)
        model.optimize()
        self.assertIn(
            model.Status,
            (GRB.OPTIMAL, GRB.TIME_LIMIT, GRB.SUBOPTIMAL),
        )
        self.assertGreater(len(variables["y"]), 0)

    def test_two_microservices_can_place_differently_if_cost_or_capacity_drives(self):
        from dag_sla_model import build_chain_dag_placement_model
        from task_dag_templates import build_chain_task_dag

        data = self._load_b4(2)
        build_chain_task_dag(data, chain_len=3)
        _, variables, meta = build_chain_dag_placement_model(data)
        y = variables["y"]
        # 同一 task 内不同 v 的 y 索引允许不同 m
        by_iv: dict[tuple[int, int], set[int]] = {}
        for (i, v, m) in y:
            by_iv.setdefault((i, v), set()).add(m)
        for i in data.I:
            for v in [0, 1, 2]:
                self.assertGreater(len(by_iv.get((i, v), set())), 1)
        # z 允许 u@ m, v@ n 且 m != n（若路径可达）
        has_distinct = any(mm != nn for (_, _, _, mm, nn) in variables["z"])
        self.assertTrue(has_distinct or meta["num_z_vars"] > 0)


if __name__ == "__main__":
    unittest.main()
