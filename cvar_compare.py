# -*- coding: utf-8 -*-
r"""
并排对比两类 CVaR（同一套 UltraComplexData / 场景 / sigma）：

- physical：`duibi.build_single_layer_model`（算力+链路利用率尾部 CVaR）
- teavar_sla：本文件内模型（TEAVAR 式「未满足需求」尾部 CVaR + 可选算力利用率 CVaR + 可选 **算力未满足 CVaR**
  （e=max(0,D-C_s)，L_s=max e/D_ref，与 1-A/D 同构思想）+ 送达量奖励

teavar_sla 使用 sum x <= y*b；场景下送达量 del 随路径可用性；目标含 -omega*E[del] 防零流。
算力利用率尾部由 lambda_node_cvar>0 打开；**算力「包到机但算不完」**由 lambda_compute_sf_cvar>0：按维 D_mk=sum w y，
场景容量 C_s 下超额 e 的归一化 max 再 CVaR（D_ref 为常数上界，使 L_s 落在合理量级）。

说明：若最优解把任务全放在 hub 上，则 ingress/egress 可为 hub→本节点空路径，不经物理边，
各场景送达仍等于需求 → 「需求损失 CVaR」易退化。可选 **虚拟源 Vs**（`data.sigma_vs`）：
对每个放置点 \(m\) 施加逻辑边 \((V_s,m)\) 的可用率 \(\sigma^{vs}_{m,s}<1\)，约束
\(R^{in}_{is}\le\sum_m b^{in}_i y_{im}\sigma^{vs}_{m,s}\)，使即便空物理路径仍有接入风险上界。
可选 **UMCF 显式虚拟源/汇**（`data.umcf_virtual_nodes`，由 `b4_joint_data` 在 `--joint-umcf-teavar` 等打开）：
ingress/egress 路径锚点为 \(V_s,V_t\)，物理 hub 仍用于放置约束与 stress；`sigma_vs` 瓶颈约束自动关闭以避免与虚拟边 \(\sigma\) 重复。

另一常见现象：即使 CVaR_loss 非零，若它在**所比较的可行放置上为同一常数**，则目标里 λ·CVaR_loss
对全体可行解是同一平移，**不改变最优排序**，各 λ 会得到相同整数解；此时应看 obj_full=cost+λ·risk-ω·E[del]。
可调 --omega、减弱 stress、或 --beta-loss 调低使尾部场景集变化，让损失在可行域内分化。
"""
import gurobipy as gp
from gurobipy import GRB

from duibi_metrics import (
    bandwidth_cost_expr,
    is_umcf_auxiliary_edge,
    path_up,
    placement_bandwidth_cost_expr,
    max_link_util_after_solve,
    max_node_util_after_solve,
    expected_delivery_ratio,
    expected_total_delivered_volume,
    worst_max_link_util_across_scenarios,
    worst_max_node_util_across_scenarios,
    sla_per_scenario_max_demand_loss,
    teavar_flow_anchors,
)


def _uses_per_task_flow(data) -> bool:
    return getattr(data, "routing_mode", "hub") in ("per_task_od", "umcf_per_task")


def _is_per_task_od(data) -> bool:
    return _uses_per_task_flow(data)


def compute_sf_resource_refs(data, eps=1.0) -> dict[int, float]:
    """Per-resource SF normalization: D_ref[k] = max(sum_i w[i,k], eps)."""
    refs: dict[int, float] = {}
    for k in data.K:
        total_demand_k = float(sum(data.w[i][k] for i in data.I))
        refs[k] = max(total_demand_k, float(eps))
    return refs


def sf_D_ref_by_resource(data, eps=1.0) -> dict[int, float]:
    """Alias for ``compute_sf_resource_refs`` (paper notation)."""
    return compute_sf_resource_refs(data, eps=eps)


def _task_flow_anchors(data, i: int, global_in_u: int, global_out_v: int) -> tuple[int, int]:
    if _is_per_task_od(data):
        return teavar_flow_anchors(data, i)
    return global_in_u, global_out_v


def compute_d_ref(data) -> float:
    """Legacy global scalar M_ex (Big-M / posthoc legacy only; SF CVaR uses per-resource refs)."""
    from metrics_posthoc import compute_d_ref as _compute_d_ref

    return float(_compute_d_ref(data))


def add_scenario_delivery_coupling(
    m,
    data,
    y,
    xin,
    xout,
    del_in,
    del_out,
    in_u: int,
    out_v: int,
) -> None:
    """
    场景送达与计划流量耦合（无 Big-M）：

    - path_up → d == x
    - 否则 → d == 0

    放置语义由 xin/xout ≤ y·b 保证，不在送达约束中重复 y。
    """
    for s in data.S:
        for i in data.I:
            iu, ov = _task_flow_anchors(data, i, in_u, out_v)
            for node in data.M:
                if (i, node) not in data.valid_assign:
                    continue
                for p in range(len(data.P_cand[iu, node])):
                    if (i, node, p) not in xin:
                        continue
                    di, xi = del_in[i, node, p, s], xin[i, node, p]
                    if path_up(data, iu, node, p, s):
                        m.addConstr(di == xi, name=f"del_in_eq_{i}_{node}_{p}_{s}")
                    else:
                        m.addConstr(di == 0, name=f"del_in_zero_{i}_{node}_{p}_{s}")
                for q in range(len(data.P_cand[node, ov])):
                    if (i, node, q) not in xout:
                        continue
                    do, xo = del_out[i, node, q, s], xout[i, node, q]
                    if path_up(data, node, ov, q, s):
                        m.addConstr(do == xo, name=f"del_out_eq_{i}_{node}_{q}_{s}")
                    else:
                        m.addConstr(do == 0, name=f"del_out_zero_{i}_{node}_{q}_{s}")


def add_compute_sf_cvar_ru(
    m,
    data,
    y,
    *,
    beta_sf: float,
    sf_d_ref_by_resource: dict[int, float] | None = None,
):
    """
    算力 SF CVaR：Rockafellar–Uryasev 纯连续形式（无 e_ex / w_exc / Big-M）。

    phi_s[s] >= (D[m,k] - C_s[m,k,s]) / D_ref[k] - zeta_sf
    """
    refs = sf_d_ref_by_resource if sf_d_ref_by_resource is not None else compute_sf_resource_refs(data)
    d_mk: dict[tuple[int, int], gp.Var] = {}
    for node in data.M:
        for k in data.K:
            d_mk[node, k] = m.addVar(lb=0.0, name=f"dreq_{node}_{k}")
            m.addConstr(
                d_mk[node, k]
                == gp.quicksum(y[i, node] * data.w[i][k] for i in data.I if (i, node) in y),
                name=f"ddef_{node}_{k}",
            )
    zeta_sf = m.addVar(lb=0.0, name="zeta_compute_sf")
    phi_s = m.addVars(data.S, lb=0.0, name="phi_compute_sf")
    for s in data.S:
        for node in data.M:
            for k in data.K:
                cap = float(data.C_s[node][k][s])
                d_ref_k = float(refs[k])
                m.addConstr(
                    phi_s[s] >= (d_mk[node, k] - cap) / d_ref_k - zeta_sf,
                    name=f"phi_sf_lb_{node}_{k}_{s}",
                )
    shortfall_cvar = zeta_sf + (1.0 / (1.0 - beta_sf)) * gp.quicksum(
        data.prob[s] * phi_s[s] for s in data.S
    )
    return zeta_sf, phi_s, shortfall_cvar, d_mk


def add_teavar_virtual_bottleneck_constraints(m, data, y, del_in, del_out, hub: int):
    """
    若 `data.sigma_vs` 存在：对每个 (s,i) 施加
      R_in(i,s) <= sum_m b_in[i] * y[i,m] * sigma_vs[m,s]
    若 `data.sigma_vt` 存在（否则沿用 sigma_vs）：对 Rout 对称上界。
    表示经虚拟源/汇逻辑边的「接入可靠性」瓶颈（与物理路径送达串联取紧上界）。

    hub 模式：Rin/Rout 按 ``P_cand[(h,node)]`` / ``P_cand[(node,h)]`` 聚合。
    per_task_od：按 ``teavar_flow_anchors(data,i)`` 的 ``(src_i,dst_i)`` 聚合。
    """
    sigma_vs = getattr(data, "sigma_vs", None)
    if not sigma_vs:
        return
    if getattr(data, "umcf_virtual_nodes", False):
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
            cap_in = gp.quicksum(
                data.b_in[i] * float(sigma_vs[node][s]) * y[i, node]
                for node in data.M
                if (i, node) in y and node in sigma_vs and s in sigma_vs[node]
            )
            cap_out = gp.quicksum(
                data.b_out[i] * float(sigma_vt[node][s]) * y[i, node]
                for node in data.M
                if (i, node) in y and node in sigma_vt and s in sigma_vt[node]
            )
            m.addConstr(Rin <= cap_in, name=f"vs_cap_in_{i}_{s}")
            m.addConstr(Rout <= cap_out, name=f"vt_cap_out_{i}_{s}")


def planned_flow_on_edge(data, e, xin, xout) -> gp.LinExpr:
    """Aggregate planned ingress/egress flow carried on directed link ``e``."""
    u, v = int(e[0]), int(e[1])
    terms: list[gp.LinExpr | gp.Var] = []
    for (i, node, p), xvar in xin.items():
        iu, _ = teavar_flow_anchors(data, i)
        path = data.P_cand[iu, node][p]
        if (u, v) in path or e in path:
            terms.append(xvar)
    for (i, node, q), xvar in xout.items():
        _, ov = teavar_flow_anchors(data, i)
        path = data.P_cand[node, ov][q]
        if (u, v) in path or e in path:
            terms.append(xvar)
    return gp.quicksum(terms) if terms else gp.LinExpr(0.0)


def add_link_nominal_capacity_constraints(m, data, xin, xout) -> None:
    """
    链路名义带宽容量（计划流量不超边容量）：

        sum_{i,m,p} x^{in} delta_{e,p} + sum_{i,m,q} x^{out} delta_{e,q} <= B_e

    默认启用；``data.enforce_link_capacity=False`` 时跳过（仅 toy 调试）。
    UMCF 辅助边跳过。
    """
    if not getattr(data, "enforce_link_capacity", True):
        return
    for e in data.E:
        if is_umcf_auxiliary_edge(data, e):
            continue
        cap = float(data.B[e])
        if cap <= 0.0:
            continue
        flow_e = planned_flow_on_edge(data, e, xin, xout)
        m.addConstr(flow_e <= cap, name=f"link_cap_{e[0]}_{e[1]}")


def build_teavar_sla_cvar_model(
    data,
    lambda_cvar,
    omega_deliver=1.0,
    beta_loss=None,
    delta_min_normal=None,
    min_tasks_off_node0=0,
    lambda_node_cvar=0.0,
    beta_node=None,
    lambda_compute_sf_cvar=0.0,
    beta_compute_sf=None,
    time_limit: float | None = None,
    mip_gap: float | None = None,
):
    r"""
    min  cost_p + cost_b
        + lambda_cvar * CVaR_loss(需求未满足)
        + lambda_node_cvar * CVaR_node(算力利用率尾部，可选)
        + lambda_compute_sf_cvar * CVaR_compute_sf(算力「未满足量」尾部，可选)
        - omega_deliver * E[ingress+egress 送达量]

    若 ``data.umcf_virtual_nodes``：ingress 为 \(V_s\to m\)、egress 为 \(m\to V_t\)（单跳虚拟边在 ``P_cand``/``sigma`` 中），
    否则保持 hub 径向 ``h\to m`` / ``m\to h``（``h=getattr(data,'hub',0)``）。

    算力未满足（TEAVAR 同构思想）：每 (m,k) 需求 D_mk=sum_i w_ik y_im，场景容量 C_s[m,k,s]，
    超额 e_{m,k,s}=max(0, D_mk-C)（MIP 线性化）；场景标量 L_s = max_{m,k} e_{m,k,s}/D_ref，
    再对 L_s 做 CVaR（zeta_sf, phi_s）。D_ref 为常数上界，使 L_s 与 1-A/D 在尺度上可比（见代码注释）。
    """
    if beta_loss is None:
        beta_loss = data.beta_N

    use_node_cvar = bool(lambda_node_cvar and lambda_node_cvar > 0.0)
    b_node = beta_node if beta_node is not None else data.beta_N

    use_compute_sf = bool(lambda_compute_sf_cvar and lambda_compute_sf_cvar > 0.0)
    b_sf = beta_compute_sf if beta_compute_sf is not None else data.beta_N

    m = gp.Model("TEAVAR_style_SLA_CVaR")
    m.setParam("OutputFlag", 0)

    h = int(getattr(data, "hub", 0))
    per_task = _uses_per_task_flow(data)
    if per_task:
        in_u, out_v = teavar_flow_anchors(data, data.I[0])
    else:
        in_u, out_v = teavar_flow_anchors(data)

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
            for p in range(len(data.P_cand[in_u, node]))
        }
        xout = {
            (i, node, q): m.addVar(lb=0)
            for i in data.I
            for node in data.M
            for q in range(len(data.P_cand[node, out_v]))
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

    zeta = m.addVar(lb=-GRB.INFINITY, name="zeta_loss")
    u_s = m.addVars(data.S, lb=0, name="u_loss")

    cost_p = gp.quicksum(y[i, node] * sum(data.w[i][k] * data.p_price[node][k] for k in data.K) for i, node in y)
    if getattr(data, "bandwidth_cost_on_placement", False):
        cost_b = placement_bandwidth_cost_expr(data, y)
    else:
        # per_task_od 下 in_u/out_v 在 bandwidth_cost_expr 内按 task_src/dst 计；传 None 避免误读为 hub
        cost_b = bandwidth_cost_expr(data, xin, xout, None, None)
    loss_cvar = zeta + (1.0 / (1.0 - beta_loss)) * gp.quicksum(data.prob[s] * u_s[s] for s in data.S)

    zeta_N = nu_s = node_cvar = None
    if use_node_cvar:
        zeta_N = m.addVar(lb=-GRB.INFINITY, name="zeta_node_util")
        nu_s = m.addVars(data.S, lb=0, name="nu_node")
        node_cvar = zeta_N + (1.0 / (1.0 - b_node)) * gp.quicksum(data.prob[s] * nu_s[s] for s in data.S)

    zeta_sf = phi_s = shortfall_cvar = None
    d_mk = {}
    if use_compute_sf:
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

    obj = cost_p + cost_b + lambda_cvar * loss_cvar - omega_deliver * exp_deliver
    if use_node_cvar:
        obj += lambda_node_cvar * node_cvar
    if use_compute_sf:
        obj += lambda_compute_sf_cvar * shortfall_cvar
    m.setObjective(obj, GRB.MINIMIZE)

    if time_limit is not None:
        m.setParam("TimeLimit", float(time_limit))
    if mip_gap is not None:
        m.setParam("MIPGap", float(mip_gap))

    m.addConstrs((y.sum(i, "*") == 1 for i in data.I))

    if min_tasks_off_node0 and min_tasks_off_node0 > 0:
        m.addConstr(
            gp.quicksum(y[i, h] for i in data.I if (i, h) in y) <= len(data.I) - min_tasks_off_node0,
            name="min_off_hub",
        )

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

    if use_node_cvar:
        for s in data.S:
            for node in data.M:
                for k in data.K:
                    den = float(data.C_s[node][k][s])
                    if den > 1e-12:
                        load = gp.quicksum(y[i, node] * data.w[i][k] for i in data.I if (i, node) in y)
                        m.addConstr(nu_s[s] >= load / den - zeta_N)

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

    if delta_min_normal is not None and 0 in data.S:
        s0 = 0
        for i in data.I:
            iu, ov = _task_flow_anchors(data, i, in_u, out_v)
            m.addConstr(
                gp.quicksum(
                    del_in[i, node, p, s0]
                    for node in data.M
                    for p in range(len(data.P_cand[iu, node]))
                    if (i, node, p, s0) in del_in
                )
                >= delta_min_normal * data.b_in[i] * gp.quicksum(y[i, node] for node in data.M if (i, node) in y)
            )
            m.addConstr(
                gp.quicksum(
                    del_out[i, node, q, s0]
                    for node in data.M
                    for q in range(len(data.P_cand[node, ov]))
                    if (i, node, q, s0) in del_out
                )
                >= delta_min_normal * data.b_out[i] * gp.quicksum(y[i, node] for node in data.M if (i, node) in y)
            )

    m.optimize()
    if m.status == GRB.OPTIMAL:
        cp = cost_p.getValue() + cost_b.getValue()
        lv = loss_cvar.getValue()
        nv = float(node_cvar.getValue()) if use_node_cvar else 0.0
        sfv = float(shortfall_cvar.getValue()) if use_compute_sf else 0.0
        return m, cp, lv, nv, sfv, y, xin, xout, del_in, del_out
    return m, None, None, 0.0, 0.0, y, xin, xout, del_in, del_out


def _print_row(label, cost, loss_or_cvar, max_link, max_node, worst_link_s, worst_node_s, deliv):
    def fmt(x):
        return f"{x:8.3f}" if x is not None else "   n/a  "

    print(
        f"{label:14s} | cost={fmt(cost)} | risk_term={fmt(loss_or_cvar)} | "
        f"linkU0={fmt(max_link)} | nodeU0={fmt(max_node)} | "
        f"worstLinkS={fmt(worst_link_s)} | worstNodeS={fmt(worst_node_s)} | avgDeliv={fmt(deliv)}"
    )


def _stress_s1_cut_all_outgoing_from_zero(data):
    """场景 1：切断 hub 的所有出边 (hub,v), v≠hub（与 b4_joint_data.stress_hub_outgoing_s1 同构）。"""
    h = int(getattr(data, "hub", 0))
    for v in data.M:
        if v == h:
            continue
        e = (h, v)
        if e in data.sigma and 1 in data.sigma[e]:
            data.sigma[e][1] = 0.0


if __name__ == "__main__":
    print(
        "本发布包仅包含 Model A/C 的 MILP 内核（build_teavar_sla_cvar_model 等）。\n"
        "请运行 tests/ 下的单元测试，或 scripts/reproduce_weekly_experiments.py 复现实验。"
    )
