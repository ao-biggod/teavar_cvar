#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Phase B++++ task D: 4-point minimal repro matrix with placement/SF/objective decomposition."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DEFAULT_POINTS = [(1.0, 0.03), (1.0, 0.0377), (0.9, 0.03), (0.8, 0.03)]


def _placement(data, y) -> dict[int, int]:
    out: dict[int, int] = {}
    for i in data.I:
        for node in data.M:
            if (i, node) in y and y[i, node].X > 0.5:
                out[i] = node
                break
    return out


def _y_assignments(data, y) -> dict[str, float]:
    return {f"y_{i}_{node}": float(y[i, node].X) for i, node in y if y[i, node].X > 1e-6}


def _resource_util(data, placement: dict[int, int]) -> dict:
    util: dict = {}
    for node in data.M:
        util[str(node)] = {}
        for k in data.K:
            demand = sum(data.w[i][k] for i in data.I if placement.get(i) == node)
            cap = float(data.C_normal[node][k])
            util[str(node)][str(k)] = {
                "demand": float(demand),
                "C_normal": cap,
                "utilization": float(demand / cap) if cap > 0 else None,
            }
    return util


def _scenario_sf_detail(data, y, placement) -> dict:
    from metrics_posthoc import compute_d_ref, compute_sf_loss_by_scenario

    d_ref = compute_d_ref(data)
    loss_sf = compute_sf_loss_by_scenario(data, y, placement=placement)
    detail: dict = {"d_ref": d_ref, "sf_loss_by_scenario": {str(s): v for s, v in loss_sf.items()}}
    for s in data.S:
        per_node = {}
        for node in data.M:
            per_k = {}
            for k in data.K:
                demand = sum(data.w[i][k] for i in data.I if placement.get(i) == node)
                cap = float(data.C_s[node][k][s])
                raw = max(0.0, (demand - cap) / d_ref)
                per_k[str(k)] = {"demand": demand, "cap": cap, "shortfall_norm": raw}
            per_node[str(node)] = per_k
        detail[f"scenario_{s}_compute"] = per_node
    return detail


def _scenario_delivery(data, din, dout) -> dict:
    from cvar_compare import _task_flow_anchors
    from duibi_metrics import teavar_flow_anchors

    per_task = getattr(data, "routing_mode", "hub") in ("per_task_od", "umcf_per_task")
    if per_task:
        in_u, out_v = 0, 0
    else:
        in_u, out_v = teavar_flow_anchors(data)
    out: dict = {}
    for s in data.S:
        task_del: dict = {}
        for i in data.I:
            iu, ov = _task_flow_anchors(data, i, in_u, out_v)
            rin = sum(
                float(din[key].X)
                for key in din
                if key[3] == s and key[0] == i
            )
            rout = sum(
                float(dout[key].X)
                for key in dout
                if key[3] == s and key[0] == i
            )
            task_del[str(i)] = {"R_in": rin, "R_out": rout, "total": rin + rout}
        out[str(s)] = task_del
    return out


def _objective_breakdown(data, m, y, xin, xout, din, dout, omega: float) -> dict:
    from duibi_metrics import bandwidth_cost_expr
    from run_gamma_frontier import _exp_deliver_value
    from scripts.diagnose_gamma_monotonicity import _monetary_cost_breakdown

    cp, cb = _monetary_cost_breakdown(data, y, xin, xout)
    exp = _exp_deliver_value(data, m, din, dout)
    obj = float(m.ObjVal)
    return {
        "compute_cost": cp,
        "bandwidth_cost": cb,
        "monetary_cost": cp + cb,
        "model_cost_b_expr": float(bandwidth_cost_expr(data, xin, xout, None, None).getValue()),
        "exp_deliver": exp,
        "omega_deliver": omega,
        "obj_val": obj,
        "obj_reconstructed": cp + cb - omega * float(exp or 0.0),
    }


def diagnose_point(data, gamma_sla: float, gamma_sf: float, *, omega: float, min_off_hub: int, time_limit: float, mip_gap: float) -> dict:
    from metrics_posthoc import compute_posthoc_cvar_metrics
    from teavar_framework_models import build_teavar_model_c

    m, cost, lvc, svc, y, xin, xout, din, dout = build_teavar_model_c(
        data,
        gamma_sla=gamma_sla,
        gamma_sf=gamma_sf,
        omega_deliver=omega,
        include_sf_budget=True,
        min_tasks_off_hub=min_off_hub,
        time_limit=time_limit,
        mip_gap=mip_gap,
    )
    placement = _placement(data, y)
    ph = compute_posthoc_cvar_metrics(data, y, din, dout, model_cvar_sla=lvc, model_cvar_sf=svc)
    return {
        "gamma_sla": gamma_sla,
        "gamma_sf": gamma_sf,
        "status": int(m.status),
        "placement_summary": {str(i): placement[i] for i in sorted(placement)},
        "placement_signature": "|".join(f"{i}:{placement[i]}" for i in sorted(placement)),
        "y_assignments": _y_assignments(data, y),
        "resource_utilization": _resource_util(data, placement),
        "scenario_sf_detail": _scenario_sf_detail(data, y, placement),
        "scenario_delivery": _scenario_delivery(data, din, dout),
        "posthoc": ph,
        "objective_breakdown": _objective_breakdown(data, m, y, xin, xout, din, dout, omega),
        "model_cvar_sla": lvc,
        "model_cvar_sf": svc,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="4-point parity matrix diagnostics")
    ap.add_argument("--output-dir", default="results/parity_matrix_b4_tasks8")
    ap.add_argument("--topology", default="B4")
    ap.add_argument("--num-tasks", type=int, default=8)
    ap.add_argument("--eta", type=float, default=1.3)
    ap.add_argument("--min-off-hub", type=int, default=2)
    ap.add_argument("--omega-deliver", type=float, default=1.0)
    ap.add_argument("--time-limit", type=float, default=120)
    ap.add_argument("--mip-gap", type=float, default=0.02)
    args = ap.parse_args(argv)

    from run_gamma_frontier import load_p0_data

    data = load_p0_data(
        base_path="./data",
        topology=args.topology,
        num_tasks=args.num_tasks,
        k_paths=4,
        eta=args.eta,
        joint_demand_scale=None,
        routing_mode="per_task_od",
        s2_derate=0.4,
        s1_link_k=4,
        s1_sigma=0.8,
        link_price_mode="uniform",
        quiet=True,
    )
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    all_rows = []
    for gs, gf in DEFAULT_POINTS:
        row = diagnose_point(
            data, gs, gf,
            omega=args.omega_deliver,
            min_off_hub=args.min_off_hub,
            time_limit=args.time_limit,
            mip_gap=args.mip_gap,
        )
        all_rows.append(row)
        tag = f"gs{gs}_gf{gf}".replace(".", "p")
        path = out_dir / f"{tag}.json"
        with path.open("w", encoding="utf-8") as f:
            json.dump(row, f, indent=2, ensure_ascii=False, default=str)
            f.write("\n")
        print(f"Wrote {path} | placement={row['placement_signature']} posthoc_sf={row['posthoc'].get('posthoc_cvar_sf')}")
    summary = out_dir / "summary.json"
    with summary.open("w", encoding="utf-8") as f:
        json.dump(all_rows, f, indent=2, ensure_ascii=False, default=str)
        f.write("\n")
    print(f"Wrote {summary}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
