#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
B4 主表：Physical / teavar_sla(λ) / Model C / monetary A vs M vs M-C

用法:
  python run_b4_main_table.py
  python run_b4_main_table.py --no-stress --out output/b4_main_table
  python run_b4_main_table.py --umcf-teavar --out output/b4_main_table
"""

from __future__ import annotations

import argparse
import csv
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
os.chdir(ROOT)
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from gurobipy import GRB


def _placement_str(data, y) -> str:
    if y is None:
        return ""
    dist: dict[int, int] = {}
    for i in data.I:
        for n in data.M:
            if (i, n) in y and y[i, n].X > 0.5:
                dist[n] = dist.get(n, 0) + 1
    return ", ".join(f"n{k}:{v}" for k, v in sorted(dist.items()))


def write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = list(rows[0].keys())
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def _table_tag(args) -> str:
    parts = []
    if args.umcf_teavar:
        parts.append(f"umcf_s{args.umcf_sigma:.2f}".replace(".", "p"))
    elif args.virtual_source:
        parts.append(f"vs_s{args.virtual_sigma:.2f}".replace(".", "p"))
    if args.stress:
        parts.append("hubstress")
    else:
        parts.append(f"topk{args.scenario_s1_link_k}")
    parts.append(f"ds{int(args.demand_scale) if args.demand_scale == int(args.demand_scale) else args.demand_scale}")
    return "_".join(parts)


def run_main_table(args) -> list[dict]:
    from b4_joint_data import load_joint_data
    from cvar_compare import build_teavar_sla_cvar_model
    from duibi import build_single_layer_model
    from duibi_metrics import expected_total_delivered_volume
    from teavar_framework_models import build_teavar_model_a, build_teavar_model_c

    data = load_joint_data(
        base_path=str(ROOT / "data"),
        topology_name="B4",
        hub_index=args.hub,
        num_tasks=args.num_tasks,
        demand_scale=args.demand_scale,
        k_paths=args.k_paths,
        stress_zero_s1=args.stress,
        umcf_virtual_nodes=args.umcf_teavar,
        umcf_access_sigma=args.umcf_sigma,
        umcf_sink_access_sigma=args.umcf_sink_sigma,
        virtual_source=args.virtual_source and not args.umcf_teavar,
        virtual_source_sigma=args.virtual_sigma,
        virtual_sink_sigma=args.virtual_sink_sigma,
        scenario_s1_link_k=args.scenario_s1_link_k,
    )

    rows: list[dict] = []
    base = {
        "topology": "B4",
        "num_tasks": len(data.I),
        "demand_scale": args.demand_scale,
        "stress_s1": int(args.stress),
        "s1_link_k": args.scenario_s1_link_k,
        "umcf_teavar": int(args.umcf_teavar),
        "virtual_source": int(args.virtual_source and not args.umcf_teavar),
        "access_sigma": args.umcf_sigma if args.umcf_teavar else (args.virtual_sigma if args.virtual_source else ""),
        "min_off_hub": args.min_off_hub,
        "k_paths": args.k_paths,
    }

    lambdas = [float(x) for x in args.lambdas.split(",") if x.strip()]

    mode = "UMCF+stress" if args.umcf_teavar and args.stress else (
        "UMCF" if args.umcf_teavar else ("stress" if args.stress else "no-stress")
    )
    print(
        f"B4 主表 | |I|={len(data.I)} | demand_scale={args.demand_scale} | {mode} | "
        f"min_off_hub={args.min_off_hub}"
    )
    print("=" * 80)

    for lam in lambdas:
        mp, cp, ncv, lcv, yp, *_ = build_single_layer_model(data, lambda_val=lam)
        phys_ok = mp.status == GRB.OPTIMAL
        phys_risk = (ncv or 0) + (lcv or 0)
        row_p = {
            **base,
            "model": "Physical",
            "lambda": lam,
            "status": mp.status,
            "optimal": int(phys_ok),
            "cost": f"{cp:.4f}" if phys_ok else "",
            "SLA_CVaR": "",
            "nodeUtil_CVaR": f"{ncv:.4f}" if ncv is not None else "",
            "link_CVaR": f"{lcv:.4f}" if lcv is not None else "",
            "computeSf_CVaR": "",
            "E_del_vol": "",
            "obj_full": f"{cp + lam * phys_risk:.4f}" if phys_ok else "",
            "placement": _placement_str(data, yp) if phys_ok else "",
            "notes": "",
        }
        rows.append(row_p)
        print(
            f"Physical λ={lam:5g} | status={mp.status} | "
            + (f"cost={cp:.3f} node+link={phys_risk:.4f}" if phys_ok else "INFEASIBLE")
        )

        mt, ct, ltv, ntv, sfv, yt, xin_t, xout_t, din_t, dout_t = build_teavar_sla_cvar_model(
            data,
            lambda_cvar=lam,
            omega_deliver=args.omega,
            min_tasks_off_node0=args.min_off_hub,
            lambda_node_cvar=args.lambda_node,
            lambda_compute_sf_cvar=args.lambda_sf,
        )
        te_ok = mt.status == GRB.OPTIMAL
        ev = expected_total_delivered_volume(data, mt, din_t, dout_t) or 0.0 if te_ok else 0.0
        obj_full = (
            (ct or 0) + lam * (ltv or 0) + args.lambda_node * (ntv or 0) + args.lambda_sf * (sfv or 0) - args.omega * ev
            if te_ok
            else None
        )
        row_t = {
            **base,
            "model": "teavar_sla",
            "lambda": lam,
            "status": mt.status,
            "optimal": int(te_ok),
            "cost": f"{ct:.4f}" if te_ok else "",
            "SLA_CVaR": f"{ltv:.4f}" if ltv is not None else "",
            "nodeUtil_CVaR": f"{ntv:.4f}" if ntv is not None else "",
            "link_CVaR": "",
            "computeSf_CVaR": f"{sfv:.4f}" if sfv is not None else "",
            "E_del_vol": f"{ev:.3f}" if te_ok else "",
            "obj_full": f"{obj_full:.4f}" if obj_full is not None else "",
            "placement": _placement_str(data, yt) if te_ok else "",
            "notes": "",
        }
        rows.append(row_t)
        print(
            f"teavar_sla λ={lam:5g} | status={mt.status} | "
            + (
                f"cost={ct:.3f} SLA={ltv:.4f} nodeUtil={ntv or 0:.4f} sf={sfv or 0:.4f} E[del]={ev:.1f}"
                if te_ok
                else "INFEASIBLE"
            )
        )

    # Model C
    lam_c = args.calib_lambda
    ma, ca, lva, sva, ya, *_ = build_teavar_model_a(
        data,
        lambda_sla=lam_c,
        lambda_sf=args.lambda_sf,
        omega_deliver=args.omega,
        min_tasks_off_hub=args.min_off_hub,
    )
    g_sla = max(float(lva) * args.gamma_sla_slack, 1e-9) if lva is not None else 1.0
    include_sf = args.lambda_sf > 0 and (sva or 0) > 1e-12
    g_sf = max(float(sva) * args.gamma_sf_slack + 0.01, 1e-9) if include_sf else None

    mc, cc, lvc, svc, yc, xin_c, xout_c, din_c, dout_c = build_teavar_model_c(
        data,
        gamma_sla=g_sla,
        gamma_sf=g_sf,
        omega_deliver=args.omega,
        min_tasks_off_hub=args.min_off_hub,
        include_sf_budget=include_sf,
    )
    c_ok = mc.status == GRB.OPTIMAL
    ev_c = expected_total_delivered_volume(data, mc, din_c, dout_c) or 0.0 if c_ok else 0.0
    rows.append(
        {
            **base,
            "model": "Model_C",
            "lambda": "",
            "status": mc.status,
            "optimal": int(c_ok),
            "cost": f"{cc:.4f}" if c_ok else "",
            "SLA_CVaR": f"{lvc:.4f}" if lvc is not None else "",
            "nodeUtil_CVaR": "",
            "link_CVaR": "",
            "computeSf_CVaR": f"{svc:.4f}" if svc is not None else "",
            "E_del_vol": f"{ev_c:.3f}" if c_ok else "",
            "obj_full": "",
            "placement": _placement_str(data, yc) if c_ok else "",
            "notes": f"A@λ={lam_c} Γ_sla={g_sla:.4f}" + (f" Γ_sf={g_sf:.4f}" if g_sf else ""),
        }
    )
    print(
        f"Model C | A标定λ={lam_c} Γ_sla={g_sla:.4f} | status={mc.status} | "
        + (f"cost={cc:.3f} SLA={lvc:.4f} sf={svc or 0:.4f}" if c_ok else "INFEASIBLE")
    )

    # Monetary (capture via compare - we'll add separate rows manually)
    from monetary_cvar import (
        build_monetary_cvar_model,
        build_monetary_cvar_model_c,
        recompute_monetary_bills,
    )
    from cvar_compare import build_teavar_sla_cvar_model as build_a

    kappa = args.kappa
    ma2, ca2, lva2, nva2, sfva2, ya2, xia2, xoa2, dia2, doa2 = build_a(
        data,
        lambda_cvar=args.monetary_lambda_sla,
        omega_deliver=args.omega,
        min_tasks_off_node0=args.min_off_hub,
        lambda_node_cvar=0.0,
        lambda_compute_sf_cvar=0.0,
    )
    a_ok = ma2.status == GRB.OPTIMAL
    bills_a = (
        recompute_monetary_bills(data, ya2, dia2, doa2, kappa_sum=kappa)
        if a_ok
        else None
    )
    rows.append(
        {
            **base,
            "model": "Model_A_monetary",
            "lambda": args.monetary_lambda_sla,
            "status": ma2.status,
            "optimal": int(a_ok),
            "cost": f"{ca2:.4f}" if a_ok else "",
            "SLA_CVaR": f"{lva2:.4f}" if lva2 is not None else "",
            "nodeUtil_CVaR": "",
            "link_CVaR": "",
            "computeSf_CVaR": "",
            "E_del_vol": f"{bills_a['expected_bill']:.2f}" if bills_a else "",
            "obj_full": "",
            "placement": _placement_str(data, ya2) if a_ok else "",
            "notes": (
                f"E[L]={bills_a['expected_bill']:.2f} CVaR(L)={bills_a['cvar_L']:.2f}"
                if bills_a
                else ""
            ),
        }
    )
    print(
        f"Model A (monetary view) λ={args.monetary_lambda_sla} | "
        + (
            f"E[L]={bills_a['expected_bill']:.1f} CVaR(L)={bills_a['cvar_L']:.1f}"
            if bills_a
            else f"status={ma2.status}"
        )
    )

    rm = build_monetary_cvar_model(
        data, kappa_sum=kappa, min_tasks_off_hub=args.min_off_hub, mip_gap=args.mip_gap
    )
    m_ok = rm.status == GRB.OPTIMAL
    rows.append(
        {
            **base,
            "model": "Model_M",
            "lambda": "",
            "status": rm.status,
            "optimal": int(m_ok),
            "cost": f"{rm.cost_p:.4f}" if m_ok and rm.cost_p is not None else "",
            "SLA_CVaR": "",
            "nodeUtil_CVaR": "",
            "link_CVaR": "",
            "computeSf_CVaR": "",
            "E_del_vol": f"{rm.E_L:.2f}" if m_ok and rm.E_L is not None else "",
            "obj_full": f"{rm.cvar_L:.2f}" if m_ok and rm.cvar_L is not None else "",
            "placement": _placement_str(data, rm.y) if m_ok else "",
            "notes": f"CVaR(L)={rm.cvar_L:.2f}" if m_ok and rm.cvar_L is not None else "",
        }
    )
    print(
        f"Model M | "
        + (
            f"E[L]={rm.E_L:.1f} CVaR(L)={rm.cvar_L:.1f}"
            if m_ok and rm.E_L is not None
            else f"status={rm.status}"
        )
    )

    if m_ok and rm.cvar_L is not None:
        gamma_m = rm.cvar_L * 1.05
        rmc = build_monetary_cvar_model_c(
            data, gamma_m, kappa_sum=kappa, min_tasks_off_hub=args.min_off_hub, mip_gap=args.mip_gap
        )
        mc_ok = rmc.status == GRB.OPTIMAL
        rows.append(
            {
                **base,
                "model": "Model_M-C",
                "lambda": "",
                "status": rmc.status,
                "optimal": int(mc_ok),
                "cost": f"{rmc.cost_p:.4f}" if mc_ok and rmc.cost_p is not None else "",
                "SLA_CVaR": "",
                "nodeUtil_CVaR": "",
                "link_CVaR": "",
                "computeSf_CVaR": "",
                "E_del_vol": f"{rmc.E_L:.2f}" if mc_ok and rmc.E_L is not None else "",
                "obj_full": f"{gamma_m:.2f}",
                "placement": _placement_str(data, rmc.y) if mc_ok else "",
                "notes": (
                    f"Γ_money={gamma_m:.2f} CVaR={rmc.cvar_L:.2f}"
                    if mc_ok and rmc.cvar_L is not None
                    else ""
                ),
            }
        )
        print(
            f"Model M-C | Γ={gamma_m:.1f} | "
            + (
                f"E[L]={rmc.E_L:.1f} CVaR={rmc.cvar_L:.1f}"
                if mc_ok and rmc.E_L is not None
                else f"status={rmc.status}"
            )
        )

    return rows


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--out", type=str, default="output/b4_main_table")
    p.add_argument("--num-tasks", type=int, default=8)
    p.add_argument("--demand-scale", type=float, default=25.0)
    p.add_argument("--k-paths", type=int, default=4)
    p.add_argument("--min-off-hub", type=int, default=2)
    p.add_argument("--hub", type=int, default=0)
    p.add_argument("--lambdas", type=str, default="0.5,5,50")
    p.add_argument("--calib-lambda", type=float, default=50.0)
    p.add_argument("--lambda-node", type=float, default=0.5)
    p.add_argument("--lambda-sf", type=float, default=1.0)
    p.add_argument("--omega", type=float, default=1.0)
    p.add_argument("--gamma-sla-slack", type=float, default=1.5)
    p.add_argument("--gamma-sf-slack", type=float, default=2.0)
    p.add_argument("--kappa", type=float, default=5.0)
    p.add_argument("--monetary-lambda-sla", type=float, default=5.0)
    p.add_argument("--mip-gap", type=float, default=0.01)
    p.add_argument(
        "--stress",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="场景1 切断 hub 出边（默认开；--no-stress 关闭）",
    )
    p.add_argument(
        "--umcf-teavar",
        action="store_true",
        help="teavar_sla / Model C / monetary 使用显式 V_s,V_t 锚点",
    )
    p.add_argument("--umcf-sigma", type=float, default=0.99, help="UMCF 边 (V_s,m)/(m,V_t) 可用率")
    p.add_argument("--umcf-sink-sigma", type=float, default=None)
    p.add_argument("--virtual-source", action="store_true", help="sigma_vs/vt 虚拟接入瓶颈（与 UMCF 互斥）")
    p.add_argument("--virtual-sigma", type=float, default=0.95)
    p.add_argument("--virtual-sink-sigma", type=float, default=None)
    p.add_argument("--scenario-s1-link-k", type=int, default=4, help="s1 按 prob_failure 断链条数（0=无）")
    p.add_argument("--csv-name", type=str, default=None, help="输出 CSV 文件名（缺省按 tag 自动生成）")
    args = p.parse_args()

    rows = run_main_table(args)
    out_dir = Path(args.out)
    tag = _table_tag(args)
    csv_name = args.csv_name or f"table_b4_{tag}_main.csv"
    csv_path = out_dir / csv_name
    write_csv(csv_path, rows)
    print("=" * 80)
    print(f"CSV → {csv_path}")


if __name__ == "__main__":
    main()
