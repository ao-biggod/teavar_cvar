# -*- coding: utf-8 -*-
"""
M1: Scenario-aware recourse model with adaptive routing.

Extends M0's placement y[i,m] with scenario-level recourse:
  - r[i,m,s]: service completion ratio per (task, node, scenario)
  - z[i,s]:    aggregate service ratio per (task, scenario)
  - x_in[i,m,p,s], x_out[i,m,q,s]: per-scenario routing (recourse)

Link failures and compute failures both constrain r[i,m,s], so they
naturally interact through the same z[i,s] → single end-to-end loss.

Constraints (per spec docs/m0_m1_m2_建模说明.md §4):
  (r)   0 ≤ r[i,m,s] ≤ y[i,m]
  (z)   z[i,s] = sum_m r[i,m,s]
  (flow-in)  sum_p x_in[i,m,p,s] = b_in[i] * r[i,m,s]
  (flow-out) sum_q x_out[i,m,q,s] = b_out[i] * r[i,m,s]
  (link)     LinkLoad[e,s] ≤ B[e] * sigma[e][s]
  (compute)  sum_i r[i,m,s] * w[i,k] ≤ C_s[m][k][s]

M1 can be solved standalone (max expected service) or serve as the
scenario sub-structure for M2's CVaR layer.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import gurobipy as gp
from gurobipy import GRB

from duibi_metrics import teavar_flow_anchors
from m0_models import _valid_pairs, _path_edges


@dataclass
class M1SolveResult:
    status: int
    objective: float
    expected_service: float
    placement: dict[tuple[int, int], float]
    r: dict[tuple[int, int, int], float]
    z: dict[tuple[int, int], float]
    x_in: dict[tuple[int, int, int, int], float]
    x_out: dict[tuple[int, int, int, int], float]
    link_load: dict[tuple[int, int, int], float]
    model: gp.Model


def _scenario_link_load_per_edge(
    data,
    xin_s: dict,
    xout_s: dict,
    e: tuple[int, int],
) -> gp.LinExpr:
    """
    Aggregate ingress + egress flow carried on directed edge *e* in a single
    scenario *s*.  Used inside the per-scenario link-capacity loop.

    ``xin_s`` is the per-scenario x_in dict with keys (i, m, p).
    """
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


def _compute_link_load(
    data,
    x_in_all: dict,
    x_out_all: dict,
) -> dict[tuple[int, int, int], float]:
    """Post-solve: compute LinkLoad[e, s] for every edge and scenario."""
    loads: dict[tuple[int, int, int], float] = {}
    for s in data.S:
        xin_s = {k: v for k, v in x_in_all.items() if k[3] == s}
        xout_s = {k: v for k, v in x_out_all.items() if k[3] == s}
        for e in data.E:
            total = 0.0
            e0, e1 = int(e[0]), int(e[1])
            for i in data.I:
                src, dst = teavar_flow_anchors(data, i)
                for m in data.M:
                    if (i, m) not in set(_valid_pairs(data)):
                        continue
                    for p, path in enumerate(data.P_cand.get((src, m), [])):
                        if (e0, e1) in _path_edges(path):
                            total += float(x_in_all.get((i, m, p, s), 0.0))
                    for q, path in enumerate(data.P_cand.get((m, dst), [])):
                        if (e0, e1) in _path_edges(path):
                            total += float(x_out_all.get((i, m, q, s), 0.0))
            loads[(e0, e1, s)] = total
    return loads


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def build_m1_model(
    data,
    *,
    quiet: bool = True,
    time_limit: float | None = None,
    mip_gap: float | None = None,
) -> gp.Model:
    """
    Build M1 MILP: placement y + scenario recourse (r, z, x_in_s, x_out_s).

    The model is *feasibility-only* by default — it places no objective.
    Use ``add_m1_max_service_objective()`` or ``set_m1_objective()`` to add one,
    or solve as-is to check feasibility (``status == OPTIMAL`` means a
    feasible placement + recourse plan exists that serves 100 % in every
    scenario).

    Parameters
    ----------
    data :
        Must have ``I, M, K, E, S, prob, B, sigma, C_s, task_src, task_dst,
        P_cand, valid_assign, b_in, b_out, w`` and ``routing_mode='per_task_od'``.
        Optional fields:
          - ``theta`` (task importance, default 1.0)
          - ``D_i``   (task demand scale, default 1.0)
    """
    model = gp.Model("M1_scenario_recourse")
    if quiet:
        model.setParam("OutputFlag", 0)
    if time_limit is not None:
        model.setParam("TimeLimit", float(time_limit))
    if mip_gap is not None:
        model.setParam("MIPGap", float(mip_gap))

    pairs = _valid_pairs(data)
    pair_set = set(pairs)

    # --- Stage 1: placement (here-and-now) ---
    y = model.addVars(pairs, vtype=GRB.BINARY, name="y")

    # (1) unique placement
    for i in data.I:
        model.addConstr(
            gp.quicksum(y[i, comp_node] for comp_node in data.M if (i, comp_node) in pair_set) == 1,
            name=f"place_{i}",
        )

    # --- Stage 2: recourse (wait-and-see) ---
    r_var: dict[tuple[int, int, int], gp.Var] = {}
    z_var: dict[tuple[int, int], gp.Var] = {}
    xin_s: dict[tuple[int, int, int, int], gp.Var] = {}
    xout_s: dict[tuple[int, int, int, int], gp.Var] = {}

    for s in data.S:
        for i in data.I:
            src_i, dst_i = teavar_flow_anchors(data, i)
            for comp_node in data.M:
                if (i, comp_node) not in pair_set:
                    continue

                # r[i, comp_node, s] ∈ [0, y[i,comp_node]]
                r_var[i, comp_node, s] = model.addVar(lb=0.0, ub=1.0, name=f"r_{i}_{comp_node}_{s}")
                model.addConstr(r_var[i, comp_node, s] <= y[i, comp_node], name=f"r_le_y_{i}_{comp_node}_{s}")

                # scenario ingress/egress routing
                in_paths = data.P_cand.get((src_i, comp_node), [])
                for p in range(len(in_paths)):
                    xin_s[i, comp_node, p, s] = model.addVar(lb=0.0, name=f"xin_s_{i}_{comp_node}_{p}_{s}")
                out_paths = data.P_cand.get((comp_node, dst_i), [])
                for q in range(len(out_paths)):
                    xout_s[i, comp_node, q, s] = model.addVar(lb=0.0, name=f"xout_s_{i}_{comp_node}_{q}_{s}")

                # flow conservation (equality): sum_p x = b * r
                model.addConstr(
                    gp.quicksum(xin_s[i, comp_node, p, s] for p in range(len(in_paths)))
                    == float(data.b_in[i]) * r_var[i, comp_node, s],
                    name=f"flow_in_s_{i}_{comp_node}_{s}",
                )
                model.addConstr(
                    gp.quicksum(xout_s[i, comp_node, q, s] for q in range(len(out_paths)))
                    == float(data.b_out[i]) * r_var[i, comp_node, s],
                    name=f"flow_out_s_{i}_{comp_node}_{s}",
                )

            # z[i, s] = sum_m r[i, comp_node, s]
            z_var[i, s] = model.addVar(lb=0.0, ub=1.0, name=f"z_{i}_{s}")
            model.addConstr(
                z_var[i, s] == gp.quicksum(
                    r_var[i, comp_node, s] for comp_node in data.M if (i, comp_node) in pair_set
                ),
                name=f"z_def_{i}_{s}",
            )

    # --- Scenario link capacity: LinkLoad[e,s] ≤ B[e] * sigma[e][s] ---
    for s in data.S:
        # Build per-scenario lookup for link_load_expr
        xin_this_s = {(i, comp_node, p): xin_s[i, comp_node, p, s]
                       for i in data.I for comp_node in data.M if (i, comp_node) in pair_set
                       for p in range(len(data.P_cand.get((teavar_flow_anchors(data, i)[0], comp_node), [])))
                       if (i, comp_node, p, s) in xin_s}
        xout_this_s = {(i, comp_node, q): xout_s[i, comp_node, q, s]
                        for i in data.I for comp_node in data.M if (i, comp_node) in pair_set
                        for q in range(len(data.P_cand.get((comp_node, teavar_flow_anchors(data, i)[1]), [])))
                        if (i, comp_node, q, s) in xout_s}
        for e in data.E:
            cap_eff = float(data.B[e]) * float(data.sigma[e][s])
            load_e = _scenario_link_load_per_edge(data, xin_this_s, xout_this_s, e)
            model.addConstr(
                load_e <= cap_eff,
                name=f"link_cap_s_{e[0]}_{e[1]}_{s}",
            )

    # --- Scenario compute capacity: sum_i r[i,m,s] * w[i,k] ≤ C_s[m][k][s] ---
    for s in data.S:
        for comp_node in data.M:
            for k in data.K:
                cap = float(data.C_s[comp_node][k][s])
                demand = gp.quicksum(
                    r_var[i, comp_node, s] * float(data.w[i][k])
                    for i in data.I if (i, comp_node) in pair_set
                )
                model.addConstr(
                    demand <= cap,
                    name=f"comp_cap_s_{comp_node}_{k}_{s}",
                )

    # --- Store references for post-solve ---
    model._m1_y = y
    model._m1_r = r_var
    model._m1_z = z_var
    model._m1_xin_s = xin_s
    model._m1_xout_s = xout_s
    model._m1_data = data
    model.update()
    return model


def add_m1_max_service_objective(
    model: gp.Model,
    data,
    r: dict,
    z: dict,
    *,
    weight_theta: bool = True,
) -> gp.LinExpr:
    """
    Add objective: maximise expected total weighted service.

    ``weight_theta=True`` (default) uses ``data.theta[i]`` (or 1.0 if absent).
    The expression is returned (and also set as the model objective).
    """
    theta = getattr(data, "theta", None) or {i: 1.0 for i in data.I}
    D_i = getattr(data, "D_i", None) or {i: 1.0 for i in data.I}

    exp_service = gp.quicksum(
        data.prob[s]
        * gp.quicksum(
            theta[i] * D_i[i] * z[i, s]
            for i in data.I
        )
        for s in data.S
    )
    model.setObjective(exp_service, GRB.MAXIMIZE)
    return exp_service


def set_m1_objective(
    model: gp.Model,
    data,
    *,
    mode: str = "max_service",
    r: dict | None = None,
    z: dict | None = None,
    **kwargs,
):
    """
    Set M1 objective by mode.

    Modes:
      - ``"max_service"``: maximise expected weighted service (default).
      - ``"feasibility"``: no objective — model is pure constraint satisfaction.
      - ``"min_max"``: maximise the worst-case (min over scenarios) service.
    """
    if r is None:
        r = model._m1_r
    if z is None:
        z = model._m1_z
    data = model._m1_data

    if mode == "feasibility":
        model.setObjective(gp.LinExpr(0.0), GRB.MINIMIZE)
        return

    if mode == "max_service":
        add_m1_max_service_objective(model, data, r, z, **kwargs)
        return

    if mode == "min_max":
        theta = getattr(data, "theta", None) or {i: 1.0 for i in data.I}
        D_i = getattr(data, "D_i", None) or {i: 1.0 for i in data.I}
        worst_z = model.addVar(lb=0.0, ub=1.0, name="worst_z")
        for s in data.S:
            avg_s = gp.quicksum(
                theta[i] * D_i[i] * z[i, s] for i in data.I
            ) / max(sum(theta[i] * D_i[i] for i in data.I), 1e-12)
            model.addConstr(worst_z <= avg_s, name=f"worst_z_{s}")
        model.setObjective(worst_z, GRB.MAXIMIZE)
        return

    raise ValueError(f"Unknown M1 objective mode: {mode!r}")


def solve_m1_model(model: gp.Model) -> M1SolveResult:
    """Solve the M1 model and extract results."""
    model.optimize()
    status = int(model.Status)
    data = model._m1_data

    y = model._m1_y
    r = model._m1_r
    z = model._m1_z
    xin_s = model._m1_xin_s
    xout_s = model._m1_xout_s

    placement = {(i, m): float(y[i, m].X) for i, m in y}
    r_out = {k: float(v.X) for k, v in r.items()}
    z_out = {k: float(v.X) for k, v in z.items()}
    x_in_out = {k: float(v.X) for k, v in xin_s.items()}
    x_out_out = {k: float(v.X) for k, v in xout_s.items()}

    obj = float(model.ObjVal) if status == GRB.OPTIMAL else float("nan")

    # Expected service (weighted)
    theta = getattr(data, "theta", None) or {i: 1.0 for i in data.I}
    D_i = getattr(data, "D_i", None) or {i: 1.0 for i in data.I}
    exp_service = 0.0
    if status == GRB.OPTIMAL:
        for s in data.S:
            for i in data.I:
                exp_service += data.prob[s] * theta[i] * D_i[i] * z_out.get((i, s), 0.0)

    link_load = _compute_link_load(data, x_in_out, x_out_out)

    return M1SolveResult(
        status=status,
        objective=obj,
        expected_service=exp_service,
        placement=placement,
        r=r_out,
        z=z_out,
        x_in=x_in_out,
        x_out=x_out_out,
        link_load=link_load,
        model=model,
    )


def format_m1_placement(data, placement: dict[tuple[int, int], float]) -> str:
    """Format M1 placement like ``'S1→A|S2→B'`` (node labels if available)."""
    try:
        from toy_instances_v2 import NODE_LABELS, node_label as _nl
        label_fn = _nl
    except ImportError:
        label_fn = str
    parts = []
    for i in sorted(data.I):
        assigned_m = None
        for (ii, m), val in placement.items():
            if ii == i and val > 0.5:
                assigned_m = m
                break
        src = data.task_src[i]
        if assigned_m is not None:
            parts.append(f"{label_fn(src)}→{label_fn(assigned_m)}")
        else:
            parts.append(f"i{i}→?")
    return " | ".join(parts)
