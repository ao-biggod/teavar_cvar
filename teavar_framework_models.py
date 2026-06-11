# -*- coding: utf-8 -*-
"""
TEAVAR 视角（SLA 需求损失 CVaR + 可选算力未满足 CVaR）与 duibi.py 四种运筹架构对齐：

- Model A：单层加权  min  c_p+c_b - ω·E[Del] + λ_sla·CVaR_SLA + λ_sf·CVaR_sf
- Model B：在 Model A 目标下，对 SLA 的 Rockafellar–Uryasev 子问题加 KKT 式 Indicator 互补（与 duibi KKT 同构）；
           若 λ_sf>0 且启用 sf，则对算力未满足 CVaR 的 φ 层再加一套 KKT Indicator。
- Model C：ε-约束  min  c_p+c_b - ω·E[Del]  s.t.  CVaR_SLA ≤ Γ_sla ，（可选）CVaR_sf ≤ Γ_sf
- Model D：min  c_p+c_b - ω·E[Del] ，对上述 KKT 互补用 McCormick 线性包络松弛（与 duibi Copo 同构）

约定：与 `duibi` 一致，路径锚点由 `teavar_flow_anchors(data)` 给出（hub 径向 `(h,h)` 或 UMCF `(V_s,V_t)`）；放置与 `min_off_hub` 仍用 `getattr(data,'hub',0)`。
不含 duibi 的链路/节点「利用率」CVaR，以便与上文「SLA + 算力未满足」叙述一致。
"""
from __future__ import annotations

import gurobipy as gp
from gurobipy import GRB

from duibi_metrics import bandwidth_cost_expr, path_up, placement_bandwidth_cost_expr, teavar_flow_anchors
from cvar_compare import (
    add_compute_sf_cvar_ru,
    add_link_nominal_capacity_constraints,
    add_scenario_delivery_coupling,
    add_teavar_virtual_bottleneck_constraints,
    _is_per_task_od,
    _task_flow_anchors,
)


def _require_hub_routing_for_model(data, model_name: str) -> None:
    if _is_per_task_od(data):
        raise NotImplementedError(
            f"{model_name} does not support routing_mode='per_task_od' yet; use Model A or Model C."
        )


def _hub(data) -> int:
    return int(getattr(data, "hub", 0))


def build_teavar_model_a(
    data,
    lambda_sla: float,
    lambda_sf: float,
    omega_deliver: float = 1.0,
    beta_loss=None,
    beta_sf=None,
    min_tasks_off_hub: int = 0,
    time_limit: float | None = None,
    mip_gap: float | None = None,
):
    """
    Model A：与 `cvar_compare.build_teavar_sla_cvar_model` 对齐（关闭 nodeUtil 项）。
    返回 (m, cost, cvar_sla, cvar_sf, y, xin, xout, del_in, del_out)；非最优时 cost 等为 None。
    """
    from cvar_compare import build_teavar_sla_cvar_model

    m, cp, lv, _nv, sfv, y, xi, xo, din, dout = build_teavar_sla_cvar_model(
        data,
        lambda_cvar=lambda_sla,
        omega_deliver=omega_deliver,
        beta_loss=beta_loss,
        min_tasks_off_node0=min_tasks_off_hub,
        lambda_node_cvar=0.0,
        lambda_compute_sf_cvar=lambda_sf,
        beta_compute_sf=beta_sf,
        time_limit=time_limit,
        mip_gap=mip_gap,
    )
    if m.status not in (GRB.OPTIMAL, GRB.TIME_LIMIT, GRB.SUBOPTIMAL) or cp is None or m.SolCount == 0:
        return m, None, None, None, y, xi, xo, din, dout
    return m, cp, lv, float(sfv or 0.0), y, xi, xo, din, dout


def build_teavar_model_c(
    data,
    gamma_sla: float,
    gamma_sf: float | None,
    omega_deliver: float = 1.0,
    beta_loss=None,
    beta_sf=None,
    min_tasks_off_hub: int = 0,
    *,
    include_sf_budget: bool = True,
    time_limit: float | None = None,
    mip_gap: float | None = None,
):
    """
    Model C：min c_p+c_b - ω·E[Del]  s.t. CVaR_SLA ≤ Γ_sla ；（可选）CVaR_sf ≤ Γ_sf 。
    include_sf_budget=False 时不建算力未满足 CVaR 块（Γ_sf 忽略）。

    ``routing_mode='per_task_od'`` 时与 ``build_teavar_sla_cvar_model`` 相同按 task_src/dst 建流。
    """
    h = _hub(data)
    per_task = _is_per_task_od(data)
    if per_task:
        in_u, out_v = teavar_flow_anchors(data, data.I[0])
    else:
        in_u, out_v = teavar_flow_anchors(data)
    src, dst = in_u, out_v
    if beta_loss is None:
        beta_loss = data.beta_N
    b_sf = beta_sf if beta_sf is not None else data.beta_N
    use_sf = bool(include_sf_budget and gamma_sf is not None and gamma_sf < 1e20)

    m = gp.Model("TEAVAR_Model_C_Epsilon")
    m.setParam("OutputFlag", 0)
    if time_limit is not None:
        m.setParam("TimeLimit", float(time_limit))
    if mip_gap is not None:
        m.setParam("MIPGap", float(mip_gap))

    y = m.addVars(data.valid_assign, vtype=GRB.BINARY, name="y")

    if per_task:
        xin = {}
        xout = {}
        for i in data.I:
            iu, ov = teavar_flow_anchors(data, i)
            for node in data.M:
                if (i, node) not in data.valid_assign:
                    continue
                for p in range(len(data.P_cand[iu, node])):
                    xin[i, node, p] = m.addVar(lb=0, name=f"xin_{i}_{node}_{p}")
                for q in range(len(data.P_cand[node, ov])):
                    xout[i, node, q] = m.addVar(lb=0, name=f"xout_{i}_{node}_{q}")
    else:
        xin = {
            (i, node, p): m.addVar(lb=0)
            for i in data.I
            for node in data.M
            for p in range(len(data.P_cand[src, node]))
        }
        xout = {
            (i, node, q): m.addVar(lb=0)
            for i in data.I
            for node in data.M
            for q in range(len(data.P_cand[node, dst]))
        }

    del_in = {}
    del_out = {}
    for s in data.S:
        for i in data.I:
            iu, ov = _task_flow_anchors(data, i, in_u, out_v)
            for node in data.M:
                if per_task and (i, node) not in data.valid_assign:
                    continue
                for p in range(len(data.P_cand[iu, node])):
                    del_in[i, node, p, s] = m.addVar(lb=0, name=f"din_{i}_{node}_{p}_{s}")
                for q in range(len(data.P_cand[node, ov])):
                    del_out[i, node, q, s] = m.addVar(lb=0, name=f"dout_{i}_{node}_{q}_{s}")

    zeta = m.addVar(lb=-GRB.INFINITY, name="zeta_sla")
    u_s = m.addVars(data.S, lb=0, name="u_sla")

    cost_p = gp.quicksum(y[i, node] * sum(data.w[i][k] * data.p_price[node][k] for k in data.K) for i, node in y)
    if getattr(data, "bandwidth_cost_on_placement", False):
        cost_b = placement_bandwidth_cost_expr(data, y)
    else:
        cost_b = bandwidth_cost_expr(data, xin, xout, None, None)
    loss_cvar = zeta + (1.0 / (1.0 - beta_loss)) * gp.quicksum(data.prob[s] * u_s[s] for s in data.S)

    zeta_sf = phi_s = shortfall_cvar = None
    d_mk = {}
    if use_sf:
        zeta_sf, phi_s, shortfall_cvar, d_mk = add_compute_sf_cvar_ru(
            m, data, y, beta_sf=b_sf
        )

    task_anchors = {i: _task_flow_anchors(data, i, in_u, out_v) for i in data.I}
    exp_deliver = gp.quicksum(
        data.prob[s]
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
    m.setObjective(cost_p + cost_b - omega_deliver * exp_deliver, GRB.MINIMIZE)

    m.addConstrs((y.sum(i, "*") == 1 for i in data.I))
    if min_tasks_off_hub and min_tasks_off_hub > 0:
        m.addConstr(gp.quicksum(y[i, h] for i in data.I if (i, h) in y) <= len(data.I) - min_tasks_off_hub)

    for i in data.I:
        iu, ov = _task_flow_anchors(data, i, in_u, out_v)
        for node in data.M:
            if (i, node) not in data.valid_assign:
                continue
            m.addConstr(
                gp.quicksum(xin[i, node, p] for p in range(len(data.P_cand[iu, node])) if (i, node, p) in xin)
                <= y[i, node] * data.b_in[i]
            )
            m.addConstr(
                gp.quicksum(xout[i, node, q] for q in range(len(data.P_cand[node, ov])) if (i, node, q) in xout)
                <= y[i, node] * data.b_out[i]
            )

    for node in data.M:
        for k in data.K:
            m.addConstr(
                gp.quicksum(y[i, node] * data.w[i][k] for i in data.I if (i, node) in y)
                <= data.C_normal[node][k]
            )

    add_link_nominal_capacity_constraints(m, data, xin, xout)

    add_scenario_delivery_coupling(m, data, y, xin, xout, del_in, del_out, in_u, out_v)
    add_teavar_virtual_bottleneck_constraints(m, data, y, del_in, del_out, h)

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
            m.addConstr(u_s[s] * data.b_in[i] >= data.b_in[i] - Rin - data.b_in[i] * zeta)
            m.addConstr(u_s[s] * data.b_out[i] >= data.b_out[i] - Rout - data.b_out[i] * zeta)

    m.addConstr(loss_cvar <= gamma_sla, name="Gamma_SLA")
    if use_sf and shortfall_cvar is not None:
        m.addConstr(shortfall_cvar <= float(gamma_sf), name="Gamma_SF")

    m.optimize()
    if m.status != GRB.OPTIMAL:
        return m, None, None, None, y, xin, xout, del_in, del_out
    cp = cost_p.getValue() + cost_b.getValue()
    lv = loss_cvar.getValue()
    sfv = float(shortfall_cvar.getValue()) if use_sf and shortfall_cvar is not None else 0.0
    return m, cp, lv, sfv, y, xin, xout, del_in, del_out


def _slack_max_teavar_sla(data) -> float:
    """SLA KKT/McCormick 中 slack 的保守尺度。"""
    return 5.0 + max(max(data.b_in.values()), max(data.b_out.values()))


def _slack_max_teavar_sf(data) -> float:
    d_max_any = max(
        float(sum(data.w[i][k] for i in data.I)) for k in data.K for _ in data.M
    )
    Cmax = max(float(data.C_s[m][k][s]) for m in data.M for k in data.K for s in data.S)
    M_ex = max(d_max_any + 1.0, Cmax + 1.0, 1.0)
    return max(50.0, 3.0 * M_ex / max(M_ex * 1e-9, 1.0))


def build_teavar_model_b(
    data,
    lambda_sla: float,
    lambda_sf: float,
    omega_deliver: float = 1.0,
    beta_loss=None,
    beta_sf=None,
    min_tasks_off_hub: int = 0,
    *,
    kkt_sf: bool = True,
):
    """
    Model B：与 Model A 相同目标，并对 SLA 的 (u_s,ζ) 子结构加 KKT Indicator；可选对算力未满足 CVaR 的 φ 层加 KKT。
    kkt_sf=False 时仅 SLA 侧加 Indicator（算力 sf 仍线性进入目标，无互补）。
    """
    _require_hub_routing_for_model(data, "Model B")
    h = _hub(data)
    src, dst = teavar_flow_anchors(data)
    if beta_loss is None:
        beta_loss = data.beta_N
    b_sf = beta_sf if beta_sf is not None else data.beta_N
    use_sf = bool(lambda_sf and lambda_sf > 0.0)

    m = gp.Model("TEAVAR_Model_B_KKT")
    m.setParam("OutputFlag", 0)
    m.setParam("MIPGap", 0.05)

    Mbig = max(max(data.b_in.values()), max(data.b_out.values())) + 1.0

    y = m.addVars(data.valid_assign, vtype=GRB.BINARY, name="y")
    xin = {(i, node, p): m.addVar(lb=0) for i in data.I for node in data.M for p in range(len(data.P_cand[src, node]))}
    xout = {(i, node, q): m.addVar(lb=0) for i in data.I for node in data.M for q in range(len(data.P_cand[node, dst]))}

    del_in = {}
    del_out = {}
    for s in data.S:
        for i in data.I:
            for node in data.M:
                for p in range(len(data.P_cand[src, node])):
                    del_in[i, node, p, s] = m.addVar(lb=0)
                for q in range(len(data.P_cand[node, dst])):
                    del_out[i, node, q, s] = m.addVar(lb=0)

    zeta = m.addVar(lb=-GRB.INFINITY, name="zeta_sla")
    u_s = m.addVars(data.S, lb=0, name="u_sla")

    cost_p = gp.quicksum(y[i, node] * sum(data.w[i][k] * data.p_price[node][k] for k in data.K) for i, node in y)
    cost_b = bandwidth_cost_expr(data, xin, xout, src, dst)
    loss_cvar = zeta + (1.0 / (1.0 - beta_loss)) * gp.quicksum(data.prob[s] * u_s[s] for s in data.S)

    zeta_sf = phi_s = shortfall_cvar = None
    d_mk = {}
    e_ex = {}
    if use_sf:
        d_max_any = 0.0
        for node in data.M:
            for k in data.K:
                dmax = float(sum(data.w[i][k] for i in data.I))
                d_max_any = max(d_max_any, dmax)
        Cmax = max(float(data.C_s[mm][kk][ss]) for mm in data.M for kk in data.K for ss in data.S)
        M_ex = max(d_max_any + 1.0, Cmax + 1.0, 1.0)
        D_ref = M_ex
        for node in data.M:
            for k in data.K:
                d_mk[node, k] = m.addVar(lb=0.0)
                m.addConstr(d_mk[node, k] == gp.quicksum(y[i, node] * data.w[i][k] for i in data.I))
        w_ex = {}
        for s in data.S:
            for node in data.M:
                for k in data.K:
                    Ccap = float(data.C_s[node][k][s])
                    x = d_mk[node, k] - Ccap
                    e_ex[node, k, s] = m.addVar(lb=0.0)
                    w_ex[node, k, s] = m.addVar(vtype=GRB.BINARY)
                    m.addConstr(e_ex[node, k, s] >= x)
                    m.addConstr(e_ex[node, k, s] >= 0)
                    m.addConstr(e_ex[node, k, s] <= x + M_ex * (1 - w_ex[node, k, s]))
                    m.addConstr(e_ex[node, k, s] <= M_ex * w_ex[node, k, s])
        zeta_sf = m.addVar(lb=-GRB.INFINITY, name="zeta_sf")
        phi_s = m.addVars(data.S, lb=0.0, name="phi_sf")
        for s in data.S:
            for node in data.M:
                for k in data.K:
                    m.addConstr(phi_s[s] >= e_ex[node, k, s] / D_ref - zeta_sf)
        shortfall_cvar = zeta_sf + (1.0 / (1.0 - b_sf)) * gp.quicksum(data.prob[s] * phi_s[s] for s in data.S)
    else:
        shortfall_cvar = 0.0

    exp_deliver = gp.quicksum(
        data.prob[s]
        * (
            gp.quicksum(del_in[i, node, p, s] for i in data.I for node in data.M for p in range(len(data.P_cand[src, node])))
            + gp.quicksum(
                del_out[i, node, q, s] for i in data.I for node in data.M for q in range(len(data.P_cand[node, dst]))
            )
        )
        for s in data.S
    )
    obj = cost_p + cost_b + lambda_sla * loss_cvar - omega_deliver * exp_deliver
    if use_sf and zeta_sf is not None:
        obj += lambda_sf * shortfall_cvar
    m.setObjective(obj, GRB.MINIMIZE)

    m.addConstrs((y.sum(i, "*") == 1 for i in data.I))
    if min_tasks_off_hub and min_tasks_off_hub > 0:
        m.addConstr(gp.quicksum(y[i, h] for i in data.I) <= len(data.I) - min_tasks_off_hub)

    for i in data.I:
        for node in data.M:
            m.addConstr(gp.quicksum(xin[i, node, p] for p in range(len(data.P_cand[src, node]))) <= y[i, node] * data.b_in[i])
            m.addConstr(gp.quicksum(xout[i, node, q] for q in range(len(data.P_cand[node, dst]))) <= y[i, node] * data.b_out[i])

    for node in data.M:
        for k in data.K:
            m.addConstr(gp.quicksum(y[i, node] * data.w[i][k] for i in data.I) <= data.C_normal[node][k])

    for s in data.S:
        for i in data.I:
            for node in data.M:
                for p in range(len(data.P_cand[src, node])):
                    di, xi = del_in[i, node, p, s], xin[i, node, p]
                    if path_up(data, src, node, p, s):
                        m.addConstr(di <= xi)
                        m.addConstr(di <= Mbig * y[i, node])
                        m.addConstr(di >= xi - Mbig * (1 - y[i, node]))
                    else:
                        m.addConstr(di == 0)
                for q in range(len(data.P_cand[node, dst])):
                    do, xo = del_out[i, node, q, s], xout[i, node, q]
                    if path_up(data, node, dst, q, s):
                        m.addConstr(do <= xo)
                        m.addConstr(do <= Mbig * y[i, node])
                        m.addConstr(do >= xo - Mbig * (1 - y[i, node]))
                    else:
                        m.addConstr(do == 0)

    add_teavar_virtual_bottleneck_constraints(m, data, y, del_in, del_out, h)

    for s in data.S:
        for i in data.I:
            Rin = gp.quicksum(del_in[i, node, p, s] for node in data.M for p in range(len(data.P_cand[src, node])))
            Rout = gp.quicksum(del_out[i, node, q, s] for node in data.M for q in range(len(data.P_cand[node, dst])))
            m.addConstr(u_s[s] * data.b_in[i] >= data.b_in[i] - Rin - data.b_in[i] * zeta)
            m.addConstr(u_s[s] * data.b_out[i] >= data.b_out[i] - Rout - data.b_out[i] * zeta)

    # ----- KKT：SLA（对每个 (s,i) 的 in/out 探测行）-----
    lam_sla = m.addVars(
        [(s, i, t) for s in data.S for i in data.I for t in (0, 1)],
        lb=0.0,
        name="lam_sla",
    )
    mu_sla = m.addVars(data.S, lb=0.0, name="mu_sla")
    z_lam_sla = m.addVars([(s, i, t) for s in data.S for i in data.I for t in (0, 1)], vtype=GRB.BINARY, name="z_lam_sla")
    z_mu_sla = m.addVars(data.S, vtype=GRB.BINARY, name="z_mu_sla")

    m.addConstr(gp.quicksum(lam_sla[s, i, t] for s in data.S for i in data.I for t in (0, 1)) == 1)
    slack_max_sla = _slack_max_teavar_sla(data)

    for s in data.S:
        lam_row = gp.quicksum(lam_sla[s, i, t] for i in data.I for t in (0, 1))
        m.addConstr(lam_row + mu_sla[s] == data.prob[s] / (1.0 - beta_loss))
        for i in data.I:
            Rin = gp.quicksum(del_in[i, node, p, s] for node in data.M for p in range(len(data.P_cand[src, node])))
            Rout = gp.quicksum(del_out[i, node, q, s] for node in data.M for q in range(len(data.P_cand[node, dst])))
            # slack_in = u_s - (1 - Rin/b_in) + zeta
            expr_in = u_s[s] - 1.0 + Rin / float(data.b_in[i]) + zeta
            m.addConstr(expr_in >= 0)
            m.addGenConstrIndicator(z_lam_sla[s, i, 0], True, expr_in == 0)
            m.addGenConstrIndicator(z_lam_sla[s, i, 0], False, lam_sla[s, i, 0] == 0)
            expr_out = u_s[s] - 1.0 + Rout / float(data.b_out[i]) + zeta
            m.addConstr(expr_out >= 0)
            m.addGenConstrIndicator(z_lam_sla[s, i, 1], True, expr_out == 0)
            m.addGenConstrIndicator(z_lam_sla[s, i, 1], False, lam_sla[s, i, 1] == 0)
        m.addGenConstrIndicator(z_mu_sla[s], True, u_s[s] == 0)
        m.addGenConstrIndicator(z_mu_sla[s], False, mu_sla[s] == 0)

    # ----- 可选 KKT：算力未满足 φ -----
    if use_sf and kkt_sf and phi_s is not None and zeta_sf is not None:
        lam_sf = m.addVars([(s, node, k) for s in data.S for node in data.M for k in data.K], lb=0.0, name="lam_sf")
        mu_sf = m.addVars(data.S, lb=0.0, name="mu_sf")
        z_lam_sf = m.addVars(
            [(s, node, k) for s in data.S for node in data.M for k in data.K], vtype=GRB.BINARY, name="z_lam_sf"
        )
        z_mu_sf = m.addVars(data.S, vtype=GRB.BINARY, name="z_mu_sf")
        d_max_any = max(
            float(sum(data.w[i][k] for i in data.I)) for k in data.K for _ in data.M
        )
        Cmax = max(float(data.C_s[mm][kk][ss]) for mm in data.M for kk in data.K for ss in data.S)
        M_ex = max(d_max_any + 1.0, Cmax + 1.0, 1.0)
        D_ref = M_ex

        m.addConstr(gp.quicksum(lam_sf[s, node, k] for s in data.S for node in data.M for k in data.K) == 1)
        for s in data.S:
            lam_row = gp.quicksum(lam_sf[s, node, k] for node in data.M for k in data.K)
            m.addConstr(lam_row + mu_sf[s] == data.prob[s] / (1.0 - b_sf))
            for node in data.M:
                for k in data.K:
                    expr = phi_s[s] - e_ex[node, k, s] / D_ref + zeta_sf
                    m.addConstr(expr >= 0)
                    m.addGenConstrIndicator(z_lam_sf[s, node, k], True, expr == 0)
                    m.addGenConstrIndicator(z_lam_sf[s, node, k], False, lam_sf[s, node, k] == 0)
            m.addGenConstrIndicator(z_mu_sf[s], True, phi_s[s] == 0)
            m.addGenConstrIndicator(z_mu_sf[s], False, mu_sf[s] == 0)

    m.optimize()
    if m.status != GRB.OPTIMAL:
        return m, None, None, None, y, xin, xout, del_in, del_out
    cp = cost_p.getValue() + cost_b.getValue()
    lv = loss_cvar.getValue()
    sfv = float(shortfall_cvar.getValue()) if use_sf else 0.0
    return m, cp, lv, sfv, y, xin, xout, del_in, del_out


def build_teavar_model_d(
    data,
    omega_deliver: float = 1.0,
    beta_loss=None,
    beta_sf=None,
    min_tasks_off_hub: int = 0,
    *,
    include_sf: bool = True,
):
    """
    Model D：min c_p+c_b - ω·E[Del]；对 SLA 与（可选）算力 sf 的 KKT 互补用 McCormick 包络代替 Indicator。
    """
    _require_hub_routing_for_model(data, "Model D")
    h = _hub(data)
    src, dst = teavar_flow_anchors(data)
    if beta_loss is None:
        beta_loss = data.beta_N
    b_sf = beta_sf if beta_sf is not None else data.beta_N

    m = gp.Model("TEAVAR_Model_D_McCormick")
    m.setParam("OutputFlag", 0)
    m.setParam("MIPGap", 0.05)

    Mbig = max(max(data.b_in.values()), max(data.b_out.values())) + 1.0

    y = m.addVars(data.valid_assign, vtype=GRB.BINARY, name="y")
    xin = {(i, node, p): m.addVar(lb=0) for i in data.I for node in data.M for p in range(len(data.P_cand[src, node]))}
    xout = {(i, node, q): m.addVar(lb=0) for i in data.I for node in data.M for q in range(len(data.P_cand[node, dst]))}

    del_in = {}
    del_out = {}
    for s in data.S:
        for i in data.I:
            for node in data.M:
                for p in range(len(data.P_cand[src, node])):
                    del_in[i, node, p, s] = m.addVar(lb=0)
                for q in range(len(data.P_cand[node, dst])):
                    del_out[i, node, q, s] = m.addVar(lb=0)

    zeta = m.addVar(lb=-GRB.INFINITY, name="zeta_sla")
    u_s = m.addVars(data.S, lb=0, name="u_sla")

    cost_p = gp.quicksum(y[i, node] * sum(data.w[i][k] * data.p_price[node][k] for k in data.K) for i, node in y)
    cost_b = bandwidth_cost_expr(data, xin, xout, src, dst)

    zeta_sf = phi_s = None
    e_ex = {}
    if include_sf:
        d_mk = {}
        d_max_any = 0.0
        for node in data.M:
            for k in data.K:
                dmax = float(sum(data.w[i][k] for i in data.I))
                d_max_any = max(d_max_any, dmax)
        Cmax = max(float(data.C_s[mm][kk][ss]) for mm in data.M for kk in data.K for ss in data.S)
        M_ex = max(d_max_any + 1.0, Cmax + 1.0, 1.0)
        D_ref = M_ex
        for node in data.M:
            for k in data.K:
                d_mk[node, k] = m.addVar(lb=0.0)
                m.addConstr(d_mk[node, k] == gp.quicksum(y[i, node] * data.w[i][k] for i in data.I))
        w_ex = {}
        for s in data.S:
            for node in data.M:
                for k in data.K:
                    Ccap = float(data.C_s[node][k][s])
                    x = d_mk[node, k] - Ccap
                    e_ex[node, k, s] = m.addVar(lb=0.0)
                    w_ex[node, k, s] = m.addVar(vtype=GRB.BINARY)
                    m.addConstr(e_ex[node, k, s] >= x)
                    m.addConstr(e_ex[node, k, s] >= 0)
                    m.addConstr(e_ex[node, k, s] <= x + M_ex * (1 - w_ex[node, k, s]))
                    m.addConstr(e_ex[node, k, s] <= M_ex * w_ex[node, k, s])
        zeta_sf = m.addVar(lb=-GRB.INFINITY, name="zeta_sf")
        phi_s = m.addVars(data.S, lb=0.0, name="phi_sf")
        for s in data.S:
            for node in data.M:
                for k in data.K:
                    m.addConstr(phi_s[s] >= e_ex[node, k, s] / D_ref - zeta_sf)

    exp_deliver = gp.quicksum(
        data.prob[s]
        * (
            gp.quicksum(del_in[i, node, p, s] for i in data.I for node in data.M for p in range(len(data.P_cand[src, node])))
            + gp.quicksum(
                del_out[i, node, q, s] for i in data.I for node in data.M for q in range(len(data.P_cand[node, dst]))
            )
        )
        for s in data.S
    )
    m.setObjective(cost_p + cost_b - omega_deliver * exp_deliver, GRB.MINIMIZE)

    m.addConstrs((y.sum(i, "*") == 1 for i in data.I))
    if min_tasks_off_hub and min_tasks_off_hub > 0:
        m.addConstr(gp.quicksum(y[i, h] for i in data.I) <= len(data.I) - min_tasks_off_hub)

    for i in data.I:
        for node in data.M:
            m.addConstr(gp.quicksum(xin[i, node, p] for p in range(len(data.P_cand[src, node]))) <= y[i, node] * data.b_in[i])
            m.addConstr(gp.quicksum(xout[i, node, q] for q in range(len(data.P_cand[node, dst]))) <= y[i, node] * data.b_out[i])

    for node in data.M:
        for k in data.K:
            m.addConstr(gp.quicksum(y[i, node] * data.w[i][k] for i in data.I) <= data.C_normal[node][k])

    for s in data.S:
        for i in data.I:
            for node in data.M:
                for p in range(len(data.P_cand[src, node])):
                    di, xi = del_in[i, node, p, s], xin[i, node, p]
                    if path_up(data, src, node, p, s):
                        m.addConstr(di <= xi)
                        m.addConstr(di <= Mbig * y[i, node])
                        m.addConstr(di >= xi - Mbig * (1 - y[i, node]))
                    else:
                        m.addConstr(di == 0)
                for q in range(len(data.P_cand[node, dst])):
                    do, xo = del_out[i, node, q, s], xout[i, node, q]
                    if path_up(data, node, dst, q, s):
                        m.addConstr(do <= xo)
                        m.addConstr(do <= Mbig * y[i, node])
                        m.addConstr(do >= xo - Mbig * (1 - y[i, node]))
                    else:
                        m.addConstr(do == 0)

    add_teavar_virtual_bottleneck_constraints(m, data, y, del_in, del_out, h)

    for s in data.S:
        for i in data.I:
            Rin = gp.quicksum(del_in[i, node, p, s] for node in data.M for p in range(len(data.P_cand[src, node])))
            Rout = gp.quicksum(del_out[i, node, q, s] for node in data.M for q in range(len(data.P_cand[node, dst])))
            m.addConstr(u_s[s] * data.b_in[i] >= data.b_in[i] - Rin - data.b_in[i] * zeta)
            m.addConstr(u_s[s] * data.b_out[i] >= data.b_out[i] - Rout - data.b_out[i] * zeta)

    # McCormick：SLA
    lam_sla = m.addVars([(s, i, t) for s in data.S for i in data.I for t in (0, 1)], lb=0.0, name="lam_sla_d")
    mu_sla = m.addVars(data.S, lb=0.0, name="mu_sla_d")
    slack_sla = m.addVars([(s, i, t) for s in data.S for i in data.I for t in (0, 1)], lb=0.0, name="slack_sla_d")
    slack_max_sla = _slack_max_teavar_sla(data)

    m.addConstr(gp.quicksum(lam_sla[s, i, t] for s in data.S for i in data.I for t in (0, 1)) == 1)
    for s in data.S:
        lam_row = gp.quicksum(lam_sla[s, i, t] for i in data.I for t in (0, 1))
        m.addConstr(lam_row + mu_sla[s] == data.prob[s] / (1.0 - beta_loss))
        lam_max = data.prob[s] / (1.0 - beta_loss)
        for i in data.I:
            Rin = gp.quicksum(del_in[i, node, p, s] for node in data.M for p in range(len(data.P_cand[src, node])))
            Rout = gp.quicksum(del_out[i, node, q, s] for node in data.M for q in range(len(data.P_cand[node, dst])))
            m.addConstr(slack_sla[s, i, 0] == u_s[s] - 1.0 + Rin / float(data.b_in[i]) + zeta)
            m.addConstr(lam_sla[s, i, 0] / lam_max + slack_sla[s, i, 0] / slack_max_sla <= 1.0)
            m.addConstr(slack_sla[s, i, 1] == u_s[s] - 1.0 + Rout / float(data.b_out[i]) + zeta)
            m.addConstr(lam_sla[s, i, 1] / lam_max + slack_sla[s, i, 1] / slack_max_sla <= 1.0)
        m.addConstr(mu_sla[s] / lam_max + u_s[s] / slack_max_sla <= 1.0)

    if include_sf and phi_s is not None and zeta_sf is not None:
        lam_sf = m.addVars([(s, node, k) for s in data.S for node in data.M for k in data.K], lb=0.0, name="lam_sf_d")
        mu_sf = m.addVars(data.S, lb=0.0, name="mu_sf_d")
        slack_sf = m.addVars([(s, node, k) for s in data.S for node in data.M for k in data.K], lb=0.0, name="slack_sf_d")
        slack_max_sf = _slack_max_teavar_sf(data)
        m.addConstr(gp.quicksum(lam_sf[s, node, k] for s in data.S for node in data.M for k in data.K) == 1)
        for s in data.S:
            lam_row = gp.quicksum(lam_sf[s, node, k] for node in data.M for k in data.K)
            alpha_max = data.prob[s] / (1.0 - b_sf)
            m.addConstr(lam_row + mu_sf[s] == alpha_max)
            for node in data.M:
                for k in data.K:
                    m.addConstr(slack_sf[s, node, k] == phi_s[s] - e_ex[node, k, s] / D_ref + zeta_sf)
                    m.addConstr(lam_sf[s, node, k] / alpha_max + slack_sf[s, node, k] / slack_max_sf <= 1.0)
            m.addConstr(mu_sf[s] / alpha_max + phi_s[s] / slack_max_sf <= 1.0)

    m.optimize()
    if m.status != GRB.OPTIMAL:
        return m, None, None, None, y, xin, xout, del_in, del_out
    cp = cost_p.getValue() + cost_b.getValue()
    zv = zeta.X + (1.0 / (1.0 - beta_loss)) * sum(data.prob[s] * u_s[s].X for s in data.S)
    sfv = 0.0
    if include_sf and phi_s is not None and zeta_sf is not None:
        sfv = zeta_sf.X + (1.0 / (1.0 - b_sf)) * sum(data.prob[s] * phi_s[s].X for s in data.S)
    return m, cp, zv, sfv, y, xin, xout, del_in, del_out


def _dist_str(data, yv):
    dist = {n: int(sum(yv[i, n].X for i in data.I if yv[i, n].X > 0.5)) for n in data.M}
    return ", ".join(f"{k}:{v}" for k, v in dist.items() if v > 0)


if __name__ == "__main__":
    from toy_instances import build_toy_combined_component_risk

    d = build_toy_combined_component_risk()
    lam_sla, lam_sf = 0.5, 0.5
    print("=== ComponentRisk toy · TEAVAR Model A ===")
    m1, c1, l1, s1, y1, *_ = build_teavar_model_a(d, lam_sla, lam_sf, omega_deliver=1.0)
    print(f"  status={m1.status}  cost={c1}  CVaR_SLA={l1}  CVaR_sf={s1}  部署={_dist_str(d, y1) if c1 else 'n/a'}")
    print("\n运行完整验证: python -m unittest discover -s tests -v")
