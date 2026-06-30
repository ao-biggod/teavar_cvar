# -*- coding: utf-8 -*-
"""Tests for M2-C-Cost Adaptive model builder."""
from __future__ import annotations

import sys, os
_srcdir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _srcdir not in sys.path:
    sys.path.insert(0, _srcdir)

import unittest
import math

from toy_two_task_independent_data import (
    build_toy_2task_independent_v1,
    TwoTaskIndependentData,
)
from refactor.m2_c_cost_models import (
    build_m2_c_cost_adaptive,
    solve_m2_c_cost_adaptive,
    M2CCostSolveResult,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def build_toy_aggregate() -> TwoTaskIndependentData:
    """Build Toy-2Task with aggregate_worst pruning (default)."""
    return build_toy_2task_independent_v1(
        scenario_mode="pruned",
        max_failed_components=2,
        renormalize_probabilities=False,
        prune_mode="aggregate_worst",
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestM2CCostBuild(unittest.TestCase):
    """Tests for M2-C-Cost Adaptive building and solving."""

    def test_m2_c_cost_builds_with_aggregate_worst(self):
        """Model builds and solves with aggregate_worst pruning."""
        data = build_toy_aggregate()
        model = build_m2_c_cost_adaptive(
            data,
            gamma=0.5,
            beta=0.8,
            quiet=True,
            service_floor={0: 0.85, 1: 0.85},
        )
        result = solve_m2_c_cost_adaptive(model)
        self.assertIn(result.status, (2, 3, 9),  # OPTIMAL, TIME_LIMIT, SUBOPTIMAL
                      f"Model failed to solve (status={result.status})")
        self.assertFalse(math.isnan(result.objective),
                         "Objective should not be NaN after solve")
        print(f"  status={result.status}, obj={result.objective:.4f}")

    def test_m2_c_cost_uses_aggregate_metadata(self):
        """Result metadata records pruning info from aggregate_worst."""
        data = build_toy_aggregate()
        model = build_m2_c_cost_adaptive(
            data, gamma=0.5, beta=0.8, quiet=True,
            service_floor={0: 0.85, 1: 0.85},
        )
        result = solve_m2_c_cost_adaptive(model)
        self.assertIn(result.status, (2, 3, 9))

        meta = result.metadata
        self.assertEqual(meta.get("prune_mode"), "aggregate_worst")
        self.assertTrue(meta.get("has_aggregate_worst"),
                        "has_aggregate_worst should be True")
        agg_prob = meta.get("aggregate_worst_probability", 0.0)
        self.assertGreater(agg_prob, 0.0,
                           f"aggregate_worst_probability={agg_prob} should be > 0")
        dropped = meta.get("dropped_probability_mass", 0.0)
        self.assertGreater(dropped, 0.0,
                           f"dropped_probability_mass={dropped} should be > 0")
        before = meta.get("scenario_count_before_pruning", 0)
        after = meta.get("scenario_count_after_pruning", 0)
        self.assertEqual(before, 277)
        self.assertEqual(after, 278)
        self.assertEqual(meta.get("loss_mode"), "mean")
        print(f"  prune_mode={meta['prune_mode']}, has_aggregate={meta['has_aggregate_worst']}, "
              f"agg_prob={agg_prob:.6f}, before={before}, after={after}")

    def test_no_active_under_service_in_nominal(self):
        """Normal scenario (s=0) has z[i,0] = 1 for all tasks."""
        data = build_toy_aggregate()
        model = build_m2_c_cost_adaptive(
            data, gamma=0.5, beta=0.8, quiet=True,
            service_floor={0: 0.85, 1: 0.85},
        )
        result = solve_m2_c_cost_adaptive(model)
        self.assertIn(result.status, (2, 3, 9))

        normal_s = data.S[0]
        for i in data.I:
            val = result.z.get((i, normal_s), 0.0)
            self.assertAlmostEqual(val, 1.0, places=6,
                                   msg=f"z[{i},{normal_s}]={val} != 1.0")
        print(f"  Nominal s={normal_s}: z[0]={result.z[(0, normal_s)]:.6f}, "
              f"z[1]={result.z[(1, normal_s)]:.6f}")

    def test_expected_service_floor_enforced(self):
        """With service_floor, each task's expected service meets the bound."""
        data = build_toy_aggregate()
        floor = {0: 0.85, 1: 0.85}
        model = build_m2_c_cost_adaptive(
            data, gamma=0.5, beta=0.8, quiet=True,
            service_floor=floor,
        )
        result = solve_m2_c_cost_adaptive(model)
        self.assertIn(result.status, (2, 3, 9))

        for i in data.I:
            exp_z = sum(data.prob[s] * result.z.get((i, s), 0.0) for s in data.S)
            self.assertGreaterEqual(exp_z + 1e-9, floor[i],
                                    f"E[z[{i}]]={exp_z:.6f} < floor={floor[i]}")
        print(f"  E[z[0]]={sum(data.prob[s]*result.z.get((0,s),0) for s in data.S):.6f}, "
              f"E[z[1]]={sum(data.prob[s]*result.z.get((1,s),0) for s in data.S):.6f}")

    def test_objective_contains_cost(self):
        """Objective includes both deployment and bandwidth cost (not max-service)."""
        data = build_toy_aggregate()
        model = build_m2_c_cost_adaptive(
            data, gamma=0.5, beta=0.8, quiet=True,
            service_floor={0: 0.85, 1: 0.85},
        )
        result = solve_m2_c_cost_adaptive(model)
        self.assertIn(result.status, (2, 3, 9))

        # Both cost components should be non-negative and finite
        self.assertGreaterEqual(result.deployment_cost, 0.0)
        self.assertGreaterEqual(result.bandwidth_cost, 0.0)
        self.assertFalse(math.isnan(result.deployment_cost))
        self.assertFalse(math.isnan(result.bandwidth_cost))

        # Objective should equal deployment + bandwidth cost
        self.assertAlmostEqual(result.objective,
                               result.deployment_cost + result.bandwidth_cost,
                               places=5,
                               msg="Objective != deploy_cost + bw_cost")
        print(f"  objective={result.objective:.4f}, "
              f"deploy={result.deployment_cost:.4f}, "
              f"bw={result.bandwidth_cost:.4f}")

    def test_adaptive_does_not_use_x0(self):
        """Adaptive model does not create nominal x0 variables."""
        data = build_toy_aggregate()
        model = build_m2_c_cost_adaptive(
            data, gamma=0.5, beta=0.8, quiet=True,
            service_floor={0: 0.85, 1: 0.85},
        )
        # Check no variable name contains 'x0' or 'x_nominal' (nominal vars)
        # Note: xin_s and xout_s are scenario variables, not nominal — they're fine
        found_nominal = []
        for v in model.getVars():
            name = v.VarName
            # x0 could appear inside names like "xin_s_...", so check for
            # standalone "x0" patterns or "x_nominal" explicitly
            parts = name.split("_")
            if "x0" in parts or "xnominal" in name.lower() or "x_nominal" in name.lower():
                found_nominal.append(name)
        self.assertEqual(len(found_nominal), 0,
                         f"Found nominal-like variables: {found_nominal}")
        print(f"  No x0/nominal variables found ({len(model.getVars())} vars)")


if __name__ == "__main__":
    unittest.main()
