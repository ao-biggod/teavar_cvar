#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
P0 旗舰图最小版：per-task OD + Model C，Γ_sla × Γ_sf 网格扫描。

示例：
  python run_gamma_frontier.py --grid-size 3 --output results/p0_gamma_frontier_smoke.csv --check
  python run_gamma_frontier.py --diagnose-feasibility --num-tasks 12 --diag-output results/p0_feas_diag.csv
"""
from __future__ import annotations

import argparse
import csv
import sys
import time
from pathlib import Path

from gurobipy import GRB

LOOSE_GAMMA_SLA = 0.95
LOOSE_GAMMA_SF = 1.00

STATUS_NAMES = {
    GRB.OPTIMAL: "OPTIMAL",
    GRB.INFEASIBLE: "INFEASIBLE",
    GRB.INF_OR_UNBD: "INF_OR_UNBD",
    GRB.UNBOUNDED: "UNBOUNDED",
    GRB.TIME_LIMIT: "TIME_LIMIT",
    GRB.SUBOPTIMAL: "SUBOPTIMAL",
}


def _status_name(code: int) -> str:
    return STATUS_NAMES.get(code, str(int(code)))


def _has_solution(m) -> bool:
    return m.SolCount > 0


def _parse_gamma_list(s: str | None, default: list[float]) -> list[float]:
    if not s:
        return default
    return [float(x.strip()) for x in s.split(",") if x.strip()]


def _exp_deliver_value(data, m, del_in, del_out) -> float | None:
    if not _has_solution(m):
        return None
    from cvar_compare import _task_flow_anchors
    from duibi_metrics import teavar_flow_anchors

    mode = getattr(data, "routing_mode", "hub")
    if mode in ("per_task_od", "umcf_per_task"):
        in_u, out_v = 0, 0
    else:
        in_u, out_v = teavar_flow_anchors(data)
    tot = 0.0
    for s in data.S:
        ps = float(data.prob[s])
        for i in data.I:
            iu, ov = _task_flow_anchors(data, i, in_u, out_v)
            for node in data.M:
                for p in range(len(data.P_cand[iu, node])):
                    key = (i, node, p, s)
                    if key in del_in:
                        tot += ps * float(del_in[key].X)
                for q in range(len(data.P_cand[node, ov])):
                    key = (i, node, q, s)
                    if key in del_out:
                        tot += ps * float(del_out[key].X)
    return tot


def resolve_routing_mode(args) -> str:
    """CLI → routing_mode（P0 默认 per_task_od）。"""
    if getattr(args, "joint_umcf_per_task", False):
        return "umcf_per_task"
    rm = getattr(args, "routing_mode", "per_task_od") or "per_task_od"
    if rm in ("hub", "per_task_od") and getattr(args, "joint_umcf_teavar", False):
        return "umcf_global"
    return rm


def collect_virtual_edge_metadata(data) -> dict:
    """
    UMCF 虚拟边审计元数据（不改变模型语义，供 CSV/README 记录）。

    虚拟边 **参与** ``bandwidth_cost_expr``（路径价含虚拟 hop 的 link_price）；
    ``is_umcf_auxiliary_edge`` 仅用于链路利用率指标，不剔除带宽费。
    """
    from duibi_metrics import ensure_link_prices, is_umcf_auxiliary_edge

    ensure_link_prices(data)
    mode = getattr(data, "routing_mode", "hub")
    n_phys = len(data.M)
    virtual_edges = [e for e in data.E if is_umcf_auxiliary_edge(data, e)]
    prices = [float(data.link_price[e]) for e in virtual_edges] if virtual_edges else []
    sigmas_s0 = []
    for e in virtual_edges:
        if e in data.sigma and 0 in data.sigma[e]:
            sigmas_s0.append(float(data.sigma[e][0]))

    access_sigma = getattr(data, "umcf_access_sigma", None)
    if access_sigma is None and virtual_edges:
        access_sigma = sigmas_s0[0] if sigmas_s0 else None

    price_mode = str(getattr(data, "bandwidth_price_mode", "inverse_capacity"))
    price_scale = float(getattr(data, "bandwidth_price_scale", 1.0))
    price_policy = f"{price_mode}@scale={price_scale:g}"

    if mode == "umcf_per_task":
        sigma_policy = f"per_task_virtual_edges@access={access_sigma}"
    elif mode == "umcf_global" or virtual_edges:
        sink = getattr(data, "umcf_sink_access_sigma", None)
        sigma_policy = f"global_Vs_Vt@access={access_sigma},sink={sink or access_sigma}"
    else:
        sigma_policy = "n/a"

    participates_in_bandwidth_cost = bool(virtual_edges) and mode in (
        "umcf_global",
        "umcf_per_task",
    )

    meta = {
        "virtual_edge_count": len(virtual_edges),
        "virtual_edge_price_policy": price_policy,
        "virtual_edge_sigma_policy": sigma_policy,
        "umcf_access_sigma": access_sigma if access_sigma is not None else "",
        "virtual_edges_in_bandwidth_cost": participates_in_bandwidth_cost,
    }
    if prices:
        meta["virtual_edge_link_price_min"] = min(prices)
        meta["virtual_edge_link_price_max"] = max(prices)
        meta["virtual_edge_link_price_sample"] = prices[0]
    else:
        meta["virtual_edge_link_price_min"] = ""
        meta["virtual_edge_link_price_max"] = ""
        meta["virtual_edge_link_price_sample"] = ""
    data.routing_virtual_edge_meta = meta
    return meta


def load_p0_data(
    *,
    base_path: str,
    topology: str,
    num_tasks: int,
    k_paths: int,
    eta: float | None,
    joint_demand_scale: float | None,
    routing_mode: str,
    s2_derate: float,
    s1_link_k: int,
    s1_sigma: float,
    umcf_access_sigma: float = 0.99,
    umcf_sink_access_sigma: float | None = None,
    quiet: bool = False,
):
    from b4_joint_data import load_joint_data
    import io
    import contextlib

    use_explicit_scale = joint_demand_scale is not None
    if not quiet:
        print(
            f"  load | {topology} | routing={routing_mode} | |I|={num_tasks} | "
            f"η={'off' if use_explicit_scale else eta} | s1_σ={s1_sigma} | s2={s2_derate}"
        )
    ctx = contextlib.redirect_stdout(io.StringIO()) if quiet else contextlib.nullcontext()
    umcf_vn = routing_mode == "umcf_global"
    with ctx:
        data = load_joint_data(
            base_path=base_path,
            topology_name=topology,
            num_tasks=num_tasks,
            k_paths=k_paths,
            demand_scale=joint_demand_scale if use_explicit_scale else 1.0,
            demand_scale_explicit=use_explicit_scale,
            eta=None if use_explicit_scale else eta,
            routing_mode=routing_mode,
            umcf_virtual_nodes=umcf_vn,
            umcf_access_sigma=umcf_access_sigma,
            umcf_sink_access_sigma=umcf_sink_access_sigma,
            stress_zero_s1=False,
            scenario_s2_derate=s2_derate,
            scenario_s1_link_k=s1_link_k,
            scenario_s1_link_sigma=s1_sigma,
        )
    data.umcf_access_sigma = float(umcf_access_sigma)
    data.umcf_sink_access_sigma = umcf_sink_access_sigma
    collect_virtual_edge_metadata(data)
    return data


def run_model_a_diagnostic(
    data,
    *,
    min_off_hub: int,
    time_limit: int,
    mip_gap: float,
) -> dict:
    from teavar_framework_models import build_teavar_model_a

    t0 = time.perf_counter()
    ma, cost, lva, sva, y, xin, xout, din, dout = build_teavar_model_a(
        data,
        lambda_sla=5.0,
        lambda_sf=1.0,
        omega_deliver=1.0,
        min_tasks_off_hub=min_off_hub,
        time_limit=float(time_limit),
        mip_gap=float(mip_gap),
    )
    obj = ma.ObjVal if _has_solution(ma) else None
    exp_del = _exp_deliver_value(data, ma, din, dout)
    return {
        "model_a_status": _status_name(ma.status),
        "model_a_objective": obj,
        "model_a_cost": cost,
        "model_a_cvar_sla": lva,
        "model_a_cvar_sf": sva,
        "model_a_exp_deliver": exp_del,
        "model_a_feasible": _has_solution(ma),
        "model_a_elapsed_sec": time.perf_counter() - t0,
    }


def run_loose_model_c_diagnostic(
    data,
    *,
    min_off_hub: int,
    time_limit: int,
    mip_gap: float,
    gamma_sla: float = LOOSE_GAMMA_SLA,
    gamma_sf: float = LOOSE_GAMMA_SF,
) -> dict:
    from teavar_framework_models import build_teavar_model_c

    t0 = time.perf_counter()
    mc, cost, lvc, svc, y, xin, xout, din, dout = build_teavar_model_c(
        data,
        gamma_sla=gamma_sla,
        gamma_sf=gamma_sf,
        omega_deliver=1.0,
        include_sf_budget=True,
        min_tasks_off_hub=min_off_hub,
        time_limit=float(time_limit),
        mip_gap=float(mip_gap),
    )
    obj = mc.ObjVal if _has_solution(mc) else None
    exp_del = _exp_deliver_value(data, mc, din, dout)
    return {
        "loose_model_c_status": _status_name(mc.status),
        "loose_gamma_sla": gamma_sla,
        "loose_gamma_sf": gamma_sf,
        "loose_model_c_objective": obj,
        "loose_model_c_cost": cost,
        "loose_model_c_cvar_sla": lvc,
        "loose_model_c_cvar_sf": svc,
        "loose_model_c_exp_deliver": exp_del,
        "loose_model_c_feasible": _has_solution(mc),
        "loose_model_c_elapsed_sec": time.perf_counter() - t0,
    }


def _compute_assignment_feasible(data, min_off_hub: int) -> bool:
    """是否存在满足 C_normal 的一任务一节点 placement（与 Model A 算力约束同型）。"""
    import gurobipy as gp
    from gurobipy import GRB

    hub = int(getattr(data, "hub", 0))
    m = gp.Model("assign_check")
    m.Params.OutputFlag = 0
    y = m.addVars(
        [(i, node) for i in data.I for node in data.M if (i, node) in data.valid_assign],
        vtype=GRB.BINARY,
    )
    m.addConstrs(
        (gp.quicksum(y[i, node] for node in data.M if (i, node) in y) == 1 for i in data.I)
    )
    if min_off_hub > 0:
        m.addConstr(
            gp.quicksum(y[i, hub] for i in data.I if (i, hub) in y)
            <= len(data.I) - min_off_hub,
            name="min_off_hub",
        )
    for node in data.M:
        for k in data.K:
            m.addConstr(
                gp.quicksum(y[i, node] * data.w[i][k] for i in data.I if (i, node) in y)
                <= data.C_normal[node][k]
            )
    m.optimize()
    return m.SolCount > 0


def guess_infeasibility_reason(
    diag: dict,
    *,
    data,
    min_off_hub: int,
    s2_derate: float,
    eta: float,
) -> str:
    if not diag.get("model_a_feasible"):
        parts = ["base_infeasible:Model_A"]
        if not _compute_assignment_feasible(data, min_off_hub):
            parts.append("compute_assignment_infeasible")
        if min_off_hub >= 2:
            parts.append("min_off_hub_restrictive")
        if s2_derate <= 0.45:
            parts.append("s2_derate_harsh")
        if eta >= 1.29:
            parts.append("eta_high")
        return ";".join(parts)
    if not diag.get("loose_model_c_feasible"):
        return "base_infeasible:loose_Model_C_despite_A_ok"
    return "feasible_base_ok"


def run_feasibility_diagnostic(
    data,
    args,
    *,
    min_off_hub: int | None = None,
) -> dict:
    moh = min_off_hub if min_off_hub is not None else args.min_off_hub
    row = {
        "num_tasks": args.num_tasks,
        "eta": args.joint_demand_scale if args.joint_demand_scale is not None else args.eta,
        "s2_derate": args.s2_derate,
        "min_off_hub": moh,
        "scenario_s1_link_sigma": args.s1_sigma,
        "routing_mode": args.routing_mode,
    }
    print("  [diag] Model A ...", flush=True)
    row.update(
        run_model_a_diagnostic(
            data,
            min_off_hub=moh,
            time_limit=args.time_limit,
            mip_gap=args.mip_gap,
        )
    )
    print(
        f"       A: status={row['model_a_status']} SLA={row['model_a_cvar_sla']} "
        f"sf={row['model_a_cvar_sf']}",
        flush=True,
    )
    print(
        f"  [diag] loose Model C Γ=({LOOSE_GAMMA_SLA},{LOOSE_GAMMA_SF}) ...",
        flush=True,
    )
    row.update(
        run_loose_model_c_diagnostic(
            data,
            min_off_hub=moh,
            time_limit=args.time_limit,
            mip_gap=args.mip_gap,
        )
    )
    print(f"       C_loose: status={row['loose_model_c_status']}", flush=True)
    row["compute_assignment_feasible"] = _compute_assignment_feasible(data, moh)
    row["reason_guess"] = guess_infeasibility_reason(
        row,
        data=data,
        min_off_hub=moh,
        s2_derate=args.s2_derate,
        eta=float(row["eta"]),
    )
    return row


def _default_gamma_grid(data, grid_size: int) -> tuple[list[float], list[float]]:
    from teavar_framework_models import build_teavar_model_a

    print("  [gamma] calibrating from Model A (λ_sla=5, λ_sf=1)...")
    ma, ca, lva, sva, *_ = build_teavar_model_a(
        data, lambda_sla=5.0, lambda_sf=1.0, omega_deliver=1.0
    )
    if not _has_solution(ma) or lva is None:
        print(f"  [gamma] Model A status={ma.status}, using fallback grid")
        base_sla, base_sf = 0.15, 0.05
    else:
        base_sla = max(float(lva), 0.05)
        base_sf = max(float(sva or 0.0), 0.01)
        print(f"  [gamma] A* SLA={base_sla:.4f} sf={base_sf:.4f}")

    if grid_size <= 3:
        mult = [0.8, 1.0, 1.2]
    else:
        mult = [0.8, 1.0, 1.2, 1.5, 2.0][:grid_size]
    g_sla = [max(m * base_sla, 1e-4) for m in mult]
    g_sf = [max(m * base_sf + (0.01 if base_sf > 1e-12 else 0.0), 1e-4) for m in mult]
    return g_sla, g_sf


def _run_grid_point(
    data,
    gamma_sla: float,
    gamma_sf: float,
    *,
    time_limit: int,
    mip_gap: float,
    min_off_hub: int,
) -> dict:
    from teavar_framework_models import build_teavar_model_c

    t0 = time.perf_counter()
    try:
        m, cost, lvc, svc, y, xin, xout, din, dout = build_teavar_model_c(
            data,
            gamma_sla=gamma_sla,
            gamma_sf=gamma_sf,
            omega_deliver=1.0,
            include_sf_budget=True,
            min_tasks_off_hub=min_off_hub,
            time_limit=float(time_limit),
            mip_gap=float(mip_gap),
        )
        elapsed = time.perf_counter() - t0
        obj = m.ObjVal if _has_solution(m) else None
        exp_del = _exp_deliver_value(data, m, din, dout)
        return {
            "gamma_sla": gamma_sla,
            "gamma_sf": gamma_sf,
            "status": _status_name(m.status),
            "objective": obj,
            "cost": cost,
            "cvar_sla": lvc,
            "cvar_sf": svc,
            "exp_deliver": exp_del,
            "elapsed_sec": elapsed,
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "gamma_sla": gamma_sla,
            "gamma_sf": gamma_sf,
            "status": f"ERROR:{type(exc).__name__}",
            "objective": None,
            "cost": None,
            "cvar_sla": None,
            "cvar_sf": None,
            "exp_deliver": None,
            "elapsed_sec": time.perf_counter() - t0,
            "error": str(exc),
        }


def summarize_frontier_csv(csv_path: Path) -> dict:
    from scripts.p0_acceptance import _load_rows, _optimal_rows, _parse_float

    rows, colmap = _load_rows(csv_path)
    opt = _optimal_rows(rows, colmap)
    if not opt:
        return {"optimal_count": 0}
    slas = [p["cvar_sla"] for p in opt]
    sfs = [p["cvar_sf"] for p in opt]
    costs = [p["cost"] for p in opt]
    return {
        "optimal_count": len(opt),
        "sla_min": min(slas),
        "sla_max": max(slas),
        "sf_min": min(sfs),
        "sf_max": max(sfs),
        "cost_min": min(costs),
        "cost_max": max(costs),
    }


def run_frontier_grid(
    data,
    args,
    *,
    routing_mode: str,
    virtual_meta: dict | None = None,
) -> list[dict]:
    """跑 Γ 网格并返回行列表（不写文件）。"""
    g_sla, g_sf = _default_gamma_grid(data, args.grid_size)
    g_sla = _parse_gamma_list(args.gamma_sla_values, g_sla)
    g_sf = _parse_gamma_list(args.gamma_sf_values, g_sf)
    print(f"  Γ_sla={g_sla}")
    print(f"  Γ_sf={g_sf}")

    meta = virtual_meta or getattr(data, "routing_virtual_edge_meta", {})
    rows_out = []
    for gs in g_sla:
        for gf in g_sf:
            print(f"  → Model C Γ_sla={gs:.4f} Γ_sf={gf:.4f} ...", flush=True)
            row = _run_grid_point(
                data,
                gs,
                gf,
                time_limit=args.time_limit,
                mip_gap=args.mip_gap,
                min_off_hub=args.min_off_hub,
            )
            row["routing_mode"] = routing_mode
            row["eta"] = args.joint_demand_scale if args.joint_demand_scale is not None else args.eta
            row["scenario_s1_link_sigma"] = args.s1_sigma
            row["num_tasks"] = args.num_tasks
            row["min_off_hub"] = args.min_off_hub
            row["s2_derate"] = args.s2_derate
            row["umcf_access_sigma"] = meta.get("umcf_access_sigma", "")
            row["virtual_edge_count"] = meta.get("virtual_edge_count", 0)
            row["virtual_edge_price_policy"] = meta.get("virtual_edge_price_policy", "")
            row["virtual_edge_sigma_policy"] = meta.get("virtual_edge_sigma_policy", "")
            rows_out.append(row)
            print(
                f"     status={row['status']} cost={row.get('cost')} "
                f"SLA={row.get('cvar_sla')} sf={row.get('cvar_sf')}"
            )
    return rows_out


FRONTIER_FIELDNAMES = [
    "gamma_sla",
    "gamma_sf",
    "status",
    "objective",
    "cost",
    "cvar_sla",
    "cvar_sf",
    "exp_deliver",
    "elapsed_sec",
    "routing_mode",
    "eta",
    "scenario_s1_link_sigma",
    "num_tasks",
    "min_off_hub",
    "s2_derate",
    "umcf_access_sigma",
    "virtual_edge_count",
    "virtual_edge_price_policy",
    "virtual_edge_sigma_policy",
    "error",
]


def write_frontier_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FRONTIER_FIELDNAMES, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)


def _write_diag_csv(path: Path, row: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(row.keys()))
        w.writeheader()
        w.writerow(row)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="P0 Γ frontier (Model C, per-task OD)")
    ap.add_argument("--topology", default="B4")
    ap.add_argument("--base-path", default="./data")
    ap.add_argument(
        "--routing-mode",
        default="per_task_od",
        choices=("hub", "per_task_od", "umcf_global", "umcf_per_task"),
    )
    ap.add_argument(
        "--joint-umcf-per-task",
        action="store_true",
        help="等价于 --routing-mode umcf_per_task",
    )
    ap.add_argument(
        "--joint-umcf-teavar",
        action="store_true",
        help="等价于 --routing-mode umcf_global（全局 V_s,V_t）",
    )
    ap.add_argument(
        "--joint-umcf-sigma",
        type=float,
        default=0.99,
        dest="umcf_access_sigma",
        help="UMCF 虚拟边 (V_s,m) 可用率",
    )
    ap.add_argument(
        "--joint-umcf-sink-sigma",
        type=float,
        default=None,
        dest="umcf_sink_access_sigma",
        help="UMCF 边 (m,V_t) 可用率；默认与 --joint-umcf-sigma 相同",
    )
    ap.add_argument("--num-tasks", type=int, default=12)
    ap.add_argument("--k-paths", type=int, default=4)
    ap.add_argument("--eta", type=float, default=1.3)
    ap.add_argument("--joint-demand-scale", type=float, default=None, help="显式覆盖 η 标定")
    ap.add_argument("--s1-sigma", type=float, default=0.80, dest="s1_sigma")
    ap.add_argument("--s1-link-k", type=int, default=4)
    ap.add_argument("--s2-derate", type=float, default=0.40)
    ap.add_argument("--min-off-hub", type=int, default=2)
    ap.add_argument("--grid-size", type=int, default=3, choices=(3, 5))
    ap.add_argument("--gamma-sla-values", type=str, default=None)
    ap.add_argument("--gamma-sf-values", type=str, default=None)
    ap.add_argument("--time-limit", type=int, default=120, help="每网格点 Gurobi 秒数上限")
    ap.add_argument("--mip-gap", type=float, default=0.02)
    ap.add_argument("--output", type=str, default="results/p0_gamma_frontier.csv")
    ap.add_argument("--check", action="store_true", help="跑完后调用 p0_acceptance")
    ap.add_argument(
        "--diagnose-feasibility",
        action="store_true",
        help="仅跑 Model A + 极宽 Γ Model C 可行性诊断",
    )
    ap.add_argument(
        "--diag-output",
        type=str,
        default="results/p0_feasibility_diag.csv",
        help="--diagnose-feasibility 输出 CSV",
    )
    args = ap.parse_args(argv)

    if args.joint_umcf_per_task and args.joint_umcf_teavar:
        ap.error("--joint-umcf-per-task 与 --joint-umcf-teavar 互斥")
    routing_mode = resolve_routing_mode(args)
    args.routing_mode = routing_mode

    print(
        f"P0 frontier | {args.topology} | routing={routing_mode} | |I|={args.num_tasks} | "
        f"min_off_hub={args.min_off_hub}"
    )
    data = load_p0_data(
        base_path=args.base_path,
        topology=args.topology,
        num_tasks=args.num_tasks,
        k_paths=args.k_paths,
        eta=args.eta,
        joint_demand_scale=args.joint_demand_scale,
        routing_mode=routing_mode,
        s2_derate=args.s2_derate,
        s1_link_k=args.s1_link_k,
        s1_sigma=args.s1_sigma,
        umcf_access_sigma=args.umcf_access_sigma,
        umcf_sink_access_sigma=args.umcf_sink_access_sigma,
    )

    if args.diagnose_feasibility:
        diag = run_feasibility_diagnostic(data, args)
        diag_path = Path(args.diag_output)
        _write_diag_csv(diag_path, diag)
        print(f"Wrote {diag_path}")
        print(f"reason_guess: {diag['reason_guess']}")
        return 0 if diag.get("loose_model_c_feasible") else 1

    virtual_meta = collect_virtual_edge_metadata(data)
    rows_out = run_frontier_grid(
        data, args, routing_mode=routing_mode, virtual_meta=virtual_meta
    )
    out_path = Path(args.output)
    write_frontier_csv(out_path, rows_out)
    print(f"Wrote {out_path} ({len(rows_out)} points)")

    summ = summarize_frontier_csv(out_path)
    if summ.get("optimal_count", 0) > 0:
        print(
            f"Summary: optimal={summ['optimal_count']} | "
            f"SLA∈[{summ['sla_min']:.4f},{summ['sla_max']:.4f}] | "
            f"sf∈[{summ['sf_min']:.4f},{summ['sf_max']:.4f}] | "
            f"cost∈[{summ['cost_min']:.2f},{summ['cost_max']:.2f}]"
        )

    if args.check:
        from scripts.p0_acceptance import run_acceptance

        return run_acceptance(out_path)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
