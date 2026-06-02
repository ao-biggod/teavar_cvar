# -*- coding: utf-8 -*-
"""
[已合并] 请优先使用 ``monetary_cvar.py``（共享 MILP 核心 + 场景 breakdown + 统一 κ 对比）。

Model M / Model M-C：货币化场景损失 + 纯 CVaR 目标

- Model M  : min  CVaR_β(L)       （金融原教旨）
- Model M-C: min  E[L_s]  s.t. CVaR_β(L) ≤ Γ_money  （落地部署推荐）

L_s = c_p + c_b(s) + κ_sum·Shortfall_sum_s + κ_max·Shortfall_max_s + Σ κ_sf·e_mks

对照：
- 现 Model A（cvar_compare.py）：min E[cost] + λ·CVaR_SLA − ω·E[Del]
- 现 Model C（teavar_framework_models.py）：min E[cost] s.t. CVaR_SLA ≤ Γ

说明文档：建模_货币化纯CVaR.md
"""

from __future__ import annotations

import gurobipy as gp
from gurobipy import GRB

from duibi_metrics import path_bandwidth_tariff, path_up, teavar_flow_anchors
from cvar_compare import add_teavar_virtual_bottleneck_constraints


def _hub(data) -> int:
    return int(getattr(data, "hub", 0))


# ──────────────────────────────────────────────
#  Model M：min  CVaR_β(L)
# ──────────────────────────────────────────────

def build_model_m(
    data,
    kappa_sum: float = 5.0,
    kappa_max: float = 0.0,
    kappa_sf: dict | None = None,
    beta: float | None = None,
    omega_deliver: float = 0.0,
    min_tasks_off_hub: int = 0,
    *,
    include_compute_penalty: bool = True,
    mip_gap: float = 0.01,
    time_limit: float | None = None,
):
    """
    Model M：货币化场景账单 + 纯 CVaR 最小化。

    Parameters
    ----------
    kappa_sum : 总 Shortfall 的违约金单价（元/业务量单位）。0 则不计 SLA 罚款。
    kappa_max : 最差任务 Shortfall 比例的违约金单价。0 则不启用逐任务公平项。
    kappa_sf  : dict {(m,k): price}，算力缺口违约金单价。None 或 include_compute_penalty=False 则不计。
    beta      : CVaR 置信水平，默认 data.beta_N。
    omega_deliver : 期望送达奖励（默认 0，Model M 不需要；>0 可对标现 Model A）。
    """
    h = _hub(data)
    src, dst = teavar_flow_anchors(data)
    if beta is None:
        beta = float(getattr(data, "beta_N", 0.95))

    use_sf = bool(include_compute_penalty and kappa_sf)
    use_max_sf = bool(kappa_max and kappa_max > 0.0)

    m = gp.Model("Model_M_Monetary_CVaR")
    m.setParam("OutputFlag", 0)
    m.setParam("MIPGap", mip_gap)
    if time_limit is not None:
        m.setParam("TimeLimit", time_limit)

    Mbig = max(max(data.b_in.values()), max(data.b_out.values())) + 1.0

    # ── 决策变量 ──
    y = m.addVars(data.valid_assign, vtype=GRB.BINARY, name="y")
    xin  = {(i, node, p): m.addVar(lb=0) for i in data.I for node in data.M
            for p in range(len(data.P_cand[src, node]))}
    xout = {(i, node, q): m.addVar(lb=0) for i in data.I for node in data.M
            for q in range(len(data.P_cand[node, dst]))}

    del_in, del_out = {}, {}
    for s in data.S:
        for i in data.I:
            for node in data.M:
                for p in range(len(data.P_cand[src, node])):
                    del_in[i, node, p, s] = m.addVar(lb=0)
                for q in range(len(data.P_cand[node, dst])):
                    del_out[i, node, q, s] = m.addVar(lb=0)

    # CVaR 辅助变量
    zeta = m.addVar(lb=-GRB.INFINITY, name="zeta")
    u_s = m.addVars(data.S, lb=0, name="u")

    # ── 放置成本 c_p（不随场景变）──
    cost_p = gp.quicksum(
        y[i, node] * sum(data.w[i][k] * data.p_price[node][k] for k in data.K)
        for i, node in y
    )

    # ── 物理约束（与现模型 A/C 完全一致）──
    m.addConstrs((y.sum(i, "*") == 1 for i in data.I))
    if min_tasks_off_hub > 0:
        m.addConstr(gp.quicksum(y[i, h] for i in data.I) <= len(data.I) - min_tasks_off_hub)

    for i in data.I:
        for node in data.M:
            m.addConstr(
                gp.quicksum(xin[i, node, p] for p in range(len(data.P_cand[src, node])))
                <= y[i, node] * data.b_in[i]
            )
            m.addConstr(
                gp.quicksum(xout[i, node, q] for q in range(len(data.P_cand[node, dst])))
                <= y[i, node] * data.b_out[i]
            )

    for node in data.M:
        for k in data.K:
            m.addConstr(
                gp.quicksum(y[i, node] * data.w[i][k] for i in data.I)
                <= data.C_normal[node][k]
            )

    # 路径–送达耦合
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

    # ── 算力缺口（可选）──
    d_mk, e_ex = {}, {}
    if use_sf:
        _setup_compute_shortfall(m, data, y, d_mk, e_ex)

    # ── 逐场景构建 L_s ──
    L_s = {}
    for s in data.S:
        # 场景带宽成本 c_b(s)：按送达量 d 计费
        cost_b_s = gp.quicksum(
            del_in[i, node, p, s] * path_bandwidth_tariff(data, src, node, p)
            for i in data.I for node in data.M
            for p in range(len(data.P_cand[src, node]))
        ) + gp.quicksum(
            del_out[i, node, q, s] * path_bandwidth_tariff(data, node, dst, q)
            for i in data.I for node in data.M
            for q in range(len(data.P_cand[node, dst]))
        )

        # 聚合送达量 R（按任务）
        R_in = {
            i: gp.quicksum(
                del_in[i, node, p, s] for node in data.M
                for p in range(len(data.P_cand[src, node]))
            )
            for i in data.I
        }
        R_out = {
            i: gp.quicksum(
                del_out[i, node, q, s] for node in data.M
                for q in range(len(data.P_cand[node, dst]))
            )
            for i in data.I
        }

        # Shortfall_sum_s
        shortfall_sum_s = gp.quicksum(
            (data.b_in[i] - R_in[i]) + (data.b_out[i] - R_out[i])
            for i in data.I
        )

        bill_s = cost_p + cost_b_s + kappa_sum * shortfall_sum_s

        # 可选：最差任务公平项
        if use_max_sf:
            ell = m.addVars(data.I, lb=0, name=f"ell_{s}")
            sf_max_s = m.addVar(lb=0, name=f"sfmax_{s}")
            for i in data.I:
                m.addConstr(ell[i] >= (data.b_in[i] - R_in[i]) / max(data.b_in[i], 1e-9))
                m.addConstr(ell[i] >= (data.b_out[i] - R_out[i]) / max(data.b_out[i], 1e-9))
                m.addConstr(sf_max_s >= ell[i])
            bill_s += kappa_max * sf_max_s

        # 可选：算力缺口罚款
        if use_sf:
            compute_penalty_s = gp.quicksum(
                kappa_sf.get((node, k), 0.0) * e_ex[node, k, s]
                for node in data.M for k in data.K
            )
            bill_s += compute_penalty_s

        L_s[s] = bill_s
        m.addConstr(u_s[s] >= L_s[s] - zeta)

    # ── 目标：min CVaR_β(L) ──
    cvar_obj = zeta + (1.0 / (1.0 - beta)) * gp.quicksum(data.prob[s] * u_s[s] for s in data.S)

    # 可选送达奖励（对标现 Model A，默认 0）
    if omega_deliver > 0:
        exp_del = gp.quicksum(
            data.prob[s] * (
                gp.quicksum(del_in[i, node, p, s] for i in data.I for node in data.M
                            for p in range(len(data.P_cand[src, node])))
                + gp.quicksum(del_out[i, node, q, s] for i in data.I for node in data.M
                              for q in range(len(data.P_cand[node, dst])))
            )
            for s in data.S
        )
        m.setObjective(cvar_obj - omega_deliver * exp_del, GRB.MINIMIZE)
    else:
        m.setObjective(cvar_obj, GRB.MINIMIZE)

    m.optimize()
    return _extract_solution(m, data, cost_p, d_mk, e_ex, y, xin, xout, del_in, del_out,
                             kappa_sum, kappa_max, kappa_sf, beta, src, dst)


# ──────────────────────────────────────────────
#  Model M-C：min E[L_s]  s.t. CVaR_β(L) ≤ Γ_money
# ──────────────────────────────────────────────

def build_model_mc(
    data,
    gamma_money: float,
    kappa_sum: float = 5.0,
    kappa_max: float = 0.0,
    kappa_sf: dict | None = None,
    beta: float | None = None,
    min_tasks_off_hub: int = 0,
    *,
    include_compute_penalty: bool = True,
    mip_gap: float = 0.01,
    time_limit: float | None = None,
):
    """
    Model M-C：最小化期望账单，约束 CVaR ≤ Γ_money。

    推荐主部署模型——不依赖精确 κ，用 Γ 二分替代 λ 扫描。
    """
    h = _hub(data)
    src, dst = teavar_flow_anchors(data)
    if beta is None:
        beta = float(getattr(data, "beta_N", 0.95))

    use_sf = bool(include_compute_penalty and kappa_sf)
    use_max_sf = bool(kappa_max and kappa_max > 0.0)

    m = gp.Model("Model_MC_Budget")
    m.setParam("OutputFlag", 0)
    m.setParam("MIPGap", mip_gap)
    if time_limit is not None:
        m.setParam("TimeLimit", time_limit)

    Mbig = max(max(data.b_in.values()), max(data.b_out.values())) + 1.0

    y = m.addVars(data.valid_assign, vtype=GRB.BINARY, name="y")
    xin  = {(i, node, p): m.addVar(lb=0) for i in data.I for node in data.M
            for p in range(len(data.P_cand[src, node]))}
    xout = {(i, node, q): m.addVar(lb=0) for i in data.I for node in data.M
            for q in range(len(data.P_cand[node, dst]))}

    del_in, del_out = {}, {}
    for s in data.S:
        for i in data.I:
            for node in data.M:
                for p in range(len(data.P_cand[src, node])):
                    del_in[i, node, p, s] = m.addVar(lb=0)
                for q in range(len(data.P_cand[node, dst])):
                    del_out[i, node, q, s] = m.addVar(lb=0)

    zeta = m.addVar(lb=-GRB.INFINITY, name="zeta")
    u_s = m.addVars(data.S, lb=0, name="u")

    cost_p = gp.quicksum(
        y[i, node] * sum(data.w[i][k] * data.p_price[node][k] for k in data.K)
        for i, node in y
    )

    # ── 物理约束 ──
    m.addConstrs((y.sum(i, "*") == 1 for i in data.I))
    if min_tasks_off_hub > 0:
        m.addConstr(gp.quicksum(y[i, h] for i in data.I) <= len(data.I) - min_tasks_off_hub)

    for i in data.I:
        for node in data.M:
            m.addConstr(
                gp.quicksum(xin[i, node, p] for p in range(len(data.P_cand[src, node])))
                <= y[i, node] * data.b_in[i]
            )
            m.addConstr(
                gp.quicksum(xout[i, node, q] for q in range(len(data.P_cand[node, dst])))
                <= y[i, node] * data.b_out[i]
            )

    for node in data.M:
        for k in data.K:
            m.addConstr(
                gp.quicksum(y[i, node] * data.w[i][k] for i in data.I)
                <= data.C_normal[node][k]
            )

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

    d_mk, e_ex = {}, {}
    if use_sf:
        _setup_compute_shortfall(m, data, y, d_mk, e_ex)

    # ── 逐场景 L_s ──
    L_s = {}
    exp_bill = gp.LinExpr()
    for s in data.S:
        cost_b_s = gp.quicksum(
            del_in[i, node, p, s] * path_bandwidth_tariff(data, src, node, p)
            for i in data.I for node in data.M
            for p in range(len(data.P_cand[src, node]))
        ) + gp.quicksum(
            del_out[i, node, q, s] * path_bandwidth_tariff(data, node, dst, q)
            for i in data.I for node in data.M
            for q in range(len(data.P_cand[node, dst]))
        )

        R_in = {
            i: gp.quicksum(
                del_in[i, node, p, s] for node in data.M
                for p in range(len(data.P_cand[src, node]))
            )
            for i in data.I
        }
        R_out = {
            i: gp.quicksum(
                del_out[i, node, q, s] for node in data.M
                for q in range(len(data.P_cand[node, dst]))
            )
            for i in data.I
        }

        shortfall_sum_s = gp.quicksum(
            (data.b_in[i] - R_in[i]) + (data.b_out[i] - R_out[i])
            for i in data.I
        )

        bill_s = cost_p + cost_b_s + kappa_sum * shortfall_sum_s

        if use_max_sf:
            ell = m.addVars(data.I, lb=0, name=f"ell_{s}")
            sf_max_s = m.addVar(lb=0, name=f"sfmax_{s}")
            for i in data.I:
                m.addConstr(ell[i] >= (data.b_in[i] - R_in[i]) / max(data.b_in[i], 1e-9))
                m.addConstr(ell[i] >= (data.b_out[i] - R_out[i]) / max(data.b_out[i], 1e-9))
                m.addConstr(sf_max_s >= ell[i])
            bill_s += kappa_max * sf_max_s

        if use_sf:
            compute_penalty_s = gp.quicksum(
                kappa_sf.get((node, k), 0.0) * e_ex[node, k, s]
                for node in data.M for k in data.K
            )
            bill_s += compute_penalty_s

        L_s[s] = bill_s
        m.addConstr(u_s[s] >= L_s[s] - zeta)
        exp_bill.add(data.prob[s] * bill_s)

    # ── 目标 + CVaR 约束 ──
    m.setObjective(exp_bill, GRB.MINIMIZE)
    cvar_expr = zeta + (1.0 / (1.0 - beta)) * gp.quicksum(data.prob[s] * u_s[s] for s in data.S)
    m.addConstr(cvar_expr <= gamma_money, name="CVaR_budget")

    m.optimize()
    return _extract_solution(m, data, cost_p, d_mk, e_ex, y, xin, xout, del_in, del_out,
                             kappa_sum, kappa_max, kappa_sf, beta, src, dst)


# ──────────────────────────────────────────────
#  Model M-C 二分标定 Γ
# ──────────────────────────────────────────────

def bisect_gamma_mc(
    data,
    kappa_sum: float = 5.0,
    kappa_max: float = 0.0,
    kappa_sf: dict | None = None,
    beta: float | None = None,
    min_tasks_off_hub: int = 0,
    *,
    include_compute_penalty: bool = True,
    gamma_lo: float | None = None,
    gamma_hi: float | None = None,
    epsilon: float = 1e-4,
    max_iters: int = 30,
    verbose: bool = True,
    mip_gap: float = 0.01,
):
    """
    二分搜索 Γ_money：找到 Model M-C 的最紧可行风险预算。

    关键：CVaR 必须基于**统一 kappa 定义的 L_s** 才能比较。
    算法：
      1. CVaR_lo：用 Model M（min CVaR(L)，含完整 kappa）→ 理论最小可达 CVaR
      2. CVaR_hi：用 Model M（kappa=0，纯成本最小化）拿到解，再以**完整 kappa**
         事后计算该解的 CVaR → 成本最优解的尾部风险（以 SLA 账单衡量）
      3. 二分 Γ ∈ [CVaR_lo, CVaR_hi] 求解 Model M-C(Γ)

    Returns
    -------
    dict with keys: gamma_star, result, history, cvar_lo, cvar_hi
    """
    h = _hub(data)
    if beta is None:
        beta = float(getattr(data, "beta_N", 0.95))

    # ── Step 1: CVaR 下界（Model M 能达到的最好 CVaR，含完整 kappa）──
    if gamma_lo is None:
        if verbose:
            print("[bisect] Step 1: 标定最小可达 CVaR（Model M, 完整 κ）...")
        res_m = build_model_m(
            data, kappa_sum=kappa_sum, kappa_max=kappa_max,
            kappa_sf=kappa_sf if include_compute_penalty else None,
            beta=beta, min_tasks_off_hub=min_tasks_off_hub,
            include_compute_penalty=include_compute_penalty, mip_gap=mip_gap,
        )
        gamma_lo = res_m["cvar_value"] if res_m["cvar_value"] is not None else 0.0
        if verbose:
            print(f"  → CVaR_lo = {gamma_lo:.4f}  (最小可达尾部风险)")

    # ── Step 2: CVaR 上界（成本最优解，但用统一 kappa 重算 CVaR）──
    if gamma_hi is None:
        if verbose:
            print("[bisect] Step 2: 标定成本最优解的 CVaR（统一 κ 事后重算）...")
        res_cost = build_model_m(
            data, kappa_sum=0.0, kappa_max=0.0,
            kappa_sf=None,  # 不算算力罚款，纯成本
            beta=beta, min_tasks_off_hub=min_tasks_off_hub,
            include_compute_penalty=False, mip_gap=mip_gap,
        )
        # 事后用完整 kappa 重算 CVaR
        gamma_hi = _recompute_cvar_with_kappa(
            data, res_cost, kappa_sum, kappa_max, kappa_sf, beta,
            include_compute_penalty,
        )
        if verbose:
            print(f"  → CVaR_hi = {gamma_hi:.4f}  (成本最优解的尾部风险，以统一 κ 衡量)")

    if gamma_lo >= gamma_hi - epsilon:
        if verbose:
            print(f"[bisect] 成本最优解已达 CVaR 下界 (gap={gamma_hi - gamma_lo:.4f})，无需二分")
            # 直接返回 Model M 的解（它已经是最优的）
            if gamma_lo is not None and res_m is not None:
                return {"gamma_star": gamma_lo, "result": res_m, "history": [],
                        "cvar_lo": gamma_lo, "cvar_hi": gamma_hi}
        return {"gamma_star": gamma_lo, "result": None, "history": [],
                "cvar_lo": gamma_lo, "cvar_hi": gamma_hi}

    # ── Step 3: 二分 ──
    lo, hi = gamma_lo, gamma_hi
    history = []
    best_result = None
    best_gamma = hi

    for it in range(max_iters):
        if hi - lo <= epsilon:
            break
        mid = (lo + hi) / 2.0
        if verbose:
            print(f"  [iter {it:2d}] Γ = {mid:.2f}  ([{lo:.2f}, {hi:.2f}]) ...", end=" ")

        result = build_model_mc(
            data, gamma_money=mid,
            kappa_sum=kappa_sum, kappa_max=kappa_max,
            kappa_sf=kappa_sf if include_compute_penalty else None,
            beta=beta, min_tasks_off_hub=min_tasks_off_hub,
            include_compute_penalty=include_compute_penalty, mip_gap=mip_gap,
        )

        feasible = result["status"] == GRB.OPTIMAL
        history.append({"gamma": mid, "feasible": feasible,
                        "obj_val": result.get("expected_bill")})

        if feasible:
            if verbose:
                print(f"可行  E[L]={result.get('expected_bill', 0):.1f}")
            hi = mid
            best_result = result
            best_gamma = mid
        else:
            if verbose:
                print("不可行")
            lo = mid

    if verbose:
        print(f"[bisect] 完成: Γ* = {best_gamma:.2f}，{len(history)} 次迭代")

    return {
        "gamma_star": best_gamma,
        "result": best_result,
        "history": history,
        "cvar_lo": gamma_lo,
        "cvar_hi": gamma_hi,
    }


def _recompute_cvar_with_kappa(data, res_cost, kappa_sum, kappa_max, kappa_sf, beta,
                                include_compute):
    """用统一 kappa 事后重算某个解的 CVaR(L)。"""
    if res_cost is None or res_cost.get("placement") is None:
        return 1e9
    # 直接用已存场景数据重算
    L_vals = {}
    for s in data.S:
        L_s = res_cost.get("cost_p", 0) + res_cost.get("cb_per_scenario", {}).get(s, 0)
        L_s += kappa_sum * res_cost.get("shortfall_per_scenario", {}).get(s, 0)
        # kappa_max 和 kappa_sf 简化：暂用 0（它们未在 res_cost 中预存）
        L_vals[s] = L_s

    L_sorted = sorted(L_vals.items(), key=lambda x: -x[1])
    return _compute_cvar_from_samples(L_sorted, data.prob, beta)


# ──────────────────────────────────────────────
#  内部工具
# ──────────────────────────────────────────────

def _setup_compute_shortfall(m, data, y, d_mk, e_ex):
    """构建算力缺口变量与 Big-M 线性化（与 cvar_compare.py 同构）。"""
    d_max_any = 0.0
    for node in data.M:
        for k in data.K:
            dmax = float(sum(data.w[i][k] for i in data.I))
            d_max_any = max(d_max_any, dmax)
    Cmax = max(float(data.C_s[mm][kk][ss]) for mm in data.M for kk in data.K for ss in data.S)
    M_ex = max(d_max_any + 1.0, Cmax + 1.0, 1.0)

    for node in data.M:
        for k in data.K:
            d_mk[node, k] = m.addVar(lb=0.0)
            m.addConstr(d_mk[node, k] == gp.quicksum(y[i, node] * data.w[i][k] for i in data.I))

    for s in data.S:
        for node in data.M:
            for k in data.K:
                Ccap = float(data.C_s[node][k][s])
                x = d_mk[node, k] - Ccap
                e_ex[node, k, s] = m.addVar(lb=0.0)
                w_ex = m.addVar(vtype=GRB.BINARY)
                m.addConstr(e_ex[node, k, s] >= x)
                m.addConstr(e_ex[node, k, s] >= 0)
                m.addConstr(e_ex[node, k, s] <= x + M_ex * (1 - w_ex))
                m.addConstr(e_ex[node, k, s] <= M_ex * w_ex)


def _extract_solution(m, data, cost_p, d_mk, e_ex, y, xin, xout, del_in, del_out,
                      kappa_sum, kappa_max, kappa_sf, beta, src, dst):
    """从优化后的模型中提取结构化结果。"""
    status = m.status
    if status != GRB.OPTIMAL:
        return {"status": status, "obj_val": None, "cvar_value": None, "cost_p": None}

    cp = cost_p.getValue()

    # 逐场景反算
    cvar_val = float(m.getObjective().getValue()) if hasattr(m.getObjective(), 'getValue') else None
    # 更好的方式：直接取 CVaR 表达式值
    L_vals = {}
    shortfall_vals = {}
    cb_vals = {}
    for s in data.S:
        cb_s = 0.0
        sf_s = 0.0
        for i in data.I:
            R_in = sum(del_in[i, node, p, s].X for node in data.M
                       for p in range(len(data.P_cand[src, node])))
            R_out = sum(del_out[i, node, q, s].X for node in data.M
                        for q in range(len(data.P_cand[node, dst])))
            sf_s += max(0, data.b_in[i] - R_in) + max(0, data.b_out[i] - R_out)
            for node in data.M:
                for p in range(len(data.P_cand[src, node])):
                    cb_s += del_in[i, node, p, s].X * path_bandwidth_tariff(data, src, node, p)
                for q in range(len(data.P_cand[node, dst])):
                    cb_s += del_out[i, node, q, s].X * path_bandwidth_tariff(data, node, dst, q)

        L_s = cp + cb_s + kappa_sum * sf_s
        if e_ex:
            for node in data.M:
                for k in data.K:
                    L_s += kappa_sf.get((node, k), 0.0) * e_ex[node, k, s].X
        L_vals[s] = L_s
        shortfall_vals[s] = sf_s
        cb_vals[s] = cb_s

    # 期望账单
    exp_bill = sum(data.prob[s] * L_vals[s] for s in data.S)

    # 后算 CVaR(L)：按 L_vals 排序算 RU 值
    L_sorted = sorted(L_vals.items(), key=lambda x: -x[1])  # 降序
    cvar_post = _compute_cvar_from_samples(L_sorted, data.prob, beta)

    # 放置决策
    placement = {}
    for i in data.I:
        for node in data.M:
            if (i, node) in y and y[i, node].X > 0.5:
                placement[i] = node
                break

    # 送达率
    delivery_ratio = 0.0
    count_i = len(data.I)
    if count_i > 0:
        for i in data.I:
            avg = 0.0
            for s in data.S:
                R_in = sum(del_in[i, node, p, s].X for node in data.M
                           for p in range(len(data.P_cand[src, node])))
                R_out = sum(del_out[i, node, q, s].X for node in data.M
                            for q in range(len(data.P_cand[node, dst])))
                ratio_in = R_in / max(data.b_in[i], 1e-9)
                ratio_out = R_out / max(data.b_out[i], 1e-9)
                avg += data.prob[s] * (ratio_in + ratio_out) / 2.0
            delivery_ratio += avg
        delivery_ratio /= count_i

    return {
        "status": status,
        "obj_val": m.ObjVal,
        "cost_p": cp,
        "expected_bill": exp_bill,
        "cvar_value": cvar_post,
        "L_per_scenario": L_vals,
        "shortfall_per_scenario": shortfall_vals,
        "cb_per_scenario": cb_vals,
        "placement": placement,
        "expected_delivery_ratio": delivery_ratio,
    }


def _compute_cvar_from_samples(L_sorted, prob, beta):
    """给定排序后的 (s, L_s) 列表和概率，手动计算 CVaR_β。"""
    remaining = 1.0 - beta
    tail_sum = 0.0
    for s, L_s in L_sorted:
        if remaining <= 0:
            break
        take = min(prob[s], remaining)
        tail_sum += take * L_s
        remaining -= take
    return tail_sum / (1.0 - beta) if remaining <= 1e-12 else tail_sum / (1.0 - beta - remaining)


# ──────────────────────────────────────────────
#  与现 Model A 的快速对比
# ──────────────────────────────────────────────

def compare_model_a_vs_m(data, lambda_sla=5.0, kappa_sum=5.0, beta=None, verbose=True):
    """并排跑 Model A（现）与 Model M（新），打印对比。"""
    from cvar_compare import build_teavar_sla_cvar_model

    if beta is None:
        beta = float(getattr(data, "beta_N", 0.95))

    if verbose:
        print("=" * 60)
        print("  Model A (现, E+cost+λ·CVaR+ω)  vs  Model M (新, min CVaR(L))")
        print("=" * 60)

    # Model A
    ma, cp_a, cvar_a, _, _, ya, xia, xoa, dia, doa = build_teavar_sla_cvar_model(
        data, lambda_cvar=lambda_sla, omega_deliver=1.0,
        beta_loss=beta, lambda_node_cvar=0.0, lambda_compute_sf_cvar=0.0,
    )

    # Model M
    res_m = build_model_m(data, kappa_sum=kappa_sum, beta=beta,
                          include_compute_penalty=False)

    if verbose:
        print(f"\n{'':>14}  {'Model A (λ={lambda_sla})':>24}  {'Model M (κ={kappa_sum})':>24}")
        print("-" * 68)
        if ma.status == GRB.OPTIMAL:
            print(f"  {'obj_val':>14}  {ma.ObjVal:24.4f}  {res_m['obj_val']:24.4f}")
        print(f"  {'cost_p':>14}  {cp_a if cp_a else 'N/A':>24}  {res_m['cost_p']:24.4f}")
        print(f"  {'expected_bill':>14}  {'—':>24}  {res_m['expected_bill']:24.4f}")
        print(f"  {'CVaR':>14}  {cvar_a if cvar_a else 'N/A':>24}  {res_m['cvar_value']:24.4f}")
        print(f"  {'E[delivery]':>14}  {'—':>24}  {res_m['expected_delivery_ratio']:24.4f}")

        # 放置对比
        if ma.status == GRB.OPTIMAL:
            p_a = {i: next(node for node in data.M if (i, node) in ya and ya[i, node].X > 0.5)
                   for i in data.I}
            p_m = res_m["placement"]
            same = sum(1 for i in data.I if p_a.get(i) == p_m.get(i))
            print(f"\n  放置一致: {same}/{len(data.I)}")
            if same < len(data.I):
                print(f"    Model A: {p_a}")
                print(f"    Model M: {p_m}")

    return ma, res_m


# ──────────────────────────────────────────────
#  main：玩具数据测试
# ──────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    from duibi import UltraComplexData
    from b4_joint_data import load_joint_data

    ap = argparse.ArgumentParser(description="Model M / M-C 货币化纯 CVaR 测试")
    ap.add_argument("--topology", type=str, default="toy",
                    help="toy | B4 | Sprint | Abilene | ...")
    ap.add_argument("--kappa-sum", type=float, default=5.0)
    ap.add_argument("--kappa-max", type=float, default=0.0)
    ap.add_argument("--beta", type=float, default=0.95)
    ap.add_argument("--gamma", type=float, default=None,
                    help="Model M-C 的 Γ_money；不指定则跑 Model M")
    ap.add_argument("--bisect", action="store_true",
                    help="对 Model M-C 跑 Γ 二分")
    ap.add_argument("--compare", action="store_true",
                    help="并排对比 Model A vs Model M")
    ap.add_argument("--num-tasks", type=int, default=10)
    ap.add_argument("--min-off-hub", type=int, default=0,
                    help="至少 K 个任务不放在 hub 上（打破空路径退化）")
    ap.add_argument("--mip-gap", type=float, default=0.01)
    args = ap.parse_args()

    # 加载数据
    if args.topology == "toy":
        data = UltraComplexData()
        print("使用玩具数据 (UltraComplexData: 4 nodes, 10 tasks, 3 scenarios)")
    else:
        data = load_joint_data(
            topology_name=args.topology,
            num_tasks=args.num_tasks,
            k_paths=3,
            stress_zero_s1=True,
        )
        print(f"使用 {args.topology} 拓扑数据 ({len(data.M)} nodes, {len(data.I)} tasks)")

    beta = args.beta if args.beta is not None else float(getattr(data, "beta_N", 0.95))

    min_off = args.min_off_hub

    if args.compare:
        compare_model_a_vs_m(data, lambda_sla=5.0, kappa_sum=args.kappa_sum, beta=beta)

    elif args.bisect:
        result = bisect_gamma_mc(
            data, kappa_sum=args.kappa_sum, kappa_max=args.kappa_max,
            beta=beta, min_tasks_off_hub=min_off, verbose=True, mip_gap=args.mip_gap,
        )
        if result["result"] is not None:
            r = result["result"]
            print(f"\n  Γ* = {result['gamma_star']:.4f}")
            print(f"  min E[L] = {r['expected_bill']:.4f}")
            print(f"  cost_p    = {r['cost_p']:.4f}")
            print(f"  placement = {r['placement']}")

    elif args.gamma is not None:
        res = build_model_mc(
            data, gamma_money=args.gamma,
            kappa_sum=args.kappa_sum, kappa_max=args.kappa_max,
            beta=beta, min_tasks_off_hub=min_off,
            include_compute_penalty=False, mip_gap=args.mip_gap,
        )
        print(f"\n  status        = {res['status']}")
        print(f"  min E[L]      = {res['expected_bill']:.4f}")
        print(f"  CVaR(L)       = {res['cvar_value']:.4f}")
        print(f"  cost_p        = {res['cost_p']:.4f}")
        print(f"  placement     = {res['placement']}")
        print(f"  E[delivery%]  = {res['expected_delivery_ratio']:.4f}")

    else:
        # 默认：跑 Model M
        res = build_model_m(
            data, kappa_sum=args.kappa_sum, kappa_max=args.kappa_max,
            beta=beta, min_tasks_off_hub=min_off,
            include_compute_penalty=False, mip_gap=args.mip_gap,
        )
        print(f"\n  status        = {res['status']}")
        print(f"  min CVaR(L)   = {res['obj_val']:.4f}")
        print(f"  CVaR_post     = {res['cvar_value']:.4f}")
        print(f"  E[L]          = {res['expected_bill']:.4f}")
        print(f"  cost_p        = {res['cost_p']:.4f}")
        print(f"  placement     = {res['placement']}")
        print(f"  E[delivery%]  = {res['expected_delivery_ratio']:.4f}")
        print(f"\n  逐场景账单:")
        for s in sorted(res["L_per_scenario"]):
            print(f"    s={s} (π={data.prob[s]:.2f}): L={res['L_per_scenario'][s]:.2f}  "
                  f"SF={res['shortfall_per_scenario'][s]:.2f}  cb={res['cb_per_scenario'][s]:.2f}")
