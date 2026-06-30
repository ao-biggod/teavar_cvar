# -*- coding: utf-8 -*-
"""Single-configuration E2E mainline runner.

Usage::

    PYTHONPATH=src python -m teavar_e2e.experiments.run_e2e_mainline \\
        --beta 0.95 --gamma 0.5 --rho 0.9 --max-failed-components 2
"""
from __future__ import annotations

import argparse
import sys, os

_self_dir = os.path.dirname(os.path.abspath(__file__))
_src = os.path.abspath(os.path.join(_self_dir, "..", ".."))
if _src not in sys.path:
    sys.path.insert(0, _src)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="TEAVAR-E2E mainline single-config runner")
    ap.add_argument("--beta", type=float, default=0.95, help="CVaR confidence level")
    ap.add_argument("--gamma", type=float, default=0.5, help="CVaR budget upper bound")
    ap.add_argument("--rho", type=float, default=0.9, help="Expected service floor (0=off)")
    ap.add_argument("--loss-mode", default="avg", choices=["avg", "fair"], help="Loss aggregation mode")
    ap.add_argument("--max-failed-components", type=int, default=2)
    ap.add_argument("--aggregate-worst-case", action="store_true")
    ap.add_argument("--time-limit", type=float, default=60)
    ap.add_argument("--mip-gap", type=float, default=0.01)
    ap.add_argument("--output-dir", default="new_results/e2e_mainline")
    args = ap.parse_args(argv)

    from teavar_e2e.experiments.common import (
        build_toy2task_data,
        solve_m2_c_cost_once,
        write_csv_row,
        output_path,
    )

    # ── build data ──
    print("Loading Toy-2Task-Independent data ...")
    data = build_toy2task_data(max_failed_components=args.max_failed_components)
    data.beta_cvar = float(args.beta)

    num_scenarios = len(data.S)
    dropped = data.scenario_metadata.get("dropped_probability_mass", 0.0)
    print(f"  |J|={len(data.J)}  |M|={len(data.M)}  |S|={num_scenarios}  dropped_mass={dropped:.6f}")

    rho_min = float(args.rho) if args.rho > 0 else None

    # ── solve ──
    print(f"\nSolving M2-C-Cost (beta={args.beta}, gamma={args.gamma}, rho={args.rho}) ...")
    _result, metrics = solve_m2_c_cost_once(
        data,
        gamma=args.gamma,
        beta_cvar=args.beta,
        rho_min_service=rho_min,
        time_limit=args.time_limit,
        mip_gap=args.mip_gap,
    )

    # ── assemble row ──
    row = {
        "dataset": "Toy-2Task-Independent-v1",
        "beta": args.beta,
        "gamma": args.gamma,
        "rho": args.rho,
        "loss_mode": args.loss_mode,
        "max_failed_components": args.max_failed_components,
        "aggregate_worst_case": str(args.aggregate_worst_case).lower(),
        "num_scenarios": num_scenarios,
        "dropped_probability_mass": f"{dropped:.6g}",
    }
    row.update(metrics)

    path = output_path("mainline_summary", args.output_dir)
    write_csv_row(path, row)

    # ── print summary ──
    print(f"\n{'='*60}")
    print(f"  status       = {row['status']}")
    print(f"  objective    = {row['objective']}")
    print(f"  total_cost   = {row['total_cost']}")
    print(f"  cvar_e2e     = {row['cvar_e2e']}")
    print(f"  exp_service  = {row['expected_service']}")
    print(f"  runtime_sec  = {row['runtime_sec']}")
    print(f"  output       = {path}")
    print(f"{'='*60}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
