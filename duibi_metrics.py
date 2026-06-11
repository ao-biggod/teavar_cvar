# -*- coding: utf-8 -*-
"""与 duibi 玩具算例配合：路径场景可达性、解后指标、带宽成本（流量×链路单价）。"""

from __future__ import annotations

from typing import Any, Optional, Tuple

import gurobipy as gp
from gurobipy import GRB

PRICING_PROFILE_UNIFORM = "uniform"
PRICING_PROFILE_LEGACY = "legacy"
PRICING_PROFILE_COPO_V1 = "copo_v1"
PRICING_PROFILE_MAIN = PRICING_PROFILE_COPO_V1  # 论文 / 代码主线默认定价

# role_transit (copo_v1): π_e = scale × φ(role[u], role[v])
COPO_V1_ROLE_TRANSIT: dict[str, dict[str, float]] = {
    "core": {"core": 1.0, "aggregation": 1.5, "edge_pop": 2.5},
    "aggregation": {"core": 1.5, "aggregation": 2.0, "edge_pop": 2.5},
    "edge_pop": {"core": 2.5, "aggregation": 2.5, "edge_pop": 3.5},
}

DEFAULT_BANDWIDTH_SHARE_TARGET = 0.30


def _norm_node_role(role: str) -> str:
    r = str(role or "").strip().lower()
    if r in ("edge", "edge_pop", "pop", "edge-pop"):
        return "edge_pop"
    if r in ("agg", "aggregation"):
        return "aggregation"
    if r == "core":
        return "core"
    return "aggregation"


def role_transit_multiplier(role_u: str, role_v: str) -> float:
    """φ(role[u], role[v]) for copo_v1 / role_transit pricing."""
    ru = _norm_node_role(role_u)
    rv = _norm_node_role(role_v)
    row = COPO_V1_ROLE_TRANSIT.get(ru, COPO_V1_ROLE_TRANSIT["aggregation"])
    return float(row.get(rv, 2.0))


def _node_roles_map(data) -> dict[int, str]:
    roles = getattr(data, "node_role", None)
    if isinstance(roles, dict) and roles:
        return {int(k): str(v) for k, v in roles.items()}
    return {int(m): "aggregation" for m in data.M}


def link_price_for_edge(data, e: tuple) -> float:
    """
    链路 $e=(u,v)$ 单位带宽单价 $\\pi_e^{\\mathrm{price}}$（元/单位流量）。
    模式：uniform | inverse_capacity | legacy_inverse_capacity | role_transit。
    """
    scale = float(getattr(data, "bandwidth_price_scale", 1.0))
    mode = str(getattr(data, "bandwidth_price_mode", "uniform"))
    if mode == "role_transit":
        roles = _node_roles_map(data)
        u, v = int(e[0]), int(e[1])
        phi = role_transit_multiplier(roles.get(u, ""), roles.get(v, ""))
        return scale * phi
    if mode in ("inverse_capacity", "legacy_inverse_capacity"):
        return scale / max(float(data.B[e]), 1.0)
    return scale


def summarize_link_prices(data) -> dict[str, float]:
    ensure_link_prices(data)
    prices = sorted(float(v) for v in data.link_price.values())
    if not prices:
        return {
            "price_min": 0.0,
            "price_max": 0.0,
            "price_ratio": 1.0,
            "mean_price": 0.0,
            "median_price": 0.0,
        }
    mid = len(prices) // 2
    median = prices[mid] if len(prices) % 2 else (prices[mid - 1] + prices[mid]) / 2.0
    pmin = prices[0]
    pmax = prices[-1]
    return {
        "price_min": pmin,
        "price_max": pmax,
        "price_ratio": pmax / pmin if pmin > 0 else float("inf"),
        "mean_price": sum(prices) / len(prices),
        "median_price": median,
    }


def _placement_cost(data, i: int, m: int) -> float:
    return sum(float(data.w[i][k]) * float(data.p_price[m][k]) for k in data.K)


def _min_path_tariff(data, u: int, v: int) -> float:
    paths = data.P_cand.get((u, v), [[]])
    if not paths:
        return float("inf")
    return min(path_bandwidth_tariff(data, u, v, p_idx) for p_idx in range(len(paths)))


def reference_placement_bandwidth_costs(
    data, *, scale: float | None = None
) -> tuple[float, float]:
    """
    Reference policy ``cheapest_placement_min_path_tariff``:
    per task pick min compute-cost valid placement; bandwidth = b_in·τ_in + b_out·τ_out
    with min path tariff on candidate paths.
    """
    old_scale = float(getattr(data, "bandwidth_price_scale", 1.0))
    old_prices = getattr(data, "link_price", None)
    try:
        if scale is not None:
            data.bandwidth_price_scale = float(scale)
        data.link_price = {}
        ensure_link_prices(data)
        c_p = 0.0
        c_b = 0.0
        for i in data.I:
            valid_ms = [m for m in data.M if data.valid_assign.get((i, m), False)]
            if not valid_ms:
                valid_ms = list(data.M)
            best_m = min(valid_ms, key=lambda m: _placement_cost(data, i, m))
            c_p += _placement_cost(data, i, best_m)
            src, dst = teavar_flow_anchors(data, i)
            tau_in = _min_path_tariff(data, src, best_m)
            tau_out = _min_path_tariff(data, best_m, dst)
            c_b += float(data.b_in[i]) * tau_in + float(data.b_out[i]) * tau_out
        return c_p, c_b
    finally:
        data.bandwidth_price_scale = old_scale
        data.link_price = old_prices if old_prices is not None else {}


def calibrate_bandwidth_price_scale(
    data, *, target_bandwidth_share: float = DEFAULT_BANDWIDTH_SHARE_TARGET
) -> float:
    """Find scale so reference (c_p, c_b) yields c_b/(c_p+c_b) ≈ target."""
    target = float(target_bandwidth_share)
    if not (0.0 < target < 1.0):
        raise ValueError("target_bandwidth_share must be in (0, 1)")
    saved_mode = str(getattr(data, "bandwidth_price_mode", "uniform"))
    saved_profile = getattr(data, "pricing_profile", PRICING_PROFILE_UNIFORM)
    try:
        data.bandwidth_price_mode = "role_transit"
        data.pricing_profile = PRICING_PROFILE_COPO_V1
        c_p, c_b_unit = reference_placement_bandwidth_costs(data, scale=1.0)
        if c_b_unit <= 0.0:
            return 1.0
        c_b_target = (target / (1.0 - target)) * c_p
        return c_b_target / c_b_unit
    finally:
        data.bandwidth_price_mode = saved_mode
        data.pricing_profile = saved_profile
        data.link_price = {}


def apply_topology_pricing_calibration(
    data, *, target_bandwidth_share: float = DEFAULT_BANDWIDTH_SHARE_TARGET
) -> float:
    """Set copo_v1 / role_transit and calibrate scale (B4 ≈ 0.003056… for share 0.30)."""
    data.pricing_profile = PRICING_PROFILE_COPO_V1
    data.bandwidth_price_mode = "role_transit"
    scale = calibrate_bandwidth_price_scale(
        data, target_bandwidth_share=target_bandwidth_share
    )
    data.bandwidth_price_scale = float(scale)
    data.link_price = {}
    ensure_link_prices(data)
    return float(scale)


def build_pricing_audit_record(
    data,
    *,
    topology: str,
    routing_mode: str,
    num_tasks: int,
    target_bandwidth_share: float = DEFAULT_BANDWIDTH_SHARE_TARGET,
) -> dict[str, Any]:
    ensure_link_prices(data)
    c_p, c_b = reference_placement_bandwidth_costs(data)
    total = c_p + c_b
    share = c_b / total if total > 0 else 0.0
    stats = summarize_link_prices(data)
    suggested = calibrate_bandwidth_price_scale(
        data, target_bandwidth_share=target_bandwidth_share
    )
    return {
        "topology": topology,
        "routing_mode": routing_mode,
        "num_tasks": int(num_tasks),
        "profile": getattr(data, "pricing_profile", PRICING_PROFILE_UNIFORM),
        "bandwidth_price_mode": getattr(data, "bandwidth_price_mode", "uniform"),
        "bandwidth_price_scale": float(getattr(data, "bandwidth_price_scale", 1.0)),
        "target_bandwidth_share": float(target_bandwidth_share),
        "suggested_bandwidth_price_scale": float(suggested),
        "reference_policy": "cheapest_placement_min_path_tariff",
        "c_p_ref": float(c_p),
        "c_b_ref": float(c_b),
        "bandwidth_share": float(share),
        **stats,
    }


def configure_pricing_on_data(
    data,
    *,
    pricing_profile: str = PRICING_PROFILE_UNIFORM,
    bandwidth_price_mode: str | None = None,
    bandwidth_price_scale: float | None = None,
    apply_topology_pricing: bool = False,
    auto_calibrate_copo: bool = True,
    target_bandwidth_share: float = DEFAULT_BANDWIDTH_SHARE_TARGET,
    quiet: bool = False,
) -> None:
    """Resolve pricing profile → mode/scale and populate ``data.link_price``."""
    if apply_topology_pricing:
        scale = apply_topology_pricing_calibration(
            data, target_bandwidth_share=target_bandwidth_share
        )
        if not quiet:
            print(
                f"  [pricing] apply_topology_pricing copo_v1 role_transit "
                f"scale={scale:.12g} (target bw share={target_bandwidth_share})"
            )
        return

    profile = str(pricing_profile or PRICING_PROFILE_UNIFORM).lower()
    if profile == PRICING_PROFILE_LEGACY:
        if not quiet:
            print("  [pricing] legacy_inverse_capacity sensitivity mode (not P0 default)")
        data.pricing_profile = PRICING_PROFILE_LEGACY
        data.bandwidth_price_mode = bandwidth_price_mode or "legacy_inverse_capacity"
        data.bandwidth_price_scale = float(
            bandwidth_price_scale if bandwidth_price_scale is not None else 1.0
        )
    elif profile == PRICING_PROFILE_COPO_V1:
        data.pricing_profile = PRICING_PROFILE_COPO_V1
        data.bandwidth_price_mode = bandwidth_price_mode or "role_transit"
        if bandwidth_price_scale is not None:
            data.bandwidth_price_scale = float(bandwidth_price_scale)
        elif auto_calibrate_copo:
            data.bandwidth_price_scale = calibrate_bandwidth_price_scale(
                data, target_bandwidth_share=target_bandwidth_share
            )
        else:
            data.bandwidth_price_scale = float(
                getattr(data, "bandwidth_price_scale", 1.0)
            )
    else:
        data.pricing_profile = PRICING_PROFILE_UNIFORM
        data.bandwidth_price_mode = bandwidth_price_mode or "uniform"
        data.bandwidth_price_scale = float(
            bandwidth_price_scale
            if bandwidth_price_scale is not None
            else getattr(data, "bandwidth_price_scale", 1.0)
        )

    data.link_price = {}
    ensure_link_prices(data)


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
    为每条链路 $e$ 提供带宽单价 $\\pi_e^{\\mathrm{price}}$（元 / 单位业务量），写入 ``data.link_price``。
    若已存在则不覆盖。

    模式：
    - ``uniform``：$\\pi_e = \\mathrm{scale}$
    - ``inverse_capacity`` / ``legacy_inverse_capacity``：$\\pi_e \\propto 1/B_e$
    - ``role_transit`` (copo_v1)：$\\pi_e = \\mathrm{scale} \\times \\phi(\\mathrm{role}[u],\\mathrm{role}[v])$
    """
    existing = getattr(data, "link_price", None)
    if existing is not None and len(existing) > 0:
        return existing

    link_price = {e: link_price_for_edge(data, e) for e in data.E}
    data.link_price = link_price
    return link_price


def placement_bandwidth_cost_value(data, placement: dict[int, int]) -> float:
    """Plan bandwidth cost for fixed single-path routing per task."""
    ensure_link_prices(data)
    total = 0.0
    for i in data.I:
        node = placement[i]
        src, dst = teavar_flow_anchors(data, i)
        tau_in = path_bandwidth_tariff(data, src, node, 0)
        tau_out = path_bandwidth_tariff(data, node, dst, 0)
        total += float(data.b_in[i]) * (tau_in + tau_out)
    return total


def placement_bandwidth_cost_expr(data, y) -> gp.LinExpr:
    """
    Plan-level bandwidth fee tied to placement:
    sum_{i,m} b_i * (tau_in + tau_out) * y_{i,m}.
    """
    ensure_link_prices(data)
    terms = []
    for i in data.I:
        src, dst = teavar_flow_anchors(data, i)
        for node in data.M:
            if (i, node) not in y:
                continue
            tau_in = path_bandwidth_tariff(data, src, node, 0)
            tau_out = path_bandwidth_tariff(data, node, dst, 0)
            terms.append(float(data.b_in[i]) * (tau_in + tau_out) * y[i, node])
    return gp.quicksum(terms) if terms else gp.LinExpr(0.0)


def link_unit_price(data, e) -> float:
    """链路 $e$ 的单位带宽单价 $\\pi_e^{\\mathrm{price}}$。"""
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
