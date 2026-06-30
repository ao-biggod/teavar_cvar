# -*- coding: utf-8 -*-
"""Minimal M2-C-Cost smoke runner on Toy-2Task-Independent data.

Usage::

    PYTHONPATH=src python -m teavar_e2e.experiments.run_m2_toy \\
        --beta 0.95 --gamma 0.2 --max-failed-components 2

If Gurobi is unavailable the script exits with a message (no crash).
"""
from __future__ import annotations

import argparse
import sys, os


def _try_import_gurobi() -> bool:
    try:
        import gurobipy  # noqa: F401
        return True
    except ImportError:
        return False


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="M2-C-Cost toy smoke runner")
    ap.add_argument("--beta", type=float, default=0.95, help="CVaR confidence level")
    ap.add_argument("--gamma", type=float, default=0.2, help="CVaR budget upper bound")
    ap.add_argument(
        "--max-failed-components", type=int, default=2,
        help="max simultaneously failed independent components (pruned mode)",
    )
    ap.add_argument("--time-limit", type=float, default=60, help="Gurobi time limit (s)")
    ap.add_argument("--mip-gap", type=float, default=0.05)
    args = ap.parse_args(argv)

    if not _try_import_gurobi():
        print("Gurobi not available — skipping M2-C-Cost solve.")
        return 0

    # Ensure src/ is on sys.path for package imports
    _src = os.path.join(os.path.dirname(__file__), "..", "..")
    _src = os.path.abspath(_src)
    if _src not in sys.path:
        sys.path.insert(0, _src)

    from teavar_e2e.data.toy_two_task_independent_data import (
        build_toy_2task_independent_v1,
    )
    from teavar_e2e.models.m2_cost_models import solve_m2_c_cost

    print("Building Toy-2Task-Independent data ...")
    data = build_toy_2task_independent_v1(
        scenario_mode="pruned",
        max_failed_components=args.max_failed_components,
        renormalize_probabilities=True,
    )
    print(f"  |I|={len(data.J)}  |M|={len(data.M)}  |S|={len(data.S)}  |K|={len(data.K)}")
    print(f"  dropped_probability_mass={data.scenario_metadata.get('dropped_probability_mass', 0):.6f}")

    print(f"\nSolving M2-C-Cost (beta={args.beta}, gamma={args.gamma}) ...")
    result = solve_m2_c_cost(
        data,
        gamma=args.gamma,
        beta_sf=args.beta,  # same beta for SLA
        time_limit=args.time_limit,
        mip_gap=args.mip_gap,
    )

    print(f"\n{'='*60}")
    print(f"  status               = {result.status}")
    print(f"  objective            = {result.objective:.4f}")
    print(f"  placement_cost       = {result.cost_placement:.4f}")
    print(f"  bandwidth_cost (E)   = {result.cost_bandwidth_expected:.4f}")
    print(f"  CVaR_E2E             = {result.cvar_value:.6f}")
    print(f"  VaR (eta)            = {result.eta:.6f}")
    print(f"  expected_service     = {result.expected_service:.6f}")
    print(f"  placement            = {result.placement}")
    print(f"  pass_label           = {result.pass_label}")
    print(f"{'='*60}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
