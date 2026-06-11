# -*- coding: utf-8 -*-
"""Exact-enumeration validation: Model A/C vs brute-force optimum on toy instances."""
from __future__ import annotations

import unittest

try:
    from gurobipy import GRB

    HAS_GUROBI = True
except ImportError:
    HAS_GUROBI = False

from exact_enumeration_solver import (
    RouteChoice,
    assert_close,
    count_feasible_solutions,
    enumerate_placements,
    enumerate_routes,
    evaluate_solution,
    extract_model_a_result,
    extract_model_c_result,
    placements_match,
    solve_exact_model_a,
    solve_exact_model_c,
)
from toy_instances import (
    K_CPU,
    K_GPU,
    K_HBM,
    SLA_A,
    SLA_B,
    SLA_C,
    SF_A,
    SF_B,
    SF_C,
    build_toy_sla,
    build_toy_sf,
    format_placement,
)

TOL = 1e-5
SLA_COMPUTE = (SLA_A, SLA_B, SLA_C)
SF_COMPUTE = (SF_A, SF_B, SF_C)


def _default_routes(data) -> RouteChoice:
    in_path: dict[int, int] = {}
    out_path: dict[int, int] = {}
    for i in data.I:
        in_path[i] = 0
        out_path[i] = 0
    return RouteChoice(in_path=in_path, out_path=out_path)


def _placement_cost(data, placement: dict[int, int]) -> float:
    total = 0.0
    for i in data.I:
        m = placement[i]
        for k in data.K:
            total += float(data.w[i][k]) * float(data.p_price[m][k])
    return total


def _all_evaluated(data, **eval_kw):
    out = []
    for placement in enumerate_placements(data):
        for routes in enumerate_routes(data, placement):
            ev = evaluate_solution(
                data,
                placement,
                routes,
                beta_sla=data.beta_N,
                beta_sf=data.beta_N,
                **eval_kw,
            )
            out.append((dict(placement), routes, ev))
    return out


def _assert_ac_or_ca(testcase, placement: dict[int, int]) -> None:
    testcase.assertEqual(set(placement.values()), {SF_A, SF_C})
    testcase.assertNotEqual(placement[0], placement[1])


def _run_model_a(data, lambda_sla: float, lambda_sf: float = 0.0, omega_deliver: float = 0.0):
    from teavar_framework_models import build_teavar_model_a

    m, cost, lv, sfv, y, xi, xo, din, dout = build_teavar_model_a(
        data,
        lambda_sla=lambda_sla,
        lambda_sf=lambda_sf,
        omega_deliver=omega_deliver,
        beta_loss=data.beta_N,
        beta_sf=data.beta_N,
    )
    return m, extract_model_a_result(
        m, cost, lv, sfv, y, xi, xo, din, dout, data,
        lambda_sla=lambda_sla, lambda_sf=lambda_sf,
    )


def _run_model_c(
    data,
    gamma_sla: float,
    gamma_sf: float | None,
    omega_deliver: float = 0.0,
):
    from teavar_framework_models import build_teavar_model_c

    m, cost, lv, sfv, y, xi, xo, din, dout = build_teavar_model_c(
        data,
        gamma_sla=gamma_sla,
        gamma_sf=gamma_sf,
        omega_deliver=omega_deliver,
        beta_loss=data.beta_N,
        beta_sf=data.beta_N,
        include_sf_budget=gamma_sf is not None,
    )
    return m, extract_model_c_result(
        m, cost, lv, sfv, y, xi, xo, din, dout, data,
        gamma_sf=gamma_sf,
    )


def _compare_model_a(data, lambda_sla: float, lambda_sf: float = 0.0):
    exact = solve_exact_model_a(
        data,
        lambda_sla=lambda_sla,
        lambda_sf=lambda_sf,
        omega_deliver=0.0,
        beta_sla=data.beta_N,
        beta_sf=data.beta_N,
    )
    _m, gurobi = _run_model_a(data, lambda_sla, lambda_sf, omega_deliver=0.0)
    assert exact.best is not None
    assert gurobi.status == GRB.OPTIMAL, f"Gurobi status={gurobi.status_name}"

    assert_close(gurobi.objective, exact.best.model_a_objective, TOL, "objective")
    assert_close(gurobi.cost, exact.best.cost, TOL, "cost")
    if lambda_sla > TOL:
        assert_close(gurobi.cvar_sla, exact.best.cvar_sla, TOL, "cvar_sla")
    else:
        assert not gurobi.cvar_sla_active, "cvar_sla should be marked inactive (N/A)"
    if lambda_sf > TOL:
        assert_close(gurobi.cvar_sf, exact.best.cvar_sf, TOL, "cvar_sf")
    assert placements_match(gurobi.placement, exact.best.placement, data=data)
    return exact, gurobi


def _compare_model_c(data, gamma_sla: float, gamma_sf: float | None):
    exact = solve_exact_model_c(
        data,
        gamma_sla=gamma_sla,
        gamma_sf=gamma_sf,
        omega_deliver=0.0,
        beta_sla=data.beta_N,
        beta_sf=data.beta_N,
    )
    _m, gurobi = _run_model_c(data, gamma_sla, gamma_sf, omega_deliver=0.0)
    assert exact.best is not None, f"exact infeasible for gamma_sla={gamma_sla} gamma_sf={gamma_sf}"
    assert gurobi.status == GRB.OPTIMAL, f"Gurobi status={gurobi.status_name}"

    assert_close(gurobi.cost, exact.best.cost, TOL, "cost")
    assert_close(gurobi.cvar_sla, exact.best.cvar_sla, TOL, "cvar_sla")
    if gamma_sf is not None:
        assert_close(gurobi.cvar_sf, exact.best.cvar_sf, TOL, "cvar_sf")
    assert placements_match(gurobi.placement, exact.best.placement, data=data)
    return exact, gurobi


def _assert_sf_model_vars_nonnegative(testcase, data) -> None:
    from cvar_compare import build_teavar_sla_cvar_model

    m, _cp, _lv, _nv, sfv, *_ = build_teavar_sla_cvar_model(
        data,
        lambda_cvar=0.0,
        lambda_compute_sf_cvar=1.0,
        omega_deliver=0.0,
    )
    testcase.assertEqual(m.status, GRB.OPTIMAL)
    zeta = m.getVarByName("zeta_compute_sf")
    testcase.assertIsNotNone(zeta)
    testcase.assertGreaterEqual(zeta.LB, 0.0 - 1e-12)
    testcase.assertGreaterEqual(float(zeta.X), -TOL)
    testcase.assertGreaterEqual(float(sfv), -TOL)
    for v in m.getVars():
        if v.VarName.startswith("phi_compute_sf"):
            testcase.assertGreaterEqual(v.LB, 0.0 - 1e-12)
            testcase.assertGreaterEqual(float(v.X), -TOL)


@unittest.skipUnless(HAS_GUROBI, "Gurobi not available")
class ToySLAExactValidation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = build_toy_sla()
        cls.n_feasible = count_feasible_solutions(cls.data)
        cls.routes = _default_routes(cls.data)

    def test_topology_and_candidates(self):
        self.assertEqual(self.data.K, [K_CPU, K_GPU, K_HBM])
        self.assertEqual(list(self.data.M), list(SLA_COMPUTE))
        expected = {(0, m) for m in SLA_COMPUTE}
        self.assertEqual(set(self.data.valid_assign), expected)

    def test_enumeration_count(self):
        self.assertEqual(self.n_feasible, 3)
        self.assertEqual(len(self.data.M), 3)

    def test_placement_economics_and_reliability(self):
        ev_a = evaluate_solution(self.data, {0: SLA_A}, self.routes, beta_sla=self.data.beta_N)
        ev_b = evaluate_solution(self.data, {0: SLA_B}, self.routes, beta_sla=self.data.beta_N)
        ev_c = evaluate_solution(self.data, {0: SLA_C}, self.routes, beta_sla=self.data.beta_N)

        self.assertAlmostEqual(ev_a.cost, 0.0, places=9)
        self.assertAlmostEqual(ev_b.cost, 0.2, places=9)
        self.assertAlmostEqual(ev_c.cost, 0.1, places=9)
        self.assertGreater(ev_b.cost, ev_c.cost)

        self.assertAlmostEqual(ev_a.scenario_sla_loss[1], 1.0, places=9)
        self.assertAlmostEqual(ev_b.scenario_sla_loss[1], 0.0, places=9)
        self.assertAlmostEqual(ev_c.scenario_sla_loss[1], 0.0, places=9)
        self.assertAlmostEqual(ev_a.cvar_sla, 1.0, places=9)
        self.assertAlmostEqual(ev_b.cvar_sla, 0.0, places=9)
        self.assertAlmostEqual(ev_c.cvar_sla, 0.0, places=9)

    def test_all_placements_sf_cvar_zero(self):
        for _placement, _routes, ev in _all_evaluated(self.data):
            self.assertAlmostEqual(ev.cvar_sf, 0.0, places=9, msg=f"placement={_placement}")
            self.assertAlmostEqual(ev.scenario_sf_loss[0], 0.0, places=9)
            self.assertAlmostEqual(ev.scenario_sf_loss[1], 0.0, places=9)

    def test_heterogeneous_resources_present(self):
        self.assertGreater(self.data.C_normal[SLA_B][K_GPU], self.data.C_normal[SLA_A][K_GPU])
        self.assertGreater(self.data.C_normal[SLA_C][K_GPU], self.data.C_normal[SLA_A][K_GPU])

    def test_zeta_sf_model_nonnegative_on_toy(self):
        _assert_sf_model_vars_nonnegative(self, self.data)

    def test_toy_sla_model_a_high_lambda_matches_exact(self):
        exact, gurobi = _compare_model_a(self.data, lambda_sla=1.0, lambda_sf=0.0)
        self.assertEqual(format_placement(self.data, exact.best.placement), "C")
        self.assertEqual(format_placement(self.data, gurobi.placement), "C")
        self.assertAlmostEqual(exact.best.cost, 0.1, places=9)

    def test_toy_sla_model_a_low_lambda_matches_exact(self):
        exact, gurobi = _compare_model_a(self.data, lambda_sla=0.1, lambda_sf=0.0)
        self.assertEqual(format_placement(self.data, exact.best.placement), "A")
        self.assertEqual(format_placement(self.data, gurobi.placement), "A")
        self.assertAlmostEqual(exact.best.model_a_objective, 0.1, places=9)

    def test_toy_sla_model_c_gamma_matches_exact(self):
        exact_c, gurobi_c = _compare_model_c(self.data, gamma_sla=0.5, gamma_sf=None)
        self.assertEqual(format_placement(self.data, exact_c.best.placement), "C")
        self.assertEqual(format_placement(self.data, gurobi_c.placement), "C")

        exact_a, gurobi_a = _compare_model_c(self.data, gamma_sla=1.0, gamma_sf=None)
        self.assertEqual(format_placement(self.data, exact_a.best.placement), "A")
        self.assertEqual(format_placement(self.data, gurobi_a.placement), "A")


@unittest.skipUnless(HAS_GUROBI, "Gurobi not available")
class ToySFExactValidation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = build_toy_sf()
        cls.n_feasible = count_feasible_solutions(cls.data)
        cls.routes = _default_routes(cls.data)
        from cvar_compare import compute_sf_resource_refs

        cls.d_ref_by_k = compute_sf_resource_refs(cls.data)

    def test_topology_and_candidates(self):
        self.assertEqual(self.data.K, [K_CPU, K_GPU, K_HBM])
        self.assertEqual(list(self.data.M), list(SF_COMPUTE))
        expected = {(i, m) for i in self.data.I for m in SF_COMPUTE}
        self.assertEqual(set(self.data.valid_assign), expected)

    def test_toy_sf_per_resource_dref(self):
        self.assertAlmostEqual(self.d_ref_by_k[K_CPU], 4.0, places=9)
        self.assertAlmostEqual(self.d_ref_by_k[K_GPU], 2.0, places=9)
        self.assertAlmostEqual(self.d_ref_by_k[K_HBM], 2.0, places=9)

    def test_heterogeneous_node_profiles(self):
        self.assertEqual(len(self.data.M), 3)
        self.assertGreater(self.data.C_normal[SF_B][K_GPU], self.data.C_normal[SF_A][K_GPU])
        self.assertAlmostEqual(self.data.C_normal[SF_C][K_CPU], self.data.C_normal[SF_B][K_CPU])
        self.assertEqual(len(self.data.K), 3)

    def test_enumeration_count(self):
        self.assertEqual(self.n_feasible, 9)

    def test_manual_aa_cpu_overflow_only(self):
        ev_aa = evaluate_solution(
            self.data,
            {0: SF_A, 1: SF_A},
            self.routes,
            beta_sf=self.data.beta_N,
        )
        cpu_overflow = (4.0 - 2.0) / self.d_ref_by_k[K_CPU]
        self.assertAlmostEqual(ev_aa.scenario_sf_loss[1], cpu_overflow, places=9)
        self.assertAlmostEqual(ev_aa.cvar_sf, cpu_overflow, places=9)
        self.assertAlmostEqual(cpu_overflow, 0.5, places=9)
        self.assertAlmostEqual(ev_aa.scenario_sf_loss[0], 0.0, places=9)

        load_a = {K_CPU: 4.0, K_GPU: 2.0, K_HBM: 2.0}
        cap_a_s1 = {
            K_CPU: float(self.data.C_s[SF_A][K_CPU][1]),
            K_GPU: float(self.data.C_s[SF_A][K_GPU][1]),
            K_HBM: float(self.data.C_s[SF_A][K_HBM][1]),
        }
        per_k = {
            k: max(0.0, load_a[k] - cap_a_s1[k]) / self.d_ref_by_k[k]
            for k in self.data.K
        }
        self.assertAlmostEqual(per_k[K_CPU], 0.5, places=9)
        self.assertAlmostEqual(per_k[K_GPU], 0.0, places=9)
        self.assertAlmostEqual(per_k[K_HBM], 0.0, places=9)

    def test_manual_ac_and_ca_zero_sf_cost_015(self):
        for placement in ({0: SF_A, 1: SF_C}, {0: SF_C, 1: SF_A}):
            ev = evaluate_solution(self.data, placement, self.routes, beta_sf=self.data.beta_N)
            self.assertAlmostEqual(ev.cvar_sf, 0.0, places=9)
            self.assertAlmostEqual(ev.cost, 0.15, places=9)
            self.assertAlmostEqual(ev.scenario_sf_loss[1], 0.0, places=9)

    def test_all_placements_sla_zero_under_full_flow(self):
        for _placement, _routes, ev in _all_evaluated(self.data):
            self.assertAlmostEqual(ev.cvar_sla, 0.0, places=9, msg=f"placement={_placement}")
            self.assertAlmostEqual(ev.scenario_sla_loss[0], 0.0, places=9)
            self.assertAlmostEqual(ev.scenario_sla_loss[1], 0.0, places=9)

    def test_zeta_sf_model_nonnegative_on_toy(self):
        _assert_sf_model_vars_nonnegative(self, self.data)

    def test_toy_sf_model_a_high_lambda_matches_exact(self):
        exact, gurobi = _compare_model_a(self.data, lambda_sla=0.0, lambda_sf=1.0)
        _assert_ac_or_ca(self, exact.best.placement)
        _assert_ac_or_ca(self, gurobi.placement)
        self.assertAlmostEqual(exact.best.cost, 0.15, places=9)
        self.assertAlmostEqual(exact.best.cvar_sf, 0.0, places=9)
        self.assertFalse(gurobi.cvar_sla_active)

    def test_toy_sf_model_a_low_lambda_matches_exact(self):
        exact, gurobi = _compare_model_a(self.data, lambda_sla=0.0, lambda_sf=0.1)
        self.assertEqual(exact.best.placement[0], SF_A)
        self.assertEqual(exact.best.placement[1], SF_A)
        self.assertEqual(gurobi.placement[0], SF_A)
        self.assertEqual(gurobi.placement[1], SF_A)
        self.assertAlmostEqual(exact.best.model_a_objective, 0.05, places=9)

    def test_toy_sf_model_c_gamma_matches_exact(self):
        exact_split, gurobi_split = _compare_model_c(self.data, gamma_sla=1.0, gamma_sf=0.25)
        _assert_ac_or_ca(self, exact_split.best.placement)
        _assert_ac_or_ca(self, gurobi_split.placement)
        self.assertAlmostEqual(exact_split.best.cost, 0.15, places=9)

        exact_aa, gurobi_aa = _compare_model_c(self.data, gamma_sla=1.0, gamma_sf=0.5)
        self.assertEqual(exact_aa.best.placement[0], SF_A)
        self.assertEqual(exact_aa.best.placement[1], SF_A)
        self.assertEqual(gurobi_aa.placement[0], SF_A)
        self.assertEqual(gurobi_aa.placement[1], SF_A)


if __name__ == "__main__":
    unittest.main()
