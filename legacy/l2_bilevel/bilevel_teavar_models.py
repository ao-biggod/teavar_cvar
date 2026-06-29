# -*- coding: utf-8 -*-
"""
L0 枚举式快慢双层 baseline（reaction-based placement–routing decomposition）。

定位
----
* **不是** KKT 嵌入的严格 Stackelberg 单模型；是「枚举 y → 快层 routing → post-hoc CVaR → 慢层 A/C」。
* 适合 toy / exact validation / 单层对照；**尚未**作为 B4 大规模主链。

慢层 / 快层
-----------
* **慢层**：枚举 placement，按 Model A（λ）或 Model C（Γ）选 y。
* **快层**：给定 y 后解 routing（连续变量 x, d；y 以常数嵌入，非 binary MIP）。
* **Risk(y)**：快层解固定后 post-hoc 计算 CVaR_SLA、CVaR_SF（SF 仅依赖 y）。

与单层 Model A 的非等价性
-------------------------
单层 A：min Cost + λ·CVaR − ω·E[Del]（ω 同时进入联合目标）。

双层 A：慢层 min Cost + λ·CVaR；ω **仅**在快层 routing 目标中（delivery / lexicographic 等）。
因此双层 A 与单层 A 是 **baseline comparison**，不是数学等价重写。
ComponentRisk toy 上 placement 常一致，是因为带宽绑 placement 且结构性强。

快层目标模式（``fast_objective``）
---------------------------------
* ``delivery``：min C_bw − ω·E[Del]（默认）
* ``lexicographic``：max E[Del] → min E[SLA loss] → min C_bw（稳定 Risk(y)）
* ``min_sla_cvar``：在快层直接 min CVaR_SLA（给定 y 下最小化尾部 SLA）
* ``lex_sla_delivery_cost``：min CVaR_SLA → max E[Del] → min C_bw（Strict lex 快层默认）

Strict risk-first lexicographic bilevel TEAVAR
---------------------------------------------
* **This is a strict risk-first lexicographic bilevel model, not a cost-risk trade-off model.**
* 无 λ / Γ / ε / ω；默认 priority SF → SLA → Cost。
* 见 ``solve_bilevel_lexicographic`` / ``evaluate_placement_lex``。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterator, Literal, Sequence

import gurobipy as gp
from gurobipy import GRB

from cvar_compare import add_scenario_delivery_coupling
from duibi_metrics import (
    bandwidth_cost_expr,
    placement_bandwidth_cost_value,
    teavar_flow_anchors,
)
from exact_enumeration_solver import compute_cvar, enumerate_placements

FastObjectiveMode = Literal[
    "delivery", "lexicographic", "min_sla_cvar", "lex_sla_delivery_cost"
]
LexPriorityName = Literal["SF", "SLA", "Cost"]
DEFAULT_LEX_PRIORITY: tuple[LexPriorityName, ...] = ("SF", "SLA", "Cost")

_STATUS_NAMES = {
    GRB.OPTIMAL: "OPTIMAL",
    GRB.INFEASIBLE: "INFEASIBLE",
    GRB.INF_OR_UNBD: "INF_OR_UNBD",
    GRB.UNBOUNDED: "UNBOUNDED",
    GRB.TIME_LIMIT: "TIME_LIMIT",
    GRB.SUBOPTIMAL: "SUBOPTIMAL",
}

_LEX_TOL = 1e-7
_NUM_TOL = 1e-9


def _status_name(code: int) -> str:
    return _STATUS_NAMES.get(code, str(int(code)))


def _uses_per_task_flow(data) -> bool:
    return getattr(data, "routing_mode", "hub") in ("per_task_od", "umcf_per_task")


def _task_flow_anchors(data, i: int, default_in_u: int, default_out_v: int) -> tuple[int, int]:
    if _uses_per_task_flow(data):
        return teavar_flow_anchors(data, i)
    return default_in_u, default_out_v


def deployment_cost(data, placement: dict[int, int]) -> float:
    """C_deploy(y): resource placement cost only (excludes flow bandwidth)."""
    total = 0.0
    for i in data.I:
        node = int(placement[i])
        for k in data.K:
            total += float(data.w[i][k]) * float(data.p_price[node][k])
    return total


def slow_placement_cost(data, placement: dict[int, int]) -> float:
    """慢层成本：放置资源 +（可选）placement 绑定的计划带宽。"""
    total = deployment_cost(data, placement)
    if getattr(data, "bandwidth_cost_on_placement", False):
        total += placement_bandwidth_cost_value(data, placement)
    return total


def _x_sum_from_flow(xin: dict, xout: dict) -> float:
    return sum(float(v) for v in xin.values()) + sum(float(v) for v in xout.values())


@dataclass
class FastRoutingResult:
    status: str
    bandwidth_cost: float
    expected_delivery: float
    objective: float
    fast_objective: str = "delivery"
    expected_sla_loss: float | None = None
    model_sla_cvar: float | None = None
    cvar_sla: float | None = None
    x_sum: float = 0.0
    stage_statuses: list[str] = field(default_factory=list)
    xin: dict[tuple[int, int, int], float] = field(default_factory=dict)
    xout: dict[tuple[int, int, int], float] = field(default_factory=dict)
    del_in: dict[tuple[int, int, int, int], float] = field(default_factory=dict)
    del_out: dict[tuple[int, int, int, int], float] = field(default_factory=dict)


@dataclass
class _FastRoutingCtx:
    m: gp.Model
    placement: dict[int, int]
    xin: dict
    xout: dict
    del_in: dict
    del_out: dict
    cost_b: gp.LinExpr
    exp_deliver: gp.LinExpr
    in_u: int
    out_v: int
    task_anchors: dict[int, tuple[int, int]]


def _add_fixed_virtual_bottleneck(
    m,
    data,
    placement: dict[int, int],
    del_in,
    del_out,
    hub: int,
) -> None:
    """固定 placement 下的虚拟接入瓶颈（不创建 y 变量）。"""
    sigma_vs = getattr(data, "sigma_vs", None)
    if not sigma_vs or getattr(data, "umcf_virtual_nodes", False):
        return
    sigma_vt = getattr(data, "sigma_vt", None) or sigma_vs
    h = int(hub)
    per_task = _uses_per_task_flow(data)
    for s in data.S:
        for i in data.I:
            if per_task:
                src_i, dst_i = teavar_flow_anchors(data, i)
            else:
                src_i, dst_i = h, h
            mnode = int(placement[i])
            Rin = gp.quicksum(
                del_in[i, node, p, s]
                for node in data.M
                for p in range(len(data.P_cand[src_i, node]))
                if (i, node, p, s) in del_in
            )
            Rout = gp.quicksum(
                del_out[i, node, q, s]
                for node in data.M
                for q in range(len(data.P_cand[node, dst_i]))
                if (i, node, q, s) in del_out
            )
            cap_in = float(data.b_in[i]) * float(sigma_vs.get(mnode, {}).get(s, 1.0))
            cap_out = float(data.b_out[i]) * float(sigma_vt.get(mnode, {}).get(s, 1.0))
            m.addConstr(Rin <= cap_in, name=f"vs_cap_in_{i}_{s}")
            m.addConstr(Rout <= cap_out, name=f"vt_cap_out_{i}_{s}")


def _add_sla_cvar_ru(
    m,
    data,
    del_in,
    del_out,
    in_u: int,
    out_v: int,
    beta: float,
) -> gp.LinExpr:
    zeta = m.addVar(lb=-GRB.INFINITY, name="zeta_sla_fast")
    u_s = m.addVars(data.S, lb=0.0, name="u_sla_fast")
    for s in data.S:
        for i in data.I:
            iu, ov = _task_flow_anchors(data, i, in_u, out_v)
            Rin = gp.quicksum(
                del_in[i, node, p, s]
                for node in data.M
                for p in range(len(data.P_cand[iu, node]))
                if (i, node, p, s) in del_in
            )
            Rout = gp.quicksum(
                del_out[i, node, q, s]
                for node in data.M
                for q in range(len(data.P_cand[node, ov]))
                if (i, node, q, s) in del_out
            )
            m.addConstr(
                u_s[s] * float(data.b_in[i]) >= float(data.b_in[i]) - Rin - float(data.b_in[i]) * zeta,
                name=f"ru_in_{i}_{s}",
            )
            m.addConstr(
                u_s[s] * float(data.b_out[i]) >= float(data.b_out[i]) - Rout - float(data.b_out[i]) * zeta,
                name=f"ru_out_{i}_{s}",
            )
    inv = 1.0 / (1.0 - float(beta))
    return zeta + inv * gp.quicksum(float(data.prob[s]) * u_s[s] for s in data.S)


def _add_expected_sla_loss(
    m,
    data,
    del_in,
    del_out,
    in_u: int,
    out_v: int,
) -> gp.LinExpr:
    L_s = m.addVars(data.S, lb=0.0, name="exp_sla_loss")
    for s in data.S:
        for i in data.I:
            iu, ov = _task_flow_anchors(data, i, in_u, out_v)
            Rin = gp.quicksum(
                del_in[i, node, p, s]
                for node in data.M
                for p in range(len(data.P_cand[iu, node]))
                if (i, node, p, s) in del_in
            )
            Rout = gp.quicksum(
                del_out[i, node, q, s]
                for node in data.M
                for q in range(len(data.P_cand[node, ov]))
                if (i, node, q, s) in del_out
            )
            if float(data.b_in[i]) > 0:
                m.addConstr(L_s[s] >= 1.0 - Rin / float(data.b_in[i]), name=f"els_in_{i}_{s}")
            if float(data.b_out[i]) > 0:
                m.addConstr(L_s[s] >= 1.0 - Rout / float(data.b_out[i]), name=f"els_out_{i}_{s}")
    return gp.quicksum(float(data.prob[s]) * L_s[s] for s in data.S)


def build_fast_routing_ctx(
    data,
    placement: dict[int, int],
    *,
    time_limit: float | None = None,
) -> _FastRoutingCtx:
    """
    快层基础模型：仅连续 x, d；placement 为常数（无 binary y）。
    """
    h = int(getattr(data, "hub", 0))
    per_task = _uses_per_task_flow(data)
    if per_task:
        in_u, out_v = teavar_flow_anchors(data, data.I[0])
    else:
        in_u, out_v = teavar_flow_anchors(data)

    m = gp.Model("TEAVAR_FastRouting")
    m.setParam("OutputFlag", 0)
    if time_limit is not None:
        m.setParam("TimeLimit", float(time_limit))

    if per_task:
        xin: dict = {}
        xout: dict = {}
        for i in data.I:
            iu, ov = teavar_flow_anchors(data, i)
            node = int(placement[i])
            for p in range(len(data.P_cand[iu, node])):
                xin[i, node, p] = m.addVar(lb=0.0, name=f"xin_{i}_{node}_{p}")
            for q in range(len(data.P_cand[node, ov])):
                xout[i, node, q] = m.addVar(lb=0.0, name=f"xout_{i}_{node}_{q}")
    else:
        xin = {
            (i, node, p): m.addVar(lb=0.0, name=f"xin_{i}_{node}_{p}")
            for i in data.I
            for node in data.M
            for p in range(len(data.P_cand[in_u, node]))
            if int(placement[i]) == node
        }
        xout = {
            (i, node, q): m.addVar(lb=0.0, name=f"xout_{i}_{node}_{q}")
            for i in data.I
            for node in data.M
            for q in range(len(data.P_cand[node, out_v]))
            if int(placement[i]) == node
        }

    del_in: dict = {}
    del_out: dict = {}
    for s in data.S:
        for i in data.I:
            iu, ov = _task_flow_anchors(data, i, in_u, out_v)
            node = int(placement[i])
            for p in range(len(data.P_cand[iu, node])):
                if (i, node, p) in xin:
                    del_in[i, node, p, s] = m.addVar(lb=0.0, name=f"din_{i}_{node}_{p}_{s}")
            for q in range(len(data.P_cand[node, ov])):
                if (i, node, q) in xout:
                    del_out[i, node, q, s] = m.addVar(lb=0.0, name=f"dout_{i}_{node}_{q}_{s}")

    bw_on_placement = bool(getattr(data, "bandwidth_cost_on_placement", False))
    cost_b = (
        gp.LinExpr(0.0)
        if bw_on_placement
        else bandwidth_cost_expr(data, xin, xout, None, None)
    )

    task_anchors = {i: _task_flow_anchors(data, i, in_u, out_v) for i in data.I}
    exp_deliver = gp.quicksum(
        float(data.prob[s])
        * (
            gp.quicksum(
                del_in[i, node, p, s]
                for i in data.I
                for node in data.M
                for p in range(len(data.P_cand[task_anchors[i][0], node]))
                if (i, node, p, s) in del_in
            )
            + gp.quicksum(
                del_out[i, node, q, s]
                for i in data.I
                for node in data.M
                for q in range(len(data.P_cand[node, task_anchors[i][1]]))
                if (i, node, q, s) in del_out
            )
        )
        for s in data.S
    )

    for i in data.I:
        iu, ov = _task_flow_anchors(data, i, in_u, out_v)
        node = int(placement[i])
        m.addConstr(
            gp.quicksum(xin[i, node, p] for p in range(len(data.P_cand[iu, node])) if (i, node, p) in xin)
            <= float(data.b_in[i]),
            name=f"cap_in_{i}",
        )
        m.addConstr(
            gp.quicksum(xout[i, node, q] for q in range(len(data.P_cand[node, ov])) if (i, node, q) in xout)
            <= float(data.b_out[i]),
            name=f"cap_out_{i}",
        )

    add_scenario_delivery_coupling(m, data, {}, xin, xout, del_in, del_out, in_u, out_v)
    _add_fixed_virtual_bottleneck(m, data, placement, del_in, del_out, h)

    return _FastRoutingCtx(
        m=m,
        placement=dict(placement),
        xin=xin,
        xout=xout,
        del_in=del_in,
        del_out=del_out,
        cost_b=cost_b,
        exp_deliver=exp_deliver,
        in_u=in_u,
        out_v=out_v,
        task_anchors=task_anchors,
    )


def build_fast_routing_model(
    data,
    placement: dict[int, int],
    *,
    omega_deliver: float = 1.0,
    fast_objective: FastObjectiveMode = "delivery",
    beta_sla: float | None = None,
    time_limit: float | None = None,
):
    """兼容旧接口：返回 (m, y_stub, xin, xout, del_in, del_out, cost_b, exp_deliver)。"""
    ctx = build_fast_routing_ctx(data, placement, time_limit=time_limit)
    beta = float(beta_sla if beta_sla is not None else data.beta_N)
    if fast_objective == "delivery":
        ctx.m.setObjective(ctx.cost_b - float(omega_deliver) * ctx.exp_deliver, GRB.MINIMIZE)
    elif fast_objective == "min_sla_cvar":
        sla_cvar = _add_sla_cvar_ru(
            ctx.m, data, ctx.del_in, ctx.del_out, ctx.in_u, ctx.out_v, beta
        )
        ctx.m.setObjective(sla_cvar, GRB.MINIMIZE)
    else:
        ctx.m.setObjective(-ctx.exp_deliver, GRB.MINIMIZE)
    return (
        ctx.m,
        {},
        ctx.xin,
        ctx.xout,
        ctx.del_in,
        ctx.del_out,
        ctx.cost_b,
        ctx.exp_deliver,
    )


def _var_values(var_dict: dict) -> dict:
    return {k: float(v.X) for k, v in var_dict.items()}


def _result_from_ctx(
    ctx: _FastRoutingCtx,
    *,
    fast_objective: str,
    expected_sla_loss: float | None = None,
    model_sla_cvar: float | None = None,
    stage_statuses: list[str] | None = None,
) -> FastRoutingResult | None:
    m = ctx.m
    if m.status not in (GRB.OPTIMAL, GRB.TIME_LIMIT, GRB.SUBOPTIMAL) or m.SolCount == 0:
        return FastRoutingResult(
            status=_status_name(m.status),
            bandwidth_cost=0.0,
            expected_delivery=0.0,
            objective=float("inf"),
            fast_objective=fast_objective,
            stage_statuses=list(stage_statuses or []),
        )
    xin_vals = _var_values(ctx.xin)
    xout_vals = _var_values(ctx.xout)
    bw = float(ctx.cost_b.getValue()) if ctx.cost_b.size() else 0.0
    ed = float(ctx.exp_deliver.getValue())
    cvar_val = model_sla_cvar
    return FastRoutingResult(
        status=_status_name(m.status),
        bandwidth_cost=bw,
        expected_delivery=ed,
        objective=float(m.ObjVal),
        fast_objective=fast_objective,
        expected_sla_loss=expected_sla_loss,
        model_sla_cvar=cvar_val,
        cvar_sla=cvar_val,
        x_sum=_x_sum_from_flow(xin_vals, xout_vals),
        stage_statuses=list(stage_statuses or []),
        xin=xin_vals,
        xout=xout_vals,
        del_in=_var_values(ctx.del_in),
        del_out=_var_values(ctx.del_out),
    )


def _solve_fast_delivery(
    data,
    placement: dict[int, int],
    *,
    omega_deliver: float,
    time_limit: float | None,
) -> FastRoutingResult | None:
    ctx = build_fast_routing_ctx(data, placement, time_limit=time_limit)
    ctx.m.setObjective(ctx.cost_b - float(omega_deliver) * ctx.exp_deliver, GRB.MINIMIZE)
    ctx.m.optimize()
    return _result_from_ctx(ctx, fast_objective="delivery")


def _solve_fast_min_sla_cvar(
    data,
    placement: dict[int, int],
    *,
    beta_sla: float,
    time_limit: float | None,
) -> FastRoutingResult | None:
    ctx = build_fast_routing_ctx(data, placement, time_limit=time_limit)
    sla_cvar = _add_sla_cvar_ru(
        ctx.m, data, ctx.del_in, ctx.del_out, ctx.in_u, ctx.out_v, beta_sla
    )
    ctx.m.setObjective(sla_cvar, GRB.MINIMIZE)
    ctx.m.optimize()
    cvar_val = float(sla_cvar.getValue()) if ctx.m.SolCount else None
    return _result_from_ctx(ctx, fast_objective="min_sla_cvar", model_sla_cvar=cvar_val)


def _solve_fast_lex_sla_delivery_cost(
    data,
    placement: dict[int, int],
    *,
    beta_sla: float,
    time_limit: float | None,
    tol: float = _NUM_TOL,
) -> FastRoutingResult | None:
    """F1: min CVaR_SLA; F2: max E[Del]; F3: min C_bw (sequential re-solve, no big-M weights)."""
    stage_statuses: list[str] = []

    ctx1 = build_fast_routing_ctx(data, placement, time_limit=time_limit)
    sla_cvar1 = _add_sla_cvar_ru(
        ctx1.m, data, ctx1.del_in, ctx1.del_out, ctx1.in_u, ctx1.out_v, beta_sla
    )
    ctx1.m.setObjective(sla_cvar1, GRB.MINIMIZE)
    ctx1.m.optimize()
    stage_statuses.append(_status_name(ctx1.m.status))
    if ctx1.m.status != GRB.OPTIMAL or ctx1.m.SolCount == 0:
        return _result_from_ctx(
            ctx1, fast_objective="lex_sla_delivery_cost", stage_statuses=stage_statuses
        )
    r_sla_star = float(sla_cvar1.getValue())

    ctx2 = build_fast_routing_ctx(data, placement, time_limit=time_limit)
    sla_cvar2 = _add_sla_cvar_ru(
        ctx2.m, data, ctx2.del_in, ctx2.del_out, ctx2.in_u, ctx2.out_v, beta_sla
    )
    ctx2.m.addConstr(sla_cvar2 <= r_sla_star + tol, name="lex_cvar_ceiling")
    ctx2.m.setObjective(-ctx2.exp_deliver, GRB.MINIMIZE)
    ctx2.m.optimize()
    stage_statuses.append(_status_name(ctx2.m.status))
    if ctx2.m.status != GRB.OPTIMAL or ctx2.m.SolCount == 0:
        return _result_from_ctx(
            ctx2,
            fast_objective="lex_sla_delivery_cost",
            model_sla_cvar=r_sla_star,
            stage_statuses=stage_statuses,
        )
    ed_star = float(ctx2.exp_deliver.getValue())

    ctx3 = build_fast_routing_ctx(data, placement, time_limit=time_limit)
    sla_cvar3 = _add_sla_cvar_ru(
        ctx3.m, data, ctx3.del_in, ctx3.del_out, ctx3.in_u, ctx3.out_v, beta_sla
    )
    ctx3.m.addConstr(sla_cvar3 <= r_sla_star + tol, name="lex_cvar_ceiling")
    ctx3.m.addConstr(ctx3.exp_deliver >= ed_star - tol, name="lex_ed_floor")
    ctx3.m.setObjective(ctx3.cost_b, GRB.MINIMIZE)
    ctx3.m.optimize()
    stage_statuses.append(_status_name(ctx3.m.status))
    return _result_from_ctx(
        ctx3,
        fast_objective="lex_sla_delivery_cost",
        model_sla_cvar=r_sla_star,
        stage_statuses=stage_statuses,
    )


def _solve_fast_lexicographic(
    data,
    placement: dict[int, int],
    *,
    time_limit: float | None,
) -> FastRoutingResult | None:
    # Phase 1: max E[Del]
    ctx1 = build_fast_routing_ctx(data, placement, time_limit=time_limit)
    ctx1.m.setObjective(-ctx1.exp_deliver, GRB.MINIMIZE)
    ctx1.m.optimize()
    r1 = _result_from_ctx(ctx1, fast_objective="lexicographic")
    if r1 is None or r1.status != "OPTIMAL":
        return r1
    ed_star = r1.expected_delivery

    # Phase 2: E[Del] >= ed* - tol, min E[SLA loss]
    ctx2 = build_fast_routing_ctx(data, placement, time_limit=time_limit)
    ctx2.m.addConstr(ctx2.exp_deliver >= ed_star - _LEX_TOL, name="lex_ed_floor")
    exp_loss = _add_expected_sla_loss(ctx2.m, data, ctx2.del_in, ctx2.del_out, ctx2.in_u, ctx2.out_v)
    ctx2.m.setObjective(exp_loss, GRB.MINIMIZE)
    ctx2.m.optimize()
    r2 = _result_from_ctx(ctx2, fast_objective="lexicographic", expected_sla_loss=float(exp_loss.getValue()))
    if r2 is None or r2.status != "OPTIMAL":
        return r2
    el_star = float(exp_loss.getValue())

    # Phase 3: tie-break min bandwidth
    ctx3 = build_fast_routing_ctx(data, placement, time_limit=time_limit)
    ctx3.m.addConstr(ctx3.exp_deliver >= ed_star - _LEX_TOL, name="lex_ed_floor")
    exp_loss3 = _add_expected_sla_loss(
        ctx3.m, data, ctx3.del_in, ctx3.del_out, ctx3.in_u, ctx3.out_v
    )
    ctx3.m.addConstr(exp_loss3 <= el_star + _LEX_TOL, name="lex_loss_ceiling")
    ctx3.m.setObjective(ctx3.cost_b, GRB.MINIMIZE)
    ctx3.m.optimize()
    return _result_from_ctx(
        ctx3,
        fast_objective="lexicographic",
        expected_sla_loss=el_star,
    )


def solve_fast_routing(
    data,
    placement: dict[int, int],
    *,
    omega_deliver: float = 1.0,
    fast_objective: FastObjectiveMode = "lex_sla_delivery_cost",
    beta_sla: float | None = None,
    time_limit: float | None = None,
    tol: float = _NUM_TOL,
) -> FastRoutingResult | None:
    """求解快层 routing 子问题。"""
    beta = float(beta_sla if beta_sla is not None else data.beta_N)
    if fast_objective == "lex_sla_delivery_cost":
        return _solve_fast_lex_sla_delivery_cost(
            data, placement, beta_sla=beta, time_limit=time_limit, tol=tol
        )
    if fast_objective == "lexicographic":
        return _solve_fast_lexicographic(data, placement, time_limit=time_limit)
    if fast_objective == "min_sla_cvar":
        return _solve_fast_min_sla_cvar(data, placement, beta_sla=beta, time_limit=time_limit)
    return _solve_fast_delivery(
        data, placement, omega_deliver=omega_deliver, time_limit=time_limit
    )


def _sf_d_ref_by_resource(data) -> dict[int, float]:
    refs: dict[int, float] = {}
    for k in data.K:
        total = sum(float(data.w[i][k]) for i in data.I)
        refs[k] = max(total, 1.0)
    return refs


def _sla_loss_by_scenario_from_fast(
    data,
    fast: FastRoutingResult,
) -> dict[int, float]:
    per_task = _uses_per_task_flow(data)
    out: dict[int, float] = {}
    for s in data.S:
        worst = 0.0
        for i in data.I:
            if per_task:
                iu, ov = teavar_flow_anchors(data, i)
            else:
                iu, ov = teavar_flow_anchors(data)
            rin = sum(
                fast.del_in.get((i, node, p, s), 0.0)
                for node in data.M
                for p in range(len(data.P_cand[iu, node]))
            )
            rout = sum(
                fast.del_out.get((i, node, q, s), 0.0)
                for node in data.M
                for q in range(len(data.P_cand[node, ov]))
            )
            li = 0.0
            if data.b_in[i] > 0:
                li = max(li, 1.0 - rin / float(data.b_in[i]))
            if data.b_out[i] > 0:
                li = max(li, 1.0 - rout / float(data.b_out[i]))
            worst = max(worst, li)
        out[s] = max(0.0, worst)
    return out


def _sf_loss_by_scenario(data, placement: dict[int, int]) -> dict[int, float]:
    d_ref = _sf_d_ref_by_resource(data)
    out: dict[int, float] = {}
    for s in data.S:
        worst = 0.0
        for node in data.M:
            for k in data.K:
                load = sum(float(data.w[i][k]) for i in data.I if int(placement[i]) == node)
                cap = float(data.C_s[node][k][s])
                worst = max(worst, max(0.0, load - cap) / float(d_ref[k]))
        out[s] = max(0.0, worst)
    return out


def placement_risk(
    data,
    placement: dict[int, int],
    fast: FastRoutingResult,
    *,
    beta_sla: float | None = None,
    beta_sf: float | None = None,
) -> tuple[float, float]:
    """给定 placement 与快层解，post-hoc 返回 (CVaR_SLA, CVaR_SF)。"""
    b_sla = float(beta_sla if beta_sla is not None else data.beta_N)
    b_sf = float(beta_sf if beta_sf is not None else data.beta_N)
    prob = {s: float(data.prob[s]) for s in data.S}
    sla = _sla_loss_by_scenario_from_fast(data, fast)
    sf = _sf_loss_by_scenario(data, placement)
    return compute_cvar(sla, prob, b_sla), compute_cvar(sf, prob, b_sf)


@dataclass
class PlacementEvaluation:
    placement: dict[int, int]
    placement_code: str
    slow_cost: float
    fast_bandwidth_cost: float
    total_cost: float
    cvar_sla: float
    cvar_sf: float
    expected_delivery: float
    fast_status: str
    fast_objective: str = "delivery"
    bilevel_a_objective: float | None = None
    bilevel_c_feasible: bool = True
    bilevel_c_objective: float | None = None


def format_placement_code(data, placement: dict[int, int]) -> str:
    labels = getattr(data, "placement_node_labels", None)
    if labels:
        inv = {int(v): str(k) for k, v in labels.items()}
        return "".join(inv.get(int(placement[i]), "?") for i in sorted(data.I))
    return ",".join(f"{i}->{placement[i]}" for i in sorted(data.I))


def evaluate_placement(
    data,
    placement: dict[int, int],
    *,
    omega_deliver: float = 1.0,
    fast_objective: FastObjectiveMode = "delivery",
    lambda_sla: float = 0.0,
    lambda_sf: float = 0.0,
    gamma_sla: float | None = None,
    gamma_sf: float | None = None,
    beta_sla: float | None = None,
    beta_sf: float | None = None,
    time_limit: float | None = None,
) -> PlacementEvaluation | None:
    """对一个 placement 完成快层求解 + post-hoc 慢层指标汇总。"""
    fast = solve_fast_routing(
        data,
        placement,
        omega_deliver=omega_deliver,
        fast_objective=fast_objective,
        beta_sla=beta_sla,
        time_limit=time_limit,
    )
    if fast is None or fast.status != "OPTIMAL":
        return None

    slow = slow_placement_cost(data, placement)
    cvar_sla, cvar_sf = placement_risk(
        data, placement, fast, beta_sla=beta_sla, beta_sf=beta_sf
    )
    total = slow + fast.bandwidth_cost

    feasible_c = True
    if gamma_sla is not None and cvar_sla > float(gamma_sla) + 1e-9:
        feasible_c = False
    if gamma_sf is not None and cvar_sf > float(gamma_sf) + 1e-9:
        feasible_c = False

    obj_a = total + lambda_sla * cvar_sla + lambda_sf * cvar_sf
    obj_c = total if feasible_c else None

    return PlacementEvaluation(
        placement=dict(placement),
        placement_code=format_placement_code(data, placement),
        slow_cost=slow,
        fast_bandwidth_cost=fast.bandwidth_cost,
        total_cost=total,
        cvar_sla=cvar_sla,
        cvar_sf=cvar_sf,
        expected_delivery=fast.expected_delivery,
        fast_status=fast.status,
        fast_objective=fast_objective,
        bilevel_a_objective=obj_a,
        bilevel_c_feasible=feasible_c,
        bilevel_c_objective=obj_c,
    )


@dataclass
class BilevelSolveResult:
    status: str
    best: PlacementEvaluation | None
    evaluated_count: int
    feasible_count: int
    all_evaluations: list[PlacementEvaluation] = field(default_factory=list)
    wall_time_sec: float | None = None


def _enumerate_evaluations(
    data,
    *,
    omega_deliver: float,
    fast_objective: FastObjectiveMode = "delivery",
    lambda_sla: float = 0.0,
    lambda_sf: float = 0.0,
    gamma_sla: float | None = None,
    gamma_sf: float | None = None,
    beta_sla: float | None = None,
    beta_sf: float | None = None,
    time_limit: float | None = None,
) -> Iterator[PlacementEvaluation]:
    for placement in enumerate_placements(data):
        ev = evaluate_placement(
            data,
            placement,
            omega_deliver=omega_deliver,
            fast_objective=fast_objective,
            lambda_sla=lambda_sla,
            lambda_sf=lambda_sf,
            gamma_sla=gamma_sla,
            gamma_sf=gamma_sf,
            beta_sla=beta_sla,
            beta_sf=beta_sf,
            time_limit=time_limit,
        )
        if ev is not None:
            yield ev


def solve_bilevel_model_a(
    data,
    *,
    lambda_sla: float,
    lambda_sf: float = 0.0,
    omega_deliver: float = 1.0,
    fast_objective: FastObjectiveMode = "delivery",
    beta_sla: float | None = None,
    beta_sf: float | None = None,
    time_limit: float | None = None,
) -> BilevelSolveResult:
    """慢层 Model A（ω 仅作用于快层，见模块 docstring）。"""
    import time as _time

    t0 = _time.perf_counter()
    best: PlacementEvaluation | None = None
    all_ev: list[PlacementEvaluation] = []
    evaluated = 0

    for ev in _enumerate_evaluations(
        data,
        omega_deliver=omega_deliver,
        fast_objective=fast_objective,
        lambda_sla=lambda_sla,
        lambda_sf=lambda_sf,
        beta_sla=beta_sla,
        beta_sf=beta_sf,
        time_limit=time_limit,
    ):
        evaluated += 1
        all_ev.append(ev)
        if best is None or (ev.bilevel_a_objective or float("inf")) < (best.bilevel_a_objective or float("inf")):
            best = ev

    return BilevelSolveResult(
        status="OPTIMAL" if best is not None else "INFEASIBLE",
        best=best,
        evaluated_count=evaluated,
        feasible_count=evaluated,
        all_evaluations=all_ev,
        wall_time_sec=_time.perf_counter() - t0,
    )


def solve_bilevel_model_c(
    data,
    *,
    gamma_sla: float,
    gamma_sf: float | None = None,
    omega_deliver: float = 1.0,
    fast_objective: FastObjectiveMode = "delivery",
    beta_sla: float | None = None,
    beta_sf: float | None = None,
    time_limit: float | None = None,
) -> BilevelSolveResult:
    """慢层 Model C：min Cost(y)  s.t. post-hoc CVaR ≤ Γ。"""
    import time as _time

    t0 = _time.perf_counter()
    best: PlacementEvaluation | None = None
    all_ev: list[PlacementEvaluation] = []
    evaluated = 0
    feasible = 0

    for ev in _enumerate_evaluations(
        data,
        omega_deliver=omega_deliver,
        fast_objective=fast_objective,
        gamma_sla=gamma_sla,
        gamma_sf=gamma_sf,
        beta_sla=beta_sla,
        beta_sf=beta_sf,
        time_limit=time_limit,
    ):
        evaluated += 1
        all_ev.append(ev)
        if not ev.bilevel_c_feasible:
            continue
        feasible += 1
        if best is None or (ev.bilevel_c_objective or float("inf")) < (best.bilevel_c_objective or float("inf")):
            best = ev

    return BilevelSolveResult(
        status="OPTIMAL" if best is not None else "INFEASIBLE",
        best=best,
        evaluated_count=evaluated,
        feasible_count=feasible,
        all_evaluations=all_ev,
        wall_time_sec=_time.perf_counter() - t0,
    )


@dataclass
class BilevelCompareReport:
    bilevel: PlacementEvaluation
    single_layer_placement_code: str | None
    single_layer_cost: float | None
    single_layer_cvar_sla: float | None
    single_layer_cvar_sf: float | None
    placement_match: bool
    cost_gap: float | None
    cvar_sla_gap: float | None
    cvar_sf_gap: float | None


def compare_with_single_layer_a(
    data,
    *,
    lambda_sla: float,
    lambda_sf: float = 0.0,
    omega_deliver: float = 1.0,
    fast_objective: FastObjectiveMode = "delivery",
    time_limit: float = 120.0,
) -> BilevelCompareReport | None:
    """双层 Model A vs 单层 Model A（baseline comparison，非等价验证）。"""
    bi = solve_bilevel_model_a(
        data,
        lambda_sla=lambda_sla,
        lambda_sf=lambda_sf,
        omega_deliver=omega_deliver,
        fast_objective=fast_objective,
        time_limit=time_limit,
    )
    if bi.best is None:
        return None

    from exact_enumeration_solver import extract_model_a_result, placements_match
    from teavar_framework_models import build_teavar_model_a

    m, cost, lv, sfv, y, xi, xo, din, dout = build_teavar_model_a(
        data,
        lambda_sla=lambda_sla,
        lambda_sf=lambda_sf,
        omega_deliver=omega_deliver,
        time_limit=time_limit,
    )
    if m.status != GRB.OPTIMAL:
        return BilevelCompareReport(
            bilevel=bi.best,
            single_layer_placement_code=None,
            single_layer_cost=None,
            single_layer_cvar_sla=None,
            single_layer_cvar_sf=None,
            placement_match=False,
            cost_gap=None,
            cvar_sla_gap=None,
            cvar_sf_gap=None,
        )

    sl = extract_model_a_result(
        m, cost, lv, sfv, y, xi, xo, din, dout, data,
        lambda_sla=lambda_sla, lambda_sf=lambda_sf,
    )
    sl_code = format_placement_code(data, sl.placement)
    match = placements_match(bi.best.placement, sl.placement, data=data)

    return BilevelCompareReport(
        bilevel=bi.best,
        single_layer_placement_code=sl_code,
        single_layer_cost=sl.cost,
        single_layer_cvar_sla=sl.cvar_sla,
        single_layer_cvar_sf=sl.cvar_sf,
        placement_match=match,
        cost_gap=bi.best.total_cost - sl.cost,
        cvar_sla_gap=bi.best.cvar_sla - sl.cvar_sla,
        cvar_sf_gap=bi.best.cvar_sf - sl.cvar_sf,
    )


@dataclass
class BilevelCompareCReport:
    gamma_sla: float
    gamma_sf: float | None
    bilevel_status: str
    bilevel_placement_code: str | None
    bilevel_cost: float | None
    bilevel_cvar_sla: float | None
    bilevel_cvar_sf: float | None
    bilevel_edel: float | None
    bilevel_feasible_count: int
    bilevel_evaluated_count: int
    bilevel_runtime_sec: float | None
    single_status: str | None
    single_placement_code: str | None
    single_cost: float | None
    single_cvar_sla: float | None
    single_cvar_sf: float | None
    placement_match: bool | None
    cost_gap: float | None
    cvar_sla_gap: float | None
    cvar_sf_gap: float | None


def compare_bilevel_c_with_single_layer_c(
    data,
    *,
    gamma_sla: float,
    gamma_sf: float | None = None,
    omega_deliver: float = 1.0,
    fast_objective: FastObjectiveMode = "delivery",
    time_limit: float = 120.0,
    compare_single: bool = True,
) -> BilevelCompareCReport:
    """双层 Model C vs 单层 Model C（同一 Γ 网格点）。"""
    bi = solve_bilevel_model_c(
        data,
        gamma_sla=gamma_sla,
        gamma_sf=gamma_sf,
        omega_deliver=omega_deliver,
        fast_objective=fast_objective,
        time_limit=time_limit,
    )
    b = bi.best
    row = BilevelCompareCReport(
        gamma_sla=gamma_sla,
        gamma_sf=gamma_sf,
        bilevel_status=bi.status,
        bilevel_placement_code=b.placement_code if b else None,
        bilevel_cost=b.total_cost if b else None,
        bilevel_cvar_sla=b.cvar_sla if b else None,
        bilevel_cvar_sf=b.cvar_sf if b else None,
        bilevel_edel=b.expected_delivery if b else None,
        bilevel_feasible_count=bi.feasible_count,
        bilevel_evaluated_count=bi.evaluated_count,
        bilevel_runtime_sec=bi.wall_time_sec,
        single_status=None,
        single_placement_code=None,
        single_cost=None,
        single_cvar_sla=None,
        single_cvar_sf=None,
        placement_match=None,
        cost_gap=None,
        cvar_sla_gap=None,
        cvar_sf_gap=None,
    )

    if not compare_single:
        return row

    from exact_enumeration_solver import extract_model_c_result, placements_match
    from teavar_framework_models import build_teavar_model_c

    m, cost, lv, sfv, y, xi, xo, din, dout = build_teavar_model_c(
        data,
        gamma_sla=gamma_sla,
        gamma_sf=gamma_sf,
        omega_deliver=omega_deliver,
        time_limit=time_limit,
    )
    row.single_status = _status_name(m.status)
    if m.status != GRB.OPTIMAL:
        return row

    sl = extract_model_c_result(
        m, cost, lv, sfv, y, xi, xo, din, dout, data, gamma_sf=gamma_sf
    )
    row.single_placement_code = format_placement_code(data, sl.placement)
    row.single_cost = sl.cost
    row.single_cvar_sla = sl.cvar_sla
    row.single_cvar_sf = sl.cvar_sf
    if b is not None:
        row.placement_match = placements_match(b.placement, sl.placement, data=data)
        row.cost_gap = b.total_cost - sl.cost
        row.cvar_sla_gap = b.cvar_sla - sl.cvar_sla
        row.cvar_sf_gap = b.cvar_sf - sl.cvar_sf
    return row


# ---------------------------------------------------------------------------
# Strict risk-first lexicographic bilevel (SF → SLA → Cost; no λ/Γ/ε/ω)
# ---------------------------------------------------------------------------


def _lex_metric_value(row: "LexPlacementEvaluation", name: LexPriorityName) -> float:
    if name == "SF":
        return float(row.r_sf)
    if name == "SLA":
        return float(row.r_sla)
    if name == "Cost":
        return float(row.cost_total)
    raise ValueError(f"unknown lex priority metric: {name!r}")


@dataclass
class LexPlacementEvaluation:
    placement: dict[int, int]
    placement_code: str
    cost_deploy: float
    cost_bw: float
    cost_total: float
    r_sla: float
    r_sf: float
    e_del: float
    x_sum: float
    fast_status: str
    fast_objective: str
    in_Y1: bool = False
    in_Y2: bool = False
    is_best: bool = False


@dataclass
class BilevelLexResult:
    status: str
    best: LexPlacementEvaluation | None
    all_rows: list[LexPlacementEvaluation] = field(default_factory=list)
    R_sf_star: float | None = None
    R_sla_star: float | None = None
    cost_star: float | None = None
    Y1_count: int = 0
    Y2_count: int = 0
    best_count: int = 0
    priority: tuple[str, ...] = DEFAULT_LEX_PRIORITY
    fast_objective: str = "lex_sla_delivery_cost"
    wall_time_sec: float | None = None


def evaluate_placement_lex(
    data,
    placement: dict[int, int],
    *,
    fast_objective: FastObjectiveMode = "lex_sla_delivery_cost",
    beta_sla: float | None = None,
    beta_sf: float | None = None,
    time_limit: float | None = None,
    tol: float = _NUM_TOL,
) -> LexPlacementEvaluation | None:
    """Evaluate one placement for strict lexicographic bilevel (fast layer + post-hoc SF)."""
    fast = solve_fast_routing(
        data,
        placement,
        fast_objective=fast_objective,
        beta_sla=beta_sla,
        time_limit=time_limit,
        tol=tol,
    )
    if fast is None or fast.status != "OPTIMAL":
        return None

    cost_deploy = deployment_cost(data, placement)
    cost_bw = float(fast.bandwidth_cost)
    cost_total = cost_deploy + cost_bw
    cvar_sla, cvar_sf = placement_risk(
        data, placement, fast, beta_sla=beta_sla, beta_sf=beta_sf
    )
    r_sla = float(fast.cvar_sla if fast.cvar_sla is not None else cvar_sla)

    return LexPlacementEvaluation(
        placement=dict(placement),
        placement_code=format_placement_code(data, placement),
        cost_deploy=cost_deploy,
        cost_bw=cost_bw,
        cost_total=cost_total,
        r_sla=r_sla,
        r_sf=float(cvar_sf),
        e_del=float(fast.expected_delivery),
        x_sum=float(fast.x_sum),
        fast_status=fast.status,
        fast_objective=str(fast_objective),
    )


def apply_lex_stages(
    evaluations: Sequence[LexPlacementEvaluation],
    priority: Sequence[LexPriorityName] = DEFAULT_LEX_PRIORITY,
    tol: float = _NUM_TOL,
) -> tuple[
    dict[str, float],
    list[LexPlacementEvaluation],
    list[LexPlacementEvaluation],
    set[str],
    set[str],
]:
    """
    Apply strict lexicographic stages on enumerated rows.

    Returns (stage_stars, Y_final_before_cost, best_rows, Y1_codes, Y2_codes).
    ``Y1`` / ``Y2`` mark sets after the first and second priority stages when
    priority is (SF, SLA, Cost); for other orders the sets follow the same index rule.
    """
    if not evaluations:
        return {}, [], [], set(), set()
    if tuple(priority) != DEFAULT_LEX_PRIORITY:
        raise NotImplementedError(
            f"only priority {DEFAULT_LEX_PRIORITY} is implemented this round, got {tuple(priority)!r}"
        )
    if priority[-1] != "Cost":
        raise ValueError("last lex stage must be Cost")

    remaining = list(evaluations)
    stars: dict[str, float] = {}
    y_sets: list[set[str]] = []

    for stage in priority[:-1]:
        star = min(_lex_metric_value(row, stage) for row in remaining)
        stars[stage] = star
        remaining = [
            row for row in remaining if _lex_metric_value(row, stage) <= star + tol
        ]
        y_sets.append({row.placement_code for row in remaining})

    cost_star = min(row.cost_total for row in remaining)
    stars["Cost"] = cost_star
    best_rows = [row for row in remaining if row.cost_total <= cost_star + tol]

    y1 = y_sets[0] if len(y_sets) >= 1 else set()
    y2 = y_sets[1] if len(y_sets) >= 2 else set()
    return stars, remaining, best_rows, y1, y2


def solve_bilevel_lexicographic(
    data,
    *,
    priority: Sequence[LexPriorityName] = DEFAULT_LEX_PRIORITY,
    fast_objective: FastObjectiveMode = "lex_sla_delivery_cost",
    beta_sla: float | None = None,
    beta_sf: float | None = None,
    time_limit: float | None = None,
    tol: float = _NUM_TOL,
) -> BilevelLexResult:
    """
    Strict risk-first lexicographic bilevel TEAVAR (enumerative L0).

    Default priority: SF → SLA → Cost. No λ, Γ, ε, or ω.
    """
    import time as _time

    t0 = _time.perf_counter()
    rows: list[LexPlacementEvaluation] = []
    for placement in enumerate_placements(data):
        ev = evaluate_placement_lex(
            data,
            placement,
            fast_objective=fast_objective,
            beta_sla=beta_sla,
            beta_sf=beta_sf,
            time_limit=time_limit,
            tol=tol,
        )
        if ev is not None:
            rows.append(ev)

    if not rows:
        return BilevelLexResult(
            status="INFEASIBLE",
            best=None,
            all_rows=[],
            priority=tuple(priority),
            fast_objective=str(fast_objective),
            wall_time_sec=_time.perf_counter() - t0,
        )

    stars, _y_final, best_rows, y1_codes, y2_codes = apply_lex_stages(
        rows, priority=priority, tol=tol
    )

    for row in rows:
        row.in_Y1 = row.placement_code in y1_codes
        row.in_Y2 = row.placement_code in y2_codes
        row.is_best = row.placement_code in {b.placement_code for b in best_rows}

    best = min(best_rows, key=lambda r: (r.cost_total, r.placement_code)) if best_rows else None

    return BilevelLexResult(
        status="OPTIMAL" if best is not None else "INFEASIBLE",
        best=best,
        all_rows=rows,
        R_sf_star=stars.get("SF"),
        R_sla_star=stars.get("SLA"),
        cost_star=stars.get("Cost"),
        Y1_count=len(y1_codes),
        Y2_count=len(y2_codes),
        best_count=len(best_rows),
        priority=tuple(priority),
        fast_objective=str(fast_objective),
        wall_time_sec=_time.perf_counter() - t0,
    )


def lex_resolved_config(
    data,
    *,
    priority: Sequence[LexPriorityName] = DEFAULT_LEX_PRIORITY,
    fast_objective: str = "lex_sla_delivery_cost",
) -> dict:
    """Resolved config snapshot for smoke / report output."""
    return {
        "instance": getattr(data, "instance_name", "Toy-Combined-ComponentRisk"),
        "scenarios": "component_independent",
        "n_scenarios": len(data.S),
        "bandwidth_mode": getattr(data, "bandwidth_mode", "unknown"),
        "bandwidth_cost_on_placement": bool(getattr(data, "bandwidth_cost_on_placement", False)),
        "fast_objective": fast_objective,
        "priority": list(priority),
        "beta_sla": float(getattr(data, "beta_N", 0.0)),
        "beta_sf": float(getattr(data, "beta_N", 0.0)),
        "pricing_mode": getattr(data, "bandwidth_price_mode", "unknown"),
        "model": "Strict risk-first lexicographic bilevel TEAVAR",
    }
