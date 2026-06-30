# -*- coding: utf-8 -*-
"""M2-C-Cost gamma-frontier scanner.

Usage::

    PYTHONPATH=src python -m teavar_e2e.experiments.run_m2_gamma_frontier \\
        --beta 0.95 --gamma-list 0.2,0.4,0.6,0.8,1.0 --max-failed-components 2
"""
from __future__ import annotations

import argparse
import sys, os

_self_dir = os.path.dirname(os.path.abspath(__file__))
_src = os.path.abspath(os.path.join(_self_dir, "..", ".."))
if _src not in sys.path:
    sys.path.insert(0, _src)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="M2-C-Cost gamma frontier scanner")
    ap.add_argument("--beta", type=float, default=0.95, help="CVaR confidence level")
    ap.add_argument("--gamma-list", default="0.1,0.2,0.4,0.6,0.8,1.0",
                    help="Comma-separated gamma values to scan")
    ap.add_argument("--rho", type=float, default=0.9, help="Expected service floor (0=off)")
    ap.add_argument("--loss-mode", default="avg", choices=["avg", "fair"])
    ap.add_argument("--max-failed-components", type=int, default=2)
    ap.add_argument("--aggregate-worst-case", action="store_true")
    ap.add_argument("--time-limit", type=float, default=60)
    ap.add_argument("--mip-gap", type=float, default=0.01)
    ap.add_argument("--output-dir", default="new_results/e2e_mainline")
    args = ap.parse_args(argv)

    from teavar_e2e.experiments.common import (
        parse_gamma_list,
        build_toy2task_data,
        solve_m2_c_cost_once,
        write_csv_row,
        output_path,
    )

    gammas = parse_gamma_list(args.gamma_list)
    rho_min = float(args.rho) if args.rho > 0 else None

    # ── build data once ──
    print("Loading Toy-2Task-Independent data ...")
    data = build_toy2task_data(max_failed_components=args.max_failed_components)
    data.beta_cvar = float(args.beta)

    num_scenarios = len(data.S)
    dropped = data.scenario_metadata.get("dropped_probability_mass", 0.0)
    print(f"  |J|={len(data.J)}  |M|={len(data.M)}  |S|={num_scenarios}  dropped_mass={dropped:.6f}")

    path = output_path("gamma_frontier", args.output_dir)

    print(f"\nScanning {len(gammas)} gamma values: {gammas}")
    print(f"{'gamma':>8}  {'status':>16}  {'obj':>10}  {'cvar':>10}  {'cost':>10}  {'time_s':>8}")
    print("-" * 75)

    base_row = {
        "dataset": "Toy-2Task-Independent-v1",
        "beta": args.beta,
        "rho": args.rho,
        "loss_mode": args.loss_mode,
        "max_failed_components": args.max_failed_components,
        "aggregate_worst_case": str(args.aggregate_worst_case).lower(),
        "num_scenarios": num_scenarios,
        "dropped_probability_mass": f"{dropped:.6g}",
    }

    for gamma in gammas:
        _result, metrics = solve_m2_c_cost_once(
            data,
            gamma=gamma,
            beta_cvar=args.beta,
            rho_min_service=rho_min,
            time_limit=args.time_limit,
            mip_gap=args.mip_gap,
        )

        row = dict(base_row)
        row.update(metrics)
        write_csv_row(path, row)

        print(
            f"{gamma:8.3f}  {row['status']:>16}  "
            f"{row['objective']:>10}  {row['cvar_e2e']:>10}  "
            f"{row['total_cost']:>10}  {row['runtime_sec']:>8}"
        )

    print(f"\nFrontier saved to {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
