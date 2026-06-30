# -*- coding: utf-8 -*-
"""Tests for strict risk-first lexicographic bilevel TEAVAR."""
from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path

try:
    from gurobipy import GRB

    HAS_GUROBI = True
except ImportError:
    HAS_GUROBI = False

ROOT = Path(__file__).resolve().parents[1]

from bilevel_teavar_models import (
    DEFAULT_LEX_PRIORITY,
    apply_lex_stages,
    evaluate_placement_lex,
    solve_bilevel_lexicographic,
    solve_fast_routing,
)
from toy_instances import CR_A, CR_B, CR_C, build_toy_combined_component_risk


def _cr_flow_data():
    data = build_toy_combined_component_risk(bandwidth_mode="flow")
    data.placement_node_labels = {"A": CR_A, "B": CR_B, "C": CR_C}
    return data


@unittest.skipUnless(HAS_GUROBI, "Gurobi required")
class TestBilevelLexicographic(unittest.TestCase):
    def test_component_risk_flow_config(self):
        data = _cr_flow_data()
        self.assertEqual(len(data.S), 512)
        self.assertAlmostEqual(sum(float(data.prob[s]) for s in data.S), 1.0, places=9)
        self.assertFalse(data.bandwidth_cost_on_placement)
        self.assertEqual(getattr(data, "bandwidth_mode"), "flow")

    def test_fast_lex_sla_delivery_cost(self):
        data = _cr_flow_data()
        placement = {i: CR_C for i in data.I}
        fast = solve_fast_routing(data, placement, fast_objective="lex_sla_delivery_cost")
        self.assertIsNotNone(fast)
        assert fast is not None
        self.assertEqual(fast.status, "OPTIMAL")
        self.assertEqual(len(fast.stage_statuses), 3)
        self.assertTrue(all(s == "OPTIMAL" for s in fast.stage_statuses))
        self.assertGreater(fast.expected_delivery, 0.0)
        self.assertGreater(fast.x_sum, 0.0)
        self.assertGreater(fast.bandwidth_cost, 0.0)
        self.assertIsNotNone(fast.cvar_sla)

    def test_sf_independence_across_fast_objectives(self):
        data = _cr_flow_data()
        placement = {0: CR_A, 1: CR_B, 2: CR_C}
        ev_lex = evaluate_placement_lex(data, placement, fast_objective="lex_sla_delivery_cost")
        ev_min = evaluate_placement_lex(data, placement, fast_objective="min_sla_cvar")
        self.assertIsNotNone(ev_lex)
        self.assertIsNotNone(ev_min)
        assert ev_lex is not None and ev_min is not None
        self.assertAlmostEqual(ev_lex.r_sf, ev_min.r_sf, places=9)

    def test_lex_stage_correctness(self):
        data = _cr_flow_data()
        result = solve_bilevel_lexicographic(data)
        self.assertEqual(result.status, "OPTIMAL")
        self.assertIsNotNone(result.best)
        assert result.best is not None
        best = result.best

        min_sf = min(r.r_sf for r in result.all_rows)
        self.assertLessEqual(best.r_sf, min_sf + 1e-9)

        y1 = [r for r in result.all_rows if r.in_Y1]
        self.assertTrue(all(r.r_sf <= min_sf + 1e-9 for r in y1))
        min_sla_y1 = min(r.r_sla for r in y1)
        self.assertLessEqual(best.r_sla, min_sla_y1 + 1e-9)

        y2 = [r for r in result.all_rows if r.in_Y2]
        self.assertTrue(set(r.placement_code for r in y2).issubset(
            set(r.placement_code for r in y1)
        ))
        min_cost_y2 = min(r.cost_total for r in y2)
        self.assertLessEqual(best.cost_total, min_cost_y2 + 1e-9)

        self.assertTrue(best.in_Y2)
        self.assertTrue(best.is_best)

    def test_apply_lex_stages_stars(self):
        data = _cr_flow_data()
        rows = []
        for placement in ({0: CR_A, 1: CR_A, 2: CR_A}, {0: CR_C, 1: CR_C, 2: CR_C}):
            ev = evaluate_placement_lex(data, placement)
            if ev is not None:
                rows.append(ev)
        self.assertGreaterEqual(len(rows), 2)
        stars, _, best_rows, y1, y2 = apply_lex_stages(rows, priority=DEFAULT_LEX_PRIORITY)
        self.assertIn("SF", stars)
        self.assertIn("SLA", stars)
        self.assertIn("Cost", stars)
        self.assertGreater(len(best_rows), 0)
        self.assertGreater(len(y1), 0)

    def test_smoke_script_runs(self):
        script = ROOT / "scripts" / "run_bilevel_lex_smoke.py"
        out_csv = ROOT / "results" / "temp_lex_smoke" / "bilevel_lex_cr_flow.csv"
        proc = subprocess.run(
            [
                sys.executable,
                str(script),
                "--output",
                str(out_csv),
                "--config-json",
                str(out_csv.with_suffix(".json")),
            ],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=600,
        )
        self.assertEqual(proc.returncode, 0, msg=proc.stderr or proc.stdout)
        self.assertTrue(out_csv.is_file())
        header = out_csv.read_text(encoding="utf-8").splitlines()[0]
        for col in (
            "placement_code",
            "cost_deploy",
            "cost_bw",
            "cost_total",
            "r_sla",
            "r_sf",
            "e_del",
            "x_sum",
            "in_Y1",
            "in_Y2",
            "is_best",
        ):
            self.assertIn(col, header)


if __name__ == "__main__":
    unittest.main()
