# -*- coding: utf-8 -*-
"""
生成实验对比 CSV 表与 PNG 图（玩具 + B4），对应「Physical vs SLA / λ_sf / UMCF / joint 折中 / 应力可行」叙事。

用法（在项目根目录、已激活 Gurobi 环境）:
    python experiment_report.py
    python experiment_report.py --out output/experiment_report

输出:
    table_a_toy_physical_vs_sla.csv
    table_b_toy_teavar_lambda_sf.csv
    table_c_toy_umcf_vs_hub.csv
    table_d_b4_baseline.csv
    table_e_b4_stress_feasibility.csv
    fig_toy_physical_scan.png
    fig_toy_teavar_lambda_sf.png
    fig_toy_umcf_physical_link_cvar.png
    fig_b4_joint_tradeoff.png
    fig_b4_stress_feasibility.png
"""
from __future__ import annotations

import argparse
import csv
import os
import sys
from pathlib import Path

# 保证从任意 cwd 调用时仍能加载数据与本地模块
ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from gurobipy import GRB


def _out_dir() -> Path:
    p = ROOT / "output" / "experiment_report"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _placement_str(data, y) -> str:
    if y is None:
        return ""
    dist: dict[int, int] = {}
    for i in data.I:
        for n in data.M:
            if (i, n) in y and y[i, n].X > 0.5:
                dist[n] = dist.get(n, 0) + 1
    return ", ".join(f"{k}:{v}" for k, v in sorted(dist.items()))


def _write_csv(path: Path, fieldnames: list[str], rows: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def _make_toy(umcf: bool = False):
    from duibi import UltraComplexData
    from b4_joint_data import attach_umcf_to_data_object

    data = UltraComplexData()
    if umcf:
        attach_umcf_to_data_object(data, 0.99, None)
    return data


def _make_b4(
    *,
    k_paths: int = 4,
    stress: bool = False,
    umcf: bool = False,
):
    from b4_joint_data import load_b4_joint_data

    return load_b4_joint_data(
        base_path=str(ROOT / "data"),
        topology_name="B4",
        hub_index=0,
        num_tasks=10,
        demand_row=0,
        demand_downscale=2.0,
        demand_scale=1.0,
        k_paths=k_paths,
        stress_zero_s1=stress,
        virtual_source=False,
        umcf_virtual_nodes=umcf,
        umcf_access_sigma=0.99,
        umcf_sink_access_sigma=None,
    )


def table_a_toy(out: Path) -> None:
    """玩具：同一拓扑下 Physical Model A 扫描 vs TEAVAR-A（固定 λ_sla/λ_sf）。"""
    from duibi import UltraComplexData, build_single_layer_model
    from teavar_framework_models import build_teavar_model_a

    data = UltraComplexData()
    lambdas = [0.5, 5.0, 50.0, 500.0, 5000.0]
    rows = []
    for lam in lambdas:
        m, cost, nc, lc, y, *_ = build_single_layer_model(data, lam)
        rows.append(
            {
                "block": "physical_model_A",
                "lambda_physical": lam,
                "status": m.status,
                "optimal": int(m.status == GRB.OPTIMAL),
                "cost": f"{cost:.6f}" if cost is not None else "",
                "node_cvar": f"{nc:.6f}" if nc is not None else "",
                "link_cvar": f"{lc:.6f}" if lc is not None else "",
                "placement": _placement_str(data, y) if m.status == GRB.OPTIMAL else "",
                "lambda_sla": "",
                "lambda_sf": "",
                "CVaR_SLA": "",
                "CVaR_sf": "",
            }
        )
    lam_sla, lam_sf, omega = 0.5, 0.5, 1.0
    m, c, lta, sta, y, *_ = build_teavar_model_a(data, lam_sla, lam_sf, omega_deliver=omega)
    rows.append(
        {
            "block": "TEAVAR_A",
            "lambda_physical": "",
            "status": m.status,
            "optimal": int(m.status == GRB.OPTIMAL),
            "cost": f"{c:.6f}" if c is not None else "",
            "node_cvar": "",
            "link_cvar": "",
            "placement": _placement_str(data, y) if m.status == GRB.OPTIMAL else "",
            "lambda_sla": lam_sla,
            "lambda_sf": lam_sf,
            "CVaR_SLA": f"{lta:.6f}" if lta is not None else "",
            "CVaR_sf": f"{sta:.6f}" if sta is not None else "",
        }
    )
    fn = [
        "block",
        "lambda_physical",
        "lambda_sla",
        "lambda_sf",
        "status",
        "optimal",
        "cost",
        "node_cvar",
        "link_cvar",
        "CVaR_SLA",
        "CVaR_sf",
        "placement",
    ]
    _write_csv(out / "table_a_toy_physical_vs_sla.csv", fn, rows)


def table_b_toy_teavar_lambda_sf(out: Path) -> None:
    from duibi import UltraComplexData
    from teavar_framework_models import build_teavar_model_a

    data = UltraComplexData()
    lam_sla = 0.5
    omega = 1.0
    sf_list = [0.0, 0.5, 2.0, 10.0, 50.0, 200.0, 2000.0, 5000.0]
    rows = []
    for lam_sf in sf_list:
        m, c, lta, sta, y, *_ = build_teavar_model_a(data, lam_sla, lam_sf, omega_deliver=omega)
        rows.append(
            {
                "lambda_sla": lam_sla,
                "lambda_sf": lam_sf,
                "omega": omega,
                "status": m.status,
                "optimal": int(m.status == GRB.OPTIMAL),
                "cost": f"{c:.6f}" if c is not None else "",
                "CVaR_SLA": f"{lta:.6f}" if lta is not None else "",
                "CVaR_sf": f"{sta:.6f}" if sta is not None else "",
                "placement": _placement_str(data, y) if m.status == GRB.OPTIMAL else "",
            }
        )
    fn = list(rows[0].keys()) if rows else []
    _write_csv(out / "table_b_toy_teavar_lambda_sf.csv", fn, rows)


def table_c_toy_umcf(out: Path) -> None:
    from duibi import build_single_layer_model
    from teavar_framework_models import build_teavar_model_a

    lam_phys = 50.0
    lam_sla, lam_sf, omega = 0.5, 0.5, 1.0
    rows = []
    for umcf, label in [(False, "hub_radial"), (True, "UMCF")]:
        data = _make_toy(umcf=umcf)
        m, cost, nc, lc, y, *_ = build_single_layer_model(data, lam_phys)
        rows.append(
            {
                "mode": label,
                "umcf": int(umcf),
                "lambda_physical": lam_phys,
                "phys_status": m.status,
                "phys_optimal": int(m.status == GRB.OPTIMAL),
                "phys_cost": f"{cost:.6f}" if cost is not None else "",
                "phys_node_cvar": f"{nc:.6f}" if nc is not None else "",
                "phys_link_cvar": f"{lc:.6f}" if lc is not None else "",
                "phys_placement": _placement_str(data, y) if m.status == GRB.OPTIMAL else "",
            }
        )
        mt, ct, lta, sta, yt, *_ = build_teavar_model_a(data, lam_sla, lam_sf, omega_deliver=omega)
        rows[-1].update(
            {
                "teavar_status": mt.status,
                "teavar_optimal": int(mt.status == GRB.OPTIMAL),
                "teavar_cost": f"{ct:.6f}" if ct is not None else "",
                "CVaR_SLA": f"{lta:.6f}" if lta is not None else "",
                "CVaR_sf": f"{sta:.6f}" if sta is not None else "",
                "teavar_placement": _placement_str(data, yt) if mt.status == GRB.OPTIMAL else "",
            }
        )
    fn = list(rows[0].keys())
    _write_csv(out / "table_c_toy_umcf_vs_hub.csv", fn, rows)


def table_d_b4_baseline(out: Path, k_paths: int) -> None:
    from duibi import build_single_layer_model
    from teavar_framework_models import build_teavar_model_a
    from cvar_compare import build_teavar_sla_cvar_model
    from duibi_metrics import expected_total_delivered_volume

    data = _make_b4(k_paths=k_paths, stress=False, umcf=False)
    lambdas = [0.5, 5.0, 50.0, 500.0]
    omega = 1.0
    lam_n = 0.5
    lam_sf_joint = 0.0
    rows = []
    for lam in lambdas:
        m, cost, nc, lc, y, *_ = build_single_layer_model(data, lam)
        rows.append(
            {
                "dataset": "B4",
                "k_paths": k_paths,
                "stress": 0,
                "umcf": 0,
                "block": "physical_A",
                "lambda": lam,
                "status": m.status,
                "optimal": int(m.status == GRB.OPTIMAL),
                "cost": f"{cost:.6f}" if cost is not None else "",
                "node_cvar": f"{nc:.6f}" if nc is not None else "",
                "link_cvar": f"{lc:.6f}" if lc is not None else "",
                "SLA_CVaR": "",
                "nodeUtil_CVaR": "",
                "computeSf_CVaR": "",
                "E_del_vol": "",
                "obj_full_teavar": "",
                "placement": _placement_str(data, y) if m.status == GRB.OPTIMAL else "",
            }
        )
        mt, ct, ltv, ntv, sfv, yt, _xin, _xout, din, dout = build_teavar_sla_cvar_model(
            data,
            lambda_cvar=lam,
            omega_deliver=omega,
            min_tasks_off_node0=0,
            lambda_node_cvar=lam_n,
            lambda_compute_sf_cvar=lam_sf_joint,
        )
        ev = 0.0
        if mt.status == GRB.OPTIMAL:
            ev = expected_total_delivered_volume(data, mt, din, dout) or 0.0
        obj_full = None
        if ct is not None and ltv is not None:
            obj_full = ct + lam * ltv + lam_n * (ntv or 0.0) + lam_sf_joint * (sfv or 0.0) - omega * ev
        rows.append(
            {
                "dataset": "B4",
                "k_paths": k_paths,
                "stress": 0,
                "umcf": 0,
                "block": "teavar_sla_joint_style",
                "lambda": lam,
                "status": mt.status,
                "optimal": int(mt.status == GRB.OPTIMAL),
                "cost": f"{ct:.6f}" if ct is not None else "",
                "node_cvar": "",
                "link_cvar": "",
                "SLA_CVaR": f"{ltv:.6f}" if ltv is not None else "",
                "nodeUtil_CVaR": f"{(ntv or 0.0):.6f}",
                "computeSf_CVaR": f"{(sfv or 0.0):.6f}",
                "E_del_vol": f"{ev:.6f}",
                "obj_full_teavar": f"{obj_full:.6f}" if obj_full is not None else "",
                "placement": _placement_str(data, yt) if mt.status == GRB.OPTIMAL else "",
            }
        )
    lam_sla, lam_sf = 0.5, 0.5
    m, c, lta, sta, y, *_ = build_teavar_model_a(data, lam_sla, lam_sf, omega_deliver=omega)
    rows.append(
        {
            "dataset": "B4",
            "k_paths": k_paths,
            "stress": 0,
            "umcf": 0,
            "block": "TEAVAR_A_duibi",
            "lambda": "",
            "status": m.status,
            "optimal": int(m.status == GRB.OPTIMAL),
            "cost": f"{c:.6f}" if c is not None else "",
            "node_cvar": "",
            "link_cvar": "",
            "SLA_CVaR": f"{lta:.6f}" if lta is not None else "",
            "nodeUtil_CVaR": "",
            "computeSf_CVaR": f"{sta:.6f}" if sta is not None else "",
            "E_del_vol": "",
            "obj_full_teavar": "",
            "placement": _placement_str(data, y) if m.status == GRB.OPTIMAL else "",
        }
    )
    fn = list(rows[0].keys())
    _write_csv(out / "table_d_b4_baseline.csv", fn, rows)


def table_e_b4_stress(out: Path, k_paths: int) -> None:
    from duibi import build_single_layer_model
    from teavar_framework_models import build_teavar_model_a

    scenarios = [
        ("baseline_no_stress", False, False),
        ("stress_no_umcf", True, False),
        ("stress_umcf", True, True),
    ]
    lam_phys = 50.0
    lam_sla, lam_sf, omega = 0.5, 0.5, 1.0
    rows = []
    for name, stress, umcf in scenarios:
        data = _make_b4(k_paths=k_paths, stress=stress, umcf=umcf)
        mp, cp, nc, lc, yp, *_ = build_single_layer_model(data, lam_phys)
        mt, ct, lta, sta, yt, *_ = build_teavar_model_a(data, lam_sla, lam_sf, omega_deliver=omega)
        rows.append(
            {
                "scenario": name,
                "stress": int(stress),
                "umcf": int(umcf),
                "k_paths": k_paths,
                "lambda_physical": lam_phys,
                "physical_A_status": mp.status,
                "physical_A_optimal": int(mp.status == GRB.OPTIMAL),
                "physical_cost": f"{cp:.6f}" if cp is not None else "",
                "TEAVAR_A_status": mt.status,
                "TEAVAR_A_optimal": int(mt.status == GRB.OPTIMAL),
                "TEAVAR_cost": f"{ct:.6f}" if ct is not None else "",
                "CVaR_SLA": f"{lta:.6f}" if lta is not None else "",
                "CVaR_sf": f"{sta:.6f}" if sta is not None else "",
                "placement_phys": _placement_str(data, yp) if mp.status == GRB.OPTIMAL else "",
                "placement_teavar": _placement_str(data, yt) if mt.status == GRB.OPTIMAL else "",
            }
        )
    fn = list(rows[0].keys())
    _write_csv(out / "table_e_b4_stress_feasibility.csv", fn, rows)


def fig_toy_physical_scan(out: Path) -> None:
    from duibi import UltraComplexData, build_single_layer_model

    data = UltraComplexData()
    lambdas = np.array([0.5, 5.0, 50.0, 500.0, 5000.0, 50000.0])
    costs, ncs, lcs = [], [], []
    for lam in lambdas:
        m, c, nc, lc, *_y = build_single_layer_model(data, float(lam))
        costs.append(c if m.status == GRB.OPTIMAL else np.nan)
        ncs.append(nc if m.status == GRB.OPTIMAL else np.nan)
        lcs.append(lc if m.status == GRB.OPTIMAL else np.nan)

    fig, ax1 = plt.subplots(figsize=(8, 4.5))
    ax1.set_xscale("log")
    ax1.plot(lambdas, costs, "o-", color="tab:blue", label="总成本")
    ax1.set_xlabel("λ (Physical Model A)")
    ax1.set_ylabel("总成本", color="tab:blue")
    ax1.tick_params(axis="y", labelcolor="tab:blue")

    ax2 = ax1.twinx()
    ax2.plot(lambdas, ncs, "s--", color="tab:orange", label="算力 CVaR")
    ax2.plot(lambdas, lcs, "^--", color="tab:green", label="链路 CVaR")
    ax2.set_ylabel("CVaR", color="tab:gray")
    ax2.tick_params(axis="y", labelcolor="tab:gray")

    lines1, lab1 = ax1.get_legend_handles_labels()
    lines2, lab2 = ax2.get_legend_handles_labels()
    ax1.legend(lines1 + lines2, lab1 + lab2, loc="center left", bbox_to_anchor=(1.15, 0.5))
    ax1.set_title("玩具数据集 · Physical Model A：λ 扫描")
    fig.tight_layout()
    fig.savefig(out / "fig_toy_physical_scan.png", dpi=150)
    plt.close(fig)


def fig_toy_teavar_lambda_sf(out: Path) -> None:
    from duibi import UltraComplexData
    from teavar_framework_models import build_teavar_model_a

    data = UltraComplexData()
    lam_sla = 0.5
    omega = 1.0
    sf_list = [0.0, 0.5, 2.0, 10.0, 50.0, 200.0, 1000.0, 5000.0]
    costs, sla, sfv = [], [], []
    for lam_sf in sf_list:
        m, c, lta, sta, *_ = build_teavar_model_a(data, lam_sla, lam_sf, omega_deliver=omega)
        costs.append(c if m.status == GRB.OPTIMAL else np.nan)
        sla.append(lta if m.status == GRB.OPTIMAL else np.nan)
        sfv.append(sta if m.status == GRB.OPTIMAL else np.nan)

    fig, axes = plt.subplots(1, 2, figsize=(10, 4))
    axes[0].semilogx(sf_list, costs, "o-", color="tab:blue")
    axes[0].set_xlabel("λ_sf (--teavar-lambda-sf)")
    axes[0].set_ylabel("总成本")
    axes[0].set_title("TEAVAR-A（玩具）")
    axes[1].semilogx(sf_list, sla, "o-", label="CVaR_SLA", color="tab:orange")
    axes[1].semilogx(sf_list, sfv, "s-", label="CVaR_sf", color="tab:green")
    axes[1].set_xlabel("λ_sf")
    axes[1].set_ylabel("CVaR")
    axes[1].legend()
    axes[1].set_title("SLA / 算力未满足 CVaR")
    fig.suptitle(f"玩具 · TEAVAR-A · λ_sla={lam_sla} · ω={omega}")
    fig.tight_layout()
    fig.savefig(out / "fig_toy_teavar_lambda_sf.png", dpi=150)
    plt.close(fig)


def fig_toy_umcf_physical_link_cvar(out: Path) -> None:
    from duibi import build_single_layer_model

    lam = 50.0
    labels, link_cv = [], []
    for umcf, lab in [(False, "Hub 径向"), (True, "UMCF")]:
        data = _make_toy(umcf=umcf)
        m, _c, _nc, lc, *_ = build_single_layer_model(data, lam)
        labels.append(lab)
        link_cv.append(lc if m.status == GRB.OPTIMAL else 0.0)

    fig, ax = plt.subplots(figsize=(5, 4))
    x = np.arange(len(labels))
    ax.bar(x, link_cv, color=["#4C72B0", "#55A868"])
    ax.set_xticks(x)
    ax.set_xticklabels(labels)
    ax.set_ylabel("链路 CVaR (Physical A, λ=50)")
    ax.set_title("玩具：UMCF 对 Physical 链路 CVaR 的影响（示意）")
    fig.tight_layout()
    fig.savefig(out / "fig_toy_umcf_physical_link_cvar.png", dpi=150)
    plt.close(fig)


def fig_b4_joint_tradeoff(out: Path, k_paths: int) -> None:
    from cvar_compare import build_teavar_sla_cvar_model
    from duibi_metrics import expected_total_delivered_volume

    data = _make_b4(k_paths=k_paths, stress=False, umcf=False)
    lambdas = [0.5, 2.0, 5.0, 10.0, 50.0, 100.0]
    omega = 1.0
    lam_n = 0.5
    lam_sf = 0.0
    costs, slas = [], []
    for lam in lambdas:
        mt, ct, ltv, ntv, sfv, _y, _xin, _xout, din, dout = build_teavar_sla_cvar_model(
            data,
            lambda_cvar=lam,
            omega_deliver=omega,
            min_tasks_off_node0=0,
            lambda_node_cvar=lam_n,
            lambda_compute_sf_cvar=lam_sf,
        )
        if mt.status != GRB.OPTIMAL or ct is None:
            costs.append(np.nan)
            slas.append(np.nan)
            continue
        costs.append(ct)
        slas.append(ltv)

    fig, ax = plt.subplots(figsize=(6.5, 5))
    sc = ax.scatter(slas, costs, c=lambdas, cmap="viridis", s=80, edgecolors="k")
    for i, lam in enumerate(lambdas):
        if not np.isnan(slas[i]):
            ax.annotate(f"λ={lam}", (slas[i], costs[i]), textcoords="offset points", xytext=(4, 4), fontsize=8)
    cb = fig.colorbar(sc, ax=ax)
    cb.set_label("λ (SLA CVaR 权重)")
    ax.set_xlabel("SLA CVaR")
    ax.set_ylabel("总成本 cost")
    ax.set_title(f"B4 · teavar_sla 折中（k_paths={k_paths}, λn={lam_n}, ω={omega}）")
    fig.tight_layout()
    fig.savefig(out / "fig_b4_joint_tradeoff.png", dpi=150)
    plt.close(fig)


def fig_b4_stress_feasibility(out: Path, k_paths: int) -> None:
    from duibi import build_single_layer_model
    from teavar_framework_models import build_teavar_model_a

    labels = ["无应力", "应力\n无UMCF", "应力\n+UMCF"]
    stress_flags = [False, True, True]
    umcf_flags = [False, False, True]
    phys_ok, te_ok = [], []
    lam_phys, lam_sla, lam_sf, omega = 50.0, 0.5, 0.5, 1.0
    for stress, umcf in zip(stress_flags, umcf_flags):
        data = _make_b4(k_paths=k_paths, stress=stress, umcf=umcf)
        mp, *_ = build_single_layer_model(data, lam_phys)
        mt, *_ = build_teavar_model_a(data, lam_sla, lam_sf, omega_deliver=omega)
        phys_ok.append(1 if mp.status == GRB.OPTIMAL else 0)
        te_ok.append(1 if mt.status == GRB.OPTIMAL else 0)

    x = np.arange(len(labels))
    w = 0.35
    fig, ax = plt.subplots(figsize=(7, 4.5))
    ax.bar(x - w / 2, phys_ok, width=w, label="Physical A 可行 (1/0)", color="#4C72B0")
    ax.bar(x + w / 2, te_ok, width=w, label="TEAVAR-A 可行 (1/0)", color="#C44E52")
    ax.set_xticks(x)
    ax.set_xticklabels(labels)
    ax.set_ylim(0, 1.25)
    ax.set_ylabel("可行指示")
    ax.legend()
    ax.set_title(f"B4 · 应力下可行性（Physical λ={lam_phys}, TEAVAR λ_sla={lam_sla}, λ_sf={lam_sf}）")
    fig.tight_layout()
    fig.savefig(out / "fig_b4_stress_feasibility.png", dpi=150)
    plt.close(fig)


def main() -> None:
    ap = argparse.ArgumentParser(description="生成实验 CSV 与 PNG")
    ap.add_argument(
        "--out",
        type=str,
        default=str(ROOT / "output" / "experiment_report"),
        help="输出目录",
    )
    ap.add_argument(
        "--k-paths",
        type=int,
        default=4,
        help="B4 load_b4_joint_data 的 k_paths（与 main.py --joint-k-paths 默认 4 对齐）",
    )
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    meta = {
        "note": "Physical 与 SLA/TEAVAR 为不同目标；Model D 事后 CVaR 不宜与 A 直接比数值。",
        "k_paths_B4": args.k_paths,
        "cwd": str(ROOT),
    }
    with (out / "README_run_meta.txt").open("w", encoding="utf-8") as f:
        for k, v in meta.items():
            f.write(f"{k}: {v}\n")

    print("写入 CSV …")
    table_a_toy(out)
    table_b_toy_teavar_lambda_sf(out)
    table_c_toy_umcf(out)
    table_d_b4_baseline(out, k_paths=args.k_paths)
    table_e_b4_stress(out, k_paths=args.k_paths)

    print("绘制 PNG …")
    fig_toy_physical_scan(out)
    fig_toy_teavar_lambda_sf(out)
    fig_toy_umcf_physical_link_cvar(out)
    fig_b4_joint_tradeoff(out, k_paths=args.k_paths)
    fig_b4_stress_feasibility(out, k_paths=args.k_paths)

    print(f"完成。输出目录: {out.resolve()}")


if __name__ == "__main__":
    main()
