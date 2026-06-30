# -*- coding: utf-8 -*-
"""
Shared helpers for M2-C-Cost and M2-Lex-3.

Pure Gurobi-agnostic weight computation + Gurobi constraint builders.
"""
from __future__ import annotations

from typing import Any

import gurobipy as gp
from gurobipy import GRB


# ---------------------------------------------------------------------------
# Pure data helper (no Gurobi dependency)
# ---------------------------------------------------------------------------

def build_e2e_loss_weights(
    task_ids: list[int],
    theta: dict[int, float] | None = None,
    demand: dict[int, float] | None = None,
    eps: float = 1e-12,
) -> dict[int, float]:
    """
    Build normalised, scenario-independent task weights.

    Returns ``omega_i = theta_i * D_i / sum_j (theta_j * D_j)``.

    Default: theta_i = 1, D_i = 1 → omega_i = 1 / |I|.
    """
    task_ids = list(task_ids)
    theta_v = {i: 1.0 for i in task_ids} if theta is None else {i: float(theta[i]) for i in task_ids}
    demand_v = {i: 1.0 for i in task_ids} if demand is None else {i: float(demand[i]) for i in task_ids}

    raw = {}
    for i in task_ids:
        if theta_v[i] < 0:
            raise ValueError(f"theta[{i}] must be nonnegative")
        if demand_v[i] < 0:
            raise ValueError(f"demand[{i}] must be nonnegative")
        raw[i] = theta_v[i] * demand_v[i]

    denom = sum(raw.values())
    if denom <= eps:
        raise ValueError("Total E2E loss weight must be positive")
    return {i: raw[i] / denom for i in task_ids}


# ---------------------------------------------------------------------------
# Gurobi constraint builders
# ---------------------------------------------------------------------------


def add_e2e_loss_constraints(
    model: gp.Model,
    data,
    z_var: dict[tuple[int, int], gp.Var],
    *,
    theta: dict[int, float] | None = None,
    omega: dict[int, float] | None = None,
) -> dict[int, gp.LinExpr]:
    """
    Add end-to-end loss expressions ``L_s = sum_i omega_i * (1 - z[i,s])``.

    Returns ``L`` dict (scenario -> LinExpr).  The expressions are NOT auxiliary
    variables — they are linear expressions that can be used directly in
    constraints or the objective.

    If ``omega`` is provided it takes precedence; otherwise built from ``theta``
    via ``build_e2e_loss_weights()``.
    """
    if omega is None:
        omega = build_e2e_loss_weights(data.J, theta=theta)

    L: dict[int, gp.LinExpr] = {}
    for s in data.S:
        expr = gp.LinExpr()
        for i in data.J:
            expr += omega[i] * (1.0 - z_var[i, s])
        L[s] = expr
    return L


def add_cvar_ru_constraints(
    model: gp.Model,
    data,
    L_expr: dict[int, gp.LinExpr],
    *,
    alpha_ub: float = 1.0,
    u_ub: float = 1.0,
) -> tuple[gp.Var, dict[int, gp.Var], gp.LinExpr]:
    """
    Rockafellar-Uryasev CVaR linearisation.

    ``L_expr[s]`` is the per-scenario loss expression (LinExpr, not Var).

    Creates:
      - ``eta`` (VaR threshold, 0 <= eta <= alpha_ub)
      - ``u[s]`` (tail excess, 0 <= u[s] <= u_ub)
      - ``cvar_expr = eta + 1/(1-beta) * sum_s pi[s] * u[s]``

    Returns ``(eta, u_dict, cvar_expr)``.
    """
    beta = getattr(data, "beta_cvar", 0.8)
    pi = getattr(data, "prob", getattr(data, "pi", {}))
    eta = model.addVar(lb=0.0, ub=alpha_ub, name="eta_cvar")
    u: dict[int, gp.Var] = {}
    for s in data.S:
        u[s] = model.addVar(lb=0.0, ub=u_ub, name=f"u_cvar_{s}")
        model.addConstr(u[s] >= L_expr[s] - eta, name=f"cvar_tail_{s}")

    cvar_expr = eta + (1.0 / (1.0 - beta)) * gp.quicksum(
        pi[s] * u[s] for s in data.S
    )
    return eta, u, cvar_expr


def compute_placement_cost(
    model: gp.Model,
    data,
    y_var: dict[tuple[int, int], gp.Var],
) -> gp.LinExpr:
    """Placement cost: c_p = sum_{i,m} y[i,m] * sum_k w[i][k] * rho_{m,k}."""
    expr = gp.LinExpr()
    id_set = getattr(data, "I", getattr(data, "J", []))
    k_set = getattr(data, "K", [])
    valid_set = getattr(data, "valid_assign", set())
    rho_comp = getattr(data, "rho_compute", {})
    for i in id_set:
        for m in getattr(data, "M", []):
            if (i, m) not in valid_set:
                continue
            if m not in rho_comp:
                continue
            resource_cost = sum(
                float(data.w[i][k]) * float(rho_comp[m].get(k, 0.0))
                for k in k_set
            )
            expr += y_var[i, m] * resource_cost
    return expr


def compute_scenario_bandwidth_cost(
    model: gp.Model,
    data,
    xin_s: dict[tuple[int, int, int, int], gp.Var],
    xout_s: dict[tuple[int, int, int, int], gp.Var],
    s: int,
) -> gp.LinExpr:
    """Scenario bandwidth cost: sum_e rho_link[e] * LinkLoad_{e,s}."""
    id_set = getattr(data, "I", getattr(data, "J", []))
    valid_set = getattr(data, "valid_assign", set())
    rho_link = getattr(data, "rho_link", {})

    expr = gp.LinExpr()
    for e in data.E:
        e0, e1 = int(e[0]), int(e[1])
        rho = float(rho_link.get(e, 0.0))
        if rho == 0.0:
            continue

        load = gp.LinExpr()
        for i in id_set:
            src = data.task_src[i]
            dst = data.task_dst[i]
            for m in data.M:
                if (i, m) not in valid_set:
                    continue
                # Ingress paths
                for p, path in enumerate(data.P_in.get((src, m), [])):
                    if any(e0 == int(a) and e1 == int(b) for a, b in path):
                        key = (i, m, p, s)
                        if key in xin_s:
                            load += xin_s[key]
                # Egress paths
                for q, path in enumerate(data.P_out.get((m, dst), [])):
                    if any(e0 == int(a) and e1 == int(b) for a, b in path):
                        key = (i, m, q, s)
                        if key in xout_s:
                            load += xout_s[key]
        expr += rho * load
    return expr
