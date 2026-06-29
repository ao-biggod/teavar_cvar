# -*- coding: utf-8 -*-
"""
L2-full 独立模块（与 P0 主链隔离）。

本轮范围（M0.5 / M1）：
* fixed-y F1 primal：min SLA CVaR routing LP
* F1 strong-duality gap 校验（primal Pi → 手写 dual objective）
* 与 L0 ``solve_fast_routing(..., fast_objective="min_sla_cvar")`` 数值对照

不实现 F2/F3 certificate、完整 L2-full、上层 MIP。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

import gurobipy as gp
from gurobipy import GRB

from bilevel_teavar_models import (
    _add_sla_cvar_ru,
    build_fast_routing_ctx,
    solve_fast_routing,
)
from cvar_compare import add_scenario_delivery_coupling
from duibi_metrics import teavar_flow_anchors

F1_DUAL_EPS_DEFAULT = 1e-6

ConstraintGroup = Literal[
    "cap_in",
    "cap_out",
    "del_in_eq",
    "del_in_zero",
    "del_out_eq",
    "del_out_zero",
    "vs_cap_in",
    "vt_cap_out",
    "ru_in",
    "ru_out",
    "other",
]


def _constraint_group(name: str) -> ConstraintGroup:
    for prefix in (
        "cap_in_",
        "cap_out_",
        "del_in_eq_",
        "del_in_zero_",
        "del_out_eq_",
        "del_out_zero_",
        "vs_cap_in_",
        "vt_cap_out_",
        "ru_in_",
        "ru_out_",
    ):
        if name.startswith(prefix):
            return prefix.rstrip("_")  # type: ignore[return-value]
    return "other"


@dataclass
class F1PrimalResult:
    status: str
    r_sla: float | None
    placement: dict[int, int]
    primal_objective: float | None = None


@dataclass
class F1DualGroupSummary:
    group: str
    count: int
    pi_sum: float
    rhs_pi_sum: float
    pi_min: float
    pi_max: float


@dataclass
class F1DualValidationResult:
    status: str
    placement: dict[int, int]
    primal_objective: float | None
    dual_objective: float | None
    gap: float | None
    gap_ok: bool
    eps: float
    group_summaries: list[F1DualGroupSummary] = field(default_factory=list)
    sign_checks: dict[str, str] = field(default_factory=dict)
    l0_r_sla: float | None = None
    l0_match: bool | None = None


def build_f1_primal_fixed_y(
    data,
    placement: dict[int, int],
    *,
    beta_sla: float | None = None,
    time_limit: float | None = None,
) -> tuple[gp.Model, gp.LinExpr, dict]:
    """
    Fixed-y F1 primal：min CVaR_SLA。

    结构与 L0 ``build_fast_routing_ctx`` + ``_add_sla_cvar_ru`` 一致；
    仅创建 placement 对应节点的 routing 变量（fixed-y 阶段，非 embedded-y）。
    """
    beta = float(beta_sla if beta_sla is not None else data.beta_N)
    ctx = build_fast_routing_ctx(data, placement, time_limit=time_limit)
    sla_cvar = _add_sla_cvar_ru(
        ctx.m, data, ctx.del_in, ctx.del_out, ctx.in_u, ctx.out_v, beta
    )
    ctx.m.setObjective(sla_cvar, GRB.MINIMIZE)
    meta = {
        "sla_cvar_expr": sla_cvar,
        "beta_sla": beta,
        "ctx": ctx,
    }
    return ctx.m, sla_cvar, meta


def solve_f1_fixed_y(
    data,
    placement: dict[int, int],
    *,
    beta_sla: float | None = None,
    time_limit: float | None = None,
) -> F1PrimalResult:
    """求解 fixed-y F1，返回 SLA CVaR 最优值。"""
    m, sla_cvar, _ = build_f1_primal_fixed_y(
        data, placement, beta_sla=beta_sla, time_limit=time_limit
    )
    m.optimize()
    if m.status != GRB.OPTIMAL or m.SolCount == 0:
        return F1PrimalResult(
            status=str(m.status),
            r_sla=None,
            placement=dict(placement),
            primal_objective=None,
        )
    obj = float(m.ObjVal)
    r_sla = float(sla_cvar.getValue())
    return F1PrimalResult(
        status="OPTIMAL",
        r_sla=r_sla,
        placement=dict(placement),
        primal_objective=obj,
    )


def _handwritten_dual_objective(m: gp.Model) -> tuple[float, list[F1DualGroupSummary]]:
    """
    手写 dual objective（Gurobi min LP 约定）：

        dual_obj = sum_i RHS_i * Pi_i

    对 minimization，强对偶成立时 dual_obj == primal_obj。
    """
    buckets: dict[str, list[tuple[float, float]]] = {}
    for c in m.getConstrs():
        grp = _constraint_group(c.ConstrName)
        buckets.setdefault(grp, []).append((float(c.RHS), float(c.Pi)))

    summaries: list[F1DualGroupSummary] = []
    dual_obj = 0.0
    for grp in sorted(buckets):
        pairs = buckets[grp]
        pi_vals = [pi for _, pi in pairs]
        rhs_pi = sum(rhs * pi for rhs, pi in pairs)
        dual_obj += rhs_pi
        summaries.append(
            F1DualGroupSummary(
                group=grp,
                count=len(pairs),
                pi_sum=sum(pi_vals),
                rhs_pi_sum=rhs_pi,
                pi_min=min(pi_vals),
                pi_max=max(pi_vals),
            )
        )
    return dual_obj, summaries


def _dual_sign_checks(m: gp.Model) -> dict[str, str]:
    """
    关键对偶乘子符号检查（Gurobi min LP + Pi 约定）：

    * ``<=`` 约束（cap_in/cap_out）：Pi <= 0
    * ``>=`` 约束（ru_in/ru_out）：Pi >= 0
    """
    checks: dict[str, str] = {}

    def _check_group(prefix: str, expected: str) -> None:
        pis = [float(c.Pi) for c in m.getConstrs() if c.ConstrName.startswith(prefix)]
        if not pis:
            checks[prefix] = "missing"
            return
        if expected == "nonneg":
            ok = all(p >= -1e-8 for p in pis)
        elif expected == "nonpos":
            ok = all(p <= 1e-8 for p in pis)
        else:
            ok = True
        checks[prefix] = "ok" if ok else "fail"

    _check_group("cap_in_", "nonpos")
    _check_group("cap_out_", "nonpos")
    _check_group("ru_in_", "nonneg")
    _check_group("ru_out_", "nonneg")
    return checks


def validate_f1_strong_duality(
    data,
    placement: dict[int, int],
    *,
    beta_sla: float | None = None,
    eps: float = F1_DUAL_EPS_DEFAULT,
    time_limit: float | None = None,
    compare_l0: bool = True,
) -> F1DualValidationResult:
    """
    M0.5：fixed-y F1 primal / dual validation。

    1. 构建并求解 F1 LP
    2. 按约束类提取 Pi
    3. 手写 dual objective = sum(RHS * Pi)
    4. 报告 gap；gap > eps 时 gap_ok=False
    5. 可选与 L0 min_sla_cvar baseline 对照
    """
    m, sla_cvar, _ = build_f1_primal_fixed_y(
        data, placement, beta_sla=beta_sla, time_limit=time_limit
    )
    m.setParam("OutputFlag", 0)
    m.setParam("DualReductions", 0)
    m.optimize()

    if m.status != GRB.OPTIMAL or m.SolCount == 0:
        return F1DualValidationResult(
            status=str(m.status),
            placement=dict(placement),
            primal_objective=None,
            dual_objective=None,
            gap=None,
            gap_ok=False,
            eps=eps,
        )

    primal_obj = float(m.ObjVal)
    dual_obj, group_summaries = _handwritten_dual_objective(m)
    gap = abs(primal_obj - dual_obj)
    sign_checks = _dual_sign_checks(m)

    l0_r_sla = None
    l0_match = None
    if compare_l0:
        l0 = solve_fast_routing(
            data, placement, fast_objective="min_sla_cvar", beta_sla=beta_sla
        )
        if l0 is not None and l0.model_sla_cvar is not None:
            l0_r_sla = float(l0.model_sla_cvar)
            l0_match = abs(l0_r_sla - primal_obj) <= eps

    return F1DualValidationResult(
        status="OPTIMAL",
        placement=dict(placement),
        primal_objective=primal_obj,
        dual_objective=dual_obj,
        gap=gap,
        gap_ok=gap <= eps,
        eps=eps,
        group_summaries=group_summaries,
        sign_checks=sign_checks,
        l0_r_sla=l0_r_sla,
        l0_match=l0_match,
    )


def embedded_y_big_m_caps(data, i: int, mnode: int) -> tuple[float, float]:
    """
    L2 embedded-y 阶段 x 上界（文档 §1.3）；M1 不启用，供 M2 参考。

    M_in[i,m,p] <= b_in[i]
    M_out[i,m,q] <= b_out[i]
    """
    return float(data.b_in[i]), float(data.b_out[i])


def build_f1_embedded_y_skeleton(
    data,
    y: dict[tuple[int, int], gp.Var],
    *,
    beta_sla: float | None = None,
) -> tuple[gp.Model, gp.LinExpr]:
    """
    M2 用骨架：为全部合法 (i,m,p) 创建 xin/xout，并用 Big-M 与 y 耦合。

    本轮不调用求解；仅固化变量空间约定，供 L2-light 实现复用。
    """
    beta = float(beta_sla if beta_sla is not None else data.beta_N)
    h = int(getattr(data, "hub", 0))
    per_task = str(getattr(data, "routing_mode", "hub")) in ("per_task_od", "umcf_per_task")
    if per_task:
        in_u, out_v = teavar_flow_anchors(data, data.I[0])
    else:
        in_u, out_v = teavar_flow_anchors(data)

    m = gp.Model("L2_F1_EmbeddedY_Skeleton")
    m.setParam("OutputFlag", 0)

    xin: dict = {}
    xout: dict = {}
    for i in data.I:
        iu, ov = (
            teavar_flow_anchors(data, i) if per_task else (in_u, out_v)
        )
        for mnode in data.M:
            if (i, mnode) not in data.valid_assign or not data.valid_assign[(i, mnode)]:
                continue
            min_cap, mout_cap = embedded_y_big_m_caps(data, i, mnode)
            yim = y[i, mnode]
            for p in range(len(data.P_cand[iu, mnode])):
                xin[i, mnode, p] = m.addVar(lb=0.0, name=f"xin_{i}_{mnode}_{p}")
                m.addConstr(xin[i, mnode, p] <= min_cap * yim, name=f"xin_ub_{i}_{mnode}_{p}")
            for q in range(len(data.P_cand[mnode, ov])):
                xout[i, mnode, q] = m.addVar(lb=0.0, name=f"xout_{i}_{mnode}_{q}")
                m.addConstr(xout[i, mnode, q] <= mout_cap * yim, name=f"xout_ub_{i}_{mnode}_{q}")

    del_in: dict = {}
    del_out: dict = {}
    for s in data.S:
        for i in data.I:
            iu, ov = (
                teavar_flow_anchors(data, i) if per_task else (in_u, out_v)
            )
            for mnode in data.M:
                if (i, mnode) not in xin and (i, mnode) not in xout:
                    continue
                for p in range(len(data.P_cand[iu, mnode])):
                    if (i, mnode, p) in xin:
                        del_in[i, mnode, p, s] = m.addVar(lb=0.0, name=f"din_{i}_{mnode}_{p}_{s}")
                for q in range(len(data.P_cand[mnode, ov])):
                    if (i, mnode, q) in xout:
                        del_out[i, mnode, q, s] = m.addVar(lb=0.0, name=f"dout_{i}_{mnode}_{q}_{s}")

    add_scenario_delivery_coupling(m, data, y, xin, xout, del_in, del_out, in_u, out_v)

    sla_cvar = _add_sla_cvar_ru(m, data, del_in, del_out, in_u, out_v, beta)
    m.setObjective(sla_cvar, GRB.MINIMIZE)
    return m, sla_cvar
