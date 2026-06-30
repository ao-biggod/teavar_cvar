# -*- coding: utf-8 -*-
"""CLI / entrypoint tests for scenario_mode=micro_pruned (Phase 3)."""
from __future__ import annotations

import argparse
import unittest
from pathlib import Path

try:
    from gurobipy import GRB

    HAS_GUROBI = True
except ImportError:
    HAS_GUROBI = False


class MicroPrunedEntrypointTests(unittest.TestCase):
    def test_default_scenario_mode_is_macro3(self):
        from b4_joint_data import load_joint_data
        import main as main_mod

        data = load_joint_data(
            topology_name="B4",
            num_tasks=4,
            routing_mode="per_task_od",
            k_paths=2,
        )
        self.assertEqual(getattr(data, "scenario_mode", "macro3"), "macro3")
        self.assertEqual(len(data.S), 3)

        parser = argparse.ArgumentParser()
        parser.add_argument("--scenario-mode", default="macro3")
        parser.add_argument("--micro-k-max", type=int, default=2)
        parser.add_argument("--micro-pi-min", type=float, default=1e-5)
        parser.add_argument("--micro-max-scenarios", type=int, default=100)
        args = parser.parse_args([])
        kw = main_mod._scenario_kwargs_from_args(args)
        self.assertEqual(kw["scenario_mode"], "macro3")

    def test_explicit_micro_pruned_loads_71_scenarios(self):
        from b4_joint_data import load_joint_data

        data = load_joint_data(
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

    def test_micro_pruned_probability_sum_is_one(self):
        from b4_joint_data import load_joint_data

        data = load_joint_data(
            topology_name="B4",
            num_tasks=4,
            routing_mode="per_task_od",
            scenario_mode="micro_pruned",
            micro_k_max=2,
            micro_pi_min=1e-5,
        )
        total = sum(float(data.prob[s]) for s in data.S)
        self.assertAlmostEqual(total, 1.0, places=4)

    def test_micro_pruned_does_not_change_p0_outputs(self):
        from run_gamma_frontier import resolve_frontier_output_path, resolve_diag_output_path

        args = argparse.Namespace(
            scenario_mode="micro_pruned",
            topology="B4",
            num_tasks=8,
            grid_size=5,
            output="results/p0_gamma_frontier_b4_tasks8_grid5.csv",
            diag_output="results/p0_feasibility_diag.csv",
        )
        out = resolve_frontier_output_path(args)
        diag = resolve_diag_output_path(args)
        self.assertNotIn("p0_", out.name)
        self.assertIn("p1_fault_micro_pruned", out.name)
        self.assertNotIn("p0_", diag.name)
        self.assertIn("p1_fault_micro_pruned", diag.name)

        args_macro = argparse.Namespace(
            scenario_mode="macro3",
            topology="B4",
            num_tasks=8,
            grid_size=5,
            output="results/p0_gamma_frontier_b4_tasks8_grid5.csv",
            diag_output="results/p0_feasibility_diag.csv",
        )
        self.assertEqual(
            resolve_frontier_output_path(args_macro),
            Path("results/p0_gamma_frontier_b4_tasks8_grid5.csv"),
        )

    @unittest.skipUnless(HAS_GUROBI, "Gurobi not available")
    def test_micro_pruned_small_model_builds(self):
        from b4_joint_data import load_joint_data
        from teavar_framework_models import build_teavar_model_c

        data = load_joint_data(
            topology_name="B4",
            num_tasks=4,
            routing_mode="per_task_od",
            k_paths=2,
            scenario_mode="micro_pruned",
            micro_k_max=2,
            micro_pi_min=1e-5,
            micro_max_scenarios=100,
        )
        self.assertFalse(getattr(data, "scenario_guard_failed", False))
        m, *_ = build_teavar_model_c(
            data,
            gamma_sla=1.0,
            gamma_sf=1.0,
            omega_deliver=0.0,
            include_sf_budget=True,
        )
        self.assertGreater(m.NumVars, 0)
        self.assertGreater(m.NumConstrs, 0)


if __name__ == "__main__":
    unittest.main()
