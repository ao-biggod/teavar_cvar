# -*- coding: utf-8 -*-
"""
Model M / Model M-C：货币化场景账单 + 纯 CVaR 或期望账单 @ CVaR 预算。

见 ``建模_货币化纯CVaR.md``。

  Model M:   min  CVaR_beta(L)
  Model M-C: min  E[L_s]   s.t. CVaR_beta(L) <= Gamma_money

  L_s = c_p + c_b(s) + kappa_sum * Shortfall_sum_s + kappa_max * Shortfall_max_s + kappa_sf * sum_{m,k} e_{mks}
"""
from __future__ import annotations

import argparse
import time
from dataclasses import dataclass
from typing import Any

import gurobipy as gp
from gurobipy import GRB

from cvar_compare import add_teavar_virtual_bottleneck_constraints, build_teavar_sla_cvar_model
from duibi import UltraComplexData
from duibi_metrics import (
    expected_delivery_ratio,
    path_bandwidth_tariff,
    path_up,
    scenario_bandwidth_cost_value,
    teavar_flow_anchors,
)


@dataclass
class MonetarySolveResult:
    model: gp.Model
    status: int
    cvar_L: float | None
    E_L: float | None
    cost_p: float | None
    E_cost_b: float | None
    E_shortfall_vol: float | None
    y: Any
    xin: Any
    xout: Any
    del_in: Any
    del_out: Any
    L_per_scenario: dict | None = None
    cb_per_scenario: dict | None = None
    shortfall_per_scenario: dict | None = None
    placement: dict | None = None


def _hub(data) -> int:
    return int(getattr(data, "hub", 0))


def _placement_cost(data, y) -> gp.LinExpr:
    return gp.quicksum(
        y[i, node] * sum(data.w[i][k] * data.p_price[node][k] for k in data.K)
        for i, node in y
    )


def _placement_cost_value(data, y) -> float:
    return sum(
        y[i, node].X * sum(data.w[i][k] * data.p_price[node][k] for k in data.K)
        for i, node in y
    )


def _extract_placement(data, y) -> dict:
    placement = {}
    for i in data.I:
        for node in data.M:
            if (i, node) in y and y[i, node].X > 0.5:
                placement[i] = node
                break
    return placement


def _scenario_bandwidth_cost(data, s, del_in, del_out, in_u, out_v) -> gp.LinExpr:
    return gp.quicksum(
        del_in[i, node, p, s] * path_bandwidth_tariff(data, in_u, node, p)
        for i in data.I
        for node in data.M
        for p in range(len(data.P_cand[in_u, node]))
    ) + gp.quicksum(
        del_out[i, node, q, s] * path_bandwidth_tariff(data, node, out_v, q)
        for i in data.I
        for node in data.M
        for q in range(len(data.P_cand[node, out_v]))
    )


def _compute_exc_from_placement(data, y) -> dict:
    e_ex = {}
    for s in data.S:
        for node in data.M:
            for k in data.K:
                demand = sum(y[i, node].X * data.w[i][k] for i in data.I if (i, node) in y)
                e_ex[node, k, s] = max(0.0, demand - float(data.C_s[node][k][s]))
    return e_ex


def _compute_cvar_from_samples(L_sorted: list[tuple], prob, beta: float) -> float:
    """给定降序排列的 (s, L_s) 与场景概率，计算 CVaR_beta。"""
    remaining = 1.0 - beta
    tail_sum = 0.0
    for s, L_s in L_sorted:
        if remaining <= 1e-12:
            break
        take = min(float(prob[s]), remaining)
        tail_sum += take * L_s
        remaining -= take
    denom = 1.0 - beta
    return tail_sum / denom if denom > 1e-12 else tail_sum


def _scenario_bills_from_solution(
    data,
    y,
    del_in,
    del_out,
    *,
    kappa_sum: float = 1.0,
    kappa_max: float = 0.0,
    kappa_sf: float = 0.0,
    cost_p: float | None = None,
) -> tuple[float, dict, dict, dict]:
    """从任意可行解事后重算逐场景 L_s、带宽费与 shortfall。"""
    in_u, out_v = teavar_flow_anchors(data)
    cp = cost_p if cost_p is not None else _placement_cost_value(data, y)
    e_ex = _compute_exc_from_placement(data, y) if kappa_sf > 0.0 else {}

    def _del_in_val(i, node, p, s) -> float:
        key = (i, node, p, s)
        return float(del_in[key].X) if key in del_in else 0.0

    def _del_out_val(i, node, q, s) -> float:
        key = (i, node, q, s)
        return float(del_out[key].X) if key in del_out else 0.0

    L_vals: dict = {}
    cb_vals: dict = {}
    sf_vals: dict = {}

    for s in data.S:
        cb_s = scenario_bandwidth_cost_value(data, del_in, del_out, in_u, out_v, s)

        sf_s = 0.0
        ell_max = 0.0
        for i in data.I:
            R_in = sum(
                _del_in_val(i, node, p, s)
                for node in data.M
                for p in range(len(data.P_cand[in_u, node]))
            )
            R_out = sum(
                _del_out_val(i, node, q, s)
                for node in data.M
                for q in range(len(data.P_cand[node, out_v]))
            )
            sf_in = max(0.0, float(data.b_in[i]) - R_in)
            sf_out = max(0.0, float(data.b_out[i]) - R_out)
            sf_s += sf_in + sf_out
            if kappa_max > 0.0:
                if data.b_in[i] > 1e-12:
                    ell_max = max(ell_max, sf_in / float(data.b_in[i]))
                if data.b_out[i] > 1e-12:
                    ell_max = max(ell_max, sf_out / float(data.b_out[i]))

        L_s = cp + cb_s + float(kappa_sum) * sf_s
        if kappa_max > 0.0:
            L_s += float(kappa_max) * ell_max
        if kappa_sf > 0.0:
            L_s += float(kappa_sf) * sum(e_ex[node, k, s] for node in data.M for k in data.K)

        L_vals[s] = L_s
        cb_vals[s] = cb_s
        sf_vals[s] = sf_s

    return cp, L_vals, cb_vals, sf_vals


def recompute_monetary_bills(
    data,
    y,
    del_in,
    del_out,
    *,
    kappa_sum: float = 1.0,
    kappa_max: float = 0.0,
    kappa_sf: float = 0.0,
    beta: float | None = None,
) -> dict:
    """对任意解（含 Model A）用统一 kappa 定义事后计算 E[L] 与 CVaR(L)。"""
    if beta is None:
        beta = float(getattr(data, "beta_N", 0.95))

    cp, L_vals, cb_vals, sf_vals = _scenario_bills_from_solution(
        data, y, del_in, del_out,
        kappa_sum=kappa_sum, kappa_max=kappa_max, kappa_sf=kappa_sf,
    )
    exp_bill = sum(float(data.prob[s]) * L_vals[s] for s in data.S)
    L_sorted = sorted(L_vals.items(), key=lambda x: -x[1])
    cvar_L = _compute_cvar_from_samples(L_sorted, data.prob, beta)

    return {
        "cost_p": cp,
        "expected_bill": exp_bill,
        "cvar_L": cvar_L,
        "L_per_scenario": L_vals,
        "cb_per_scenario": cb_vals,
        "shortfall_per_scenario": sf_vals,
        "placement": _extract_placement(data, y),
    }


def _add_compute_exc(data, m, y, M_ex: float) -> dict:
    d_mk = {}
    for node in data.M:
        for k in data.K:
            d_mk[node, k] = m.addVar(lb=0.0, name=f"dreq_{node}_{k}")
            m.addConstr(
                d_mk[node, k] == gp.quicksum(y[i, node] * data.w[i][k] for i in data.I),
                name=f"ddef_{node}_{k}",
            )
    e_ex = {}
    for s in data.S:
        for node in data.M:
            for k in data.K:
                Ccap = float(data.C_s[node][k][s])
                x = d_mk[node, k] - Ccap
                e_ex[node, k, s] = m.addVar(lb=0.0, name=f"exc_{node}_{k}_{s}")
                w_ex = m.addVar(vtype=GRB.BINARY, name=f"wexc_{node}_{k}_{s}")
                m.addConstr(e_ex[node, k, s] >= x)
                m.addConstr(e_ex[node, k, s] >= 0)
                m.addConstr(e_ex[node, k, s] <= x + M_ex * (1 - w_ex))
                m.addConstr(e_ex[node, k, s] <= M_ex * w_ex)
    return e_ex


def _normalize_kappa_sf(kappa_sf: float | dict | None) -> float:
    if kappa_sf is None:
        return 0.0
    if isinstance(kappa_sf, (int, float)):
        return float(kappa_sf)
    if isinstance(kappa_sf, dict):
        vals = [float(v) for v in kappa_sf.values() if v]
        return max(vals) if vals else 0.0
    return 0.0


def _build_monetary_milp_core(
    data,
    *,
    kappa_sum: float = 1.0,
    kappa_max: float = 0.0,
    kappa_sf: float | dict | None = 0.0,
    beta: float | None = None,
    min_tasks_off_hub: int = 0,
    output_flag: int = 0,
    mip_gap: float = 0.01,
):
    kappa_sf_val = _normalize_kappa_sf(kappa_sf)

    if beta is None:
        beta = float(getattr(data, "beta_N", 0.95))

    h = _hub(data)
    in_u, out_v = teavar_flow_anchors(data)
    Mbig = max(max(data.b_in.values()), max(data.b_out.values())) + 1.0

    m = gp.Model("Monetary_CVaR")
    m.setParam("OutputFlag", output_flag)
    m.setParam("MIPGap", mip_gap)

    y = m.addVars(data.valid_assign, vtype=GRB.BINARY, name="y")
    xin = {
        (i, node, p): m.addVar(lb=0, name=f"xin_{i}_{node}_{p}")
        for i in data.I
        for node in data.M
        for p in range(len(data.P_cand[in_u, node]))
    }
    xout = {
        (i, node, q): m.addVar(lb=0, name=f"xout_{i}_{node}_{q}")
        for i in data.I
        for node in data.M
        for q in range(len(data.P_cand[node, out_v]))
    }
    del_in = {}
    del_out = {}
    for s in data.S:
        for i in data.I:
            for node in data.M:
                for p in range(len(data.P_cand[in_u, node])):
                    del_in[i, node, p, s] = m.addVar(lb=0, name=f"din_{i}_{node}_{p}_{s}")
                for q in range(len(data.P_cand[node, out_v])):
                    del_out[i, node, q, s] = m.addVar(lb=0, name=f"dout_{i}_{node}_{q}_{s}")

    cost_p = _placement_cost(data, y)

    m.addConstrs((y.sum(i, "*") == 1 for i in data.I), name="assign")
    if min_tasks_off_hub and min_tasks_off_hub > 0:
        m.addConstr(
            gp.quicksum(y[i, h] for i in data.I) <= len(data.I) - min_tasks_off_hub,
            name="min_off_hub",
        )

    for i in data.I:
        for node in data.M:
            m.addConstr(
                gp.quicksum(xin[i, node, p] for p in range(len(data.P_cand[in_u, node])))
                <= y[i, node] * data.b_in[i],
            )
            m.addConstr(
                gp.quicksum(xout[i, node, q] for q in range(len(data.P_cand[node, out_v])))
                <= y[i, node] * data.b_out[i],
            )

    for node in data.M:
        for k in data.K:
            m.addConstr(gp.quicksum(y[i, node] * data.w[i][k] for i in data.I) <= data.C_normal[node][k])

    for s in data.S:
        for i in data.I:
            for node in data.M:
                for p in range(len(data.P_cand[in_u, node])):
                    di, xi = del_in[i, node, p, s], xin[i, node, p]
                    if path_up(data, in_u, node, p, s):
                        m.addConstr(di <= xi)
                        m.addConstr(di <= Mbig * y[i, node])
                        m.addConstr(di >= xi - Mbig * (1 - y[i, node]))
                    else:
                        m.addConstr(di == 0)
                for q in range(len(data.P_cand[node, out_v])):
                    do, xo = del_out[i, node, q, s], xout[i, node, q]
                    if path_up(data, node, out_v, q, s):
                        m.addConstr(do <= xo)
                        m.addConstr(do <= Mbig * y[i, node])
                        m.addConstr(do >= xo - Mbig * (1 - y[i, node]))
                    else:
                        m.addConstr(do == 0)

    add_teavar_virtual_bottleneck_constraints(m, data, y, del_in, del_out, h)

    sf_in, sf_out, ell_ratio = {}, {}, {}
    for s in data.S:
        for i in data.I:
            Rin = gp.quicksum(
                del_in[i, node, p, s] for node in data.M for p in range(len(data.P_cand[in_u, node]))
            )
            Rout = gp.quicksum(
                del_out[i, node, q, s] for node in data.M for q in range(len(data.P_cand[node, out_v]))
            )
            sf_in[i, s] = m.addVar(lb=0.0, name=f"sf_in_{i}_{s}")
            sf_out[i, s] = m.addVar(lb=0.0, name=f"sf_out_{i}_{s}")
            m.addConstr(sf_in[i, s] >= float(data.b_in[i]) - Rin)
            m.addConstr(sf_out[i, s] >= float(data.b_out[i]) - Rout)
            if kappa_max > 0.0:
                ell_ratio[i, s] = m.addVar(lb=0.0, name=f"ell_{i}_{s}")
                if data.b_in[i] > 1e-12:
                    m.addConstr(ell_ratio[i, s] >= sf_in[i, s] / float(data.b_in[i]))
                if data.b_out[i] > 1e-12:
                    m.addConstr(ell_ratio[i, s] >= sf_out[i, s] / float(data.b_out[i]))

    e_ex = {}
    if kappa_sf_val > 0.0:
        d_max_any = max(sum(data.w[i][k] for i in data.I) for node in data.M for k in data.K)
        Cmax = max(float(data.C_s[node][k][s]) for node in data.M for k in data.K for s in data.S)
        M_ex = max(float(d_max_any) + 1.0, Cmax + 1.0, 1.0)
        e_ex = _add_compute_exc(data, m, y, M_ex)

    L_s = {}
    shortfall_max = {}
    for s in data.S:
        shortfall_sum_s = gp.quicksum(sf_in[i, s] + sf_out[i, s] for i in data.I)
        cost_b_s = _scenario_bandwidth_cost(data, s, del_in, del_out, in_u, out_v)
        penalty_sf_s = gp.LinExpr(0.0)
        if kappa_sf_val > 0.0:
            penalty_sf_s = float(kappa_sf_val) * gp.quicksum(
                e_ex[node, k, s] for node in data.M for k in data.K
            )
        max_term = gp.LinExpr(0.0)
        if kappa_max > 0.0:
            shortfall_max[s] = m.addVar(lb=0.0, name=f"sf_max_{s}")
            for i in data.I:
                m.addConstr(shortfall_max[s] >= ell_ratio[i, s])
            max_term = float(kappa_max) * shortfall_max[s]
        L_s[s] = cost_p + cost_b_s + float(kappa_sum) * shortfall_sum_s + max_term + penalty_sf_s

    zeta = m.addVar(lb=-GRB.INFINITY, name="zeta")
    u_s = m.addVars(data.S, lb=0.0, name="u_tail")
    for s in data.S:
        m.addConstr(u_s[s] >= L_s[s] - zeta, name=f"ru_{s}")

    cvar_expr = zeta + (1.0 / (1.0 - beta)) * gp.quicksum(float(data.prob[s]) * u_s[s] for s in data.S)
    E_L_expr = gp.quicksum(float(data.prob[s]) * L_s[s] for s in data.S)

    core = {
        "beta": beta,
        "kappa_sum": kappa_sum,
        "kappa_max": kappa_max,
        "kappa_sf": kappa_sf_val,
        "cost_p": cost_p,
        "L_s": L_s,
        "cvar_expr": cvar_expr,
        "E_L_expr": E_L_expr,
        "in_u": in_u,
        "out_v": out_v,
    }
    return m, y, xin, xout, del_in, del_out, core


def _pack_result(m, y, xin, xout, del_in, del_out, core, data) -> MonetarySolveResult:
    if m.status != GRB.OPTIMAL:
        return MonetarySolveResult(
            m, m.status, None, None, None, None, None, y, xin, xout, del_in, del_out
        )

    cp, L_vals, cb_vals, sf_vals = _scenario_bills_from_solution(
        data, y, del_in, del_out,
        kappa_sum=core["kappa_sum"],
        kappa_max=core["kappa_max"],
        kappa_sf=core["kappa_sf"],
        cost_p=float(core["cost_p"].getValue()),
    )
    beta = core["beta"]
    E_L_v = sum(float(data.prob[s]) * L_vals[s] for s in data.S)
    L_sorted = sorted(L_vals.items(), key=lambda x: -x[1])
    cvar_v = _compute_cvar_from_samples(L_sorted, data.prob, beta)
    E_cb = sum(float(data.prob[s]) * cb_vals[s] for s in data.S)
    E_sf = sum(float(data.prob[s]) * sf_vals[s] for s in data.S)

    return MonetarySolveResult(
        m,
        m.status,
        cvar_v,
        E_L_v,
        cp,
        E_cb,
        E_sf,
        y,
        xin,
        xout,
        del_in,
        del_out,
        L_per_scenario=L_vals,
        cb_per_scenario=cb_vals,
        shortfall_per_scenario=sf_vals,
        placement=_extract_placement(data, y),
    )


def build_monetary_cvar_model(
    data,
    *,
    kappa_sum: float = 1.0,
    kappa_max: float = 0.0,
    kappa_sf: float | dict | None = 0.0,
    beta: float | None = None,
    min_tasks_off_hub: int = 0,
    output_flag: int = 0,
    mip_gap: float = 0.01,
) -> MonetarySolveResult:
    """Model M: min CVaR_beta(L)."""
    m, y, xin, xout, del_in, del_out, core = _build_monetary_milp_core(
        data,
        kappa_sum=kappa_sum,
        kappa_max=kappa_max,
        kappa_sf=kappa_sf,
        beta=beta,
        min_tasks_off_hub=min_tasks_off_hub,
        output_flag=output_flag,
        mip_gap=mip_gap,
    )
    m.setObjective(core["cvar_expr"], GRB.MINIMIZE)
    m.optimize()
    return _pack_result(m, y, xin, xout, del_in, del_out, core, data)


def build_monetary_cvar_model_c(
    data,
    gamma_money: float,
    *,
    kappa_sum: float = 1.0,
    kappa_max: float = 0.0,
    kappa_sf: float | dict | None = 0.0,
    beta: float | None = None,
    min_tasks_off_hub: int = 0,
    output_flag: int = 0,
    mip_gap: float = 0.01,
) -> MonetarySolveResult:
    """Model M-C: min E[L_s]  s.t. CVaR_beta(L) <= gamma_money."""
    m, y, xin, xout, del_in, del_out, core = _build_monetary_milp_core(
        data,
        kappa_sum=kappa_sum,
        kappa_max=kappa_max,
        kappa_sf=kappa_sf,
        beta=beta,
        min_tasks_off_hub=min_tasks_off_hub,
        output_flag=output_flag,
        mip_gap=mip_gap,
    )
    m.addConstr(core["cvar_expr"] <= float(gamma_money), name="cvar_budget")
    m.setObjective(core["E_L_expr"], GRB.MINIMIZE)
    m.optimize()
    return _pack_result(m, y, xin, xout, del_in, del_out, core, data)


def _bisect_hi_bound(
    data,
    r_m: MonetarySolveResult,
    *,
    kappa_sum: float,
    kappa_max: float,
    kappa_sf: float,
    beta: float,
    cvar_slack: float,
    expand_hi: bool,
    min_tasks_off_hub: int,
    mip_gap: float,
) -> float:
    hi = r_m.cvar_L * cvar_slack
    if not expand_hi or r_m.cvar_L is None:
        return hi

    r_cost = build_monetary_cvar_model(
        data,
        kappa_sum=0.0,
        kappa_max=0.0,
        kappa_sf=0.0,
        beta=beta,
        min_tasks_off_hub=min_tasks_off_hub,
        mip_gap=mip_gap,
    )
    if r_cost.status != GRB.OPTIMAL:
        return hi

    bills = recompute_monetary_bills(
        data, r_cost.y, r_cost.del_in, r_cost.del_out,
        kappa_sum=kappa_sum, kappa_max=kappa_max, kappa_sf=kappa_sf, beta=beta,
    )
    return max(hi, bills["cvar_L"])


def bisect_monetary_cvar_c(
    data,
    *,
    kappa_sum: float = 1.0,
    kappa_max: float = 0.0,
    kappa_sf: float = 0.0,
    beta: float | None = None,
    min_tasks_off_hub: int = 0,
    tol: float = 1e-2,
    max_iter: int = 20,
    cvar_slack: float = 1.05,
    expand_hi: bool = False,
    verbose: bool = True,
    mip_gap: float = 0.01,
) -> tuple[MonetarySolveResult | None, float]:
    """二分 Gamma_money：找最紧仍可行的 M-C 解。"""
    if beta is None:
        beta = float(getattr(data, "beta_N", 0.95))

    r_m = build_monetary_cvar_model(
        data,
        kappa_sum=kappa_sum,
        kappa_max=kappa_max,
        kappa_sf=kappa_sf,
        beta=beta,
        min_tasks_off_hub=min_tasks_off_hub,
        mip_gap=mip_gap,
    )
    if r_m.cvar_L is None:
        return None, float("nan")

    lo = r_m.cvar_L
    hi = _bisect_hi_bound(
        data, r_m,
        kappa_sum=kappa_sum, kappa_max=kappa_max, kappa_sf=kappa_sf, beta=beta,
        cvar_slack=cvar_slack, expand_hi=expand_hi,
        min_tasks_off_hub=min_tasks_off_hub, mip_gap=mip_gap,
    )
    best, best_g = r_m, lo

    if verbose:
        print(f"  [bisect] Model M CVaR*={r_m.cvar_L:.4f}, search Gamma in [{lo:.2f}, {hi:.2f}]")

    for it in range(max_iter):
        mid = 0.5 * (lo + hi)
        res = build_monetary_cvar_model_c(
            data, mid,
            kappa_sum=kappa_sum, kappa_max=kappa_max, kappa_sf=kappa_sf,
            beta=beta, min_tasks_off_hub=min_tasks_off_hub, mip_gap=mip_gap,
        )
        ok = res.status == GRB.OPTIMAL
        if verbose:
            print(
                f"  [{it+1}] Gamma={mid:.4f} ok={ok} "
                f"E[L]={res.E_L if ok else '-'} CVaR={res.cvar_L if ok else '-'}"
            )
        if ok:
            best, best_g = res, mid
            hi = mid
        else:
            lo = mid
        if hi - lo <= tol:
            break
    return best, best_g


def print_monetary_result(label: str, r: MonetarySolveResult):
    def f(x):
        return f"{x:10.3f}" if x is not None else "       n/a"

    print(
        f"{label:18s} | CVaR(L)={f(r.cvar_L)} | E[L]={f(r.E_L)} | c_p={f(r.cost_p)} | "
        f"E[c_b(s)]={f(r.E_cost_b)} | E[shortfall]={f(r.E_shortfall_vol)}"
    )


def print_scenario_breakdown(
    label: str,
    r: MonetarySolveResult,
    data,
    *,
    kappa_sum: float = 0.0,
    top_k: int | None = None,
):
    """打印逐场景 L_s 分解，便于发现哪条场景拉高 CVaR。"""
    if r.L_per_scenario is None:
        print(f"{label}: 无场景级数据（未最优或缺少 breakdown）")
        return

    print(f"\n--- {label} 场景账单 L_s (beta={getattr(data, 'beta_N', 0.95)}) ---")
    rows = sorted(r.L_per_scenario.items(), key=lambda x: -x[1])
    if top_k is not None:
        rows = rows[:top_k]

    h = _hub(data)
    on_hub = sum(1 for node in (r.placement or {}).values() if node == h)
    print(f"  放置: hub 上 {on_hub}/{len(data.I)}  |  {r.placement}")

    print(f"  {'s':>4}  {'pi':>6}  {'c_b(s)':>10}  {'sf_vol':>10}  {'κ*sf':>10}  {'L_s':>10}")
    for s, L_s in rows:
        ps = float(data.prob[s])
        cb = r.cb_per_scenario.get(s, 0.0) if r.cb_per_scenario else 0.0
        sf = r.shortfall_per_scenario.get(s, 0.0) if r.shortfall_per_scenario else 0.0
        ksf = float(kappa_sum) * sf
        print(f"  {s:4d}  {ps:6.3f}  {cb:10.3f}  {sf:10.3f}  {ksf:10.3f}  {L_s:10.3f}")


def load_monetary_data(
    *,
    toy: bool = False,
    topology: str = "B4",
    num_tasks: int = 8,
    k_paths: int = 4,
    stress_zero_s1: bool | None = None,
):
    if toy or topology.lower() == "toy":
        return UltraComplexData(), "UltraComplexData (toy)"

    from b4_joint_data import load_joint_data

    if stress_zero_s1 is None:
        stress_zero_s1 = topology.upper() == "B4"

    data = load_joint_data(
        topology_name=topology,
        num_tasks=num_tasks,
        k_paths=k_paths,
        stress_zero_s1=stress_zero_s1,
    )
    label = f"{topology} | |I|={len(data.I)} | stress_s1={stress_zero_s1}"
    return data, label


def compare_with_model_a(
    data,
    kappa_sum: float,
    *,
    kappa_max: float = 0.0,
    kappa_sf: float = 0.0,
    lambda_sla: float = 5.0,
    omega: float = 1.0,
    beta: float | None = None,
    min_tasks_off_hub: int = 0,
    show_scenarios: bool = True,
    mip_gap: float = 0.01,
):
    if beta is None:
        beta = float(getattr(data, "beta_N", 0.95))

    print("\n=== Model A (teavar_sla) ===")
    t0 = time.perf_counter()
    ma, cp, cvar_sla, _, _, y, xi, xo, di, do = build_teavar_sla_cvar_model(
        data,
        lambda_cvar=lambda_sla,
        omega_deliver=omega,
        lambda_node_cvar=0.0,
        lambda_compute_sf_cvar=0.0,
        min_tasks_off_node0=min_tasks_off_hub,
    )
    dt = time.perf_counter() - t0

    bills_a = None
    if ma.status == GRB.OPTIMAL:
        bills_a = recompute_monetary_bills(
            data, y, di, do,
            kappa_sum=kappa_sum, kappa_max=kappa_max, kappa_sf=kappa_sf, beta=beta,
        )
        print(
            f"  time={dt:.2f}s  reported_cost={cp:.3f}  CVaR_SLA={cvar_sla:.4f}  "
            f"avgDeliv={expected_delivery_ratio(data, ma, y, xi, xo):.3f}"
        )
        print(
            f"  统一κ事后: E[L]={bills_a['expected_bill']:.3f}  "
            f"CVaR(L)={bills_a['cvar_L']:.3f}  placement={bills_a['placement']}"
        )
    else:
        print(f"  status={ma.status}")

    print("\n=== Model M ===")
    t0 = time.perf_counter()
    rm = build_monetary_cvar_model(
        data, kappa_sum=kappa_sum, kappa_max=kappa_max, kappa_sf=kappa_sf,
        beta=beta, min_tasks_off_hub=min_tasks_off_hub, mip_gap=mip_gap,
    )
    print(f"  time={time.perf_counter()-t0:.2f}s")
    print_monetary_result("Model M", rm)

    if show_scenarios:
        if bills_a:
            print_scenario_breakdown(
                "Model A (统一κ)", _bills_to_result_stub(bills_a), data, kappa_sum=kappa_sum,
            )
        print_scenario_breakdown("Model M", rm, data, kappa_sum=kappa_sum)

    rc = None
    if rm.cvar_L is not None:
        g = rm.cvar_L * 1.05
        print(f"\n=== Model M-C (Gamma={g:.2f}) ===")
        rc = build_monetary_cvar_model_c(
            data, g, kappa_sum=kappa_sum, kappa_max=kappa_max, kappa_sf=kappa_sf,
            beta=beta, min_tasks_off_hub=min_tasks_off_hub, mip_gap=mip_gap,
        )
        print_monetary_result("Model M-C", rc)
        if show_scenarios:
            print_scenario_breakdown("Model M-C", rc, data, kappa_sum=kappa_sum)

    if rm.cvar_L is not None and bills_a:
        headers = ["Model A", "Model M"]
        cvar_sla_col = f"{cvar_sla:.4f}"
        cvar_a = f"{bills_a['cvar_L']:.4f}"
        cvar_m = f"{rm.cvar_L:.4f}"
        el_a = f"{bills_a['expected_bill']:.4f}"
        el_m = f"{rm.E_L:.4f}"
        cp_a = f"{bills_a['cost_p']:.4f}"
        cp_m = f"{rm.cost_p:.4f}"
        cvar_c = el_c = cp_c = "—"
        if rc is not None and rc.cvar_L is not None:
            headers.append("Model M-C")
            cvar_c = f"{rc.cvar_L:.4f}"
            el_c = f"{rc.E_L:.4f}"
            cp_c = f"{rc.cost_p:.4f}"

        w = 14
        print(f"\n{'':>16}  " + "  ".join(f"{h:>{w}}" for h in headers))
        print("-" * (18 + (w + 2) * len(headers)))
        print(f"  {'CVaR_SLA':>16}  {cvar_sla_col:>{w}}  {'—':>{w}}" + (f"  {'—':>{w}}" if len(headers) > 2 else ""))
        print(f"  {'CVaR(L)@κ':>16}  {cvar_a:>{w}}  {cvar_m:>{w}}" + (f"  {cvar_c:>{w}}" if len(headers) > 2 else ""))
        print(f"  {'E[L]@κ':>16}  {el_a:>{w}}  {el_m:>{w}}" + (f"  {el_c:>{w}}" if len(headers) > 2 else ""))
        print(f"  {'c_p':>16}  {cp_a:>{w}}  {cp_m:>{w}}" + (f"  {cp_c:>{w}}" if len(headers) > 2 else ""))

        if rc is not None and rc.cvar_L is not None and bills_a:
            d_cvar = rc.cvar_L - bills_a["cvar_L"]
            d_el = rc.E_L - bills_a["expected_bill"]
            print(f"\n  M-C vs A: ΔCVaR(L)={d_cvar:+.2f}  ΔE[L]={d_el:+.2f}")

    return ma, rm, bills_a, rc


def _bills_to_result_stub(bills: dict) -> MonetarySolveResult:
    """把 recompute_monetary_bills 输出包装成可打印 breakdown 的 stub。"""
    return MonetarySolveResult(
        model=None,
        status=GRB.OPTIMAL,
        cvar_L=bills.get("cvar_L"),
        E_L=bills.get("expected_bill"),
        cost_p=bills.get("cost_p"),
        E_cost_b=sum(bills["cb_per_scenario"].values()) / max(len(bills["cb_per_scenario"]), 1),
        E_shortfall_vol=sum(bills["shortfall_per_scenario"].values()) / max(len(bills["shortfall_per_scenario"]), 1),
        y=None,
        xin=None,
        xout=None,
        del_in=None,
        del_out=None,
        L_per_scenario=bills.get("L_per_scenario"),
        cb_per_scenario=bills.get("cb_per_scenario"),
        shortfall_per_scenario=bills.get("shortfall_per_scenario"),
        placement=bills.get("placement"),
    )


def main():
    ap = argparse.ArgumentParser(description="Model M / M-C monetary CVaR")
    ap.add_argument("--toy", action="store_true", help="使用 UltraComplexData 玩具数据")
    ap.add_argument("--topology", type=str, default="B4", help="拓扑名：toy | B4 | Sprint | ...")
    ap.add_argument("--num-tasks", type=int, default=8)
    ap.add_argument("--k-paths", type=int, default=4)
    ap.add_argument("--kappa", type=float, default=5.0, help="kappa_sum")
    ap.add_argument("--kappa-max", type=float, default=0.0)
    ap.add_argument("--kappa-sf", type=float, default=0.0)
    ap.add_argument("--beta", type=float, default=None)
    ap.add_argument("--gamma", type=float, default=None, help="Model M-C Gamma_money")
    ap.add_argument("--bisect", action="store_true")
    ap.add_argument("--compare-a", action="store_true")
    ap.add_argument("--lambda-sla", type=float, default=5.0)
    ap.add_argument("--omega", type=float, default=1.0, help="Model A 送达奖励 ω")
    ap.add_argument("--min-off-hub", type=int, default=0,
                    help="至少 K 个任务不放在 hub（打破退化）")
    ap.add_argument("--stress-zero-s1", action="store_true",
                    help="场景 s=1 压 hub 出边（B4 默认开启）")
    ap.add_argument("--no-stress-zero-s1", action="store_true",
                    help="关闭 stress_zero_s1（覆盖 B4 默认）")
    ap.add_argument("--cvar-slack", type=float, default=1.05,
                    help="二分上界 = CVaR* × slack（默认 1.05）")
    ap.add_argument("--expand-bisect-hi", action="store_true",
                    help="二分上界取 max(slack×CVaR*, 成本最优解的统一κ CVaR)")
    ap.add_argument("--scenario", action="store_true", help="打印逐场景 L_s 分解")
    ap.add_argument("--mip-gap", type=float, default=0.01)
    args = ap.parse_args()

    stress = None
    if args.no_stress_zero_s1:
        stress = False
    elif args.stress_zero_s1:
        stress = True

    data, label = load_monetary_data(
        toy=args.toy,
        topology=args.topology,
        num_tasks=args.num_tasks,
        k_paths=args.k_paths,
        stress_zero_s1=stress,
    )
    print(f"数据: {label}")

    beta = args.beta if args.beta is not None else data.beta_N
    min_off = args.min_off_hub
    show_sc = args.scenario

    if args.compare_a:
        compare_with_model_a(
            data, kappa_sum=args.kappa, kappa_max=args.kappa_max, kappa_sf=args.kappa_sf,
            lambda_sla=args.lambda_sla, omega=args.omega, beta=beta, min_tasks_off_hub=min_off,
            show_scenarios=show_sc, mip_gap=args.mip_gap,
        )
        return

    if args.bisect:
        best, g = bisect_monetary_cvar_c(
            data,
            kappa_sum=args.kappa,
            kappa_max=args.kappa_max,
            kappa_sf=args.kappa_sf,
            beta=beta,
            min_tasks_off_hub=min_off,
            cvar_slack=args.cvar_slack,
            expand_hi=args.expand_bisect_hi,
            mip_gap=args.mip_gap,
        )
        if best:
            print_monetary_result(f"bisect G={g:.4f}", best)
            if show_sc:
                print_scenario_breakdown(f"bisect G={g:.4f}", best, data, kappa_sum=args.kappa)
        return

    if args.gamma is not None:
        r = build_monetary_cvar_model_c(
            data, args.gamma,
            kappa_sum=args.kappa, kappa_max=args.kappa_max, kappa_sf=args.kappa_sf,
            beta=beta, min_tasks_off_hub=min_off, mip_gap=args.mip_gap,
        )
        print_monetary_result("Model M-C", r)
    else:
        r = build_monetary_cvar_model(
            data,
            kappa_sum=args.kappa, kappa_max=args.kappa_max, kappa_sf=args.kappa_sf,
            beta=beta, min_tasks_off_hub=min_off, mip_gap=args.mip_gap,
        )
        print_monetary_result("Model M", r)

    if show_sc and r.status == GRB.OPTIMAL:
        print_scenario_breakdown("result", r, data, kappa_sum=args.kappa)


if __name__ == "__main__":
    main()
