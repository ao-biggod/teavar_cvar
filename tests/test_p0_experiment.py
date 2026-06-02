# -*- coding: utf-8 -*-
"""P0 实验装置：部分 σ、η 标定、p0_acceptance 逻辑（无完整 Gurobi 网格）。"""

from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path


class P0ExperimentTests(unittest.TestCase):
    def test_partial_sigma_applied(self):
        from b4_joint_data import load_joint_data

        data = load_joint_data(
            topology_name="B4",
            num_tasks=4,
            routing_mode="per_task_od",
            scenario_s1_link_sigma=0.80,
            scenario_s1_link_k=4,
            stress_zero_s1=False,
            k_paths=2,
        )
        self.assertEqual(getattr(data, "scenario_s1_mode"), "partial_sigma")
        self.assertAlmostEqual(float(data.scenario_s1_link_sigma), 0.80)
        stressed = getattr(data, "scenario_s1_stressed_edges", [])
        self.assertTrue(len(stressed) > 0)
        for e in stressed:
            self.assertAlmostEqual(float(data.sigma[e][1]), 0.80)
            self.assertNotAlmostEqual(float(data.sigma[e][1]), 0.0)
            self.assertNotAlmostEqual(float(data.sigma[e][1]), 1.0)

    def test_hub_stress_still_hard_break(self):
        from b4_joint_data import load_joint_data

        data = load_joint_data(
            topology_name="B4",
            num_tasks=4,
            routing_mode="hub",
            stress_zero_s1=True,
            scenario_s1_link_k=4,
            k_paths=2,
        )
        self.assertEqual(getattr(data, "scenario_s1_mode"), "hub_hard_stress")
        for e in getattr(data, "scenario_s1_stressed_edges", []):
            self.assertAlmostEqual(float(data.sigma[e][1]), 0.0)

    def test_eta_calibration_changes_demand(self):
        from b4_joint_data import load_joint_data
        from p0_calibration import _total_task_demand

        base = load_joint_data(
            topology_name="B4",
            num_tasks=4,
            routing_mode="per_task_od",
            demand_scale=1.0,
            k_paths=2,
            scenario_s1_link_sigma=0.80,
        )
        t0 = _total_task_demand(base)

        scaled = load_joint_data(
            topology_name="B4",
            num_tasks=4,
            routing_mode="per_task_od",
            demand_scale=1.0,
            eta=1.3,
            k_paths=2,
            scenario_s1_link_sigma=0.80,
        )
        t1 = _total_task_demand(scaled)
        self.assertTrue(scaled.p0_calibration.get("used_eta_calibration"))
        self.assertNotAlmostEqual(t0, t1, places=3)

        explicit = load_joint_data(
            topology_name="B4",
            num_tasks=4,
            routing_mode="per_task_od",
            demand_scale=10.0,
            demand_scale_explicit=True,
            k_paths=2,
        )
        self.assertFalse(explicit.p0_calibration.get("used_eta_calibration", False))

    def test_p0_acceptance_on_synthetic_csv(self):
        from scripts.p0_acceptance import run_acceptance

        rows = [
            {"gamma_sla": 0.1, "gamma_sf": 0.05, "status": "OPTIMAL", "cost": 100, "cvar_sla": 0.12, "cvar_sf": 0.08},
            {"gamma_sla": 0.1, "gamma_sf": 0.15, "status": "OPTIMAL", "cost": 102, "cvar_sla": 0.20, "cvar_sf": 0.03},
            {"gamma_sla": 0.1, "gamma_sf": 0.25, "status": "OPTIMAL", "cost": 101, "cvar_sla": 0.08, "cvar_sf": 0.06},
            {"gamma_sla": 0.2, "gamma_sf": 0.05, "status": "INFEASIBLE", "cost": "", "cvar_sla": "", "cvar_sf": ""},
        ]
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "syn.csv"
            with path.open("w", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(
                    f,
                    fieldnames=["gamma_sla", "gamma_sf", "status", "cost", "cvar_sla", "cvar_sf"],
                )
                w.writeheader()
                w.writerows(rows)
            rc = run_acceptance(path, cost_band_pct=5.0, min_distinct_points=3)
            self.assertEqual(rc, 0)

        fail_rows = [
            {"gamma_sla": 0.1, "gamma_sf": 0.0, "status": "OPTIMAL", "cost": 100, "cvar_sla": 0.0, "cvar_sf": 0.0},
            {"gamma_sla": 0.1, "gamma_sf": 0.0, "status": "OPTIMAL", "cost": 100, "cvar_sla": 0.0, "cvar_sf": 0.0},
        ]
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "bad.csv"
            with path.open("w", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(
                    f,
                    fieldnames=["gamma_sla", "gamma_sf", "status", "cost", "cvar_sla", "cvar_sf"],
                )
                w.writeheader()
                w.writerows(fail_rows)
            rc = run_acceptance(path)
            self.assertEqual(rc, 1)


if __name__ == "__main__":
    unittest.main()
