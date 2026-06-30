# -*- coding: utf-8 -*-
"""
Γ_sla × Γ_sf 网格扫描：双层 Model C + 可选单层 Model C 对照。

示例：
  python scripts/run_bilevel_gamma_frontier.py --output results/bilevel_gamma_frontier_cr.csv
  python scripts/run_bilevel_gamma_frontier.py --compare-single --fast-objective lexicographic
"""
from __future__ import annotations

import argparse
import csv
import sys
import time
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bilevel_teavar_models import BilevelCompareCReport, compare_bilevel_c_with_single_layer_c
from toy_instances import CR_A, CR_B, CR_C, build_toy_combined_component_risk


def _parse_gamma_list(s: str | None, default: list[float]) -> list[float]:
    if not s:
        return default
    return [float(x.strip()) for x in s.split(",") if x.strip()]


def _linspace(a: float, b: float, n: int) -> list[float]:
    if n <= 1:
        return [a]
    step = (b - a) / (n - 1)
    return [a + i * step for i in range(n)]


def _row_dict(r: BilevelCompareCReport) -> dict:
    d = asdict(r)
    d["placement_match"] = "" if r.placement_match is None else int(bool(r.placement_match))
    return d


def _fieldnames(sample: dict) -> list[str]:
    order = [
        "gamma_sla",
        "gamma_sf",
        "bilevel_status",
        "bilevel_placement_code",
        "bilevel_cost",
        "bilevel_cvar_sla",
        "bilevel_cvar_sf",
        "bilevel_edel",
        "bilevel_feasible_count",
        "bilevel_evaluated_count",
        "bilevel_runtime_sec",
        "single_status",
        "single_placement_code",
        "single_cost",
        "single_cvar_sla",
        "single_cvar_sf",
        "placement_match",
        "cost_gap",
        "cvar_sla_gap",
        "cvar_sf_gap",
    ]
    return [k for k in order if k in sample]


def main() -> None:
    p = argparse.ArgumentParser(description="Bilevel Model C Γ frontier (ComponentRisk toy default)")
    p.add_argument(
        "--gamma-sla-grid",
        type=str,
        default=None,
        help="Comma-separated Γ_sla values (default: linspace 0.05..1.0, 5 points)",
    )
    p.add_argument(
        "--gamma-sf-grid",
        type=str,
        default=None,
        help="Comma-separated Γ_sf values (default: linspace 0.025..1.0, 5 points)",
    )
    p.add_argument("--grid-size", type=int, default=5, help="Grid side length if lists not given")
    p.add_argument("--omega", type=float, default=1.0)
    p.add_argument(
        "--fast-objective",
        choices=("delivery", "lexicographic", "min_sla_cvar"),
        default="delivery",
    )
    p.add_argument("--compare-single", action="store_true", help="Also run single-layer Model C")
    p.add_argument("--time-limit", type=float, default=120.0)
    p.add_argument(
        "--output",
        type=str,
        default="results/bilevel_gamma_frontier_cr.csv",
    )
    args = p.parse_args()

    n = max(2, int(args.grid_size))
    gamma_sla_vals = _parse_gamma_list(
        args.gamma_sla_grid,
        _linspace(0.05, 1.0, n),
    )
    gamma_sf_vals = _parse_gamma_list(
        args.gamma_sf_grid,
        _linspace(0.025, 1.0, n),
    )

    data = build_toy_combined_component_risk()
    data.placement_node_labels = {"A": CR_A, "B": CR_B, "C": CR_C}

    rows: list[dict] = []
    t_all = time.perf_counter()
    total = len(gamma_sla_vals) * len(gamma_sf_vals)
    idx = 0

    print(
        f"Bilevel Γ frontier: |Γ_sla|={len(gamma_sla_vals)} × |Γ_sf|={len(gamma_sf_vals)} "
        f"= {total} points, fast_objective={args.fast_objective}, compare_single={args.compare_single}"
    )

    for g_sla in gamma_sla_vals:
        for g_sf in gamma_sf_vals:
            idx += 1
            rep = compare_bilevel_c_with_single_layer_c(
                data,
                gamma_sla=g_sla,
                gamma_sf=g_sf,
                omega_deliver=args.omega,
                fast_objective=args.fast_objective,
                time_limit=args.time_limit,
                compare_single=args.compare_single,
            )
            row = _row_dict(rep)
            rows.append(row)
            tag = row.get("bilevel_placement_code") or "INFEAS"
            match = row.get("placement_match", "")
            print(
                f"  [{idx}/{total}] Γ=({g_sla:.4f},{g_sf:.4f}) "
                f"bi={tag} cost={row.get('bilevel_cost')} "
                f"match={match} gap={row.get('cost_gap')}"
            )

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    fields = _fieldnames(rows[0]) if rows else []
    with out.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)

    elapsed = time.perf_counter() - t_all
    n_match = sum(1 for r in rows if r.get("placement_match") == 1)
    n_bi_feas = sum(1 for r in rows if r.get("bilevel_status") == "OPTIMAL")
    n_mismatch = sum(
        1 for r in rows
        if r.get("placement_match") == 0 and r.get("bilevel_status") == "OPTIMAL"
    )
    print(f"\nWrote {len(rows)} rows → {out}")
    print(f"Total wall time: {elapsed:.2f}s")
    print(f"Bilevel feasible: {n_bi_feas}/{len(rows)}")
    if args.compare_single:
        print(f"Placement match: {n_match}/{n_bi_feas} (mismatch={n_mismatch})")


if __name__ == "__main__":
    main()
