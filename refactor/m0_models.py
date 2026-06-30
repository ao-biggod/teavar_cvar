# -*- coding: utf-8 -*-
"""
M0 deterministic two-stage multi-path placement–routing model.

Constraints (1)–(7) and objective per ``docs/m0_m1_m2_建模说明.md`` §3.
No scenarios, CVaR, or recourse variables.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import gurobipy as gp
from gurobipy import GRB

from duibi_metrics import teavar_flow_anchors


# ---------------------------------------------------------------------------
# Post-hoc peak utilisation — pure dict arithmetic, no Gurobi dependency
# ---------------------------------------------------------------------------


def posthoc_peak_util(data, x_in: dict, x_out: dict, y: dict) -> dict:
    """Recompute true peak link/node utilisation from solved flows and
    placements.

    This function does NOT trust epigraph variables ``U_link_max`` /
    ``U_node_max``, especially at λ endpoints (0 or 1) where the ignored
    epigraph variable may not equal the true peak in the solver output.

    Parameters
    ----------
    data :
        Object with ``E, B, M, K, C_normal, w, I, task_src, task_dst,
        P_cand, valid_assign``.
    x_in :
        Dict ``(i, m, p) -> float`` of ingress flows.
    x_out :
        Dict ``(i, m, q) -> float`` of egress flows.
    y :
        Dict ``(i, m) -> float`` of placement (0 or 1).

    Returns
    -------
    dict with keys:
        ``peak_link_util`` — max_e LinkLoad_e / B[e]
        ``peak_node_util`` — max_{m,k} sum_i y·w / C_normal[m,k]
        ``argmax_link`` — edge ``(u, v)`` attaining the link peak
        ``argmax_node`` — tuple ``(m, k)`` attaining the node peak
    """
    # --- Link peak ---
    peak_link = 0.0
    argmax_link = None
    pair_set = set(_valid_pairs(data))

    for e in data.E:
        e0, e1 = int(e[0]), int(e[1])
        cap = float(data.B.get(e, 1.0))
        load = 0.0
        for i in data.I:
            src, dst = teavar_flow_anchors(data, i)
            for m in data.M:
                if (i, m) not in pair_set:
                    continue
                in_paths = data.P_cand.get((src, m), [])
                for p, path in enumerate(in_paths):
                    if (e0, e1) in _path_edges(path):
                        load += float(x_in.get((i, m, p), 0.0))
                out_paths = data.P_cand.get((m, dst), [])
                for q, path in enumerate(out_paths):
                    if (e0, e1) in _path_edges(path):
                        load += float(x_out.get((i, m, q), 0.0))
        util = load / cap if cap > 0 else 0.0
        if util > peak_link:
            peak_link = util
            argmax_link = (e0, e1)

    # --- Node peak ---
    peak_node = 0.0
    argmax_node = None
    for m in data.M:
        for k in data.K:
            demand = sum(
                float(y.get((i, m), 0.0)) * float(data.w[i][k])
                for i in data.I if (i, m) in pair_set
            )
            cap = float(data.C_normal[m][k])
            util = demand / cap if cap > 0 else 0.0
            if util > peak_node:
                peak_node = util
                argmax_node = (m, k)

    return {
        "peak_link_util": peak_link,
        "peak_node_util": peak_node,
        "argmax_link": argmax_link,
        "argmax_node": argmax_node,
    }


# ---------------------------------------------------------------------------
# M0SolveResult — solver epigraph + posthoc peak side by side
# ---------------------------------------------------------------------------


@dataclass
class M0SolveResult:
    """Result of an M0 solve.

    Fields prefixed ``U_*_solver`` come directly from the solver's epigraph
    variables.  Fields prefixed ``peak_*`` are recomputed from the actual
    flows and placements via ``posthoc_peak_util()`` — these are the ground
    truth and should be used for reporting, especially at λ endpoints.
    """
    status: int
    objective: float
    # Solver epigraph values (read from U_link.X / U_node.X)
    U_link_solver: float
    U_node_solver: float
    # Posthoc recomputed peak utilisations
    peak_link_util: float
    peak_node_util: float
    argmax_link: tuple[int, int] | None = None
    argmax_node: tuple[int, int] | None = None
    # Flows and placement
    placement: dict[tuple[int, int], float] = field(default_factory=dict)
    x_in: dict[tuple[int, int, int], float] = field(default_factory=dict)
    x_out: dict[tuple[int, int, int], float] = field(default_factory=dict)
    link_load: dict[tuple[int, int], float] = field(default_factory=dict)
    # Backward-compat aliases (deprecated — use U_*_solver / peak_*)
    @property
    def U_link_max(self) -> float:
        return self.U_link_solver
    @property
    def U_node_max(self) -> float:
        return self.U_node_solver
    model: gp.Model | None = None


def _valid_pairs(data) -> list[tuple[int, int]]:
    va = getattr(data, "valid_assign", None)
    if va:
        return sorted((int(i), int(m)) for i, m in va)
    return [(int(i), int(m)) for i in data.I for m in data.M]


def _path_edges(path: list) -> list[tuple[int, int]]:
    return [(int(u), int(v)) for u, v in path]


def link_load_expr(
    data,
    xin: dict,
    xout: dict,
    e: tuple[int, int],
) -> gp.LinExpr:
    """Constraint (4): aggregate ingress + egress flow crossing edge e."""
    expr = gp.LinExpr()
    e0, e1 = int(e[0]), int(e[1])
    for i in data.I:
        src, dst = teavar_flow_anchors(data, i)
        for m in data.M:
            if (i, m) not in set(_valid_pairs(data)):
                continue
            in_paths = data.P_cand.get((src, m), [])
            for p, path in enumerate(in_paths):
                if (e0, e1) in _path_edges(path):
                    expr += xin[i, m, p]
            out_paths = data.P_cand.get((m, dst), [])
            for q, path in enumerate(out_paths):
                if (e0, e1) in _path_edges(path):
                    expr += xout[i, m, q]
    return expr


def compute_link_load(data, xin: dict, xout: dict) -> dict[tuple[int, int], float]:
    loads: dict[tuple[int, int], float] = {}
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
                        total += float(xin.get((i, m, p), 0.0))
                for q, path in enumerate(data.P_cand.get((m, dst), [])):
                    if (e0, e1) in _path_edges(path):
                        total += float(xout.get((i, m, q), 0.0))
        loads[(e0, e1)] = total
    return loads


def build_m0_model(data, lambda_m0: float = 0.5, *, quiet: bool = True) -> gp.Model:
    """
    Build M0 MILP: placement y, routing x, epigraph U_link/U_node in [0,1].

    Parameters
    ----------
    data :
        Needs ``I, M, K, E, B, C_normal, P_cand, valid_assign, b_in, b_out, w``,
        plus ``routing_mode='per_task_od'`` with ``task_src`` / ``task_dst``.
    lambda_m0 :
        Weight on ``U_link_max`` in ``min lambda_m0 U_link + (1-lambda_m0) U_node``.
    """
    lam = float(lambda_m0)
    if not 0.0 <= lam <= 1.0:
        raise ValueError(f"lambda_m0 must be in [0,1], got {lambda_m0}")

    model = gp.Model("M0_placement_routing")
    if quiet:
        model.setParam("OutputFlag", 0)

    pairs = _valid_pairs(data)
    pair_set = set(pairs)

    y = model.addVars(pairs, vtype=GRB.BINARY, name="y")

    xin: dict[tuple[int, int, int], gp.Var] = {}
    xout: dict[tuple[int, int, int], gp.Var] = {}
    for i in data.I:
        src, dst = teavar_flow_anchors(data, i)
        for m in data.M:
            if (i, m) not in pair_set:
                continue
            for p in range(len(data.P_cand.get((src, m), []))):
                xin[i, m, p] = model.addVar(lb=0.0, name=f"xin_{i}_{m}_{p}")
            for q in range(len(data.P_cand.get((m, dst), []))):
                xout[i, m, q] = model.addVar(lb=0.0, name=f"xout_{i}_{m}_{q}")

    U_link = model.addVar(lb=0.0, ub=1.0, name="U_link_max")
    U_node = model.addVar(lb=0.0, ub=1.0, name="U_node_max")

    # (1) unique placement
    for i in data.I:
        model.addConstr(
            gp.quicksum(y[i, m] for m in data.M if (i, m) in pair_set) == 1,
            name=f"place_{i}",
        )

    # (2)(3) equality flow conservation
    for i in data.I:
        src, dst = teavar_flow_anchors(data, i)
        b_in = float(data.b_in[i])
        b_out = float(data.b_out[i])
        for m in data.M:
            if (i, m) not in pair_set:
                continue
            in_paths = data.P_cand.get((src, m), [])
            out_paths = data.P_cand.get((m, dst), [])
            model.addConstr(
                gp.quicksum(xin[i, m, p] for p in range(len(in_paths))) == b_in * y[i, m],
                name=f"flow_in_{i}_{m}",
            )
            model.addConstr(
                gp.quicksum(xout[i, m, q] for q in range(len(out_paths))) == b_out * y[i, m],
                name=f"flow_out_{i}_{m}",
            )

    # (4)(5) link load epigraph
    for e in data.E:
        cap = float(data.B[e])
        model.addConstr(
            link_load_expr(data, xin, xout, (int(e[0]), int(e[1]))) <= cap * U_link,
            name=f"link_epigraph_{e[0]}_{e[1]}",
        )

    # (6)(7) node resource epigraph
    for m in data.M:
        for k in data.K:
            demand = gp.quicksum(
                y[i, m] * float(data.w[i][k]) for i in data.I if (i, m) in pair_set
            )
            cap = float(data.C_normal[m][k])
            model.addConstr(demand <= cap * U_node, name=f"node_epigraph_{m}_{k}")

    model.setObjective(lam * U_link + (1.0 - lam) * U_node, GRB.MINIMIZE)

    model._m0_y = y
    model._m0_xin = xin
    model._m0_xout = xout
    model._m0_U_link = U_link
    model._m0_U_node = U_node
    model._m0_data = data
    model.update()
    return model


def solve_m0_model(model: gp.Model) -> M0SolveResult:
    model.optimize()
    status = int(model.Status)
    data = model._m0_data
    y = model._m0_y
    xin = model._m0_xin
    xout = model._m0_xout

    placement = {(i, m): float(y[i, m].X) for i, m in y}
    x_in = {k: float(v.X) for k, v in xin.items()}
    x_out = {k: float(v.X) for k, v in xout.items()}
    link_load = compute_link_load(data, x_in, x_out)

    obj = float(model.ObjVal) if status == GRB.OPTIMAL else float("nan")
    U_link_val = float(model._m0_U_link.X) if status == GRB.OPTIMAL else float("nan")
    U_node_val = float(model._m0_U_node.X) if status == GRB.OPTIMAL else float("nan")

    # Posthoc peak — always computed from dicts, solver / NaN safe
    if status == GRB.OPTIMAL:
        ph = posthoc_peak_util(data, x_in, x_out, placement)
    else:
        ph = {"peak_link_util": float("nan"), "peak_node_util": float("nan"),
              "argmax_link": None, "argmax_node": None}

    return M0SolveResult(
        status=status,
        objective=obj,
        U_link_solver=U_link_val,
        U_node_solver=U_node_val,
        peak_link_util=ph["peak_link_util"],
        peak_node_util=ph["peak_node_util"],
        argmax_link=ph["argmax_link"],
        argmax_node=ph["argmax_node"],
        placement=placement,
        x_in=x_in,
        x_out=x_out,
        link_load=link_load,
        model=model,
    )
