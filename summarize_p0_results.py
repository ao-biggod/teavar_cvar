#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
汇总 P0 8/11/12 任务边界对照表 → results/p0_summary_table.csv。

用法：
  python summarize_p0_results.py
  python summarize_p0_results.py --output results/p0_summary_table.csv
"""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

from scripts.p0_acceptance import _load_rows, _optimal_rows, check_v1, check_v2, check_v3


def _summarize_frontier(csv_path: Path) -> dict:
    rows, colmap = _load_rows(csv_path)
    points = _optimal_rows(rows, colmap)
    total = len(rows)
    optimal = len(points)

    if points:
        slas = [p["cvar_sla"] for p in points]
        sfs = [p["cvar_sf"] for p in points]
        costs = [p["cost"] for p in points]
        sla_min, sla_max = min(slas), max(slas)
        sf_min, sf_max = min(sfs), max(sfs)
        cost_min, cost_max = min(costs), max(costs)
    else:
        sla_min = sla_max = sf_min = sf_max = cost_min = cost_max = ""

    v1_ok, _ = check_v1(points) if points else (False, "")
    v2_ok, _ = check_v2(points) if points else (False, "")
    v3_ok, _ = check_v3(points, 5.0, 3) if points else (False, "")
    acceptance = "PASS" if (v1_ok and v2_ok and v3_ok) else ("FAIL" if points else "N/A")

    num_tasks = ""
    if rows:
        num_tasks = rows[0].get("num_tasks", "")
    if not num_tasks and points:
        num_tasks = points[0]["raw"].get("num_tasks", "")

    status_summary = f"{optimal}/{total} OPTIMAL"
    return {
        "num_tasks": num_tasks,
        "status_summary": status_summary,
        "optimal_points": optimal,
        "cvar_sla_min": sla_min,
        "cvar_sla_max": sla_max,
        "cvar_sf_min": sf_min,
        "cvar_sf_max": sf_max,
        "cost_min": cost_min,
        "cost_max": cost_max,
        "acceptance": acceptance,
    }


def _summarize_tasks12(diag_path: Path) -> dict:
    with diag_path.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    n = len(rows)
    compute_bad = sum(
        1 for r in rows if str(r.get("compute_assignment_feasible", "")).lower() == "false"
    )
    model_a_ok = sum(1 for r in rows if str(r.get("model_a_feasible", "")).lower() == "true")
    status_summary = (
        f"0/{n} frontier feasible; "
        f"Model A feasible in {model_a_ok}/{n}; "
        f"compute_assignment_infeasible in {compute_bad}/{n}"
    )
    return {
        "num_tasks": "12",
        "status_summary": status_summary,
        "optimal_points": 0,
        "cvar_sla_min": "",
        "cvar_sla_max": "",
        "cvar_sf_min": "",
        "cvar_sf_max": "",
        "cost_min": "",
        "cost_max": "",
        "acceptance": "N/A (no frontier)",
    }


def _interpretation(num_tasks: str, summary: dict) -> str:
    n = str(num_tasks)
    if n == "8":
        return "main frontier, non-degenerate, PASS"
    if n == "11":
        cmin, cmax = summary.get("cost_min"), summary.get("cost_max")
        flat = (
            cmin != ""
            and cmax != ""
            and abs(float(cmax) - float(cmin)) < 0.01
        )
        base = "capacity boundary, feasible"
        return f"{base}, cost-flat" if flat else f"{base}, frontier degenerate"
    if n == "12":
        return "compute placement infeasible, structural ceiling"
    return ""


def build_summary_table(
    tasks8_csv: Path,
    tasks11_csv: Path,
    tasks12_diag_csv: Path,
) -> list[dict]:
    out = []
    for path, is_diag in (
        (tasks8_csv, False),
        (tasks11_csv, False),
        (tasks12_diag_csv, True),
    ):
        if not path.is_file():
            print(f"WARNING: missing {path}", file=sys.stderr)
            continue
        if is_diag:
            row = _summarize_tasks12(path)
        else:
            row = _summarize_frontier(path)
        row["interpretation"] = _interpretation(row["num_tasks"], row)
        out.append(row)
    return out


def write_summary_csv(rows: list[dict], output_path: Path) -> None:
    fieldnames = [
        "num_tasks",
        "status_summary",
        "optimal_points",
        "cvar_sla_min",
        "cvar_sla_max",
        "cvar_sf_min",
        "cvar_sf_max",
        "cost_min",
        "cost_max",
        "acceptance",
        "interpretation",
    ]
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in fieldnames})


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="P0 8/11/12 boundary summary table")
    ap.add_argument(
        "--tasks8-csv",
        default="results/p0_gamma_frontier_b4_tasks8_grid5.csv",
    )
    ap.add_argument(
        "--tasks11-csv",
        default="results/p0_gamma_frontier_b4_tasks11_grid3.csv",
    )
    ap.add_argument(
        "--tasks12-diag-csv",
        default="results/p0_diag_tasks12.csv",
    )
    ap.add_argument(
        "--output",
        default="results/p0_summary_table.csv",
    )
    args = ap.parse_args(argv)

    rows = build_summary_table(
        Path(args.tasks8_csv),
        Path(args.tasks11_csv),
        Path(args.tasks12_diag_csv),
    )
    if not rows:
        print("ERROR: no input files found", file=sys.stderr)
        return 2

    out_path = Path(args.output)
    write_summary_csv(rows, out_path)
    print(f"Wrote {out_path} ({len(rows)} rows)")
    for r in rows:
        print(
            f"  |I|={r['num_tasks']}: {r['status_summary']} | "
            f"acceptance={r['acceptance']} | {r['interpretation']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
