#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Probe omega under Model A (lambda_sla) and Model C (Gamma) settings."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from toy_instances import build_toy_combined_component_risk, format_component_risk_placement
from teavar_framework_models import build_teavar_model_a, build_teavar_model_c


def exp_del(data, din, dout) -> float:
    return sum(data.prob[k[-1]] * v.X for k, v in din.items()) + sum(
        data.prob[k[-1]] * v.X for k, v in dout.items()
    )


def run_a(data, ls, lf, omega):
    m, c, lv, sfv, y, xi, xo, din, dout = build_teavar_model_a(
        data,
        lambda_sla=ls,
        lambda_sf=lf,
        omega_deliver=omega,
        beta_loss=data.beta_N,
        beta_sf=data.beta_N,
        time_limit=60,
    )
    p = {i: n for i in data.I for n in data.M if (i, n) in y and y[i, n].X > 0.5}
    xs = sum(v.X for v in xi.values()) + sum(v.X for v in xo.values())
    ed = exp_del(data, din, dout)
    return format_component_risk_placement(p), c, lv, sfv, xs, ed, m.ObjVal


def run_c(data, gs, gf, omega):
    m, c, lv, sfv, y, xi, xo, din, dout = build_teavar_model_c(
        data,
        gamma_sla=gs,
        gamma_sf=gf,
        omega_deliver=omega,
        beta_loss=data.beta_N,
        beta_sf=data.beta_N,
        include_sf_budget=True,
        time_limit=60,
    )
    if c is None:
        return "INFEAS", None, None, None, 0, 0, None
    p = {i: n for i in data.I for n in data.M if (i, n) in y and y[i, n].X > 0.5}
    xs = sum(v.X for v in xi.values()) + sum(v.X for v in xo.values())
    ed = exp_del(data, din, dout)
    return format_component_risk_placement(p), c, lv, sfv, xs, ed, m.ObjVal


def model_a_lambda_sweep():
    d = build_toy_combined_component_risk()
    d.bandwidth_cost_on_placement = False
    print("=" * 78)
    print("Model A：带宽绑 x，lambda_sf=0，对比 omega=0 vs omega=1")
    print("=" * 78)
    print(f"{'lam_sla':>8} | {'w=0':^26} | {'w=1':^26} | same")
    print("-" * 78)
    for ls in [0, 0.001, 0.005, 0.01, 0.05, 0.1, 0.5, 1, 2, 5, 10, 20, 50]:
        r0 = run_a(d, ls, 0, 0)
        r1 = run_a(d, ls, 0, 1)
        same = (
            "Y"
            if r0[0] == r1[0] and abs(r0[4] - r1[4]) < 0.01 and abs(r0[5] - r1[5]) < 0.01
            else "N"
        )
        print(
            f"{ls:8.3f} | {r0[0]:^4} x={r0[4]:4.1f} E={r0[5]:5.2f} c={r0[1]:5.3f} | "
            f"{r1[0]:^4} x={r1[4]:4.1f} E={r1[5]:5.2f} c={r1[1]:5.3f} | {same}"
        )


def model_c_gamma_sweep():
    d = build_toy_combined_component_risk()
    print()
    print("=" * 78)
    print("Model C：默认带宽绑 y，对比 omega=0 vs omega=1 vs omega=10")
    print("=" * 78)
    cases = [
        (0.08, 1.0, "SLA宽 SF极宽"),
        (1.0, 1.0, "双宽"),
        (1.0, 0.08, "SLA宽 SF紧"),
        (0.1, 0.5, "中间 ACC区"),
        (0.5, 0.5, "中间宽"),
        (0.08, 0.08, "双紧 CCC"),
    ]
    print(f"{'Gamma':^14} | {'w=0':^24} | {'w=1':^24} | {'w=10':^24}")
    print("-" * 78)
    for gs, gf, tag in cases:
        rows = [run_c(d, gs, gf, w) for w in (0, 1, 10)]
        parts = []
        for r in rows:
            if r[0] == "INFEAS":
                parts.append("INFEAS".center(24))
            else:
                parts.append(f"{r[0]:^4} x={r[4]:4.1f} E={r[5]:5.2f}".center(24))
        print(f"({gs},{gf}) {tag:8} | {parts[0]} | {parts[1]} | {parts[2]}")


def model_c_wide_with_x_bw():
    d = build_toy_combined_component_risk()
    d.bandwidth_cost_on_placement = False
    print()
    print("=" * 78)
    print("Model C + 带宽绑 x：宽 Gamma 下 omega 能否逼送流？")
    print("=" * 78)
    for gs, gf in [(1.0, 1.0), (0.5, 0.5), (0.2, 0.2), (0.08, 1.0)]:
        r0 = run_c(d, gs, gf, 0)
        r1 = run_c(d, gs, gf, 10)
        print(
            f"G=({gs},{gf}): w=0  {r0[0]:^4} cost={r0[1]:.3f} x={r0[4]:.1f} E={r0[5]:.2f} "
            f"sla={r0[2]:.3f} sf={r0[3]:.3f} | "
            f"w=10 {r1[0]:^4} cost={r1[1]:.3f} x={r1[4]:.1f} E={r1[5]:.2f}"
        )


def model_c_tie_break_scan():
    """Among feasible placements at wide Gamma, check if cost/risk tie but E[Del] differs."""
    from exact_enumeration_solver import evaluate_solution, RouteChoice, enumerate_placements

    d = build_toy_combined_component_risk()
    routes = RouteChoice(in_path={i: 0 for i in d.I}, out_path={i: 0 for i in d.I})
    gs, gf = 1.0, 1.0
    print()
    print("=" * 78)
    print(f"Model C 宽预算 G=({gs},{gf})：枚举可行 placement 的 cost / CVaR / E[Del]")
    print("=" * 78)
    feasible = []
    for pl in enumerate_placements(d):
        ev = evaluate_solution(d, pl, routes, gamma_sla=gs, gamma_sf=gf)
        if ev.model_c_feasible:
            code = format_component_risk_placement(pl)
            exp_d = 0.0
            for s in d.S:
                # approximate from full-flow assumption in exact enum
                pass
            feasible.append((code, ev.cost, ev.cvar_sla, ev.cvar_sf, ev.expected_delivery))
    feasible.sort(key=lambda t: (t[1], t[2], t[3]))
    print(f"{'plac':^6} | {'cost':>6} | {'sla':>6} | {'sf':>6} | {'E[Del]':>7}")
    for row in feasible[:12]:
        print(f"{row[0]:^6} | {row[1]:6.3f} | {row[2]:6.4f} | {row[3]:6.4f} | {row[4]:7.3f}")
    print(f"... 共 {len(feasible)} 个可行 placement")


if __name__ == "__main__":
    model_a_lambda_sweep()
    model_c_gamma_sweep()
    model_c_wide_with_x_bw()
    model_c_tie_break_scan()
