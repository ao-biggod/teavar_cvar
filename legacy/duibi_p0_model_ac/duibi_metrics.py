# -*- coding: utf-8 -*-
"""与 duibi 玩具算例配合：路径场景可达性、解后指标、带宽成本（流量×链路单价）。"""

from __future__ import annotations

from typing import Optional, Tuple

import gurobipy as gp
from gurobipy import GRB


def _hub(data) -> int:
    return int(getattr(data, "hub", 0))


def teavar_flow_anchors(data, i: Optional[int] = None) -> Tuple[int, int]:
    """
    TEAVAR SLA（`build_teavar_sla_cvar_model`）下 ingress/egress 在 P_cand 中的锚点。

    - ``routing_mode == 'hub'``：``(h,h)``。
    - ``routing_mode == 'per_task_od'`` 且 ``i is not None``：``(task_src[i], task_dst[i])``。
    - ``routing_mode == 'umcf_global'``：全局 ``(umcf_vs, umcf_vt)``（与 i 无关）。
    - ``routing_mode == 'umcf_per_task'`` 且 ``i is not None``：``(umcf_task_src[i], umcf_task_dst[i])``。
    - 兼容：``hub`` + ``umcf_virtual_nodes``（旧 ``--joint-umcf-teavar``）同 umcf_global。
    """
    mode = getattr(data, "routing_mode", "hub")

    if mode == "umcf_per_task":
        if i is None:
            raise ValueError(
                "routing_mode='umcf_per_task' requires task index i for teavar_flow_anchors(data, i)."
            )
        src_map = getattr(data, "umcf_task_src", None)
        dst_map = getattr(data, "umcf_task_dst", None)
        if not src_map or not dst_map:
            raise ValueError(
                "routing_mode='umcf_per_task' requires data.umcf_task_src and data.umcf_task_dst "
                "(set by attach_umcf_per_task / load_b4_joint_data)."
            )
        if i not in src_map or i not in dst_map:
            raise ValueError(f"task index {i} missing in umcf_task_src/umcf_task_dst")
        return int(src_map[i]), int(dst_map[i])

    if mode == "umcf_global" or (
        mode == "hub" and getattr(data, "umcf_virtual_nodes", False)
    ):
        if not getattr(data, "umcf_virtual_nodes", False):
            raise ValueError(
                "routing_mode='umcf_global' requires UMCF virtual nodes on data "
                "(load with routing_mode='umcf_global' or --joint-umcf-teavar)."
            )
        vs = getattr(data, "umcf_vs", None)
        vt = getattr(data, "umcf_vt", None)
        if vs is None or vt is None:
            raise ValueError("umcf_global missing data.umcf_vs / data.umcf_vt")
        return int(vs), int(vt)

    if mode == "per_task_od" and i is not None:
        task_src = getattr(data, "task_src", None)
        task_dst = getattr(data, "task_dst", None)
        if not task_src or not task_dst:
            raise ValueError(
                "routing_mode='per_task_od' requires data.task_src and data.task_dst "
                "(set by load_joint_data / load_b4_joint_data)."
            )
        if i not in task_src or i not in task_dst:
            raise ValueError(f"task index {i} missing in task_src/task_dst")
        return int(task_src[i]), int(task_dst[i])

    h = _hub(data)
    return h, h


def is_umcf_auxiliary_edge(data, e: tuple) -> bool:
    """
    UMCF 下 (V_s,m)、(m,V_t) 为逻辑辅助边；链路「利用率」类指标中跳过，
    避免 B 取物理上界时利用率被稀释。
    """
    if not getattr(data, "umcf_virtual_nodes", False):
        return False
    n = len(data.M)
    u, v = int(e[0]), int(e[1])
    return u >= n or v >= n


def ensure_link_prices(data) -> dict:
    """
    为每条链路 $e$ 提供带宽单价 $\\pi_e$（元 / 单位业务量），写入 ``data.link_price``。
    若已存在则不覆盖。默认：``bandwidth_price_scale``（默认 1.0）为常数单价；
    ``bandwidth_price_mode='inverse_capacity'`` 时 $\\pi_e \\propto 1/B_e$。
    """
    existing = getattr(data, "link_price", None)
    if existing is not None and len(existing) > 0:
        return existing

    scale = float(getattr(data, "bandwidth_price_scale", 1.0))
    mode = str(getattr(data, "bandwidth_price_mode", "uniform"))
    link_price = {}
    for e in data.E:
        if mode == "inverse_capacity":
            link_price[e] = scale / max(float(data.B[e]), 1.0)
        else:
            link_price[e] = scale
    data.link_price = link_price
    return link_price


def link_unit_price(data, e) -> float:
    """链路 $e$ 的单位带宽单价 $\\pi_e$。"""
    ensure_link_prices(data)
    return float(data.link_price[e])


def path_bandwidth_tariff(data, u: int, v: int, p_idx: int) -> float:
    """
    路径 $p \\in \\mathcal{P}_{uv}$ 的带宽单价（路径价）：
    $\\tau_p = \\sum_{e \\in p} \\pi_e$。
    """
    path = data.P_cand[u, v][p_idx]
    if not path:
        return 0.0
    return sum(link_unit_price(data, e) for e in path)


def bandwidth_cost_expr(
    data, xin, xout, in_u: Optional[int] = None, out_v: Optional[int] = None
) -> gp.LinExpr:
    """
    计划流量带宽费（Model A/C 等）：
    $c_b = \\sum_{i,m,p} x^{in}_{i,m,p}\\,\\tau_p + \\sum_{i,m,q} x^{out}_{i,m,q}\\,\\tau_q$，
    $\\tau_p=\\sum_{e\\in p}\\pi_e$。

    ``routing_mode='per_task_od'`` 时按每任务 ``task_src[i]`` / ``task_dst[i]`` 计路径价；
    否则使用全局 ``in_u,out_v``（缺省则 ``teavar_flow_anchors(data)``）。
    """
    ensure_link_prices(data)
    if getattr(data, "routing_mode", "hub") in ("per_task_od", "umcf_per_task"):
        return gp.quicksum(
            xin[i, node, p] * path_bandwidth_tariff(data, teavar_flow_anchors(data, i)[0], node, p)
            for (i, node, p) in xin
        ) + gp.quicksum(
            xout[i, node, q] * path_bandwidth_tariff(data, node, teavar_flow_anchors(data, i)[1], q)
            for (i, node, q) in xout
        )
    if in_u is None or out_v is None:
        in_u, out_v = teavar_flow_anchors(data)
    return gp.quicksum(
        xin[i, node, p] * path_bandwidth_tariff(data, in_u, node, p)
        for (i, node, p) in xin
    ) + gp.quicksum(
        xout[i, node, q] * path_bandwidth_tariff(data, node, out_v, q)
        for (i, node, q) in xout
    )


def scenario_bandwidth_cost_value(
    data, del_in, del_out, in_u: int, out_v: int, s: int
) -> float:
    """场景 $s$ 下按送达量 $d$ 计的带宽费（Model M）：$\\sum d \\cdot \\tau_p$。"""
    ensure_link_prices(data)
    cb = 0.0
    for (i, node, p, sc), var in del_in.items():
        if sc != s:
            continue
        cb += float(var.X) * path_bandwidth_tariff(data, in_u, node, p)
    for (i, node, q, sc), var in del_out.items():
        if sc != s:
            continue
        cb += float(var.X) * path_bandwidth_tariff(data, node, out_v, q)
    return cb


def path_up(data, u, v, p_idx, s):
    """场景 s 下路径 p 上所有边是否均可用 (sigma>0)。"""
    path = data.P_cand[u, v][p_idx]
    if not path:
        return True
    return all(data.sigma[e][s] > 0 for e in path)


def max_link_util_after_solve(data, m, xin, xout):
    """用当前解在名义场景 s=0 上算 max_e flow_e / B_e。"""
    if m.status != GRB.OPTIMAL:
        return None
    in_u, out_v = teavar_flow_anchors(data)
    best = 0.0
    for e in data.E:
        if is_umcf_auxiliary_edge(data, e):
            continue
        fe = 0.0
        for (i, node, p), var in xin.items():
            if e in data.P_cand[in_u, node][p]:
                fe += var.X
        for (i, node, q), var in xout.items():
            if e in data.P_cand[node, out_v][q]:
                fe += var.X
        uu = fe / data.B[e] if data.B[e] > 0 else 0.0
        best = max(best, uu)
    return best


def max_node_util_after_solve(data, m, y):
    if m.status != GRB.OPTIMAL:
        return None
    best = 0.0
    for node in data.M:
        for k in data.K:
            load = sum(y[i, node].X * data.w[i][k] for i in data.I)
            uu = load / data.C_normal[node][k] if data.C_normal[node][k] > 0 else 0.0
            best = max(best, uu)
    return best


def expected_delivery_ratio(data, m, y, xin, xout):
    """各任务在放置节点上 ingress+egress 名义流量占需求比例（简化标量）。"""
    if m.status != GRB.OPTIMAL:
        return None
    in_u, out_v = teavar_flow_anchors(data)
    ratios = []
    for i in data.I:
        placed = None
        for n in data.M:
            if y[i, n].X > 0.5:
                placed = n
                break
        if placed is None:
            continue
        xin_sum = sum(xin[i, placed, p].X for p in range(len(data.P_cand[in_u, placed])))
        xout_sum = sum(xout[i, placed, q].X for q in range(len(data.P_cand[placed, out_v])))
        r_in = xin_sum / data.b_in[i] if data.b_in[i] > 0 else 1.0
        r_out = xout_sum / data.b_out[i] if data.b_out[i] > 0 else 1.0
        ratios.append((r_in + r_out) / 2.0)
    return sum(ratios) / len(ratios) if ratios else 0.0


def worst_max_link_util_across_scenarios(data, m, xin, xout):
    """各场景下 max_e flow_e/(B_e*sigma) 的最大值（与 duibi 链路 CVaR 分母一致）。"""
    if m.status != GRB.OPTIMAL:
        return None
    in_u, out_v = teavar_flow_anchors(data)
    worst = 0.0
    for s in data.S:
        for e in data.E:
            if is_umcf_auxiliary_edge(data, e):
                continue
            fe = 0.0
            for (i, node, p), var in xin.items():
                if e in data.P_cand[in_u, node][p]:
                    fe += var.X
            for (i, node, q), var in xout.items():
                if e in data.P_cand[node, out_v][q]:
                    fe += var.X
            cap = data.B[e] * data.sigma[e][s]
            if cap > 0:
                worst = max(worst, fe / cap)
    return worst


def worst_max_node_util_across_scenarios(data, m, y):
    if m.status != GRB.OPTIMAL:
        return None
    worst = 0.0
    for s in data.S:
        for node in data.M:
            for k in data.K:
                load = sum(y[i, node].X * data.w[i][k] for i in data.I)
                den = data.C_s[node][k][s]
                if den > 0:
                    worst = max(worst, load / den)
    return worst


def expected_total_delivered_volume(data, m, del_in, del_out):
    """场景加权总送达量 E_s[Σ_i (R_in(i,s)+R_out(i,s))]，与 teavar_sla 目标中 exp_deliver 一致。"""
    if m.status != GRB.OPTIMAL:
        return None
    in_u, out_v = teavar_flow_anchors(data)
    tot = 0.0
    for s in data.S:
        ps = data.prob[s]
        din = sum(
            del_in[i, node, p, s].X
            for i in data.I
            for node in data.M
            for p in range(len(data.P_cand[in_u, node]))
        )
        dout = sum(
            del_out[i, node, q, s].X
            for i in data.I
            for node in data.M
            for q in range(len(data.P_cand[node, out_v]))
        )
        tot += ps * (din + dout)
    return tot


def sla_per_scenario_max_demand_loss(data, y, del_in, del_out):
    """
    对每个场景 s：L_s = max_i max( 1 - R_in(i,s)/b_in, 1 - R_out(i,s)/b_out )，R 为送达量。
    用于解释「模型里 CVaR_loss 已为 0 但各场景仍可有非零瞬时损失」等情况。
    返回 (L_max, dict s->L_s)。
    """
    in_u, out_v = teavar_flow_anchors(data)
    per_s = {}
    for s in data.S:
        Ls = 0.0
        for i in data.I:
            rin = sum(
                del_in[i, node, p, s].X for node in data.M for p in range(len(data.P_cand[in_u, node]))
            )
            rout = sum(
                del_out[i, node, q, s].X for node in data.M for q in range(len(data.P_cand[node, out_v]))
            )
            li = 0.0
            if data.b_in[i] > 0:
                li = max(li, 1.0 - rin / data.b_in[i])
            if data.b_out[i] > 0:
                li = max(li, 1.0 - rout / data.b_out[i])
            Ls = max(Ls, li)
        per_s[s] = Ls
    L_max = max(per_s.values()) if per_s else 0.0
    return L_max, per_s
