# -*- coding: utf-8 -*-
"""
M2-C-Cost:  cost minimisation + single CVaR constraint + service guarantees.
M2-Lex-3:  three-pass lexicographic (CVaR → service → cost).

Builds on top of M1's scenario recourse model.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import sys, os
# Ensure refactor/ is treated as a package
_refactor_dir = os.path.dirname(os.path.abspath(__file__))
if _refactor_dir not in sys.path:
    sys.path.insert(0, _refactor_dir)
_parent = os.path.dirname(_refactor_dir)
if _parent not in sys.path:
    sys.path.insert(0, _parent)

import gurobipy as gp
from gurobipy import GRB

from m1_models import build_m1_model
from m2_cost_helpers import (
    build_e2e_loss_weights,
    add_e2e_loss_constraints,
    add_cvar_ru_constraints,
    compute_placement_cost,
    compute_scenario_bandwidth_cost,
)


# ---------------------------------------------------------------------------
# Post-hoc CVaR computation (no Gurobi dependency)
# ---------------------------------------------------------------------------

def _posthoc_cvar_from_L(
    L_dict: dict[int, float],
    pi: dict[int, float],
    beta: float,
) -> tuple[float, float]:
    """Compute CVaR and VaR from scenario loss dict + probabilities."""
    import math
    scenarios = list(L_dict.keys())
    sorted_s = sorted(scenarios, key=lambda s: L_dict[s])
    cum_prob = 0.0
    var_alpha = 0.0
    for s in sorted_s:
        cum_prob += pi[s]
        if cum_prob >= beta:
            var_alpha = L_dict[s]
            break
    # CVaR = expected loss in tail (loss > VaR)
    tail_prob = 0.0
    tail_sum = 0.0
    for s in scenarios:
        if L_dict[s] >= var_alpha - 1e-12:
            tail_prob += pi[s]
            tail_sum += pi[s] * L_dict[s]
    cvar = tail_sum / tail_prob if tail_prob > 0 else 0.0
    return cvar, var_alpha


@dataclass
class M2CostResult:
    """Result of an M2-C-Cost or M2-Lex-3 solve."""

    status: int
    objective: float
    cost_placement: float
    cost_bandwidth_expected: float
    cvar_value: float
    eta: float
    expected_service: float
    L_s: dict[int, float]
    z: dict[tuple[int, int], float]
    r: dict[tuple[int, int, int], float]
    placement: dict[tuple[int, int], float]
    model: gp.Model | None = None
    pass_label: str = ""


def _extract_m2_cost_result(
    model: gp.Model, data, *, pass_label: str = ""
) -> M2CostResult:
    """Extract results from a solved M2 cost model."""
    status = int(model.Status)
    id_set = list(getattr(data, "I", getattr(data, "J", [])))
    valid_set = getattr(data, "valid_assign", set())
    pi = getattr(data, "prob", getattr(data, "pi", {}))
    beta = getattr(data, "beta_cvar", 0.8)
    omega = build_e2e_loss_weights(id_set, theta=getattr(data, "theta", None))

    if status not in (GRB.OPTIMAL, GRB.TIME_LIMIT, GRB.SUBOPTIMAL) or model.SolCount == 0:
        return M2CostResult(
            status=status, objective=float("nan"),
            cost_placement=float("nan"), cost_bandwidth_expected=float("nan"),
            cvar_value=float("nan"), eta=float("nan"),
            expected_service=0.0, L_s={}, z={}, r={}, placement={}, model=model,
            pass_label=pass_label,
        )

    # Placement
    y_vals = {}
    cost_p = 0.0
    rho_comp = getattr(data, "rho_compute", {})
    for i in id_set:
        for m in data.M:
            if (i, m) in model._m1_y:
                val = float(model._m1_y[i, m].X)
                y_vals[i, m] = val
                if val > 0.5:
                    rc = sum(float(data.w[i][k]) * float(rho_comp.get(m, {}).get(k, 0.0)) for k in data.K)
                    cost_p += rc

    # Service ratios
    r_vals = {k: float(v.X) for k, v in model._m1_r.items()}
    z_vals = {k: float(v.X) for k, v in model._m1_z.items()}

    # Bandwidth cost
    xin_all = {k: float(v.X) for k, v in model._m1_xin_s.items()}
    xout_all = {k: float(v.X) for k, v in model._m1_xout_s.items()}
    rho_link = getattr(data, "rho_link", {})

    cost_b_exp = 0.0
    for s in data.S:
        cost_b_s = 0.0
        for e in data.E:
            e0, e1 = int(e[0]), int(e[1])
            rho = float(rho_link.get(e, 0.0))
            if rho == 0.0:
                continue
            load = 0.0
            for i in id_set:
                src = data.task_src[i]
                dst = data.task_dst[i]
                for m in data.M:
                    if (i, m) not in valid_set:
                        continue
                    for p, path in enumerate(data.P_in.get((src, m), [])):
                        if any(e0 == int(a) and e1 == int(b) for a, b in path):
                            load += xin_all.get((i, m, p, s), 0.0)
                    for q, path in enumerate(data.P_out.get((m, dst), [])):
                        if any(e0 == int(a) and e1 == int(b) for a, b in path):
                            load += xout_all.get((i, m, q, s), 0.0)
            cost_b_s += rho * load
        cost_b_exp += pi[s] * cost_b_s

    # Service and loss
    exp_svc = sum(pi[s] * sum(omega[i] * z_vals.get((i, s), 0.0) for i in id_set) for s in data.S)
    L_vals = {}
    for s in data.S:
        L_vals[s] = sum(omega[i] * (1.0 - z_vals.get((i, s), 0.0)) for i in id_set)

    # Post-hoc CVaR
    cvar_val, eta_opt = _posthoc_cvar_from_L(L_vals, pi, beta)

    return M2CostResult(
        status=status, objective=float(model.ObjVal),
        cost_placement=cost_p, cost_bandwidth_expected=cost_b_exp,
        cvar_value=cvar_val, eta=eta_opt,
        expected_service=exp_svc, L_s=L_vals,
        z=z_vals, r=r_vals, placement=y_vals, model=model,
        pass_label=pass_label,
    )


# ---------------------------------------------------------------------------
# M2-C-Cost
# ---------------------------------------------------------------------------

def build_m2_c_cost_model(
    data,
    gamma: float,
    *,
    rho_min_service: float | None = None,
    theta: dict[int, float] | None = None,
    omega: dict[int, float] | None = None,
    quiet: bool = True,
    time_limit: float | None = None,
    mip_gap: float | None = None,
) -> gp.Model:
    """
    Build M2-C-Cost MILP.

    Objective: ``min c_p + E[c_b(x_s)]``

    Constraints:
      - M1 scenario recourse (build_m1_model)
      - CVaR_β(L^{E2E}) ≤ gamma
      - z[i, s0] = 1  (normal scenario full service)
      - E[z] ≥ rho_min_service  (optional expected service floor)

    Returns the model (not solved).  Call ``solve_m2_c_cost()``.
    """
    model = build_m1_model(data, quiet=quiet, time_limit=time_limit, mip_gap=mip_gap)
    z_var = model._m1_z

    # End-to-end loss
    L_expr = add_e2e_loss_constraints(model, data, z_var, theta=theta, omega=omega)

    # CVaR + budget constraint
    eta, u, cvar_expr = add_cvar_ru_constraints(model, data, L_expr)
    model.addConstr(cvar_expr <= float(gamma), name="Gamma_CVaR_E2E")

    # Normal scenario full service (s0 = first scenario)
    s0 = data.S[0]
    for i in getattr(data, "I", getattr(data, "J", [])):
        model.addConstr(z_var[i, s0] == 1.0, name=f"full_service_normal_{i}")

    # Expected service floor
    if rho_min_service is not None and rho_min_service > 0.0:
        pi = getattr(data, "prob", getattr(data, "pi", {}))
        for i in getattr(data, "I", getattr(data, "J", [])):
            exp_z = gp.quicksum(pi[s] * z_var[i, s] for s in data.S)
            model.addConstr(exp_z >= float(rho_min_service), name=f"exp_service_floor_{i}")

    # Cost objective
    cost_p = compute_placement_cost(model, data, model._m1_y)
    pi = getattr(data, "prob", getattr(data, "pi", {}))
    cost_b_exp = gp.quicksum(
        pi[s] * compute_scenario_bandwidth_cost(model, data, model._m1_xin_s, model._m1_xout_s, s)
        for s in data.S
    )
    model.setObjective(cost_p + cost_b_exp, GRB.MINIMIZE)

    model._m2_cost_cvar_expr = cvar_expr
    model._m2_cost_eta = eta
    return model


def solve_m2_c_cost(model: gp.Model) -> M2CostResult:
    """Solve M2-C-Cost and extract results."""
    model.optimize()
    data = model._m1_data
    return _extract_m2_cost_result(model, data, pass_label="M2-C-Cost")


# ---------------------------------------------------------------------------
# M2-Lex-3
# ---------------------------------------------------------------------------

def solve_m2_lex3(
    data,
    *,
    theta: dict[int, float] | None = None,
    omega: dict[int, float] | None = None,
    quiet: bool = True,
    time_limit: float | None = None,
    mip_gap: float | None = None,
    cvar_tol: float = 1e-4,
    svc_tol: float = 1e-4,
) -> tuple[M2CostResult, M2CostResult, M2CostResult]:
    """
    Three-pass lexicographic optimisation.

    Pass 1: minimise CVaR_β(L^{E2E})
    Pass 2: maximise expected service (CVaR fixed at Pass-1 optimum)
    Pass 3: minimise cost (CVaR + service fixed at Pass-1/Pass-2 optimum)

    Returns ``(p1, p2, p3)``.
    """
    id_set = list(getattr(data, "I", getattr(data, "J", [])))
    if omega is None:
        omega = build_e2e_loss_weights(id_set, theta=theta)
    pi = getattr(data, "prob", getattr(data, "pi", {}))

    # ---- Pass 1: min CVaR ----
    m1 = build_m1_model(data, quiet=quiet, time_limit=time_limit, mip_gap=mip_gap)
    L1 = add_e2e_loss_constraints(m1, data, m1._m1_z, omega=omega)
    eta1, u1, cvar1 = add_cvar_ru_constraints(m1, data, L1)
    m1.setObjective(cvar1, GRB.MINIMIZE)
    m1.optimize()
    p1 = _extract_m2_cost_result(m1, data, pass_label="Lex3-P1")
    if p1.status != 2:
        empty = M2CostResult(status=3, objective=float("nan"),
                             cost_placement=float("nan"), cost_bandwidth_expected=float("nan"),
                             cvar_value=float("nan"), eta=float("nan"),
                             expected_service=0.0, L_s={}, z={}, r={}, placement={})
        return p1, empty, empty

    cvar_opt = p1.cvar_value

    # ---- Pass 2: max service (CVaR fixed) ----
    m2 = build_m1_model(data, quiet=quiet, time_limit=time_limit, mip_gap=mip_gap)
    L2 = add_e2e_loss_constraints(m2, data, m2._m1_z, omega=omega)
    eta2, u2, cvar2 = add_cvar_ru_constraints(m2, data, L2)
    m2.addConstr(cvar2 <= cvar_opt + cvar_tol, name="Lex3_CVaR_fixed")
    svc_expr = gp.quicksum(
        pi[s] * gp.quicksum(omega[i] * m2._m1_z[i, s] for i in id_set)
        for s in data.S
    )
    m2.setObjective(svc_expr, GRB.MAXIMIZE)
    m2.optimize()
    p2 = _extract_m2_cost_result(m2, data, pass_label="Lex3-P2")
    if p2.status != 2:
        empty = M2CostResult(status=3, objective=float("nan"),
                             cost_placement=float("nan"), cost_bandwidth_expected=float("nan"),
                             cvar_value=float("nan"), eta=float("nan"),
                             expected_service=0.0, L_s={}, z={}, r={}, placement={})
        return p1, p2, empty

    svc_opt = p2.expected_service

    # ---- Pass 3: min cost (CVaR + service fixed) ----
    m3 = build_m1_model(data, quiet=quiet, time_limit=time_limit, mip_gap=mip_gap)
    L3 = add_e2e_loss_constraints(m3, data, m3._m1_z, omega=omega)
    eta3, u3, cvar3 = add_cvar_ru_constraints(m3, data, L3)
    m3.addConstr(cvar3 <= cvar_opt + cvar_tol, name="Lex3_CVaR_fixed")
    svc_expr3 = gp.quicksum(
        pi[s] * gp.quicksum(omega[i] * m3._m1_z[i, s] for i in id_set)
        for s in data.S
    )
    m3.addConstr(svc_expr3 >= svc_opt - svc_tol, name="Lex3_svc_fixed")
    cost_p3 = compute_placement_cost(m3, data, m3._m1_y)
    cost_b3 = gp.quicksum(
        pi[s] * compute_scenario_bandwidth_cost(m3, data, m3._m1_xin_s, m3._m1_xout_s, s)
        for s in data.S
    )
    m3.setObjective(cost_p3 + cost_b3, GRB.MINIMIZE)
    m3.optimize()
    p3 = _extract_m2_cost_result(m3, data, pass_label="Lex3-P3")

    return p1, p2, p3
