# -*- coding: utf-8 -*-
"""Entrypoint tests for scripts/run_pricing_ablation_smoke.py (P1-PRICING Phase 3)."""
from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path

try:
    from gurobipy import GRB

    HAS_GUROBI = True
except ImportError:
    HAS_GUROBI = False


class PricingAblationSmokeTests(unittest.TestCase):
    def test_default_output_not_p0(self):
        from scripts.run_pricing_ablation_smoke import DEFAULT_OUTPUT

        self.assertNotIn("p0_", Path(DEFAULT_OUTPUT).name.lower())
        self.assertEqual(Path(DEFAULT_OUTPUT).name, "pricing_ablation_b4.csv")

    def test_write_csv_refuses_p0_path(self):
        from scripts.run_pricing_ablation_smoke import write_csv

        with self.assertRaises(ValueError):
            write_csv("results/p0_gamma_frontier_b4.csv", [])

    def test_fieldnames_cover_required_metrics(self):
        from scripts.run_pricing_ablation_smoke import FIELDNAMES

        required = {
            "pricing_profile",
            "cost_p",
            "cost_b",
            "bandwidth_share",
            "avg_path_price",
            "objective",
            "cvar_sla",
            "cvar_sf",
            "placements",
        }
        self.assertTrue(required.issubset(set(FIELDNAMES)))

    @unittest.skipUnless(HAS_GUROBI, "Gurobi not available")
    def test_ablation_two_profiles_optimal(self):
        from scripts.run_pricing_ablation_smoke import run_ablation, write_csv

        rows = run_ablation(num_tasks=8, k_paths=4, eta=1.3, time_limit=120.0)
        self.assertEqual(len(rows), 2)
        profiles = {r["pricing_profile"] for r in rows}
        self.assertEqual(profiles, {"legacy", "copo_v1"})

        for r in rows:
            self.assertEqual(r["solver_status"], "OPTIMAL")
            self.assertEqual(r["scenario_mode"], "macro3")
            self.assertEqual(r["num_tasks"], 8)
            self.assertIsNotNone(r["cost_p"])
            self.assertIsNotNone(r["cost_b"])
            self.assertIsNotNone(r["bandwidth_share"])
            self.assertIsNotNone(r["avg_path_price"])
            self.assertIsNotNone(r["objective"])
            self.assertIsNotNone(r["cvar_sla"])
            self.assertIsNotNone(r["cvar_sf"])
            self.assertTrue(r["placements"])

        legacy = next(r for r in rows if r["pricing_profile"] == "legacy")
        copo = next(r for r in rows if r["pricing_profile"] == "copo_v1")
        self.assertAlmostEqual(float(legacy["bandwidth_price_scale"]), 1.0)
        self.assertAlmostEqual(float(copo["bandwidth_price_scale"]), 0.0030563617503325887, places=6)
        self.assertGreater(float(copo["bandwidth_share"]), float(legacy["bandwidth_share"]))

        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "pricing_ablation_b4.csv"
            write_csv(str(out), rows)
            self.assertTrue(out.is_file())
            with open(out, newline="", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                self.assertEqual(len(list(reader)), 2)


if __name__ == "__main__":
    unittest.main()
