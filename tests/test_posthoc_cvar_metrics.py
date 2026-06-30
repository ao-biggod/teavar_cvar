# -*- coding: utf-8 -*-
"""Post-hoc CVaR metrics (P1-METRICS Phase 3.6)."""
from __future__ import annotations

import unittest

try:
    from gurobipy import GRB

    HAS_GUROBI = True
except ImportError:
    HAS_GUROBI = False


def _legacy_m_ex(data) -> float:
    if not data.I or not data.K:
        return 1.0
    d_max_any = max(
        float(sum(data.w[i][k] for i in data.I))
        for k in data.K
        for _ in data.M
    )
    if not data.M or not data.S:
        return max(d_max_any + 1.0, 1.0)
    cmax = max(
        float(data.C_s[node][k][s])
        for node in data.M
        for k in data.K
        for s in data.S
    )
    return max(d_max_any + 1.0, cmax + 1.0, 1.0)


class DiscreteCvarTests(unittest.TestCase):
    def test_discrete_cvar_uniform_probability(self):
        from metrics_posthoc import compute_discrete_cvar

        losses = {0: 0.0, 1: 1.0, 2: 2.0, 3: 3.0}
        prob = {s: 0.25 for s in losses}
        beta = 0.75
        res = compute_discrete_cvar(losses, prob, beta)
        self.assertAlmostEqual(res.mean_loss, 1.5)
        self.assertAlmostEqual(res.tail_mass, 0.25)
        self.assertAlmostEqual(res.cvar, 3.0)
        self.assertAlmostEqual(res.var, 2.0)
        self.assertEqual(res.worst_scenarios, [3])

        beta2 = 0.5
        res2 = compute_discrete_cvar(losses, prob, beta2)
        self.assertAlmostEqual(res2.cvar, 2.5)
        self.assertAlmostEqual(res2.var, 1.0)

    def test_discrete_cvar_nonuniform_probability(self):
        from metrics_posthoc import compute_discrete_cvar

        losses = {"a": 1.0, "b": 4.0, "c": 7.0}
        prob = {"a": 0.5, "b": 0.3, "c": 0.2}
        beta = 0.8
        res = compute_discrete_cvar(losses, prob, beta)
        self.assertAlmostEqual(res.mean_loss, 0.5 * 1 + 0.3 * 4 + 0.2 * 7)
        self.assertAlmostEqual(res.tail_mass, 0.2)
        self.assertAlmostEqual(res.cvar, 7.0)
        self.assertIn("c", res.worst_scenarios)

        prob2 = {"a": 0.1, "b": 0.1, "c": 0.8}
        res2 = compute_discrete_cvar(losses, prob2, 0.5)
        self.assertAlmostEqual(res2.cvar, 7.0)


@unittest.skipUnless(HAS_GUROBI, "Gurobi not available")
class PosthocIntegrationTests(unittest.TestCase):
    def test_micro_pruned_compute_posthoc_zero(self):
        from b4_joint_data import load_joint_data
        from metrics_posthoc import compute_sf_loss_by_scenario, compute_posthoc_cvar_metrics
        from teavar_framework_models import build_teavar_model_c

        data = load_joint_data(
            topology_name="B4",
            num_tasks=4,
            routing_mode="per_task_od",
            k_paths=2,
            scenario_mode="micro_pruned",
            micro_k_max=2,
            micro_pi_min=1e-5,
        )
        m, *_rest, y, _xin, _xout, din, dout = build_teavar_model_c(
            data,
            gamma_sla=1.0,
            gamma_sf=1.0,
            omega_deliver=1.0,
            include_sf_budget=True,
            time_limit=60.0,
            mip_gap=0.05,
        )
        self.assertEqual(m.status, GRB.OPTIMAL)
        loss_sf = compute_sf_loss_by_scenario(data, y)
        self.assertTrue(all(v == 0.0 for v in loss_sf.values()))
        ph = compute_posthoc_cvar_metrics(data, y, din, dout, model_cvar_sla=1.0, model_cvar_sf=1.0)
        self.assertAlmostEqual(ph["posthoc_mean_sf_loss"], 0.0)
        self.assertAlmostEqual(ph["posthoc_cvar_sf"], 0.0)

    def test_model_c_aux_can_differ_from_posthoc(self):
        from b4_joint_data import load_joint_data
        from metrics_posthoc import compute_posthoc_cvar_metrics
        from teavar_framework_models import build_teavar_model_c

        # legacy_inverse_capacity makes routing economics differ enough that model
        # auxiliary CVaR and post-hoc CVaR diverge on this micro_pruned instance.
        data = load_joint_data(
            topology_name="B4",
            num_tasks=4,
            routing_mode="per_task_od",
            k_paths=2,
            scenario_mode="micro_pruned",
            micro_k_max=2,
            micro_pi_min=1e-5,
            pricing_profile="legacy",
            bandwidth_price_mode="legacy_inverse_capacity",
        )
        m, _cost, lvc, svc, y, _xin, _xout, din, dout = build_teavar_model_c(
            data,
            gamma_sla=1.0,
            gamma_sf=1.0,
            omega_deliver=1.0,
            include_sf_budget=True,
            time_limit=60.0,
            mip_gap=0.05,
        )
        self.assertEqual(m.status, GRB.OPTIMAL)
        ph = compute_posthoc_cvar_metrics(
            data, y, din, dout, model_cvar_sla=lvc, model_cvar_sf=svc
        )
        self.assertAlmostEqual(float(lvc), 1.0, places=3)
        self.assertLess(float(ph["posthoc_cvar_sla"]), float(lvc) - 0.05)
        self.assertAlmostEqual(float(ph["posthoc_mean_sla_loss"]), 0.0, delta=0.05)

    def test_d_ref_uses_per_resource_refs(self):
        from b4_joint_data import load_joint_data
        from cvar_compare import compute_sf_resource_refs
        from metrics_posthoc import compute_sf_loss_by_scenario, _placement_from_y
        from teavar_framework_models import build_teavar_model_c

        data = load_joint_data(
            topology_name="B4",
            num_tasks=4,
            routing_mode="per_task_od",
            k_paths=2,
        )
        m, *_rest, y, _xin, _xout, _din, _dout = build_teavar_model_c(
            data,
            gamma_sla=0.5,
            gamma_sf=0.5,
            omega_deliver=1.0,
            include_sf_budget=True,
            time_limit=60.0,
        )
        self.assertEqual(m.status, GRB.OPTIMAL)
        refs = compute_sf_resource_refs(data)
        placement = _placement_from_y(data, y)

        cap_s0 = float(data.C_s[data.M[0]][data.K[0]][data.S[0]])
        d_mk = sum(
            float(data.w[i][data.K[0]])
            for i in data.I
            if placement.get(i) == data.M[0]
        )
        expected = max(0.0, (d_mk - cap_s0) / refs[data.K[0]])

        loss_sf = compute_sf_loss_by_scenario(data, y, placement=placement, sf_d_ref_by_resource=refs)
        self.assertAlmostEqual(loss_sf[data.S[0]], expected, places=9)
        self.assertNotEqual(refs[data.K[0]], _legacy_m_ex(data))


class MetricColumnResolutionTests(unittest.TestCase):
    def test_resolve_auto_prefers_posthoc(self):
        from metrics_posthoc import resolve_cvar_metric_columns

        fields = [
            "cvar_sla",
            "cvar_sf",
            "posthoc_cvar_sla",
            "posthoc_cvar_sf",
        ]
        info = resolve_cvar_metric_columns(fields, "auto")
        self.assertEqual(info["metric_source"], "posthoc")
        self.assertEqual(info["sla_column"], "posthoc_cvar_sla")
        self.assertEqual(info["sf_column"], "posthoc_cvar_sf")

    def test_resolve_legacy_fallback_warning(self):
        from metrics_posthoc import resolve_cvar_metric_columns

        info = resolve_cvar_metric_columns(["cvar_sla", "cvar_sf"], "auto")
        self.assertEqual(info["metric_source"], "legacy")
        self.assertIn("WARNING", info["warning"] or "")


@unittest.skipUnless(HAS_GUROBI, "Gurobi not available")
class FrontierReportedColumnTests(unittest.TestCase):
    def test_run_gamma_frontier_reported_columns(self):
        from b4_joint_data import load_joint_data
        from run_gamma_frontier import _run_grid_point

        data = load_joint_data(
            topology_name="B4",
            num_tasks=4,
            routing_mode="per_task_od",
            k_paths=2,
        )
        row = _run_grid_point(
            data,
            gamma_sla=0.5,
            gamma_sf=0.5,
            time_limit=60,
            mip_gap=0.05,
            min_off_hub=0,
        )
        self.assertEqual(row["status"], "OPTIMAL")
        self.assertIn("reported_cvar_sla", row)
        self.assertIn("reported_cvar_sf", row)
        self.assertEqual(row.get("reported_metric_source"), "posthoc")
        self.assertIsNotNone(row.get("reported_cvar_sla"))
        self.assertIsNotNone(row.get("posthoc_cvar_sla"))
        self.assertAlmostEqual(
            float(row["reported_cvar_sla"]),
            float(row["posthoc_cvar_sla"]),
        )


if __name__ == "__main__":
    unittest.main()
