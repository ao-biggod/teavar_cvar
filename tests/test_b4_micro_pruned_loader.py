# -*- coding: utf-8 -*-
"""B4 loader integration for scenario_mode=micro_pruned (Phase 2)."""
from __future__ import annotations

import unittest


class B4MicroPrunedLoaderTests(unittest.TestCase):
    def test_default_scenario_mode_is_macro3(self):
        from b4_joint_data import load_b4_joint_data

        data = load_b4_joint_data(
            topology_name="B4",
            num_tasks=4,
            routing_mode="per_task_od",
            k_paths=2,
        )
        self.assertEqual(getattr(data, "scenario_mode", "macro3"), "macro3")
        self.assertEqual(data.S, [0, 1, 2])
        self.assertAlmostEqual(data.prob[0], 0.6)
        self.assertAlmostEqual(data.prob[1], 0.3)
        self.assertAlmostEqual(data.prob[2], 0.1)
        self.assertEqual(getattr(data, "scenario_s1_mode"), "partial_sigma")
        self.assertTrue(len(getattr(data, "scenario_s1_stressed_edges", [])) > 0)
        for e in data.E:
            self.assertIn(0, data.sigma[e])
            self.assertIn(1, data.sigma[e])
            self.assertIn(2, data.sigma[e])

    def test_micro_pruned_loader_returns_71_scenarios(self):
        from b4_joint_data import load_b4_joint_data

        data = load_b4_joint_data(
            topology_name="B4",
            num_tasks=4,
            routing_mode="per_task_od",
            k_paths=2,
            scenario_mode="micro_pruned",
            micro_k_max=2,
            micro_pi_min=1e-5,
            micro_max_scenarios=100,
        )
        self.assertEqual(data.scenario_mode, "micro_pruned")
        self.assertEqual(len(data.S), 71)
        self.assertEqual(len(data.prob), 71)

    def test_micro_pruned_probability_sum_is_one(self):
        from b4_joint_data import load_b4_joint_data

        data = load_b4_joint_data(
            topology_name="B4",
            num_tasks=4,
            routing_mode="per_task_od",
            k_paths=2,
            scenario_mode="micro_pruned",
            micro_k_max=2,
            micro_pi_min=1e-5,
            micro_max_scenarios=100,
        )
        total = sum(float(data.prob[s]) for s in data.S)
        self.assertAlmostEqual(total, 1.0, places=9)

    def test_micro_pruned_schema_compatible_with_macro3(self):
        from b4_joint_data import load_b4_joint_data

        data = load_b4_joint_data(
            topology_name="B4",
            num_tasks=4,
            routing_mode="per_task_od",
            k_paths=2,
            scenario_mode="micro_pruned",
            micro_k_max=2,
            micro_pi_min=1e-5,
            micro_max_scenarios=100,
        )
        self.assertIsInstance(data.S, list)
        self.assertIsInstance(data.prob, dict)
        self.assertIsInstance(data.sigma, dict)
        self.assertIsInstance(data.C_s, dict)
        self.assertIsInstance(data.E, list)
        self.assertIsInstance(data.B, dict)
        for s in data.S:
            self.assertIn(s, data.prob)
            self.assertGreaterEqual(float(data.prob[s]), 0.0)
        for e in data.E:
            self.assertIn(e, data.sigma)
            for s in data.S:
                self.assertIn(s, data.sigma[e])
                val = float(data.sigma[e][s])
                self.assertIn(val, (0.0, 1.0))
        for m in data.M:
            for k in data.K:
                for s in data.S:
                    self.assertIn(s, data.C_s[m][k])
                    self.assertGreater(float(data.C_s[m][k][s]), 0.0)

    def test_micro_pruned_guard_not_triggered(self):
        from b4_joint_data import load_b4_joint_data

        data = load_b4_joint_data(
            topology_name="B4",
            num_tasks=4,
            routing_mode="per_task_od",
            k_paths=2,
            scenario_mode="micro_pruned",
            micro_k_max=2,
            micro_pi_min=1e-5,
            micro_max_scenarios=100,
        )
        self.assertEqual(len(data.S), 71)
        self.assertLessEqual(len(data.S), 100)
        self.assertFalse(getattr(data, "scenario_guard_failed", False))
        audit = getattr(data, "scenario_audit", None)
        self.assertIsNotNone(audit)
        self.assertEqual(audit.num_kept, 71)


if __name__ == "__main__":
    unittest.main()
