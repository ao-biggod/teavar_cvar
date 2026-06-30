#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from toy_instances import build_toy_combined_component_risk, format_component_risk_placement
from exact_enumeration_solver import (
    compute_cvar,
    evaluate_solution,
    RouteChoice,
    enumerate_placements,
    solve_exact_model_a,
    _scenario_delivery,
    _sla_loss_per_scenario,
    _sf_loss_per_scenario,
    _sf_d_ref_by_resource,
)

LAB = {"A": 6, "B": 7, "C": 8}


def rank_placements(beta, ls=1, lf=10):
    data = build_toy_combined_component_risk()
    data.beta_N = beta
    routes = RouteChoice(in_path={i: 0 for i in range(3)}, out_path={i: 0 for i in range(3)})
    rows = []
    for pl in enumerate_placements(data):
        ev = evaluate_solution(
            data, pl, routes,
            lambda_sla=ls, lambda_sf=lf, beta_sla=beta, beta_sf=beta,
        )
        rows.append((
            ev.model_a_objective,
            format_component_risk_placement(pl),
            ev.cost,
            ev.cvar_sla,
            ev.cvar_sf,
        ))
    rows.sort()
    print(f"=== beta={beta}, lambda=(1,10): top 10 placements ===")
    print(f"{'obj':>7} | {'plac':^4} | {'cost':>5} | {'sla':>6} | {'sf':>6}")
    for row in rows[:10]:
        print(f"{row[0]:7.3f} | {row[1]:^4} | {row[2]:5.3f} | {row[3]:6.4f} | {row[4]:6.4f}")
    best = solve_exact_model_a(data, ls, lf, beta_sla=beta, beta_sf=beta).best
    print(f"exact best: {format_component_risk_placement(best.placement)}  obj={best.model_a_objective:.3f}\n")


def tail_analysis(code):
    data = build_toy_combined_component_risk()
    routes = RouteChoice(in_path={i: 0 for i in range(3)}, out_path={i: 0 for i in range(3)})
    p = {i: LAB[c] for i, c in enumerate(code)}
    dref = _sf_d_ref_by_resource(data)
    sla, sf = {}, {}
    for s in data.S:
        rin, rout = _scenario_delivery(data, p, routes, s)
        sla[s] = _sla_loss_per_scenario(data, rin, rout)
        sf[s] = _sf_loss_per_scenario(data, p, s, dref)

    # scenarios with any loss
    bad = [s for s in data.S if sla[s] > 0 or sf[s] > 0]
    bad.sort(key=lambda s: sf[s] + sla[s], reverse=True)
    print(f"--- {code}: {len(bad)} scenarios with loss>0 (of 512) ---")
    print("worst 6 by max(sla,sf):")
    for s in bad[:6]:
        print(f"  s={s:3d}  L_sla={sla[s]:.3f}  L_sf={sf[s]:.3f}  p={data.prob[s]:.7f}")

    for b in (0.8, 0.99):
        csla = compute_cvar(sla, data.prob, b)
        csf = compute_cvar(sf, data.prob, b)
        cost = evaluate_solution(data, p, routes).cost
        obj = cost + 1.0 * csla + 10.0 * csf
        print(f"  beta={b}: cost={cost:.3f}  CVaR_sla={csla:.4f}  CVaR_sf={csf:.4f}  obj={obj:.3f}")
    print()


if __name__ == "__main__":
    rank_placements(0.8)
    rank_placements(0.99)
    for c in ("CCC", "ABC", "BBC", "ACC"):
        tail_analysis(c)
