# -*- coding: utf-8 -*-
"""
Tests for M2-C-Cost and M2-Lex-3 on Toy-2Task-IndependentComponentRisk-v1.
"""
from __future__ import annotations

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from math import isclose
from toy_two_task_independent_data import build_toy_2task_independent_v1
from refactor.m2_cost_models import build_m2_c_cost_model, solve_m2_c_cost, solve_m2_lex3
from refactor.m2_cost_helpers import build_e2e_loss_weights


@pytest.fixture(scope="module")
def data():
    """Build Toy-2Task dataset once per module."""
    return build_toy_2task_independent_v1(scenario_mode="pruned", max_failed_components=3)


# ── test 1: normal full service ──────────────────────────────────────────

def test_normal_full_service(data):
    """z[i, s0] == 1 must be enforced by the model."""
    model = build_m2_c_cost_model(data, gamma=0.2, rho_min_service=0.0)
    result = solve_m2_c_cost(model)
    assert result.status in (2, 13), f"solve failed: status={result.status}"
    for i in data.J:
        assert result.z[(i, 0)] == pytest.approx(1.0), f"z[{i},0]={result.z[(i,0)]}"


# ── test 2: no active service dropping ───────────────────────────────────

def test_no_active_service_dropping(data):
    """z[i, s] must be 1 when all capacities are healthy."""
    model = build_m2_c_cost_model(data, gamma=0.2, rho_min_service=0.0)
    result = solve_m2_c_cost(model)
    for i in data.J:
        for m in data.M:
            if (i, m) in data.valid_assign and result.placement.get((i, m), 0) > 0.5:
                assert result.z[(i, 0)] == pytest.approx(1.0)


# ── test 3: γ monotonicity ──────────────────────────────────────────────

def test_gamma_monotonicity(data):
    """Tighter gamma (smaller → harder) should not give lower cost."""
    gammas = [0.05, 0.15, 0.25]
    costs = []
    for g in gammas:
        model = build_m2_c_cost_model(data, gamma=g, rho_min_service=0.0, quiet=True)
        res = solve_m2_c_cost(model)
        c = res.cost_placement + res.cost_bandwidth_expected
        costs.append(c)
    # Looser gamma → cost should be ≤ tighter gamma
    assert costs[2] <= costs[0] + 1e-6, f"gamma=0.25 cost {costs[2]} > gamma=0.05 cost {costs[0]}"
    assert costs[1] <= costs[0] + 1e-6, f"gamma=0.15 cost {costs[1]} > gamma=0.05 cost {costs[0]}"


# ── test 4: ρ monotonicity ──────────────────────────────────────────────

def test_rho_monotonicity(data):
    """Higher rho (higher service requirement) → cost should not decrease."""
    rhos = [0.0, 0.95, 0.99]
    costs = []
    for rho in rhos:
        model = build_m2_c_cost_model(data, gamma=0.2, rho_min_service=rho, quiet=True)
        res = solve_m2_c_cost(model)
        c = res.cost_placement + res.cost_bandwidth_expected
        costs.append(c)
    assert costs[1] >= costs[0] - 1e-6, f"rho=0.95 cost {costs[1]} < rho=0.0 cost {costs[0]}"
    assert costs[2] >= costs[0] - 1e-6, f"rho=0.99 cost {costs[2]} < rho=0.0 cost {costs[0]}"


# ── test 5: Lex3 pass consistency ───────────────────────────────────────

def test_lex3_pass_consistency(data):
    """Lex3 passes should be non-decreasing in CVaR and non-increasing in cost."""
    p1, p2, p3 = solve_m2_lex3(data, quiet=True)
    assert p1.status == 2 and p2.status == 2 and p3.status == 2, \
        f"Lex3 statuses: {p1.status}, {p2.status}, {p3.status}"

    # P1 has lowest CVaR
    assert p2.cvar_value >= p1.cvar_value - 1e-4, \
        f"P2 CVaR {p2.cvar_value} < P1 CVaR {p1.cvar_value}"
    assert p3.cvar_value >= p1.cvar_value - 1e-4, \
        f"P3 CVaR {p3.cvar_value} < P1 CVaR {p1.cvar_value}"

    # P2 has highest service (given fixed CVaR)
    assert p2.expected_service >= p1.expected_service - 1e-4, \
        f"P2 service {p2.expected_service} < P1 service {p1.expected_service}"

    # P3 has lowest cost (given fixed CVaR + service)
    cost_p1 = p1.cost_placement + p1.cost_bandwidth_expected
    cost_p3 = p3.cost_placement + p3.cost_bandwidth_expected
    assert cost_p3 <= cost_p1 + 1e-6, \
        f"P3 cost {cost_p3} > P1 cost {cost_p1}"


# ── test 6: dropped probability mass reporting ──────────────────────────

def test_dropped_probability_mass(data):
    """The dataset must report dropped probability mass metadata."""
    meta = data.scenario_metadata
    assert "dropped_probability_mass" in meta, "missing dropped_probability_mass"
    assert "original_probability_mass" in meta, "missing original_probability_mass"
    assert meta["dropped_probability_mass"] > 0
    assert meta["original_probability_mass"] < 1.0
    assert meta["renormalized"] is True


# ── test 7: build_e2e_loss_weights default ──────────────────────────────

def test_e2e_loss_weights_default():
    """build_e2e_loss_weights with no args returns equal weights."""
    w = build_e2e_loss_weights([0, 1, 2])
    assert w[0] == pytest.approx(1/3)
    assert w[1] == pytest.approx(1/3)
    assert w[2] == pytest.approx(1/3)


# ── test 8: build_e2e_loss_weights with theta ───────────────────────────

def test_e2e_loss_weights_theta():
    """build_e2e_loss_weights with theta respects weights."""
    w = build_e2e_loss_weights([0, 1], theta={0: 3.0, 1: 1.0})
    assert w[0] == pytest.approx(0.75)
    assert w[1] == pytest.approx(0.25)


# ── test 9: cost structure ──────────────────────────────────────────────

def test_cost_structure(data):
    """Placement cost and bandwidth cost are both nonnegative."""
    model = build_m2_c_cost_model(data, gamma=0.2, rho_min_service=0.0)
    result = solve_m2_c_cost(model)
    assert result.cost_placement >= 0
    assert result.cost_bandwidth_expected >= 0
    total = result.cost_placement + result.cost_bandwidth_expected
    assert abs(result.objective - total) < 1e-4, \
        f"Objective {result.objective} != cost sum {total}"


# ── test 10: all 10 and γ are within [0,1] ──────────────────────────────

def test_cvar_bounds(data):
    """CVaR value and eta should be within [0, 1]."""
    model = build_m2_c_cost_model(data, gamma=0.3, rho_min_service=0.0)
    result = solve_m2_c_cost(model)
    assert 0.0 <= result.cvar_value <= 1.0
    assert 0.0 <= result.eta <= 1.0
