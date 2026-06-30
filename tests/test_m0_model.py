# -*- coding: utf-8 -*-
"""Unit tests for M0 deterministic placement–routing model."""

from __future__ import annotations

import unittest

from gurobipy import GRB

from duibi_metrics import teavar_flow_anchors
from m0_instances import M0_RELAY, build_m0_toy
from m0_models import build_m0_model, compute_link_load, link_load_expr, solve_m0_model


class M0ModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = build_m0_toy()

    def test_toy_multipath_per_od(self):
        data = self.data
        for i in data.I:
            src, dst = teavar_flow_anchors(data, i)
            for m in data.M:
                in_paths = data.P_cand[(src, m)]
                out_paths = data.P_cand[(m, dst)]
                self.assertGreaterEqual(len(in_paths), 2, msg=f"ingress ({src},{m})")
                self.assertGreaterEqual(len(out_paths), 2, msg=f"egress ({m},{dst})")

    def test_model_builds_and_feasible(self):
        model = build_m0_model(self.data, lambda_m0=0.5)
        res = solve_m0_model(model)
        self.assertEqual(res.status, GRB.OPTIMAL)
        self.assertLessEqual(res.U_link_max, 1.0 + 1e-6)
        self.assertLessEqual(res.U_node_max, 1.0 + 1e-6)
        self.assertGreaterEqual(res.U_link_max, 0.0)
        self.assertGreaterEqual(res.U_node_max, 0.0)

    def test_unique_placement_per_task(self):
        model = build_m0_model(self.data, lambda_m0=0.5)
        res = solve_m0_model(model)
        for i in self.data.I:
            chosen = [m for m in self.data.M if res.placement.get((i, m), 0.0) > 0.5]
            self.assertEqual(len(chosen), 1, msg=f"task {i} placement")

    def test_equality_flow_conservation(self):
        model = build_m0_model(self.data, lambda_m0=0.5)
        res = solve_m0_model(model)
        data = self.data
        for i in data.I:
            src, dst = teavar_flow_anchors(data, i)
            b_in = float(data.b_in[i])
            b_out = float(data.b_out[i])
            for m in data.M:
                if res.placement.get((i, m), 0.0) < 0.5:
                    in_sum = sum(
                        res.x_in.get((i, m, p), 0.0)
                        for p in range(len(data.P_cand[(src, m)]))
                    )
                    out_sum = sum(
                        res.x_out.get((i, m, q), 0.0)
                        for q in range(len(data.P_cand[(m, dst)]))
                    )
                    self.assertAlmostEqual(in_sum, 0.0, places=5)
                    self.assertAlmostEqual(out_sum, 0.0, places=5)
                else:
                    in_sum = sum(
                        res.x_in.get((i, m, p), 0.0)
                        for p in range(len(data.P_cand[(src, m)]))
                    )
                    out_sum = sum(
                        res.x_out.get((i, m, q), 0.0)
                        for q in range(len(data.P_cand[(m, dst)]))
                    )
                    self.assertAlmostEqual(in_sum, b_in, places=5)
                    self.assertAlmostEqual(out_sum, b_out, places=5)

    def test_link_load_matches_constraints(self):
        data = self.data
        model = build_m0_model(data, lambda_m0=0.5)
        res = solve_m0_model(model)
        for e in data.E:
            load = res.link_load[(int(e[0]), int(e[1]))]
            cap = float(data.B[e])
            self.assertLessEqual(load, cap * res.U_link_max + 1e-5)
            ratio = load / cap if cap > 0 else 0.0
            self.assertLessEqual(ratio, res.U_link_max + 1e-5)

    def test_link_load_expr_agrees_with_posthoc(self):
        data = self.data
        model = build_m0_model(data, lambda_m0=0.5)
        res = solve_m0_model(model)
        for e in data.E:
            expr_val = float(link_load_expr(data, model._m0_xin, model._m0_xout, (e[0], e[1])).getValue())
            self.assertAlmostEqual(expr_val, res.link_load[(int(e[0]), int(e[1]))], places=5)

    def test_compute_link_load_helper(self):
        data = self.data
        model = build_m0_model(data, lambda_m0=0.5)
        res = solve_m0_model(model)
        loads = compute_link_load(data, res.x_in, res.x_out)
        self.assertEqual(set(loads.keys()), set((int(e[0]), int(e[1])) for e in data.E))
        for e, val in loads.items():
            self.assertAlmostEqual(val, res.link_load[e], places=5)

    def test_no_scenario_or_cvar_vars(self):
        model = build_m0_model(self.data, lambda_m0=0.5)
        names = [v.VarName for v in model.getVars()]
        allowed_u = {"U_link_max", "U_node_max"}
        forbidden_prefixes = ("r_", "z_", "eta", "u_s", "zeta", "del_")
        for n in names:
            if n in allowed_u:
                continue
            low = n.lower()
            for prefix in forbidden_prefixes:
                self.assertFalse(low.startswith(prefix), msg=f"unexpected var {n}")
            self.assertNotIn("gamma", low)

    def test_lambda_tradeoff_link_vs_node(self):
        data = self.data
        res_link = solve_m0_model(build_m0_model(data, lambda_m0=1.0))
        res_node = solve_m0_model(build_m0_model(data, lambda_m0=0.0))
        self.assertEqual(res_link.status, GRB.OPTIMAL)
        self.assertEqual(res_node.status, GRB.OPTIMAL)

        # lambda=1 optimum should not have worse link balance than lambda=0 optimum
        self.assertLessEqual(
            res_link.U_link_max,
            res_node.U_link_max + 1e-4,
            msg=f"link: lam=1 -> {res_link.U_link_max}, lam=0 -> {res_node.U_link_max}",
        )
        # lambda=0 optimum should not have worse node balance than lambda=1 optimum
        self.assertLessEqual(
            res_node.U_node_max,
            res_link.U_node_max + 1e-4,
            msg=f"node: lam=0 -> {res_node.U_node_max}, lam=1 -> {res_link.U_node_max}",
        )
        # Trade-off should be strict on at least one axis for this toy.
        strict = (
            res_link.U_link_max + 1e-4 < res_node.U_link_max
            or res_node.U_node_max + 1e-4 < res_link.U_node_max
        )
        self.assertTrue(strict, "toy should expose link vs node trade-off")

    def test_colocated_placement_is_node_heavy(self):
        """Both tasks on node 5 -> high U_node; split 4/6 is better for lambda=0."""
        data = self.data
        res_node = solve_m0_model(build_m0_model(data, lambda_m0=0.0))
        chosen = {i: m for i in data.I for m in data.M if res_node.placement.get((i, m), 0) > 0.5}
        self.assertNotEqual(chosen[0], chosen[1], msg="lambda=0 should split compute load")

    def test_relay_edges_used_under_link_objective(self):
        """lambda=1 should prefer low-util routing (often direct / split off relay)."""
        data = self.data
        res = solve_m0_model(build_m0_model(data, lambda_m0=1.0))
        relay_load = sum(
            load
            for e, load in res.link_load.items()
            if M0_RELAY in e
        )
        total_demand = sum(float(data.b_in[i]) + float(data.b_out[i]) for i in data.I)
        self.assertLess(relay_load, total_demand, msg="link-opt should not push all traffic via relay")


if __name__ == "__main__":
    unittest.main()
