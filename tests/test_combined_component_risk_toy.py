# -*- coding: utf-8 -*-
"""
Integration validation: Toy-Combined-ComponentRisk.

Component-level link/compute failures (512 scenarios) with placement +
bandwidth cost.  Asserts structural trade-off properties, not hand-written
macro-scenario tables.
"""
from __future__ import annotations

import unittest

try:
    from gurobipy import GRB

    HAS_GUROBI = True
except ImportError:
    HAS_GUROBI = False

from component_scenario_generator import FailureComponent, iter_component_failure_states
from exact_enumeration_solver import (
    RouteChoice,
    assert_close,
    count_feasible_solutions,
    evaluate_solution,
    extract_model_a_result,
    extract_model_c_result,
    placements_match,
    solve_exact_model_a,
    solve_exact_model_c,
)
from toy_instances import (
    CR_A,
    CR_B,
    CR_C,
    build_toy_combined_component_risk,
    count_placement_nodes,
    format_component_risk_placement,
)

TOL = 1e-5


def _default_routes(data) -> RouteChoice:
    return RouteChoice(in_path={i: 0 for i in data.I}, out_path={i: 0 for i in data.I})


def _placement_from_code(code: str) -> dict[int, int]:
    lab = {"A": CR_A, "B": CR_B, "C": CR_C}
    return {i: lab[ch] for i, ch in enumerate(code)}


def _run_model_a(data, lambda_sla: float, lambda_sf: float = 0.0):
    from teavar_framework_models import build_teavar_model_a

    m, cost, lv, sfv, y, xi, xo, din, dout = build_teavar_model_a(
        data,
        lambda_sla=lambda_sla,
        lambda_sf=lambda_sf,
        omega_deliver=0.0,
        beta_loss=data.beta_N,
        beta_sf=data.beta_N,
        time_limit=120.0,
    )
    return extract_model_a_result(
        m, cost, lv, sfv, y, xi, xo, din, dout, data,
        lambda_sla=lambda_sla, lambda_sf=lambda_sf,
    )


def _run_model_c(data, gamma_sla: float, gamma_sf: float):
    from teavar_framework_models import build_teavar_model_c

    m, cost, lv, sfv, y, xi, xo, din, dout = build_teavar_model_c(
        data,
        gamma_sla=gamma_sla,
        gamma_sf=gamma_sf,
        omega_deliver=0.0,
        beta_loss=data.beta_N,
        beta_sf=data.beta_N,
        include_sf_budget=True,
        time_limit=120.0,
    )
    return extract_model_c_result(
        m, cost, lv, sfv, y, xi, xo, din, dout, data,
        gamma_sf=gamma_sf,
    )


class TestComponentScenarioGenerator(unittest.TestCase):
    def test_nine_components_yield_512_states(self):
        comps = [
            FailureComponent("link", "A_in", 0.005),
            FailureComponent("link", "A_out", 0.005),
            FailureComponent("link", "B_in", 0.10),
            FailureComponent("link", "B_out", 0.10),
            FailureComponent("link", "C_in", 0.005),
            FailureComponent("link", "C_out", 0.005),
            FailureComponent("compute_derate", "A", 0.20),
            FailureComponent("compute_derate", "B", 0.01),
            FailureComponent("compute_derate", "C", 0.005),
        ]
        states = list(iter_component_failure_states(comps))
        self.assertEqual(len(states), 512)
        prob_sum = sum(p for _sid, _failed, p in states)
        self.assertAlmostEqual(prob_sum, 1.0, places=9)


class TestComponentRiskToyStructure(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = build_toy_combined_component_risk()
        cls.routes = _default_routes(cls.data)

    def test_topology_and_scenarios(self):
        self.assertEqual(len(self.data.I), 3)
        self.assertEqual(len(self.data.M), 3)
        self.assertEqual(len(self.data.S), 512)
        self.assertAlmostEqual(sum(self.data.prob.values()), 1.0, places=9)
        self.assertEqual(count_feasible_solutions(self.data), 27)

    def test_hand_cost_aaa_bbb_ccc(self):
        cases = {
            "AAA": 3 * 0.04,
            "BBB": 3 * 0.05,
            "CCC": 3 * 0.28,
        }
        for code, expected in cases.items():
            ev = evaluate_solution(
                self.data, _placement_from_code(code), self.routes,
            )
            assert_close(ev.cost, expected, tol=TOL, label=f"cost {code}")

    def test_pure_placements_risk_ordering(self):
        """Sanity: A best SLA among cheap; B best SF among cheap; C best on both."""
        ev_a = evaluate_solution(self.data, _placement_from_code("AAA"), self.routes)
        ev_b = evaluate_solution(self.data, _placement_from_code("BBB"), self.routes)
        ev_c = evaluate_solution(self.data, _placement_from_code("CCC"), self.routes)
        self.assertLess(ev_a.cvar_sla, ev_b.cvar_sla)
        self.assertLess(ev_c.cvar_sla, ev_b.cvar_sla)
        self.assertLess(ev_b.cvar_sf, ev_a.cvar_sf)
        self.assertLess(ev_c.cvar_sf, ev_a.cvar_sf)
        self.assertLess(ev_a.cost, ev_b.cost)
        self.assertLess(ev_b.cost, ev_c.cost)


class TestComponentRiskModelA(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = build_toy_combined_component_risk()

    def test_cheap_risk_placement_is_a_heavy(self):
        r = solve_exact_model_a(self.data, lambda_sla=0.0, lambda_sf=0.0)
        self.assertIsNotNone(r.best)
        self.assertEqual(count_placement_nodes(r.best.placement, CR_A), 3)
        self.assertEqual(format_component_risk_placement(r.best.placement), "AAA")

    def test_high_sla_weight_favors_a_over_b(self):
        cheap = solve_exact_model_a(self.data, lambda_sla=0.0, lambda_sf=0.0)
        risk = solve_exact_model_a(self.data, lambda_sla=50.0, lambda_sf=0.01)
        n_a_cheap = count_placement_nodes(cheap.best.placement, CR_A)
        n_b_cheap = count_placement_nodes(cheap.best.placement, CR_B)
        n_a_risk = count_placement_nodes(risk.best.placement, CR_A)
        n_b_risk = count_placement_nodes(risk.best.placement, CR_B)
        self.assertGreaterEqual(n_a_risk, n_b_risk)
        self.assertGreaterEqual(n_a_risk, n_a_cheap - 1)

    def test_high_sf_weight_favors_b_over_a(self):
        risk = solve_exact_model_a(self.data, lambda_sla=0.01, lambda_sf=10.0)
        self.assertIsNotNone(risk.best)
        self.assertGreater(
            count_placement_nodes(risk.best.placement, CR_B),
            count_placement_nodes(risk.best.placement, CR_A),
        )
        self.assertEqual(format_component_risk_placement(risk.best.placement), "BBB")

    def test_high_both_weights_favor_c(self):
        risk = solve_exact_model_a(self.data, lambda_sla=50.0, lambda_sf=50.0)
        self.assertIsNotNone(risk.best)
        self.assertEqual(count_placement_nodes(risk.best.placement, CR_C), 3)

    @unittest.skipUnless(HAS_GUROBI, "Gurobi not installed")
    def test_gurobi_model_a_matches_exact_high_sf(self):
        exact = solve_exact_model_a(self.data, lambda_sla=0.01, lambda_sf=10.0)
        gurobi = _run_model_a(self.data, lambda_sla=0.01, lambda_sf=10.0)
        self.assertEqual(gurobi.status, GRB.OPTIMAL)
        self.assertTrue(placements_match(exact.best.placement, gurobi.placement, data=self.data))
        assert_close(gurobi.cost, exact.best.cost, tol=1e-3)


class TestComponentRiskModelC(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = build_toy_combined_component_risk()

    def test_wide_budgets_prefer_cheap_over_c(self):
        """Wide Γ with SF budget allowing A → AAA, not CCC."""
        r = solve_exact_model_c(self.data, gamma_sla=0.08, gamma_sf=1.0)
        self.assertIsNotNone(r.best)
        self.assertLess(r.best.cost, 0.20)
        self.assertEqual(count_placement_nodes(r.best.placement, CR_C), 0)

    def test_tight_sla_reduces_b_usage(self):
        wide = solve_exact_model_c(self.data, gamma_sla=1.0, gamma_sf=0.08)
        tight = solve_exact_model_c(self.data, gamma_sla=0.08, gamma_sf=0.08)
        self.assertIsNotNone(wide.best)
        self.assertIsNotNone(tight.best)
        n_b_wide = count_placement_nodes(wide.best.placement, CR_B)
        n_b_tight = count_placement_nodes(tight.best.placement, CR_B)
        self.assertGreaterEqual(n_b_wide, n_b_tight)
        self.assertEqual(n_b_wide, 3)

    def test_tight_sf_reduces_a_usage(self):
        wide = solve_exact_model_c(self.data, gamma_sla=0.08, gamma_sf=1.0)
        tight = solve_exact_model_c(self.data, gamma_sla=0.08, gamma_sf=0.06)
        self.assertIsNotNone(wide.best)
        self.assertIsNotNone(tight.best)
        n_a_wide = count_placement_nodes(wide.best.placement, CR_A)
        n_a_tight = count_placement_nodes(tight.best.placement, CR_A)
        self.assertGreater(n_a_wide, n_a_tight)

    def test_both_tight_increases_c_usage(self):
        wide = solve_exact_model_c(self.data, gamma_sla=0.08, gamma_sf=1.0)
        tight = solve_exact_model_c(self.data, gamma_sla=0.06, gamma_sf=0.06)
        self.assertIsNotNone(wide.best)
        self.assertIsNotNone(tight.best)
        n_c_wide = count_placement_nodes(wide.best.placement, CR_C)
        n_c_tight = count_placement_nodes(tight.best.placement, CR_C)
        self.assertGreater(n_c_tight, n_c_wide)
        self.assertEqual(n_c_tight, 3)

    @unittest.skipUnless(HAS_GUROBI, "Gurobi not installed")
    def test_gurobi_model_c_matches_exact_both_tight(self):
        exact = solve_exact_model_c(self.data, gamma_sla=0.06, gamma_sf=0.06)
        gurobi = _run_model_c(self.data, gamma_sla=0.06, gamma_sf=0.06)
        self.assertEqual(gurobi.status, GRB.OPTIMAL)
        self.assertTrue(placements_match(exact.best.placement, gurobi.placement, data=self.data))
        assert_close(gurobi.cost, exact.best.cost, tol=1e-3)


if __name__ == "__main__":
    unittest.main()
