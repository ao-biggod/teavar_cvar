#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from toy_instances import build_toy_combined_component_risk, format_component_risk_placement
from exact_enumeration_solver import evaluate_solution, RouteChoice, solve_exact_model_a
from teavar_framework_models import build_teavar_model_a, build_teavar_model_c

LAB = {"A": 6, "B": 7, "C": 8}


def main():
    routes = RouteChoice(in_path={i: 0 for i in range(3)}, out_path={i: 0 for i in range(3)})

    print("=== Pure placements: SLA/SF CVaR vs beta ===")
    header = f"{'code':^6} | {'b=0.80':^14} | {'b=0.95':^14} | {'b=0.99':^14}"
    print(header)
    print("-" * len(header))
    for code in ["AAA", "BBB", "CCC", "ACC"]:
        parts = [f"{code:^6}"]
        for b in (0.8, 0.95, 0.99):
            data = build_toy_combined_component_risk()
            data.beta_N = b
            p = {i: LAB[c] for i, c in enumerate(code)}
            ev = evaluate_solution(data, p, routes)
            parts.append(f"{ev.cvar_sla:.3f}/{ev.cvar_sf:.3f}".center(14))
        print(" | ".join(parts))

    print("\n=== Model A optimal vs beta (lam_sla=1, lam_sf=10, omega=0) ===")
    for b in (0.8, 0.9, 0.95, 0.99):
        data = build_toy_combined_component_risk()
        data.beta_N = b
        r = solve_exact_model_a(
            data, lambda_sla=1, lambda_sf=10, beta_sla=b, beta_sf=b, omega_deliver=0
        )
        bst = r.best
        print(
            f"b={b:.2f}: {format_component_risk_placement(bst.placement)} "
            f"cost={bst.cost:.3f} sla={bst.cvar_sla:.4f} sf={bst.cvar_sf:.4f}"
        )

    print("\n=== Model C G=(1.0,0.08): placement vs beta, omega=0/10 ===")
    for b in (0.8, 0.95, 0.99):
        for w in (0, 10):
            data = build_toy_combined_component_risk()
            data.beta_N = b
            m, c, lv, sfv, y, xi, xo, din, dout = build_teavar_model_c(
                data,
                gamma_sla=1.0,
                gamma_sf=0.08,
                omega_deliver=w,
                beta_loss=b,
                beta_sf=b,
                include_sf_budget=True,
            )
            p = {i: n for i in data.I for n in data.M if y[i, n].X > 0.5}
            print(
                f"  b={b:.2f} w={w:2d}: {format_component_risk_placement(p)} "
                f"cost={c:.3f} sla={lv:.3f} sf={sfv:.3f}"
            )

    print("\n=== Zero-flow threshold: lam=0.13, omega=0, bw on x, vs beta ===")
    for b in (0.8, 0.95, 0.99):
        data = build_toy_combined_component_risk()
        data.bandwidth_cost_on_placement = False
        data.beta_N = b
        m, c, lv, sfv, y, xi, xo, din, dout = build_teavar_model_a(
            data, lambda_sla=0.13, lambda_sf=0, omega_deliver=0, beta_loss=b, beta_sf=b
        )
        xs = sum(v.X for v in xi.values()) + sum(v.X for v in xo.values())
        print(f"  b={b:.2f}: x_sum={xs:.1f} (full flow if 6.0)")


if __name__ == "__main__":
    main()
