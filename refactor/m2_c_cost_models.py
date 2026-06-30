# -*- coding: utf-8 -*-
"""
M2-C-Cost Adaptive:  minimise deployment + expected bandwidth cost
                      subject to  CVaR_beta(L) ≤ gamma  &  service floor.

recourse_mode = "adaptive" (only mode for now).
loss_mode     = "mean"     (only mode for now).
cost_mode     = "usage"    (expected scenario bandwidth cost).

No nominal flow x^0 — every scenario adapts independently.
"""
from __future__ import annotations

import sys, os
# Ensure refactor/ and project root are on sys.path for sibling imports
_refactor_dir = os.path.dirname(os.path.abspath(__file__))
if _refactor_dir not in sys.path:
    sys.path.insert(0, _refactor_dir)
_parent = os.path.dirname(_refactor_dir)
if _parent not in sys.path:
    sys.path.insert(0, _parent)

from dataclasses import dataclass, field
from typing import Any, Optional

import gurobipy as gp
from gurobipy import GRB

from duibi_metrics import teavar_flow_anchors
from m0_models import _valid_pairs, _path_edges
from m2_models import _compute_cvar_from_L


# ---------------------------------------------------------------------------
# Solve result
# ---------------------------------------------------------------------------

@dataclass
class M2CCostSolveResult:
    status: int
    objective: float
    deployment_cost: float
    bandwidth_cost: float
    expected_service: float
    cvar_value: float
    eta: float
    L_s: dict[int, float]
    z: dict[tuple[int, int], float]
    r: dict[tuple[int, int, int], float]
    placement: dict[tuple[int, int], float]
    x_in: dict[tuple[int, int, int, int], float]
    x_out: dict[tuple[int, int, int, int], float]
    gamma: float
    beta: float
    metadata: dict = field(default_factory=dict)
    model: Optional[gp.Model] = None


# ---------------------------------------------------------------------------
# Scenario link-load helper (reused from m1_models)
# ---------------------------------------------------------------------------

def _scenario_link_load_per_edge(
    data,
    xin_s: dict,
    xout_s: dict,
    e: tuple[int, int],
) -> gp.LinExpr:
    """Aggregate flow on directed edge *e* for a single scenario."""
    e0, e1 = int(e[0]), int(e[1])
    expr = gp.LinExpr()
    for i in data.I:
        src, dst = teavar_flow_anchors(data, i)
        for m in data.M:
            if (i, m) not in set(_valid_pairs(data)):
                continue
            in_paths = data.P_cand.get((src, m), [])
            for p, path in enumerate(in_paths):
                if (e0, e1) in _path_edges(path):
                    key = (i, m, p)
                    if key in xin_s:
                        expr += xin_s[key]
            out_paths = data.P_cand.get((m, dst), [])
            for q, path in enumerate(out_paths):
                if (e0, e1) in _path_edges(path):
                    key = (i, m, q)
                    if key in xout_s:
                        expr += xout_s[key]
    return expr


# ---------------------------------------------------------------------------
# M2-C-Cost builder
# ---------------------------------------------------------------------------

def build_m2_c_cost_adaptive(
    data,
    gamma: float,
    *,
    beta: float = 0.8,
    loss_mode: str = "mean",
    service_floor: Optional[dict[int, float]] = None,
    deployment_cost: Optional[dict[int, dict[int, float]]] = None,
    bandwidth_cost: Optional[dict[tuple[int, int], float]] = None,
    quiet: bool = True,
    time_limit: Optional[float] = None,
    mip_gap: Optional[float] = None,
) -> gp.Model:
    """
    Build M2-C-Cost Adaptive MILP.

    Minimises deployment cost + expected scenario bandwidth cost, subject to:

      1. Unique placement.
      2. Scenario recourse (r, z, x_in_s, x_out_s).
      3. Normal scenario full service: ``z[i, s0] = 1``.
      4. Expected service floor: ``E[z[i]] >= service_floor[i]``.
      5. Scenario link capacity.
      6. Scenario compute capacity.
      7. E2E loss L_s  &  CVaR_beta(L) ≤ gamma.

    Parameters
    ----------
    data :
        Must have ``I, M, K, E, S, prob, B, sigma, C_s, task_src, task_dst,
        P_cand, valid_assign, b_in, b_out, w``.
        Optional: ``theta`` (task importance, default 1.0).
    gamma : float
        CVaR budget.
    beta : float (default 0.8)
        CVaR confidence level.
    loss_mode : str (default "mean")
        Only ``"mean"`` supported in this version.
    service_floor : dict[int, float] or None
        ``service_floor[i]`` = minimum expected service per task.
        If None, defaults to ``{i: 0.95 for i in data.I}``.
    deployment_cost : dict[int, dict[int, float]] or None
        ``deployment_cost[m][k]`` = cost per unit of resource *k* on node *m*.
        If None, uses ``data.rho_compute``.
    bandwidth_cost : dict[tuple[int,int], float] or None
        ``bandwidth_cost[e]`` = cost per unit flow on edge *e*.
        If None, uses ``data.rho_link`` (default 1.0).
    """
    if loss_mode != "mean":
        raise ValueError(f"loss_mode={loss_mode!r} not supported; use 'mean'")

    model = gp.Model("M2_C_Cost_adaptive")
    if quiet:
        model.setParam("OutputFlag", 0)
    if time_limit is not None:
        model.setParam("TimeLimit", float(time_limit))
    if mip_gap is not None:
        model.setParam("MIPGap", float(mip_gap))

    pairs = _valid_pairs(data)
    pair_set = set(pairs)

    # Default costs
    _dep_cost = deployment_cost if deployment_cost is not None else (
        getattr(data, "rho_compute", {})
    )
    _bw_cost = bandwidth_cost if bandwidth_cost is not None else (
        getattr(data, "rho_link", {e: 1.0 for e in data.E})
    )

    # Default service floor
    # NOTE: 0.90 is a practical default for aggregate_worst pruning (which
    # drops ~2 % probability mass into a zero-capacity tail scenario).
    # With aggregate_worst, max feasible floor is ~0.98 but cost optimisation
    # may push it lower; 0.90 gives the model room to trade off cost vs
    # service without being trivially infeasible.
    _floor = service_floor
    if _floor is None:
        _floor = {i: 0.90 for i in data.I}

    theta = getattr(data, "theta", None) or {i: 1.0 for i in data.I}
    total_weight = max(sum(theta[i] for i in data.I), 1e-12)

    # ---- Stage 1: placement (here-and-now) ----
    y = model.addVars(pairs, vtype=GRB.BINARY, name="y")
    for i in data.I:
        model.addConstr(
            gp.quicksum(y[i, cn] for cn in data.M if (i, cn) in pair_set) == 1,
            name=f"place_{i}",
        )

    # ---- Stage 2: recourse (wait-and-see) ----
    r_var: dict[tuple[int, int, int], gp.Var] = {}
    z_var: dict[tuple[int, int], gp.Var] = {}
    xin_s: dict[tuple[int, int, int, int], gp.Var] = {}
    xout_s: dict[tuple[int, int, int, int], gp.Var] = {}

    normal_s = data.S[0]  # first scenario = zero failures

    for s in data.S:
        for i in data.I:
            src_i, dst_i = teavar_flow_anchors(data, i)
            for cn in data.M:
                if (i, cn) not in pair_set:
                    continue

                # r[i, cn, s] ∈ [0, y[i,cn]]
                r_var[i, cn, s] = model.addVar(lb=0.0, ub=1.0, name=f"r_{i}_{cn}_{s}")
                model.addConstr(
                    r_var[i, cn, s] <= y[i, cn],
                    name=f"r_le_y_{i}_{cn}_{s}",
                )

                # Scenario ingress / egress routing
                in_paths = data.P_cand.get((src_i, cn), [])
                for p in range(len(in_paths)):
                    xin_s[i, cn, p, s] = model.addVar(
                        lb=0.0, name=f"xin_s_{i}_{cn}_{p}_{s}"
                    )
                out_paths = data.P_cand.get((cn, dst_i), [])
                for q in range(len(out_paths)):
                    xout_s[i, cn, q, s] = model.addVar(
                        lb=0.0, name=f"xout_s_{i}_{cn}_{q}_{s}"
                    )

                # Flow conservation (equality)
                model.addConstr(
                    gp.quicksum(xin_s[i, cn, p, s] for p in range(len(in_paths)))
                    == float(data.b_in[i]) * r_var[i, cn, s],
                    name=f"flow_in_s_{i}_{cn}_{s}",
                )
                model.addConstr(
                    gp.quicksum(xout_s[i, cn, q, s] for q in range(len(out_paths)))
                    == float(data.b_out[i]) * r_var[i, cn, s],
                    name=f"flow_out_s_{i}_{cn}_{s}",
                )

            # z[i, s] = sum_m r[i, cn, s]
            z_var[i, s] = model.addVar(lb=0.0, ub=1.0, name=f"z_{i}_{s}")
            model.addConstr(
                z_var[i, s] == gp.quicksum(
                    r_var[i, cn, s] for cn in data.M if (i, cn) in pair_set
                ),
                name=f"z_def_{i}_{s}",
            )

    # ---- (R1) Normal scenario full service ----
    for i in data.I:
        model.addConstr(z_var[i, normal_s] == 1.0, name=f"z_full_nominal_{i}")

    # ---- (R2) Expected service floor ----
    for i in data.I:
        floor_val = float(_floor[i])
        exp_z = gp.quicksum(data.prob[s] * z_var[i, s] for s in data.S)
        model.addConstr(exp_z >= floor_val, name=f"svc_floor_{i}")

    # ---- Scenario link capacity ----
    for s in data.S:
        xin_this_s = {
            (i, cn, p): xin_s[i, cn, p, s]
            for i in data.I for cn in data.M if (i, cn) in pair_set
            for p in range(len(data.P_cand.get((teavar_flow_anchors(data, i)[0], cn), [])))
            if (i, cn, p, s) in xin_s
        }
        xout_this_s = {
            (i, cn, q): xout_s[i, cn, q, s]
            for i in data.I for cn in data.M if (i, cn) in pair_set
            for q in range(len(data.P_cand.get((cn, teavar_flow_anchors(data, i)[1]), [])))
            if (i, cn, q, s) in xout_s
        }
        for e in data.E:
            cap_eff = float(data.B[e]) * float(data.sigma[e][s])
            load_e = _scenario_link_load_per_edge(data, xin_this_s, xout_this_s, e)
            model.addConstr(load_e <= cap_eff, name=f"link_cap_s_{e[0]}_{e[1]}_{s}")

    # ---- Scenario compute capacity ----
    for s in data.S:
        for cn in data.M:
            for k in data.K:
                cap = float(data.C_s[cn][k][s])
                demand = gp.quicksum(
                    r_var[i, cn, s] * float(data.w[i][k])
                    for i in data.I if (i, cn) in pair_set
                )
                model.addConstr(demand <= cap, name=f"comp_cap_s_{cn}_{k}_{s}")

    # ---- E2E loss L_s + CVaR ----
    L_s_expr: dict[int, gp.LinExpr] = {}
    for s in data.S:
        loss_expr = gp.quicksum(
            theta[i] * (1.0 - z_var[i, s]) for i in data.I
        ) / total_weight
        L_s_expr[s] = loss_expr

    eta = model.addVar(lb=0.0, ub=1.0, name="eta_cvar")
    u_s = model.addVars(data.S, lb=0.0, ub=1.0, name="u_cvar")

    for s in data.S:
        model.addConstr(u_s[s] >= L_s_expr[s] - eta, name=f"cvar_tail_{s}")

    cvar_expr = eta + (1.0 / (1.0 - float(beta))) * gp.quicksum(
        data.prob[s] * u_s[s] for s in data.S
    )
    model.addConstr(cvar_expr <= float(gamma), name="Gamma_CVaR_E2E")

    # ---- Objective: min deployment_cost + expected bandwidth_cost ----
    # Deployment cost: sum of placed resource consumption × price
    deploy_cost_expr = gp.quicksum(
        y[i, cn]
        * float(data.w[i][k])
        * float(_dep_cost.get(cn, {}).get(k, 0.0))
        for i in data.I for cn in data.M if (i, cn) in pair_set
        for k in data.K
    )

    # Expected bandwidth cost: sum_s pi[s] * sum_e bw_cost[e] * LinkLoad[e,s]
    bw_cost_expr = gp.LinExpr()
    for s in data.S:
        xin_this_s = {
            (i, cn, p): xin_s[i, cn, p, s]
            for i in data.I for cn in data.M if (i, cn) in pair_set
            for p in range(len(data.P_cand.get((teavar_flow_anchors(data, i)[0], cn), [])))
            if (i, cn, p, s) in xin_s
        }
        xout_this_s = {
            (i, cn, q): xout_s[i, cn, q, s]
            for i in data.I for cn in data.M if (i, cn) in pair_set
            for q in range(len(data.P_cand.get((cn, teavar_flow_anchors(data, i)[1]), [])))
            if (i, cn, q, s) in xout_s
        }
        for e in data.E:
            load_e = _scenario_link_load_per_edge(data, xin_this_s, xout_this_s, e)
            bw_cost_expr += float(data.prob[s]) * float(_bw_cost.get(e, 0.0)) * load_e

    model.setObjective(deploy_cost_expr + bw_cost_expr, GRB.MINIMIZE)

    # ---- Store references for post-solve ----
    model._m2cc_y = y
    model._m2cc_r = r_var
    model._m2cc_z = z_var
    model._m2cc_xin_s = xin_s
    model._m2cc_xout_s = xout_s
    model._m2cc_eta = eta
    model._m2cc_u_s = u_s
    model._m2cc_L_s_expr = L_s_expr
    model._m2cc_cvar_expr = cvar_expr
    model._m2cc_deploy_cost_expr = deploy_cost_expr
    model._m2cc_bw_cost_expr = bw_cost_expr
    model._m2cc_data = data
    model._m2cc_gamma = gamma
    model._m2cc_beta = beta
    model._m2cc_theta = theta
    model._m2cc_total_weight = total_weight
    model._m2cc_service_floor = _floor
    model.update()
    return model


# ---------------------------------------------------------------------------
# Solver
# ---------------------------------------------------------------------------

def solve_m2_c_cost_adaptive(model: gp.Model) -> M2CCostSolveResult:
    """Solve the M2-C-Cost adaptive model and extract results.

    CVaR is computed post-hoc from per-scenario L_s values to avoid relying
    on the solver's free η variable when all L_s = 0.
    """
    model.optimize()
    status = int(model.Status)
    data = model._m2cc_data
    gamma = model._m2cc_gamma
    beta = model._m2cc_beta
    theta = model._m2cc_theta
    total_weight = model._m2cc_total_weight
    _floor = model._m2cc_service_floor

    if status not in (GRB.OPTIMAL, GRB.TIME_LIMIT, GRB.SUBOPTIMAL) or model.SolCount == 0:
        return M2CCostSolveResult(
            status=status, objective=float("nan"),
            deployment_cost=float("nan"), bandwidth_cost=float("nan"),
            expected_service=0.0,
            cvar_value=float("nan"), eta=float("nan"), L_s={},
            z={}, r={}, placement={}, x_in={}, x_out={},
            gamma=gamma, beta=beta,
        )

    y_vals = {(i, m): float(model._m2cc_y[i, m].X) for i, m in model._m2cc_y}
    r_vals = {k: float(v.X) for k, v in model._m2cc_r.items()}
    z_vals = {k: float(v.X) for k, v in model._m2cc_z.items()}
    x_in_vals = {k: float(v.X) for k, v in model._m2cc_xin_s.items()}
    x_out_vals = {k: float(v.X) for k, v in model._m2cc_xout_s.items()}

    # Objective components
    deploy_cost = float(model._m2cc_deploy_cost_expr.getValue())
    bw_cost = float(model._m2cc_bw_cost_expr.getValue())

    # Expected service
    exp_svc = sum(
        data.prob[s] * sum(theta[i] * z_vals.get((i, s), 0.0) for i in data.I)
        for s in data.S
    )

    # Post-hoc CVaR
    L_vals: dict[int, float] = {}
    for s in data.S:
        L_vals[s] = sum(
            theta[i] * (1.0 - z_vals.get((i, s), 0.0)) for i in data.I
        ) / total_weight
    cvar_val, eta_opt = _compute_cvar_from_L(L_vals, data.prob, beta)

    # Metadata from scenario metadata if present
    meta = {}
    if hasattr(data, "scenario_metadata") and data.scenario_metadata:
        sm = data.scenario_metadata
        meta["prune_mode"] = sm.get("prune_mode", "unknown")
        meta["has_aggregate_worst"] = sm.get("has_aggregate_worst", False)
        meta["aggregate_worst_probability"] = sm.get("aggregate_worst_probability", 0.0)
        meta["dropped_probability_mass"] = sm.get("dropped_probability_mass", 0.0)
        meta["scenario_count_before_pruning"] = sm.get("num_scenarios_before_pruning", 0)
        meta["scenario_count_after_pruning"] = sm.get("num_scenarios_after_pruning", 0)

    meta["loss_mode"] = "mean"
    meta["service_floor"] = dict(_floor)
    meta["gamma"] = gamma
    meta["beta"] = beta

    return M2CCostSolveResult(
        status=status,
        objective=float(model.ObjVal),
        deployment_cost=deploy_cost,
        bandwidth_cost=bw_cost,
        expected_service=exp_svc,
        cvar_value=cvar_val,
        eta=eta_opt,
        L_s=L_vals,
        z=z_vals,
        r=r_vals,
        placement=y_vals,
        x_in=x_in_vals,
        x_out=x_out_vals,
        gamma=gamma,
        beta=beta,
        metadata=meta,
        model=model,
    )
