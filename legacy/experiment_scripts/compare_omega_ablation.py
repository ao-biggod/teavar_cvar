#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
对比目标函数中 -omega * E[Del] 项有无时的行为差异。

典型现象（omega=0 且带宽费绑在计划流量 x 上时）：
  优化器可将 x=0、d=0，省带宽费，但 placement 不变、SLA CVaR 在 lambda>0 时恶化。

用法：
  python scripts/compare_omega_ablation.py
"""
from __future__ import annotations

import copy
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from toy_instances import build_toy_combined_component_risk, build_toy_sla, format_component_risk_placement


@dataclass
class OmegaRun:
    label: str
    omega: float
    placement: str
    cost: float
    cvar_sla: float
    cvar_sf: float
    x_total: float
    exp_deliver: float
    objective: float


def _placement_str(data, y) -> str:
    p = {i: n for i in data.I for n in data.M if (i, n) in y and y[i, n].X > 0.5}
    if len(data.I) == 3:
        return format_component_risk_placement(p)
    from toy_instances import node_label_sla

    return node_label_sla(next(iter(p.values())))


def _exp_deliver(data, del_in, del_out) -> float:
    total = 0.0
    for key, var in del_in.items():
        total += float(data.prob[key[-1]]) * float(var.X)
    for key, var in del_out.items():
        total += float(data.prob[key[-1]]) * float(var.X)
    return total


def run_model_a(data, *, omega: float, lambda_sla: float, lambda_sf: float) -> OmegaRun:
    from teavar_framework_models import build_teavar_model_a

    m, cost, lv, sfv, y, xi, xo, din, dout = build_teavar_model_a(
        data,
        lambda_sla=lambda_sla,
        lambda_sf=lambda_sf,
        omega_deliver=omega,
        beta_loss=data.beta_N,
        beta_sf=data.beta_N,
    )
    x_total = sum(v.X for v in xi.values()) + sum(v.X for v in xo.values())
    return OmegaRun(
        label="",
        omega=omega,
        placement=_placement_str(data, y),
        cost=float(cost or 0.0),
        cvar_sla=float(lv or 0.0),
        cvar_sf=float(sfv or 0.0),
        x_total=float(x_total),
        exp_deliver=_exp_deliver(data, din, dout),
        objective=float(m.ObjVal),
    )


def _print_table(title: str, rows: list[OmegaRun]) -> None:
    print(f"\n{'=' * 72}")
    print(title)
    print(f"{'=' * 72}")
    print(
        f"{'omega':>6} | {'placement':^8} | {'cost':>6} | {'CVaR_SLA':>8} | "
        f"{'x_sum':>6} | {'E[Del]':>7} | {'objective':>10}"
    )
    print("-" * 72)
    for r in rows:
        print(
            f"{r.omega:6.2f} | {r.placement:^8} | {r.cost:6.4f} | {r.cvar_sla:8.4f} | "
            f"{r.x_total:6.2f} | {r.exp_deliver:7.3f} | {r.objective:10.4f}"
        )


def experiment_a_zero_flow_on_x() -> None:
    """带宽费绑在 x 上 + lambda=0：omega=0 时出现零流退化。"""
    data = build_toy_combined_component_risk()
    data.bandwidth_cost_on_placement = False
    rows = [
        run_model_a(data, omega=w, lambda_sla=0.0, lambda_sf=0.0)
        for w in (0.0, 0.5, 1.0, 5.0)
    ]
    _print_table(
        "实验 A：ComponentRisk，带宽费绑在计划流量 x 上，lambda=(0,0)\n"
        "  预期：omega=0 → x=0、E[Del]=0、成本接近 0；omega>0 → 恢复送流",
        rows,
    )


def experiment_b_lambda_sla_with_x() -> None:
    """同样 x 计费，但 lambda_sla>0：omega=0 时 SLA CVaR 仍高（无送达）。"""
    data = build_toy_combined_component_risk()
    data.bandwidth_cost_on_placement = False
    rows = [
        run_model_a(data, omega=w, lambda_sla=1.0, lambda_sf=0.0)
        for w in (0.0, 1.0, 5.0)
    ]
    _print_table(
        "实验 B：ComponentRisk，带宽费绑 x，lambda_sla=1\n"
        "  预期：omega=0 时即使惩罚 SLA，仍可能 x=0；omega>0 强制送流、CVaR_SLA 下降",
        rows,
    )


def experiment_c_placement_bw_zero_flow() -> None:
    """带宽费绑在 y 上（当前 toy 默认）：成本不变，但 omega=0 仍可不送流。"""
    data = build_toy_combined_component_risk()
    rows = [
        run_model_a(data, omega=w, lambda_sla=0.0, lambda_sf=0.0)
        for w in (0.0, 0.5, 1.0)
    ]
    _print_table(
        "实验 C：ComponentRisk，带宽费绑 placement y（默认），lambda=(0,0)\n"
        "  预期：成本相同，但 omega=0 → x=0/E[Del]=0；omega>0 → 正常送流",
        rows,
    )


def experiment_d_toy_sla() -> None:
    """单任务 Toy-SLA + 非零链路价：经典零流 vs 满流对比。"""
    data = build_toy_sla()
    for e in data.E:
        data.link_price[e] = 0.05
    rows = [
        run_model_a(data, omega=w, lambda_sla=0.0, lambda_sf=0.0)
        for w in (0.0, 1.0, 10.0)
    ]
    _print_table(
        "实验 D：Toy-SLA（1 任务），link_price=0.05，lambda=0\n"
        "  预期：omega=0 → 选免费节点 A、零流；omega>0 → 选可靠节点 C、满流送达",
        rows,
    )


def main() -> None:
    experiment_a_zero_flow_on_x()
    experiment_b_lambda_sla_with_x()
    experiment_c_placement_bw_zero_flow()
    experiment_d_toy_sla()
    print("\n说明：E[Del] 为期望送达量（ingress+egress 概率加权）；x_sum 为计划流量总和。")
    print("omega=0 时若 x=0 且 E[Del]=0，即为「有 placement 无送达」的退化解。\n")


if __name__ == "__main__":
    main()
