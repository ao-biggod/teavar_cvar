#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""P0 实验：恢复 teavar_sla λ 灵敏度 — UMCF σ / virtual σ / top-k 无 hub stress"""

from __future__ import annotations

import argparse
import csv
import os
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent
os.chdir(ROOT)
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from gurobipy import GRB


@dataclass
class SweepCase:
    name: str
    stress_hub: bool = False
    s1_link_k: int = 4
    umcf: bool = False
    umcf_sigma: float = 0.99
    virtual_source: bool = False
    virtual_sigma: float = 0.99


P0_CASES = [
    SweepCase("umcf_sigma095", stress_hub=False, umcf=True, umcf_sigma=0.95),
    SweepCase("umcf_sigma090", stress_hub=False, umcf=True, umcf_sigma=0.90),
    SweepCase("umcf_sigma090_hub", stress_hub=True, umcf=True, umcf_sigma=0.90),
    SweepCase("virtual_sigma095", stress_hub=False, virtual_source=True, virtual_sigma=0.95),
    SweepCase("virtual_sigma090", stress_hub=False, virtual_source=True, virtual_sigma=0.90),
    SweepCase("virtual_sigma095_hub", stress_hub=True, virtual_source=True, virtual_sigma=0.95),
    SweepCase("hub_stress_baseline", stress_hub=True, s1_link_k=4),
    SweepCase("topk1_nohub", stress_hub=False, s1_link_k=1),
    SweepCase("topk2_nohub", stress_hub=False, s1_link_k=2),
    SweepCase("topk4_nohub", stress_hub=False, s1_link_k=4),
]


def _placement_str(data, y) -> str:
    if y is None:
        return ""
    dist: dict[int, int] = {}
    for i in data.I:
        for n in data.M:
            if (i, n) in y and y[i, n].X > 0.5:
                dist[n] = dist.get(n, 0) + 1
    return ", ".join(f"n{k}:{v}" for k, v in sorted(dist.items()))


def run_teavar_sweep(case: SweepCase, lambdas: list[float], args) -> list[dict]:
    from b4_joint_data import load_joint_data
    from cvar_compare import build_teavar_sla_cvar_model
    from duibi_metrics import expected_total_delivered_volume

    data = load_joint_data(
        base_path=str(ROOT / "data"),
        topology_name="B4",
        hub_index=args.hub,
        num_tasks=args.num_tasks,
        demand_scale=args.demand_scale,
        k_paths=args.k_paths,
        stress_zero_s1=case.stress_hub,
        scenario_s1_link_k=case.s1_link_k,
        virtual_source=case.virtual_source and not case.umcf,
        virtual_source_sigma=case.virtual_sigma,
        umcf_virtual_nodes=case.umcf,
        umcf_access_sigma=case.umcf_sigma,
    )

    rows: list[dict] = []
    print(f"\n{'='*80}")
    print(
        f"[{case.name}] |I|={len(data.I)} ds={args.demand_scale} | "
        f"hub_stress={case.stress_hub} s1_k={case.s1_link_k} | "
        f"umcf={case.umcf} σ_umcf={case.umcf_sigma if case.umcf else '-'} | "
        f"vs={case.virtual_source} σ_vs={case.virtual_sigma if case.virtual_source else '-'}"
    )
    print("-" * 80)

    prev_key = None
    for lam in lambdas:
        mt, ct, ltv, ntv, sfv, yt, xin_t, xout_t, din_t, dout_t = build_teavar_sla_cvar_model(
            data,
            lambda_cvar=lam,
            omega_deliver=args.omega,
            min_tasks_off_node0=args.min_off_hub,
            lambda_node_cvar=args.lambda_node,
            lambda_compute_sf_cvar=args.lambda_sf,
        )
        ok = mt.status == GRB.OPTIMAL
        ev = expected_total_delivered_volume(data, mt, din_t, dout_t) or 0.0 if ok else 0.0
        placement = _placement_str(data, yt) if ok else ""
        key = (f"{ct:.4f}" if ok else "", f"{ltv:.4f}" if ltv is not None else "", placement)
        changed = prev_key is not None and key != prev_key
        prev_key = key

        row = {
            "case": case.name,
            "lambda": lam,
            "status": mt.status,
            "optimal": int(ok),
            "cost": f"{ct:.4f}" if ok else "",
            "SLA_CVaR": f"{ltv:.4f}" if ltv is not None else "",
            "nodeUtil_CVaR": f"{ntv:.4f}" if ntv is not None else "",
            "computeSf_CVaR": f"{sfv:.4f}" if sfv is not None else "",
            "E_del_vol": f"{ev:.3f}" if ok else "",
            "placement": placement,
            "lambda_sensitive": int(changed),
            "stress_hub": int(case.stress_hub),
            "s1_link_k": case.s1_link_k,
            "umcf": int(case.umcf),
            "umcf_sigma": case.umcf_sigma if case.umcf else "",
            "virtual_source": int(case.virtual_source),
            "virtual_sigma": case.virtual_sigma if case.virtual_source else "",
            "demand_scale": args.demand_scale,
            "num_tasks": len(data.I),
        }
        rows.append(row)
        flag = " *Δ*" if changed else ""
        print(
            f"  λ={lam:5g} | "
            + (
                f"cost={ct:.3f} SLA={ltv:.4f} nodeU={ntv or 0:.4f} sf={sfv or 0:.4f} "
                f"E[del]={ev:.1f} | {placement}{flag}"
                if ok
                else f"status={mt.status}"
            )
        )

    sla_vals = [float(r["SLA_CVaR"]) for r in rows if r["SLA_CVaR"]]
    costs = [float(r["cost"]) for r in rows if r["cost"]]
    n_sensitive = sum(r["lambda_sensitive"] for r in rows)
    summary = {
        "case": case.name,
        "SLA_min": min(sla_vals) if sla_vals else "",
        "SLA_max": max(sla_vals) if sla_vals else "",
        "cost_min": min(costs) if costs else "",
        "cost_max": max(costs) if costs else "",
        "cost_spread": (max(costs) - min(costs)) if len(costs) >= 2 else 0,
        "lambda_steps_changed": n_sensitive,
        "lambda_effective": int(n_sensitive > 0 or (len(costs) >= 2 and max(costs) - min(costs) > 0.01)),
    }
    print(
        f"  >> SLA∈[{summary['SLA_min']},{summary['SLA_max']}] "
        f"cost∈[{summary['cost_min']},{summary['cost_max']}] "
        f"λ敏感={'YES' if summary['lambda_effective'] else 'NO'}"
    )
    return rows, summary


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--out", default="output/b4_p0_sweep")
    p.add_argument("--num-tasks", type=int, default=8)
    p.add_argument("--demand-scale", type=float, default=25.0)
    p.add_argument("--k-paths", type=int, default=4)
    p.add_argument("--min-off-hub", type=int, default=2)
    p.add_argument("--hub", type=int, default=0)
    p.add_argument("--lambdas", default="0.5,5,50,500")
    p.add_argument("--lambda-node", type=float, default=0.5)
    p.add_argument("--lambda-sf", type=float, default=1.0)
    p.add_argument("--omega", type=float, default=1.0)
    p.add_argument("--cases", default=None, help="逗号分隔 case 名；缺省=全部 P0")
    args = p.parse_args()

    lambdas = [float(x) for x in args.lambdas.split(",") if x.strip()]
    cases = P0_CASES
    if args.cases:
        names = {x.strip() for x in args.cases.split(",") if x.strip()}
        cases = [c for c in P0_CASES if c.name in names]

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    all_rows: list[dict] = []
    summaries: list[dict] = []
    for case in cases:
        rows, summary = run_teavar_sweep(case, lambdas, args)
        all_rows.extend(rows)
        summaries.append(summary)

    detail_path = out_dir / "p0_teavar_lambda_sweep.csv"
    summary_path = out_dir / "p0_teavar_summary.csv"

    with detail_path.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(all_rows[0].keys()))
        w.writeheader()
        w.writerows(all_rows)

    with summary_path.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(summaries[0].keys()))
        w.writeheader()
        w.writerows(summaries)

    print(f"\n{'='*80}")
    print("P0 汇总（λ 是否有效 = cost/SLA/放置 随 λ 变化）")
    print(f"{'case':>18} | {'SLA range':>14} | {'cost spread':>11} | effective")
    print("-" * 60)
    for s in summaries:
        sla_r = f"{s['SLA_min']}–{s['SLA_max']}"
        eff = "YES" if s["lambda_effective"] else "NO"
        print(f"{s['case']:>18} | {sla_r:>14} | {s['cost_spread']:>11.4f} | {eff}")
    print(f"\n详情 → {detail_path}")
    print(f"汇总 → {summary_path}")


if __name__ == "__main__":
    main()
