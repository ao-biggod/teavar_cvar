# -*- coding: utf-8 -*-
"""
M2: CVaR-constrained recourse model.

Extends M1 with end-to-end loss L^{E2E}_s and its CVaR:

  L^{E2E}_s = sum_i θ_i · D_i · (1 - z[i,s]) / sum_i θ_i · D_i
  CVaR_α(L^{E2E}) = η + 1/(1-α) · sum_s π_s · u_s
  u_s ≥ L^{E2E}_s - η,  0 ≤ η ≤ 1,  0 ≤ u_s ≤ 1

Modes:
  M2-C:    max expected service  s.t.  CVaR_α(L) ≤ γ
  M2-Lex:  1) min CVaR_α(L),  2) max expected service (with CVaR fixed)
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import gurobipy as gp
from gurobipy import GRB

from duibi_metrics import teavar_flow_anchors
from m0_models import _valid_pairs
from m1_models import build_m1_model, add_m1_max_service_objective


@dataclass
class M2SolveResult:
    status: int
    objective: float
    expected_service: float
    cvar_value: float
    eta: float
    L_s: dict[int, float]
    z: dict[tuple[int, int], float]
    r: dict[tuple[int, int, int], float]
    placement: dict[tuple[int, int], float]
    x_in: dict[tuple[int, int, int, int], float]
    x_out: dict[tuple[int, int, int, int], float]
    model: gp.Model


def _compute_cvar_from_L(
    L_s: dict[int, float],
    prob: dict[int, float],
    alpha: float,
) -> tuple[float, float]:
    """
    Post-hoc CVaR computation from per-scenario loss values.

    Uses the Rockafellar–Uryasev formula directly on the discrete distribution:

        CVaR_α = min_η { η + 1/(1-α) · Σ_s π_s · max(L_s - η, 0) }

    The minimising η* is the α-quantile: η* = inf{η : P(L ≤ η) ≥ α}.
    """
    import numpy as np

    scenarios = sorted(L_s.keys())
    losses = np.array([L_s[s] for s in scenarios], dtype=np.float64)
    probs = np.array([prob[s] for s in scenarios], dtype=np.float64)
    probs = probs / probs.sum()  # normalise (should already sum to 1)

    # Sort by loss
    idx = np.argsort(losses)
    sorted_loss = losses[idx]
    sorted_prob = probs[idx]
    cum_prob = np.cumsum(sorted_prob)

    # α-quantile: smallest η such that P(L ≤ η) ≥ α
    # We use a small epsilon to handle floating-point rounding on cum_prob.
    q_idx = int(np.searchsorted(cum_prob, alpha - 1e-12, side="right"))
    if q_idx >= len(sorted_loss):
        q_idx = len(sorted_loss) - 1
    eta_opt = float(sorted_loss[q_idx])

    # CVaR = η* + 1/(1-α) · Σ π_s · max(L_s - η*, 0)
    excess = 0.0
    for i in range(len(sorted_loss)):
        if sorted_loss[i] > eta_opt:
            excess += sorted_prob[i] * (sorted_loss[i] - eta_opt)
    cvar_val = eta_opt + excess / (1.0 - alpha) if alpha < 1.0 else eta_opt

    return cvar_val, eta_opt


def add_end_to_end_cvar(
    model: gp.Model,
    data,
    z_var: dict[tuple[int, int], gp.Var],
    *,
    alpha: float | None = None,
    theta: dict[int, float] | None = None,
    D_i: dict[int, float] | None = None,
) -> tuple[gp.Var, gp.Var, gp.LinExpr]:
    """
    Add end-to-end loss L^{E2E}_s and its CVaR to an existing M1 model.

    Creates:
      - L_s[s] (end-to-end loss per scenario, aux variable for reporting)
      - η (VaR level, 0 ≤ η ≤ 1)
      - u_s[s] (tail excess, 0 ≤ u_s ≤ 1)
      - cvar_expr (the full CVaR expression)

    Returns (eta, u_s_dict, cvar_expr).
    Users call ``model.addConstr(cvar_expr <= gamma)`` for M2-C.
    """
    if alpha is None:
        alpha = getattr(data, "alpha", 0.8)
    if theta is None:
        theta = getattr(data, "theta", None) or {i: 1.0 for i in data.I}
    if D_i is None:
        D_i = getattr(data, "D_i", None) or {i: 1.0 for i in data.I}

    total_weight = max(sum(theta[i] * D_i[i] for i in data.I), 1e-12)

    # Per-scenario end-to-end loss (reporting only)
    L_s = {}
    for s in data.S:
        loss_expr = gp.quicksum(
            theta[i] * D_i[i] * (1.0 - z_var[i, s])
            for i in data.I
        ) / total_weight
        L_s[s] = loss_expr  # not a variable, just the expression

    # CVaR linearization (Rockafellar-Uryasev)
    eta = model.addVar(lb=0.0, ub=1.0, name="eta_cvar")
    u_s = model.addVars(data.S, lb=0.0, ub=1.0, name="u_cvar")

    for s in data.S:
        loss_expr = gp.quicksum(
            theta[i] * D_i[i] * (1.0 - z_var[i, s])
            for i in data.I
        ) / total_weight
        model.addConstr(
            u_s[s] >= loss_expr - eta,
            name=f"cvar_tail_{s}",
        )

    cvar_expr = eta + (1.0 / (1.0 - float(alpha))) * gp.quicksum(
        data.prob[s] * u_s[s] for s in data.S
    )

    model._m2_eta = eta
    model._m2_u_s = u_s
    model._m2_L_s = L_s
    model._m2_alpha = alpha
    model._m2_total_weight = total_weight
    return eta, u_s, cvar_expr


# ---------------------------------------------------------------------------
# M2-C:  maximize expected service  s.t.  CVaR_α(L) ≤ γ
# ---------------------------------------------------------------------------


def build_m2_model_c(
    data,
    gamma: float,
    *,
    alpha: float | None = None,
    quiet: bool = True,
    time_limit: float | None = None,
    mip_gap: float | None = None,
) -> gp.Model:
    """
    M2-C: Build M1 model + CVaR constraint ``CVaR_α(L) ≤ γ``.

    Objective: maximize expected weighted service (same as M1 max_service).

    Returns the Gurobi model (not yet solved). Call ``solve_m2_model_c()``.
    """
    model = build_m1_model(data, quiet=quiet, time_limit=time_limit, mip_gap=mip_gap)
    z_var = model._m1_z

    eta, u_s, cvar_expr = add_end_to_end_cvar(model, data, z_var, alpha=alpha)

    # CVaR budget constraint
    model.addConstr(cvar_expr <= float(gamma), name="Gamma_CVaR_E2E")

    # Set objective: maximize expected service (reuse M1 helper)
    theta = getattr(data, "theta", None) or {i: 1.0 for i in data.I}
    D_i = getattr(data, "D_i", None) or {i: 1.0 for i in data.I}
    add_m1_max_service_objective(model, data, model._m1_r, z_var)

    model._m2_cvar_expr = cvar_expr
    model._m2_gamma = gamma
    return model


def solve_m2_model_c(model: gp.Model) -> M2SolveResult:
    """Solve M2-C and extract results.

    CVaR is computed *post-hoc* from L_s values, rather than reading the
    solver's ``η`` variable directly.  This is necessary because when
    L_s=0 for all scenarios, ``η`` is a free variable (any value in [0,1]
    satisfies the constraints) and the solver may set it arbitrarily high.
    """
    model.optimize()
    status = int(model.Status)
    data = model._m1_data

    theta = getattr(data, "theta", None) or {i: 1.0 for i in data.I}
    D_i = getattr(data, "D_i", None) or {i: 1.0 for i in data.I}
    total_weight = max(sum(theta[i] * D_i[i] for i in data.I), 1e-12)

    if status not in (GRB.OPTIMAL, GRB.TIME_LIMIT, GRB.SUBOPTIMAL) or model.SolCount == 0:
        return M2SolveResult(
            status=status, objective=float("nan"), expected_service=0.0,
            cvar_value=float("nan"), eta=float("nan"), L_s={},
            z={}, r={}, placement={}, x_in={}, x_out={}, model=model,
        )

    # Extract M0/M1 solution variables from solved model
    y_vals = {(i, m): float(model._m1_y[i, m].X) for i, m in model._m1_y}
    r_vals = {k: float(v.X) for k, v in model._m1_r.items()}
    z_vals = {k: float(v.X) for k, v in model._m1_z.items()}

    # Expected service
    exp_svc = sum(data.prob[s] * sum(theta[i] * D_i[i] * z_vals.get((i, s), 0.0)
                                      for i in data.I) for s in data.S)

    # Post-hoc CVaR from L_s values (correct even when η is arbitrary)
    L_vals: dict[int, float] = {}
    for s in data.S:
        loss_val = sum(theta[i] * D_i[i] * (1.0 - z_vals.get((i, s), 0.0))
                       for i in data.I) / total_weight
        L_vals[s] = loss_val

    alpha = getattr(data, "alpha", 0.8)
    cvar_val, eta_opt = _compute_cvar_from_L(L_vals, data.prob, alpha)
    eta_var = float(model._m2_eta.X)

    # Flow variables
    x_in_vals = {k: float(v.X) for k, v in model._m1_xin_s.items()}
    x_out_vals = {k: float(v.X) for k, v in model._m1_xout_s.items()}

    return M2SolveResult(
        status=status,
        objective=float(model.ObjVal),
        expected_service=exp_svc,
        cvar_value=cvar_val,
        eta=eta_opt,          # post-hoc optimal η, not solver's free variable
        L_s=L_vals,
        z=z_vals,
        r=r_vals,
        placement=y_vals,
        x_in=x_in_vals,
        x_out=x_out_vals,
        model=model,
    )


# ---------------------------------------------------------------------------
# M2-Lex: lexicographic — 1) minimise CVaR  2) maximise expected service
# ---------------------------------------------------------------------------


def build_m2_lex(
    data,
    *,
    alpha: float | None = None,
    quiet: bool = True,
    time_limit: float | None = None,
    mip_gap: float | None = None,
) -> None:
    """
    M2-Lex is solved in two passes via ``solve_m2_lex()``.

    This function is a no-op (all setup happens in solve_m2_lex).
    """
    pass


def solve_m2_lex(
    data,
    *,
    alpha: float | None = None,
    quiet: bool = True,
    time_limit: float | None = None,
    mip_gap: float | None = None,
) -> tuple[M2SolveResult, M2SolveResult | None]:
    """
    Two-pass lexicographic solve:

    Pass 1: build M1 + CVaR, minimise CVaR (no gamma budget).
    Pass 2: fix CVaR at Pass 1 optimum, maximise expected service.

    Returns (pass1_result, pass2_result). Pass 2 is None if Pass 1 failed.
    """
    # --- Pass 1: minimise CVaR ---
    model1 = build_m1_model(data, quiet=quiet, time_limit=time_limit, mip_gap=mip_gap)
    z_var1 = model1._m1_z

    eta1, u_s1, cvar_expr1 = add_end_to_end_cvar(model1, data, z_var1, alpha=alpha)
    model1.setObjective(cvar_expr1, GRB.MINIMIZE)

    model1.optimize()
    status1 = int(model1.Status)
    cvar_opt = float(cvar_expr1.getValue()) if status1 == GRB.OPTIMAL else float("nan")

    p1 = _extract_m2_from_model(model1, data, status1, cvar_expr1)

    if status1 != GRB.OPTIMAL:
        return p1, None

    # --- Pass 2: fix CVaR at optimal, maximise expected service ---
    model2 = build_m1_model(data, quiet=quiet, time_limit=time_limit, mip_gap=mip_gap)
    z_var2 = model2._m1_z

    eta2, u_s2, cvar_expr2 = add_end_to_end_cvar(model2, data, z_var2, alpha=alpha)
    # Fix CVaR ≤ Pass-1 optimum + small tolerance
    tol = max(1e-4, cvar_opt * 0.001)
    model2.addConstr(cvar_expr2 <= cvar_opt + tol, name="Gamma_CVaR_E2E_lex_fixed")

    # Maximise expected service as secondary objective
    add_m1_max_service_objective(model2, data, model2._m1_r, z_var2)

    model2.optimize()
    status2 = int(model2.Status)

    p2 = _extract_m2_from_model(model2, data, status2, cvar_expr2) if status2 == GRB.OPTIMAL else None
    return p1, p2


def _extract_m2_from_model(
    model: gp.Model,
    data,
    status: int,
    cvar_expr,
) -> M2SolveResult:
    """Helper: extract M2SolveResult from an optimised model.

    Uses direct variable .X access + post-hoc CVaR computation.
    """
    if status not in (GRB.OPTIMAL, GRB.TIME_LIMIT, GRB.SUBOPTIMAL) or model.SolCount == 0:
        return M2SolveResult(
            status=status, objective=float("nan"), expected_service=0.0,
            cvar_value=float("nan"), eta=float("nan"), L_s={},
            z={}, r={}, placement={}, x_in={}, x_out={}, model=model,
        )

    y_vals = {(i, m): float(model._m1_y[i, m].X) for i, m in model._m1_y}
    r_vals = {k: float(v.X) for k, v in model._m1_r.items()}
    z_vals = {k: float(v.X) for k, v in model._m1_z.items()}
    x_in_vals = {k: float(v.X) for k, v in model._m1_xin_s.items()}
    x_out_vals = {k: float(v.X) for k, v in model._m1_xout_s.items()}

    theta = getattr(data, "theta", None) or {i: 1.0 for i in data.I}
    D_i = getattr(data, "D_i", None) or {i: 1.0 for i in data.I}
    total_weight = max(sum(theta[i] * D_i[i] for i in data.I), 1e-12)

    exp_svc = sum(data.prob[s] * sum(theta[i] * D_i[i] * z_vals.get((i, s), 0.0)
                                      for i in data.I) for s in data.S)

    L_vals: dict[int, float] = {}
    for s in data.S:
        L_vals[s] = sum(theta[i] * D_i[i] * (1.0 - z_vals.get((i, s), 0.0))
                        for i in data.I) / total_weight

    alpha = getattr(data, "alpha", 0.8)
    cvar_val, eta_opt = _compute_cvar_from_L(L_vals, data.prob, alpha)

    return M2SolveResult(
        status=status,
        objective=float(model.ObjVal),
        expected_service=exp_svc,
        cvar_value=cvar_val,
        eta=eta_opt,
        L_s=L_vals,
        z=z_vals,
        r=r_vals,
        placement=y_vals,
        x_in=x_in_vals,
        x_out=x_out_vals,
        model=model,
    )
