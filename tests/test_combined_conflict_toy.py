# -*- coding: utf-8 -*-
"""
Integration exact-validation: Toy-Combined-Conflict (SLA vs SF opposing risks).

Tier 1 — complements Tier-0 Toy-SLA / Toy-SF without modifying them.
"""
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
    evaluate_solution,
    extract_model_a_result,
    extract_model_c_result,
    placements_match,
    solve_exact_model_a,
    solve_exact_model_c,
)
from toy_instances import (
    COMB_A,
    COMB_B,
    COMB_C,
    K_CPU,
    K_GPU,
    K_HBM,
    build_toy_combined,
    format_combined_placement,
)

TOL = 1e-5
COMB_COMPUTE = (COMB_A, COMB_B, COMB_C)

# Hand-computed under per-task-max SLA + full-flow delivery (see docs/exact_validation.md).
# Symmetric pairs AB/BA, AC/CA, BC/CB share the same metrics.
LOSS_TABLE: dict[str, tuple[float, float, float]] = {
    "AA": (0.00, 0.0, 1.0),
    "AB": (0.02, 1.0, 0.5),
    "AC": (0.20, 0.0, 0.5),
    "BB": (0.04, 1.0, 0.0),
    "BC": (0.22, 1.0, 0.0),
    "CC": (0.40, 0.0, 0.0),
}


def _default_routes(data) -> RouteChoice:
    return RouteChoice(
        in_path={i: 0 for i in data.I},
        out_path={i: 0 for i in data.I},
    )


def _run_model_a(data, lambda_sla: float, lambda_sf: float = 0.0):
    from teavar_framework_models import build_teavar_model_a

    m, cost, lv, sfv, y, xi, xo, din, dout = build_teavar_model_a(
        data,
        lambda_sla=lambda_sla,
        lambda_sf=lambda_sf,
        omega_deliver=0.0,
        beta_loss=data.beta_N,
        beta_sf=data.beta_N,
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
    )
    return extract_model_c_result(
        m, cost, lv, sfv, y, xi, xo, din, dout, data,
        gamma_sf=gamma_sf,
    )


def _compare_model_a(data, lambda_sla: float, lambda_sf: float):
    exact = solve_exact_model_a(
        data, lambda_sla=lambda_sla, lambda_sf=lambda_sf,
        beta_sla=data.beta_N, beta_sf=data.beta_N,
    )
    gurobi = _run_model_a(data, lambda_sla, lambda_sf)
    assert exact.best is not None
    assert gurobi.status == GRB.OPTIMAL
    assert_close(gurobi.objective, exact.best.model_a_objective, TOL, "objective")
    assert_close(gurobi.cost, exact.best.cost, TOL, "cost")
    assert_close(gurobi.cvar_sla, exact.best.cvar_sla, TOL, "cvar_sla")
    assert_close(gurobi.cvar_sf, exact.best.cvar_sf, TOL, "cvar_sf")
    assert placements_match(gurobi.placement, exact.best.placement, data=data)
    return exact, gurobi


def _compare_model_c(data, gamma_sla: float, gamma_sf: float):
    exact = solve_exact_model_c(
        data, gamma_sla=gamma_sla, gamma_sf=gamma_sf,
        beta_sla=data.beta_N, beta_sf=data.beta_N,
    )
    gurobi = _run_model_c(data, gamma_sla, gamma_sf)
    assert exact.best is not None, f"exact infeasible gamma=({gamma_sla},{gamma_sf})"
    assert gurobi.status == GRB.OPTIMAL
    assert_close(gurobi.cost, exact.best.cost, TOL, "cost")
    assert_close(gurobi.cvar_sla, exact.best.cvar_sla, TOL, "cvar_sla")
    assert_close(gurobi.cvar_sf, exact.best.cvar_sf, TOL, "cvar_sf")
    assert placements_match(gurobi.placement, exact.best.placement, data=data)
    return exact, gurobi


def _assert_code_in(testcase, placement: dict[int, int], allowed: set[str]) -> None:
    code = format_combined_placement(placement)
    testcase.assertIn(code, allowed, f"placement {code} not in {allowed}")


@unittest.skipUnless(HAS_GUROBI, "Gurobi not available")
class CombinedConflictToyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = build_toy_combined()
        cls.routes = _default_routes(cls.data)
        cls.n_feasible = count_feasible_solutions(cls.data)

    def test_combined_conflict_has_3_compute_nodes(self):
        self.assertEqual(self.data.K, [K_CPU, K_GPU, K_HBM])
        self.assertEqual(list(self.data.M), list(COMB_COMPUTE))
        self.assertEqual(len(self.data.M), 3)

    def test_combined_conflict_has_9_feasible_placements(self):
        self.assertEqual(self.n_feasible, 9)

    def test_combined_conflict_loss_table(self):
        seen: set[str] = set()
        for placement in enumerate_placements(self.data):
            code = format_combined_placement(placement)
            if code in seen:
                continue
            seen.add(code)
            ev = evaluate_solution(
                self.data, placement, self.routes,
                beta_sla=self.data.beta_N, beta_sf=self.data.beta_N,
            )
            canon = code if code in LOSS_TABLE else code[::-1] if code[::-1] in LOSS_TABLE else code
            if code in ("BA", "CA", "CB"):
                canon = {"BA": "AB", "CA": "AC", "CB": "BC"}[code]
            exp_cost, exp_sla, exp_sf = LOSS_TABLE[canon]
            self.assertAlmostEqual(ev.cost, exp_cost, places=6, msg=code)
            self.assertAlmostEqual(ev.cvar_sla, exp_sla, places=6, msg=code)
            self.assertAlmostEqual(ev.cvar_sf, exp_sf, places=6, msg=code)
        self.assertEqual(seen, {"AA", "AB", "BA", "AC", "CA", "BB", "BC", "CB", "CC"})

    def test_a_network_safe_sf_risky(self):
        ev_aa = evaluate_solution(
            self.data, {0: COMB_A, 1: COMB_A}, self.routes,
            beta_sla=self.data.beta_N, beta_sf=self.data.beta_N,
        )
        self.assertAlmostEqual(ev_aa.cvar_sla, 0.0, places=9)
        self.assertAlmostEqual(ev_aa.cvar_sf, 1.0, places=9)

    def test_b_compute_safe_sla_risky(self):
        ev_bb = evaluate_solution(
            self.data, {0: COMB_B, 1: COMB_B}, self.routes,
            beta_sla=self.data.beta_N, beta_sf=self.data.beta_N,
        )
        self.assertAlmostEqual(ev_bb.cvar_sf, 0.0, places=9)
        self.assertAlmostEqual(ev_bb.cvar_sla, 1.0, places=9)

    def test_c_both_safe_expensive(self):
        ev_cc = evaluate_solution(
            self.data, {0: COMB_C, 1: COMB_C}, self.routes,
            beta_sla=self.data.beta_N, beta_sf=self.data.beta_N,
        )
        self.assertAlmostEqual(ev_cc.cvar_sla, 0.0, places=9)
        self.assertAlmostEqual(ev_cc.cvar_sf, 0.0, places=9)
        self.assertAlmostEqual(ev_cc.cost, 0.40, places=9)

    def test_model_a_sla_priority_chooses_AA(self):
        exact, gurobi = _compare_model_a(self.data, lambda_sla=1.0, lambda_sf=0.1)
        self.assertEqual(format_combined_placement(exact.best.placement), "AA")
        self.assertAlmostEqual(exact.best.model_a_objective, 0.10, places=6)

    def test_model_a_sf_priority_chooses_BB(self):
        exact, gurobi = _compare_model_a(self.data, lambda_sla=0.1, lambda_sf=1.0)
        self.assertEqual(format_combined_placement(exact.best.placement), "BB")
        self.assertAlmostEqual(exact.best.model_a_objective, 0.14, places=6)

    def test_model_a_dual_priority_chooses_CC(self):
        exact, gurobi = _compare_model_a(self.data, lambda_sla=1.0, lambda_sf=1.0)
        self.assertEqual(format_combined_placement(exact.best.placement), "CC")
        self.assertAlmostEqual(exact.best.model_a_objective, 0.40, places=6)

    def test_model_a_cost_priority_chooses_AA(self):
        exact, _ = _compare_model_a(self.data, lambda_sla=0.1, lambda_sf=0.1)
        self.assertEqual(format_combined_placement(exact.best.placement), "AA")

    def test_model_c_loose_budget_chooses_AA(self):
        exact, _ = _compare_model_c(self.data, gamma_sla=1.0, gamma_sf=1.0)
        self.assertEqual(format_combined_placement(exact.best.placement), "AA")

    def test_model_c_sla_tight_chooses_AA(self):
        exact, _ = _compare_model_c(self.data, gamma_sla=0.0, gamma_sf=1.0)
        self.assertEqual(format_combined_placement(exact.best.placement), "AA")

    def test_model_c_sf_tight_chooses_BB(self):
        exact, _ = _compare_model_c(self.data, gamma_sla=1.0, gamma_sf=0.0)
        self.assertEqual(format_combined_placement(exact.best.placement), "BB")

    def test_model_c_mixed_budget_chooses_AC_or_CA(self):
        """Γ=0.5/0.5: one task on A (SF=0.5) beats AB (SLA=1.0) under per-task-max SLA."""
        exact, gurobi = _compare_model_c(self.data, gamma_sla=0.5, gamma_sf=0.5)
        _assert_code_in(self, exact.best.placement, {"AC", "CA"})
        _assert_code_in(self, gurobi.placement, {"AC", "CA"})
        self.assertAlmostEqual(exact.best.cost, 0.20, places=6)

    def test_model_c_zero_zero_chooses_CC(self):
        exact, gurobi = _compare_model_c(self.data, gamma_sla=0.0, gamma_sf=0.0)
        self.assertEqual(format_combined_placement(exact.best.placement), "CC")
        self.assertEqual(format_combined_placement(gurobi.placement), "CC")


if __name__ == "__main__":
    unittest.main()
