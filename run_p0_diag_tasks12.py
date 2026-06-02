#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
12 任务 P0 可行性诊断矩阵：min_off_hub × s2_derate × eta。

每个组合：Model A + loose Model C；若两者可行则跑 3×3 Γ 网格 + acceptance。

  python run_p0_diag_tasks12.py --output results/p0_diag_tasks12.csv
"""
from __future__ import annotations

import argparse
import csv
import tempfile
from pathlib import Path

from run_gamma_frontier import (
    load_p0_data,
    run_feasibility_diagnostic,
    _default_gamma_grid,
    _run_grid_point,
)


def _run_mini_grid_and_check(data, args, min_off_hub: int) -> dict:
    from scripts.p0_acceptance import run_acceptance

    g_sla, g_sf = _default_gamma_grid(data, 3)
    rows = []
    for gs in g_sla:
        for gf in g_sf:
            row = _run_grid_point(
                data,
                gs,
                gf,
                time_limit=args.time_limit,
                mip_gap=args.mip_gap,
                min_off_hub=min_off_hub,
            )
            rows.append(row)
    optimal = sum(1 for r in rows if r.get("status") == "OPTIMAL")
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".csv", delete=False, newline="", encoding="utf-8"
    ) as tf:
        tmp = Path(tf.name)
        fields = [
            "gamma_sla", "gamma_sf", "status", "cost", "cvar_sla", "cvar_sf",
        ]
        w = csv.DictWriter(tf, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)
    rc = run_acceptance(tmp, cost_band_pct=5.0, min_distinct_points=3)
    tmp.unlink(missing_ok=True)
    return {
        "grid3_optimal_count": optimal,
        "grid3_total": len(rows),
        "acceptance_pass": rc == 0,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="P0 tasks=12 feasibility diagnostic matrix")
    ap.add_argument("--output", default="results/p0_diag_tasks12.csv")
    ap.add_argument("--time-limit", type=int, default=120)
    ap.add_argument("--mip-gap", type=float, default=0.02)
    ap.add_argument("--s1-sigma", type=float, default=0.80)
    ap.add_argument("--num-tasks", type=int, default=12)
    args = ap.parse_args()

    min_off_hubs = [0, 1, 2]
    s2_derates = [0.40, 0.50, 0.60]
    etas = [1.2, 1.3]

    out_rows = []
    fieldnames = None

    for moh in min_off_hubs:
        for s2 in s2_derates:
            for eta in etas:
                print(f"\n=== |I|={args.num_tasks} min_off_hub={moh} s2={s2} eta={eta} ===")
                run_args = argparse.Namespace(
                    topology="B4",
                    base_path="./data",
                    routing_mode="per_task_od",
                    num_tasks=args.num_tasks,
                    k_paths=4,
                    eta=eta,
                    joint_demand_scale=None,
                    s1_sigma=args.s1_sigma,
                    s1_link_k=4,
                    s2_derate=s2,
                    min_off_hub=moh,
                    time_limit=args.time_limit,
                    mip_gap=args.mip_gap,
                )
                data = load_p0_data(
                    base_path=run_args.base_path,
                    topology=run_args.topology,
                    num_tasks=run_args.num_tasks,
                    k_paths=run_args.k_paths,
                    eta=eta,
                    joint_demand_scale=None,
                    routing_mode=run_args.routing_mode,
                    s2_derate=s2,
                    s1_link_k=4,
                    s1_sigma=args.s1_sigma,
                    quiet=True,
                )
                diag = run_feasibility_diagnostic(data, run_args, min_off_hub=moh)
                row = {
                    "min_off_hub": moh,
                    "s2_derate": s2,
                    "eta": eta,
                    "scenario_s1_link_sigma": args.s1_sigma,
                    "num_tasks": args.num_tasks,
                    "model_a_feasible": diag["model_a_feasible"],
                    "model_a_status": diag["model_a_status"],
                    "model_a_cvar_sla": diag["model_a_cvar_sla"],
                    "model_a_cvar_sf": diag["model_a_cvar_sf"],
                    "loose_model_c_feasible": diag["loose_model_c_feasible"],
                    "loose_model_c_status": diag["loose_model_c_status"],
                    "compute_assignment_feasible": diag.get("compute_assignment_feasible"),
                    "reason_guess": diag["reason_guess"],
                    "grid3_optimal_count": "",
                    "grid3_acceptance_pass": "",
                    "grid3_fail_reason": "",
                }
                if diag["model_a_feasible"] and diag["loose_model_c_feasible"]:
                    print("  [grid] running 3×3 + acceptance ...")
                    ginfo = _run_mini_grid_and_check(data, run_args, moh)
                    row["grid3_optimal_count"] = ginfo["grid3_optimal_count"]
                    row["grid3_acceptance_pass"] = ginfo["acceptance_pass"]
                    if not ginfo["acceptance_pass"]:
                        if ginfo["grid3_optimal_count"] == 0:
                            row["grid3_fail_reason"] = "gamma_too_tight_or_all_infeasible"
                        else:
                            row["grid3_fail_reason"] = "acceptance_criteria_not_met"
                elif not diag["model_a_feasible"]:
                    row["grid3_fail_reason"] = "skipped:Model_A_infeasible"
                else:
                    row["grid3_fail_reason"] = "skipped:loose_C_infeasible"

                out_rows.append(row)
                if fieldnames is None:
                    fieldnames = list(row.keys())

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(out_rows)
    print(f"\nWrote {out_path} ({len(out_rows)} combinations)")

    passing = [r for r in out_rows if r.get("grid3_acceptance_pass") is True]
    print(f"Combinations with grid3 acceptance PASS: {len(passing)}")
    for r in passing:
        print(
            f"  PASS: min_off_hub={r['min_off_hub']} s2={r['s2_derate']} eta={r['eta']} "
            f"optimal={r['grid3_optimal_count']}/9"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
