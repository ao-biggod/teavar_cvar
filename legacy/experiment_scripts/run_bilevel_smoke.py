# -*- coding: utf-8 -*-
"""Smoke run: bilevel slow/fast TEAVAR on ComponentRisk toy."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bilevel_teavar_models import (
    compare_with_single_layer_a,
    solve_bilevel_model_a,
    solve_bilevel_model_c,
)
from toy_instances import CR_A, CR_B, CR_C, build_toy_combined_component_risk


def main() -> None:
    p = argparse.ArgumentParser(description="Bilevel TEAVAR smoke (ComponentRisk toy)")
    p.add_argument("--lambda-sla", type=float, default=1.0)
    p.add_argument("--lambda-sf", type=float, default=1.0)
    p.add_argument("--gamma-sla", type=float, default=0.05)
    p.add_argument("--gamma-sf", type=float, default=0.05)
    p.add_argument("--omega", type=float, default=1.0)
    p.add_argument(
        "--fast-objective",
        choices=("delivery", "lexicographic", "min_sla_cvar"),
        default="delivery",
    )
    p.add_argument("--compare-single", action="store_true")
    args = p.parse_args()

    data = build_toy_combined_component_risk()
    data.placement_node_labels = {"A": CR_A, "B": CR_B, "C": CR_C}

    print("=== Bilevel Model A ===")
    ba = solve_bilevel_model_a(
        data,
        lambda_sla=args.lambda_sla,
        lambda_sf=args.lambda_sf,
        omega_deliver=args.omega,
        fast_objective=args.fast_objective,
    )
    if ba.best:
        b = ba.best
        print(
            f"  placement={b.placement_code}  cost={b.total_cost:.4f}  "
            f"CVaR_sla={b.cvar_sla:.4f}  CVaR_sf={b.cvar_sf:.4f}  "
            f"E[Del]={b.expected_delivery:.2f}  obj={b.bilevel_a_objective:.4f}"
        )
    else:
        print("  INFEASIBLE")

    print("=== Bilevel Model C ===")
    bc = solve_bilevel_model_c(
        data,
        gamma_sla=args.gamma_sla,
        gamma_sf=args.gamma_sf,
        omega_deliver=args.omega,
        fast_objective=args.fast_objective,
    )
    if bc.best:
        b = bc.best
        print(
            f"  placement={b.placement_code}  cost={b.total_cost:.4f}  "
            f"CVaR_sla={b.cvar_sla:.4f}  CVaR_sf={b.cvar_sf:.4f}"
        )
    else:
        print(f"  INFEASIBLE (feasible placements={bc.feasible_count}/{bc.evaluated_count})")

    if args.compare_single:
        print("=== vs Single-layer Model A ===")
        rep = compare_with_single_layer_a(
            data,
            lambda_sla=args.lambda_sla,
            lambda_sf=args.lambda_sf,
            omega_deliver=args.omega,
            fast_objective=args.fast_objective,
        )
        if rep:
            print(f"  bilevel={rep.bilevel.placement_code}  single={rep.single_layer_placement_code}")
            print(f"  match={rep.placement_match}  cost_gap={rep.cost_gap}")


if __name__ == "__main__":
    main()
