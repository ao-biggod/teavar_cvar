#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
routing_mode 消融：per_task_od vs umcf_global vs umcf_per_task（小网格，非 P0 主图）。

用法：
  python run_routing_mode_ablation.py --num-tasks 4 --grid-size 3 \\
    --output results/routing_mode_ablation_tasks4.csv
"""
from __future__ import annotations

import argparse
import csv
import tempfile
from pathlib import Path

from run_gamma_frontier import (
    load_p0_data,
    run_frontier_grid,
    write_frontier_csv,
    collect_virtual_edge_metadata,
    summarize_frontier_csv,
)

DEFAULT_MODES = ["per_task_od", "umcf_global", "umcf_per_task"]


def _summarize_mode(
    routing_mode: str,
    frontier_rows: list[dict],
    *,
    num_tasks: int,
    virtual_meta: dict,
) -> dict:
    from scripts.p0_acceptance import run_acceptance

    total = len(frontier_rows)
    optimal = [r for r in frontier_rows if str(r.get("status", "")).upper() == "OPTIMAL"]
    infeasible = total - len(optimal)

    row = {
        "routing_mode": routing_mode,
        "num_tasks": num_tasks,
        "optimal_points": len(optimal),
        "infeasible_points": infeasible,
        "cvar_sla_min": "",
        "cvar_sla_max": "",
        "cvar_sf_min": "",
        "cvar_sf_max": "",
        "cost_min": "",
        "cost_max": "",
        "acceptance_pass": False,
        "virtual_edge_count": virtual_meta.get("virtual_edge_count", 0),
        "umcf_access_sigma": virtual_meta.get("umcf_access_sigma", ""),
        "virtual_edge_price_policy": virtual_meta.get("virtual_edge_price_policy", ""),
        "virtual_edge_sigma_policy": virtual_meta.get("virtual_edge_sigma_policy", ""),
        "notes": "",
    }

    if not optimal:
        row["notes"] = "no_optimal_points"
        return row

    slas = [float(r["cvar_sla"]) for r in optimal]
    sfs = [float(r["cvar_sf"]) for r in optimal]
    costs = [float(r["cost"]) for r in optimal]
    row.update(
        {
            "cvar_sla_min": min(slas),
            "cvar_sla_max": max(slas),
            "cvar_sf_min": min(sfs),
            "cvar_sf_max": max(sfs),
            "cost_min": min(costs),
            "cost_max": max(costs),
        }
    )

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".csv", delete=False, newline="", encoding="utf-8"
    ) as tf:
        tmp = Path(tf.name)
        write_frontier_csv(tmp, frontier_rows)
    rc = run_acceptance(tmp, cost_band_pct=5.0, min_distinct_points=3)
    tmp.unlink(missing_ok=True)
    row["acceptance_pass"] = rc == 0
    if not row["acceptance_pass"]:
        row["notes"] = "acceptance_fail"
    elif len(set(round(c, 4) for c in costs)) == 1:
        row["notes"] = "cost_flat"
    return row


def run_ablation(args) -> tuple[list[dict], list[dict]]:
    summary_rows: list[dict] = []
    all_points: list[dict] = []

    for mode in args.routing_modes:
        print(f"\n=== routing_mode={mode} |I|={args.num_tasks} ===", flush=True)
        args.routing_mode = mode
        data = load_p0_data(
            base_path=args.base_path,
            topology=args.topology,
            num_tasks=args.num_tasks,
            k_paths=args.k_paths,
            eta=args.eta,
            joint_demand_scale=None,
            routing_mode=mode,
            s2_derate=args.s2_derate,
            s1_link_k=args.s1_link_k,
            s1_sigma=args.s1_sigma,
            umcf_access_sigma=args.umcf_access_sigma,
            umcf_sink_access_sigma=args.umcf_sink_access_sigma,
            quiet=False,
        )
        virtual_meta = collect_virtual_edge_metadata(data)
        frontier_rows = run_frontier_grid(
            data, args, routing_mode=mode, virtual_meta=virtual_meta
        )
        all_points.extend(frontier_rows)
        summary_rows.append(
            _summarize_mode(
                mode,
                frontier_rows,
                num_tasks=args.num_tasks,
                virtual_meta=virtual_meta,
            )
        )
        print(
            f"  summary: optimal={summary_rows[-1]['optimal_points']}/{len(frontier_rows)} "
            f"acceptance={summary_rows[-1]['acceptance_pass']}"
        )

    return summary_rows, all_points


SUMMARY_FIELDS = [
    "routing_mode",
    "num_tasks",
    "optimal_points",
    "infeasible_points",
    "cvar_sla_min",
    "cvar_sla_max",
    "cvar_sf_min",
    "cvar_sf_max",
    "cost_min",
    "cost_max",
    "acceptance_pass",
    "virtual_edge_count",
    "umcf_access_sigma",
    "virtual_edge_price_policy",
    "virtual_edge_sigma_policy",
    "notes",
]


def write_summary_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=SUMMARY_FIELDS, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="P0 routing_mode ablation (non-flagship)")
    ap.add_argument("--topology", default="B4")
    ap.add_argument("--base-path", default="./data")
    ap.add_argument("--num-tasks", type=int, default=4)
    ap.add_argument("--grid-size", type=int, default=3, choices=(3, 5))
    ap.add_argument("--eta", type=float, default=1.3)
    ap.add_argument("--s1-sigma", type=float, default=0.80, dest="s1_sigma")
    ap.add_argument("--s1-link-k", type=int, default=4)
    ap.add_argument("--s2-derate", type=float, default=0.40)
    ap.add_argument("--min-off-hub", type=int, default=2)
    ap.add_argument("--k-paths", type=int, default=4)
    ap.add_argument("--time-limit", type=int, default=120)
    ap.add_argument("--mip-gap", type=float, default=0.02)
    ap.add_argument("--umcf-access-sigma", type=float, default=0.99)
    ap.add_argument("--umcf-sink-access-sigma", type=float, default=None)
    ap.add_argument(
        "--routing-modes",
        nargs="+",
        default=DEFAULT_MODES,
        choices=DEFAULT_MODES,
    )
    ap.add_argument("--output", default="results/routing_mode_ablation_tasks4.csv")
    ap.add_argument(
        "--points-output",
        default=None,
        help="前沿散点 CSV（默认 <output>_points.csv）",
    )
    args = ap.parse_args(argv)
    args.routing_mode = DEFAULT_MODES[0]
    args.joint_demand_scale = None
    args.gamma_sla_values = None
    args.gamma_sf_values = None
    args.joint_umcf_per_task = False
    args.joint_umcf_teavar = False
    args.umcf_access_sigma = args.umcf_access_sigma
    args.umcf_sink_access_sigma = args.umcf_sink_access_sigma

    summary_rows, all_points = run_ablation(args)

    out_path = Path(args.output)
    write_summary_csv(out_path, summary_rows)
    points_path = Path(
        args.points_output
        or str(out_path.with_name(out_path.stem + "_points.csv"))
    )
    write_frontier_csv(points_path, all_points)

    print(f"\nWrote summary {out_path} ({len(summary_rows)} modes)")
    print(f"Wrote points  {points_path} ({len(all_points)} rows)")
    for r in summary_rows:
        print(
            f"  {r['routing_mode']}: optimal={r['optimal_points']} "
            f"cost=[{r['cost_min']},{r['cost_max']}] acceptance={r['acceptance_pass']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
